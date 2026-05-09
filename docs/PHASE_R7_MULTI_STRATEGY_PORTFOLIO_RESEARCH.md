# Phase R7: Multi-Strategy Portfolio Research

## Overview

Phase R7 adds portfolio-level research capabilities to detect correlation redundancy across strategies. This ensures that a multi-strategy portfolio achieves genuine diversification, not just concentrated bets disguised as separate strategies.

## Components

### 1. ResearchPromotionGate - R7 Check

The enhanced `ResearchPromotionGate` includes one R7 check:

| Check | Metric | Threshold | Outcome on Failure |
|-------|--------|-----------|-------------------|
| Correlation Redundancy | `correlation_redundancy` | < 0.70 | NEED_MORE_RESEARCH |

### 2. Correlation Redundancy Detection

**Purpose:** Detect when strategies in a portfolio are highly correlated, indicating they are capturing the same underlying signal rather than providing diversification.

**Method:**
- Compute pairwise correlation matrix for all strategy manifests in the portfolio
- `correlation_redundancy` = max absolute pairwise correlation across all strategy pairs
- A high value indicates that at least two strategies are highly correlated

**Threshold:** < 0.70

**Failure:** NEED_MORE_RESEARCH with reason `high_redundancy`

### 3. NEED_MORE_RESEARCH Decision

The `NEED_MORE_RESEARCH` decision is a new promotion gate outcome, distinct from BLOCKED and WATCHLIST:

| Decision | Meaning | Action Required |
|----------|---------|-----------------|
| BLOCKED | Fatal issue detected | Must fix before proceeding |
| WATCHLIST | Non-fatal concern | Monitor during review |
| NEED_MORE_RESEARCH | Additional research required | Conduct further analysis before resubmission |
| READY_FOR_PAPER_REVIEW | All checks pass | Candidate enters human review pool |

## Data Model

The R7 metric is stored in the candidate's `metrics` dict:

```python
{
    "correlation_redundancy": 0.35,  # float [0.0, 1.0]
}
```

## PaperReviewCandidate Portfolio Evidence Integration

The `PaperReviewManager.create_from_portfolio_evidence()` method (in `quant_us/research/paper_review_bridge.py`) provides a new pathway for creating paper reviews directly from portfolio-level evidence packs:

```
Evidence Pack (portfolio-level)
  └─> create_from_portfolio_evidence()
        └─> PaperReviewCandidate (PENDING_HUMAN_REVIEW)
```

**Validation:**
- Evidence pack must exist at `data/research/evidence_packs/<id>/evidence_pack.json`
- Evidence pack must contain a non-trivial `portfolio_sim` section
- Promotion gate must not be BLOCKED
- Extraction of symbols, capital, and risk envelope from evidence data

## Safety

- R7 checks operate on computed correlation metrics only
- No network calls or broker access
- PaperReviewManager.create_from_portfolio_evidence() is read-only on existing evidence
- No auto-promotion: result remains PENDING_HUMAN_REVIEW
