from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.monitoring_snapshot import (
    build_btc_monitoring_snapshot,
    render_btc_monitoring_snapshot_html,
    render_btc_monitoring_snapshot_markdown,
)
from scripts.build_btc_monitoring_snapshot import load_market_1h_status


TS = datetime(2026, 6, 29, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def test_btc_monitoring_snapshot_complete_read_only_view() -> None:
    payload = build_btc_monitoring_snapshot(
        generated_at_utc=TS,
        market_1h_status=_market_1h_status(),
        sources=_sources(),
        source_paths={name: f"artifacts/{name}.json" for name in _sources()},
        report_paths={"html": "artifacts/btc_monitoring/latest/btc_monitoring_snapshot.html"},
    )

    assert payload["status"] == "complete"
    assert payload["read_only"] is True
    assert payload["current_state"]["live_order_allowed"] is False
    assert payload["data_freshness"]["market_1h"]["latest_closed_bar_time_utc"] == "2026-06-27T08:59:59.999000+00:00"
    assert payload["data_freshness"]["daily_observation"]["observation_days"] == 5
    assert payload["funding"]["status"] == "funding_ledger_reconciled"
    assert payload["position_target"]["target_weight"] == 0.0
    assert payload["position_target"]["order_required"] is False
    assert payload["paper_fills"]["source"] == "paper_oms_session_contract_evidence"
    assert payload["paper_fills"]["order_count"] == 1
    assert payload["paper_fills"]["fill_count"] == 1
    assert payload["incident_replay"]["current_realtime_data_accessed"] is False
    assert payload["guardrails"] == {
        "live_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }
    assert "btc_monitoring_data_status_artifact_older_than_market_1h" in payload["warnings"]
    assert validate_btc_artifact_schema(payload) == []

    markdown = render_btc_monitoring_snapshot_markdown(payload)
    html = render_btc_monitoring_snapshot_html(payload)
    assert "BTC 只读监控快照" in markdown
    assert "不写 paper 队列" in markdown
    assert "<title>BTC 只读监控快照</title>" in html
    assert "submit_order" not in html


def test_btc_monitoring_snapshot_blocks_missing_critical_source() -> None:
    sources = _sources()
    sources["latest_target"] = None
    payload = build_btc_monitoring_snapshot(
        generated_at_utc=TS,
        market_1h_status=_market_1h_status(),
        sources=sources,
    )

    assert payload["status"] == "blocked"
    assert "btc_monitoring_snapshot_source_missing:latest_target" in payload["blockers"]


def test_btc_monitoring_snapshot_blocks_unsafe_source_flag() -> None:
    sources = _sources()
    sources["daily_observation"] = {
        **sources["daily_observation"],
        "guardrails": {"order_endpoint_used": True, "real_order_submitted": False},
    }
    payload = build_btc_monitoring_snapshot(
        generated_at_utc=TS,
        market_1h_status=_market_1h_status(),
        sources=sources,
    )

    assert payload["status"] == "blocked"
    assert any("order_endpoint_used=true" in blocker for blocker in payload["blockers"])


def test_load_market_1h_status_reads_latest_closed_bar(tmp_path) -> None:
    db_path = tmp_path / "market_data.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            create table market_klines (
                exchange text, symbol text, interval text, open_time text, close_time text,
                close real, volume real, source text, ingested_at text, updated_at text,
                close_time_ms integer
            )
            """
        )
        connection.execute(
            """
            insert into market_klines values (
                'binance_spot', 'BTCUSDT', '1h', '2026-06-27T08:00:00+00:00',
                '2026-06-27T08:59:59.999000+00:00', 60454.67, 0.20325,
                'binance_rest', '2026-06-27T09:01:00+00:00',
                '2026-06-27T09:01:00+00:00', 1782550799999
            )
            """
        )

    status = load_market_1h_status(db_path, generated_at_utc=TS)

    assert status["status"] == "pass"
    assert status["row_count"] == 1
    assert status["latest_close_time_utc"] == "2026-06-27T08:59:59.999000+00:00"
    assert status["closed_bar_only"] is True


def _market_1h_status() -> dict[str, object]:
    return {
        "status": "pass",
        "exchange": "binance_spot",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "row_count": 21801,
        "latest_close_time_utc": "2026-06-27T08:59:59.999000+00:00",
        "latest_close": 60454.67,
        "latest_volume": 0.20325,
        "latest_ingested_at_utc": "2026-06-27T15:49:05.390297+00:00",
        "closed_bar_only": True,
    }


def _sources() -> dict[str, dict[str, object] | None]:
    return {
        "current_status": {"status": "paper_observing", "live_status": "frozen", "generated_at": "2026-06-29T00:00:00Z"},
        "data_status": {
            "status": "pass",
            "generated_at": "2026-06-23T00:00:00Z",
            "coverage": {"sample_end": "2026-05-12T00:00:00+00:00"},
            "blockers": [],
        },
        "gate_dashboard": {
            "status": "complete",
            "paper_state": {"readiness_status": "ready_for_paper_start"},
            "blockers": [],
            "generated_at": "2026-06-29T00:00:00Z",
            "artifact_hash": HASH,
        },
        "daily_observation": {
            "status": "PASS",
            "generated_at": "2026-06-29T03:13:39Z",
            "blockers": [],
            "data": {"sample_end": "2026-06-29T00:00:00Z", "public_rest_only": True},
            "forward_observation": {"observation_days": 5},
            "guardrails": {"simulated_only": True, "order_endpoint_used": False, "real_order_submitted": False},
        },
        "funding_ledger": {
            "generated_at": "2026-06-23T01:48:11Z",
            "blockers": [],
            "funding_info_available": True,
            "funding_rate_available": True,
            "funding_payment_in_ledger": True,
            "funding_adjusted_net_pnl_reconciled": True,
            "funding_interval_hours": 8.0,
            "funding_events_count": 94,
            "promotion_evidence": False,
        },
        "live_readiness": {
            "status": "live_readiness_blocked",
            "generated_at": "2026-06-29T04:07:58Z",
            "blockers": ["btc_live_readiness_forward_observation_less_than_30_days"],
            "forward_observation": {"minimum_complete_days": 30},
            "gate_checks": {"daily_pipeline_pass": True, "forward_observation_complete": False},
            "operational_evidence": {"replay": {"complete": True}},
            "live_order_allowed": False,
        },
        "paper_validation_runtime": {
            "status": "complete",
            "generated_at": "2026-06-29T03:06:57Z",
            "blockers": [],
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
        "paper_validation_replay": {
            "status": "replay_pass",
            "decision": "replay_pass",
            "generated_at": "2026-06-28T00:00:00Z",
            "blockers": [],
            "metadata": {"current_realtime_data_accessed": False},
            "diffs": {"target": {"changed": False}},
        },
        "incident_replay_drill": {
            "status": "complete",
            "generated_at": "2026-06-29T03:09:09Z",
            "blockers": [],
            "scenario_count": 4,
            "required_scenarios": ["data_outage", "funding_gap", "ledger_mismatch", "order_reject"],
        },
        "latest_target": {
            "target": {
                "strategy_id": "btc_trend_raw_t01_twelve_month_momentum",
                "target_position_id": "tgt_001",
                "timestamp_utc": "2026-06-29T00:00:00+00:00",
                "target_weight": 0.0,
                "target_quantity": 0.0,
                "metadata": {
                    "target_notional": 0.0,
                    "order_generation_allowed": True,
                    "perpetual_risk_policy": {"perpetual_allowed": False},
                    "risk_state": {"exchange_available": True},
                },
            }
        },
        "latest_order_intent": {"order_intent": None, "order_endpoint_used": False, "real_order_submitted": False},
        "latest_paper_oms_lifecycle": {
            "order_required": False,
            "reason": "no_order_intent_approved_or_delta_below_minimum",
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
        "paper_oms_session_contract": {
            "status": "complete",
            "generated_at": "2026-06-29T03:09:09Z",
            "order_count": 1,
            "fill_count": 1,
            "execution_quality": {"fill_rate": 1.0, "rejected_order_count": 0},
            "fills": [
                {
                    "fill_id": "fill_001",
                    "client_order_id": "coid_001",
                    "filled_at_utc": "2026-06-29T03:09:10Z",
                    "filled_quantity": 0.01,
                    "fill_price": 100001.0,
                }
            ],
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
    }
