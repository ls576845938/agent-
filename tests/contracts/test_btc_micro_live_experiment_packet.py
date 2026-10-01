from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research.btc_micro_live_experiment_packet import build_btc_micro_live_experiment_packet


def test_btc_micro_live_experiment_packet_builds_1000_rmb_rulebook(tmp_path: Path) -> None:
    context, direction = _fixture_market(funding_rate=0.0)
    depth_path, fill_path = _write_depth_reports(tmp_path)

    report = build_btc_micro_live_experiment_packet(
        output_dir=tmp_path / "out",
        depth_slippage_report_path=depth_path,
        fill_mapping_report_path=fill_path,
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        market_context=context,
        direction=direction,
        rmb_usdt_rate=0.14,
        record_count=3,
    )

    assert report["schema_version"] == "btc_micro_live_experiment_packet_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_micro_live_experiment_packet_observe_only_alert_only_no_order_no_paper_no_live"

    rules = report["experiment_rules"]
    assert rules["total_budget_rmb"] == 1000.0
    assert rules["sleeve_count"] == 10
    assert rules["sleeve_rmb"] == 100.0
    assert rules["max_total_exposed_sleeves"] == 3
    assert rules["research_lines"][0]["leverage"] == 5.0
    assert rules["research_lines"][1]["leverage"] == 10.0

    latest = report["observe_only_recorder"]["records"][-1]
    assert latest["direction"] == "long"
    assert latest["defensive_5x_sleeves"] == 2
    assert latest["attack_10x_sleeves"] == 1
    assert latest["total_exposed_sleeves"] == 3
    assert latest["principal_exposed_rmb"] == 300.0
    assert latest["remaining_principal_pct_after_5pct_spike"] == 100.0
    assert latest["remaining_principal_pct_after_8pct_spike"] == 100.0
    assert latest["remaining_principal_pct_after_10pct_spike"] == 90.0
    assert latest["order_action_allowed"] is False

    alert_ids = {row["alert_id"] for row in report["alert_only"]["alerts"]}
    assert "defensive_5x_entry_signal" in alert_ids
    assert "attack_10x_condition" in alert_ids
    assert "spike_risk_near_floor" in alert_ids
    assert all(row["order_action_allowed"] is False for row in report["alert_only"]["alerts"])

    rehearsal_rows = report["no_trade_execution_rehearsal"]["rows"]
    assert {row["line_id"] for row in rehearsal_rows} == {
        "defensive_5x_spike_sleeve",
        "actual_10x_attack_limited",
    }
    assert all(row["order_endpoint_used"] is False for row in rehearsal_rows)
    assert all(row["paper_order_allowed"] is False for row in rehearsal_rows)
    assert all(row["live_order_allowed"] is False for row in rehearsal_rows)
    assert any(row["conforms_to_1000_rmb_rules"] is True for row in rehearsal_rows)
    assert report["pre_live_checklist"]["observe_only_allowed"] is True
    assert report["pre_live_checklist"]["paper_allowed"] is False
    assert report["pre_live_checklist"]["live_allowed"] is False
    assert report["pre_live_checklist"]["broker_or_order_allowed"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False

    summary = (tmp_path / "out" / "btc_micro_live_experiment_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 1000 RMB 实验规则包" in summary
    assert "不下单" in summary


def test_btc_micro_live_experiment_packet_blocks_funding_crowding(tmp_path: Path) -> None:
    context, direction = _fixture_market(funding_rate=0.001)
    depth_path, fill_path = _write_depth_reports(tmp_path)

    report = build_btc_micro_live_experiment_packet(
        output_dir=tmp_path / "out",
        depth_slippage_report_path=depth_path,
        fill_mapping_report_path=fill_path,
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        market_context=context,
        direction=direction,
        rmb_usdt_rate=0.14,
        record_count=3,
    )

    latest = report["observe_only_recorder"]["records"][-1]
    assert latest["funding_pressure"] == "crowded_abs"
    assert latest["total_exposed_sleeves"] == 0
    alert_ids = {row["alert_id"] for row in report["alert_only"]["alerts"]}
    assert "funding_crowded" in alert_ids
    assert report["pre_live_checklist"]["current_risk_level"] == "blocked"
    assert report["pre_live_checklist"]["max_principal_this_signal_rmb"] == 0.0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False


def _fixture_market(*, funding_rate: float) -> tuple[dict, pd.Series]:
    index = pd.date_range("2026-07-01T00:00:00Z", periods=4, freq="4h")
    bars = pd.DataFrame(
        {
            "open_time": index - pd.Timedelta(hours=4),
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [101.0, 102.0, 103.0, 104.0],
            "volume": [10.0, 10.0, 10.0, 10.0],
        },
        index=index,
    )
    derivatives = pd.DataFrame(
        {
            "open_interest_usd": [1_000_000.0] * 4,
            "funding_rate": [funding_rate] * 4,
            "long_short_ratio": [1.0] * 4,
            "top_trader_long_short_ratio": [1.0] * 4,
            "taker_buy_sell_ratio": [1.0] * 4,
        },
        index=index,
    )
    direction = pd.Series([0.0, 1.0, 1.0, 1.0], index=index)
    return {"bars_4h": bars, "derivatives_4h": derivatives, "blockers": []}, direction


def _write_depth_reports(tmp_path: Path) -> tuple[Path, Path]:
    depth_path = tmp_path / "depth.json"
    fill_path = tmp_path / "fill.json"
    depth_path.write_text(
        json.dumps(
            {
                "depth_snapshot_available": True,
                "depth_aware": False,
                "depth_aware_slippage_history_verified": False,
                "latest_snapshot": {"mid_price": 104.0, "spread_bps": 1.0},
                "market_order_simulations": [
                    {
                        "side": "buy",
                        "notional_usd": 1000.0,
                        "complete": True,
                        "slippage_bps_vs_mid": 0.2,
                        "levels_used": 1,
                    },
                    {
                        "side": "sell",
                        "notional_usd": 1000.0,
                        "complete": True,
                        "slippage_bps_vs_mid": 0.2,
                        "levels_used": 1,
                    },
                ],
                "blockers": ["depth_history_not_gate_eligible"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fill_path.write_text(
        json.dumps(
            {
                "mapped_fill_count": 0,
                "blockers": ["fill_mapping_unverified"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return depth_path, fill_path
