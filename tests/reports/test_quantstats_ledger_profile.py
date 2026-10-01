from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, PortfolioSnapshot
from quant_us.reports.quantstats_ledger_profile import (
    LEDGER_SOURCE_KIND,
    build_quantstats_ledger_profile,
    ledger_returns_from_snapshots,
)


def test_quantstats_profile_accepts_only_ledger_derived_snapshots() -> None:
    snapshots = _snapshots([10000.0, 10100.0, 10050.0, 10200.0])
    fills = [_fill()]

    profile = build_quantstats_ledger_profile(snapshots, fills, source_kind=LEDGER_SOURCE_KIND)

    payload = profile.to_dict()
    assert payload["status"] == "PASS"
    assert payload["pnl_source"] == "ledger_fills"
    assert payload["metric_source"] in {
        "internal_performance",
        "internal_performance_with_quantstats_crosscheck",
    }
    assert payload["metrics"]["total_return_pct"] == 2.0
    assert payload["metrics"]["trade_count"] == 1
    assert payload["diagnostics"]["snapshot_count"] == 4


def test_quantstats_profile_blocks_raw_price_or_signal_equity_sources() -> None:
    profile = build_quantstats_ledger_profile(
        _snapshots([10000.0, 10100.0]),
        [],
        source_kind="raw_price_returns",
    )

    assert profile.status == "BLOCKED"
    assert "unsupported_pnl_source:raw_price_returns" in profile.blockers
    assert profile.metrics == {}


def test_quantstats_profile_blocks_unreconciled_ledgers() -> None:
    profile = build_quantstats_ledger_profile(
        _snapshots([10000.0, 10100.0]),
        [],
        ledger_reconciled=False,
    )

    assert profile.status == "BLOCKED"
    assert "ledger_reconciliation_failed" in profile.blockers


def test_ledger_returns_are_sorted_and_derived_from_snapshot_equity() -> None:
    snapshots = list(reversed(_snapshots([10000.0, 10100.0, 10201.0])))

    returns = ledger_returns_from_snapshots(snapshots)

    assert list(returns.round(4)) == [0.0, 0.01, 0.01]
    assert returns.index.is_monotonic_increasing


def _snapshots(equity_values: list[float]) -> list[PortfolioSnapshot]:
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return [
        PortfolioSnapshot(
            timestamp_utc=start + timedelta(days=i),
            equity=equity,
            cash=equity,
            gross_exposure=0.0,
            net_exposure=0.0,
        )
        for i, equity in enumerate(equity_values)
    ]


def _fill() -> Fill:
    return Fill(
        order_id="order-1",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=10.0,
        price=100.0,
        commission=1.0,
        filled_at=datetime(2026, 1, 2, 15, 30, tzinfo=timezone.utc),
        broker="paper",
    )
