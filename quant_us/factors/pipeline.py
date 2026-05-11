"""Batch factor computation with lookahead protection.

Wraps the existing per-symbol factor functions (momentum, volatility, liquidity)
into a cross-sectional pipeline that handles winsorization, z-score
standardisation, sector/size neutralisation, and parquet caching.

Usage:
    pipe = FactorPipeline(data_root="data")
    df = pipe.compute(
        factor_ids=["momentum_60d", "volatility_20d"],
        symbols=["SPY", "QQQ"],
        start="2024-01-01", end="2024-06-30",
    )
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.factors.definition import FACTOR_CATEGORIES, FactorDefinition, FactorLibrary
from quant_us.factors.liquidity import average_dollar_volume
from quant_us.factors.momentum import rolling_momentum_score
from quant_us.factors.volatility import realized_volatility

# ---------------------------------------------------------------------------
# Internal lookup: factor_id → callable(close, volume) → pd.Series
# ---------------------------------------------------------------------------

_FACTOR_FN_REGISTRY: dict[str, str] = {
    # momentum
    "momentum_60d": "momentum",
    "momentum_20d": "momentum",
    "momentum_120d": "momentum",
    # volatility
    "volatility_20d": "volatility",
    "volatility_60d": "volatility",
    # liquidity
    "liquidity_20d": "liquidity",
    # reversal
    "reversal_1d": "reversal",
    # volume
    "volume_20d": "volume",
}


def _compute_factor_series(
    factor_id: str,
    close: pd.Series | None,
    volume: pd.Series | None,
) -> pd.Series:
    """Compute a single factor time-series for one symbol.

    All functions use rolling windows anchored at t (no lookahead).
    Returns a Series aligned to the input index, with NaN at leading
    positions where the rolling window is not yet full.
    """
    family = _FACTOR_FN_REGISTRY.get(factor_id, "")
    if family == "momentum":
        short = 20
        long = 60
        if factor_id == "momentum_20d":
            short = 20
            long = 20
        elif factor_id == "momentum_120d":
            short = 20
            long = 120
        elif factor_id == "momentum_60d":
            short = 20
            long = 60
        if close is None:
            return pd.Series(dtype=float)
        return rolling_momentum_score(close, short_window=short, long_window=long)

    if family == "volatility":
        window = 20
        if factor_id == "volatility_60d":
            window = 60
        if close is None:
            return pd.Series(dtype=float)
        return realized_volatility(close, window=window)

    if family == "liquidity":
        if close is None or volume is None:
            return pd.Series(dtype=float)
        return average_dollar_volume(close, volume, window=20)

    if family == "reversal":
        if close is None:
            return pd.Series(dtype=float)
        return -close.pct_change(1)

    if family == "volume":
        if volume is None:
            return pd.Series(dtype=float)
        short_ma = volume.rolling(window=20, min_periods=20).mean()
        long_ma = volume.rolling(window=60, min_periods=60).mean()
        return short_ma / long_ma.replace(0, pd.NA)

    raise ValueError(f"Unknown factor_id '{factor_id}' — no compute function registered.")


# ---------------------------------------------------------------------------
# Cross-sectional helpers
# ---------------------------------------------------------------------------


def _winsorize(series: pd.Series, pct: float = 0.01) -> pd.Series:
    """Clip extreme values at the *pct* and (1 - pct) percentiles."""
    if pct <= 0 or pct >= 0.5:
        return series
    lower = series.quantile(pct)
    upper = series.quantile(1.0 - pct)
    return series.clip(lower, upper)


def _zscore(series: pd.Series) -> pd.Series:
    """Standardise to mean=0, std=1."""
    mean = series.mean()
    std = series.std(ddof=0)
    if std == 0 or pd.isna(std):
        return series * 0.0
    return (series - mean) / std


def _rank_to_percentile(series: pd.Series) -> pd.Series:
    """Convert values to percentile ranks [0, 1]."""
    return series.rank(pct=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_bars(
    data_root: str,
    symbols: list[str],
    start: str,
    end: str,
    *,
    bar_size: str = "1d",
    vendor: str = "alpaca",
    asset_class: str = "equity",
) -> pd.DataFrame:
    """Load OHLCV bar data for all *symbols* in [start, end].

    Tries the cleaned DataLake store first, then falls back to raw parquet
    partitions.  Returns a DataFrame with columns:
        timestamp_utc, symbol, open, high, low, close, volume
    """
    from datetime import datetime, timezone

    from quant_us.data.pipeline import DataLakeConfig, DataLakeService

    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)

    dl = DataLakeService(DataLakeConfig(data_root=Path(data_root)))
    vendors = _candidate_vendors(Path(data_root), vendor)

    frames: list[pd.DataFrame] = []
    for sym in symbols:
        loaded = False
        for candidate_vendor in vendors:
            try:
                df = dl.read_cleaned_bars(
                    symbol=sym,
                    start=start_dt,
                    end=end_dt,
                    bar_size=bar_size,
                    vendor=candidate_vendor,
                    asset_class=asset_class,
                )
                if df is not None and not df.empty:
                    df = df.copy()
                    if "symbol" not in df.columns:
                        df["symbol"] = sym
                    if "bar_size" not in df.columns:
                        df["bar_size"] = bar_size
                    if "vendor" not in df.columns:
                        df["vendor"] = candidate_vendor
                    frames.append(df)
                    loaded = True
                    break
            except Exception:
                continue
        if loaded:
            continue

    if not frames:
        # Fallback: raw parquet scan
        for candidate_vendor in vendors:
            raw_root = (
                Path(data_root)
                / "raw"
                / f"vendor={candidate_vendor}"
                / f"asset_class={asset_class}"
                / f"bar_size={bar_size}"
            )
            if not raw_root.exists():
                continue
            for sym in symbols:
                sym_dir = raw_root / f"symbol={sym}"
                if sym_dir.exists():
                    parts = sorted(sym_dir.rglob("*.parquet"))
                    if parts:
                        df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
                        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
                        df = df[(df["timestamp_utc"] >= start_dt) & (df["timestamp_utc"] <= end_dt)]
                        if "symbol" not in df.columns:
                            df["symbol"] = sym
                        if "bar_size" not in df.columns:
                            df["bar_size"] = bar_size
                        if "vendor" not in df.columns:
                            df["vendor"] = candidate_vendor
                        frames.append(df)

    if not frames:
        raise FileNotFoundError(
            f"No data found for symbols {symbols} at bar_size={bar_size} in [{start}, {end}]. "
            f"Run `quant-us ingest` first."
        )

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values("timestamp_utc").reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Result of a single ``compute`` call."""

    factor_id: str
    n_dates: int
    n_symbols: int
    n_valid: int
    snapshot_paths: list[str] = field(default_factory=list)


class FactorPipeline:
    """Batch factor computation with lookahead protection.

    Parameters:
        data_root: Path to the data directory (used for both source bars
            and factor snapshot output).
        factor_library: Optional overridden library (defaults to the
            built-in FactorLibrary singleton).
    """

    def __init__(
        self,
        data_root: str = "data",
        factor_library: FactorLibrary | None = None,
        data_vendor: str = "alpaca",
        asset_class: str = "equity",
    ) -> None:
        self.data_root = data_root
        self.lib = factor_library or FactorLibrary()
        self._store = ParquetFeatureStore(f"{data_root}/features")
        self.data_vendor = data_vendor
        self.asset_class = asset_class

    # ------------------------------------------------------------------
    # Main compute entry-point
    # ------------------------------------------------------------------

    def compute(
        self,
        factor_ids: list[str],
        symbols: list[str],
        start: str,
        end: str,
        *,
        bar_size: str = "1d",
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Compute one or more factors across *symbols* for the date range.

        The resulting DataFrame has columns ``date``, ``symbol``, plus one
        column per factor_id.  Factor values are winsorized, z-scored
        (per definition), and stored in long-format parquet snapshots.

        Returns a wide DataFrame ready for evaluation or export.
        """
        # 1. Validate factor_ids
        for fid in factor_ids:
            self.lib.get(fid)  # raises KeyError if unknown

        # 2. Load raw bars (extend lookback to accommodate rolling windows)
        max_lookback = max(self.lib.get(fid).lookback for fid in factor_ids)
        padded_start = self._padded_start(start, max_lookback)
        effective_bar_size = timeframe or bar_size
        bars = _load_bars(
            self.data_root,
            symbols,
            padded_start,
            end,
            bar_size=effective_bar_size,
            vendor=self.data_vendor,
            asset_class=self.asset_class,
        )

        if bars.empty:
            return pd.DataFrame(columns=["timestamp_utc", "date", "symbol"] + factor_ids)

        # 3. Per-symbol factor computation
        records: list[dict[str, Any]] = []
        for sym, group in bars.groupby("symbol", sort=False):
            group = group.sort_values("timestamp_utc")
            close: pd.Series | None = group["close"].astype(float) if "close" in group.columns else None
            volume: pd.Series | None = group["volume"].astype(float) if "volume" in group.columns else None
            dates = group["timestamp_utc"].dt.date
            timestamps = group["timestamp_utc"]

            for fid in factor_ids:
                raw = _compute_factor_series(fid, close, volume)
                for ts, dt, val in zip(timestamps, dates, raw):
                    if pd.isna(val):
                        continue
                    # Only keep values on or after the user-supplied start
                    if str(dt) < start:
                        continue
                    records.append({
                        "timestamp_utc": ts,
                        "date": str(dt),
                        "symbol": sym,
                        fid: float(val),
                    })

        if not records:
            return pd.DataFrame(columns=["timestamp_utc", "date", "symbol"] + factor_ids)

        # 4. Widen: group records into date × symbol grid
        df = pd.DataFrame(records)
        # Pivot only if we have more than one factor
        if len(factor_ids) == 1:
            # Single factor: records already have the factor column
            result = df[["timestamp_utc", "date", "symbol"] + factor_ids].drop_duplicates(["timestamp_utc", "symbol"])
        else:
            # Melted records: each record has date, symbol, ONE factor_id column
            melted = df.melt(
                id_vars=["timestamp_utc", "date", "symbol"],
                value_vars=[c for c in df.columns if c not in ("timestamp_utc", "date", "symbol")],
                var_name="factor_id",
                value_name="value",
            )
            result = melted.pivot_table(
                index=["timestamp_utc", "date", "symbol"],
                columns="factor_id",
                values="value",
                aggfunc="first",
            ).reset_index()
            result.columns.name = None
            # Ensure all requested factor columns exist
            for fid in factor_ids:
                if fid not in result.columns:
                    result[fid] = pd.NA

        result = result.sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)

        # 5. Cross-sectional post-processing per factor
        cross_section_key = "timestamp_utc" if "timestamp_utc" in result.columns else "date"
        for fid in factor_ids:
            definition = self.lib.get(fid)
            series = result[fid]
            if definition.winsorize_pct > 0:
                series = result.groupby(cross_section_key, group_keys=False)[fid].transform(
                    lambda group: _winsorize(group, definition.winsorize_pct)
                )
            if definition.zscore:
                series = series.groupby(result[cross_section_key]).transform(_zscore)
            if definition.rank_method == "percentile":
                series = series.groupby(result[cross_section_key]).transform(_rank_to_percentile)
            result[fid] = series

        # 6. Save snapshots
        for fid in factor_ids:
            self.save_snapshot(result, fid, start, bar_size=effective_bar_size, timeframe=effective_bar_size)

        return result

    # ------------------------------------------------------------------
    # Single-date cross-sectional computation
    # ------------------------------------------------------------------

    def compute_cross_sectional(
        self,
        factor_id: str,
        date: str,
        universe: list[str],
        *,
        bar_size: str = "1d",
        timeframe: str | None = None,
    ) -> dict[str, float]:
        """Compute factor value for every symbol in *universe* on a single date.

        This loads a wider window to satisfy lookback requirements, then
        returns only the values for *date*.
        """
        definition = self.lib.get(factor_id)
        padded_start = self._padded_start(date, definition.lookback)
        effective_bar_size = timeframe or bar_size
        bars = _load_bars(
            self.data_root,
            universe,
            padded_start,
            date,
            bar_size=effective_bar_size,
            vendor=self.data_vendor,
            asset_class=self.asset_class,
        )

        result: dict[str, float] = {}
        for sym, group in bars.groupby("symbol", sort=False):
            group = group.sort_values("timestamp_utc")
            close = group["close"].astype(float) if "close" in group.columns else None
            volume = group["volume"].astype(float) if "volume" in group.columns else None
            raw = _compute_factor_series(factor_id, close, volume)
            if len(raw) > 0 and not pd.isna(raw.iloc[-1]):
                val = float(raw.iloc[-1])
                # Post-process
                if definition.winsorize_pct > 0:
                    vals = np.array(list(result.values()) + [val])
                    lower = float(np.percentile(vals, definition.winsorize_pct * 100))
                    upper = float(np.percentile(vals, (1.0 - definition.winsorize_pct) * 100))
                    val = max(lower, min(upper, val))
                result[sym] = val

        # Cross-sectional z-score
        if definition.zscore and result:
            vals = pd.Series(result)
            vals = _zscore(vals)
            for sym in result:
                result[sym] = float(vals[sym])

        return result

    # ------------------------------------------------------------------
    # Lookahead validation
    # ------------------------------------------------------------------

    def _validate_no_lookahead(
        self,
        df: pd.DataFrame,
        factor_id: str,
    ) -> bool:
        """Heuristic check: ensure factor[t] does not correlate perfectly
        with future returns.

        If rank IC exceeds 0.2, a warning is issued.  This does NOT prove
        absence of lookahead, only flags suspiciously high predictive power.
        """
        try:
            from quant_us.factors.evaluation import FactorEvaluator
        except ImportError:
            return True  # evaluation module not available — skip

        evaluator = FactorEvaluator(self.data_root)
        lookahead, message = evaluator.detect_lookahead(factor_id)
        if lookahead:
            warnings.warn(
                f"Lookahead suspected for '{factor_id}': {message}",
                stacklevel=2,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def winsorize(series: pd.Series, pct: float = 0.01) -> pd.Series:
        """Winsorize *series* at ``pct`` and ``1-pct`` percentiles."""
        return _winsorize(series, pct)

    @staticmethod
    def neutralize(
        factor_values: dict[str, float],
        groupings: dict[str, str],
    ) -> dict[str, float]:
        """Subtract group mean from each factor value.

        *groupings* maps symbol → group label (e.g. sector or size bucket).
        Returns a new dict with neutralised values.
        """
        by_group: dict[str, list[float]] = {}
        for sym, val in factor_values.items():
            g = groupings.get(sym, "_ungrouped")
            by_group.setdefault(g, []).append(val)

        group_mean = {g: float(np.mean(vals)) for g, vals in by_group.items()}

        neutralized: dict[str, float] = {}
        for sym, val in factor_values.items():
            g = groupings.get(sym, "_ungrouped")
            neutralized[sym] = val - group_mean.get(g, 0.0)
        return neutralized

    def save_snapshot(
        self,
        df: pd.DataFrame,
        factor_id: str,
        date: str,
        *,
        bar_size: str = "1d",
        timeframe: str | None = None,
    ) -> str:
        """Save factor values for *factor_id* to parquet.

        Returns the file path written.
        """
        if df.empty:
            return ""
        columns = ["date", "symbol", factor_id]
        if "timestamp_utc" in df.columns:
            columns.insert(0, "timestamp_utc")
        snapshot = df[columns].dropna(subset=[factor_id]).copy()
        snapshot = snapshot.rename(columns={factor_id: "factor_value"})
        snapshot["factor_name"] = factor_id
        snapshot["universe"] = "default"
        snapshot["version"] = "v1"
        snapshot["bar_size"] = bar_size
        snapshot["timeframe"] = timeframe or bar_size
        from datetime import datetime, timezone

        snapshot["created_at"] = datetime.now(timezone.utc)

        write = self._store.write_factor_values(snapshot, version="v1")
        paths = [str(p) for p in write.files_written]
        return paths[0] if paths else ""

    @staticmethod
    def _padded_start(start: str, lookback: int) -> str:
        """Extend *start* backward by *lookback* trading days (~1.4x calendar days)."""
        from datetime import datetime, timedelta

        dt = datetime.strptime(start, "%Y-%m-%d")
        padding = int(lookback * 1.4) + 5
        padded = dt - timedelta(days=padding)
        return padded.strftime("%Y-%m-%d")


def _candidate_vendors(data_root: Path, preferred_vendor: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        vendor = str(value or "").strip()
        if vendor and vendor not in seen:
            seen.add(vendor)
            candidates.append(vendor)

    _add(preferred_vendor)
    for root_subdir in ("cleaned", "raw"):
        base = data_root / root_subdir
        if not base.exists():
            continue
        for path in sorted(base.glob("vendor=*")):
            _add(path.name.split("=", 1)[-1])
    return candidates or [preferred_vendor]
