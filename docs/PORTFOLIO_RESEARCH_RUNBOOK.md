# Portfolio Research Runbook (R7)

## Purpose

This runbook explains how to use the Multi-Strategy Portfolio Research (R7) features to detect correlation redundancy and ensure genuine portfolio diversification.

## Prerequisites

- Multiple StrategyCandidateManifests that have passed the ResearchPromotionGate
- Scorecards for each strategy manifest

## Workflow

### Step 1: Check Pairwise Correlations

Use PortfolioSimBridge to check correlation between strategies before creating a full simulation:

```python
from quant_us.research.portfolio_sim_bridge import PortfolioSimBridge

bridge = PortfolioSimBridge(data_root="data")
corr_result = bridge.check_correlation(["manifest_001", "manifest_002", "manifest_003"])
print(f"Pairwise correlations: {corr_result['pairs']}")
print(f"Warnings: {corr_result['warnings']}")
```

**Expected:** No warnings (all pairs have abs(correlation) < 0.70)
**Check:** `corr_result['max_correlation']` for the highest pairwise correlation

### Step 2: Run Portfolio Simulation

```python
request = bridge.create_simulation(
    ["manifest_001", "manifest_002", "manifest_003"],
    config={"allocation_method": "equal_weight", "capital": 100000.0}
)
result = bridge.run_simulation(request.portfolio_sim_id)
print(f"Decision: {result.decision}")
print(f"Risk breaches: {result.risk_breach_count}")
```

### Step 3: Check Correlation Redundancy in Promotion Gate

The ResearchPromotionGate's `correlation_redundancy` check uses the max pairwise correlation:

```python
from quant_us.research.automation.promotion_gate import ResearchPromotionGate

gate = ResearchPromotionGate(data_root="data")
result = gate.evaluate(candidate_id)
if result.decision == "NEED_MORE_RESEARCH":
    print(f"Needs more research: {result.needs_more_research}")
    # Review the redundancy issue before proceeding
```

### Step 4: Create Paper Review from Portfolio Evidence

Once portfolio simulations pass, create a paper review from evidence:

```python
from quant_us.research.evidence_pack import EvidencePackGenerator
from quant_us.research.paper_review_bridge import PaperReviewManager

# Generate evidence pack
ev_gen = EvidencePackGenerator(data_root="data")
ev_path = ev_gen.save(candidate_id)
print(f"Evidence pack: {ev_path}")

# Create paper review from evidence
mgr = PaperReviewManager(data_root="data")
review = mgr.create_from_portfolio_evidence(candidate_id)
print(f"Review: {review.paper_review_id}, Status: {review.status}")
```

## Correlation Redundancy Interpretation

| Max Correlation | Interpretation | Action |
|----------------|---------------|--------|
| < 0.30 | Well diversified | Proceed |
| 0.30 - 0.50 | Moderately diversified | Acceptable, monitor |
| 0.50 - 0.70 | Some redundancy | Consider replacing redundant pairs |
| >= 0.70 | High redundancy | NEED_MORE_RESEARCH - restructure portfolio |

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| High correlation between strategies | Strategies share same signal family | Choose uncorrelated strategies |
| Invalid manifest error | Manifest params not frozen | Call manifest_mgr.freeze_params() first |
| Evidence pack creation fails | Missing portfolio_sim section | Run portfolio simulation first |
