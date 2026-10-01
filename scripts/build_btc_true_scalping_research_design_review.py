#!/usr/bin/env python3
"""Build the BTC true-scalping research-design manual review gate."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_READINESS = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json")
DEFAULT_MODEL_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_model_report.json")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_report.json")
DEFAULT_EVENT_LEDGER = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json")


def build_btc_true_scalping_research_design_review(
    *,
    repo_root: Path | None = None,
    readiness_path: Path | None = None,
    model_report_path: Path | None = None,
    capture_report_path: Path | None = None,
    event_ledger_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    readiness_file = _resolve(root, readiness_path or DEFAULT_READINESS)
    model_file = _resolve(root, model_report_path or DEFAULT_MODEL_REPORT)
    capture_file = _resolve(root, capture_report_path or DEFAULT_CAPTURE_REPORT)
    event_ledger_file = _resolve(root, event_ledger_path or DEFAULT_EVENT_LEDGER)
    readiness = _read_json(readiness_file)
    model_report = _read_json(model_file)
    capture_report = _read_json(capture_file)
    event_ledger = _read_json(event_ledger_file)
    checks = _checks(readiness=readiness, model_report=model_report, capture_report=capture_report, event_ledger=event_ledger)
    blockers = _blockers(checks)
    passed = not blockers
    return {
        "schema_version": "btc_true_scalping_research_design_review_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "research_only_scalping_design_review_passed"
        if passed
        else "research_only_scalping_design_review_blocked",
        "decision": "allow_research_only_true_scalping_design"
        if passed
        else "continue_microstructure_or_event_ledger_repair",
        "next_required_action": "build_research_only_true_scalping_design_report"
        if passed
        else "repair_blocked_review_checks_before_scalping_design",
        "source_reports": {
            "microstructure_readiness": _relpath(readiness_file, root) if readiness_file.exists() else None,
            "microstructure_model_report": _relpath(model_file, root) if model_file.exists() else None,
            "microstructure_capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
            "drift_guarded_event_ledger": _relpath(event_ledger_file, root) if event_ledger_file.exists() else None,
        },
        "checks": checks,
        "blockers": blockers,
        "limitations": [
            "public_rest_microstructure_sample_is_research_only_not_execution_latency",
            "queue_model_uses_visible_book_depth_not_exchange_order_queue_position",
            "spread_model_uses_current_public_book_sample_not_full_historical_l2_replay",
            "research_design_must_emit_signal_or_order_intent_only_no_broker_or_private_endpoint",
        ],
        "research_only_scalping_design_allowed": passed,
        "research_only_event_definition_allowed": passed,
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "guardrails": {
            "research_only": True,
            "manual_review_gate_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    }


def write_btc_true_scalping_research_design_review(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_true_scalping_research_design_review.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--readiness-path", default=str(DEFAULT_READINESS))
    parser.add_argument("--model-report-path", default=str(DEFAULT_MODEL_REPORT))
    parser.add_argument("--capture-report-path", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--event-ledger-path", default=str(DEFAULT_EVENT_LEDGER))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_research_design_review(
        repo_root=Path(args.repo_root),
        readiness_path=Path(args.readiness_path),
        model_report_path=Path(args.model_report_path),
        capture_report_path=Path(args.capture_report_path),
        event_ledger_path=Path(args.event_ledger_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_true_scalping_research_design_review(payload, Path(args.output_root)))
    if payload.get("status") != "research_only_scalping_design_review_passed":
        raise SystemExit(2)


def _checks(
    *,
    readiness: Mapping[str, Any],
    model_report: Mapping[str, Any],
    capture_report: Mapping[str, Any],
    event_ledger: Mapping[str, Any],
) -> dict[str, bool]:
    evidence = _mapping(readiness.get("evidence"))
    guardrails = _mapping(readiness.get("guardrails"))
    event_guardrails = _mapping(event_ledger.get("guardrails"))
    return {
        "microstructure_readiness_passed": str(readiness.get("status", "")) == "microstructure_evidence_ready_research_only",
        "one_minute_klines_pass": _mapping(evidence.get("one_minute_klines")).get("status") == "pass",
        "tick_or_agg_trade_history_pass": _mapping(evidence.get("tick_or_agg_trade_history")).get("status") == "pass",
        "order_book_depth_history_pass": _mapping(evidence.get("order_book_depth_history")).get("status") == "pass",
        "spread_model_pass": _mapping(evidence.get("spread_model")).get("status") == "pass",
        "latency_model_pass": _mapping(evidence.get("latency_model")).get("status") == "pass",
        "queue_position_model_pass": _mapping(evidence.get("queue_position_model")).get("status") == "pass",
        "microstructure_model_report_pass": str(model_report.get("status", "")) == "pass",
        "public_capture_verified": str(capture_report.get("status", "")) == "verified",
        "public_capture_has_latency_samples": len(_list_of_mappings(capture_report.get("latency_samples"))) >= 2,
        "event_ledger_passed_internal_research_gate": bool(_mapping(event_ledger.get("gate")).get("passed", False)),
        "event_ledger_candidate_still_locked": bool(event_ledger.get("candidate_generation_allowed", True)) is False,
        "event_ledger_paper_live_locked": bool(event_ledger.get("paper_or_live_unlock_allowed", True)) is False,
        "readiness_true_scalping_still_locked": bool(readiness.get("true_scalping_allowed", True)) is False,
        "readiness_strategy_skeleton_still_locked": bool(readiness.get("strategy_skeleton_generation_allowed", True)) is False,
        "readiness_candidate_generation_still_locked": bool(readiness.get("candidate_generation_allowed", True)) is False,
        "private_order_broker_paths_locked": all(
            bool(value) is False
            for value in (
                guardrails.get("broker_calls_allowed", True),
                guardrails.get("private_endpoints_allowed", True),
                guardrails.get("order_endpoints_allowed", True),
                event_guardrails.get("broker_calls_allowed", True),
                event_guardrails.get("private_endpoints_allowed", True),
                event_guardrails.get("order_endpoints_allowed", True),
            )
        ),
    }


def _blockers(checks: Mapping[str, bool]) -> list[str]:
    return [f"btc_scalping_review_{name}_failed" for name, passed in checks.items() if not passed]


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


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
