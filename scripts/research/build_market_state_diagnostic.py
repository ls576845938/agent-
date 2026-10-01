"""Build one bounded, read-only market-state diagnostic from sealed evidence.

No replay, training, strategy evaluation, account access or network call occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.app.services.donchian_stage_views import validate_stage_snapshot
from quant_shared.trend_environment import Bar
from quant_shared.trend_environment.diagnostics import build_stage_diagnostic
from quant_shared.trend_environment.state_v2 import (
    CausalStateStreamV2,
    StateDefinitionV2,
    StateSourceBinding,
)
from quant_shared.trend_environment.model import digest
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    load_manifest_from_git,
    resolve_manifest_payload,
)


PROTOCOL = "docs/research/market-state-conditional-policy-protocol-20260927.json"
PROTOCOL_COMMIT = "97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02"
STAGE = ".agent/offline_evidence/donchian-stage-20260921.json"
OUTPUT = ".agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json"
SAFETY = {key: False for key in (
    "demo_control_enabled", "execution_permission", "runtime_observed", "promotion",
    "paper", "live", "private", "order", "real_order", "transfer", "withdraw",
)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_bytes(repo: Path, spec: str) -> bytes:
    return subprocess.run(["git", "show", spec], cwd=repo, check=True,
                          capture_output=True).stdout


def _load_frozen_protocol(repo: Path) -> tuple[bytes, dict]:
    raw = _git_bytes(repo, f"{PROTOCOL_COMMIT}:{PROTOCOL}")
    protocol = json.loads(raw)
    if (protocol.get("schema_version") != "market_state_conditional_policy_protocol_v1"
            or protocol.get("status") != "frozen_before_diagnostic"):
        raise ValueError("market_state_protocol_invalid")
    return raw, protocol


def build(repo: Path, *, shared_root: Path | None = None) -> dict:
    repo = repo.resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    protocol_raw, protocol = _load_frozen_protocol(repo)
    stage_raw = _git_bytes(repo, f"{head}:{STAGE}")
    stage = validate_stage_snapshot(json.loads(stage_raw), head)
    source = protocol["source"]
    if (stage["source_head"] != source["stage_source_head"]
            or stage["identity"]["manifest_git_spec"] != source["manifest_git_spec"]
            or stage["identity"]["manifest_sha256"] != source["manifest_sha256"]
            or stage["identity"]["aggregate_sha256"] != source["aggregate_sha256"]):
        raise ValueError("market_state_stage_protocol_binding_mismatch")
    manifest_raw = _git_bytes(repo, source["manifest_git_spec"])
    if _sha(manifest_raw) != source["manifest_sha256"]:
        raise ValueError("market_state_manifest_git_hash_mismatch")
    manifest = load_manifest_from_git(repo, source["manifest_git_spec"])
    if manifest.get("aggregate_sha256") != source["aggregate_sha256"]:
        raise ValueError("market_state_manifest_aggregate_mismatch")
    physical = resolve_manifest_payload(
        manifest,
        shared_root=(shared_root or default_shared_data_root(repo)).resolve(),
        verify_files=True,
    )
    frame = pd.read_parquet(physical / "history_input/daily_bars.parquet")
    required = {"event_time", "available_time", "decision_time", "symbol", "close", "confirm"}
    if not required.issubset(frame):
        raise ValueError("market_state_input_columns_missing")
    for name in ("event_time", "available_time", "decision_time"):
        frame[name] = pd.to_datetime(frame[name], utc=True, errors="raise")
    if frame.duplicated(["symbol", "event_time"]).any() or len(set(frame.symbol)) != 1:
        raise ValueError("market_state_input_identity_or_duplicate_invalid")
    one_hour = pd.Timedelta(hours=1)
    if not ((frame.available_time == frame.event_time + one_hour).all()
            and (frame.decision_time == frame.available_time).all()
            and (frame.confirm == 1).all()):
        raise ValueError("market_state_input_clock_contract_invalid")
    window = protocol["window"]
    warmup = pd.Timestamp(window["warmup_start_utc"])
    start = pd.Timestamp(window["analysis_start_utc"])
    end = pd.Timestamp(window["analysis_end_exclusive_utc"])
    selected = frame[(frame.event_time >= warmup) & (frame.event_time < end)].copy()
    analysis_mask = (selected.event_time >= start) & (selected.event_time < end)
    if analysis_mask.sum() != window["expected_analysis_bars"]:
        raise ValueError("market_state_analysis_bar_count_mismatch")
    state_contract = protocol["state_definition"]
    definition = StateDefinitionV2(
        horizons=tuple(state_contract["horizons"]),
        primary_horizon=state_contract["primary_horizon"],
        volatility_history_bars=state_contract["volatility_history_bars"],
        state_history_bars=state_contract["state_history_bars"],
        minimum_history_observations=state_contract["minimum_history_observations"],
        calendar=window["calendar"],
        periods_per_year=state_contract["periods_per_year"],
        max_age_seconds=state_contract["max_age_seconds"],
    )
    source_binding = StateSourceBinding(
        data_version=stage["identity"]["dataset_version"],
        manifest_git_spec=source["manifest_git_spec"],
        manifest_sha256=source["manifest_sha256"],
        aggregate_sha256=source["aggregate_sha256"],
        source_evidence_hash=_sha(stage_raw),
    )
    asset = str(selected.symbol.iloc[0])
    stream = CausalStateStreamV2(asset=asset, definition=definition, source=source_binding)
    states = []
    all_content_hashes = []
    reason_counts: Counter[str] = Counter()
    for row in selected.itertuples(index=False):
        event = row.event_time.to_pydatetime()
        available = row.available_time.to_pydatetime()
        observation = stream.push(
            Bar(asset, event, available, available, float(row.close), True),
            expected_close_time=available,
            decision_time=row.decision_time.to_pydatetime(),
        )
        if start <= row.event_time < end:
            value = observation.to_dict()
            value["event_time_utc"] = event.astimezone(timezone.utc).isoformat()
            states.append(value)
            all_content_hashes.append(value["content_hash"])
            reason_counts.update(value["reasons"])
    diagnostic = build_stage_diagnostic(stage, states)
    observed = sum(row["status"] == "observed" for row in states)
    unknown = len(states) - observed
    payload = {
        "schema_version": "market_state_stage_diagnostic_v1",
        "selector": stage["selector"],
        "status": "completed_exploratory_research_only",
        "truth_kind": "historical_market_state_diagnostic",
        "usage": "description_and_precommitted_entry_policy_design_only",
        "protocol": {
            "path": PROTOCOL,
            "sha256": _sha(protocol_raw),
            "commit": PROTOCOL_COMMIT,
            "protocol_id": protocol["protocol_id"],
        },
        "source": {
            "stage_snapshot": STAGE,
            "stage_snapshot_sha256": _sha(stage_raw),
            "stage_source_head": stage["source_head"],
            "publication_head_at_build": head,
            "manifest_git_spec": source["manifest_git_spec"],
            "manifest_sha256": source["manifest_sha256"],
            "aggregate_sha256": source["aggregate_sha256"],
            "data_version": stage["identity"]["dataset_version"],
            "physical_root_redacted": True,
        },
        "window": window,
        "clock_contract": {
            "event_time": "bar_open_utc",
            "available_time": "event_time_plus_1h",
            "decision_time": "available_time",
            "verified_for_all_selected_rows": True,
        },
        "description": {
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "source_binding_hash": source_binding.binding_hash,
            "series_content_hash": digest(all_content_hashes),
            "observed_bars": observed,
            "unknown_bars": unknown,
            "unknown_reason_counts": dict(sorted(reason_counts.items())),
            "optional_input_coverage": {
                "funding": "missing_from_state_input",
                "open_interest": "missing_from_state_input",
                "depth": "missing_from_state_input",
            },
        },
        "stratification": diagnostic,
        "sample_assessment": {
            "descriptive_grouping_available": True,
            "roundtrips": diagnostic["sample_units"]["roundtrips"],
            "promotion_or_policy_effect_claim_supported": False,
            "reason": "28_roundtrips_exploratory_only_and_no_policy_replay_ab",
        },
        "policy_trial": {
            "status": "not_started",
            "effect_verified": False,
            "counterfactual_entry_count_only": diagnostic["policy_counterfactual"]["would_reject_entries"],
            "budget": protocol["ab_budget_not_started"],
        },
        "runtime_status": {
            "entry_policy_enabled": False,
            "attachment_consumed_by_btc_runtime": False,
            "execution_effect_observed": False,
        },
        "limitations": [
            "historical_reconstructed_availability",
            "funding_not_allocatable_per_trade",
            "donchian_has_no_prediction_series_ic_not_applicable",
            "28_roundtrips_insufficient_for_promotion_claim",
            "policy_counterfactual_is_not_policy_replay",
            "stage_window_is_partial_not_annual",
        ],
        **SAFETY,
    }
    return {**payload, "evidence_hash": digest(payload)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--shared-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path(OUTPUT))
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    expected_parent = (repo / ".agent/market_state_evidence").resolve()
    if output.resolve().parent != expected_parent:
        raise ValueError("market_state_output_path_forbidden")
    if output.exists():
        raise FileExistsError("market_state_output_already_exists")
    payload = build(repo, shared_root=args.shared_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": payload["status"], "output": output.relative_to(repo).as_posix(),
                      "evidence_hash": payload["evidence_hash"],
                      "bars": payload["stratification"]["sample_units"]["bars"],
                      "roundtrips": payload["stratification"]["sample_units"]["roundtrips"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
