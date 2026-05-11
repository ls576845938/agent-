"""US equity data ingestion pipeline.

Downloads bars via yfinance/Alpaca, lands as Parquet in data lake,
tags sessions, generates data_manifest per dataset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import SessionName
from quant_us.data.connectors.yfinance_data import YFinanceDataConnector
from quant_us.data.storage.data_manifest import DataManifestStore, build_manifest_from_quality
from quant_us.data.storage.parquet_store import ParquetBarStore


@dataclass
class USEquityIngestionConfig:
    data_root: str = "data"
    source: str = "yfinance"
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL"])
    intervals: list[str] = field(default_factory=lambda: ["1d"])
    start: str = "2020-01-01"
    end: str = ""
    generate_manifest: bool = True


@dataclass
class IngestionResult:
    symbol: str
    interval: str
    path: str
    row_count: int
    data_version: str
    manifest_path: str
    error: str = ""


class USEquityIngestionPipeline:
    """Ingest US equity bars, land as Parquet, and generate manifests.

    Data lake layout:
        data/raw/vendor={vendor}/asset_class=equity/bar_size={size}/symbol={sym}/date={date}.parquet
    """

    def __init__(self, config: USEquityIngestionConfig | None = None) -> None:
        self.config = config or USEquityIngestionConfig()
        self.calendar = USEquityCalendar.with_holidays()
        self.manifest_store = DataManifestStore(Path(self.config.data_root) / "manifests")
        self._connector = YFinanceDataConnector()
        self.cleaned_store = ParquetBarStore(Path(self.config.data_root) / "cleaned")

    def run(self) -> list[IngestionResult]:
        results: list[IngestionResult] = []
        end_str = self.config.end or date.today().isoformat()

        for symbol in self.config.symbols:
            for interval in self.config.intervals:
                try:
                    result = self._ingest_one(symbol, interval, self.config.start, end_str)
                    results.append(result)
                    print(f"  {symbol} {interval}: {result.row_count} rows → {result.data_version}")
                except Exception as exc:
                    results.append(IngestionResult(
                        symbol=symbol, interval=interval, path="",
                        row_count=0, data_version="", manifest_path="", error=str(exc),
                    ))
                    print(f"  FAIL {symbol} {interval}: {exc}")

        return results

    def _ingest_one(self, symbol: str, interval: str, start: str, end: str) -> IngestionResult:
        start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)

        raw = self._connector.fetch_bars(symbol, start_dt, end_dt, interval)
        if raw.empty:
            return IngestionResult(symbol=symbol, interval=interval, path="", row_count=0, data_version="", manifest_path="", error="No data returned")

        cleaned = self._clean_bars(raw, interval)
        if cleaned.empty:
            return IngestionResult(symbol=symbol, interval=interval, path="", row_count=0, data_version="", manifest_path="", error="All bars filtered during cleaning")

        quality = self._quality_report(cleaned, symbol, interval, start, end)
        data_version = quality["data_version"]
        cleaned["symbol"] = symbol.upper()
        cleaned["data_version"] = data_version

        parquet_path = self._write_parquet(cleaned, symbol, interval)
        clean_write = self.cleaned_store.write_bars(
            cleaned,
            vendor=self.config.source,
            asset_class="equity",
            bar_size=interval,
            symbol=symbol,
        )
        cleaned_path = (
            Path(self.config.data_root)
            / "cleaned"
            / f"vendor={self.config.source}"
            / "asset_class=equity"
            / f"bar_size={interval}"
            / f"symbol={symbol.upper()}"
        )
        quality.update(
            self._connector.quality_metadata(
                symbol=symbol,
                start=quality.get("first_timestamp", start),
                end=quality.get("last_timestamp", end),
                bar_size=interval,
                frame=cleaned,
                data_root=Path(self.config.data_root) / "cleaned",
            )
        )
        quality["raw_path"] = str(parquet_path)
        quality["cleaned_path"] = str(cleaned_path)
        quality["cleaned_files"] = [str(path) for path in clean_write.files_written]

        manifest = build_manifest_from_quality(
            quality=quality,
            source=self.config.source,
            symbol=symbol,
            interval=interval,
            asset_class="equity",
            raw_path=str(parquet_path),
            cleaned_path=str(cleaned_path),
            requested_start=start,
            requested_end=end,
        )
        if self.config.generate_manifest:
            manifest_path = str(self.manifest_store.write(manifest))
        else:
            manifest_path = ""

        return IngestionResult(
            symbol=symbol,
            interval=interval,
            path=str(parquet_path),
            row_count=len(cleaned),
            data_version=manifest.data_version,
            manifest_path=manifest_path,
        )

    def _clean_bars(self, raw: pd.DataFrame, interval: str) -> pd.DataFrame:
        df = raw.copy()
        ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True)

        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df[(df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)]
        df = df[df["high"] >= df["low"]]
        df = df.drop_duplicates(subset=[ts_col], keep="last")
        df = df.sort_values(ts_col)

        df = self._tag_sessions(df, ts_col)

        # Per-bar metadata: source, ingested_at, data_version
        now_utc = utc_now()
        df["source"] = self.config.source
        df["ingested_at"] = now_utc
        # data_version is per-symbol-per-interval, set later in _ingest_one

        return df

    def _tag_sessions(self, df: pd.DataFrame, ts_col: str) -> pd.DataFrame:
        sessions: list[str] = []
        for idx in df.index:
            ts = df.loc[idx, ts_col]
            session = self.calendar.session_for(ts)
            sessions.append(session.value)
        df["session"] = sessions
        return df

    def _write_parquet(self, df: pd.DataFrame, symbol: str, interval: str) -> Path:
        root = Path(self.config.data_root) / "raw" / f"vendor={self.config.source}" / "asset_class=equity" / f"bar_size={interval}" / f"symbol={symbol}"
        root.mkdir(parents=True, exist_ok=True)

        ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
        df["date"] = pd.to_datetime(df[ts_col], utc=True).dt.date

        for d, group in df.groupby("date"):
            path = root / f"date={d.isoformat()}.parquet"
            if path.exists():
                existing = pd.read_parquet(path)
                group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(subset=[ts_col], keep="last")
            group = group.sort_values(ts_col)
            out = group.drop(columns=["date"])
            out.to_parquet(path, index=False)

        return root

    def _quality_report(self, df: pd.DataFrame, symbol: str, interval: str, start: str, end: str) -> dict[str, Any]:
        import hashlib

        from quant_us.data.quality_reports import generate_daily_quality_report

        ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
        timestamps = pd.to_datetime(df[ts_col], utc=True)
        n = len(df)
        duplicates = int(timestamps.duplicated().sum())
        prices = df[["open", "high", "low", "close"]]
        invalid_ohlc = int(((prices["high"] < prices["low"]) | (prices["high"] < prices[["open", "close"]].max(axis=1)) | (prices["low"] > prices[["open", "close"]].min(axis=1))).sum())
        non_positive = int(((prices <= 0) | prices.isna()).any(axis=1).sum())

        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        if interval == "1d":
            expected = len(pd.bdate_range(start=start_ts, end=end_ts))
        else:
            expected = n

        coverage = round((1.0 - max(0, expected - n) / max(1, expected)) * 100.0, 4)
        score = max(0.0, 100.0 - duplicates * 2.0 - invalid_ohlc * 5.0 - non_positive * 5.0 - max(0, expected - n) * 0.1)

        fingerprint_raw = f"{symbol}:{interval}:{start}:{end}:{n}:{duplicates}".encode()
        fingerprint = hashlib.sha256(fingerprint_raw).hexdigest()
        data_version = f"qs-{self.config.source}-{symbol.upper()}-{interval}-{fingerprint[:12]}"

        # Generate the six-category quality reports.
        report_set = generate_daily_quality_report(
            df, symbol, (start_ts.date(), end_ts.date())
        )
        issues = report_set.to_issues_list()

        return {
            "data_version": data_version,
            "fingerprint": fingerprint,
            "row_count": n,
            "expected_rows": expected,
            "coverage_pct": coverage,
            "quality_score": round(score, 4),
            "duplicate_timestamps": duplicates,
            "invalid_ohlc": invalid_ohlc,
            "non_positive_prices": non_positive,
            "missing_bars": max(0, expected - n),
            "cleaning_loss_rows": 0,
            "first_timestamp": timestamps.min().isoformat() if not timestamps.empty else "",
            "last_timestamp": timestamps.max().isoformat() if not timestamps.empty else "",
            "issues": issues,
        }
