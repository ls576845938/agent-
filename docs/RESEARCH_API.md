# Research API Reference

## Overview

The Research API provides programmatic access to experiment management, candidate scoring, ranking, comparison, lineage tracking, and promotion gates. All endpoints are under the `/api/research/` prefix.

## Authentication

All endpoints require `X-API-Key` header (unless `web_api_key` is not configured in settings).

```
X-API-Key: your-api-key
```

## Endpoints

### List Experiments

```
GET /api/research/experiments
```

Returns all experiments from the research lab.

**Response (200):**
```json
[
  {
    "experiment_id": "exp_abc123",
    "strategy_id": "trend_momentum",
    "strategy_family": "trend",
    "symbols": ["AAPL", "MSFT", "GOOGL"],
    "status": "COMPLETED",
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
    "created_at": "2025-06-01T12:00:00Z"
  }
]
```

---

### Get Experiment

```
GET /api/research/experiments/{experiment_id}
```

Returns a single experiment's details including manifest.

**Response (200):**
```json
{
  "experiment_id": "exp_abc123",
  "strategy_id": "trend_momentum",
  "strategy_version": "1.0.0",
  "params": {"lookback": 20, "entry_zscore": 2.0},
  "metrics": {"sharpe": 1.5, "cagr": 0.12},
  "status": "COMPLETED",
  "config_hash": "a1b2c3d4e5f6..."
}
```

---

### Get Experiment Ranking

```
GET /api/research/experiments/{experiment_id}/ranking
```

Returns ranked candidates for a specific experiment, sorted by composite score (descending).

**Response (200):**
```json
[
  {
    "candidate_id": "cand_001",
    "experiment_id": "exp_abc123",
    "strategy_id": "trend_momentum",
    "score": 0.85,
    "sharpe": 1.8,
    "max_drawdown": -0.15,
    "robustness_score": 0.9,
    "overfit_score": 0.05,
    "alpha_score": 0.75,
    "risk_score": 0.15,
    "turnover_score": 0.25,
    "rank": 1,
    "promotion_status": "CANDIDATE"
  },
  {
    "candidate_id": "cand_002",
    "score": 0.72,
    "rank": 2,
    ...
  }
]
```

---

### Compare Experiments

```
POST /api/research/experiments/compare
```

Compares multiple experiments side-by-side on a specified metric.

**Request Body:**
```json
{
  "experiment_ids": ["exp_abc123", "exp_def456"],
  "metric": "sharpe"
}
```

**Response (200):**
```json
{
  "exp_abc123": [
    {"candidate_id": "cand_001", "sharpe": 1.8, "score": 0.85, "strategy_id": "trend_momentum"},
    {"candidate_id": "cand_002", "sharpe": 1.5, "score": 0.72, "strategy_id": "trend_momentum"}
  ],
  "exp_def456": [
    {"candidate_id": "cand_003", "sharpe": 2.1, "score": 0.91, "strategy_id": "mean_reversion"},
    {"candidate_id": "cand_004", "sharpe": 1.2, "score": 0.55, "strategy_id": "mean_reversion"}
  ]
}
```

---

### List Candidates

```
GET /api/research/candidates
```

Returns all strategy candidates across all experiments.

**Response (200):**
```json
[
  {
    "candidate_id": "cand_001",
    "experiment_id": "exp_abc123",
    "strategy_id": "trend_momentum",
    "promotion_status": "CANDIDATE",
    "score": 0.85,
    "sharpe": 1.8,
    "robustness_score": 0.9,
    "overfit_score": 0.05,
    "alpha_score": 0.75,
    "risk_score": 0.15,
    "turnover_score": 0.25,
    "created_at": "2025-06-01T12:00:00Z"
  }
]
```

---

### Get Candidate Lineage

```
GET /api/research/candidates/{candidate_id}/lineage
```

Returns the full lineage chain for a candidate, from the candidate back to the root ancestor.

**Response (200):**
```json
[
  {
    "candidate_id": "cand_003",
    "experiment_id": "exp_003",
    "strategy_id": "momentum_v2",
    "params_hash": "ghi789",
    "promotion_status": "CANDIDATE",
    "parents": ["cand_002"]
  },
  {
    "candidate_id": "cand_002",
    "experiment_id": "exp_002",
    "strategy_id": "momentum_v1",
    "params_hash": "def456",
    "promotion_status": "CANDIDATE",
    "parents": ["cand_001"]
  },
  {
    "candidate_id": "cand_001",
    "experiment_id": "exp_001",
    "strategy_id": "momentum",
    "params_hash": "abc123",
    "promotion_status": "CANDIDATE",
    "parents": []
  }
]
```

**Note:** The response is ordered from newest to oldest (child-first). The last entry in the array is the root candidate (no parents).

---

### Check Promotion Gate

```
POST /api/research/candidates/{candidate_id}/promotion-gate
```

Evaluates a candidate through the Research Promotion Gate to determine if it's ready for promotion.

**Response (200) - PASS:**
```json
{
  "candidate_id": "cand_001",
  "gate_status": "PASS",
  "decision": "PROMOTE_TO_REVIEW",
  "next_stage": "PAPER_ELIGIBLE",
  "checks": {
    "manifest_exists": true,
    "not_overfit": true,
    "sharpe_above_threshold": true,
    "trade_count_sufficient": true,
    "cost_stress_passes": true,
    "walk_forward_passes": true
  }
}
```

**Response (200) - BLOCKED:**
```json
{
  "candidate_id": "cand_overfit",
  "gate_status": "BLOCKED",
  "decision": "REJECT",
  "next_stage": null,
  "reason": "Overfit detected: OOS degradation 55%",
  "checks": {
    "manifest_exists": true,
    "not_overfit": false,
    "sharpe_above_threshold": true,
    "trade_count_sufficient": true
  }
}
```

---

### Run Experiment

```
POST /api/research/experiments/{experiment_id}/run
```

Runs the backtest for a specific experiment.

**Response (200):**
```json
{
  "status": "completed",
  "experiment_id": "exp_abc123",
  "candidates_generated": 12
}
```

---

### Score Experiment

```
POST /api/research/experiments/{experiment_id}/score
```

Scores all candidates from a completed experiment.

**Response (200):**
```json
{
  "status": "completed",
  "experiment_id": "exp_abc123",
  "candidates_scored": 12,
  "overfit_detected": 2,
  "clean_candidates": 10
}
```

---

### Generate Candidates

```
POST /api/research/experiments/generate
```

Generates candidates from a configuration. This creates experiments and runs the full pipeline.

**Request Body:**
```json
{
  "experiment_name": "momentum_research_v3",
  "strategy_id": "trend_momentum",
  "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN"],
  "params": {"lookback": 20, "entry_zscore": 2.0},
  "param_grid": {
    "lookback": [10, 20, 40, 60],
    "entry_zscore": [1.5, 2.0, 2.5]
  },
  "start_date": "2020-01-01",
  "end_date": "2024-12-31",
  "data_version": "v2",
  "feature_version": "v1"
}
```

**Response (200):**
```json
{
  "pipeline_id": "pl_abc123",
  "status": "completed",
  "experiment_ids": ["exp_abc123"],
  "candidate_ids": ["cand_001", "cand_002", "cand_003"],
  "promoted": ["cand_001"]
}
```

---

### Get Experiment Report

```
GET /api/research/experiments/{experiment_id}/report
```

Downloads the experiment report (PDF or JSON format).

**Response (200):** Binary report file or JSON report data depending on Accept header.

## Error Responses

All endpoints return standard HTTP errors:

**400 Bad Request:**
```json
{
  "detail": "Invalid experiment ID format"
}
```

**404 Not Found:**
```json
{
  "detail": "Experiment exp_nonexistent not found"
}
```

**403 Forbidden (bad API key):**
```json
{
  "detail": "Invalid API key"
}
```

## Rate Limiting

No built-in rate limiting. Clients should implement exponential backoff on 429 or 5xx responses.

## SDK Usage

All API endpoints are available through the Python SDK:

```python
from quant_us.research.lab.manifest import ExperimentManager
from quant_us.research.automation.scorer import CandidateScorer
from quant_us.research.automation.promotion_gate import ResearchPromotionGate

# List experiments
mgr = ExperimentManager()
experiments = mgr.list_experiments()

# Score and rank
scorer = CandidateScorer()
scores = scorer.score("exp_abc123")
ranked = scorer.rank(scores)

# Promotion gate
gate = ResearchPromotionGate()
result = gate.evaluate("cand_001")
```
