# M1 immutable archive frontend compatibility integration — 2026-09-12

## Decision

- Ticket: `M1-ARCHIVE-COMPAT-INTEGRATION-20260912`.
- Role: short-lived `integrator`; change risk: `research_readonly_release`.
- Approved base / rollback point: `c9aec584fb1fbe6712399162f080935c59d2e81f` on registered `main`.
- Producer final: `47d921a88e4bd0de88798b338efc0189353de927`; producer deliverable: `66aa7c43f8ef571fd8968d0e0ddd20a8c7f82399`; producer code: `59ff1591607588332da84a0619fd403e1177060b`.
- Producer event `published-m1-archive-compat-fix-20260912-66aa7c43f` was independently revalidated as `valid`; base → code → deliverable → final ancestry and all declared deliverable hashes passed.
- Offline integration review is accepted at readiness ceiling `quality_checked`. Registered-main publication, canonical restart and real-browser acceptance are intentionally still pending and are not claimed by this report.

## Scope and ownership

Initial scoped status was clean. No overlapping dirty path was found and no other worktree was cleaned, reset or overwritten.

Approved production paths:

- `frontend/src/workspaces/research/workspace-evidence.ts`: fixed immutable M1 Qlib archive identity, shared sequential read/cancellation contract.
- `frontend/src/workspaces/research/ResearchRunDetails.tsx`: selected detail first, then Qlib and Factory lists; partial list success remains visible; selected evidence never falls back to another run.
- `frontend/src/workspaces/research/AlphaFactoryConsole.tsx`: read-only parent data injection prevents duplicate child GETs and keeps submit/resume controls absent.

Approved verification and release paths:

- `frontend/scripts/test-m1-archive-compat.mjs`.
- `frontend/e2e/m1-archive-compat.spec.ts`.
- `frontend/public/frontend-identity.json`.
- Producer report / published handoff and this integration report / integrated handoff.

No backend, global timeout, data pipeline, strategy signal, position, exit, risk, OMS, protection, ledger, broker/private transport, runtime artifact store, governance or permission path changed.

## Independent review findings

The producer repair correctly confines archive acceptance to the run-details read-only surface. Existing portfolio actions and shared research/portfolio action guards still call `runEvidenceErrors` without `allowReadonlyM1Archive`, so an immutable historical M1 run cannot become a portfolio action input.

One material fail-closed defect was found and corrected in the integration ticket. `exactM1QlibArchive` originally reused the Windows local-path normalizer for a logical `shared-data://` URI, which accepted case changes, backslashes and a trailing slash. The archive URI now requires exact string equality while legacy local-path matching keeps its previous normalization behavior. Failure-first tests reproduced the permissive behavior before the correction and now reject all three variants.

Two test-only races were also corrected:

- the partial-success browser case now waits until the factory handler has actually installed its release callback;
- the factory-detail case waits until both list results are visible before asserting the complete serialized request order.

The shared read scheduler was reviewed for StrictMode setup/cleanup/setup, cancellation between stages, completed-read eviction and same-key replacement. A new same-key replacement assertion passes: a cancelled old entry cannot delete or feed the replacement entry. No production scheduler change was required.

## Validation

- `node frontend/scripts/test-m1-archive-compat.mjs` — PASS. Exact archive identity, StrictMode sharing, serialized reads, cancellation, refresh, partial failure and same-key replacement covered.
- `D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_m1_research_readonly_archive.py` — **11 passed**, one upstream Starlette deprecation warning, 20.37 s.
- `npm.cmd --prefix frontend run lint` — PASS (`tsc --noEmit`).
- `npm.cmd --prefix frontend run build` — PASS, 5,258 modules in 18.91 s; pre-existing chunk-size warning remains.
- `npm.cmd --prefix frontend run identity:check` — PASS on integration branch, manifest match true, baseline ancestor true, dirty paths empty.
- `npm.cmd --prefix frontend run identity:test` — PASS, four object targets.
- `npx.cmd playwright test --list e2e/m1-archive-compat.spec.ts` — four cases discovered. This is discovery only, not browser execution.
- `node frontend/scripts/test-research-portfolio-contract.mjs` — FAIL on the pre-existing frozen `frontend/src/lib/task-api.ts` baseline because `submitQlibPipelineTask` already exists on base. Both that script and `task-api.ts` are byte-for-byte unchanged by this ticket (`git diff --exit-code base..integration -- ...` passed). The failure is recorded, not repaired or hidden.
- `git diff --check base..integration` — PASS.

The four Playwright cases were not executed in this worktree because repository policy allows browser acceptance only on canonical registered-main port 3000. They must run after the separately authorized publication and official restart.

## Frontend identity

- Identity baseline commit: `257d4323d730350be780412a5112b4eef8d102d5`.
- Fingerprint: `0ffa7fa461912b55f34b75a5e97ffe6a65444cb7d7d408935d9b17f34459e874`.
- Frontend source tree: `8380e8c67c2c6828497343f65452ce373cd195cf`.
- Canonical state remains false in this isolated worktree by design. Current-main identity and listener ownership are pending publication acceptance.

## Governance evidence

- Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
- Read: `AGENTS.md`, `docs/knowledge/README.md`, `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`, `docs/agent_playbooks/shared_pitfalls.md`, `.codex/agents/integrator.toml`, `docs/agent_playbooks/delivery_risk_policy.json`, `docs/agent_playbooks/research_readonly_release.md`, and both quant preflight/handoff skills.
- Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `MONITOR-AUDIT-001`, `QSYS-GATE-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.
- Raw historical pitfall logs were not read because no selected rule required incident detail.

## Remaining fail-closed state

- Pending: controlled registered-main integration, official backend/frontend restart in `research_readonly`, current-main identity/listener verification, the four canonical browser cases and live M1 page acceptance.
- `demo_control_enabled=false`; `promotion=false`; `paper=false`; `live=false`; `private=false`; `order=false`; `real_order=false`; `transfer=false`; `withdraw=false`; `execution_permission=false`; `runtime_observed=false` remain required.
- BTC runtime artifact root unavailability / 503 is preserved; no root, marker or artifact was created.
- M1 evidence remains historically reconstructed and stale relative to current code; the Alpha Factory candidate remains rejected. This is not runtime, performance, promotion, paper or live evidence.
- M2–M4 remain unauthorized and were not started.
