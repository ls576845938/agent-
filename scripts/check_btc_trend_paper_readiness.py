#!/usr/bin/env python3
"""Check BTC trend v0 daily paper readiness."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "btc_trend_paper_readiness_report_v1"
DEFAULT_PROMOTION_GATE = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_promotion_gate_report.json")
DEFAULT_FREEZE_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_5m_hft_freeze_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_paper_readiness_report.json")
DEFAULT_LEDGER_ROOT = Path("data/paper_ledger/btc_trend_v0")
FORBIDDEN_5M_LEDGER = Path("data/paper_ledger/btc_5m")
EXPECTED_SELECTED_CANDIDATE = "twelve_month_momentum_intended"


def check_btc_trend_paper_readiness(
    *,
    repo_root: Path | None = None,
    promotion_gate: Path = DEFAULT_PROMOTION_GATE,
    freeze_report: Path = DEFAULT_FREEZE_REPORT,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    output: Path = DEFAULT_OUTPUT,
    expected_selected_candidate: str = EXPECTED_SELECTED_CANDIDATE,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    gate_path = _resolve(root, promotion_gate)
    freeze_path = _resolve(root, freeze_report)
    ledger = _resolve(root, ledger_root)
    output_path = _resolve(root, output)
    gate = _read_json(gate_path)
    freeze = _read_json(freeze_path)
    blockers: list[str] = []

    if not gate:
        blockers.append("btc_trend_promotion_gate_missing")
    if str(gate.get("status", "")) != "paper_candidate_ready":
        blockers.append("btc_trend_promotion_gate_not_ready")
    if gate.get("paper_candidate_ready") is not True:
        blockers.append("btc_trend_paper_candidate_not_ready")
    if bool(gate.get("paper_candidate_ready_is_strategy_validation", False)):
        blockers.append("btc_trend_paper_gate_misstates_strategy_validation")
    selected = _mapping(gate.get("selected_candidate"))
    selected_strategy = str(selected.get("strategy_id", "") or "")
    if selected_strategy != expected_selected_candidate:
        blockers.append("btc_trend_selected_candidate_mismatch")

    ledger_audit = _mapping(gate.get("ledger_audit"))
    if not bool(ledger_audit.get("complete", False)):
        blockers.append("btc_trend_position_ledger_not_complete")
    if not bool(ledger_audit.get("lookahead_pass", False)):
        blockers.append("btc_trend_position_ledger_lookahead_failed")

    guardrails = _mapping(gate.get("guardrails"))
    if bool(guardrails.get("private_endpoint_used", True)):
        blockers.append("btc_trend_private_endpoint_used")
    if bool(guardrails.get("order_endpoint_used", True)):
        blockers.append("btc_trend_order_endpoint_used")
    if bool(guardrails.get("broker_calls_allowed", True)):
        blockers.append("btc_trend_broker_calls_allowed")
    if bool(guardrails.get("live_order_allowed", True)):
        blockers.append("btc_trend_live_order_allowed")

    if _same_path(ledger, _resolve(root, FORBIDDEN_5M_LEDGER)):
        blockers.append("btc_trend_ledger_root_must_not_be_btc_5m")

    if not freeze:
        blockers.append("btc_5m_hft_freeze_report_missing")
    if str(freeze.get("status", "")) != "frozen_rejected_as_high_frequency":
        blockers.append("btc_5m_hft_not_frozen")
    freeze_guardrails = _mapping(freeze.get("guardrails"))
    if freeze_guardrails.get("parameter_tuning_allowed") is not False:
        blockers.append("btc_5m_hft_freeze_allows_parameter_tuning")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "BLOCKED" if blockers else "PASS",
        "readiness_type": "paper_operational_readiness_only",
        "readiness_scope": "simulated_daily_paper_runner",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "selected_candidate": selected_strategy,
        "expected_selected_candidate": expected_selected_candidate,
        "ledger_root": _relpath(ledger, root),
        "promotion_gate": _relpath(gate_path, root),
        "freeze_report": _relpath(freeze_path, root),
        "checks": {
            "promotion_gate_ready": str(gate.get("status", "")) == "paper_candidate_ready",
            "paper_candidate_ready": gate.get("paper_candidate_ready") is True,
            "paper_candidate_ready_is_strategy_validation": bool(gate.get("paper_candidate_ready_is_strategy_validation", False)),
            "selected_candidate_matches": selected_strategy == expected_selected_candidate,
            "position_ledger_complete": bool(ledger_audit.get("complete", False)),
            "position_ledger_lookahead_pass": bool(ledger_audit.get("lookahead_pass", False)),
            "ledger_root_isolated": not _same_path(ledger, _resolve(root, FORBIDDEN_5M_LEDGER)),
            "five_minute_hft_frozen": str(freeze.get("status", "")) == "frozen_rejected_as_high_frequency",
            "private_endpoint_used": bool(guardrails.get("private_endpoint_used", True)),
            "order_endpoint_used": bool(guardrails.get("order_endpoint_used", True)),
            "broker_calls_allowed": bool(guardrails.get("broker_calls_allowed", True)),
            "live_order_allowed": bool(guardrails.get("live_order_allowed", True)),
        },
        "guardrails": {
            "paper_readiness_is_not_strategy_validation": True,
            "strategy_validation_gate_required_before_strategy_claims": True,
            "paper_runner_observation_allowed_without_strategy_validation": True,
            "broker_calls_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "live_order_allowed": False,
            "do_not_reuse_5m_hft_ledger": True,
        },
        "blockers": _dedupe(blockers),
    }
    _write_json(output_path, payload)
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check BTC trend v0 daily paper readiness.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--promotion-gate", default=str(DEFAULT_PROMOTION_GATE))
    parser.add_argument("--freeze-report", default=str(DEFAULT_FREEZE_REPORT))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--expected-selected-candidate", default=EXPECTED_SELECTED_CANDIDATE)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = check_btc_trend_paper_readiness(
        repo_root=Path(args.repo_root),
        promotion_gate=Path(args.promotion_gate),
        freeze_report=Path(args.freeze_report),
        ledger_root=Path(args.ledger_root),
        output=Path(args.output),
        expected_selected_candidate=args.expected_selected_candidate,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


if __name__ == "__main__":
    main()
