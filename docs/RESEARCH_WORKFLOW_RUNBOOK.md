# Research Workflow Runbook

## Overview

This runbook describes the day-to-day research workflow: from creating experiments to evaluating candidates, comparing results, promoting strategies, and verifying safety.

## Prerequisites

- QuantStation environment configured (see setup docs)
- Market data populated for relevant symbols/periods
- Strategy templates registered in the research registry

## Step-by-Step Workflow

### 1. Create a New Experiment

Create an experiment by defining strategy parameters and search space:

```python
from quant_us.research.lab.manifest import ExperimentManager

mgr = ExperimentManager()
exp = mgr.create_experiment(
    strategy_id="trend_momentum",
    symbols=["AAPL", "MSFT", "GOOGL", "AMZN"],
    params={"lookback": 20, "entry_zscore": 2.0},
    param_grid={
        "lookback": [10, 20, 40, 60],
        "entry_zscore": [1.5, 2.0, 2.5],
    },
    start_date="2020-01-01",
    end_date="2024-12-31",
)
print(f"Created: {exp.experiment_id}")
```

### 2. Run Backtest

Execute the experiment through the backtest engine:

```python
# Via API
mgr.run_experiment(exp.experiment_id)

# Via CLI (from project root)
python -m quant_us.cli research run exp_001
```

### 3. Score Candidates

After backtesting, score all candidates:

```python
mgr.score_experiment(exp.experiment_id)
```

This runs:
- Scorecard computation
- Overfit detection
- Walk-forward analysis
- Cost stress testing

### 4. View Rankings

List ranked candidates for an experiment:

```python
from quant_us.research.automation.scorer import CandidateScorer

scorer = CandidateScorer()
scores = scorer.score(exp.experiment_id)
ranked = scorer.rank(scores)

for i, c in enumerate(ranked[:10], 1):
    print(f"{i}. {c.candidate_id}: score={c.score:.3f}")
```

### 5. Compare Experiments

Compare multiple experiments side-by-side:

```python
results = mgr.compare_experiments(
    ["exp_001", "exp_002", "exp_003"],
    metric="sharpe",
)
for exp_id, candidates in results.items():
    print(f"{exp_id}: top candidate sharpe = {candidates[0]['sharpe']:.2f}")
```

### 6. Check Candidate Lineage

Trace a candidate's evolution through versions:

```python
lineage = mgr.get_lineage("cand_002")
for cand in lineage:
    print(f"{cand['candidate_id']}: {cand.get('params_hash')}")
```

### 7. Run Promotion Gate

Before marking a candidate as PAPER_ELIGIBLE, run the promotion gate:

```python
from quant_us.research.automation.promotion_gate import ResearchPromotionGate

gate = ResearchPromotionGate()
result = gate.evaluate("cand_002")
print(f"Gate status: {result.gate_status}")
print(f"Decision: {result.decision}")
```

### 8. Promote Candidate

Manual promotion to PAPER_ELIGIBLE (requires explicit intent):

```python
from quant_us.research.automation.pipeline import ResearchAutomationPipeline

pipeline = ResearchAutomationPipeline(data_root="data")
pipeline.step_promote("cand_002")
```

**Note**: This is a manual step. The pipeline never auto-promotes.

### 9. Generate Research Dossier

Generate a comprehensive markdown research dossier:

```python
from quant_us.research.automation.dossier import ResearchDossierBuilder

builder = ResearchDossierBuilder(data_root="data")
dossier = builder.build("cand_002")
print(dossier)
```

## API Quick Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/research/experiments` | List all experiments |
| GET | `/api/research/experiments/{id}` | Get experiment details |
| POST | `/api/research/experiments/{id}/run` | Run experiment backtest |
| POST | `/api/research/experiments/{id}/score` | Score experiment candidates |
| GET | `/api/research/experiments/{id}/ranking` | Get ranked candidates |
| GET | `/api/research/experiments/{id}/report` | Download experiment report |
| POST | `/api/research/experiments/compare` | Compare multiple experiments |
| POST | `/api/research/experiments/generate` | Generate candidates from config |
| GET | `/api/research/candidates` | List all candidates |
| GET | `/api/research/candidates/{id}/lineage` | Get candidate lineage |
| POST | `/api/research/candidates/{id}/promotion-gate` | Check promotion gate |

### Python SDK

```python
from quant_us.research.lab.manifest import ExperimentManager
from quant_us.research.automation.scorer import CandidateScorer
from quant_us.research.automation.promotion_gate import ResearchPromotionGate
from quant_us.research.automation.pipeline import ResearchAutomationPipeline
from quant_us.research.automation.dossier import ResearchDossierBuilder
```

## Common Recipes

### Find Best Candidates Across All Experiments

```python
mgr = ExperimentManager()
all_candidates = mgr.list_candidates()
ranked = sorted(all_candidates, key=lambda c: c.get("score", 0), reverse=True)
for c in ranked[:5]:
    print(f"{c['candidate_id']}: score={c['score']:.3f}")
```

### Check Overfit Risk Before Promotion

```python
gate = ResearchPromotionGate()
result = gate.evaluate("cand_003")
if result.gate_status == "BLOCKED":
    print(f"BLOCKED: {result.reason}")
else:
    print("Ready for promotion review")
```

### Detect Duplicate Candidates

```python
candidates = mgr.list_candidates()
hashes = {}
for c in candidates:
    h = c.get("params_hash")
    hashes.setdefault(h, []).append(c["candidate_id"])

dupes = {h: ids for h, ids in hashes.items() if len(ids) > 1}
for h, ids in dupes.items():
    print(f"Duplicate hash {h}: {ids}")
```

## Safety Checklist

Before any promotion action, verify:

- [ ] Candidate is not overfit (OOS degradation <= 40%)
- [ ] Trade count >= 10
- [ ] Sharpe >= 0.5
- [ ] Survives cost stress at 1x costs
- [ ] Walk-forward pass rate >= 50%
- [ ] Promotion gate returns PASS
- [ ] No live modules imported
- [ ] No broker access needed

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| Experiment not found | Registry path mismatch | Check `data/research/experiments/` |
| Scoring returns empty | Backtest not run yet | Run experiment first |
| Promotion gate BLOCKED | Overfit or missing data | Check gate reason field |
| Compare returns empty | Experiment IDs don't exist | Verify experiment IDs |
| Lineage chain broken | Parent candidate deleted | Cannot recover -- re-run |
