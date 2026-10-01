from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.trend_boundary import build_btc_trend_boundary_report
from scripts.build_btc_trend_boundary_report import build_btc_trend_boundary_report_file


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _source_report(**guardrail_overrides: object) -> dict[str, object]:
    guardrails = {
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
    }
    guardrails.update(guardrail_overrides)
    return {
        "pipeline": "btc_trend_raw_forward_observation_daily",
        "status": "PASS",
        "symbol": "BTCUSDT",
        "guardrails": guardrails,
    }


def test_btc_trend_boundary_report_accepts_complete_forecast_cost_oms_chain() -> None:
    payload = build_btc_trend_boundary_report(
        source_report=_source_report(),
        generated_at_utc=TS,
        boundary_chain={
            "signal_artifact": "artifacts/btc/signal.json",
            "forecast_artifact": "artifacts/btc/forecast.json",
            "target_artifact": "artifacts/btc/target.json",
            "cost_gate_artifact": "artifacts/btc/cost_gate.json",
            "order_intent_artifact": "artifacts/btc/order_intent.json",
            "paper_oms_lifecycle_artifact": "artifacts/btc/paper_oms.json",
            "forecast_source_boundary": "signal_to_btc_forecast",
            "target_source_boundary": "forecast_to_target_position_no_order_intent",
            "order_intent_source_boundary": "cost_gate_to_order_intent_no_broker_submit",
            "paper_oms_source_boundary": "btc_paper_oms_lifecycle",
        },
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "trend_boundary_chain_complete"
    assert payload["allows_live_orders"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_trend_boundary_report_blocks_missing_chain_and_unsafe_guardrails() -> None:
    payload = build_btc_trend_boundary_report(
        source_report=_source_report(order_endpoint_used=True),
        generated_at_utc=TS,
        boundary_chain={},
    )

    assert payload["status"] == "blocked"
    assert "btc_trend_boundary_order_endpoint_used_not_false" in payload["blockers"]
    assert "btc_trend_boundary_chain_missing:forecast_artifact" in payload["blockers"]
    assert "btc_trend_boundary_order_intent_not_from_cost_gate" in payload["blockers"]


def test_btc_trend_boundary_file_falls_back_to_roll_chain_when_daily_refresh_blocked(tmp_path: Path) -> None:
    daily = tmp_path / "daily.json"
    roll = tmp_path / "roll.json"
    output = tmp_path / "boundary.json"
    daily.write_text(json.dumps(_source_report(), ensure_ascii=False), encoding="utf-8")
    roll.write_text(
        json.dumps(
            {
                "forecast_target_order_chain": {
                    "signal_artifact": "signal.json",
                    "forecast_artifact": "forecast.json",
                    "target_artifact": "target.json",
                    "cost_gate_artifact": "cost.json",
                    "order_intent_artifact": "intent.json",
                    "paper_oms_lifecycle_artifact": "oms.json",
                    "forecast_source_boundary": "signal_to_btc_forecast",
                    "target_source_boundary": "forecast_to_target_position_no_order_intent",
                    "order_intent_source_boundary": "cost_gate_to_order_intent_no_broker_submit",
                    "paper_oms_source_boundary": "btc_paper_oms_lifecycle",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_btc_trend_boundary_report_file(
        source=daily,
        roll_source=roll,
        output=output,
        generated_at_utc=TS,
    )

    assert payload["status"] == "complete"
    assert payload["chain"]["chain_source_report"] == str(roll).replace("\\", "/")
