# Research Promotion Runbook (R8)

## Purpose

This runbook explains how to use the Research Promotion Gate with all R6/R7/R8 checks enabled. It covers stress testing, the promotion gate evaluation, and result interpretation.

## Prerequisites

- A StrategyCandidate with all required data:
  - Experiment manifest
  - Scorecard
  - OverfitDetector results
  - Walk-forward results
  - R6 metrics (Monte Carlo, alpha decay, param stability)
  - R7 metrics (correlation redundancy)
  - R8 metrics (stress survival rate)

## Workflow

### Step 1: Compute Stress Survival Rate

Run cost stress scenarios and crash window simulations:

```python
# Cost stress scenarios
cost_levels = [1.0, 2.0, 3.0, 5.0, 10.0]
returns_after_cost = []
base_return = 0.15

for cost_mult in cost_levels:
    cost_penalty = 0.02 * cost_mult
    net_return = base_return - cost_penalty
    returns_after_cost.append(max(net_return, -0.50))

survival_rate = sum(1.0 for r in returns_after_cost if r > 0) / len(returns_after_cost)
```

### Step 2: Run Full Promotion Gate

```python
from quant_us.research.automation.promotion_gate import ResearchPromotionGate

gate = ResearchPromotionGate(data_root="data")
result = gate.evaluate("candidate_id_here")

print(f"Candidate: {result.candidate_id}")
print(f"Decision: {result.decision}")
print(f"Reasons (BLOCKED): {result.reasons}")
print(f"Warnings (WATCHLIST): {result.warnings}")
print(f"Needs Research: {result.needs_more_research}")
```

### Step 3: Interpret the Decision

| Decision | Meaning | Next Step |
|----------|---------|-----------|
| BLOCKED | Fatal issue found | Fix the issues listed in `reasons` |
| NEED_MORE_RESEARCH | Additional research required | Investigate and resolve items in `needs_more_research` |
| WATCHLIST | Minor concerns exist | Note warnings in `warnings` for human review |
| READY_FOR_PAPER_REVIEW | All checks pass | Generate evidence pack and submit for human review |

### Step 4: Generate Evidence Pack and Create Paper Review

```python
from quant_us.research.evidence_pack import EvidencePackGenerator
from quant_us.research.paper_review_bridge import PaperReviewManager

# Generate comprehensive evidence pack
ev_gen = EvidencePackGenerator(data_root="data")
ev_path = ev_gen.save("candidate_id_here")

# Create paper review
mgr = PaperReviewManager(data_root="data")
review = mgr.create_review("sim_id_here")
# OR from portfolio evidence:
review = mgr.create_from_portfolio_evidence("candidate_id_here")
```

## Complete Promotion Gate Check List

Before running the promotion gate, ensure all metrics are populated in the candidate's `candidate.json` under `metrics`:

```json
{
    "metrics": {
        "walk_forward_pass_rate": 0.8,
        "trade_count": 50,
        "cost_sensitivity": 0.2,
        "max_drawdown_pct": 0.15,
        "monte_carlo_survival_rate": 0.85,
        "alpha_decay_half_life_days": 12.0,
        "param_stability_score": 0.75,
        "correlation_redundancy": 0.35,
        "stress_survival_rate": 0.85
    }
}
```

Missing metrics default to failure thresholds (0.0 for rates, causing BLOCKED/WATCHLIST/NEED_MORE_RESEARCH).

## Decision Priority

The gate uses a strict priority system:

```
1. Any BLOCKED reason found        → decision = BLOCKED
2. Any NEED_MORE_RESEARCH item     → decision = NEED_MORE_RESEARCH
3. Any WATCHLIST warning           → decision = WATCHLIST
4. No issues at all                → decision = READY_FOR_PAPER_REVIEW
```

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| Missing metrics defaulting to fail | Metrics not populated | Compute and add metrics to candidate.json |
| False positive on correlation | Only one strategy in portfolio | Correlation redundancy only meaningful with 2+ strategies |
| Stress survival blocked | Strategy fails under high costs | Reduce trading frequency, use limit orders |
| Gate takes too long | OverfitDetector running for many candidates | Check candidate data integrity |
