# Phase R6: Alpha Robustness Engine

## Overview

Phase R6 adds statistical robustness validation to the research track, ensuring that candidate strategies have genuine alpha that is not the result of data mining, overfitting, or parameter instability.

## Components

### 1. ResearchPromotionGate - R6 Checks

The enhanced `ResearchPromotionGate` (in `quant_us/research/automation/promotion_gate.py`) now includes three R6 checks:

| Check | Metric | Threshold | Outcome on Failure |
|-------|--------|-----------|-------------------|
| Monte Carlo Survival | `monte_carlo_survival_rate` | > 0.80 | BLOCKED |
| Alpha Decay | `alpha_decay_half_life_days` | > 5 days | WATCHLIST |
| Parameter Stability | `param_stability_score` | > 0.5 | BLOCKED |

### 2. Monte Carlo Survival

**Purpose:** Verify strategy robustness by simulating many alternative trade sequences via bootstrapping or shuffling.

**Method:**
- Take the observed trade list from the candidate's backtest
- Resample with replacement (bootstrap) or shuffle trade order N times (default: 1000)
- For each iteration, compute the net return
- `monte_carlo_survival_rate` = fraction of iterations with positive net return

**Threshold:** > 0.80 (at least 80% of bootstrap trials produce positive returns)

**Failure:** BLOCKED with reason `monte_carlo_survival_low`

### 3. Alpha Decay Half-Life

**Purpose:** Measure how quickly the strategy's alpha decays over time. Strategies with rapid alpha decay are likely capturing ephemeral market anomalies rather than persistent signals.

**Method:**
- Compute alpha (excess return over benchmark) over a rolling window
- Fit an exponential decay model: alpha(t) = alpha_0 * 0.5^(t / half_life)
- Estimate half-life as the time for alpha to drop to 50% of initial value

**Threshold:** half-life > 5 days

**Failure:** WATCHLIST with warning `rapid_alpha_decay`

### 4. Parameter Stability

**Purpose:** Verify that strategy performance is not overly sensitive to small parameter changes.

**Method:**
- Run the strategy with perturbed parameters (within a small neighborhood)
- Compute performance variance across perturbations
- `param_stability_score` = 1.0 - normalized_variance

**Threshold:** > 0.5

**Failure:** BLOCKED with reason `param_unstable`

## Data Model

All R6 metrics are stored in the candidate's `metrics` dict:

```python
{
    "monte_carlo_survival_rate": 0.85,   # float [0.0, 1.0]
    "alpha_decay_half_life_days": 12.0,  # float (days)
    "param_stability_score": 0.75,       # float [0.0, 1.0]
}
```

## Integration Points

- EvidencePackGenerator automatically picks up R6 metrics from candidate data
- The promotion gate enforces all R6 checks in a single `evaluate()` call
- R6 checks are evaluated after existing R2 checks (manifest, overfit, walk-forward, cost stress, drawdown)
- No new modules are introduced; existing modules are extended

## Safety

- R6 checks operate on existing candidate data only
- No network calls, no broker access
- No live trading interaction
- All data is locally computed and stored
