from __future__ import annotations

from datetime import datetime
from pathlib import Path

from quant_us.data.minute_quality_gate import (
    MinuteDataQualityReport,
    SUPPORTED_MINUTE_BAR_SIZES,
    inspect_minute_data_quality,
)


def inspect_minute_quality_report(
    data_root: str | Path = "data",
    *,
    symbols: list[str] | None = None,
    vendor: str = "yfinance",
    asset_class: str = "equity",
    bar_sizes: list[str] | tuple[str, ...] = SUPPORTED_MINUTE_BAR_SIZES,
    lookback_trading_days: int = 5,
    as_of: datetime | None = None,
    root_subdir: str = "raw",
) -> MinuteDataQualityReport:
    return inspect_minute_data_quality(
        data_root=data_root,
        symbols=symbols,
        vendor=vendor,
        asset_class=asset_class,
        bar_sizes=bar_sizes,
        lookback_trading_days=lookback_trading_days,
        as_of=as_of,
        root_subdir=root_subdir,
    )
