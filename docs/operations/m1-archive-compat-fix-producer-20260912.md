# M1 immutable archive frontend compatibility producer report

Date: 2026-09-12

Ticket: `M1-ARCHIVE-COMPAT-FIX-20260912`

Role: `super_developer`

Change risk: `research_readonly_release`

Base: `c9aec584fb1fbe6712399162f080935c59d2e81f`

Code/test deliverable: `59ff1591607588332da84a0619fd403e1177060b`

## Scope and diagnosis

The canonical page on the base commit showed both `部分运行目录读取失败` and `返回的运行身份或来源目录不匹配`. The second error was deterministic: `runEvidenceErrors` accepted only `artifacts/qlib_runs/<id>` and rejected the fixed `shared-data://...` logical root returned by the sealed M1 archive API.

The list timeout was caused by an avoidable request pattern in the page. The old page started Qlib detail, Qlib list, and Alpha Factory overview together; React StrictMode repeated mount effects, and the read-only Factory child started overlapping detail/overview reads again. Every archive GET intentionally re-verifies the committed manifest and all file hashes. Canonical shell measurements showed the three concurrent GETs still completed below 12 seconds in one reproduction, so an exact greater-than-20-second duration is not claimed as deterministic. The browser failure, StrictMode double-effect source, redundant parent/child GETs, and independent full-integrity work per GET establish the request storm and I/O contention as the minimal frontend defect to remove.

No backend cache, global timeout increase, integrity bypass, manifest relaxation, or archive storage change was made.

## Changed files and boundaries

- `frontend/src/workspaces/research/workspace-evidence.ts`
  - Keeps the default shared-workspace contract local-only.
  - Allows the immutable archive only through an explicit read-only-details option and exact M1 dataset id, dataset version, Git manifest spec, logical run, URI, consumer-read-only, and historical-availability binding.
  - Adds a reference-counted in-flight read coordinator: StrictMode reuses one chain, archive GETs run sequentially, obsolete chains stop before later stages, and completed promises are removed so explicit refreshes perform new verified GETs.
- `frontend/src/workspaces/research/ResearchRunDetails.tsx`
  - Uses one detail-first serialized chain for the selected run and both picker lists.
  - Publishes each successful list independently; one later failure does not erase the earlier successful directory.
  - Ignores stale component completions and never falls back to `latest` or another run.
  - Enables the strict M1 archive option only on this read-only page.
- `frontend/src/workspaces/research/AlphaFactoryConsole.tsx`
  - In read-only detail mode consumes parent-provided verified overview/detail and performs no duplicate overview, detail, polling, submit, or resume request.
  - The normal Alpha Factory console keeps its existing behavior.
- `frontend/scripts/test-m1-archive-compat.mjs`
  - Failure-first contract for exact archive provenance, local-only default, StrictMode reuse, serialization, cancellation, partial failure, and non-persistent in-flight promises.
- `frontend/e2e/m1-archive-compat.spec.ts`
  - Canonical integration acceptance for request count/order, parent/child de-duplication, provenance rejection, progressive partial success, and zero non-GET requests.

There are no changes to API request timeouts, backend services, schemas, data, strategy signals, positions, exits, risk, OMS, protection, ledger, broker transport, private WebSocket reconciliation, runtime artifact storage/publication, promotion, permissions, or governance.

## Failure-first and verification evidence

- Failure-first: `node frontend/scripts/test-m1-archive-compat.mjs`
  - Before the production fix: failed because the exact fixed M1 archive returned one root error (`1 !== 0`).
  - After the fix: `PASS: exact M1 archive provenance and sequential full-integrity research reads.`
- `npm.cmd --prefix frontend run lint`
  - PASS, TypeScript `--noEmit`.
- `npm.cmd --prefix frontend run build`
  - PASS, 5,258 modules transformed in 51.15 seconds.
  - Existing Vite warning remains for chunks larger than 500 kB.
- `npx.cmd playwright test --list e2e/m1-archive-compat.spec.ts`
  - PASS, four tests discovered.
- `npx.cmd tsc --noEmit --target ES2022 --module ESNext --moduleResolution Node --types node,@playwright/test e2e/m1-archive-compat.spec.ts`
  - PASS.
- `python -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_m1_research_readonly_archive.py`
  - PASS, `11 passed`, one upstream Starlette/httpx deprecation warning.
  - The first sparse runs failed only because planner defaults omitted read-only `quant_crypto` and then `quant_cn`; adding those two sparse read surfaces made the unchanged suite pass. No files under either domain were edited.
- `node frontend/scripts/test-research-portfolio-contract.mjs`
  - Existing unrelated failure remains: frozen rollback baseline does not include the already-current `taskApi.submitQlibPipelineTask`. This ticket did not modify `task-api.ts`, the frozen baseline, or that regression contract.

The producer did not run a worktree frontend server or the new browser tests. Repository policy permits only the registered current-main frontend on port 3000. The independent integrator must merge the committed deliverable into its own clean integration worktree, update/verify frontend identity as required, run the four canonical browser tests, publish to main only through the approved path, restart via official launchers in `research_readonly`, and repeat real-browser acceptance.

## Existing evidence and gate state

- Immutable source manifest remains `.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json` at fixed Git object `165a446729f8c114748e1b20bbfcf0c91e75066e`.
- Aggregate archive SHA-256 remains `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`.
- Historical reconstructed availability and `source_stale=true` remain visible facts; they are not current-HEAD promotion evidence.
- The BTC runtime artifact root 503 is outside this ticket and remains unchanged.
- Readiness ceiling is `quality_checked`. M2-M4 are not started.
- `demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`, `real_order`, `transfer`, `withdraw`, `execution_permission`, and `runtime_observed` remain false.

## Governance evidence

Read: `AGENTS.md`, `docs/knowledge/README.md`, `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`, `docs/agent_playbooks/shared_pitfalls.md`, `docs/agent_playbooks/super_developer_pitfalls.md`, `docs/agent_playbooks/delivery_risk_policy.json`, `docs/agent_playbooks/research_readonly_release.md`, and `docs/knowledge/05_architecture/domain_architecture_rules.md`.

Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.

Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `MONITOR-AUDIT-001`, `QSYS-GATE-001`, `RESEARCH-HOLDOUT-001`, `GOV-PROMPT-001`, and `GOV-WINDOWS-001`.

All declared source paths were clean before edits. No overlap or uncommitted upstream file was consumed. No raw pitfall log was needed.
