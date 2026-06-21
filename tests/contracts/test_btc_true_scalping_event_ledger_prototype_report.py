from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_event_ledger_prototype_report import (
    build_btc_true_scalping_event_ledger_prototype_report,
)


SCHEMA = Path("schemas/btc_true_scalping_event_ledger_prototype_report.schema.json")
REPORT = Path("artifacts/btc_scalping_event_ledger/latest/btc_true_scalping_event_ledger_prototype_report.json")


def test_btc_true_scalping_event_ledger_prototype_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_event_ledger_prototype_fails_gate_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    metrics = payload["metrics"]
    gate = payload["gate"]

    assert payload["status"] == "event_ledger_research_gate_failed"
    assert payload["decision"] == "reject_or_redesign_scalping_hypothesis"
    assert payload["next_required_action"] == "redesign_true_scalping_event_definition_before_strategy_skeleton"
    assert payload["event_definition"]["simulated_order_intent_only"] is True
    assert payload["event_definition"]["future_label_used_for_signal"] is False
    assert payload["event_definition"]["lookahead_used_for_signal"] is False
    assert metrics["trade_count"] >= 100
    assert metrics["fill_count"] == metrics["trade_count"] * 2
    assert metrics["pnl_from_fill_ledger"] is True
    assert gate["passed"] is False
    assert gate["checks"]["minimum_trade_count"] is True
    assert gate["checks"]["minimum_fill_count"] is True
    assert gate["checks"]["profit_factor"] is False
    assert gate["checks"]["hit_rate"] is False
    assert gate["checks"]["mean_trade_return_bps"] is False
    assert "btc_true_scalping_event_ledger_gate_failed_profit_factor" in payload["blockers"]
    assert "btc_true_scalping_event_ledger_candidate_generation_locked" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False


def test_current_btc_true_scalping_fill_ledger_matches_report_metrics() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    ledger_path = Path(payload["artifacts"]["fill_ledger"])
    rows = list(csv.DictReader(ledger_path.open("r", encoding="utf-8")))

    assert len(rows) == payload["metrics"]["fill_count"]
    pnl = sum(float(row["cash_flow"]) for row in rows)
    assert pnl == pytest.approx(payload["metrics"]["net_pnl"])


def test_btc_true_scalping_event_ledger_prototype_blocks_without_design(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_research_design_report.json",
        {
            "status": "research_only_scalping_design_blocked",
            "research_only_event_ledger_prototype_allowed": False,
        },
    )
    payload = build_btc_true_scalping_event_ledger_prototype_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "event_ledger_research_gate_blocked"
    assert "btc_true_scalping_design_not_ready" in payload["blockers"]
    assert "btc_true_scalping_event_ledger_prototype_not_allowed" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_true_scalping_event_ledger_schema_rejects_candidate_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["candidate_generation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
