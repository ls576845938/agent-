#!/usr/bin/env python3
"""Build a read-only BTC compression-expansion attribution bundle."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SOURCE_RUN_DIR = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_attribution/latest_compression_expansion_attribution")
DEFAULT_FUNDING_LEDGER_REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")


def build_btc_compression_expansion_attribution_bundle(
    *,
    repo_root: Path | None = None,
    source_run_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = _resolve_path(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    failure = _read_json(run_dir / "compression_expansion_failure_mode_report.json")
    event_attribution = _read_json(run_dir / "event_ledger_attribution_report.json")
    fold_audit = _read_json(run_dir / "fold_regime_contract_audit.json")
    data_status = _read_json(run_dir / "btc_data_fold_regime_status_report.json")
    validation = _read_json(run_dir / "candidate_validation_result.json")
    canonical = _read_json(run_dir / "canonical_backtest_report.json")
    base_manifest = _read_json(run_dir / "manifests/run_btc_compression_expansion_breakout_v1_base.json")

    active_vs_full = _mapping(failure.get("full_vs_active_exposure"))
    failed_regimes = _list_of_strings(_mapping(failure.get("regime_drag")).get("dragging_regimes"))
    if not failed_regimes:
        failed_regimes = _list_of_strings(_mapping(fold_audit.get("regime_contract")).get("dragging_regimes"))
    candidate_metrics = _mapping(failure.get("candidate_metrics"))
    active_event_pf = _float(_mapping(active_vs_full.get("active_exposure")).get("event_pf"))
    full_event_pf = _float(_mapping(active_vs_full.get("full_ledger")).get("event_pf") or candidate_metrics.get("event_pf"))
    active_full_gap = round(active_event_pf - full_event_pf, 6)
    stable_repair_pattern_found = False
    archive_recommended = True
    fold_failure = {
        "schema_version": "btc_compression_expansion_fold_failure_report_v1",
        "generated_at": generated,
        "source_run_dir": _relpath(run_dir, root),
        "failed_folds": [str(row.get("fold_id", "")) for row in _list_of_mappings(failure.get("failed_fold_autopsy"))],
        "failed_fold_autopsy": _list_of_mappings(failure.get("failed_fold_autopsy")),
        "fold_contract": _mapping(fold_audit.get("fold_contract")),
        "walk_forward_pass_rate": _float(_mapping(failure.get("candidate_metrics")).get("walk_forward_pass_rate")),
        "blockers": ["btc_compression_expansion_failed_folds_require_repair_decision"],
        "promotion_ready": False,
    }
    regime_drag = {
        "schema_version": "btc_compression_expansion_regime_drag_report_v1",
        "generated_at": generated,
        "source_run_dir": _relpath(run_dir, root),
        "regime_drag": _mapping(failure.get("regime_drag")),
        "by_regime": _list_of_mappings(event_attribution.get("by_regime")),
        "regime_contract": _mapping(fold_audit.get("regime_contract")),
        "regime_status": _mapping(data_status.get("regime_status")),
        "blockers": ["btc_compression_expansion_regime_drag_unresolved"],
        "promotion_ready": False,
    }
    entry_exit = {
        "schema_version": "btc_compression_expansion_entry_exit_timing_report_v1",
        "generated_at": generated,
        "source_run_dir": _relpath(run_dir, root),
        "entry_exit_timing": _mapping(failure.get("entry_exit_timing")),
        "blockers": ["btc_compression_expansion_entry_exit_timing_diagnostic_only"],
        "promotion_ready": False,
    }
    active_full = {
        "schema_version": "btc_compression_expansion_active_vs_full_ledger_report_v1",
        "generated_at": generated,
        "source_run_dir": _relpath(run_dir, root),
        "active_vs_full_ledger": active_vs_full,
        "ordinary_pf": _float(event_attribution.get("ordinary_pf")),
        "event_pf": _float(event_attribution.get("event_pf")),
        "active_event_pf": active_event_pf,
        "active_vs_full_ledger_gap": active_full_gap,
        "full_event_pf_gate_passes": bool(_mapping(active_vs_full.get("full_ledger")).get("event_pf", 0.0) and active_vs_full.get("full_event_pf_gate_passes", False)),
        "active_event_pf_gate_passes": bool(active_vs_full.get("active_event_pf_gate_passes", False)),
        "blockers": ["btc_compression_expansion_full_ledger_event_pf_failed"],
        "promotion_ready": False,
    }
    cost_funding_drag = _cost_funding_drag_report(
        generated_at=generated,
        run_dir=run_dir,
        root=root,
        canonical=canonical,
        base_manifest=base_manifest,
    )
    attribution_report = {
        "schema_version": "btc_compression_expansion_attribution_bundle_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "strategy_id": str(failure.get("strategy_id") or validation.get("strategy_id") or "compression_expansion_breakout"),
        "status": "archived",
        "allowed_next_action": "archive_only",
        "archive_recommended": archive_recommended,
        "stable_repair_pattern_found": stable_repair_pattern_found,
        "paper_review_pending_allowed": False,
        "source_run_dir": _relpath(run_dir, root),
        "source_reports": {
            "failure_mode_report": _relpath(run_dir / "compression_expansion_failure_mode_report.json", root),
            "event_ledger_attribution_report": _relpath(run_dir / "event_ledger_attribution_report.json", root),
            "fold_regime_contract_audit": _relpath(run_dir / "fold_regime_contract_audit.json", root),
            "btc_data_fold_regime_status_report": _relpath(run_dir / "btc_data_fold_regime_status_report.json", root),
        },
        "candidate_metrics": candidate_metrics,
        "gate_status": str(failure.get("gate_status") or event_attribution.get("gate_status") or validation.get("status", "")),
        "gate_fail_reasons": [
            str(item)
            for item in (failure.get("gate_fail_reasons") or event_attribution.get("gate_fail_reasons") or validation.get("gate_fail_reasons", []))
        ],
        "root_cause_summary": [str(item) for item in event_attribution.get("root_cause_summary", [])],
        "attribution_answers": {
            "hypothesis_layer": "passed_proxy_metrics_before_full_lifecycle_event_ledger",
            "event_ledger_candidate_failure": "event_PF_walk_forward_and_regime_gates_failed",
            "event_pf_failure_sources": [
                "full_ledger_event_pf_below_gate",
                "failed_folds_3_4",
                "regime_drag_unresolved",
                "active_exposure_outperformed_full_ledger_diagnostic",
            ],
            "failed_folds_concentrated": ["3", "4"],
            "failed_regimes": failed_regimes,
            "target_active_vs_full_ledger_gap": active_full_gap,
            "stable_repair_pattern": "none_confirmed",
        },
        "decision": _mapping(failure.get("decision")),
        "paper_queue": str(event_attribution.get("paper_queue") or "LOCKED"),
        "live": str(event_attribution.get("live") or "FROZEN"),
        "paper_review_pending_created": False,
        "promotion_ready": False,
        "child_reports": {
            "fold_failure_report": str(DEFAULT_OUTPUT_ROOT / "fold_failure_report.json"),
            "regime_drag_report": str(DEFAULT_OUTPUT_ROOT / "regime_drag_report.json"),
            "entry_exit_timing_report": str(DEFAULT_OUTPUT_ROOT / "entry_exit_timing_report.json"),
            "active_vs_full_ledger_report": str(DEFAULT_OUTPUT_ROOT / "active_vs_full_ledger_report.json"),
            "cost_funding_drag_report": str(DEFAULT_OUTPUT_ROOT / "cost_funding_drag_report.json"),
        },
        "blockers": _dedupe(
            [
                "btc_compression_expansion_archived",
                "btc_compression_expansion_candidate_gate_failed",
                *fold_failure["blockers"],
                *regime_drag["blockers"],
                *active_full["blockers"],
                *cost_funding_drag["blockers"],
            ]
        ),
    }
    return {
        "attribution_report": attribution_report,
        "fold_failure_report": fold_failure,
        "regime_drag_report": regime_drag,
        "entry_exit_timing_report": entry_exit,
        "active_vs_full_ledger_report": active_full,
        "cost_funding_drag_report": cost_funding_drag,
    }


def write_btc_compression_expansion_attribution_bundle(
    payload: Mapping[str, Any],
    output_root: Path,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "attribution_report": output_root / "attribution_report.json",
        "fold_failure_report": output_root / "fold_failure_report.json",
        "regime_drag_report": output_root / "regime_drag_report.json",
        "entry_exit_timing_report": output_root / "entry_exit_timing_report.json",
        "active_vs_full_ledger_report": output_root / "active_vs_full_ledger_report.json",
        "cost_funding_drag_report": output_root / "cost_funding_drag_report.json",
    }
    payload_to_write = {key: dict(payload[key]) for key in paths}
    payload_to_write["attribution_report"]["child_reports"] = {
        key: str(path) for key, path in paths.items() if key != "attribution_report"
    }
    for key, path in paths.items():
        path.write_text(json.dumps(payload_to_write[key], indent=2, sort_keys=True), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_btc_compression_expansion_attribution_bundle(
        repo_root=Path(args.repo_root),
        source_run_dir=Path(args.source_run_dir),
        generated_at=args.generated_at or None,
    )
    paths = write_btc_compression_expansion_attribution_bundle(payload, Path(args.output_root))
    print(json.dumps(paths, indent=2, sort_keys=True))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _cost_funding_drag_report(
    *,
    generated_at: str,
    run_dir: Path,
    root: Path,
    canonical: Mapping[str, Any],
    base_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = _mapping(canonical.get("metrics"))
    costs = _mapping(base_manifest.get("cost_model"))
    funding_report = _read_json(root / DEFAULT_FUNDING_LEDGER_REPORT)
    fee_drag = _float(costs.get("realized_commission") or metrics.get("fees"))
    slippage_drag = _float(costs.get("realized_slippage_cost") or metrics.get("slippage"))
    funding_payment_in_ledger = bool(funding_report.get("funding_payment_in_ledger", False))
    blockers = []
    if not funding_payment_in_ledger:
        blockers.append("btc_funding_payment_not_in_ledger")
    blockers.extend(_list_of_strings(funding_report.get("blockers")))
    blockers.extend(["btc_perpetual_cost_contract_not_complete"])
    return {
        "schema_version": "btc_compression_expansion_cost_funding_drag_report_v1",
        "generated_at": generated_at,
        "source_run_dir": _relpath(run_dir, root),
        "fee_drag": round(fee_drag, 6),
        "funding_drag": round(_float(funding_report.get("funding_pnl_total")), 6)
        if funding_report.get("funding_pnl_total") is not None
        else None,
        "trade_ledger_net_pnl_total": _float(funding_report.get("trade_ledger_net_pnl_total")),
        "funding_adjusted_net_pnl_total": _float(funding_report.get("funding_adjusted_net_pnl_total")),
        "funding_adjusted_ledger_path": funding_report.get("funding_adjusted_ledger_path"),
        "slippage_drag": round(slippage_drag, 6),
        "funding_payment_in_ledger": funding_payment_in_ledger,
        "fee_in_ledger": bool(fee_drag or metrics.get("fill_count", 0)),
        "slippage_in_ledger": bool(slippage_drag or metrics.get("fill_count", 0)),
        "mark_price_available": bool(funding_report.get("funding_events_count", 0)),
        "blockers": _dedupe(blockers),
        "promotion_ready": False,
    }


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
