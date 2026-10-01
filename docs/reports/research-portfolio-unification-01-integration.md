# Research / portfolio unification — independent integration

- Ticket: `RESEARCH-PORTFOLIO-UNIFICATION-01-INTEGRATION-01`
- Role: short-lived `integrator`; change risk: `unclassified`; gate impact: `none`
- Approved base: `13486a7802628e93dd624213ba6c317c5deb4ddf`
- Final approved producer source: `3a799a0aadb48d0b508e42447d7c0ef95c85e52a`
- Current application acceptance commit: `97e948b8432a044e5259e37f1ee492bb0486eeae`
- Worktree: planner-created sibling `integrator-research-portfolio-unification-01-integration-01`, sparse checkout enabled.

## Outcome and ownership boundary

The new research, portfolio and research-review surfaces, the two saved rollback generations, and the evidence-registry read-only GET closure passed independent integration. `GET /api/research/evidence-registry?data_root=data&rebuild=false` now returns a structured HTTP 409 `CONFLICT` for the current unreadable evidence instead of an unstructured 500, and it does not rebuild or repair evidence. This is correct fail-closed disclosure, not a data-quality pass.

Producer ownership is the 22 paths in the final published envelope: 15 application source files, three E2E files, one static contract, the producer report, `backend/app/api/app_factory.py`, and `backend/tests/test_research_registry_readonly_api.py`. The backend change is limited to the research evidence-registry public read-only GET and its regression tests; POST behavior, schemas outside this handler, strategy, risk, OMS, ledger, broker, private/order/live permissions and promotion behavior were not changed.

Integrator-only additions are `frontend/public/frontend-identity.json`, this report and the append-only integration handoff. No producer-owned source or test was edited by the integrator. Initial scoped dirty paths were empty in canonical main, producer and integrator worktrees. All approved source/handoff paths were committed and clean before consumption. The sequential `--no-ff` merges had no conflicts. Git reported pre-existing out-of-sparse-cone runtime/data paths while main advanced; they were preserved without scan, cleanup, reset or modification and are not deliverables.

## Governance and input validation

Read: `quant-agent-preflight`, `quant-agent-handoff`, `AGENTS.md`, the knowledge README, quant non-negotiables, shared pitfalls, integrator profile and delivery risk policy. No integrator-specific pitfall markdown exists.

Catalog SHA-256: `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`.

Active IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.

The superseding producer events ending in `64a3cdef7`, `a36fba0cd`, `686a83406`, `a4678952d` and `3a799a0aa` each passed `handoff.py validate` before consumption. Base/source/handoff ancestry, current main, producer branch, scoped dirty state, blocker inventory, `promotion_eligible=false`, guardrails and all 22 deliverable SHA-256 values were independently verified. The final two corrections changed tests only; `frontend/src` and `backend` objects remained identical to the already validated application/backend source. A transient Team Context `cat-file` timeout was independently retried by the main session and current ticket discovery succeeded. Fourteen unrelated invalid historical handoffs were not repaired or expanded into this ticket.

## Validation results

- Backend: canonical `.venv` ran `python -m pytest -q backend/tests/test_research_registry_readonly_api.py tests/api/test_research_only_boundaries.py`; **15 passed**, one deprecation warning, 33.04 seconds.
- Static contract: first attempt in the fresh sparse tree failed with `MODULE_NOT_FOUND: typescript` because the tree had no dependency directory. After an absolute directory junction from the integration worktree `frontend/node_modules` to canonical `frontend/node_modules`, the unchanged command passed. No package was installed or changed.
- `node scripts/test-research-portfolio-contract.mjs`: passed; no network calls.
- `node scripts/test-research-rollback.mjs`: passed against frozen baseline `4096453b344e777e99f4272b43582d60cf1251f9`.
- `node node_modules/typescript/bin/tsc --noEmit`: passed.
- `node node_modules/vite/bin/vite.js build`: passed, 5,238 modules in 50.62 seconds. The existing >500 kB bundle warning remains.
- First canonical Playwright run on `7fd07dde2...`: **32 passed / 6 failed** in 5.8 minutes. All six failure contexts were preserved before Playwright cleanup at `D:/vibe coding/Obsidian/量化系统/research-verification/research-portfolio-unification-01/integration-evidence/playwright-first-32pass-6fail/`; `.last-run.json` SHA-256 `9d78f79407123f3d93108e8ccd65f29690dbed28b8659f969a25828f6503ffb7`.
- First corrected six-case rerun on `2a64237f...`: **5 passed / 1 failed** in 1.1 minutes; the remaining cross-document load race was preserved at `.../integration-evidence/playwright-targeted-5pass-1fail/`; `.last-run.json` SHA-256 `0ccd7540f652d18a183c0310fd53901b1bd61f50e8c038cbcc0485fc96cd8369`.
- Final two-case keyboard/rollback rerun on `97e948b84...`: **2 passed** in 54.6 seconds.
- Final required command on canonical `97e948b84...`: `node node_modules/@playwright/test/cli.js test e2e/research-portfolio-workflow.spec.ts e2e/research-workbench.spec.ts e2e/research.spec.ts --workers=1`; **38 passed / 0 failed** in 4.6 minutes. The 28 new workflow tests and 10 saved/legacy tests mock all API POSTs; this validates UI contracts and explicitly proves no POST escaped the mocks, but does not prove a real training, portfolio, review or promotion workflow. Final `.last-run.json` is under `.../integration-evidence/playwright-final-38pass/`, SHA-256 `91d1c43004802cd49950d78eb11c8fa7d05da8ffffe219a8b13b2f561bc00903`.

## Visual and public-read acceptance

Read-only Playwright visual QA covered `/research`, `/portfolio`, `/live?view=research-review`, `/research?layout=previous`, `/portfolio?layout=legacy`, and 820 px research/portfolio views. All seven pages reached ready state, `loading=false`, had no page exception, no blocked/non-GET request and no main-document horizontal overflow. The research, portfolio and review surfaces displayed the expected evidence conflict and kept paper/live locked. The shared legacy top bar remains crowded at 820 px; this pre-existing shared-shell issue is not claimed as mobile-perfect and was not expanded into this ticket.

Screenshots and machine summary: `D:/vibe coding/Obsidian/量化系统/research-verification/research-portfolio-unification-01/integration-visual-final/`. The expected console errors are only HTTP 409 responses from the evidence-registry GET; the legacy portfolio rollback had no console error. Independent main-session review confirmed the research/portfolio/review layout, rollback entrances, locks and lack of main-content horizontal overflow.

Current public GET observations on the acceptance application commit:

- `/api/health`: HTTP 200, `status=ok`, default source `yfinance`.
- `/__backend_identity`: canonical true, runtime stale false, profile `demo_quasi_live`; paper/live/broker-or-order false.
- `/api/integrations/qlib/runs`: HTTP 200, qlib/lightgbm true, `runs=[]`, research-only and live disabled.
- `/api/integrations/portfolio/runs`: HTTP 200, pypfopt true, `runs=[]`, research-only and live disabled.
- `/api/research/evidence-registry?data_root=data&rebuild=false`: HTTP 409, code `research_evidence_unreadable`, registry `CONFLICT`, read-only true and promotion eligible false.
- `/api/system/overview?data_root=data`: HTTP 200 but business status `blocked`, stage `paper_validation_blocked`, data coverage `MISSING` and paper validation `BLOCKED`.
- `/api/research/paper-review/entry-state?data_root=data`: HTTP 200 but status `CONFLICT`, `entry_allowed=false`.
- `/api/research/global-registry`: HTTP 200, paper queue locked and live frozen.

The UI once reported system overview and review entry among concurrent read failures even though direct isolated GETs returned HTTP 200 with blocked/conflict business states. This is recorded as an observed concurrent-read timeout distinction, not changed into new code scope.

## Runtime, rollback and unresolved gates

Canonical services were only started through root `start-backend.cmd` and `start-frontend.cmd`, with process-local `QS_BACKEND_EVIDENCE_PROFILE=demo_quasi_live`, `QS_ALLOW_FIXTURE_FALLBACK=false`, `QS_BTC_DEMO_CONTROL_ENABLED=true`, `JOBLIB_TEMP_FOLDER=D:/quantstation-research-qa-temp-20260908`, and `QS_BTC_STRATEGY_HISTORY_ARTIFACT_ROOT=D:/vibe coding/Obsidian/量化系统/runtime-artifacts/strategy-alpha-parameter-map-01-20260908`. No global environment, dependency, artifact root, fixture/profile configuration or launcher was changed. No worktree preview/server was started.

Rollback remains available at `/research?layout=previous`, `/portfolio?layout=legacy`, and older `/research?layout=legacy`. Backup refs remain `codex/research-portfolio-before-20260909=13486a7802628e93dd624213ba6c317c5deb4ddf` and `codex/research-before-20260908=4096453b344e777e99f4272b43582d60cf1251f9`. Any permanent rollback must be a scoped revert, never a reset of main.

The user authorized necessary project engineering, and this ticket completed its page and read-only API acceptance. The **real end-to-end research workflow is still not passed** because it was not rerun by this integration ticket and current data/evidence/gates are not eligible: the evidence registry is unreadable/conflicting, research integration run registries are empty, system data coverage is missing, paper validation is blocked and the promotion artifact is unavailable. Historical Qlib/provider/training smoke or mocked UI evidence must not be substituted for current research/promotion evidence.

Not run: real Qlib training/backtest/metric/portfolio workflow, evidence-registry rebuild or repair, artifact/bootstrap/publication, promotion artifact rebuild, paper queue writes, private/account/order/live/broker calls, real execution, transfer or withdrawal. No manifest, ledger or promotion artifact was produced by this integration. Promotion, paper, live, private, order, real-order, transfer and withdraw remain false/fail-closed. Integration itself unlocks none of them.

The final append-only integrated handoff will be followed by a current-main service restart and an external final acceptance receipt at `D:/vibe coding/Obsidian/量化系统/research-verification/research-portfolio-unification-01/integration-evidence/final-acceptance-receipt.json`; that receipt binds the final metadata HEAD and listener identities without creating a circular report commit.
