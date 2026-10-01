from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_btc_only_trend_v0_report import build_btc_only_trend_v0_report


def test_btc_only_trend_v0_current_history_is_proxy_only(tmp_path: Path) -> None:
    payload = build_btc_only_trend_v0_report(
        generated_at="2026-06-23T00:00:00Z",
        output=tmp_path / "btc_only_trend_v0_report.json",
        markdown_output=tmp_path / "btc_only_trend_v0.md",
    )

    assert payload["status"] == "research_proxy_only_insufficient_history_for_full_trend_v0"
    assert payload["not_multi_asset_cta"] is True
    assert payload["data_requirements"]["available_daily_rows"] < 220
    assert payload["data_requirements"]["ma120_200_ready"] is False
    assert payload["data_requirements"]["twelve_month_momentum_ready"] is False
    assert payload["guardrails"]["spot_or_low_leverage_first"] is True
    assert payload["guardrails"]["high_leverage_perpetual_not_allowed_for_v0"] is True
    assert payload["guardrails"]["order_endpoint_used"] is False

    by_id = {row["strategy_id"]: row for row in payload["strategies"]}
    assert by_id["buy_hold_btc"]["status"] == "ready"
    assert by_id["btc_trend_v0_proxy_vol_target"]["status"] == "ready"
    assert by_id["ma120_200_trend_intended"]["status"] == "insufficient_history"
    assert by_id["ma120_200_trend_vol_target_intended"]["status"] == "insufficient_history"
    assert by_id["twelve_month_momentum_intended"]["status"] == "insufficient_history"

    assert payload["benchmark_comparison"]["btc_trend_v0_proxy_vol_target"]["valid"] is True
    assert payload["benchmark_comparison"]["ma120_200_trend_intended"]["valid"] is False
    assert payload["benchmark_comparison"]["ma120_200_trend_intended"]["drawdown_reduction_vs_buy_hold_pct"] is None
    assert payload["benchmark_comparison"]["ma120_200_trend_vol_target_intended"]["valid"] is False

    markdown = (tmp_path / "btc_only_trend_v0.md").read_text(encoding="utf-8")
    assert "不是多品种 CTA" in markdown
    assert "不能严肃验证 120/200 日均线" in markdown


def test_btc_only_trend_v0_long_daily_history_runs_formal_comparison(tmp_path: Path) -> None:
    bundle = tmp_path / "daily_bundle"
    bundle.mkdir()
    daily_path = bundle / "klines_1d.csv"
    start_ts = 1624406400000
    with daily_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "open_time",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume_contracts",
                "volume_base",
                "volume_quote",
                "confirm",
                "source_record_id",
            ],
        )
        writer.writeheader()
        for day in range(500):
            ts = start_ts + day * 86_400_000
            close = 20000 + day * 50
            timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            writer.writerow(
                {
                    "timestamp": timestamp,
                    "open_time": ts,
                    "symbol": "BTCUSDT",
                    "open": close - 10,
                    "high": close + 100,
                    "low": close - 100,
                    "close": close,
                    "volume_contracts": 1,
                    "volume_base": 1,
                    "volume_quote": close,
                    "confirm": 1,
                    "source_record_id": f"fixture:{ts}",
                }
            )

    payload = build_btc_only_trend_v0_report(
        bundle_dir=bundle,
        output=tmp_path / "btc_only_trend_v0_formal.json",
        markdown_output=tmp_path / "btc_only_trend_v0_formal.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "research_ready"
    assert payload["data_requirements"]["full_trend_rules_ready"] is True
    by_id = {row["strategy_id"]: row for row in payload["strategies"]}
    assert by_id["ma120_200_trend_intended"]["status"] == "ready"
    assert by_id["ma120_200_trend_vol_target_intended"]["status"] == "ready"
    assert by_id["twelve_month_momentum_intended"]["status"] == "ready"
    assert payload["benchmark_comparison"]["ma120_200_trend_vol_target_intended"]["valid"] is True

    markdown = (tmp_path / "btc_only_trend_v0_formal.md").read_text(encoding="utf-8")
    assert "MA 趋势 + 波动率仓位" in markdown
