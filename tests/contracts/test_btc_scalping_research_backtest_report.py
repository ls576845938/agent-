from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA = Path("schemas/btc_scalping_research_backtest_report.schema.json")
REPORT = Path("artifacts/btc_research_backtests/latest/btc_scalping_research_backtest_report.json")


def test_btc_scalping_research_backtest_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_scalping_research_backtest_summarizes_usable_research_track() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    one_minute = payload["backtests"]["one_minute_proxy_scalping"]
    five_minute = payload["backtests"]["five_minute_drift_guarded_intraday"]

    assert payload["status"] == "research_backtest_completed"
    assert payload["recommended_research_track"] == "five_minute_drift_guarded_intraday"
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["paper_queue"] == "LOCKED"
    assert payload["guardrails"]["live"] == "FROZEN"

    assert one_minute["timeframe"] == "1m"
    assert one_minute["gate_passed"] is False
    assert one_minute["metrics"]["trade_count"] >= 100
    assert one_minute["metrics"]["fill_count"] == one_minute["metrics"]["trade_count"] * 2
    assert one_minute["metrics"]["profit_factor"] < 1.0
    assert one_minute["manifest"]["complete"] is True
    assert one_minute["manifest"]["paper_queue"] == "LOCKED"
    assert one_minute["manifest"]["live"] == "FROZEN"

    assert five_minute["timeframe"] == "5m"
    assert five_minute["gate_passed"] is True
    assert five_minute["metrics"]["trade_count"] == 78
    assert five_minute["metrics"]["fill_count"] == 156
    assert five_minute["metrics"]["profit_factor"] == pytest.approx(2.647434)
    assert five_minute["metrics"]["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert five_minute["metrics"]["regime_pass_rate"] == pytest.approx(0.8)
    assert five_minute["manifest"]["complete"] is True
    assert five_minute["manifest"]["paper_queue"] == "LOCKED"
    assert five_minute["manifest"]["live"] == "FROZEN"


def test_btc_scalping_research_backtest_manifest_contract_complete() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    required = set(payload["manifest_contract"]["required_fields"])

    assert required == {"data_version", "strategy_version", "params", "cost_model", "slippage_model", "commit_hash"}
    assert payload["manifest_contract"]["one_minute_proxy_scalping_complete"] is True
    assert payload["manifest_contract"]["five_minute_drift_guarded_intraday_complete"] is True
    for backtest in payload["backtests"].values():
        assert all(backtest["manifest"]["required_fields_present"].values())


def test_btc_scalping_research_backtest_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["backtests"]["five_minute_drift_guarded_intraday"]["research_only_lock"][
        "candidate_generation_allowed"
    ] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
