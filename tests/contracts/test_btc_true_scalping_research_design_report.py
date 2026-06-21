from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_research_design_report import (
    build_btc_true_scalping_research_design_report,
)


SCHEMA = Path("schemas/btc_true_scalping_research_design_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_research_design_report.json")


def test_btc_true_scalping_research_design_report_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_research_design_is_event_ledger_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    design = payload["strategy_design"]
    requirements = payload["event_ledger_requirements"]

    assert payload["status"] == "research_only_scalping_design_ready_for_event_ledger_prototype"
    assert payload["decision"] == "build_research_only_true_scalping_event_ledger_backtest"
    assert payload["next_required_action"] == "build_research_only_true_scalping_event_ledger_backtest"
    assert payload["blockers"] == []
    assert payload["research_only_event_ledger_prototype_allowed"] is True
    assert payload["research_only_scalping_design_allowed"] is True
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert design["strategy_id"] == "btc_true_scalp_liquidity_reclaim_research_v0"
    assert design["primary_timeframe"] == "1m"
    assert design["scope"] == "research_only_event_ledger_design_no_candidate_no_paper_no_live"
    assert requirements["simulated_order_intent_only"] is True
    assert requirements["pnl_from_fill_ledger_required"] is True
    assert requirements["future_label_used_for_signal"] is False
    assert requirements["lookahead_used_for_signal"] is False
    assert payload["guardrails"]["strategy_may_emit_only"] == ["Signal", "OrderIntent"]
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False


def test_btc_true_scalping_research_design_builder_blocks_without_review(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_research_design_review.json",
        {
            "status": "research_only_scalping_design_review_blocked",
            "research_only_scalping_design_allowed": False,
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json",
        {
            "true_scalping_allowed": False,
            "evidence": {
                "tick_or_agg_trade_history": {"files": ["agg_trades.csv"]},
                "order_book_depth_history": {"files": ["order_book_depth.csv"]},
                "spread_model": {"files": ["spread_model.json"]},
                "latency_model": {"files": ["latency_model.json"]},
                "queue_position_model": {"files": ["queue_position_model.json"]},
            },
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        {
            "candidate_generation_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "strategy_id": "fixture",
            "variant_id": "fixture",
            "event_definition": {"event_count": 1},
            "metrics": {},
        },
    )

    payload = build_btc_true_scalping_research_design_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "research_only_scalping_design_blocked"
    assert payload["research_only_event_ledger_prototype_allowed"] is False
    assert "btc_true_scalping_research_design_review_not_passed" in payload["blockers"]
    assert "btc_true_scalping_research_design_not_allowed" in payload["blockers"]


def test_btc_true_scalping_research_design_schema_rejects_paper_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
