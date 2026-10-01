# Shared Alpha Factory 01

- Ticket: SHARED-ALPHA-FACTORY-01; role: super_developer; change_risk: unclassified.
- Approved base: 41b3f6aa9e5af95f3e851443c43564d61751c2e1.
- One isolated sparse producer; independent architect review and integration required.
- Initial declared scopes clean. No production strategy, Risk, OMS, ledger, credential,
  private/order/live endpoint or existing data/registry writer is in scope.
- Scope: quant_shared/alpha_factory; integrations/qlib_adapter; configs/qlib;
  backend/app/services/alpha_factory.py, backend/app/api/alpha_factory.py and app_factory.py registration;
  frontend/src/workspaces/ResearchPortfolioWorkspace.tsx and research/;
  frontend/src/lib/alpha-factory-api.ts; frontend/e2e/alpha-factory.spec.ts;
  tests/research/test_alpha_factory.py; tests/integrations/test_qlib_alpha_factory.py;
  tests/api/test_alpha_factory.py; this report; append-only ticket handoffs.

## Acceptance contract

One market-independent research campaign drives registered/template/genetic factor
generation, train-only metrics and decorrelation, actual Qlib training, frozen
validation selection, final test audit and automatic exploratory research nomination.
All rejected/failed trials remain visible. Research nomination never changes the
existing promotion contract or grants paper/live permission. Test history already
observed by prior campaigns is not a clean confirmatory holdout.

Market profiles inject data bindings, calendar, labels, costs and metric mode.
BTC uses the existing immutable OKX Qlib exporter. US and future CN/other profiles
must fail closed when a verified input binding is missing, not reuse BTC assumptions.
Existing miners' full-window statistics, zero placeholder turnover and proxy PnL
are not imported as acceptance evidence. Expression/definition reuse is adapter-only.

UI: one Alpha Factory control panel inside the existing research workspace;
profile/capability matrix, budgets, persisted stages, trials/rejections, nominated
candidates and explicit unknown/blocked states. GET/navigation never starts work.

## Governance

Read: AGENTS, knowledge README/non-negotiables, shared/super-developer pitfalls,
data reliability, financial ML validation, backtest evidence, domain architecture;
quant-agent-preflight, quant-agent-handoff, quant-gate-evidence-review skills.
Catalog: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
Active: BACKTEST-COST-001, DATA-US-PIT-001, GOV-CONCURRENCY-001, GOV-DIRTY-001,
GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001,
GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, MONITOR-AUDIT-001,
QSYS-ARTIFACT-001, QSYS-GATE-001, QSYS-SECURITY-001, REPLAY-ISOLATION-001,
RESEARCH-HOLDOUT-001, US-QUEUE-FRESHNESS-001, GOV-PROMPT-001, GOV-WINDOWS-001,
US-SERVICE-BOUNDARY-001. No unrelated historical blocker is a new work ticket.

Safety: promotion=false; paper=false; live=false; private=false; order=false;
real_order=false; transfer=false; withdraw=false. Runtime evidence root bootstrap
is not authorized; any missing strict runtime artifact stays fail-closed.

## Verification

Producer verification (2026-09-10; committed-source review/integration pending):

- Failure-first: generated template timestamps made identical searches differ;
  stripped non-semantic created_at provenance, deterministic regression passed.
- Failure-first: CSV loader converted A-share 000001 to 1. Replaced only factory
  input loading with a typed Parquet DataLoader; three-market actual Qlib fitting passed.
- Failure-first: Windows GET held a state-file read handle during atomic replace;
  bounded sharing-violation retry preserves atomicity. Synthetic regression and
  persistent failure/resume tests passed. Permanent filesystem failures are not ignored.
- Full suite: 148 passed, 2 existing warnings, 181.14s, pytest basetemp suffix 06.
- TypeScript no-emit passed, including final frontend regression addition.
- Vite production build passed (5243 modules, 23.09s); existing bundle-size warning.
- New seven-case frontend regression is prepared for canonical-main execution only;
  no sparse-worktree frontend server was started.
- No real Alpha factory market run, canonical browser acceptance or promotion
  evidence rebuild is claimed in this producer report. Integration receipt will
  record these separately. Prior fixed-feature Qlib run02 is not factory evidence.

Independent source review found and this producer fixed before integration:

- Actual committed-class interleaving reproduced two successful resume writers.
  Claim/reclaim/release now use one OS byte/flock mutex; process death releases
  the guard. Reclamation checks the current owner inside that guard, and release
  compares the exact owner. The concurrent-resume regression accepts one writer
  only and proves stale release cannot delete the winner.
- Initialized request/profile/state/events are durable before owner publication.
  An initialization interruption cannot strand an owner without state. Queue
  rejection becomes persisted failed + event + seal, not perpetual queued.
- Generic daily panels reject frequency-serialized calendar key collisions
  before export, rather than deduplicating bars or silently changing provider data.
- Rendered run facts are gated by exact selected identity; switching to a delayed
  second response hides the previous run's facts immediately.
- No eligible model means rejected with audit_status=not_run_selection_failed;
  audit fit count is zero. Only an eligible frozen champion opens audit. Both
  orchestration paths have regressions. The eligible test fixture was enlarged
  to meet the unchanged effective-sample floor, not by reducing the gate.
- Post-lock fixes full suite: 151 passed, 2 existing warnings, 183.73s (suffix 07).
  The audit-conservation suite initially had 151 passed / 1 fixture failure
  (insufficient samples in the synthetic eligible case); after fixture correction,
  both focused paths passed (2 passed, 29 deselected, 12.60s). Final full suite:
  152 passed, 2 existing warnings, 179.55s (suffix 09), with all source fixes included.
- Final TypeScript no-emit and Vite build passed (5243 modules, 47.42s), with only
  the existing bundle-size warning. No worktree browser server was used.

Architect clarified the existing canonical backend operational profile is
demo_quasi_live (live HTTP identity at baseline HEAD confirms this). Official
restart preserving that profile is permitted for pure research/API/UI acceptance.
It does not satisfy promotion_strict; promotion_artifact_status=unavailable and
btc_runtime_artifact_root_env_missing remain unchanged, no bootstrap authorized.

Final additive recovery check: a failure after state publication but before owner
publication now also seals failed via a separate initialized flag. Lock release
still requires claimed/exact-owner. API/factory/background safety suite passed:
52 passed, 1 existing warning, 48.41s (suffix 10). The temporal sample floor also
counts distinct decision times, not security rows; adding correlated securities
cannot multiply the time-evidence count. It is labeled a conservative overlap
proxy, not a claim of statistical independence.
Final research rerun including the multi-security time-count assertion: 31 passed,
17.85s. No trainer, data exporter or frontend changes followed their passing suites.

Full Python command (producer CWD; canonical .venv interpreter):

```text
python -B -m pytest tests/research/test_alpha_factory.py tests/api/test_alpha_factory.py tests/integrations/test_qlib_alpha_factory.py tests/api/test_qlib_pipeline.py tests/integrations/test_qlib_time_series.py tests/integrations/test_qlib_multi_market.py tests/integrations/test_qlib_adapter_contract.py tests/integrations/test_qlib_to_pypfopt_pipeline.py tests/api/test_background_tasks.py tests/api/test_research_only_boundaries.py -q -p no:cacheprovider --tb=short --basetemp <task-evidence>/alpha-factory-pytest-20260910-06
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
```

## Implemented boundaries

- Shared pure engine: bounded JSON expressions, registered/template/genetic origins,
  train-only IC/Rank IC/block ICIR/signal turnover, train-only decorrelation; all
  evaluated, failed and duplicate proposals retained. No Python expression eval.
- Existing factor definitions and pure BTC expression crossover are reused through
  adapters. Old full-window mining/scoring pipelines are not called. Legacy factor
  names ending in d retain identity but their effective bar unit is explicit metadata.
- Four chronological windows with horizon/delay purge; each model has four real
  expanding Qlib fits. One champion is frozen before its single final audit fit.
  A campaign with no eligible model never opens the audit window.
  No replacement is chosen after viewing audit results. Historical audit cannot
  self-certify freshness via profile configuration.
- Model-family BY FDR uses HAC block Rank IC tests including failed configurations.
  Generated expressions use train data only; their count is separately retained.
  This is exploratory screening, not a proof against repeated campaign selection.
- Signal turnover is measured tanh-factor change; the icir field is explicitly
  displayed as block Rank ICIR (Rank IC mean / standard deviation), not annualized. Cost
  scenarios are forecast-edge diagnostics, not fill-derived performance. PnL,
  DSR and PBO are unknown/not run. No evidence of actual trades is invented.
- Qlib factory trials call the existing run_qlib_workflow / LGBModel / recorder.
  DataHandlerLP + DatasetH use the supported custom DataLoader extension interface:
  https://qlib.readthedocs.io/en/latest/component/data.html .
- Repository owns atomic state, append-only hash-chain events, single-writer locks,
  explicit interruption/resume and immutable linked attempts. Resume reuses exact
  sealed inputs/models; changed HEAD/profile rejects recovery as the same campaign.
  Completed reads revalidate campaign, referenced inputs and all successful trials.
- Factory artifacts: artifacts/alpha_factory_runs/<run_id>/; each input/fold/audit:
  artifacts/qlib_runs/<qlib_run_id>/. No latest writer or old candidate registry writes.
- Existing BTC Portfolio/Risk, OMS, execution and ledger remain the only trading
  authority. Factory strategy configs have automatic_execution_handoff=false.
- Unified console: /research?view=alpha-factory; durable run deep link factoryRun.
  GET/navigation never starts a campaign; explicit bounded POST only. In-progress
  events are partial observations, completed facts require valid seals.

## Real data availability and extension contract

BTC uses existing okx_btc_trend_1h Qlib immutable binding, not a new BTC engine.
The frozen input has 5280 finalized UTC hours; source BTCUSDT, venue/Qlib
BTC-USDT-SWAP. OI/liquidations are absent; funding joins at each decision's
available_time and is excluded as a primitive if train coverage is insufficient.
These are historical observed data with reconstructed availability, not a fresh
confirmation sample or current execution snapshot.

US is intentionally disabled: the existing immutable minute bundle lacks a complete
three-symbol strict daily intersection; the public daily physical bundle is missing,
and point-in-time adjustment remains unproven. CN has no committed shared dataset.
Successful synthetic US/CN Qlib tests prove interface compatibility, not real market
readiness. No partial-session aggregation, fake zeros or placeholder market metrics.

To bind another supported market, publish an immutable shared data version and add
one server-owned profile to configs/qlib/alpha_factory_markets.yaml. No new engine,
HTTP path/config override, BTC code edits or dependencies on BTC execution are needed.
Required profile fields:

```yaml
profile_id: us_equity_daily
label: US verified daily panel
market: us_equity
asset_class: equity
bar_size: 1d
calendar: XNYS
source: <publisher source>
data_mode: immutable_panel
data_version: <exact immutable version>
symbols: [AAPL, MSFT, SPY]
metric_mode: cross_sectional
annualization: 252
label_horizon: 5
entry_delay: 1
cost_scenarios_bps: {base: 10, conservative: 20, stress: 30} # illustrative, not validated costs
data_binding:
  manifest_path: .agent/data_manifests/<dataset>/<version>.json
  manifest_sha256: <Git blob sha256>
  dataset_id: <exact id>
  dataset_version: <same version>
  aggregate_sha256: <published aggregate>
  files:
    panel: {path: panel.parquet, sha256: <sha256>}
    calendar: {path: calendar.parquet, sha256: <sha256>}
    quality: {path: quality.json, sha256: <sha256>}
```

Panel requires string instrument, OHLCV, timezone-aware event_time, available_time
and decision_time; event <= available <= decision for every row. Calendar is the
publisher's complete event_time/decision_time schedule, pinned to exact market/calendar.
Every configured symbol must match every calendar row; gaps, suspensions, delistings
or unavailable bars cannot be silently compressed. Publication must document the
PIT selection policy; this v1 strict complete-panel adapter is not a general suspended-
stock universe engine. Daily and hourly bars are supported; other granularities need
an explicit adapter contract. A-share trading-rule/fee/fill simulation remains outside
factory nomination and requires separate evidence before execution handoff.

Quality JSON must identify market/calendar and attest complete_calendar, pit_universe,
pit_adjustment and available_time_verified=true, backed by the committed publisher
manifest. All three payload hashes and the entire shared manifest are checked.
Optional derivatives/fundamentals are not admitted by this OHLCV-only generic
contract; each needs its own per-decision availability adapter. Leading-zero CN
instruments are preserved. Slashes, reserved filenames and non-finite costs fail closed.

## Rollback and remaining acceptance

Rollback reference is main 41b3f6aa9e5af95f3e851443c43564d61751c2e1. Producer work
does not overwrite main or existing research runs. Independent no-ff integration
must preserve a reviewable integration commit; rollback is a reviewed revert of
that integration, not reset --hard or deletion of artifacts. Historical artifacts
remain labeled with their original code version after any change or rollback.

Pending owner: architect (committed-source review); integrator (source integration,
official backend restart, canonical UI regression, new current-HEAD OKX factory run).
Promotion evidence/read-model remains blocked if btc_runtime_artifact_root_env_missing;
no root bootstrap or existing registry repair is part of this ticket. All promotion,
paper/live/private/order/real-order/transfer/withdraw flags remain false. No unrelated
dirty paths or other agents' uncommitted changes were consumed, merged or reverted.
