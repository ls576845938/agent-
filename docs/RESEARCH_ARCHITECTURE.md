# Research Architecture (Extended for R6/R7/R8)

## Overview

The QuantStation Research Track is organized into phases:

- **R2 (Hardened):** Experiment manifests, candidate lineage, dedup, scoring, promotion gate (basic)
- **R5 (Automation):** Pipeline automation, ranking, overfit detection, dossiers
- **R6 (Robustness):** Monte Carlo validation, alpha decay, parameter stability
- **R7 (Portfolio):** Multi-strategy correlation, diversification analysis
- **R8 (Promotion):** Stress testing, complete promotion gate, evidence-based paper review

## R6: Alpha Robustness Engine

**Location:** `quant_us/research/automation/promotion_gate.py` (extended)

**New checks in PromotionGate:**
- Monte Carlo survival rate (> 0.80)
- Alpha decay half-life (> 5 days)
- Parameter stability score (> 0.5)

**Data flow:**
```
Candidate Backtest → Trade List → Bootstrap Resampling → Survival Rate
                    → Rolling Alpha → Decay Model → Half-Life
                    → Param Perturbation → Stability Variance → Stability Score
                                                 ↓
                          PromotionGate.evaluate() → Decision
```

## R7: Multi-Strategy Portfolio Research

**Location:** `quant_us/research/automation/promotion_gate.py` (extended)
**New integration:** `quant_us/research/paper_review_bridge.py` (extended)

**New check in PromotionGate:**
- Correlation redundancy (< 0.70)

**New PaperReviewManager method:**
- `create_from_portfolio_evidence()`: Creates paper review directly from portfolio-level evidence packs

**Data flow:**
```
Strategy Manifests → Pairwise Correlation Matrix → Max Correlation
                                                      ↓
                          PromotionGate.evaluate() → NEED_MORE_RESEARCH?
                                                      ↓
                          PaperReviewManager.create_from_portfolio_evidence()
                                                      ↓
                          PaperReviewCandidate (PENDING_HUMAN_REVIEW)
```

## R8: Research-to-Production Promotion

**Location:** `quant_us/research/automation/promotion_gate.py` (extended)

**New check in PromotionGate:**
- Stress survival rate (> 0.70)

**Complete 13-check gate:**
| Phase | Checks |
|-------|--------|
| R2 | Manifest, Scorecard, Overfit, Walk-Forward, Trade Count, Cost Stress, Max Drawdown |
| R6 | Monte Carlo, Alpha Decay, Param Stability |
| R7 | Correlation Redundancy |
| R8 | Stress Survival |

## Module Dependency Graph

```
evidence_pack.py
    └─> promotion_gate.py (ResearchPromotionGate)
    └─> overfit.py (OverfitDetector)
    └─> lab/manifest.py (ExperimentManager)
    
paper_review_bridge.py
    └─> portfolio_sim_bridge.py (PortfolioSimBridge)
    └─> strategy_manifest.py (StrategyManifestManager)
    └─> core/clock.py (utc_now)
    └─> core/types.py (new_id)
    
promotion_gate.py
    └─> overfit.py (OverfitDetector)
    (All checks read from candidate.json metrics dict)
```

## New Decision Outcome: NEED_MORE_RESEARCH

The promotion gate now has 4 decision outcomes:

| Outcome | Priority | Meaning |
|---------|----------|---------|
| BLOCKED | Highest | Fatal issue, must fix |
| NEED_MORE_RESEARCH | Medium | Additional research needed |
| WATCHLIST | Low | Non-blocking concern |
| READY_FOR_PAPER_REVIEW | None | All checks pass |

## Safety Boundaries (Extended for R6/R7/R8)

All R6/R7/R8 components:
- Read from pre-computed candidate data only
- Never import from `quant_us.live` or `quant_us.execution`
- Never reference `AlpacaBroker` or `submit_order()`
- Never trigger paper or live trading
- Use `tmp_path` and synthetic data in tests (deterministic, seeded RNG)
