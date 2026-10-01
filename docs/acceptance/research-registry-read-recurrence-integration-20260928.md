# Research registry read recurrence: independent integration review

Date: 2026-09-28  
Ticket: `RESEARCH-REGISTRY-READ-RECURRENCE-20260928`  
Change risk: `research_readonly_release`

## Verdict

The approved source set is accepted as a source-only release candidate. The recurring evidence-registry read fixes preserve the full saved-registry validation and conflict result, add bounded cooperative cancellation, propagate cancellation through the exact Vite registry GET proxy route, and retain the original 12-second page budget.

This verdict does not claim deployment acceptance. Ordinary merge into current `main`, canonical service restart, and the formal 3000-port page matrix remain pending. Existing registry `CONFLICT` evidence remains fail-closed and must not be relabelled as PASS.

## Source and handoff chain

- Approved base: `ee87345b6ec13b08ee6bf450e8e3a88c15cea150`.
- Final producer business source: `540a66e170bf7b9e273ed9533e797bd9517269a7`.
- Final producer test-only correction: `30841d76cf214965d45242c15cfb49131fbd274c`.
- Valid final producer envelope: `1eea37e6d1a58a535e9cdec024bf14afef9591ca`.
- Final event: `.agent/handoffs/RESEARCH-REGISTRY-READ-RECURRENCE-20260928/published-research-registry-read-recurrence-superseding-03-20260928-30841d76c.json`.
- Earlier `8a6fa8987`, `3c41c1b4c`, and `540a66e17` events are superseded as recorded by the append-only chain; none was rewritten or deleted.
- The final envelope passed `validate_handoff_against_git` with `errors=[]`; base ancestry, exact Git objects, declared blockers, and the eight-file source/test scope were verified before consumption.

## Approved responsibilities and touch set

Business and test paths:

1. `backend/app/api/app_factory.py` — asynchronous, cancellable read-only registry route with fail-closed 499 projection.
2. `quant_us/research/evidence_registry.py` — request-local parent validation reuse, single conflict projection, and bounded cancellation checkpoints without weakening hash/discovery validation.
3. `frontend/vite.config.ts` — cancellation propagation only for raw-path exact `GET /api/research/evidence-registry`.
4. `frontend/src/workspaces/ResearchPortfolioWorkspace.tsx` — initiate registry and Qlib reads before lighter overview reads; deadline remains 12 seconds.
5. `frontend/scripts/test-research-read-request.mjs` — request/cancellation/proxy contract tests.
6. `frontend/scripts/test-research-portfolio-contract.mjs` — fixed overview ordering and deadline contract.
7. `tests/api/test_research_registry_summary_api.py` — actual route success, 409/405/400, disconnect 499, and child-task lifecycle coverage.
8. `tests/research/test_evidence_registry.py` — summary equivalence, cancellation, parent-cache boundary, reparse, and conflict regression coverage.
9. `frontend/public/frontend-identity.json` — generated once after the final business/test integration commit via the existing `identity:refresh` entry point.

This report and the final append-only integration event are delivery evidence only. No strategy, model, risk, OMS, ledger, execution adapter, launcher, timeout, permission, data, or governance rule changed.

## Independent review findings and corrections

Independent review stopped the first candidate for three concrete issues: an outside-parent leaf resolving back inside the root could be accepted, an outer ASGI cancellation did not retrieve the child task result, and a downstream response already closed before the proxy hook installed listeners could leave the upstream request running. A fourth cache-hit variable bug was found in the first correction, and the first actual-route test incorrectly assumed flat FastAPI routes rather than `_IncludedRouter` nesting.

The final producer chain corrects all five issues. Independent full-checkout verification confirmed:

- outside raw parents remain rejected even when a leaf target resolves inside the data root;
- parent-cache hits use the current cached resolved parent and remain history-independent;
- reparse leaves still receive full-path resolution;
- route cancellation sets the cooperative event, retrieves the worker task result, and never returns a partial PASS;
- normal fixture reads return 200, malformed saved evidence returns 409, `rebuild=true` returns 405, and an invalid view returns 400;
- exact registry GET cancellation reaches the upstream proxy request, including the already-closed response race, while normal completion, POST, rebuild POST, and other GET routes remain untouched.

## Verification

All commands ran from the dedicated sparse integration worktree using the canonical repository Python 3.11 environment or a normal worktree-local `npm ci --ignore-scripts --prefer-offline` dependency installation. No junction, preview server, worktree Vite server, or service restart was used.

- `python -m pytest ... test_evidence_registry.py test_research_registry_summary_api.py`: `23 passed, 1 skipped` (Windows symlink privilege only), one existing Starlette deprecation warning.
- Compatibility set `test_research_only_boundaries.py`, `test_qlib_pipeline.py`, `test_m1_research_readonly_archive.py`, `test_research_release_policy.py`: `68 passed`.
- `node frontend/scripts/test-research-read-request.mjs`: `14/14 passed`, including real loopback Vite cancellation.
- `node frontend/scripts/test-research-portfolio-contract.mjs`: PASS.
- `npm run lint`: PASS.
- `npm run build`: PASS, 5,275 modules; only the pre-existing large-chunk warning remained.
- Final source and test blobs match the validated producer commits; scoped source paths were clean before and after cherry-picks.

The producer's final 0.7721-second profile is retained only as producer evidence and is not treated as a directly comparable formal performance claim. Formal acceptance is the current-main browser matrix below.

## Governance and preflight evidence

- Read: `AGENTS.md`, `docs/knowledge/README.md`, `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`, `docs/agent_playbooks/shared_pitfalls.md`, `.codex/agents/integrator.toml`, and `docs/agent_playbooks/research_readonly_release.md`.
- Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
- Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-PROMPT-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WINDOWS-001`, `GOV-WORKTREE-001`, `MONITOR-AUDIT-001`, and `QSYS-GATE-001`.
- Team Context normal CLI discovery succeeded at `2026-09-28T09:01:41Z`, projection `full`, verification mode `discovery_only`. Historical invalid handoffs remained isolated and were not consumed.
- Worktree was created by `worktree_plan.py`, `core.sparseCheckout=true`, and all approved source paths were initially clean. No other agent's uncommitted files were read, overwritten, cleaned, reset, or merged.

## Formal deployment acceptance still required

After ordinary merge and canonical `research_readonly` restart, the single formal browser writer must preserve every attempt and run, without extending the 12-second deadline or selecting only successful retries:

1. bare research overview, three attempts;
2. `m1-okx-qlib` source-bound overview, three attempts;
3. details → overview → rapid leave/return, three attempts;
4. one bounded dual-page overlap group through port 3000.

Every attempt must finish within the existing page deadline with no partial read failure. Evidence-registry `CONFLICT` is an expected current evidence state, not a transport failure and not promotion readiness. Current-main backend/frontend identity, listener ownership, health, canonical/stale flags, and the exact merged HEAD must also be verified.

## Safety and remaining blockers

No artifact, manifest, model, data set, ledger, account fact, order, or runtime record was created or modified. No private, broker, order, live, paper, candidate-management write, training, rebuild, recovery, or trading endpoint was called.

The following remain false and fail-closed: `promotion`, `paper`, `live`, `private`, `order`, `real_order`, `transfer`, `withdraw`, `execution_permission`, `runtime_observed`, `candidate_management_write`, and Demo controls. Production BTC runtime evidence unavailability and the current registry conflict remain unchanged. This source review is not promotion evidence and does not prove strategy quality or trading readiness.
