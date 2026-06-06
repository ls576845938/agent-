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

- A global registry builder/schema exists, but frontends and research services do
  not yet consume it as the single source of truth.
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

## Phase 2 US Equity Evidence Registry Boundary

- US equity remains `mainline` in the global registry.
- Qlib outputs are normalized to `evidence_candidate` only.
- Qlib / factor / portfolio research artifacts are not paper candidates.
- The only allowed next action for US evidence candidates is
  `internal_event_backtest_required`.
- US data lineage now excludes BTC SQLite manifests from the US equity registry
  node.
- Missing universe manifests, corporate action reports, factor evidence packs,
  portfolio canonical reports, and event-ledger portfolio backtests are reported
  as blockers instead of being silently ignored.
- Paper queue remains `locked`; live remains `frozen`; candidate passed count
  remains `0`.

## Phase 3 US Equity Data Status Contract

- Added a read-only US equity data status builder contract.
- Default generated artifact paths:
  - `artifacts/us_equity_data_status/latest/data_status_report.json`
  - `artifacts/us_equity_data_status/latest/universe_manifest.json`
  - `artifacts/us_equity_data_status/latest/corporate_action_report.json`
- The universe manifest is manifest-derived only; it is not yet a full
  point-in-time constituent history.
- The corporate action report is manifest-derived only; a dedicated split /
  dividend event source remains a blocker.
- Global registry surfaces these artifact paths when they exist, but still keeps
  US equity candidates as evidence-only until internal event-ledger validation.

## Phase 4 US Equity Factor Evidence Pack Contract

- Added a read-only US equity factor evidence pack builder contract.
- Default generated artifact path:
  - `artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json`
- The pack summarizes existing factor-mining artifacts only; it does not mine
  factors, compile new strategies, run backtests, or promote candidates.
- Required evidence now includes rank IC / IC, hit rate, turnover, style
  exposure, capacity proxy, correlation report, cost-adjusted spread, and
  walk-forward stability.
- Missing factor-mining reports, generated-factor registry, correlation
  reports, cost-adjusted spread, walk-forward stability, or portfolio-layer
  validation remain blockers.
- Global registry prefers the factor evidence pack when it exists, but US equity
  factor candidates still remain evidence-only until portfolio and internal
  event-ledger validation pass.

## Phase 5 US Equity Portfolio Canonical Report Contract

- Added a read-only US equity portfolio canonical report builder contract.
- Default generated artifact paths:
  - `artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json`
  - `artifacts/us_equity_portfolio/latest/exposure_report.json`
  - `artifacts/us_equity_portfolio/latest/cost_stress_report.json`
  - `artifacts/us_equity_portfolio/latest/rebalance_drift_report.json`
- The report summarizes existing PyPortfolioOpt adapter run manifests and
  target weights only; it does not optimize weights, submit orders, or run
  portfolio backtests.
- Missing factor evidence pack, target weights, sector/style exposure, cost
  stress, event-ledger portfolio backtest, ledger PnL, walk-forward validation,
  or promotion-gate evidence remain blockers.
- Global registry prefers the portfolio canonical report when it exists, but
  portfolio artifacts remain research-only until event-ledger validation passes.

## Phase 6 BTC Data / Fold / Regime Status Contract

- Added a read-only BTC data status builder contract.
- Default generated artifact path:
  - `artifacts/btc_data_status/latest/btc_data_status_report.json`
- The report summarizes existing BTC candidate validation diagnostics,
  including SQLite interval coverage, manifest lineage, fold contract status,
  regime classifier status, and dragging regimes.
- The fold definition is pinned as `btc_walk_forward_fold_contract_v1`; the
  regime classifier is pinned as `classify_btc_regimes_v1`.
- Missing interval coverage, manifest lineage, fold contract, regime contract,
  fee model, or funding model evidence remain blockers.
- Global registry now surfaces BTC data status as research-sandbox evidence;
  it is not a paper/live approval path.

## Phase 7 BTC Compression-Expansion Attribution Bundle

- Added a read-only BTC compression-expansion attribution bundle builder.
- Default generated artifact paths:
  - `artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json`
  - `artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/fold_failure_report.json`
  - `artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/regime_drag_report.json`
  - `artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/entry_exit_timing_report.json`
  - `artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/active_vs_full_ledger_report.json`
- The bundle only splits and indexes existing event-ledger diagnostics; it does
  not modify strategy logic, create a skeleton, optimize parameters, or unlock
  paper/live.
- Compression-expansion is now explicitly `archived` in the BTC and global
  registries after the full-lifecycle event-ledger failure and Hypothesis Lab
  v2 rejection; `paper_review_pending_allowed = false`.

## Phase 8 Global Registry Read Path

- Added a read-only API endpoint:
  - `GET /api/research/global-registry`
- Added a frontend research API client method and dashboard summary for the
  global registry.
- The endpoint builds the registry from existing artifacts and writes only when
  explicitly called with `write=true`.
- The dashboard now surfaces global US equity evidence paths, portfolio report
  path, BTC data status, and BTC attribution path from the global registry
  instead of inferring those paths locally.

## Phase 9 Local Evidence Validation Commands

- Added local validation Make targets:
  - `make validate-contracts`
  - `make validate-us-equity-evidence`
  - `make validate-btc-evidence`
  - `make validate-candidate-gate`
  - `make build-global-registry`
- Make now defaults to `python3` via `PYTHON ?= python3` so validation works in
  environments without a `python` shim.
