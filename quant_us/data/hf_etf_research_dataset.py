"""Read-only adapter for manifest-pinned HF Data Library ETF research bars."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
import gc
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


SUPPORTED_BAR_SIZES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 390,
}
REQUIRED_COLUMNS = {"datetime", "Open", "High", "Low", "Close", "Volume", "source"}


@dataclass(frozen=True)
class HFETFManifestEntry:
    symbol: str
    path: Path
    row_count: int
    size_bytes: int
    sha256: str


class HFETFResearchDataset:
    """Load a licensed ETF batch without copying or mutating steward-owned files."""

    def __init__(self, manifest_path: str | Path, *, dataset_root: str | Path | None = None) -> None:
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        if not self.manifest_path.is_file():
            raise FileNotFoundError(f"HF ETF batch manifest not found: {self.manifest_path}")
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.schema_version = str(self.manifest.get("schema_version", ""))
        if self.schema_version not in {
            "hf_data_library_etf_batch_manifest_v1",
            "shared_dataset_manifest_v1",
        }:
            raise ValueError(f"unsupported HF ETF manifest schema: {self.schema_version!r}")
        if self.schema_version == "shared_dataset_manifest_v1" and dataset_root is None:
            raise ValueError("dataset_root is required for shared_dataset_manifest_v1")
        self.dataset_root = (
            Path(dataset_root).expanduser().resolve()
            if dataset_root is not None
            else _discover_repo_root(self.manifest_path)
        )
        self.data_version = str(
            self.manifest.get("dataset_version") or self.manifest.get("data_version", "")
        ).strip()
        self.batch_sha256 = str(
            self.manifest.get("aggregate_sha256") or self.manifest.get("batch_sha256", "")
        ).strip()
        self.blockers = tuple(
            dict.fromkeys(
                str(value)
                for value in [
                    *self.manifest.get("blockers", []),
                    *self.manifest.get("known_gaps", []),
                ]
                if str(value)
            )
        )
        self.entries = self._build_entries()

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.entries)

    def load_bars(
        self,
        *,
        symbols: Iterable[str],
        start: str | date,
        end: str | date,
        bar_size: str = "1d",
    ) -> pd.DataFrame:
        normalized_bar_size = str(bar_size).strip().lower()
        if normalized_bar_size not in SUPPORTED_BAR_SIZES:
            raise ValueError(f"unsupported HF ETF research bar size: {bar_size!r}")
        requested = _normalize_symbols(symbols)
        missing = [symbol for symbol in requested if symbol not in self.entries]
        if missing:
            raise ValueError(f"symbols missing from HF ETF batch manifest: {missing}")
        start_date = date.fromisoformat(str(start)) if not isinstance(start, date) else start
        end_date = date.fromisoformat(str(end)) if not isinstance(end, date) else end
        if end_date < start_date:
            raise ValueError("end date must not precede start date")

        if normalized_bar_size == "1d" and len(requested) > 3:
            tasks = [
                (
                    self.entries[symbol].path,
                    symbol,
                    start_date,
                    end_date,
                    self.data_version,
                )
                for symbol in requested
            ]
            with ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) as executor:
                frames = list(executor.map(_load_daily_worker, tasks))
        else:
            frames = []
            for symbol in requested:
                frames.append(
                    self._load_symbol(
                        self.entries[symbol],
                        start_date=start_date,
                        end_date=end_date,
                        bar_size=normalized_bar_size,
                    )
                )
                gc.collect()
                pa.default_memory_pool().release_unused()
        non_empty = [frame for frame in frames if not frame.empty]
        if not non_empty:
            return pd.DataFrame()
        combined = (
            pd.concat(non_empty, ignore_index=True)
            .sort_values(["timestamp_utc", "symbol"])
            .reset_index(drop=True)
        )
        combined.attrs.update(self.research_metadata())
        return combined

    def research_metadata(self) -> dict[str, Any]:
        return {
            "provider": "hf_data_library",
            "data_version": self.data_version,
            "batch_sha256": self.batch_sha256,
            "manifest_path": str(self.manifest_path),
            "research_only": True,
            "promotion_clean_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "blockers": list(self.blockers),
        }

    def _build_entries(self) -> dict[str, HFETFManifestEntry]:
        if self.schema_version == "shared_dataset_manifest_v1":
            return self._build_shared_entries()
        entries: dict[str, HFETFManifestEntry] = {}
        for raw in self.manifest.get("entries", []):
            symbol = str(raw.get("ticker", "")).strip().upper()
            if not symbol or symbol in entries:
                raise ValueError(f"invalid or duplicate ticker in HF ETF manifest: {symbol!r}")
            if raw.get("critical_quality_failures"):
                raise ValueError(f"critical quality failures recorded for {symbol}")
            columns = {str(value) for value in raw.get("schema_columns", [])}
            missing_columns = sorted(REQUIRED_COLUMNS.difference(columns))
            if missing_columns:
                raise ValueError(f"HF ETF manifest entry {symbol} missing columns: {missing_columns}")
            path = (self.dataset_root / str(raw.get("path", ""))).resolve()
            try:
                path.relative_to(self.dataset_root)
            except ValueError as exc:
                raise ValueError(f"HF ETF manifest path escapes dataset root: {path}") from exc
            if not path.is_file():
                raise FileNotFoundError(f"HF ETF parquet missing for {symbol}: {path}")
            expected_size = int(raw.get("size_bytes", 0) or 0)
            if expected_size and path.stat().st_size != expected_size:
                raise ValueError(f"HF ETF parquet size mismatch for {symbol}: {path}")
            entries[symbol] = HFETFManifestEntry(
                symbol=symbol,
                path=path,
                row_count=int(raw.get("row_count", 0) or 0),
                size_bytes=expected_size,
                sha256=str(raw.get("sha256", "")),
            )
        if not entries:
            raise ValueError("HF ETF batch manifest has no entries")
        return entries

    def _build_shared_entries(self) -> dict[str, HFETFManifestEntry]:
        entries: dict[str, HFETFManifestEntry] = {}
        for raw in self.manifest.get("files", []):
            relative = Path(str(raw.get("path", "")))
            parent = relative.parent.name
            symbol = parent.removeprefix("symbol=").strip().upper()
            if not symbol or symbol in entries:
                raise ValueError(f"invalid or duplicate ticker in shared HF ETF manifest: {symbol!r}")
            path = (self.dataset_root / relative).resolve()
            try:
                path.relative_to(self.dataset_root)
            except ValueError as exc:
                raise ValueError(f"shared HF ETF manifest path escapes dataset root: {path}") from exc
            if not path.is_file():
                raise FileNotFoundError(f"shared HF ETF parquet missing for {symbol}: {path}")
            expected_size = int(raw.get("bytes", 0) or 0)
            if expected_size and path.stat().st_size != expected_size:
                raise ValueError(f"shared HF ETF parquet size mismatch for {symbol}: {path}")
            entries[symbol] = HFETFManifestEntry(
                symbol=symbol,
                path=path,
                row_count=0,
                size_bytes=expected_size,
                sha256=str(raw.get("sha256", "")),
            )
        if not entries:
            raise ValueError("shared HF ETF batch manifest has no files")
        return entries

    def _load_symbol(
        self,
        entry: HFETFManifestEntry,
        *,
        start_date: date,
        end_date: date,
        bar_size: str,
    ) -> pd.DataFrame:
        start_local = pd.Timestamp(start_date)
        end_local = pd.Timestamp(end_date + timedelta(days=1))
        if bar_size == "1d":
            frame = _load_daily_streaming(
                entry.path,
                symbol=entry.symbol,
                start_local=start_local,
                end_local=end_local,
            )
            frame["source"] = "hf_data_library"
            frame["adjusted_flag"] = True
            frame["data_version"] = self.data_version
            return frame
        read_kwargs: dict[str, Any] = {
            "columns": ["datetime", "Open", "High", "Low", "Close", "Volume", "source"]
        }
        datetime_type = pq.read_schema(entry.path).field("datetime").type
        if pa.types.is_timestamp(datetime_type):
            read_kwargs["filters"] = [
                ("datetime", ">=", start_local),
                ("datetime", "<", end_local),
            ]
        frame = pd.read_parquet(entry.path, **read_kwargs)
        if frame.empty:
            return frame
        local_timestamp = pd.to_datetime(frame["datetime"], errors="coerce")
        if local_timestamp.dt.tz is None:
            local_timestamp = local_timestamp.dt.tz_localize(
                "America/New_York", ambiguous="raise", nonexistent="raise"
            )
        else:
            local_timestamp = local_timestamp.dt.tz_convert("America/New_York")
        frame = frame.assign(
            timestamp_utc=local_timestamp.dt.tz_convert("UTC"),
            symbol=entry.symbol,
            provider_subsource=frame["source"].astype("string").str.lower(),
        )
        frame = frame.loc[
            (local_timestamp.dt.tz_localize(None) >= start_local)
            & (local_timestamp.dt.tz_localize(None) < end_local)
        ]
        frame = frame.rename(
            columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
        )
        frame = frame.drop(columns=["datetime", "source"]).dropna(
            subset=["timestamp_utc", "open", "high", "low", "close", "volume"]
        )
        frame = _resample_rth(frame, bar_size)
        frame["source"] = "hf_data_library"
        frame["adjusted_flag"] = True
        frame["data_version"] = self.data_version
        return frame


def _resample_rth(frame: pd.DataFrame, bar_size: str) -> pd.DataFrame:
    local = frame["timestamp_utc"].dt.tz_convert("America/New_York")
    minute_of_day = local.dt.hour * 60 + local.dt.minute
    rth = frame.loc[
        (minute_of_day >= 570) & (minute_of_day < 960) & (local.dt.dayofweek < 5)
    ].copy()
    if rth.empty or bar_size == "1m":
        return rth.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    local = rth["timestamp_utc"].dt.tz_convert("America/New_York")
    rth["session"] = local.dt.strftime("%Y-%m-%d")
    if bar_size == "1d":
        group_keys = ["session"]
    else:
        minute_of_day = local.dt.hour * 60 + local.dt.minute
        rth["bucket"] = ((minute_of_day - 570) // SUPPORTED_BAR_SIZES[bar_size]).astype(int)
        group_keys = ["session", "bucket"]
    result = (
        rth.groupby(group_keys, sort=True, observed=True)
        .agg(
            symbol=("symbol", "first"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            provider_subsource=("provider_subsource", "last"),
        )
        .reset_index()
    )
    session_open = pd.to_datetime(result["session"] + " 09:30:00").dt.tz_localize(
        "America/New_York", ambiguous="raise", nonexistent="raise"
    )
    if bar_size == "1d":
        elapsed_minutes = pd.Series(390, index=result.index)
    else:
        elapsed_minutes = ((result["bucket"] + 1) * SUPPORTED_BAR_SIZES[bar_size]).clip(
            upper=390
        )
    result["timestamp_utc"] = (
        session_open + pd.to_timedelta(elapsed_minutes, unit="m")
    ).dt.tz_convert("UTC")
    result = result.drop(columns=["session", "bucket"], errors="ignore")
    return result.sort_values("timestamp_utc")


def _load_daily_streaming(
    path: Path,
    *,
    symbol: str,
    start_local: pd.Timestamp,
    end_local: pd.Timestamp,
) -> pd.DataFrame:
    dataset = ds.dataset(path, format="parquet")
    datetime_type = dataset.schema.field("datetime").type
    filter_expression = None
    if pa.types.is_timestamp(datetime_type):
        filter_expression = (
            (ds.field("datetime") >= start_local.to_pydatetime())
            & (ds.field("datetime") < end_local.to_pydatetime())
        )
    scanner = dataset.scanner(
        columns=["datetime", "Open", "High", "Low", "Close", "Volume"],
        filter=filter_expression,
        batch_size=20_000,
        use_threads=False,
    )
    partials: list[pd.DataFrame] = []
    for batch in scanner.to_batches():
        frame = batch.to_pandas()
        local_timestamp = pd.to_datetime(frame["datetime"], errors="coerce")
        if local_timestamp.dt.tz is not None:
            local_timestamp = local_timestamp.dt.tz_convert("America/New_York").dt.tz_localize(None)
        minute_of_day = local_timestamp.dt.hour * 60 + local_timestamp.dt.minute
        mask = (
            (local_timestamp >= start_local)
            & (local_timestamp < end_local)
            & (minute_of_day >= 570)
            & (minute_of_day < 960)
            & (local_timestamp.dt.dayofweek < 5)
        )
        if not mask.any():
            continue
        working = frame.loc[mask].copy()
        working["local_timestamp"] = local_timestamp.loc[mask]
        working["session"] = working["local_timestamp"].dt.strftime("%Y-%m-%d")
        partials.append(
            working.groupby("session", sort=True, observed=True)
            .agg(
                first_timestamp=("local_timestamp", "min"),
                last_timestamp=("local_timestamp", "max"),
                open=("Open", "first"),
                high=("High", "max"),
                low=("Low", "min"),
                close=("Close", "last"),
                volume=("Volume", "sum"),
            )
            .reset_index()
        )
    if not partials:
        return pd.DataFrame()
    partial = pd.concat(partials, ignore_index=True).sort_values(
        ["session", "first_timestamp", "last_timestamp"]
    )
    result = (
        partial.groupby("session", sort=True, observed=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )
    session_close = pd.to_datetime(result["session"] + " 16:00:00").dt.tz_localize(
        "America/New_York", ambiguous="raise", nonexistent="raise"
    )
    result["timestamp_utc"] = session_close.dt.tz_convert("UTC")
    result["symbol"] = symbol
    result["provider_subsource"] = "mixed_source_segments_from_manifest"
    return result.drop(columns=["session"]).sort_values("timestamp_utc")


def _load_daily_worker(
    task: tuple[Path, str, date, date, str],
) -> pd.DataFrame:
    path, symbol, start_date, end_date, data_version = task
    frame = _load_daily_streaming(
        path,
        symbol=symbol,
        start_local=pd.Timestamp(start_date),
        end_local=pd.Timestamp(end_date + timedelta(days=1)),
    )
    frame["source"] = "hf_data_library"
    frame["adjusted_flag"] = True
    frame["data_version"] = data_version
    return frame


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in symbols:
        symbol = str(value).strip().upper()
        if symbol and symbol not in result:
            result.append(symbol)
    if not result:
        raise ValueError("at least one symbol is required")
    return result


def _discover_repo_root(path: Path) -> Path:
    for candidate in (path.parent, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ValueError(f"could not discover dataset worktree root from {path}")
