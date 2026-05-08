# Research Automation Runbook

## Overview

The Research Automation pipeline orchestrates the end-to-end research workflow: loading strategy templates, running batch backtests, evaluating candidates, detecting overfitting, ranking, generating dossiers, and marking candidates as PAPER_ELIGIBLE for further consideration.

## Pipeline Steps

The `ResearchAutomationPipeline` runs 11 steps:

1. **Load Strategy Templates**: Create experiments from configuration
2. **Generate Parameter Grids**: Expand parameter grids into full factorial combinations
3. **Run Batch Backtests**: Execute all experiments through the backtest runner
4. **Run Walk-Forward**: Split data into train/test periods and re-run
5. **Run Cost Stress**: Test with high/low cost and slippage assumptions
6. **Run Regime Split**: Test separately in bull, bear, and sideways regimes
7. **Compute Scorecards**: Generate ResearchScorecard for each candidate
8. **Rank Candidates**: Sort by multi-dimensional score
9. **Reject Overfit**: Remove candidates with overfitting signs
10. **Promote to PAPER_ELIGIBLE**: Mark clean candidates (manual-only marker)
11. **Generate Dossier**: Build complete markdown research dossiers

## Common Operations

### Running the Full Pipeline

```python
from quant_us.research.automation.pipeline import ResearchAutomationPipeline

pipeline = ResearchAutomationPipeline(data_root="data")

config = {
    "experiment_name": "momentum_research_v3",
    "strategy_id": "trend_momentum",
    "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN"],
    "params": {"lookback": 20, "entry_zscore": 2.0},
    "param_grid": {
        "lookback": [10, 20, 40, 60],
        "entry_zscore": [1.5, 2.0, 2.5],
    },
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
    "data_version": "v2",
    "feature_version": "v1",
}

result = pipeline.run(config)

print(f"Pipeline: {result['pipeline_id']}")
print(f"Status: {result['status']}")
print(f"Experiments: {len(result['experiment_ids'])}")
print(f"Candidates: {len(result['candidate_ids'])}")
print(f"Promoted: {len(result['promoted'])}")

for cid, score, breakdown in result['ranked_candidates']:
    print(f"  {cid}: score={score:.2f}")
```

### Evaluating a Single Experiment

```python
metrics = pipeline.step_evaluate("exp_abc123")
print(f"Sharpe: {metrics.get('sharpe_ratio')}")
print(f"CAGR: {metrics.get('cagr')}")
```

### Ranking All Existing Candidates

```python
ranked = pipeline.step_rank()
for cid, score, breakdown in ranked:
    print(f"{cid}: total={score:.2f}")
    for component, value in breakdown.items():
        print(f"  {component}: {value:.2f}")
```

### Manual Promotion to PAPER_ELIGIBLE

```python
# Requires explicit action -- this is the manual step
candidate = pipeline.step_promote("cand_abc123")
print(f"Promoted {candidate.candidate_id} to {candidate.promotion_status}")

# Attempting to promote again will raise ValueError
# because already PAPER_ELIGIBLE
try:
    pipeline.step_promote("cand_abc123")
except ValueError as e:
    print(f"Expected error: {e}")
```

## Candidate Ranking Engine

The `CandidateRankingEngine` scores candidates on 8 dimensions:

| Dimension | Max Score | Description |
|-----------|-----------|-------------|
| Performance | 30 | Based on Sharpe and CAGR |
| Risk | 20 | Inverse of max drawdown |
| Stability | 20 | Walk-forward pass rate + OOS degradation |
| Cost Robustness | 10 | Resistance to trading costs |
| Regime Robustness | 10 | Consistent performance across regimes |
| Simplicity Bonus | 5 | Bonus for fewer parameters |
| Turnover Penalty | -5 | Penalty for high turnover |
| Overfit Penalty | -10 | Penalty for overfit risk |

Total possible range: -15 to 100 points.

## Overfit Detection

The `OverfitDetector` checks 6 criteria:

| Criterion | Threshold | Consequence |
|-----------|-----------|-------------|
| OOS Degradation | > 40% | Overfit |
| Parameter Sensitivity | > 0.5 | Overfit |
| Trade Count | < 10 | Overfit (not significant) |
| Single-Year Concentration | > 50% | Overfit |
| Single-Symbol Concentration | > 60% | Overfit |
| Cost Stress Failure | Sharpe < 0 after 5x costs | Overfit |

Any single criterion triggers `is_overfit = True`.

## Lookahead Bias Detection

The `LookaheadBiasChecker` detects potential lookahead bias:

| Check | Detection Method |
|-------|-----------------|
| High IC | IC > 0.2 suspiciously high |
| Constant IC | IC std near 0 with non-zero IC |
| bfill in features | `bfill_features: true` in params |
| shift(-1) | `shift_minus_one: true` in params |
| High Sharpe | Sharpe > 3.0 in experiment metrics |

## Dossier Builder

The `ResearchDossierBuilder` generates comprehensive markdown dossiers:

```python
from quant_us.research.automation.dossier import ResearchDossierBuilder

builder = ResearchDossierBuilder(data_root="data")

# Full dossier as markdown
dossier = builder.build("cand_abc123")
print(dossier[:500])  # First 500 chars

# Get recommendation only
rec = builder.recommend("cand_abc123")
print(f"Recommendation: {rec}")
```

### Recommendation Logic

| Condition | Recommendation |
|-----------|---------------|
| Overfit detected | REJECT |
| Sharpe <= 0 | REJECT |
| Sharpe < 0.5 | RESEARCH_MORE |
| Trade count < 10 | RESEARCH_MORE |
| Overfit risk == HIGH | RESEARCH_MORE |
| Max drawdown > 30% | RESEARCH_MORE |
| Sharpe >= 1.0 and drawdown <= 20% | PORTFOLIO_CANDIDATE |
| Sharpe >= 0.5 and drawdown <= 25% | PAPER_ELIGIBLE |
| Otherwise | RESEARCH_MORE |

## Safety Rules

1. **No live promotion**: Max promotion is PAPER_ELIGIBLE (a marker, not execution)
2. **Manual promotion required**: step_promote() requires explicit caller intent
3. **No submit_order**: Pipeline has no order submission capability
4. **No broker access**: Pipeline does not import from live/execution modules
5. **Overfit guard**: Overfit candidates are marked REJECTED, not promoted
6. **Cannot promote REJECTED**: Rejected candidates cannot be promoted

## File Locations

- Pipeline results: `data/research/pipeline_results/<pipeline_id>.json`
- Dossiers: `data/research/dossiers/<candidate_id>.md`
- Experiments: `data/research/experiments/<experiment_id>/manifest.json`
- Candidates: `data/research/candidates/<candidate_id>/candidate.json`
- Scorecards: `data/research/scorecards/<candidate_id>.json`
