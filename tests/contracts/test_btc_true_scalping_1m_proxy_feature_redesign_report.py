from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_1m_proxy_feature_redesign_report import (
    build_btc_true_scalping_1m_proxy_feature_redesign_report,
)


SCHEMA = Path("schemas/btc_true_scalping_1m_proxy_feature_redesign_report.schema.json")
REPORT = Path("artifacts/btc_scalping_event_ledger/latest/btc_true_scalping_1m_proxy_feature_redesign_report.json")


def test_btc_true_scalping_1m_proxy_feature_redesign_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_1m_proxy_feature_redesign_rejects_proxy_set() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    best = payload["best_variant"]
    metrics = best["metrics"]
    gate = best["gate"]

    assert payload["status"] == "proxy_feature_redesign_completed_no_viable_event"
    assert payload["decision"] == "reject_current_1m_proxy_feature_redesign_set"
    assert payload["next_required_action"] == "collect_timestamp_aligned_l2_history_before_true_scalping"
    assert payload["not_true_l2_scalping"] is True
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["variant_count"] == 144
    assert payload["research_gate_passed"] is False
    assert metrics["fill_count"] == metrics["trade_count"] * 2
    assert metrics["pnl_from_fill_ledger"] is True
    assert gate["passed"] is False
    assert "btc_true_scalping_proxy_redesign_no_variant_passed_research_gate" in payload["blockers"]
    assert "btc_true_scalping_proxy_redesign_not_true_l2_scalping" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["completed_bar_features_only"] is True
    assert payload["guardrails"]["lookahead_used_for_signal"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False


def test_current_btc_true_scalping_1m_proxy_best_ledger_matches_metrics() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    ledger_path = Path(payload["artifacts"]["best_variant_fill_ledger"])
    rows = list(csv.DictReader(ledger_path.open("r", encoding="utf-8")))

    assert len(rows) == payload["best_variant"]["metrics"]["fill_count"]
    pnl = sum(float(row["cash_flow"]) for row in rows)
    assert pnl == pytest.approx(payload["best_variant"]["metrics"]["net_pnl"])


def test_btc_true_scalping_1m_proxy_blocks_without_l2_feature_diagnostics(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_scalping_event_ledger/latest/btc_true_scalping_event_definition_redesign_report.json",
        {"status": "redesign_audit_completed_no_viable_scalping_event"},
    )
    _write_json(tmp_path / "artifacts/btc_scalping_readiness/latest/spread_model.json", {"status": "pass"})
    _write_json(tmp_path / "artifacts/btc_scalping_readiness/latest/latency_model.json", {"status": "pass"})

    payload = build_btc_true_scalping_1m_proxy_feature_redesign_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "proxy_feature_redesign_blocked"
    assert "btc_l2_feature_diagnostics_not_ready" in payload["blockers"]
    assert "btc_true_scalping_sqlite_market_data_missing" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_true_scalping_1m_proxy_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
