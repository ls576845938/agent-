from __future__ import annotations

import numpy as np
import pandas as pd

from quant_us.factors.evaluation import FactorEvaluationResult
from quant_us.research.automation.factor_evidence import build_factor_return_stream
from quant_us.research.automation.factor_mining import FactorMiningEngine


def _sample_bars() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2024-01-02", periods=80, freq="B", tz="UTC")
    symbols = ["AAPL", "MSFT", "NVDA", "META", "GOOGL"]
    for symbol_idx, symbol in enumerate(symbols):
        price = 100.0 + symbol_idx * 7.0
        for step, ts in enumerate(dates):
            drift = 0.0008 * (symbol_idx + 1)
            seasonal = 0.0005 * np.sin(step / 7.0 + symbol_idx)
            price *= 1.0 + drift + seasonal
            rows.append(
                {
                    "timestamp_utc": ts,
                    "date": str(ts.date()),
                    "symbol": symbol,
                    "open": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price,
                    "volume": 900_000 + step * 5_000 + symbol_idx * 25_000,
                }
            )
    return pd.DataFrame(rows)


def _sample_factor_frame(factor_ids: list[str]) -> pd.DataFrame:
    bars = _sample_bars()
    symbols = sorted(bars["symbol"].unique())
    frame = bars[["timestamp_utc", "date", "symbol"]].copy()
    symbol_rank = {symbol: idx for idx, symbol in enumerate(symbols)}
    time_index = (
        frame.groupby("symbol", sort=False).cumcount().astype(float).to_numpy()
    )
    for factor_idx, factor_id in enumerate(factor_ids):
        base = frame["symbol"].map(symbol_rank).astype(float).to_numpy()
        frame[factor_id] = (
            base * (0.6 + factor_idx * 0.15)
            + np.sin(time_index / (5.0 + factor_idx)) * 0.25
            + factor_idx * 0.1
        )
    return frame


def test_factor_mining_style_exposure_enters_candidate_and_manifest_evidence(
    monkeypatch,
    tmp_path,
) -> None:
    bars = _sample_bars()
    factor_ids = ["momentum_20d", "volatility_20d", "liquidity_20d"]

    def fake_evaluate(
        self,
        factor_id,
        symbols,
        start,
        end,
        forward_period=5,
        *,
        bar_size="1d",
        timeframe=None,
    ):
        return FactorEvaluationResult(
            factor_id=factor_id,
            ic_mean=0.05,
            icir=1.2,
            rank_ic_mean=0.06 if factor_id == "momentum_20d" else 0.045,
            rank_icir=1.1 if factor_id == "momentum_20d" else 0.9,
            rank_ic_std=0.04,
            long_short_spread=0.03,
            hit_rate=0.62 if factor_id == "momentum_20d" else 0.57,
            monotonicity=0.55,
            n_observations=200,
            n_dates=40,
        )

    def fake_compute(
        self,
        factor_ids,
        symbols,
        start,
        end,
        *,
        bar_size="1d",
        timeframe=None,
    ):
        return _sample_factor_frame(list(factor_ids))

    monkeypatch.setattr(
        "quant_us.factors.evaluation.FactorEvaluator.evaluate",
        fake_evaluate,
    )
    monkeypatch.setattr(
        "quant_us.factors.pipeline.FactorPipeline.compute",
        fake_compute,
    )
    monkeypatch.setattr(
        "quant_us.factors.pipeline._load_bars",
        lambda *args, **kwargs: bars,
    )

    result = FactorMiningEngine(data_root=str(tmp_path)).mine(
        symbols=["AAPL", "MSFT", "NVDA", "META", "GOOGL"],
        start="2024-01-02",
        end="2024-04-30",
        bar_sizes=["1d"],
        factor_ids=factor_ids,
        max_selected=2,
    )

    single_factor = next(
        config for config in result.strategy_configs if config["template_id"] == "single_factor_rank"
    )
    evidence = single_factor["candidate_evidence"]
    assert evidence["style_exposure"]["betas"]
    assert "MKT" in evidence["style_exposure"]["benchmark_columns"]
    assert "lookahead_guard" in evidence["style_exposure"]
    assert result.manifest_evidence["style_exposure_coverage"]["covered_candidates"] >= 1
    assert result.manifest_evidence["correlation_report_path"] == result.correlation_report_path


def test_factor_return_stream_is_stable_before_future_boundary() -> None:
    bars = _sample_bars()
    factor_frame = _sample_factor_frame(["signal"])
    shocked_bars = bars.copy()
    last_ts = shocked_bars["timestamp_utc"].max()
    shocked_bars.loc[
        (shocked_bars["symbol"] == "AAPL") & (shocked_bars["timestamp_utc"] == last_ts),
        "close",
    ] *= 4.0

    base = build_factor_return_stream(factor_frame, bars, "signal")
    shocked = build_factor_return_stream(factor_frame, shocked_bars, "signal")

    timestamps = sorted(base.index.unique())
    cutoff = timestamps[-2]
    pd.testing.assert_series_equal(
        base.loc[base.index < cutoff],
        shocked.loc[shocked.index < cutoff],
    )
