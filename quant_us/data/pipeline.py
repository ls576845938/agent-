from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.types import new_id
from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.cleaners.bar_cleaner import CleaningResult
from quant_us.data.cleaners.data_validator import BarDataValidator, DataQualityReport
from quant_us.data.connectors.base import MarketDataConnector
from quant_us.data.connectors.yfinance_data import YFinanceDataConnector
from quant_us.data.storage.data_manifest import DataManifestStore, build_manifest_from_quality
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

    @property
    def manifest_root(self) -> Path:
        return self.data_root / "manifests"


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
    data_version: str = ""
    data_manifest_path: str = ""
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
        self.manifest_store = DataManifestStore(self.config.manifest_root)

    def sync_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        bar_size: str,
        vendor: str = "yfinance",
        asset_class: str = "equity",
    ) -> DataLakeSyncResult:
        run_id = new_id("sync")
        created_at = utc_now()
        connector = self._connector(vendor)
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        try:
            raw = connector.fetch_bars(symbol=symbol, start=start_utc, end=end_utc, bar_size=bar_size)
            clean_result = self.cleaner.clean(raw, symbol=symbol, source=connector.vendor)
            quality = self.validator.validate(clean_result.frame, expected_interval=bar_size)
            if raw.empty or clean_result.frame.empty:
                return DataLakeSyncResult(
                    run_id=run_id,
                    status="completed",
                    vendor=connector.vendor,
                    asset_class=asset_class,
                    symbol=symbol.upper(),
                    bar_size=bar_size,
                    start=start_utc,
                    end=end_utc,
                    rows_received=len(raw),
                    rows_cleaned=len(clean_result.frame),
                    raw_files=[],
                    cleaned_files=[],
                    quality=quality,
                    created_at=created_at,
                    completed_at=utc_now(),
                )

            quality_payload = self._build_manifest_quality(
                connector=connector,
                symbol=symbol,
                bar_size=bar_size,
                asset_class=asset_class,
                start=start_utc,
                end=end_utc,
                cleaned=clean_result.frame,
                cleaning=clean_result,
                quality=quality,
            )
            data_version = str(quality_payload["data_version"])
            ingested_at = utc_now()
            raw_to_write = _with_ingestion_metadata(raw, symbol=symbol, source=connector.vendor, data_version=data_version, ingested_at=ingested_at)
            clean_to_write = _with_ingestion_metadata(
                clean_result.frame,
                symbol=symbol,
                source=connector.vendor,
                data_version=data_version,
                ingested_at=ingested_at,
            )
            raw_write = self.raw_store.write_bars(
                raw_to_write,
                vendor=connector.vendor,
                asset_class=asset_class,
                bar_size=bar_size,
                symbol=symbol,
            )
            clean_write = self.cleaned_store.write_bars(
                clean_to_write,
                vendor=connector.vendor,
                asset_class=asset_class,
                bar_size=bar_size,
                symbol=symbol,
            )
            quality_payload["raw_path"] = str(
                _partition_root(self.config.raw_root, connector.vendor, asset_class, bar_size, symbol)
            )
            quality_payload["cleaned_path"] = str(
                _partition_root(self.config.cleaned_root, connector.vendor, asset_class, bar_size, symbol)
            )
            manifest = build_manifest_from_quality(
                quality=quality_payload,
                source=connector.vendor,
                symbol=symbol,
                interval=bar_size,
                asset_class=asset_class,
                raw_path=str(quality_payload["raw_path"]),
                cleaned_path=str(quality_payload["cleaned_path"]),
                requested_start=start_utc.isoformat(),
                requested_end=end_utc.isoformat(),
            )
            manifest_path = self.manifest_store.write(manifest)
            return DataLakeSyncResult(
                run_id=run_id,
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
                data_version=manifest.data_version,
                data_manifest_path=str(manifest_path),
                created_at=created_at,
                completed_at=utc_now(),
            )
        except Exception as exc:
            return DataLakeSyncResult(
                run_id=run_id,
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

    def _build_manifest_quality(
        self,
        *,
        connector: MarketDataConnector,
        symbol: str,
        bar_size: str,
        asset_class: str,
        start: datetime,
        end: datetime,
        cleaned: pd.DataFrame,
        cleaning: CleaningResult,
        quality: DataQualityReport,
    ) -> dict[str, Any]:
        timestamps = pd.to_datetime(cleaned["timestamp_utc"], utc=True) if "timestamp_utc" in cleaned.columns else pd.Series(dtype="datetime64[ns, UTC]")
        first_ts = timestamps.min().isoformat() if not timestamps.empty else start.isoformat()
        last_ts = timestamps.max().isoformat() if not timestamps.empty else end.isoformat()
        expected_rows = _expected_rows_for_us_equity(start=start, end=end, bar_size=bar_size, observed_rows=len(cleaned))
        missing_bars = max(0, expected_rows - int(quality.row_count))
        coverage_pct = 100.0 if expected_rows <= 0 else min(100.0, int(quality.row_count) / expected_rows * 100.0)
        quality_score = _quality_score(
            duplicate_timestamps=int(quality.duplicate_timestamps),
            invalid_ohlc=int(quality.invalid_ohlc),
            non_positive_prices=int(quality.non_positive_prices),
            missing_bars=missing_bars,
            cleaning_loss_rows=int(cleaning.dropped_rows),
            coverage_pct=coverage_pct,
        )
        fingerprint = _fingerprint_bars(
            frame=cleaned,
            source=connector.vendor,
            symbol=symbol,
            bar_size=bar_size,
            start=start,
            end=end,
        )
        data_version = f"qs-{connector.vendor}-{symbol.upper()}-{bar_size}-{fingerprint[:12]}"
        metadata = _connector_quality_metadata(
            connector=connector,
            symbol=symbol,
            start=first_ts,
            end=last_ts,
            bar_size=bar_size,
            frame=cleaned,
            data_root=self.config.cleaned_root,
        )
        metadata.update(
            {
                "actual_source": connector.vendor,
                "data_version": data_version,
                "fingerprint": fingerprint,
                "row_count": int(quality.row_count),
                "expected_rows": int(expected_rows),
                "coverage_pct": round(float(coverage_pct), 4),
                "quality_score": round(float(quality_score), 4),
                "duplicate_timestamps": int(quality.duplicate_timestamps),
                "invalid_ohlc": int(quality.invalid_ohlc),
                "non_positive_prices": int(quality.non_positive_prices),
                "missing_bars": int(missing_bars),
                "cleaning_loss_rows": int(cleaning.dropped_rows),
                "first_timestamp": first_ts,
                "last_timestamp": last_ts,
                "asset_class": asset_class,
                "quality_summary": {
                    "duplicate_bars": int(quality.duplicate_timestamps),
                    "invalid_ohlc_rows": int(quality.invalid_ohlc),
                    "non_positive_price_rows": int(quality.non_positive_prices),
                    "missing_bars": int(missing_bars),
                },
                "issues": _quality_issues(quality, missing_bars=missing_bars),
            }
        )
        return metadata


def _with_ingestion_metadata(
    frame: pd.DataFrame,
    *,
    symbol: str,
    source: str,
    data_version: str,
    ingested_at: datetime,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    working = frame.copy()
    if "symbol" not in working.columns:
        working["symbol"] = symbol.upper()
    else:
        working["symbol"] = working["symbol"].astype(str).str.upper()
    if "source" not in working.columns:
        working["source"] = source
    working["ingested_at"] = ingested_at
    working["data_version"] = data_version
    return working


def _partition_root(root: Path, vendor: str, asset_class: str, bar_size: str, symbol: str) -> Path:
    return root / f"vendor={vendor}" / f"asset_class={asset_class}" / f"bar_size={bar_size}" / f"symbol={symbol.upper()}"


def _connector_quality_metadata(
    *,
    connector: MarketDataConnector,
    symbol: str,
    start: Any,
    end: Any,
    bar_size: str,
    frame: pd.DataFrame,
    data_root: Path,
) -> dict[str, Any]:
    quality_metadata = getattr(connector, "quality_metadata", None)
    if not callable(quality_metadata):
        return {}
    try:
        metadata = quality_metadata(
            symbol=symbol,
            start=start,
            end=end,
            bar_size=bar_size,
            frame=frame,
            data_root=data_root,
        )
    except Exception:
        return {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _fingerprint_bars(
    *,
    frame: pd.DataFrame,
    source: str,
    symbol: str,
    bar_size: str,
    start: datetime,
    end: datetime,
) -> str:
    columns = [column for column in ["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"] if column in frame.columns]
    normalized = frame[columns].copy().sort_values(columns[:2] or None).reset_index(drop=True)
    if "timestamp_utc" in normalized.columns:
        normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True).astype(str)
    hashed_frame = pd.util.hash_pandas_object(normalized, index=False).values.tobytes()
    digest = hashlib.sha256()
    digest.update(f"{source}:{symbol.upper()}:{bar_size}:{start.isoformat()}:{end.isoformat()}:{len(frame)}".encode("utf-8"))
    digest.update(hashed_frame)
    return digest.hexdigest()


def _expected_rows_for_us_equity(
    *,
    start: datetime,
    end: datetime,
    bar_size: str,
    observed_rows: int,
) -> int:
    if end < start:
        return max(0, observed_rows)
    years = tuple(range(start.year, end.year + 1)) or (start.year,)
    calendar = USEquityCalendar.with_holidays(years=years)
    start_day = start.date()
    end_day = end.date()
    trading_days = list(_iter_trading_days(calendar, start_day, end_day))
    if not trading_days:
        return max(0, observed_rows)
    if bar_size == "1d":
        return len(trading_days)
    minutes = _bar_size_minutes(bar_size)
    if minutes <= 0:
        return max(0, observed_rows)
    expected = 0
    for trading_day in trading_days:
        regular_minutes = 210 if calendar.is_early_close(trading_day) else 390
        expected += (regular_minutes + minutes - 1) // minutes
    return max(expected, 0)


def _iter_trading_days(calendar: USEquityCalendar, start: date, end: date):
    current = start
    while current <= end:
        if calendar.is_trading_day(current):
            yield current
        current += timedelta(days=1)


def _bar_size_minutes(bar_size: str) -> int:
    return {
        "1m": 1,
        "2m": 2,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "1h": 60,
    }.get(str(bar_size).lower(), 0)


def _quality_score(
    *,
    duplicate_timestamps: int,
    invalid_ohlc: int,
    non_positive_prices: int,
    missing_bars: int,
    cleaning_loss_rows: int,
    coverage_pct: float,
) -> float:
    penalty = (
        duplicate_timestamps * 2.0
        + invalid_ohlc * 5.0
        + non_positive_prices * 5.0
        + missing_bars * 0.1
        + cleaning_loss_rows * 0.05
        + max(0.0, 90.0 - coverage_pct)
    )
    return max(0.0, min(100.0, 100.0 - penalty))


def _quality_issues(quality: DataQualityReport, *, missing_bars: int) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if quality.duplicate_timestamps:
        issues.append({"type": "duplicate_timestamps", "severity": "error", "count": str(quality.duplicate_timestamps)})
    if quality.invalid_ohlc:
        issues.append({"type": "invalid_ohlc", "severity": "error", "count": str(quality.invalid_ohlc)})
    if quality.non_positive_prices:
        issues.append({"type": "non_positive_prices", "severity": "error", "count": str(quality.non_positive_prices)})
    if missing_bars:
        issues.append({"type": "missing_bars", "severity": "warning", "count": str(missing_bars)})
    return issues
