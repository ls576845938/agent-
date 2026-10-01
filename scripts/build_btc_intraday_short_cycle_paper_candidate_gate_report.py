#!/usr/bin/env python3
"""Build the BTC intraday short-cycle paper-candidate gate report.

This gate promotes a research candidate definition to manual paper review only.
It never starts paper trading, never unlocks live trading, and never claims true
scalping readiness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_CURRENT_STATUS = Path("artifacts/btc_current_status/latest/btc_current_status_report.json")
DEFAULT_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
DEFAULT_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_FUNDING_LEDGER = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
REPORT_FILENAME = "btc_intraday_short_cycle_paper_candidate_gate_report.json"


def build_btc_intraday_short_cycle_paper_candidate_gate_report(
    *,
    repo_root: Path | None = None,
    current_status_path: Path | None = None,
    data_status_path: Path | None = None,
    cost_model_path: Path | None = None,
    funding_ledger_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    current_file = _resolve(root, current_status_path or DEFAULT_CURRENT_STATUS)
    data_file = _resolve(root, data_status_path or DEFAULT_DATA_STATUS)
    cost_file = _resolve(root, cost_model_path or DEFAULT_COST_MODEL)
    funding_file = _resolve(root, funding_ledger_path or DEFAULT_FUNDING_LEDGER)
    current = _read_json(current_file)
    data = _read_json(data_file)
    cost = _read_json(cost_file)
    funding = _read_json(funding_file)
    selected = _mapping(current.get("selected_candidate_definition"))
    metrics = _mapping(current.get("metrics"))
    policy = _mapping(current.get("execution_evidence_policy"))
    external = _mapping(current.get("external_evidence"))
    source_lineage = _source_lineage(root=root, selected=selected, cost=cost, funding=funding)
    paper_candidate_id = _paper_candidate_id(str(selected.get("candidate_id", "")))
    checks = _checks(
        current_file=current_file,
        current=current,
        selected=selected,
        metrics=metrics,
        policy=policy,
        external=external,
        data=data,
        cost=cost,
        funding=funding,
        source_lineage=source_lineage,
    )
    blockers = _blockers(checks)
    ready = not blockers and bool(paper_candidate_id)
    return {
        "schema_version": "btc_intraday_short_cycle_paper_candidate_gate_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "manual_paper_review_candidate_only_no_paper_start_no_live",
        "status": "ready_for_manual_paper_review" if ready else "blocked_paper_candidate_gate",
        "decision": "allow_manual_paper_review_only" if ready else "repair_current_intraday_paper_candidate_gate",
        "next_required_action": "human_paper_review_approval" if ready else "repair_current_intraday_paper_candidate_gate",
        "source_reports": {
            "current_status": _relpath(current_file, root) if current_file.exists() else None,
            "data_status": _relpath(data_file, root) if data_file.exists() else None,
            "cost_model": _relpath(cost_file, root) if cost_file.exists() else None,
            "funding_ledger": _relpath(funding_file, root) if funding_file.exists() else None,
            "current_candidate_run_manifest": str(source_lineage.get("current_run_manifest_path", "")) or None,
            "current_candidate_cost_stress": str(source_lineage.get("current_cost_stress_report_path", "")) or None,
            "current_candidate_trade_ledger": str(source_lineage.get("expected_trade_ledger_path", "")) or None,
        },
        "research_candidate_definition": {
            "candidate_id": str(selected.get("candidate_id", "")),
            "definition_scope": str(selected.get("definition_scope", "")),
            "family_id": str(selected.get("family_id", "")),
            "strategy_id": str(selected.get("strategy_id", "")),
            "variant_id": str(selected.get("variant_id", "")),
            "source_run_id": str(selected.get("source_run_id", "")),
            "source_strategy_version": str(selected.get("source_strategy_version", "")),
            "source_data_version": str(selected.get("source_data_version", "")),
            "params_hash": str(selected.get("params_hash", "")),
        },
        "paper_candidate": {
            "candidate_id": paper_candidate_id,
            "family_id": str(selected.get("family_id", "")),
            "strategy_id": str(selected.get("strategy_id", "")),
            "variant_id": str(selected.get("variant_id", "")),
            "market_type": "usds_m_perpetual",
            "symbol": "BTCUSDT",
            "paper_mode": "simulated_broker_only",
            "validation_days_required": 30,
            "primary_timeframes": ["5m", "15m"],
        },
        "metrics": {
            "trade_count": int(metrics.get("trade_count", 0) or 0),
            "fill_count": int(metrics.get("fill_count", 0) or 0),
            "profit_factor": _float_or_none(metrics.get("profit_factor")),
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
            "pbo": _float_or_none(metrics.get("pbo")),
            "dsr": _float_or_none(metrics.get("dsr")),
        },
        "source_lineage": source_lineage,
        "checks": checks,
        "blockers": blockers,
        "paper_candidate_generation_allowed": ready,
        "paper_review_pending_allowed": ready,
        "paper_execution_authorized": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "execution_evidence_policy": {
            "current_scope": "intraday_5m_15m_simulated_paper_not_true_scalping",
            "true_scalping_requirements_are_diagnostic_for_current_scope": True,
            "true_scalping_only_blockers_accepted_as_diagnostic": _list_of_strings(
                external.get("true_scalping_only_blockers")
            ),
            "intraday_paper_sim_hard_blockers_resolved_by_this_gate": [
                "btc_external_evidence_paper_gate_not_ready"
            ]
            if ready
            else [],
        },
        "guardrails": {
            "research_only_until_manual_paper_review": True,
            "simulated_broker_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_auto_start": False,
            "paper_or_live_unlock_allowed": False,
            "live": "FROZEN",
        },
    }


def write_btc_intraday_short_cycle_paper_candidate_gate_report(
    payload: Mapping[str, Any],
    output_root: Path,
) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--current-status-path", default=str(DEFAULT_CURRENT_STATUS))
    parser.add_argument("--data-status-path", default=str(DEFAULT_DATA_STATUS))
    parser.add_argument("--cost-model-path", default=str(DEFAULT_COST_MODEL))
    parser.add_argument("--funding-ledger-path", default=str(DEFAULT_FUNDING_LEDGER))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_paper_candidate_gate_report(
        repo_root=Path(args.repo_root),
        current_status_path=Path(args.current_status_path),
        data_status_path=Path(args.data_status_path),
        cost_model_path=Path(args.cost_model_path),
        funding_ledger_path=Path(args.funding_ledger_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_paper_candidate_gate_report(payload, Path(args.output_root)))


def _checks(
    *,
    current_file: Path,
    current: Mapping[str, Any],
    selected: Mapping[str, Any],
    metrics: Mapping[str, Any],
    policy: Mapping[str, Any],
    external: Mapping[str, Any],
    data: Mapping[str, Any],
    cost: Mapping[str, Any],
    funding: Mapping[str, Any],
    source_lineage: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "current_status_present": current_file.exists(),
        "current_status_ready": str(current.get("status", ""))
        in {"research_definition_ready_paper_locked", "paper_candidate_ready_for_manual_review"},
        "research_gate_passed_for_manual_review": str(current.get("research_gate_status", ""))
        == "passed_for_manual_review",
        "research_candidate_definition_ready": str(current.get("research_candidate_definition_status", "")) == "ready",
        "research_definition_passed_internal_gate": int(
            current.get("research_definition_passed_internal_gate", 0) or 0
        )
        > 0,
        "selected_candidate_is_intraday_pullback_reclaim": str(selected.get("family_id", ""))
        == "pullback_reclaim_intraday_v0",
        "selected_candidate_strategy_present": bool(str(selected.get("strategy_id", "")).strip()),
        "selected_candidate_definition_scope_research_only": str(selected.get("definition_scope", ""))
        == "research_candidate_definition_only",
        "trade_count_minimum_met": int(metrics.get("trade_count", 0) or 0) >= 50,
        "fill_count_minimum_met": int(metrics.get("fill_count", 0) or 0) >= 100,
        "event_profit_factor_minimum_met": _float_or_none(metrics.get("event_profit_factor")) is not None
        and float(metrics.get("event_profit_factor")) >= 1.15,
        "walk_forward_pass_rate_minimum_met": _float_or_none(metrics.get("walk_forward_pass_rate")) is not None
        and float(metrics.get("walk_forward_pass_rate")) >= 0.8,
        "regime_pass_rate_minimum_met": _float_or_none(metrics.get("regime_pass_rate")) is not None
        and float(metrics.get("regime_pass_rate")) >= 0.75,
        "pbo_maximum_met": _float_or_none(metrics.get("pbo")) is not None
        and float(metrics.get("pbo")) <= 0.5,
        "dsr_minimum_met": _float_or_none(metrics.get("dsr")) is not None
        and float(metrics.get("dsr")) >= 0.1,
        "data_status_pass": str(data.get("status", "")) == "pass",
        "cost_model_pass": str(cost.get("status", "")) == "pass",
        "funding_payment_in_ledger": bool(funding.get("funding_payment_in_ledger", False)),
        "funding_merged_into_net_ledger": bool(funding.get("funding_merged_into_net_ledger", False)),
        "current_run_manifest_present": bool(source_lineage.get("current_run_manifest_exists", False)),
        "current_run_manifest_params_hash_matches": bool(
            source_lineage.get("current_run_manifest_params_hash_matches", False)
        ),
        "current_run_manifest_data_version_matches": bool(
            source_lineage.get("current_run_manifest_data_version_matches", False)
        ),
        "current_cost_stress_report_present": bool(source_lineage.get("current_cost_stress_report_exists", False)),
        "current_cost_stress_required_scenarios_present": bool(
            source_lineage.get("current_cost_stress_required_scenarios_present", False)
        ),
        "current_cost_stress_all_scenarios_survive": bool(
            source_lineage.get("current_cost_stress_all_scenarios_survive", False)
        ),
        "latest_cost_model_matches_current_candidate_run": bool(
            source_lineage.get("latest_cost_model_matches_current_candidate_run", False)
        ),
        "latest_funding_ledger_matches_current_candidate_trade_ledger": bool(
            source_lineage.get("latest_funding_ledger_matches_current_candidate_trade_ledger", False)
        ),
        "current_scope_not_true_scalping": str(policy.get("current_scope", ""))
        == "intraday_5m_15m_simulated_paper_not_true_scalping",
        "true_scalping_requirements_diagnostic_for_current_scope": bool(
            policy.get("true_scalping_requirements_are_diagnostic_for_current_scope", False)
        ),
        "only_paper_gate_hard_blocker_for_intraday": set(
            _list_of_strings(external.get("intraday_paper_sim_hard_blockers"))
        )
        <= {"btc_external_evidence_paper_gate_not_ready"},
        "paper_and_live_still_locked": str(current.get("paper_queue_status", "")) in {"locked", "pending_review"}
        and str(current.get("live_status", "")) == "frozen",
    }


def _blockers(checks: Mapping[str, bool]) -> list[str]:
    return [f"btc_intraday_paper_candidate_gate_{name}_failed" for name, passed in checks.items() if not passed]


def _source_lineage(
    *,
    root: Path,
    selected: Mapping[str, Any],
    cost: Mapping[str, Any],
    funding: Mapping[str, Any],
) -> dict[str, Any]:
    source_run_id = str(selected.get("source_run_id", "") or "")
    source_data_version = str(selected.get("source_data_version", "") or "")
    params_hash = str(selected.get("params_hash", "") or "")
    expected_run_dir = Path("artifacts/btc_intraday_event_ledger") / source_run_id if source_run_id else Path("")
    expected_trade_ledger = expected_run_dir / "trade_ledger.csv" if source_run_id else Path("")
    run_manifest_path = expected_run_dir / "run_manifest.json" if source_run_id else Path("")
    current_cost_stress_path = expected_run_dir / "cost_stress_report.json" if source_run_id else Path("")
    run_manifest = _read_json(root / run_manifest_path) if source_run_id else {}
    current_cost_stress = _read_json(root / current_cost_stress_path) if source_run_id else {}
    scenarios = [item for item in current_cost_stress.get("scenarios", []) if isinstance(item, Mapping)]
    latest_cost_source = str(cost.get("source_run_dir", "") or "")
    latest_funding_fills = str(funding.get("fills_source", "") or "")
    latest_funding_position = str(funding.get("position_source", "") or "")
    return {
        "expected_source_run_id": source_run_id,
        "expected_source_run_dir": expected_run_dir.as_posix() if source_run_id else "",
        "expected_trade_ledger_path": expected_trade_ledger.as_posix() if source_run_id else "",
        "current_run_manifest_path": run_manifest_path.as_posix() if source_run_id else "",
        "current_cost_stress_report_path": current_cost_stress_path.as_posix() if source_run_id else "",
        "latest_cost_model_source_run_dir": latest_cost_source,
        "latest_funding_fills_source": latest_funding_fills,
        "latest_funding_position_source": latest_funding_position,
        "current_run_manifest_exists": bool(source_run_id and (root / run_manifest_path).exists()),
        "current_run_manifest_data_version": str(run_manifest.get("data_version", "") or ""),
        "current_run_manifest_data_version_matches": bool(
            source_data_version and str(run_manifest.get("data_version", "") or "") == source_data_version
        ),
        "current_run_manifest_params_hash": str(run_manifest.get("params_hash", "") or ""),
        "current_run_manifest_params_hash_matches": bool(
            params_hash and str(run_manifest.get("params_hash", "") or "") == params_hash
        ),
        "current_cost_stress_report_exists": bool(source_run_id and (root / current_cost_stress_path).exists()),
        "current_cost_stress_required_scenarios_present": bool(
            current_cost_stress.get("required_scenarios_present", False)
        ),
        "current_cost_stress_scenario_count": int(current_cost_stress.get("scenario_count", 0) or 0),
        "current_cost_stress_survival_rate": _float_or_none(current_cost_stress.get("survival_rate")),
        "current_cost_stress_all_scenarios_survive": bool(
            scenarios and all(bool(item.get("survives", False)) for item in scenarios)
        ),
        "latest_cost_model_matches_current_candidate_run": _same_or_under(latest_cost_source, expected_run_dir),
        "latest_funding_ledger_matches_current_candidate_trade_ledger": bool(
            _same_path(latest_funding_fills, expected_trade_ledger)
            and _same_path(latest_funding_position, expected_trade_ledger)
        ),
    }


def _paper_candidate_id(research_candidate_id: str) -> str:
    if not research_candidate_id:
        return ""
    if research_candidate_id.endswith(":research_candidate_definition_v1"):
        return research_candidate_id.replace(":research_candidate_definition_v1", ":paper_candidate_v1")
    return f"{research_candidate_id}:paper_candidate_v1"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _same_or_under(value: object, expected_base: Path) -> bool:
    actual = _normal_path_string(value)
    expected = expected_base.as_posix().strip("/")
    return bool(actual and expected and (actual == expected or actual.startswith(f"{expected}/")))


def _same_path(value: object, expected: Path) -> bool:
    actual = _normal_path_string(value)
    expected_value = expected.as_posix().strip("/")
    return bool(actual and expected_value and actual == expected_value)


def _normal_path_string(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
