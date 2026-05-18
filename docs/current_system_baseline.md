# QuantStation VNEXT Current System Baseline

Generated from Phase 0 read-only audit. This document is a planning baseline,
not a trading authorization.

## Repository State

- Branch: `main`
- Baseline commit: `dc34e1a`
- Known unrelated dirty file at audit time:
  `docs/reports/quantstation_vnext_global_status_and_roadmap_20260518.html`
- Paper queue: `locked`
- Live: `frozen`
- `candidate_passed_internal_gate`: `0`

## Asset Line Positioning

- US equity is the mainline asset path.
- BTC is a research sandbox for high-pressure evidence gates.
- Paper/live runtime work remains frozen until evidence gates pass.

## Real Paths

### US Equity

- Data: `quant_us/data/`
- US equity ingestion: `quant_us/data/connectors/us_equity_ingestion.py`
- Data manifest: `quant_us/data/storage/data_manifest.py`
- Universe: `quant_us/data/universe/`
- Factors: `quant_us/factors/`
- Strategies: `quant_us/strategies/`
- Portfolio: `quant_us/portfolio/`
- Portfolio construction: `quant_us/portfolio/construction/`
- Portfolio configs: `configs/portfolio/`
- Qlib adapter: `integrations/qlib_adapter/`
- PyPortfolioOpt adapter: `integrations/pypfopt_adapter/`
- Backtest/ledger: `quant_us/backtest/unified_runner.py`,
  `quant_us/backtest/ledger_pnl.py`

### BTC

- BTC research modules: `quant_us/research/btc_*.py`
- BTC configs: `configs/btc/`
- BTC registry: `artifacts/btc_research_registry/research_registry.json`
- Range reclaim lifecycle report:
  `artifacts/btc_hypothesis/20260518T010000Z_range_reclaim_lifecycle/range_reclaim_lifecycle_report.json`
- Compression-expansion event-ledger report:
  `artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger/canonical_backtest_report.json`

### Risk, Promotion, Paper, Live

- Main promotion authority: `quant_us/research/automation/promotion_gate.py`
- BTC internal canonical gate: `quant_us/research/btc_canonical.py`
- Legacy/API research assessment: `backend/app/services/research_gate.py`
- Risk modules: `quant_us/risk/`
- Kill switch: `quant_us/risk/kill_switch.py`
- Paper/live modules: `quant_us/live/`
- Execution modules: `quant_us/execution/`

## Existing Protection

- `ResearchPromotionGate` requires event-driven, canonical, fills, ledger
  reconciliation, and risk metadata before `READY_FOR_PAPER_REVIEW`.
- BTC canonical gate requires `canonical_event_ledger`, event-ledger status,
  event profit factor, and signal-equity diagnostic-only status.
- `LiveRuntimeConfig.real_order_submission_enabled` is fail-closed.
- Live submission remains review-only/frozen.

## Known Gaps

- No single global registry source of truth exists yet.
- `tests/contracts/` did not exist at audit time.
- BTC registry and `data/research/evidence_registry.json` are separate systems.
- Frontend reads status from multiple APIs, not one global registry.
- HTML reports in `docs/reports/` and `reports/` are not indexed by a registry.
- Multiple gate names can be confused:
  - `ResearchPromotionGate`
  - BTC canonical gate
  - legacy service research gate
  - paper review gate
  - live readiness gate
- `backend/app/services/research_gate.py` can surface `paper_candidate` language
  from service-layer assessment and must not be treated as promotion authority.

## Phase 0/1 Guardrails

- Do not modify strategy logic.
- Do not create alpha skeletons.
- Do not run long backtests.
- Do not touch paper/live execution logic.
- Qlib and PyPortfolioOpt remain research inputs/adapters only.
- Signal equity, target-active return, and plain PF remain diagnostics only.
- Global registry artifacts are read-only summaries, not trading approval.
