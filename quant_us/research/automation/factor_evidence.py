"""Point-in-time evidence helpers for factor-mining candidates.

These utilities build research-only return streams and style benchmark proxies
from the same bar data used by factor mining.  They never emit broker orders or
touch the live execution path.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_us.research.benchmarks import estimate_style_exposure


def build_factor_return_stream(
    factor_frame: pd.DataFrame,
    bars: pd.DataFrame,
    factor_id: str,
    *,
    bucket_fraction: float = 0.3,
) -> pd.Series:
    """Build a long-short next-bar return stream for one factor.

    Factor values at timestamp ``t`` are matched with the forward return from
    ``t`` to ``t+1`` for the same symbol.  This keeps the evidence path
    point-in-time and avoids same-bar leakage.
    """
    if factor_frame.empty or bars.empty or factor_id not in factor_frame.columns:
        return pd.Series(dtype=float, name=factor_id)

    forward = _prepare_forward_return_frame(bars)
    if forward.empty:
        return pd.Series(dtype=float, name=factor_id)

    merged = factor_frame[["timestamp_utc", "symbol", factor_id]].merge(
        forward,
        on=["timestamp_utc", "symbol"],
        how="inner",
    )
    if merged.empty:
        return pd.Series(dtype=float, name=factor_id)

    records: list[tuple[pd.Timestamp, float]] = []
    for timestamp, group in merged.groupby("timestamp_utc", sort=True):
        long_short = _cross_section_long_short(
            group,
            score_column=factor_id,
            return_column="next_return",
            high_minus_low=True,
            bucket_fraction=bucket_fraction,
        )
        if long_short is None:
            continue
        records.append((pd.Timestamp(timestamp), float(long_short)))

    if not records:
        return pd.Series(dtype=float, name=factor_id)

    index = pd.DatetimeIndex([item[0] for item in records], name="timestamp_utc")
    series = pd.Series(
        [item[1] for item in records],
        index=index,
        name=factor_id,
        dtype=float,
    )
    return series.sort_index()


def build_style_benchmark_returns(
    bars: pd.DataFrame,
    *,
    bucket_fraction: float = 0.3,
) -> pd.DataFrame:
    """Construct point-in-time benchmark proxy returns from the local universe."""
    if bars.empty:
        return pd.DataFrame()

    frame = bars.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.sort_values(["symbol", "timestamp_utc"]).reset_index(drop=True)
    frame["close"] = pd.to_numeric(frame.get("close"), errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["next_return"] = frame.groupby("symbol", sort=False)["close"].transform(
        lambda series: series.shift(-1) / series - 1.0
    )
    frame["dollar_volume"] = frame["close"] * frame["volume"]
    frame["trailing_vol_20"] = (
        frame.groupby("symbol", sort=False)["close"]
        .pct_change()
        .rolling(window=20, min_periods=20)
        .std()
        .reset_index(level=0, drop=True)
    )
    frame["trailing_momentum_20"] = (
        frame.groupby("symbol", sort=False)["close"].pct_change(20)
    )
    frame = frame.dropna(subset=["next_return"])
    if frame.empty:
        return pd.DataFrame()

    records: list[dict[str, float | pd.Timestamp]] = []
    for timestamp, group in frame.groupby("timestamp_utc", sort=True):
        market = pd.to_numeric(group["next_return"], errors="coerce").dropna()
        if market.empty:
            continue
        row: dict[str, float | pd.Timestamp] = {
            "timestamp_utc": pd.Timestamp(timestamp),
            "MKT": float(market.mean()),
        }
        row["SMB_PROXY"] = float(
            _cross_section_long_short(
                group,
                score_column="dollar_volume",
                return_column="next_return",
                high_minus_low=False,
                bucket_fraction=bucket_fraction,
            )
            or 0.0
        )
        row["LOWVOL_PROXY"] = float(
            _cross_section_long_short(
                group,
                score_column="trailing_vol_20",
                return_column="next_return",
                high_minus_low=False,
                bucket_fraction=bucket_fraction,
            )
            or 0.0
        )
        row["MOM_PROXY"] = float(
            _cross_section_long_short(
                group,
                score_column="trailing_momentum_20",
                return_column="next_return",
                high_minus_low=True,
                bucket_fraction=bucket_fraction,
            )
            or 0.0
        )
        records.append(row)

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records).set_index("timestamp_utc").sort_index()
    return result


def estimate_candidate_style_exposure(
    factor_frame: pd.DataFrame,
    bars: pd.DataFrame,
    factor_id: str,
    *,
    min_observations: int = 20,
) -> dict[str, Any]:
    """Estimate style exposure for a research-only factor candidate."""
    factor_returns = build_factor_return_stream(factor_frame, bars, factor_id)
    benchmark_returns = build_style_benchmark_returns(bars)
    if factor_returns.empty or benchmark_returns.empty:
        return {
            "missing_reason": "style_exposure_inputs_unavailable",
            "observations": 0,
            "betas": {},
            "warnings": ["style_exposure_inputs_unavailable"],
            "lookahead_guard": "factor[t] is paired with next_return[t->t+1] only",
        }

    exposure = estimate_style_exposure(
        factor_returns,
        benchmark_returns,
        min_observations=min_observations,
    )
    payload = exposure.to_dict()
    payload["lookahead_guard"] = "factor[t] is paired with next_return[t->t+1] only"
    if not payload.get("betas"):
        payload["missing_reason"] = (
            payload.get("warnings", ["style_exposure_estimation_failed"])[0]
            if payload.get("warnings")
            else "style_exposure_estimation_failed"
        )
    return payload


def build_factor_correlation_matrix(
    factor_frame: pd.DataFrame,
    factor_ids: list[str],
) -> pd.DataFrame:
    """Return an absolute correlation matrix for the requested factor columns."""
    available = [factor_id for factor_id in factor_ids if factor_id in factor_frame.columns]
    if not available:
        return pd.DataFrame(index=available, columns=available, dtype=float)
    numeric = factor_frame[available].apply(pd.to_numeric, errors="coerce")
    return numeric.corr().abs()


def _prepare_forward_return_frame(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.copy()
    if frame.empty or "timestamp_utc" not in frame.columns or "symbol" not in frame.columns:
        return pd.DataFrame(columns=["timestamp_utc", "symbol", "next_return"])
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.sort_values(["symbol", "timestamp_utc"]).reset_index(drop=True)
    frame["close"] = pd.to_numeric(frame.get("close"), errors="coerce")
    frame["next_return"] = frame.groupby("symbol", sort=False)["close"].transform(
        lambda series: series.shift(-1) / series - 1.0
    )
    return frame.dropna(subset=["next_return"])[["timestamp_utc", "symbol", "next_return"]]


def _cross_section_long_short(
    frame: pd.DataFrame,
    *,
    score_column: str,
    return_column: str,
    high_minus_low: bool,
    bucket_fraction: float,
) -> float | None:
    sample = frame[[score_column, return_column]].copy()
    sample[score_column] = pd.to_numeric(sample[score_column], errors="coerce")
    sample[return_column] = pd.to_numeric(sample[return_column], errors="coerce")
    sample = sample.dropna()
    if len(sample) < 2:
        return None

    bucket_size = max(1, int(len(sample) * bucket_fraction))
    bucket_size = min(bucket_size, len(sample) // 2)
    if bucket_size < 1:
        return None

    ordered = sample.sort_values(score_column, ascending=True)
    low_bucket = ordered.head(bucket_size)[return_column]
    high_bucket = ordered.tail(bucket_size)[return_column]
    if low_bucket.empty or high_bucket.empty:
        return None

    low_mean = float(low_bucket.mean())
    high_mean = float(high_bucket.mean())
    return high_mean - low_mean if high_minus_low else low_mean - high_mean


__all__ = [
    "build_factor_correlation_matrix",
    "build_factor_return_stream",
    "build_style_benchmark_returns",
    "estimate_candidate_style_exposure",
]
