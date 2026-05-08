# Research Track Architecture

## Overview

The QuantStation Research Track is a self-contained research environment for developing, testing, and evaluating quantitative trading strategies. It is strictly isolated from live execution -- no research module can submit orders, access real brokers, or promote strategies to production without explicit manual intervention.

## Architecture Principles

1. **Zero Live Access**: Research modules never import from `quant_us.live` or `quant_us.execution`. No `submit_order()`, `AlpacaBroker`, or `QUANT_LIVE` references exist in research code.
2. **Max Promotion: PAPER_ELIGIBLE**: The maximum automated promotion level is `PAPER_ELIGIBLE` (a marker). Further promotion requires manual CLI flags and external governance processes.
3. **No Lookahead**: All factor computations and regime detection use only data available at time `t`. Rolling/expanding windows, never full-dataset statistics.
4. **Temporary Data Isolation**: Tests use `tmp_path` and fake data. No real API keys, no network calls.
5. **Surgical Imports**: Research modules import only from `quant_us.core`, `quant_us.backtest`, `quant_us.data`, `quant_us.strategies`, and `quant_us.factors`. Never from execution or live modules.

## Module Architecture

```
quant_us/research/
    __init__.py
    experiments.py       -- ExperimentSpec, ExperimentRegistry
    datasets.py          -- MLFeatureDatasetBuilder, DatasetSpec
    sweeps.py            -- ResearchSweepRunner, SweepConfig
    cache.py             -- ResearchCache (parquet + JSON caching)

    lab/
        __init__.py
        manifest.py      -- ResearchExperimentManifest, ExperimentManager,
                            StrategyCandidate
        scorecard.py     -- ResearchScorecard, ResearchScorecardBuilder

    automation/
        __init__.py
        pipeline.py      -- ResearchAutomationPipeline
        ranking.py       -- CandidateRankingEngine
        overfit.py       -- OverfitDetector, LookaheadBiasChecker,
                            OverfitReport
        dossier.py       -- ResearchDossierBuilder

quant_us/factors/
    definition.py        -- FactorDefinition, FactorLibrary
    feature_pipeline.py  -- FeaturePipeline
    momentum.py, volatility.py, liquidity.py, quality.py, value.py

quant_us/regime/
    detector.py          -- MarketRegimeDetector, RegimeState, RegimeResult
    backtest.py          -- RegimeAwareBacktest, RegimeBacktestResult
    report.py            -- RegimeReportBuilder
    store.py             -- RegimeFeatureStore, RegimeRecord

quant_us/portfolio/
    allocation.py        -- AllocationCombiner
    construction/
        engine.py        -- PortfolioConstructionEngine, PortfolioConfig,
                            PortfolioTarget
        allocator.py     -- CapitalAllocator, AllocationMethod
        exposure.py      -- ExposureManager, ExposureReport
        backtest.py      -- PortfolioBacktestRunner, PortfolioBacktestResult
        scorecard.py     -- PortfolioScorecard, PortfolioScorecardBuilder
```

## Data Flow

```
Strategy Templates --> ExperimentManager --> Backtest Runner --> Results
       |                     |                      |               |
       v                     v                      v               v
  Parameter Grids      ExperimentRegistry      Data Lake      Scorecard
       |                                                            |
       v                                                            v
  Batch Runner --> Candidate Ranking --> Overfit Detection --> Dossier
                                  |                              |
                                  v                              v
                           PAPER_ELIGIBLE                   Recommendation
                           (manual only)                      REJECT
                                                           RESEARCH_MORE
                                                           PAPER_ELIGIBLE
                                                           PORTFOLIO_CANDIDATE
```

## Safety Boundaries

| Layer | Can Submit Orders | Can Access Live API | Max Auto-Promotion |
|-------|-------------------|---------------------|--------------------|
| Research Backtest | No | No | N/A |
| Candidate Registry | No | No | RESEARCH_ONLY |
| Automation Pipeline | No | No | PAPER_ELIGIBLE |
| Factor Computation | No | No | N/A |
| Regime Detection | No | No | N/A |
| Portfolio Construction | No | No | N/A |

## Key Dataclasses

### ResearchExperimentManifest
- `experiment_id`, `strategy_id`, `strategy_version`, `strategy_family`
- `symbols`, `universe`, `timeframe`, `start_date`, `end_date`
- `train_period`, `test_period`, `walk_forward_config`
- `params`, `param_grid`, `data_version`, `feature_version`
- `cost_model`, `slippage_model`
- `status`: DRAFT | RUNNING | COMPLETED | FAILED | PROMOTED_TO_CANDIDATE | REJECTED
- `metrics`: dict of backtest results

### StrategyCandidate
- `candidate_id`, `experiment_id`, `strategy_id`, `params_hash`
- `promotion_status`: RESEARCH_ONLY | CANDIDATE | PAPER_ELIGIBLE | REJECTED
- `robustness_score`, `overfit_score`, `alpha_score`, `risk_score`, `turnover_score`
- `metrics`: dict of evaluation metrics

### ResearchScorecard
- `cagr`, `sharpe`, `sortino`, `calmar`, `max_drawdown`
- `win_rate`, `profit_factor`, `turnover`, `avg_exposure`, `trade_count`
- `cost_sensitivity`, `walk_forward_pass_rate`, `oos_degradation`
- `robustness_score`, `overfit_risk`

## Test Architecture

All research tests follow these rules:
1. Use `tmp_path` or `TemporaryDirectory` for file I/O
2. Use synthetic/fake data, never real market data
3. No network calls or broker connections
4. Verify research modules have no live imports
5. Each test file covers a single module or concern
6. Target 120+ total tests across all research test files
