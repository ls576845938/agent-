from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_us.factors.evaluation import FactorEvaluationResult
from quant_us.factors.formula import GeneratedFactorLibrary, generate_candidate_formula_specs
from quant_us.factors.pipeline import FactorPipeline
from quant_us.research.automation.factor_mining import FactorMiningEngine


def _sample_bars() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-02", periods=90, freq="B", tz="UTC")
    for idx, symbol in enumerate(["AAPL", "MSFT", "NVDA", "META", "GOOGL"]):
        price = 100.0 + idx * 10.0
        for step, ts in enumerate(dates):
            price *= 1.0 + 0.001 * (idx + 1)
            rows.append(
                {
                    "timestamp_utc": ts,
                    "date": str(ts.date()),
                    "symbol": symbol,
                    "open": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price,
                    "volume": 1_000_000 + step * 1000 + idx * 10_000,
                }
            )
    return pd.DataFrame(rows)


def test_generated_formula_factor_computes_from_registered_spec(monkeypatch, tmp_path) -> None:
    generated = GeneratedFactorLibrary(tmp_path).generate_and_register(
        seed_factor_ids=["momentum_20d", "volatility_20d", "liquidity_20d"],
        max_specs=6,
    )
    factor_id = generated[0].factor_id

    monkeypatch.setattr("quant_us.factors.pipeline._load_bars", lambda *args, **kwargs: _sample_bars())

    frame = FactorPipeline(data_root=str(tmp_path)).compute(
        factor_ids=[factor_id],
        symbols=["AAPL", "MSFT", "NVDA", "META", "GOOGL"],
        start="2024-02-01",
        end="2024-04-30",
    )

    assert not frame.empty
    assert factor_id in frame.columns
    values = pd.to_numeric(frame[factor_id], errors="coerce").dropna()
    assert not values.empty
    assert values.min() >= 0.0
    assert values.max() <= 1.0


def test_generated_formula_specs_include_nonlinear_templates_and_dedup() -> None:
    specs = generate_candidate_formula_specs(
        seed_factor_ids=[
            "momentum_20d",
            "momentum_20d",
            "volatility_20d",
            "liquidity_20d",
            "reversal_1d",
            "volume_20d",
        ],
        max_specs=16,
    )

    assert specs
    assert len({spec.factor_id for spec in specs}) == len(specs)
    assert len({spec.signature for spec in specs}) == len(specs)
    assert {"signed_power", "gated_combo", "interaction"} <= {
        spec.formula_type for spec in specs
    }
    assert all(spec.factor_id.startswith("gf_") for spec in specs)
    assert all(spec.complexity_score > 0 for spec in specs)


def test_generated_formula_specs_respect_complexity_limit() -> None:
    specs = generate_candidate_formula_specs(
        seed_factor_ids=[
            "momentum_20d",
            "volatility_20d",
            "liquidity_20d",
            "reversal_1d",
        ],
        max_specs=24,
        max_complexity=4,
    )

    assert specs
    assert all(spec.complexity_score <= 4 for spec in specs)
    assert "tri_factor_risk_gated" not in {spec.generation_family for spec in specs}
    assert not any(
        spec.formula_type == "gated_combo" and len(spec.components) >= 3
        for spec in specs
    )


def test_factor_mining_can_generate_formulas_and_strategy_logic(monkeypatch, tmp_path) -> None:
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
        score_seed = 0.08 if str(factor_id).startswith("gf_") else 0.03
        return FactorEvaluationResult(
            factor_id=factor_id,
            ic_mean=score_seed,
            rank_ic_mean=score_seed,
            icir=1.2,
            long_short_spread=0.03,
            hit_rate=0.58,
            turnover=0.05,
            n_observations=120,
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
        base = np.linspace(0, 1, 20)
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2024-01-01", periods=20, freq="D", tz="UTC"),
                "date": pd.date_range("2024-01-01", periods=20, freq="D").date,
                "symbol": np.resize(np.array(symbols), 20),
            }
        )
        patterns = [
            base,
            np.sin(np.linspace(0, np.pi * 3, 20)),
            np.cos(np.linspace(0, np.pi * 2, 20)),
            np.resize(np.array([0.1, 0.8, 0.2, 0.9, 0.3]), 20),
        ]
        for idx, factor_id in enumerate(factor_ids):
            frame[factor_id] = patterns[idx % len(patterns)] + idx * 0.03
        return frame

    monkeypatch.setattr("quant_us.factors.evaluation.FactorEvaluator.evaluate", fake_evaluate)
    monkeypatch.setattr("quant_us.factors.pipeline.FactorPipeline.compute", fake_compute)

    result = FactorMiningEngine(data_root=str(tmp_path)).mine(
        symbols=["AAPL", "MSFT", "NVDA", "META", "GOOGL"],
        start="2024-01-01",
        end="2024-04-30",
        bar_sizes=["1d"],
        factor_ids=["momentum_20d", "volatility_20d", "liquidity_20d"],
        auto_generate_formulas=True,
        max_generated_factors=4,
        max_formula_complexity=4,
        max_selected=3,
    )

    assert result.generated_factor_ids
    assert len(result.generated_factor_ids) == len(set(result.generated_factor_ids))
    assert any(score.factor_id.startswith("gf_") for score in result.selected_factors)
    assert result.strategy_configs
    config_keys = {
        (config["strategy_id"], config["bar_size"], tuple(config["factor_ids"]))
        for config in result.strategy_configs
    }
    assert len(config_keys) == len(result.strategy_configs)
    assert all(config.get("logic_path") for config in result.strategy_configs)
    assert {"single_factor_rank", "weighted_factor_basket", "consensus_rank"} <= {
        config["template_id"] for config in result.strategy_configs
    }
    for path in result.strategy_logic_paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["execution_semantics"] == "signal_at_bar_close_order_next_bar"
        assert payload["strategy_id"] in {"factor_rank", "factor_basket", "factor_consensus"}


def test_generated_formula_pipeline_is_stable_before_future_bar(monkeypatch, tmp_path) -> None:
    bars = _sample_bars()
    future_shocked = bars.copy()
    last_ts = future_shocked["timestamp_utc"].max()
    future_shocked.loc[
        (future_shocked["symbol"] == "AAPL") & (future_shocked["timestamp_utc"] == last_ts),
        "close",
    ] *= 5.0

    specs = GeneratedFactorLibrary(tmp_path).generate_and_register(
        seed_factor_ids=["momentum_20d", "volatility_20d", "liquidity_20d"],
        max_specs=12,
    )
    factor_id = next(spec.factor_id for spec in specs if spec.formula_type == "gated_combo")

    monkeypatch.setattr("quant_us.factors.pipeline._load_bars", lambda *args, **kwargs: bars)
    base = FactorPipeline(data_root=str(tmp_path)).compute(
        factor_ids=[factor_id],
        symbols=["AAPL", "MSFT", "NVDA", "META", "GOOGL"],
        start="2024-02-01",
        end="2024-04-30",
    )

    monkeypatch.setattr("quant_us.factors.pipeline._load_bars", lambda *args, **kwargs: future_shocked)
    shocked = FactorPipeline(data_root=str(tmp_path)).compute(
        factor_ids=[factor_id],
        symbols=["AAPL", "MSFT", "NVDA", "META", "GOOGL"],
        start="2024-02-01",
        end="2024-04-30",
    )

    cutoff = str(pd.Timestamp(last_ts).date())
    base_history = base.loc[base["date"] < cutoff, ["timestamp_utc", "symbol", factor_id]].reset_index(drop=True)
    shocked_history = shocked.loc[shocked["date"] < cutoff, ["timestamp_utc", "symbol", factor_id]].reset_index(drop=True)
    pd.testing.assert_frame_equal(base_history, shocked_history)
