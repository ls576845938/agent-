# Research workbench refactor — independent integration

- Ticket: `RESEARCH-WORKBENCH-REFACTOR-01-INTEGRATION-01`
- Role: short-lived `integrator`; change risk: `unclassified`
- Approved main base: `bbc39bec1449c5ea6947c200be1541988d34db2c`
- Approved producer source: `85f669ccd58d9b2a313796748c6db08495a9056b`
- Test-only correction: `2b3ca63e08aedbd0cd21912a4f8279d1c34c81b4`
- Canonical acceptance candidate: `09675ec2a54d7c136a00711e73c104f4fee936f5`
- Worktree: planner-created sibling `integrator-research-workbench-refactor-01-integration-01`, sparse checkout enabled.

## Ownership and touch set

The producer owns the nine paths declared by the published handoff: the research dashboard selector, the preserved legacy dashboard, the new workbench/navigation and local CSS, two research E2E files, the exact-rollback test, the research-only verification runner, and the producer report. The correction changes only `frontend/e2e/research-workbench.spec.ts`; application source is unchanged.

The integrator additionally owns only `frontend/public/frontend-identity.json`, this report, and the append-only integration handoff. No backend, shared schema, strategy, risk, OMS, ledger, broker, paper/live permission, shared CSS, or other strategy page was edited.

Initial scoped dirty paths were empty in canonical main, producer, and integrator worktrees. From producer base `4096453b...` to approved main `bbc39bec...`, none of the nine source paths changed. Producer worktree files and both handoff files were clean; their worktree blob IDs matched the committed objects. Sparse checkout reported pre-existing out-of-cone artifact/data paths when main advanced; they were left untouched and were not treated as deliverables.

## Governance and input validation

Read: `quant-agent-preflight`, `quant-agent-handoff`, `AGENTS.md`, knowledge README and non-negotiables, shared pitfalls, integrator profile, and delivery risk policy. No integrator-specific pitfall markdown exists.

Catalog hash: `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`.

Selected IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.

The published envelopes `published-research-workbench-refactor-01-85f669ccd` and `published-research-workbench-refactor-01-2b3ca63e0` both passed `handoff.py validate`. Producer ancestry, base ancestry, nine deliverable SHA-256 values, report/test evidence, blocker inventory, and `promotion_eligible=false` were independently checked before each merge. The source and correction were merged with `--no-ff`; canonical main was only advanced after scoped dirty checks.

## Validation results

- `node node_modules/typescript/bin/tsc --noEmit`: passed.
- `npm.cmd run build`: passed, 5,227 modules in 52.08 seconds. The pre-existing large-bundle warning remains (1,620.31 kB JavaScript, 466.14 kB gzip).
- `node frontend/scripts/test-research-rollback.mjs`: passed against exact baseline `4096453b...`.
- `git diff --check` on the nine source paths: passed.
- First canonical Playwright run on `87e737b...`: failed, 8 passed / 2 failed in 1.0 minute. The accessibility snapshot contained the correct `params JSON` textbox and value; the failures were an unstable label locator and English assertions against intentionally localized Chinese status pills. Evidence: `canonical-e2e-first-run-failure.json`, SHA-256 `5015dac03d210f8b2e5fe13bdb1fedc936c67c4a42d3cfe4cac0d6d147be1b31`.
- Producer correction `2b3ca63e...`: four test assertion/locator lines only; the two failure-first cases passed independently in 6.4 seconds.
- Corrected canonical Playwright run on `09675ec2...`: **10 passed / 0 failed in 33.4 seconds**. These are mocked UI contracts and do not prove training, backtest, or promotion success.
- Independent in-app-browser acceptance on `09675ec2...` confirmed the new four-stage page, all three dependencies shown as installed, legacy seven-view rollback and return to the new page. At the calibrated compact viewport, `scrollWidth=innerWidth=1130` with no overlap or horizontal overflow. Screenshots: `C:/Users/LOCAL_USER/.codex/visualizations/2026/09/08/01a080f1-4630-7253-bcda-f37ffa68c539/research-refactor/04-after-final.png` and `05-after-final-compact.png`.
- `GET /api/health`: `status=ok`, default source `yfinance`.
- `GET /api/integrations/qlib/runs`: `qlib=true`, `lightgbm=true`, zero registered runs.
- `GET /api/integrations/portfolio/runs`: `pypfopt=true`, zero registered runs.
- Canonical identity on `09675ec2...`: backend `canonical=true`, `runtime_stale=false`, profile `demo_quasi_live`; frontend fingerprint `36ba885d3311b2803caf22ccd659b53fc57e96db11fc84a1bd9f7024d411ae06`.
- The real evidence-registry read was not green: the current independent read returned HTTP 500; an earlier independent UI read returned HTTP 409 and legacy showed `CONFLICT`. No rebuild or data write was triggered.

Candidate acceptance receipt: `D:/vibe coding/Obsidian/量化系统/research-verification/research-workbench-refactor-01/integration-acceptance-09675ec2.json`, SHA-256 `b8646b614a7a1e9465e5fca326fe4c94925fe999ff90713950c05ec0ee7a1417`.

## Runtime and dependency boundary

Canonical services were started only through `start-backend.cmd` and `start-frontend.cmd`. The strategy-history root was preserved as `D:/vibe coding/Obsidian/量化系统/runtime-artifacts/strategy-alpha-parameter-map-01-20260908`. Backend process environment retained `demo_quasi_live`, fixture fallback false, demo control true, and the task-owned ASCII `JOBLIB_TEMP_FOLDER=D:/quantstation-research-qa-temp-20260908`. The latter is process-local; future restarts must preserve it until a separately authorized launcher change exists.

The canonical environment recognizes `pyqlib 0.9.7`, `lightgbm 4.7.0`, and `PyPortfolioOpt 1.6.0`. `pip check`, imports, a 40-row LightGBM fit, and a three-asset optimizer smoke passed. Only pre-existing `protobuf 7.35.1` changed to `6.33.6`; all other prior packages were retained. Before/after evidence is under the external verification root (`environment-before.json` SHA-256 `bbebe217...`; `environment-after.json` SHA-256 `6cb33cc8...`). Package smoke is not research evidence.

## Gate decision and unresolved blockers

UI acceptance is passed and the visual rollback remains immediate at `/research?layout=legacy`; return to the new page at `/research`. The backup branch `codex/research-before-20260908` remains anchored to `4096453b...`. A permanent rollback must be a scoped revert, never a reset of main.

The full research workflow is **not passed**. Historical Qlib provider construction, LightGBM training, and metric import completed, but predictions were constant, Rank IC was NaN, native portfolio analysis failed at the final calendar index, the portfolio step used a fallback optimizer, pending order intents remained 3, and walk-forward produced no windows. Factor date/time-key and regime-parameter contract blockers remain in existing backend code. The seven research regression suites remain 72 passed / 2 failed on Windows path-separator assertions; both underlying decisions stayed BLOCKED. No backend repair, model retuning, evidence-registry rebuild, promotion artifact rebuild, or large training rerun was authorized or performed.

`unclassified` policy requires a fresh promotion artifact before any future promotion claim. This UI-only ticket has `gate_impact=none`, so no promotion artifact was rebuilt and `promotion_artifact_status=unavailable` remains explicit. Promotion, paper, live, private, order, real-order, transfer, and withdraw permissions all remain false. No private, broker, order, or live endpoint was called.
