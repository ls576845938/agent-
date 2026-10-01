# Phase R8: Research-to-Production Promotion System

## Overview

Phase R8 completes the research-to-production promotion pipeline by adding stress testing validation and consolidating the promotion gate with all R6/R7/R8 checks.

## Components

### 1. ResearchPromotionGate - R8 Check

The enhanced `ResearchPromotionGate` includes one R8 check:

| Check | Metric | Threshold | Outcome on Failure |
|-------|--------|-----------|-------------------|
| Stress Survival | `stress_survival_rate` | > 0.70 | BLOCKED |

### 2. Stress Survival Rate

**Purpose:** Verify strategy resilience under adverse market conditions (cost stress, crash windows).

**Method:**
- Run the strategy under multiple stress scenarios:
  - **Cost stress:** Increase trading costs by 1x, 2x, 3x, 5x, 10x and re-evaluate returns
  - **Crash windows:** Simulate historical crash periods (2008 financial crisis, 2020 COVID crash, 2022 rate hike)
- `stress_survival_rate` = fraction of stress scenarios where the strategy maintains positive returns or stays above a survival threshold

**Threshold:** > 0.70 (at least 70% of stress scenarios must be survived)

**Failure:** BLOCKED with reason `stress_survival_low`

## Complete Promotion Gate (All Phases)

The `ResearchPromotionGate.evaluate()` now runs 13 checks across all research phases:

| # | Phase | Check | Threshold | Failure |
|---|-------|-------|-----------|---------|
| 1 | R2 | Manifest exists | File exists | BLOCKED |
| 2 | R2 | Experiment manifest | File exists | BLOCKED |
| 3 | R2 | Scorecard exists | File exists | BLOCKED |
| 4 | R2 | Overfit detection | Not overfit | BLOCKED |
| 5 | R2 | Walk-forward run | pass_rate >= 0 | WATCHLIST |
| 6 | R2 | Trade count | > 10 | WATCHLIST |
| 7 | R2 | Cost stress | sensitivity <= 0.5 | BLOCKED |
| 8 | R2 | Max drawdown | < 50% | BLOCKED |
| 9 | R6 | Monte Carlo survival | > 80% | BLOCKED |
| 10 | R6 | Alpha decay half-life | > 5 days | WATCHLIST |
| 11 | R6 | Param stability | > 0.5 | BLOCKED |
| 12 | R7 | Correlation redundancy | < 0.70 | NEED_MORE_RESEARCH |
| 13 | R8 | Stress survival | > 70% | BLOCKED |

### Decision Priority

```
BLOCKED > NEED_MORE_RESEARCH > WATCHLIST > READY_FOR_PAPER_REVIEW
```

If any check in a higher-priority category fails, the decision is immediately set to that category.

## Integration Tests

Comprehensive integration tests are in `backend/tests/test_r6_r7_r8.py`:

| Test Class | Coverage |
|------------|----------|
| TestMonteCarlo | Trade shuffle reproducibility, bootstrap return convergence |
| TestAlphaDecay | Half-life estimation, decay curve monotonicity |
| TestCorrelationCluster | Redundant pair detection, diversification scoring |
| TestPortfolioStress | Cost stress monotonic degradation, crash window survival |
| TestPromotionGateEnhanced | All R6/R7/R8 gate checks verify correct decision outcomes |
| TestSafetyInvariants | No live imports, no broker access, deterministic tests |

## Safety

- R8 stress checks operate on pre-computed metrics only
- No network calls or broker access
- All stress scenarios are simulated locally
- The promotion gate cannot promote beyond PAPER_ELIGIBLE
- PaperReviewManager.create_from_portfolio_evidence() is the only new pathway and requires portfolio-level evidence
