#!/usr/bin/env python3
"""Build a BTC research trial registry from existing artifacts.

The registry is read-only: it records accepted, selected, failed, and rejected
BTC research trials. It does not run backtests, submit orders, or change gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "btc_trial_registry_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trial_registry/latest/btc_trial_registry.json")
DEFAULT_PAPER_GATE = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_paper_candidate_gate_report.json")
DEFAULT_CURRENT_STATUS = Path("artifacts/btc_current_status/latest/btc_current_status_report.json")
DEFAULT_RESEARCH_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
DEFAULT_BOUNDED_RETEST_OUTCOME = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json")
DEFAULT_VARIANT_ROOT = Path("artifacts/btc_candidate_attribution")
DEFAULT_VALIDATION_ROOT = Path("artifacts/btc_candidate_validation")


def build_btc_trial_registry(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    source_files = _source_files(root)
    trials: list[dict[str, Any]] = []
    trials.extend(_selected_trials(root))
    trials.extend(_candidate_validation_trials(root))
    trials.extend(_bounded_retest_trials(root))
    trials.extend(_variant_summary_trials(root))
    trials = _dedupe_trials(trials)
    blockers = _registry_blockers(trials)
    warnings = _registry_warnings(trials)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "as_of_utc": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "complete" if not blockers else "blocked",
        "decision": "trial_registry_ready" if not blockers else "repair_trial_registry",
        "blockers": blockers,
        "warnings": warnings,
        "trial_count": len(trials),
        "status_counts": _status_counts(trials),
        "required_contract": {
            "per_trial_required_fields": [
                "trial_id",
                "run_id",
                "strategy_id",
                "variant_id",
                "params_hash",
                "status",
                "selected_by",
                "rejection_reason",
            ],
            "source_policy": "existing_artifacts_only_no_backtest_no_order_calls",
        },
        "source_artifacts": {_key_for_path(path): _relpath(path, root) for path in source_files if path.exists()},
        "input_hashes": {_key_for_path(path): _sha256(path) for path in source_files if path.exists() and path.is_file()},
        "trials": trials,
    }
    payload["artifact_hash"] = _payload_hash(payload)
    return payload


def write_btc_trial_registry(payload: Mapping[str, Any], *, output: Path = DEFAULT_OUTPUT) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_json_text(payload), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_trial_registry(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_trial_registry(payload, output=Path(args.output)))


def _selected_trials(root: Path) -> list[dict[str, Any]]:
    path = root / DEFAULT_PAPER_GATE
    payload = _read_json(path)
    candidate = _mapping(payload.get("paper_candidate"))
    research = _mapping(payload.get("research_candidate_definition"))
    source_lineage = _mapping(payload.get("source_lineage"))
    metrics = _mapping(payload.get("metrics"))
    run_id = str(research.get("source_run_id") or source_lineage.get("expected_source_run_id") or "")
    strategy_id = str(candidate.get("strategy_id") or research.get("strategy_id") or "")
    variant_id = str(candidate.get("variant_id") or research.get("variant_id") or "")
    params_hash = str(research.get("params_hash") or source_lineage.get("current_run_manifest_params_hash") or "")
    if not any([run_id, strategy_id, variant_id, params_hash]):
        return []
    return [
        _trial(
            trial_id=f"selected:{run_id}:{variant_id}",
            run_id=run_id,
            strategy_id=strategy_id,
            variant_id=variant_id,
            params_hash=params_hash,
            status="selected",
            selected_by="btc_intraday_short_cycle_paper_candidate_gate",
            rejection_reason=[],
            metrics=dict(metrics),
            source_artifacts={"paper_candidate_gate": _relpath(path, root)},
            params={},
        )
    ]


def _candidate_validation_trials(root: Path) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for manifest_path in sorted((root / DEFAULT_VALIDATION_ROOT).glob("*/run_manifest.json")):
        run_dir = manifest_path.parent
        manifest = _read_json(manifest_path)
        promotion_path = run_dir / "promotion_decision.json"
        promotion = _read_json(promotion_path)
        gate_results = promotion.get("candidate_gate_results", [])
        first_gate = _mapping(gate_results[0]) if isinstance(gate_results, list) and gate_results else {}
        fail_reasons = _list_of_strings(first_gate.get("fail_reasons"))
        status = "accepted" if bool(first_gate.get("passed", False)) else "failed"
        trials.append(
            _trial(
                trial_id=f"validation:{manifest.get('run_id', run_dir.name)}",
                run_id=str(manifest.get("run_id", run_dir.name)),
                strategy_id=str(manifest.get("strategy_id", "")),
                variant_id=str(manifest.get("variant_id", manifest.get("strategy_id", ""))),
                params_hash=str(manifest.get("params_hash") or manifest.get("config_hash") or ""),
                status=status,
                selected_by=str(first_gate.get("evidence_source") or "candidate_validation_promotion_decision"),
                rejection_reason=fail_reasons,
                metrics={},
                source_artifacts={
                    "run_manifest": _relpath(manifest_path, root),
                    "promotion_decision": _relpath(promotion_path, root) if promotion_path.exists() else "",
                },
                params=_mapping(manifest.get("params")),
            )
        )
    return trials


def _bounded_retest_trials(root: Path) -> list[dict[str, Any]]:
    path = root / DEFAULT_BOUNDED_RETEST_OUTCOME
    payload = _read_json(path)
    if not payload:
        return []
    source_artifacts = {
        key: str(value).replace("\\", "/")
        for key, value in _mapping(payload.get("source_artifacts")).items()
        if isinstance(value, str)
    }
    run_manifest_path = root / Path(source_artifacts.get("run_manifest", ""))
    canonical_path = root / Path(source_artifacts.get("canonical_backtest_report", ""))
    run_manifest = _read_json(run_manifest_path)
    canonical = _read_json(canonical_path)
    params_hash = str(
        _mapping(payload.get("manifest_contract")).get("params_hash")
        or canonical.get("params_hash")
        or canonical.get("config_hash")
        or run_manifest.get("config_hash")
        or _stable_hash({"run_id": payload.get("run_id", ""), "source_run_id": run_manifest.get("source_run_id", "")})
    )
    return [
        _trial(
            trial_id=f"bounded_retest:{payload.get('run_id', '')}",
            run_id=str(payload.get("run_id", "")),
            strategy_id=str(canonical.get("strategy_id", "")),
            variant_id=str(payload.get("run_id", "")),
            params_hash=params_hash,
            status="failed" if not bool(payload.get("candidate_gate_passed", False)) else "accepted",
            selected_by="candidate_bounded_retest_outcome_gate",
            rejection_reason=_list_of_strings(payload.get("failed_metrics")) or _list_of_strings(payload.get("blockers")),
            metrics=dict(_mapping(payload.get("metrics"))),
            source_artifacts={"bounded_retest_outcome": _relpath(path, root), **source_artifacts},
            params={},
        )
    ]


def _variant_summary_trials(root: Path) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for path in sorted((root / DEFAULT_VARIANT_ROOT).glob("**/variant_summary.json")):
        payload = _read_json(path)
        variant = str(payload.get("variant") or path.parent.name)
        params = _mapping(payload.get("params"))
        fail_reasons = _list_of_strings(payload.get("fail_reasons"))
        manifest_path = str(payload.get("manifest_path", ""))
        status = "rejected" if fail_reasons else "accepted"
        trials.append(
            _trial(
                trial_id=f"variant:{path.parent.parent.parent.name}:{variant}",
                run_id=_run_id_from_manifest_path(manifest_path) or path.parent.parent.parent.name,
                strategy_id=_strategy_from_manifest_path(manifest_path),
                variant_id=variant,
                params_hash=_stable_hash(params) if params else _stable_hash({"variant": variant}),
                status=status,
                selected_by=str(payload.get("evaluation_source") or "variant_summary_gate"),
                rejection_reason=fail_reasons,
                metrics=_variant_metrics(payload),
                source_artifacts={
                    "variant_summary": _relpath(path, root),
                    "manifest": manifest_path,
                },
                params=params,
            )
        )
    return trials


def _trial(
    *,
    trial_id: str,
    run_id: str,
    strategy_id: str,
    variant_id: str,
    params_hash: str,
    status: str,
    selected_by: str,
    rejection_reason: list[str],
    metrics: Mapping[str, Any],
    source_artifacts: Mapping[str, str],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "trial_id": trial_id,
        "run_id": run_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "params_hash": params_hash,
        "status": status,
        "selected_by": selected_by,
        "rejection_reason": rejection_reason,
        "metrics": dict(metrics),
        "params": dict(params),
        "source_artifacts": dict(source_artifacts),
    }


def _registry_blockers(trials: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not trials:
        blockers.append("btc_trial_registry_empty")
    selected = [trial for trial in trials if trial.get("status") == "selected"]
    if not selected:
        blockers.append("btc_trial_registry_selected_trial_missing")
    rejected_or_failed = [trial for trial in trials if trial.get("status") in {"rejected", "failed"}]
    if not rejected_or_failed:
        blockers.append("btc_trial_registry_rejected_or_failed_trial_missing")
    for index, trial in enumerate(trials):
        for field in ["run_id", "params_hash", "selected_by"]:
            if not trial.get(field):
                blockers.append(f"btc_trial_registry_trial_{index}_{field}_missing")
        if trial.get("status") in {"rejected", "failed"} and not trial.get("rejection_reason"):
            blockers.append(f"btc_trial_registry_trial_{index}_rejection_reason_missing")
    return _dedupe(blockers)


def _registry_warnings(trials: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for index, trial in enumerate(trials):
        if not trial.get("strategy_id"):
            warnings.append(f"btc_trial_registry_trial_{index}_strategy_id_inferred_missing")
    return warnings


def _source_files(root: Path) -> list[Path]:
    files = [
        root / DEFAULT_PAPER_GATE,
        root / DEFAULT_CURRENT_STATUS,
        root / DEFAULT_RESEARCH_REGISTRY,
        root / DEFAULT_BOUNDED_RETEST_OUTCOME,
    ]
    files.extend(sorted((root / DEFAULT_VALIDATION_ROOT).glob("*/run_manifest.json")))
    files.extend(sorted((root / DEFAULT_VALIDATION_ROOT).glob("*/promotion_decision.json")))
    files.extend(sorted((root / DEFAULT_VARIANT_ROOT).glob("**/variant_summary.json")))
    return files


def _variant_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = [
        "event_PF",
        "WF_pass",
        "regime_pass",
        "PF",
        "PBO",
        "DSR",
        "Sharpe",
        "MDD",
        "total_return_pct",
        "trade_count",
        "turnover",
        "cost_stress_base_pass",
        "cost_stress_harsh_survives",
    ]
    return {key: payload.get(key) for key in keys if key in payload}


def _run_id_from_manifest_path(value: str) -> str:
    if not value:
        return ""
    return Path(value).stem.removeprefix("run_")


def _strategy_from_manifest_path(value: str) -> str:
    stem = _run_id_from_manifest_path(value)
    if stem.endswith("_base"):
        stem = stem[: -len("_base")]
    if "_cost_" in stem:
        stem = stem.split("_cost_", 1)[0]
    return stem


def _dedupe_trials(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for trial in trials:
        key = str(trial.get("trial_id", ""))
        if key:
            by_id[key] = trial
    return [by_id[key] for key in sorted(by_id)]


def _status_counts(trials: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trial in trials:
        status = str(trial.get("status", ""))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _key_for_path(path: Path) -> str:
    return path.as_posix().replace("/", "__").replace("\\", "__").replace(".", "_")


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _payload_hash(payload: Mapping[str, Any]) -> str:
    copy = dict(payload)
    copy.pop("artifact_hash", None)
    return _stable_hash(copy)


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
