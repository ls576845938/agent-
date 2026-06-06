#!/usr/bin/env python3
"""Build BTC candidate gate audit from existing compression event-ledger artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SOURCE_RUN_DIR = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
DEFAULT_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_FUNDING_LEDGER = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
DEFAULT_TAIL_DEPENDENCY = Path("artifacts/btc_tail_dependency/latest/tail_dependency_report.json")
DIAGNOSTIC_ONLY_WARNINGS = {
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_agg_trades_missing",
    "btc_liquidation_snapshot_missing_diagnostic_only",
    "btc_liquidation_snapshots_missing_diagnostic_only",
    "diagnostic_only_not_gate_evidence",
}


def build_btc_candidate_gate_audit(
    *,
    repo_root: Path | None = None,
    source_run_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = _resolve(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    canonical = _read_json(run_dir / "canonical_backtest_report.json")
    manifest = _read_json(run_dir / "manifests/run_btc_compression_expansion_breakout_v1_base.json")
    promotion = _read_json(run_dir / "promotion_decision.json")
    data_status = _read_json(root / DEFAULT_DATA_STATUS)
    provider = _read_json(root / DEFAULT_PROVIDER_VERIFICATION)
    cost_model = _read_json(root / DEFAULT_COST_MODEL)
    funding_report = _read_json(root / DEFAULT_FUNDING_LEDGER)
    tail_report = _read_json(root / DEFAULT_TAIL_DEPENDENCY)
    ledger = _mapping(_mapping(_mapping(manifest.get("evidence")).get("ledger_artifact")))
    ledger_pnl = _mapping(ledger.get("pnl"))
    fills = _mapping(ledger.get("fills"))
    metrics = _mapping(canonical.get("metrics"))
    required = {
        "canonical_backtest_report": (run_dir / "canonical_backtest_report.json").exists(),
        "fills": int(fills.get("effective_fill_count", metrics.get("fill_count", 0)) or 0) > 0,
        "ledger_pnl": ledger_pnl.get("source") == "ledger_fills" and float(ledger_pnl.get("net_pnl", 0.0) or 0.0) != 0.0,
        "funding_pnl": bool(funding_report.get("funding_payment_in_ledger", False)),
        "fee_pnl": bool(_mapping(ledger.get("fees")).get("total_fees", 0.0) or _mapping(manifest.get("cost_model")).get("realized_commission", 0.0)),
        "slippage_pnl": bool(_mapping(manifest.get("cost_model")).get("realized_slippage_cost", 0.0)),
        "cost_stress_report": (run_dir / "cost_stress_report.json").exists(),
        "walk_forward_report": (run_dir / "walk_forward_report.json").exists(),
        "regime_report": (run_dir / "regime_report.json").exists(),
        "no_lookahead_report": str(_mapping(canonical.get("no_lookahead_status")).get("status", "")).lower() == "pass",
        "PBO_DSR_report": (run_dir / "pbo_dsr_report.json").exists(),
        "tail_dependency_report": bool(tail_report.get("tail_dependency_pass", False)),
    }
    gate_checks = _mapping(_mapping(canonical.get("gate_decision")).get("checks"))
    thresholds = _mapping(_mapping(canonical.get("gate_decision")).get("thresholds"))
    blockers = _build_blockers(
        required,
        gate_checks=gate_checks,
        canonical=canonical,
        data_status=data_status,
        provider=provider,
        cost_model=cost_model,
        funding_report=funding_report,
        tail_report=tail_report,
    )
    candidate_passed_internal_gate = int(promotion.get("candidate_passed_internal_gate_count", 0) or 0)
    status = "fail" if blockers or candidate_passed_internal_gate <= 0 else "pass"
    paper_review_pending_allowed = status == "pass"
    metric_failures = _metric_failures(gate_checks)
    perpetual_evidence_blockers = _perpetual_evidence_blockers(
        data_status=data_status,
        provider=provider,
        cost_model=cost_model,
        funding_report=funding_report,
        tail_report=tail_report,
    )
    diagnostic_warnings = _diagnostic_warnings(
        [
            *_list_of_strings(data_status.get("diagnostic_warnings")),
            *_list_of_strings(provider.get("diagnostic_warnings")),
            *_list_of_strings(cost_model.get("diagnostic_warnings")),
            *_diagnostic_only_items(_list_of_strings(data_status.get("blockers"))),
            *_diagnostic_only_items(_list_of_strings(provider.get("blockers"))),
            *_diagnostic_only_items(_list_of_strings(cost_model.get("blockers"))),
        ]
    )
    best_available_candidate = _best_available_candidate(root, run_dir, canonical)
    return {
        "schema_version": "btc_candidate_gate_audit_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "strategy_id": str(canonical.get("strategy_id", "btc_compression_expansion_breakout_v1")),
        "source_run_dir": _relpath(run_dir, root),
        "candidate_gate_required_artifacts": required,
        "candidate_gate_perpetual_evidence": {
            "data_status_report": _relpath(root / DEFAULT_DATA_STATUS, root)
            if (root / DEFAULT_DATA_STATUS).exists()
            else None,
            "provider_verification_report": _relpath(root / DEFAULT_PROVIDER_VERIFICATION, root)
            if (root / DEFAULT_PROVIDER_VERIFICATION).exists()
            else None,
            "cost_model_report": _relpath(root / DEFAULT_COST_MODEL, root)
            if (root / DEFAULT_COST_MODEL).exists()
            else None,
            "funding_ledger_report": _relpath(root / DEFAULT_FUNDING_LEDGER, root)
            if (root / DEFAULT_FUNDING_LEDGER).exists()
            else None,
            "tail_dependency_report": _relpath(root / DEFAULT_TAIL_DEPENDENCY, root)
            if (root / DEFAULT_TAIL_DEPENDENCY).exists()
            else None,
            "market_type": str(_mapping(data_status.get("instrument")).get("market_type", "")),
            "contract_type": str(_mapping(data_status.get("instrument")).get("contract_type", "")),
            "perpetual_evidence_ready": bool(provider.get("perpetual_evidence_ready", False)),
            "cost_model_status": str(cost_model.get("status", "missing") or "missing"),
            "funding_payment_in_ledger": bool(funding_report.get("funding_payment_in_ledger", False)),
            "tail_dependency_pass": bool(tail_report.get("tail_dependency_pass", False)),
        },
        "candidate_gate_metric_checks": {
            "event_pf_pass": bool(gate_checks.get("event_profit_factor", False)),
            "ordinary_pf_diagnostic_only": True,
            "signal_equity_diagnostic_only": bool(gate_checks.get("signal_equity_diagnostic_only", False)),
            "target_active_return_diagnostic_only": True,
            "walk_forward_pass": bool(gate_checks.get("walk_forward_pass_rate", False)),
            "regime_pass": bool(gate_checks.get("regime_pass_rate", False)),
            "cost_stress_pass": bool(gate_checks.get("cost_stress_base", False))
            and bool(gate_checks.get("cost_stress_harsh", False)),
        },
        "candidate_gate_thresholds": {
            "event_profit_factor": _float_or_none(thresholds.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(thresholds.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(thresholds.get("regime_pass_rate")),
            "cost_stress_required": True,
        },
        "metric_failures": metric_failures,
        "best_available_candidate": best_available_candidate,
        "candidate_repair_plan": _candidate_repair_plan(
            status=status,
            candidate_passed_internal_gate=candidate_passed_internal_gate,
            perpetual_evidence_blockers=perpetual_evidence_blockers,
            metric_failures=metric_failures,
            best_available_candidate=best_available_candidate,
        ),
        "candidate_passed_internal_gate": candidate_passed_internal_gate,
        "paper_review_pending_allowed": paper_review_pending_allowed,
        "paper_queue_status": "pending_review" if paper_review_pending_allowed else "locked",
        "live_status": "frozen",
        "status": status,
        "diagnostic_warnings": diagnostic_warnings,
        "blockers": blockers,
    }


def write_btc_candidate_gate_audit(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "candidate_gate_audit_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_candidate_gate_audit(
        repo_root=Path(args.repo_root),
        source_run_dir=Path(args.source_run_dir),
        generated_at=args.generated_at or None,
    )
    print(write_btc_candidate_gate_audit(payload, Path(args.output_root)))


def _build_blockers(
    required: Mapping[str, bool],
    *,
    gate_checks: Mapping[str, Any],
    canonical: Mapping[str, Any],
    data_status: Mapping[str, Any],
    provider: Mapping[str, Any],
    cost_model: Mapping[str, Any],
    funding_report: Mapping[str, Any],
    tail_report: Mapping[str, Any],
) -> list[str]:
    blockers = []
    for name, available in required.items():
        if not available:
            blockers.append(f"btc_candidate_gate_{name}_missing")
    if not bool(gate_checks.get("event_profit_factor", False)):
        blockers.append("btc_candidate_gate_event_pf_failed")
    if not bool(gate_checks.get("walk_forward_pass_rate", False)):
        blockers.append("btc_candidate_gate_walk_forward_failed")
    if not bool(gate_checks.get("regime_pass_rate", False)):
        blockers.append("btc_candidate_gate_regime_failed")
    metrics = _mapping(canonical.get("metrics"))
    if "signal_equity" in metrics:
        blockers.append("btc_signal_equity_not_allowed_in_gate_metrics")
    if any(str(key).startswith("target_active") for key in metrics):
        blockers.append("btc_target_active_metric_not_allowed_in_gate_metrics")
    instrument = _mapping(data_status.get("instrument"))
    if str(instrument.get("market_type", "")) != "usds_m_perpetual":
        blockers.append("btc_candidate_gate_requires_usds_m_perpetual_data")
    if not provider.get("perpetual_evidence_ready", False):
        blockers.append("btc_candidate_gate_perpetual_evidence_not_ready")
    if str(cost_model.get("status", "missing")) != "pass":
        blockers.append("btc_candidate_gate_cost_model_not_pass")
    if not funding_report.get("funding_payment_in_ledger", False):
        blockers.append("btc_candidate_gate_funding_payment_not_in_ledger")
    if tail_report and not tail_report.get("tail_dependency_pass", False):
        blockers.append("btc_candidate_gate_tail_dependency_failed")
    blockers.extend(_hard_blockers(_list_of_strings(provider.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(cost_model.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(funding_report.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(tail_report.get("blockers"))))
    return _dedupe(blockers)


def _metric_failures(gate_checks: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if not bool(gate_checks.get("event_profit_factor", False)):
        failures.append("event_profit_factor")
    if not bool(gate_checks.get("walk_forward_pass_rate", False)):
        failures.append("walk_forward_pass_rate")
    if not bool(gate_checks.get("regime_pass_rate", False)):
        failures.append("regime_pass_rate")
    if not (bool(gate_checks.get("cost_stress_base", False)) and bool(gate_checks.get("cost_stress_harsh", False))):
        failures.append("cost_stress")
    return failures


def _perpetual_evidence_blockers(
    *,
    data_status: Mapping[str, Any],
    provider: Mapping[str, Any],
    cost_model: Mapping[str, Any],
    funding_report: Mapping[str, Any],
    tail_report: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    instrument = _mapping(data_status.get("instrument"))
    if str(instrument.get("market_type", "")) != "usds_m_perpetual":
        blockers.append("btc_candidate_repair_requires_usds_m_perpetual_data")
    if not provider.get("perpetual_evidence_ready", False):
        blockers.append("btc_candidate_repair_perpetual_evidence_not_ready")
    if str(cost_model.get("status", "missing")) != "pass":
        blockers.append("btc_candidate_repair_cost_model_not_pass")
    if not funding_report.get("funding_payment_in_ledger", False):
        blockers.append("btc_candidate_repair_funding_payment_not_in_ledger")
    if tail_report and not tail_report.get("tail_dependency_pass", False):
        blockers.append("btc_candidate_repair_tail_dependency_failed")
    return _dedupe(blockers)


def _candidate_repair_plan(
    *,
    status: str,
    candidate_passed_internal_gate: int,
    perpetual_evidence_blockers: list[str],
    metric_failures: list[str],
    best_available_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    data_cost_complete = not perpetual_evidence_blockers
    metric_complete = not metric_failures and candidate_passed_internal_gate > 0
    if status == "pass":
        next_required_action = "none"
    elif not data_cost_complete:
        next_required_action = "complete_btc_perpetual_data_cost_evidence"
    elif metric_failures:
        next_required_action = "repair_btc_candidate_metric_gate"
    else:
        next_required_action = "materialize_btc_candidate_promotion_decision"
    return {
        "next_required_action": next_required_action,
        "stages": [
            {
                "name": "perpetual_data_cost_evidence",
                "status": "complete" if data_cost_complete else "blocked",
                "action": "complete_manual_metadata_fee_tier_and_perpetual_provider_evidence",
                "blockers": perpetual_evidence_blockers,
            },
            {
                "name": "internal_metric_gate",
                "status": "complete" if metric_complete else "blocked",
                "action": "repair_event_pf_walk_forward_regime_or_select_better_candidate",
                "blockers": metric_failures,
            },
            {
                "name": "paper_review_queue",
                "status": "ready" if status == "pass" else "blocked",
                "action": "create_record_only_human_paper_review_after_candidate_pass",
                "blockers": [] if status == "pass" else ["btc_candidate_gate_not_pass"],
            },
        ],
        "best_available_candidate_strategy_id": str(best_available_candidate.get("strategy_id", "")),
    }


def _best_available_candidate(root: Path, primary_run_dir: Path, primary_canonical: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [_candidate_summary(root, primary_run_dir, primary_canonical)]
    for path in sorted(root.glob("artifacts/btc_candidate_validation/*/canonical_backtest_report.json")):
        candidates.append(_candidate_summary(root, path.parent, _read_json(path)))
    for path in sorted(root.glob("artifacts/btc_canonical/*/*/canonical_backtest_report.json")):
        candidates.append(_candidate_summary(root, path.parent, _read_json(path)))
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = f"{candidate['source_run_dir']}::{candidate['strategy_id']}"
        unique[key] = candidate
    return max(unique.values(), key=_candidate_score) if unique else _empty_candidate_summary()


def _candidate_summary(root: Path, run_dir: Path, canonical: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _mapping(canonical.get("metrics"))
    gate_decision = _mapping(canonical.get("gate_decision"))
    checks = _mapping(gate_decision.get("checks"))
    thresholds = _mapping(gate_decision.get("thresholds"))
    core_checks = {
        "event_profit_factor": bool(checks.get("event_profit_factor", False)),
        "walk_forward_pass_rate": bool(checks.get("walk_forward_pass_rate", False)),
        "regime_pass_rate": bool(checks.get("regime_pass_rate", False)),
        "cost_stress": bool(checks.get("cost_stress_base", False)) and bool(checks.get("cost_stress_harsh", False)),
        "dsr": bool(checks.get("dsr", False)),
        "pbo": bool(checks.get("pbo", False)),
        "max_drawdown": bool(checks.get("max_drawdown", False)),
        "annual_turnover": bool(checks.get("annual_turnover", False)),
    }
    failed_metrics = [name for name, passed in core_checks.items() if not passed]
    return {
        "strategy_id": str(canonical.get("strategy_id", run_dir.name)),
        "source_run_dir": _relpath(run_dir, root),
        "status": str(gate_decision.get("status", "candidate_gate_unknown") or "candidate_gate_unknown"),
        "passed_metric_count": sum(1 for passed in core_checks.values() if passed),
        "required_metric_count": len(core_checks),
        "failed_metrics": failed_metrics,
        "metrics": {
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
            "profit_factor": _float_or_none(metrics.get("profit_factor")),
            "dsr": _float_or_none(metrics.get("dsr")),
            "pbo": _float_or_none(metrics.get("pbo")),
            "max_drawdown": _float_or_none(metrics.get("max_drawdown")),
            "trade_count": _int_or_none(metrics.get("trade_count")),
            "fill_count": _int_or_none(metrics.get("fill_count")),
        },
        "thresholds": {
            "event_profit_factor": _float_or_none(thresholds.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(thresholds.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(thresholds.get("regime_pass_rate")),
        },
    }


def _candidate_score(candidate: Mapping[str, Any]) -> tuple[int, float, float, float, int]:
    metrics = _mapping(candidate.get("metrics"))
    return (
        int(candidate.get("passed_metric_count", 0) or 0),
        _float_or_default(metrics.get("event_profit_factor"), 0.0),
        _float_or_default(metrics.get("walk_forward_pass_rate"), 0.0),
        _float_or_default(metrics.get("regime_pass_rate"), 0.0),
        int(_int_or_none(metrics.get("fill_count")) or 0),
    )


def _empty_candidate_summary() -> dict[str, Any]:
    return {
        "strategy_id": "",
        "source_run_dir": "",
        "status": "candidate_gate_missing",
        "passed_metric_count": 0,
        "required_metric_count": 0,
        "failed_metrics": [],
        "metrics": {
            "event_profit_factor": None,
            "walk_forward_pass_rate": None,
            "regime_pass_rate": None,
            "profit_factor": None,
            "dsr": None,
            "pbo": None,
            "max_drawdown": None,
            "trade_count": None,
            "fill_count": None,
        },
        "thresholds": {
            "event_profit_factor": None,
            "walk_forward_pass_rate": None,
            "regime_pass_rate": None,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _diagnostic_only_items(values: list[str]) -> list[str]:
    return [value for value in _list_of_strings(values) if value in DIAGNOSTIC_ONLY_WARNINGS]


def _diagnostic_warnings(values: list[str]) -> list[str]:
    return _dedupe(_diagnostic_only_items(values))


def _hard_blockers(values: list[str]) -> list[str]:
    return _dedupe([value for value in _list_of_strings(values) if value not in DIAGNOSTIC_ONLY_WARNINGS])


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _float_or_default(value: object, default: float) -> float:
    number = _float_or_none(value)
    return default if number is None else number


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
