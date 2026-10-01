from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pandas as pd

from quant_us.data.storage.data_manifest import DataManifestStore
from quant_us.data.storage.parquet_store import ParquetBarStore

from .build_expected_returns import build_expected_returns
from .schemas import (
    ArtifactError,
    MissingDependencyError,
    PortfolioAdapterConfig,
    covariance_path,
    expected_returns_path,
    load_portfolio_config,
    now_iso,
    portfolio_run_dir,
    read_expected_returns_frame,
    resolve_portfolio_run_id,
    write_frame,
)


def build_covariance(
    *,
    score_run_id: str,
    config: PortfolioAdapterConfig,
    portfolio_run_id: str | None = None,
) -> tuple[pd.DataFrame, Path]:
    resolved_run_id = resolve_portfolio_run_id(config, portfolio_run_id)
    portfolio_run_dir(config, resolved_run_id)

    if not expected_returns_path(config, resolved_run_id).exists():
        build_expected_returns(score_run_id=score_run_id, config=config, portfolio_run_id=resolved_run_id)
    expected_frame = read_expected_returns_frame(config, resolved_run_id)

    manifest_store = DataManifestStore(config.data_root / "manifests")
    cleaned_store = ParquetBarStore(config.data_root / "cleaned")
    history_cache: dict[str, pd.DataFrame] = {}
    created_at = now_iso()

    def load_history(symbol: str, end_before: pd.Timestamp) -> pd.DataFrame:
        cached = history_cache.get(symbol)
        if cached is not None:
            return cached

        manifest = manifest_store.read_latest(config.vendor, symbol, config.bar_size)
        if manifest is None:
            raise ArtifactError(
                f"Missing daily data manifest for symbol {symbol}. "
                f"Expected a cleaned {config.bar_size} manifest under {config.data_root / 'manifests'}."
            )

        start = datetime(1970, 1, 1, tzinfo=timezone.utc)
        history = cleaned_store.read_bars(
            vendor=config.vendor,
            asset_class=config.asset_class,
            bar_size=config.bar_size,
            symbol=symbol,
            start=start,
            end=end_before.to_pydatetime(),
        )
        if history.empty:
            raise ArtifactError(f"No cleaned daily bars found for symbol {symbol} before {end_before.isoformat()}.")

        working = history.copy()
        working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        working = working.sort_values("timestamp_utc").reset_index(drop=True)
        working["close"] = pd.to_numeric(working["close"], errors="raise")
        working["daily_return"] = working["close"].pct_change()
        history_cache[symbol] = working
        return working

    rows: list[dict[str, object]] = []
    for timestamp, group in expected_frame.groupby("datetime", sort=True):
        returns_series: list[pd.Series] = []
        window_end = pd.Timestamp(timestamp)

        for symbol in group["symbol"].astype(str).str.upper():
            history = load_history(symbol, window_end)
            prior = history[history["timestamp_utc"] < window_end]
            returns = prior[["timestamp_utc", "daily_return"]].dropna().tail(config.lookback_days)
            if len(returns) < config.min_observations:
                raise ArtifactError(
                    f"Insufficient cleaned daily return history for {symbol} before {window_end.isoformat()}: "
                    f"have {len(returns)} observations, need at least {config.min_observations}."
                )
            series = returns.set_index("timestamp_utc")["daily_return"].rename(symbol)
            returns_series.append(series)

        returns_wide = pd.concat(returns_series, axis=1).sort_index().tail(config.lookback_days)
        if len(returns_wide) < config.min_observations:
            raise ArtifactError(
                f"Covariance window for {window_end.isoformat()} has only {len(returns_wide)} rows after alignment; "
                f"need at least {config.min_observations}."
            )

        cov = _estimate_covariance(returns_wide=returns_wide, config=config)
        cov = cov.sort_index(axis=0).sort_index(axis=1)
        cov = cov.fillna(0.0)

        returns_start = returns_wide.index.min().isoformat()
        returns_end = returns_wide.index.max().isoformat()
        observation_count = int(len(returns_wide))

        for symbol in cov.index:
            for peer_symbol in cov.columns:
                rows.append(
                    {
                        "portfolio_run_id": resolved_run_id,
                        "source_score_run_id": score_run_id,
                        "datetime": window_end,
                        "symbol": symbol,
                        "peer_symbol": peer_symbol,
                        "covariance": float(cov.loc[symbol, peer_symbol]),
                        "method": config.covariance_method,
                        "lookback_days": config.lookback_days,
                        "observation_count": observation_count,
                        "returns_start": returns_start,
                        "returns_end": returns_end,
                        "created_at": created_at,
                    }
                )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values(["datetime", "symbol", "peer_symbol"]).reset_index(drop=True)

    output_path = covariance_path(config, resolved_run_id)
    write_frame(frame, output_path)
    return frame, output_path


def _estimate_covariance(*, returns_wide: pd.DataFrame, config: PortfolioAdapterConfig) -> pd.DataFrame:
    if config.covariance_method == "sample":
        return returns_wide.cov(min_periods=config.min_observations) * config.annualization

    if config.covariance_method == "exponential":
        return _exponential_covariance(returns_wide=returns_wide, config=config)

    if config.covariance_method == "shrinkage":
        if importlib.util.find_spec("pypfopt") is None:
            raise MissingDependencyError(
                "covariance_method=shrinkage requires PyPortfolioOpt. Install pypfopt or use covariance_method=sample."
            )
        from pypfopt import risk_models

        return risk_models.CovarianceShrinkage(
            returns_wide,
            returns_data=True,
            frequency=config.annualization,
        ).ledoit_wolf()

    raise ArtifactError(f"Unsupported covariance_method: {config.covariance_method}")


def _exponential_covariance(*, returns_wide: pd.DataFrame, config: PortfolioAdapterConfig) -> pd.DataFrame:
    clean = returns_wide.dropna(how="any")
    if len(clean) < config.min_observations:
        raise ArtifactError(
            f"Exponential covariance has only {len(clean)} complete rows; need at least {config.min_observations}."
        )
    span = min(config.lookback_days, max(config.min_observations, 60))
    alpha = 2.0 / (span + 1.0)
    count = len(clean)
    raw_weights = pd.Series(
        [(1.0 - alpha) ** (count - idx - 1) for idx in range(count)],
        index=clean.index,
        dtype=float,
    )
    weights = raw_weights / float(raw_weights.sum())
    mean = clean.mul(weights, axis=0).sum(axis=0)
    demeaned = clean - mean
    cov = demeaned.mul(weights, axis=0).T.dot(demeaned) * config.annualization
    return pd.DataFrame(cov, index=clean.columns, columns=clean.columns)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build covariance matrices from cleaned daily returns only.")
    parser.add_argument("--score-run-id", required=True, help="Qlib score run id under artifacts/qlib_runs/<run_id>/")
    parser.add_argument("--config", required=False, help="Portfolio config yaml path.")
    parser.add_argument("--portfolio-run-id", required=False, help="Optional explicit portfolio run id.")
    args = parser.parse_args()

    config = load_portfolio_config(args.config)
    frame, output_path = build_covariance(
        score_run_id=args.score_run_id,
        config=config,
        portfolio_run_id=args.portfolio_run_id,
    )
    print(f"wrote covariance: {output_path}")
    print(f"rows={len(frame)} dates={frame['datetime'].nunique() if not frame.empty else 0}")


if __name__ == "__main__":
    main()
