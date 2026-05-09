# Research Engine Architecture

## Overview

The Research Engine is the core of QuantStation's strategy development pipeline. It manages experiments, candidates, scoring, lineage tracking, and promotion gates -- all strictly isolated from live execution.

## Core Components

### ExperimentRegistry

The ExperimentRegistry is the central index of all research experiments. It maintains:

- **Experiment ID**: Unique identifier (`exp_<uuid>`)
- **Strategy ID**: Reference to the strategy template
- **Manifest**: Full reproduction metadata (see below)
- **Status**: DRAFT | RUNNING | COMPLETED | FAILED | PROMOTED_TO_CANDIDATE | REJECTED
- **Metrics**: Dictionary of backtest performance metrics

```
ExperimentRegistry
  |-- experiments/
  |   |-- exp_001/
  |   |   |-- manifest.json
  |   |   |-- results/
  |   |   |   |-- backtest.json
  |   |   |   |-- walk_forward.json
  |   |   |   |-- cost_stress.json
  |   |   |   |-- regime_split.json
  |   |   |-- scorecard.json
  |-- candidates/
  |   |-- cand_001/
  |   |   |-- candidate.json
  |   |   |-- lineage.json
```

### ExperimentManifest

Every experiment carries a manifest with full reproducibility metadata:

| Field | Description | Required |
|-------|-------------|----------|
| `experiment_id` | Unique experiment ID | Yes |
| `strategy_id` | Strategy template ID | Yes |
| `strategy_version` | Version of the strategy code | Yes |
| `strategy_family` | Strategy family label | Yes |
| `symbols` | List of symbols tested | Yes |
| `universe` | Universe selection | Yes |
| `timeframe` | Bar interval | Yes |
| `start_date` | Backtest start | Yes |
| `end_date` | Backtest end | Yes |
| `train_period` | Training period | Recommended |
| `test_period` | OOS test period | Recommended |
| `params` | Strategy parameters | Yes |
| `param_grid` | Parameter search grid | Optional |
| `data_version` | Market data version | Yes |
| `feature_version` | Feature set version | Yes |
| `cost_model` | Cost assumptions | Optional |
| `config_hash` | Deterministic hash of config | Auto |
| `status` | Experiment status | Yes |
| `metrics` | Performance metrics | Optional |
| `archived` | Archive flag | Default false |

The `config_hash` is computed deterministically from `{strategy_id, strategy_version, params, data_version, feature_version}` sorted by key. This enables exact reproducibility detection and candidate deduplication.

### StrategyCandidate

A candidate represents a strategy parameterization that has been evaluated:

| Field | Description |
|-------|-------------|
| `candidate_id` | Unique candidate ID (`cand_<uuid>`) |
| `experiment_id` | Source experiment |
| `strategy_id` | Strategy template ID |
| `params_hash` | Hash of strategy parameters |
| `promotion_status` | RESEARCH_ONLY | CANDIDATE | PAPER_ELIGIBLE | REJECTED |
| `robustness_score` | 0-1 robustness metric |
| `overfit_score` | 0-1 overfit risk (higher = riskier) |
| `alpha_score` | 0-1 alpha generation score |
| `risk_score` | 0-1 risk metric (higher = riskier) |
| `turnover_score` | 0-1 turnover metric |
| `metrics` | Dictionary of evaluation metrics |
| `parents` | List of parent candidate IDs (lineage) |
| `is_duplicate` | Flag if duplicate of another candidate |

### Lineage Tracking

Lineage tracks the parent-child relationships between candidates. When a candidate is refined (e.g., adjusted parameters, new data), the new candidate records its parents. This enables:

- **Chain traversal**: Walk from any candidate back to its root
- **Change auditing**: See what changed between generations
- **Performance regression**: Detect if refinement degraded performance

```
cand_001 (initial) --> cand_002 (refined params) --> cand_003 (new data)
```

Lineage is stored as a list of parent `candidate_id` strings. A candidate with no parents is a root candidate.

### CandidateScoring

The scoring pipeline evaluates candidates using the `CandidateScorer`:

1. **Score**: Computes raw scores for each candidate using performance, risk, and stability metrics
2. **Rank**: Sorts candidates by composite score, returns ranked list

Scoring dimensions:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Sharpe Ratio | 30% | Risk-adjusted return |
| CAGR | 15% | Annualized return |
| Max Drawdown | 15% | Inverse of worst loss |
| Walk-Forward Pass Rate | 15% | Stability across time folds |
| Cost Robustness | 10% | Performance under cost stress |
| Turnover Efficiency | 10% | Return per unit turnover |
| Overfit Penalty | -5% | Penalty for overfit signals |

### OverfitDetector

The OverfitDetector checks every candidate before promotion:

| Check | Threshold | Triggers Rejection |
|-------|-----------|-------------------|
| OOS Degradation | > 40% | Yes |
| Parameter Sensitivity | > 0.5 | Yes |
| Trade Count | < 10 | Yes |
| Single-Year Concentration | > 50% | Yes |
| Single-Symbol Concentration | > 60% | Yes |
| Cost Stress Failure | Sharpe < 0 at 5x costs | Yes |

Any single criterion triggers `is_overfit = True` and blocks promotion.

### WalkForwardScoring

Walk-forward validation splits data into sequential folds. Each fold contains a training period and an out-of-sample validation period:

```
Fold 0: [train 2020-01..2021-06] -> [validate 2021-07..2022-06]
Fold 1: [train 2020-07..2022-06] -> [validate 2022-07..2023-06]
Fold 2: [train 2021-01..2023-06] -> [validate 2023-07..2024-06]
```

Key metrics:
- **Pass Rate**: Fraction of folds where strategy survives (meets minimum performance)
- **Parameter Stability**: How much parameters vary between folds
- **OOS Degradation**: Performance drop from in-sample to out-of-sample

Minimum 2 folds required for meaningful walk-forward analysis.

### ResearchPromotionGate

The promotion gate is the final checkpoint before a candidate can be marked as PAPER_ELIGIBLE:

| Check | What It Validates |
|-------|-------------------|
| Manifest exists | Experiment manifest is present and complete |
| Not overfit | OverfitDetector returns False |
| Sharpe above threshold | Sharpe > 0.5 minimum |
| Trade count sufficient | >= 10 trades |
| Cost stress passes | Survives at 1x and 3x costs |
| Walk-forward passes | Pass rate >= 50% |

Gate statuses:
- **BLOCKED**: One or more checks failed
- **PASS**: All checks passed, ready for review

Max promotion stage is **PAPER_ELIGIBLE** (a status marker, not execution). Further promotion requires manual governance processes outside the research engine.

## Safety Architecture

```
Research Modules
  |-- No live imports (quant_us.live, quant_us.execution)
  |-- No submit_order() calls
  |-- No AlpacaBroker references
  |-- No QUANT_LIVE env var references
  |-- No broker configs
  |-- Automated output stops at paper_review_ready evidence; PAPER_ELIGIBLE is manual
  |-- All tests use tmp_path + fake data
```

See [RUNTIME_SAFETY.md](./RUNTIME_SAFETY.md) for the full safety architecture.
