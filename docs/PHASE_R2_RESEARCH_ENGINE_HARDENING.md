# Phase R2: Research Engine Hardening

## Overview

Phase R2 hardens the QuantStation research engine by adding experiment manifest reproducibility, candidate lineage tracking, deduplication, robust scoring, walk-forward validation, promotion gate safety, and comprehensive integration tests.

## What Changed from R1

| Area | R1 (Before) | R2 (After) |
|------|-------------|------------|
| Experiment manifest | Basic metadata | Full reproducibility metadata + config hash |
| Candidate tracking | Flat list | Lineage chain with parent-child tracking |
| Deduplication | None | Hash-based duplicate detection |
| Scoring | Simple ranking | Multi-dimension + overfit detector |
| Walk-forward | Manual | Automated fold analysis |
| Promotion gate | Manual checks | Automated gate with 6 checks |
| Integration tests | ~10 tests | 18+ structured tests |
| API endpoints | 2 research endpoints | 10 research endpoints |
| Frontend | 3 tabs | 4 tabs (added compare view) |
| Documentation | 2 research docs | 6 research docs |

## New Files

### Backend

- `backend/tests/test_r2_hardening.py` -- 18 integration tests across 7 test classes

### Frontend

- `frontend/src/workspaces/research/ExperimentCompare.tsx` -- Multi-experiment comparison view
- `frontend/src/lib/research-api.ts` -- Research API client

### Documentation

- `docs/RESEARCH_ENGINE_ARCHITECTURE.md` -- Full component architecture
- `docs/RESEARCH_WORKFLOW_RUNBOOK.md` -- Step-by-step research workflow
- `docs/RESEARCH_API.md` -- API reference with request/response examples
- `docs/PHASE_R2_RESEARCH_ENGINE_HARDENING.md` -- This transition document

## Modified Files

### Backend

- `backend/app/api/app_factory.py` -- Added 4 new research endpoints

### Frontend

- `frontend/src/workspaces/ResearchDashboard.tsx` -- Added "实验对比" tab

### Documentation

- `docs/RUNTIME_SAFETY.md` -- Appended R2 safety section

## New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/research/experiments/{id}/ranking` | Ranked candidates for an experiment |
| POST | `/api/research/experiments/compare` | Compare multiple experiments |
| GET | `/api/research/candidates/{id}/lineage` | Candidate lineage chain |
| POST | `/api/research/candidates/{id}/promotion-gate` | Promotion gate evaluation |

## New Frontend Tab

The ResearchDashboard now has a "实验对比" (Experiment Compare) tab that allows selecting multiple experiments and comparing their candidates side-by-side in a unified data table.

## New Integration Test Classes

| Test Class | Tests | Description |
|------------|-------|-------------|
| TestExperimentManifest | 3 | Reproducibility, config hash, archive |
| TestCandidateLineage | 2 | Parent-child, chain traversal |
| TestCandidateDedup | 2 | Hash detection, duplicate marking |
| TestRobustScoring | 2 | Overfit detector, trade count penalty |
| TestWalkForwardScoring | 2 | Pass rate, min fold check |
| TestResearchPromotionGate | 4 | Missing manifest, overfit, all-pass, no-live |
| TestSafetyInvariants | 2 | No live imports, no broker access |
| **Total** | **17** | |

## Safety Invariants

R2 enforces 10 safety invariants:

1. Research modules cannot submit real orders
2. Research modules cannot access live brokers
3. Automated output stops at paper_review_ready evidence; PAPER_ELIGIBLE is manual
4. Manual action required for all promotions beyond RESEARCH_ONLY
5. Overfit candidates are automatically rejected
6. Lookahead bias is detected and prevented
7. Time-split is enforced in all dataset construction
8. Portfolio construction outputs allocation targets, not orders
9. No research module references QUANT_LIVE environment variable
10. All research tests use tmp_path and fake data -- no real API keys or network calls

## Migration Guide

### For API Clients

The new endpoints are additive -- existing clients are unaffected. To use the new features:

1. **Ranking**: Replace manual sort with `GET /api/research/experiments/{id}/ranking`
2. **Comparison**: Use `POST /api/research/experiments/compare` instead of fetching each experiment separately
3. **Lineage**: Trace candidate history with `GET /api/research/candidates/{id}/lineage`
4. **Promotion Gate**: Replace manual checks with `POST /api/research/candidates/{id}/promotion-gate`

### For Frontend

The new `researchApi` client in `frontend/src/lib/research-api.ts` provides typed wrappers for all research endpoints. Import it directly:

```typescript
import { researchApi } from '../../lib/research-api';

const ranking = await researchApi.getRanking('exp_abc123');
const comparison = await researchApi.compareExperiments(['exp_abc123', 'exp_def456']);
const lineage = await researchApi.getLineage('cand_001');
const gateResult = await researchApi.checkPromotionGate('cand_001');
```

### For Tests

Run R2 tests with:

```bash
pytest backend/tests/test_r2_hardening.py -v
```

## Test Verification

To verify all R2 changes:

```bash
# Backend tests
pytest backend/tests/test_r2_hardening.py -v --tb=short

# Frontend type check (from frontend/)
npx tsc --noEmit

# All integration tests
pytest -m integration -v --tb=short
```

## Rollback Plan

If R2 causes issues:

1. **API only**: Remove the 4 new endpoints from `app_factory.py` (revert the edit)
2. **Frontend only**: Remove the compare tab from `ResearchDashboard.tsx` and delete `ExperimentCompare.tsx` and `research-api.ts`
3. **Tests only**: Delete `backend/tests/test_r2_hardening.py`
4. **Docs only**: Delete the 4 new doc files and revert the RUNTIME_SAFETY.md append

Rollback order: API -> Frontend -> Tests -> Docs.
