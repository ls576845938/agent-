# BTC Qlib research and seven-layer trace

- Ticket: BTC-QLIB-SEVEN-LAYER-01; producer: super_developer (user main session).
- Base: 96a6aca3dcbec759f2cb5f7b1b87d3155506dfe5.
- Risk: unclassified; independent integration required.
- Source dirty at entry: none in declared scopes; unrelated worktrees are not consumed.
- Scope (user clarified): extend the EXISTING Qlib adapter, task/result API,
  experiment records and frontend to support crypto via market/profile settings.
  No parallel BTC research service, endpoint family, storage system or workbench.
  Add shared seven-layer research trace/results to existing research/portfolio/
  strategy-module pages; this report and append-only ticket handoffs.
- Excluded: BTC production strategy selection, risk/OMS/ledger/exchange semantics,
  private endpoints, secrets, account reads, paper/live/order activation.
- One producer writer; parallel agents are read-only data/architecture reviewers.
- Rollback: preserve base commit; deliver isolated additive changes and revertable
  integration commit, no data migration or overwrite of historical runs.

## Acceptance

1. Immutable committed BTC data binding, UTC completed-bar/PIT checks.
2. Actual Qlib/LightGBM fitting, purged chronological validation/test, no stock
   cross-sectional labels or processors, no synthetic data masquerading as real.
3. Shared research-only seven-layer decision trace with versioned model/data/params,
   cost-aware target, simulated fills/cash/positions and reconciliation.
4. Actual runtime authority remains existing BTC Risk/OMS/ledger. Research
   simulation is never presented as account state; absent runtime evidence is unknown.
5. Frontend distinguishes methodology, candidate configuration and recorded facts;
   no fixed chart or disabled strategy filter is represented as currently active.
6. Safe API, path/hash/identity/error and no-lookahead regressions; real run
   receipt; canonical-main frontend/backend validation after independent integration.

## Safety

promotion=false; paper_or_live=false; private=false; order=false;
real_order=false; transfer=false; withdraw=false.

## Implementation / evidence scope

- Unified pipeline: existing Qlib namespace, server-owned profiles; no BTC-specific research service or storage.
- Main acceptance profile: OKX BTC-USDT-SWAP 1h, 2025-12-22 through 2026-07-29.
  Immutable manifest SHA256: 6c5dd8036da320062002b839792852c1aa53971fecdd20b1ba7ae3ec6c2260c9.
  Funding available from 2026-04-29; all cost evaluation is on the June-July OOS intersection.
- Fixed features and chronological train/valid/test; purged 14-hour label boundary,
  validation-only calibration, single holdout, no hyperparameter search or promotion claim.
- Reuses existing BTC forecast, sizing, risk constitution, portfolio decision and
  cost-intent pure functions. No edits to quant_crypto production modules.
- Cash/positions/PnL are an explicitly separate research simulation. Actual account,
  OMS, fills and production ledger remain unbound/unknown.
- Known assumptions: reconstructed arrival times; assumed spread/slippage/impact;
  funding valuation uses prior available mark; close-based delayed exits are not
  exchange stop orders. Target volatility is NOT applied by the current sizing function.
  Market regime is a causal diagnostic, not a position filter or fitted regime model.
- Frontend: generic trace in research/portfolio/modules; fixed market-state chart
  removed; actual candidate parameters separated; crypto score runs blocked at the
  equity optimizer; Crypto initial private-observation polling removed.
- Model persistence uses Python UTF-8 rather than LightGBM native filename writes
  (reproduced failure on Chinese Windows paths).
- Qlib recorder disables automatic unscoped Git/env/argv harvesting, preserving
  explicit code/config/data lineage and recorder metrics.
- Producer tests are synthetic/local only. No producer artifact may serve as real OKX
  acceptance or be copied into canonical main.

## Touch set

integrations/qlib_adapter/**; integrations/pypfopt_adapter/optimize_weights.py;
configs/qlib/okx_btc_trend_1h.yaml; configs/universe/okx_btc_perpetual_1h.yaml;
backend/app/api/app_factory.py; frontend/src/lib/task-api.ts;
frontend/src/workspaces/{ResearchPortfolioWorkspace,StrategyModulesWorkspace,CryptoWorkspace}.tsx;
frontend/src/workspaces/research-actions.ts; frontend/src/workspaces/research/{QlibDecisionTrace.tsx,qlib-trace.css};
frontend/e2e/{research-portfolio-workflow,qlib-safety}.spec.ts;
tests/api/test_qlib_pipeline.py; tests/integrations/test_qlib_{multi_market,time_series}.py;
this report and ticket handoff envelopes.

## Governance

- Read: knowledge README, non-negotiables, shared/super-developer pitfalls,
  data reliability, financial ML validation, backtest evidence, forecast/portfolio
  and domain architecture rules; preflight/handoff/gate-review skills.
- Catalog: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
- Active: BACKTEST-COST-001, GOV-CONCURRENCY-001, GOV-DIRTY-001,
  GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001,
  GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-BOUNDARY-001,
  QSYS-GATE-001, QSYS-LEDGER-001, QSYS-SECURITY-001, REPLAY-ISOLATION-001,
  RESEARCH-HOLDOUT-001, GOV-PROMPT-001, GOV-WINDOWS-001.
- Main rechecked clean at 96a6aca3 in all touched scopes; all producer changes owned
  by this ticket, no other uncommitted work consumed or overwritten.
- Initial regressions: 2 failures (disabled analysis falsely completed; fixed UI chart).
  Subsequent synthetic integration uncovered Unicode model-file write and delayed
  stale-position intents; both corrected and tested without production execution.
- Environment failures: default pytest temp denied; producer log/dist writes needed
  scoped escalation; quant_cn sparse dependency added read-only for app imports.
- Pending final acceptance: committed-source independent review/integration; canonical
  service restart/identity; actual OKX Qlib run; current-HEAD gate/read-model evidence;
  canonical browser regression and visual verification.

## Producer verification (2026-09-09)

- Python: canonical .venv Python, pytest -q -p no:cacheprovider --tb=short,
  scoped temporary root qlib-pytest-20260909-07. Files:
  tests/integrations/test_qlib_time_series.py, tests/api/test_qlib_pipeline.py,
  tests/integrations/test_qlib_multi_market.py, tests/integrations/test_qlib_adapter_contract.py,
  tests/integrations/test_qlib_to_pypfopt_pipeline.py, tests/api/test_background_tasks.py,
  tests/api/test_research_only_boundaries.py.
  Result: 68 passed, 2 warnings, 48.80 seconds.
  Warnings: installed Starlette/httpx deprecation; pre-existing runpy import warning.
- node node_modules/typescript/bin/tsc --noEmit: passed.
- node node_modules/vite/bin/vite.js build --emptyOutDir false: passed; 5240 modules,
  23.91 seconds. Existing large-bundle warning remains; no producer server started.
- Synthetic actual Qlib/LightGBM fit/predict is tested; explicitly synthetic calibrated
  signals exercise non-flat research fills and independent cash/position/PnL replay.
  This is NOT a real OKX run and NOT a model-quality or promotion acceptance.
- Current-HEAD BTC gate rebuild remains not_run pending integration and an existing
  compliant external runtime artifact root. If root is absent, preserve
  btc_runtime_artifact_root_env_missing / unavailable_fail_closed; do not bootstrap it.

## Independent review correction

- The review reproduced a blocked daily-loss assessment with a valid existing BTC
  reduce-only plan. The initial research replay ignored that plan and prevented exit.
- Failure-first synthetic stress test left 0.195095865468846 BTC unclosed.
- Research replay now consumes the existing plan only after strict decision/position/
  forecast/target binding and reduce-only checks. A capped target is reassessed.
  Pending research intents are superseded locally; actual OMS permission stays false.
- Completion additionally requires flat final position, no pending research intents
  and a filled terminal exit when a position existed. No production domain code changed.
- The supported forward-open label expression must exactly match declared positive
  horizon/delay offsets. Arbitrary label expressions are rejected, not guessed.
- Raw score and frozen-validation-calibrated, clipped test metrics are recorded
  separately; neither test metric feeds contemporaneous sizing or config selection.
- API Qlib evidence root is server-owned; noncanonical roots are rejected. Unsealed
  or corrupt runs return only minimal identity/unknown status/integrity blockers/safety.
  All returned evidence files are sealed; appended unsealed facts also fail closed.
- Committed dataset aggregate digest is checked and recorded through trace identity.
  Forecast quality path/hash now binds the full evaluation file; calibration retains
  its independent nested-object hash.
- Sizing is explicitly an unlevered exposure proposal, not production perpetual
  sizing readiness. Historical risk uses simulated reference-price assumptions;
  actual account, margin and liquidation observations remain unknown.
- Candidate identity comes from the actual candidate manifest, not the run ID.
  Alpha/diagnostic are research_derived; risk/portfolio/exit/fill/ledger are
  research_simulated. No derived or simulated facts are called runtime observations.
- Final producer regression after all review corrections: same seven-file pytest
  command above, qlib-pytest-20260909-11, 72 passed / 2 existing warnings / 75.25s.
  Both normal and forced-loss synthetic Qlib replays finish flat with reconciled
  ledgers; root escape, corrupt/unsealed facts, aggregate, label and candidate
  mismatches are covered. Final tsc --noEmit passed.
- Strict backend evidence acceptance remains blocked by missing pre-existing BTC
  runtime artifact root. Restoring the user's already-running demo_quasi_live
  service for research API smoke does not satisfy strict promotion acceptance.
- P1 temporal follow-up: final-flat alone missed repeated exits canceling and
  rescheduling the earliest reduction. A persistent one-bar maximum-hold stress
  failed first. Compatible equal-or-stronger pending reductions now retain their
  original deadline; later decisions reference that intent. Only incompatible
  pending proposals are superseded. Test asserts the first planned reduction
  fills at the configured delayed open, not merely at the end of the sample.
- Final temporal correction regression: same seven-file suite, temporary root
  qlib-pytest-20260909-14: 72 passed, 2 existing warnings, 72.27 seconds.
- Canonical acceptance at main 3cbd49bad99e found a deploy-only missing sparse
  integrations directory (GET listing 500). Materializing committed source restored
  HTTP 200 without business-code changes. Existing registry 409 does not disable
  the independent Qlib profile/pipeline after initial loading; its guard is unchanged.
- Failure-first canonical browser regression proved OKX selection remounted the
  workspace and submitted us_equity_daily. Same-ticket correction carries only a
  profile ID via router state, restoring configuration exclusively from the server
  whitelist; no old run, arbitrary path or permission is carried. Invalid profile
  remains unverified and the unified action is disabled.
- Qlib tab now has a separate read-only context: verified selected-run identity
  takes priority; bad seal/unknown identity never falls back to AAPL. New draft
  context displays the server profile. The remaining daily-only label is corrected
  and both Qlib artifact-root inputs are read-only. Backend and all trading guards
  are unchanged. Expanded browser checks cover remount/reload, context/seal boundary,
  immutable root and absence of automatic/private/order writes; canonical rerun is
  assigned to the independent integrator after committed-source approval.
- Producer `node node_modules/typescript/bin/tsc --noEmit` and scoped
  `git diff --check` passed after the navigation/context correction. No Python
  source changed since the independently repeated 72-test passing suite.
- Canonical full frontend regression at 0e2db0b7: 43 passed (2.5 minutes).
  Real run qlib_okx_btc_1h_20260909_integration01 / task
  ba4d1bbe11e14f7fa1e71b594c1a4ffd failed at dataset identity validation;
  training and all downstream stages were not_run. Its sealed failure remains
  immutable. Raw payload symbol BTCUSDT was incorrectly compared directly with
  the venue/Qlib instrument BTC-USDT-SWAP; all real confirms were 1.
- Same-ticket identity correction verifies immutable exchange_info.json hash,
  source symbol, venue instrument and SWAP/linear/USDT metadata. Each row must
  match its exact kind-specific source_record_id and UTC event milliseconds;
  funding additionally requires matching instId. Only validated copies are mapped,
  retaining source_symbol and source_record_id. Manifest records source_symbol,
  venue_instrument_id and qlib_instrument separately. No source data/hash, UTC,
  finality, price, training or production execution contract is weakened.
- Failure-first evidence is the retained real run01. Added regressions cover
  success/lineage, spot or mixed contracts, wrong prefix/event/raw symbol, missing
  identity, unfinalized input, incompatible contract metadata and hash/path escape.
  Same seven-file Python suite with qlib-pytest-20260909-15: 92 passed, two existing
  warnings, 60.09 seconds. Frontend code and its passing 43 tests are unchanged.
- Real immutable-input export-only smoke (no training) passed under the producer
  correction: 5280 requested UTC hourly rows, 276 funding events; all original
  immutable files and metadata hashes verified. The input manifest records the
  full three-identity mapping. Temporary smoke artifact:
  C:/Users/李烁18353780778/.codex/visualizations/2026/09/08/01a080f1-4630-7253-bcda-f37ffa68c539/qlib-okx-identity-smoke-20260909/okx-identity-smoke/qlib_input/dataset_manifest.json.
  This is dataset-adapter evidence, not training/promotion evidence. Independent
  committed-source integration and a new real run02 remain required.
- The sealed failed run01 also exposed a read-model identity bug: with no dataset
  yet, summary incorrectly defaulted to equity/1d although its own pipeline receipt
  explicitly recorded crypto/1h. The two summary fields now use sealed pipeline
  identity as fallback (otherwise unknown), with a dedicated API regression.
  No task execution, permissions or downstream trading behavior changed.
- After the two-field failed-summary correction, the same seven-file suite with
  qlib-pytest-20260909-16 passed: 93 tests, two existing warnings, 45.41 seconds.
- Final API-only rerun including the no-pipeline unknown identity case:
  qlib-pytest-20260909-17, 10 passed, one existing warning, 8.09 seconds.
