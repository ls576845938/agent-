from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_us.factors.evaluation import FactorEvaluationResult
from quant_us.research.automation.factor_mining import FactorMiningEngine


def test_factor_mining_selects_low_redundancy_strategy_configs(
    monkeypatch,
    tmp_path,
) -> None:
    metrics = {
        "momentum_20d": FactorEvaluationResult(
            factor_id="momentum_20d",
            ic_mean=0.07,
            icir=1.4,
            rank_ic_mean=0.08,
            long_short_spread=0.04,
            hit_rate=0.60,
            turnover=0.10,
            n_observations=120,
        ),
        "momentum_60d": FactorEvaluationResult(
            factor_id="momentum_60d",
            ic_mean=0.06,
            icir=1.3,
            rank_ic_mean=0.075,
            long_short_spread=0.035,
            hit_rate=0.58,
            turnover=0.10,
            n_observations=120,
        ),
        "volatility_20d": FactorEvaluationResult(
            factor_id="volatility_20d",
            ic_mean=-0.05,
            icir=1.1,
            rank_ic_mean=-0.06,
            long_short_spread=0.03,
            hit_rate=0.56,
            turnover=0.10,
            n_observations=120,
        ),
    }

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
        return metrics[factor_id]

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
        base = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        values = {
            "momentum_20d": base,
            "momentum_60d": [item * 2.0 + 0.01 for item in base],
            "volatility_20d": [8.0, 1.0, 7.0, 2.0, 6.0, 3.0, 5.0, 4.0],
        }
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(
                    "2024-01-01",
                    periods=len(base),
                    freq="D",
                    tz="UTC",
                ),
                "date": pd.date_range("2024-01-01", periods=len(base), freq="D").date,
                "symbol": ["AAPL", "MSFT", "AAPL", "MSFT", "AAPL", "MSFT", "AAPL", "MSFT"],
            }
        )
        for factor_id in factor_ids:
            frame[factor_id] = values[factor_id]
        return frame

    monkeypatch.setattr(
        "quant_us.factors.evaluation.FactorEvaluator.evaluate",
        fake_evaluate,
    )
    monkeypatch.setattr(
        "quant_us.factors.pipeline.FactorPipeline.compute",
        fake_compute,
    )

    result = FactorMiningEngine(data_root=str(tmp_path)).mine(
        symbols=["aapl", "msft"],
        start="2024-01-01",
        end="2024-02-01",
        bar_sizes=["1d"],
        factor_ids=["momentum_20d", "momentum_60d", "volatility_20d"],
        max_abs_correlation=0.90,
        max_selected=3,
    )

    selected_keys = {
        (score.factor_id, score.bar_size) for score in result.selected_factors
    }
    assert ("momentum_20d", "1d") in selected_keys
    assert ("momentum_60d", "1d") not in selected_keys
    assert ("volatility_20d", "1d") in selected_keys
    assert {"single_factor_rank", "weighted_factor_basket", "consensus_rank"} <= {
        config["template_id"] for config in result.strategy_configs
    }
    assert any(config["strategy_id"] == "factor_rank" for config in result.strategy_configs)
    assert any(config["strategy_id"] == "factor_basket" for config in result.strategy_configs)
    assert any(config["strategy_id"] == "factor_consensus" for config in result.strategy_configs)
    assert all(config["timeframe"] == "1d" for config in result.strategy_configs)
    assert any(config["candidate_rank"] == 1 for config in result.strategy_configs)
    assert all("candidate_evidence" in config for config in result.strategy_configs)
    composite_configs = [
        config
        for config in result.strategy_configs
        if config["template_id"] in {"weighted_factor_basket", "consensus_rank"}
    ]
    assert composite_configs
    for config in composite_configs:
        evidence = config["candidate_evidence"]
        assert "capacity" in evidence
        assert "turnover" in evidence
        assert evidence["turnover"]["annual_turnover_pct"] >= 0.0

    persisted = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
    assert persisted["run_id"] == result.run_id
    assert len(persisted["selected_factors"]) == 2
    assert persisted["manifest_evidence"]["selected_count"] == 2
    assert persisted["manifest_evidence"]["compiled_strategy_count"] == len(
        result.strategy_configs
    )

    ranks = {
        (row["factor_id"], row["bar_size"]): row["candidate_rank"]
        for row in result.candidate_ranking
    }
    assert ranks[("momentum_20d", "1d")] < ranks[("momentum_60d", "1d")]

    score_by_key = {
        (score.factor_id, score.bar_size): score
        for score in result.factor_scores
    }
    assert score_by_key[("momentum_20d", "1d")].stability_score > 0.0
    assert (
        score_by_key[("momentum_60d", "1d")].reject_reason
        == "high_correlation_to_selected"
    )
    assert (
        score_by_key[("momentum_60d", "1d")].redundant_with_factor_id
        == "momentum_20d"
    )

    correlation_report = json.loads(
        Path(result.correlation_report_path).read_text(encoding="utf-8")
    )
    bar_report = correlation_report["bar_sizes"][0]
    assert bar_report["selected_factor_ids"] == ["momentum_20d", "volatility_20d"]
    assert any(
        row["factor_id"] == "momentum_60d"
        and row["redundant_with_factor_id"] == "momentum_20d"
        for row in bar_report["redundant_candidates"]
    )

    compiled_logic = json.loads(
        Path(result.strategy_logic_paths[0]).read_text(encoding="utf-8")
    )
    assert compiled_logic["schema_version"] == "research_strategy_artifact_v1"
    assert compiled_logic["artifact_type"] == "research_strategy_logic_template"
    assert compiled_logic["research_controls"]["promotion_status"] == "RESEARCH_ONLY"
    assert compiled_logic["research_controls"]["paper_trading_enabled"] is False
    assert compiled_logic["research_controls"]["live_trading_enabled"] is False
    assert compiled_logic["safeguards"]["capacity"]
    assert compiled_logic["safeguards"]["turnover"]
    assert compiled_logic["safeguards"]["style_exposure"]
    assert (
        compiled_logic["validation_summary"]["status"]
        == "pending_research_validation"
    )


def test_factor_mining_rejects_weak_and_underpopulated_factors(
    monkeypatch,
    tmp_path,
) -> None:
    metrics = {
        "momentum_20d": FactorEvaluationResult(
            factor_id="momentum_20d",
            ic_mean=0.03,
            icir=0.8,
            rank_ic_mean=0.04,
            long_short_spread=0.02,
            hit_rate=0.55,
            n_observations=100,
        ),
        "liquidity_20d": FactorEvaluationResult(
            factor_id="liquidity_20d",
            ic_mean=0.08,
            icir=1.0,
            rank_ic_mean=0.08,
            long_short_spread=0.02,
            hit_rate=0.55,
            n_observations=5,
        ),
        "reversal_1d": FactorEvaluationResult(
            factor_id="reversal_1d",
            ic_mean=0.001,
            icir=0.1,
            rank_ic_mean=0.001,
            long_short_spread=0.001,
            hit_rate=0.50,
            n_observations=100,
        ),
    }

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
        if factor_id == "volume_20d":
            raise FileNotFoundError("missing 5m sample")
        return metrics[factor_id]

    monkeypatch.setattr(
        "quant_us.factors.evaluation.FactorEvaluator.evaluate",
        fake_evaluate,
    )

    result = FactorMiningEngine(data_root=str(tmp_path)).mine(
        symbols=["AAPL", "MSFT"],
        start="2024-01-01",
        end="2024-02-01",
        bar_sizes=["1d", "5m"],
        factor_ids=["momentum_20d", "liquidity_20d", "reversal_1d", "volume_20d"],
        min_abs_rank_ic=0.01,
        min_observations=20,
    )

    reasons = {
        (score.factor_id, score.bar_size): score.reject_reason
        for score in result.factor_scores
    }
    assert reasons[("liquidity_20d", "1d")] == "insufficient_observations"
    assert reasons[("reversal_1d", "1d")] == "weak_rank_ic"
    assert reasons[("volume_20d", "1d")] == "evaluation_error:FileNotFoundError"
    assert all(score.factor_id == "momentum_20d" for score in result.selected_factors)
    assert {score.bar_size for score in result.selected_factors} == {"1d", "5m"}
