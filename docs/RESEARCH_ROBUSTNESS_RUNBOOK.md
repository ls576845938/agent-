# Research Robustness Runbook (R6)

## Purpose

This runbook explains how to use the Alpha Robustness Engine (R6) to validate that strategy alphas are statistically robust, not the result of data mining or overfitting.

## Prerequisites

- A completed backtest with trade-level results
- A registered StrategyCandidate with candidate.json

## Workflow

### Step 1: Compute Monte Carlo Survival Rate

Run bootstrap resampling on the candidate's trade list to estimate survival rate:

```python
import random

trades = [...]  # list of trade returns from backtest
seed = 42
n_iterations = 1000
n_samples = len(trades)
rng = random.Random(seed)

bootstrap_means = []
for _ in range(n_iterations):
    sample = [rng.choice(trades) for _ in range(n_samples)]
    bootstrap_means.append(sum(sample) / n_samples)

survival_rate = sum(1.0 for m in bootstrap_means if m > 0) / n_iterations
```

**Expected:** survival_rate > 0.80
**If failing:** The strategy's profits are concentrated in a few trades. Consider:
- Increasing trade count
- Improving trade consistency
- Adding a stop-loss or profit-target mechanism

### Step 2: Estimate Alpha Decay Half-Life

Fit an exponential decay model to the strategy's rolling alpha:

```python
# alpha_t = alpha_0 * 0.5^(t / half_life)
# half_life = time for alpha to reach 50% of initial value
rolling_alpha = [...]  # rolling alpha over time
half_life = estimate_half_life(rolling_alpha)
```

**Expected:** half_life > 5 days
**If warning:** The strategy's alpha decays rapidly. Consider:
- Shortening the holding period
- Improving signal quality
- Adding a faster exit mechanism

### Step 3: Compute Parameter Stability Score

Run the strategy with slightly perturbed parameters and measure performance variance:

```python
base_params = {"lookback": 20, "entry_zscore": 2.0}
perturbations = [
    {"lookback": 18, "entry_zscore": 1.8},
    {"lookback": 22, "entry_zscore": 2.2},
    {"lookback": 15, "entry_zscore": 2.5},
]

# Run backtest for each perturbation
sharpe_values = [run_backtest(p) for p in perturbations]
stability_score = 1.0 - (max(sharpe_values) - min(sharpe_values)) / max(sharpe_values)
```

**Expected:** stability_score > 0.5
**If failing:** Strategy is too sensitive to parameter selection. Consider:
- Reducing the number of parameters
- Using ensemble methods
- Adding parameter regularization

## Checking the Promotion Gate

The ResearchPromotionGate automatically evaluates all R6 checks:

```python
from quant_us.research.automation.promotion_gate import ResearchPromotionGate

gate = ResearchPromotionGate(data_root="data")
result = gate.evaluate(candidate_id)
print(f"Decision: {result.decision}")
print(f"Reasons: {result.reasons}")
print(f"Warnings: {result.warnings}")
print(f"Evidence: {result.evidence}")
```

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| Low Monte Carlo survival | Strategy relies on few large wins | Increase trade count, add exits |
| Rapid alpha decay | Signal fades quickly | Shorten holding period, improve signal |
| Unstable parameters | Strategy overfitted to specific params | Reduce param count, use ensembles |
| ALL R6 checks fail | Strategy has no genuine alpha | Return to research, find better signal |
