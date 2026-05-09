from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.types import new_id
from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.cleaners.data_validator import BarDataValidator, DataQualityReport
from quant_us.data.connectors.base import MarketDataConnector
from quant_us.data.connectors.yfinance_data import YFinanceDataConnector
from quant_us.data.storage.parquet_store import ParquetBarStore


@dataclass(frozen=True)
class DataLakeConfig:
    data_root: Path = Path("data")
    raw_subdir: str = "raw"
    cleaned_subdir: str = "cleaned"

    @property
    def raw_root(self) -> Path:
        return self.data_root / self.raw_subdir

    @property
    def cleaned_root(self) -> Path:
        return self.data_root / self.cleaned_subdir


@dataclass(frozen=True)
class DataLakeSyncResult:
    run_id: str
    status: str
    vendor: str
    asset_class: str
    symbol: str
    bar_size: str
    start: datetime
    end: datetime
    rows_received: int
    rows_cleaned: int
    raw_files: list[str]
    cleaned_files: list[str]
    quality: DataQualityReport
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str | None = None


class DataLakeService:
    def __init__(
        self,
        config: DataLakeConfig | None = None,
        cleaner: BarCleaner | None = None,
        validator: BarDataValidator | None = None,
    ) -> None:
        self.config = config or DataLakeConfig()
        self.cleaner = cleaner or BarCleaner()
        self.validator = validator or BarDataValidator()
        self.raw_store = ParquetBarStore(self.config.raw_root)
        self.cleaned_store = ParquetBarStore(self.config.cleaned_root)

    def sync_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        bar_size: str,
        vendor: str = "yfinance",
        asset_class: str = "equity",
    ) -> DataLakeSyncResult:
        created_at = utc_now()
        connector = self._connector(vendor)
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        try:
            raw = connector.fetch_bars(symbol=symbol, start=start_utc, end=end_utc, bar_size=bar_size)
            raw_write = self.raw_store.write_bars(raw, vendor=connector.vendor, asset_class=asset_class, bar_size=bar_size, symbol=symbol)
            clean_result = self.cleaner.clean(raw, symbol=symbol, source=connector.vendor)
            quality = self.validator.validate(clean_result.frame, expected_interval=bar_size)
            clean_write = self.cleaned_store.write_bars(
                clean_result.frame,
                vendor=connector.vendor,
                asset_class=asset_class,
                bar_size=bar_size,
                symbol=symbol,
            )
            return DataLakeSyncResult(
                run_id=new_id("sync"),
                status="completed",
                vendor=connector.vendor,
                asset_class=asset_class,
                symbol=symbol.upper(),
                bar_size=bar_size,
                start=start_utc,
                end=end_utc,
                rows_received=len(raw),
                rows_cleaned=len(clean_result.frame),
                raw_files=[str(path) for path in raw_write.files_written],
                cleaned_files=[str(path) for path in clean_write.files_written],
                quality=quality,
                created_at=created_at,
                completed_at=utc_now(),
            )
        except Exception as exc:
            return DataLakeSyncResult(
                run_id=new_id("sync"),
                status="failed",
                vendor=vendor,
                asset_class=asset_class,
                symbol=symbol.upper(),
                bar_size=bar_size,
                start=start_utc,
                end=end_utc,
                rows_received=0,
                rows_cleaned=0,
                raw_files=[],
                cleaned_files=[],
                quality=DataQualityReport(0, 0, 0, 0, 0),
                created_at=created_at,
                completed_at=utc_now(),
                error=str(exc),
            )

    def read_cleaned_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        bar_size: str,
        vendor: str = "yfinance",
        asset_class: str = "equity",
    ):
        return self.cleaned_store.read_bars(vendor=vendor, asset_class=asset_class, bar_size=bar_size, symbol=symbol, start=start, end=end)

    @staticmethod
    def _connector(vendor: str) -> MarketDataConnector:
        if vendor == "yfinance":
            return YFinanceDataConnector()
        raise ValueError(f"Unsupported data vendor: {vendor}")
