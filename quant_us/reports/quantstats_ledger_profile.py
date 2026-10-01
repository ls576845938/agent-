"""QuantStats-facing profile built only from ledger-derived equity.

QuantStats is useful for tear sheets and familiar performance metrics, but it
must stay downstream of the platform's canonical ledger PnL path. This adapter
therefore accepts PortfolioSnapshot + Fill evidence and refuses raw price-return
inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quant_us.backtest.performance import compute_performance
from quant_us.core.types import Fill, PortfolioSnapshot

LEDGER_SOURCE_KIND = "ledger_fills"


@dataclass(frozen=True)
class QuantStatsLedgerProfile:
    status: str
    source_kind: str
    pnl_source: str
    quantstats_available: bool
    metric_source: str
    metrics: dict[str, float | int]
    quantstats_metrics: dict[str, float] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_kind": self.source_kind,
            "pnl_source": self.pnl_source,
            "quantstats_available": self.quantstats_available,
            "metric_source": self.metric_source,
            "metrics": dict(self.metrics),
            "quantstats_metrics": dict(self.quantstats_metrics),
            "blockers": list(self.blockers),
            "diagnostics": dict(self.diagnostics),
        }


def build_quantstats_ledger_profile(
    snapshots: list[PortfolioSnapshot],
    fills: list[Fill],
    *,
    source_kind: str = LEDGER_SOURCE_KIND,
    ledger_reconciled: bool = True,
    periods_per_year: float = 252.0,
) -> QuantStatsLedgerProfile:
    """Build a tear-sheet-ready profile from canonical ledger evidence.

    Parameters
    ----------
    snapshots:
        Ledger-derived portfolio snapshots. These are the only accepted equity
        source; raw market prices or strategy signal equity are intentionally
        unsupported here.
    fills:
        Fill records used to derive turnover and trade count.
    source_kind:
        Must be ``ledger_fills``. Any other value indicates a non-canonical PnL
        path and is rejected.
    ledger_reconciled:
        Caller-provided reconciliation state. A failed reconciliation blocks the
        profile instead of producing attractive-looking metrics.
    """

    blockers: list[str] = []
    if source_kind != LEDGER_SOURCE_KIND:
        blockers.append(f"unsupported_pnl_source:{source_kind}")
    if not ledger_reconciled:
        blockers.append("ledger_reconciliation_failed")
    if not snapshots:
        blockers.append("missing_portfolio_snapshots")

    if blockers:
        return QuantStatsLedgerProfile(
            status="BLOCKED",
            source_kind=source_kind,
            pnl_source=LEDGER_SOURCE_KIND,
            quantstats_available=_quantstats_stats_module() is not None,
            metric_source="none",
            metrics={},
            blockers=blockers,
            diagnostics={"snapshot_count": len(snapshots), "fill_count": len(fills)},
        )

    metrics = compute_performance(snapshots, fills, periods_per_year=periods_per_year)
    returns = ledger_returns_from_snapshots(snapshots)
    qs_stats = _quantstats_stats_module()
    quantstats_metrics: dict[str, float] = {}
    metric_source = "internal_performance"
    if qs_stats is not None:
        quantstats_metrics = _compute_quantstats_metrics(qs_stats, returns)
        metric_source = "internal_performance_with_quantstats_crosscheck"

    return QuantStatsLedgerProfile(
        status="PASS",
        source_kind=source_kind,
        pnl_source=LEDGER_SOURCE_KIND,
        quantstats_available=qs_stats is not None,
        metric_source=metric_source,
        metrics=metrics,
        quantstats_metrics=quantstats_metrics,
        diagnostics={
            "snapshot_count": len(snapshots),
            "fill_count": len(fills),
            "first_snapshot": snapshots[0].timestamp_utc.isoformat(),
            "last_snapshot": snapshots[-1].timestamp_utc.isoformat(),
            "returns_count": int(len(returns)),
        },
    )


def ledger_returns_from_snapshots(snapshots: list[PortfolioSnapshot]) -> pd.Series:
    """Return pct-change series from ledger-derived snapshot equity only."""

    equity = pd.Series(
        [snapshot.equity for snapshot in snapshots],
        index=pd.DatetimeIndex([snapshot.timestamp_utc for snapshot in snapshots]),
        dtype="float64",
    ).sort_index()
    return equity.pct_change().fillna(0.0)


def _quantstats_stats_module() -> Any | None:
    try:
        from quantstats import stats as qs_stats
    except Exception:
        return None
    return qs_stats


def _compute_quantstats_metrics(qs_stats: Any, returns: pd.Series) -> dict[str, float]:
    metrics: dict[str, float] = {}
    candidates = {
        "cagr": "cagr",
        "sharpe": "sharpe",
        "max_drawdown": "max_drawdown",
        "volatility": "volatility",
    }
    for output_name, attr_name in candidates.items():
        fn = getattr(qs_stats, attr_name, None)
        if fn is None:
            continue
        try:
            metrics[output_name] = round(float(fn(returns)), 6)
        except Exception:
            continue
    return metrics


__all__ = [
    "LEDGER_SOURCE_KIND",
    "QuantStatsLedgerProfile",
    "build_quantstats_ledger_profile",
    "ledger_returns_from_snapshots",
]
