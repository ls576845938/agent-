# Strategy Research Lab Runbook

## Overview

The Strategy Research Lab provides tools for creating, running, and evaluating trading strategy experiments. It is the foundational layer of the research track, supporting experiment lifecycle management, parameter sweeps, and candidate promotion.

## Components

### ExperimentManager
Manages the full experiment lifecycle:
- **Create**: Initialize experiments in DRAFT status with strategy, symbols, and parameters
- **Run**: Execute backtests through the UnifiedBacktestRunner
- **Promote**: Promote completed experiments to StrategyCandidate status
- **Load/List**: Query experiments by ID or status filter

### ResearchSweepRunner
Executes parameter sweeps across a grid of strategy and portfolio parameters:
- Expands parameter grids into all combinations
- Runs each combination as a separate backtest
- Collects results and identifies the best-performing parameter set
- Uses `expand_parameter_grid()` for Cartesian product expansion

### ResearchScorecardBuilder
Computes standardized evaluation scorecards from candidate metrics:
- Risk/return metrics (CAGR, Sharpe, Sortino, Calmar)
- Trade statistics (win rate, profit factor, turnover, trade count)
- Overfit assessment (cost sensitivity, walk-forward metrics, robustness)
- Generates markdown reports

## Common Operations

### Creating an Experiment

```python
from quant_us.research.lab.manifest import ExperimentManager

mgr = ExperimentManager(data_root="data")
manifest = mgr.create(
    strategy_id="trend_momentum",
    symbols=["AAPL", "MSFT", "SPY"],
    params={"lookback": 20, "entry_zscore": 2.0},
    timeframe="1d",
    start_date="2020-01-01",
    end_date="2024-12-31",
)
print(f"Created experiment {manifest.experiment_id}")
```

### Running a Parameter Sweep

```python
from datetime import datetime
from quant_us.research.sweeps import ResearchSweepRunner, SweepConfig

config = SweepConfig(
    experiment_name="momentum_sweep",
    symbols=["AAPL", "MSFT"],
    start=datetime(2020, 1, 1),
    end=datetime(2024, 12, 31),
    strategy_id="trend_momentum",
    parameter_grid={
        "lookback": [10, 20, 40, 60],
        "entry_zscore": [1.5, 2.0, 2.5],
    },
    capital=100000.0,
)

runner = ResearchSweepRunner()
result = runner.run(config)
print(f"Best params: {result.best}")
```

### Promoting a Completed Experiment to Candidate

```python
mgr = ExperimentManager(data_root="data")
candidate = mgr.promote_to_candidate("exp_abc123")
print(f"Candidate {candidate.candidate_id} created")
print(f"Status: {candidate.promotion_status}")  # RESEARCH_ONLY
```

### Building a Scorecard

```python
from quant_us.research.lab.scorecard import ResearchScorecardBuilder

builder = ResearchScorecardBuilder(data_root="data")
scorecard = builder.build("cand_abc123")
print(f"Sharpe: {scorecard.sharpe:.2f}")
print(f"Max Drawdown: {scorecard.max_drawdown:.2%}")

# Generate markdown report
md = builder.to_markdown(scorecard)
print(md)
```

### Ranking Candidates

```python
candidates = mgr.list_candidates()
candidate_ids = [c.candidate_id for c in candidates]
ranked = builder.rank_candidates(candidate_ids)
for cid, score in ranked:
    print(f"{cid}: {score:.4f}")
```

## Status Transitions

```
DRAFT -> RUNNING -> COMPLETED -> PROMOTED_TO_CANDIDATE -> [Manual] PAPER_ELIGIBLE
                     |                                       |
                     v                                       v
                   FAILED                                REJECTED
```

## Safety Rules

1. **Never import from live modules**: Research code must not import `quant_us.live` or `quant_us.execution`
2. **No order submission**: ExperimentManager has no `submit_order` method or any broker reference
3. **Max auto-status**: promote_to_candidate() always creates RESEARCH_ONLY status
4. **Manual promotion required**: PAPER_ELIGIBLE requires direct file manipulation (simulating CLI --manual flag)
5. **No live promotion**: There is no promote_to_live method anywhere in the research track

## File Locations

- Experiments: `data/research/experiments/<experiment_id>/manifest.json`
- Candidates: `data/research/candidates/<candidate_id>/candidate.json`
- Scorecards: `data/research/scorecards/<candidate_id>.json`
- Backtest Results: `data/backtest_results/<run_id>/`
