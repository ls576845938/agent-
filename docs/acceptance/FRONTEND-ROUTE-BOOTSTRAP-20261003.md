# FRONTEND-ROUTE-BOOTSTRAP-20261003 producer acceptance

## Decision

- Producer status: `quality_checked`; independent integration and canonical-browser acceptance remain required.
- Role: `super_developer`.
- Change risk: `research_readonly_release`.
- Base / rollback point: `b21bb541127ae71ee5e80c3aa4006c7d5338bd6d`.
- Branch: `agent/super_developer/frontend-route-bootstrap-20261003`.
- Dedicated worktree: planner-created sparse checkout; `core.sparseCheckout=true`.
- No strategy, position, risk, OMS, ledger, broker/private transport, permission, launcher, dependency-version, data, manifest, runtime-artifact, or promotion semantics changed.

## Owned touch set and behavior

- `frontend/src/App.tsx`: loads the eight non-architecture workspaces through route-level dynamic imports and keeps the existing architecture workspace dynamic. Each route retains the existing `ErrorBoundary`; loading is announced with `role=status`; module-download failure is announced with `role=alert` and offers a real full-page refresh. The Crypto workspace keeps its evidence-profile/read-only/controls-disabled-derived component key and all existing props.
- `frontend/src/components/workbench/Workbench.tsx`: replaces the package-root Phosphor import with the 16 installed `@phosphor-icons/react@2.1.10` official `dist/csr/<Name>` subpaths. Icon names and JSX usage are unchanged.
- `frontend/scripts/test-route-bootstrap.mjs`: programmatic Vite/Rollup graph regression using the real `main.tsx` entry. It can read the base `App.tsx` from a committed Git object for failure-first proof, rejects eager workspace leakage, requires nine route dynamic entries, and imports all 16 CSR icon modules.
- This acceptance record and the ticket-local append-only handoff are the only additional delivery files.
- `frontend/public/frontend-identity.json` is intentionally not touched; the independent integrator owns the identity refresh.

## Failure-first and focused validation

1. Valid base regression (committed Git object, no dirty-source rollback):

   ```powershell
   $env:ROUTE_BOOTSTRAP_BASE_REF='b21bb541127ae71ee5e80c3aa4006c7d5338bd6d'
   node scripts\test-route-bootstrap.mjs
   ```

   Result: expected failure, exit `1`, `61.161s`: `CryptoWorkspace.tsx leaked into the initial App execution graph`, including the actual module path.

2. TypeScript:

   ```powershell
   npm run lint
   ```

   The first implementation attempt failed closed because the repository `react-shim.d.ts` does not export `ComponentType` or `Key`; the loader was narrowed locally without changing the shared shim. Final result: exit `0`, `12.280s`, no diagnostics. The earlier failing run is retained as a test-development result, not hidden as a pass.

3. Current import graph and icon resolution:

   ```powershell
   Remove-Item Env:ROUTE_BOOTSTRAP_BASE_REF -ErrorAction SilentlyContinue
   node scripts\test-route-bootstrap.mjs
   ```

   Result: exit `0`, `55.034s`: `9 route chunks are lazy and 16 CSR icon modules resolve`.

4. Scoped whitespace check:

   ```powershell
   git diff --check -- frontend/src/App.tsx frontend/src/components/workbench/Workbench.tsx frontend/scripts/test-route-bootstrap.mjs docs/acceptance/FRONTEND-ROUTE-BOOTSTRAP-20261003.md
   ```

   Result: exit `0`; only Git's existing LF-to-CRLF worktree warnings were emitted.

The initial App-direct Rollup-input attempts were test calibration failures (Windows path normalization, then an input that did not execute `App`); they are not used as failure-first product evidence. The real-entry/base-object result above supersedes them.

## Deferred acceptance and material risk

- Per ticket boundary, the producer did not start Vite/preview/Playwright servers and did not run the formal 29-case browser matrix. The independent integrator must refresh the committed frontend identity, integrate on current main, use the canonical launcher, and verify the unchanged 29-item / 30s / 5s / 1-worker / 0-retry budget.
- `main.tsx` still loads `index.css`, `workbench.css`, and `terminal-workbench.css` eagerly. Route-owned CSS for CN equity, strategy explorer, strategy modules, and architecture now arrives with its route chunk. This is the intended dependency delay but creates a material first-navigation risk (brief loading state or route CSS arrival ordering), so same-page navigation and computed-style/browser checks remain required.
- A rejected route import is not retried through React's cached lazy promise. The loader displays a reliable `window.location.reload()` recovery action; the canonical browser test must inject a one-time module failure and verify the visible alert plus successful refresh recovery.
- No backend restart, artifact/manifest/ledger/replay rebuild, data discovery, or source freshness claim was made. This UI delivery is not promotion evidence.

## Correction 01: route state identity isolation

Committed pre-integration review found that all nine route elements rendered the same unkeyed `LazyWorkspace` component type. React reconciliation could therefore retain `Workspace` or `loadError` state while moving between routes, briefly rendering the prior workspace with the next route's props before the new effect ran. Clearing state inside the effect would still occur after render and was rejected as insufficient.

The correction assigns every `LazyWorkspace` element a unique stable string-literal React key. The Crypto loader identity remains the stable `route-crypto`; its separate `componentKey` still carries `evidence_profile`, `read_only`, and `controls_disabled`, so health changes remount only the loaded Crypto workspace rather than resetting the loader. Because this repository's minimal `react-shim.d.ts` does not declare React's built-in JSX key attribute, `LazyWorkspaceProps` locally permits an optional `key` solely for type checking; the component does not read it.

Correction validation:

1. Failure-first on the prior committed implementation:

   ```powershell
   node scripts\test-route-bootstrap.mjs
   ```

   Result: exit `1`, `58.642s`, `LazyWorkspace is missing a stable route identity key`.

2. First TypeScript correction attempt: exit `2`, `13.495s`; all nine elements reported `Property 'key' does not exist on type 'LazyWorkspaceProps<...>'`. This exposed the repository shim limitation and was fixed locally without changing `react-shim.d.ts`.

3. Final TypeScript:

   ```powershell
   npm run lint
   ```

   Result: exit `0`, `13.459s`, no diagnostics.

4. Final import graph, icon resolution, and route identity structure:

   ```powershell
   node scripts\test-route-bootstrap.mjs
   ```

   Result: exit `0`, `55.009s`: `9 lazy route chunks have isolated identities and 16 CSR icon modules resolve`.

The producer did not run the same-page browser navigation check; it remains an explicit independent-integrator acceptance item. Fresh Team Context generation in the sparse producer failed with `ModuleNotFoundError: No module named 'quant_crypto'`; no upstream delivery was consumed, and this correction depends only on the branch's committed ticket history.

## Governance evidence

- Initial scoped dirty paths: none (`dirty_count=0`). No overlapping writer changes were found or overwritten.
- Team Context: no ready upstream, dependency, integration candidate, or valid handoff was consumed.
- Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
- Playbooks read: `AGENTS.md`, `docs/knowledge/README.md`, `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`, `docs/agent_playbooks/shared_pitfalls.md`, `docs/agent_playbooks/super_developer_pitfalls.md`, `docs/agent_playbooks/delivery_risk_policy.json`, and `docs/agent_playbooks/research_readonly_release.md`.
- Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `MONITOR-AUDIT-001`, `QSYS-GATE-001`, `RESEARCH-HOLDOUT-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.
- Required safety flags remain false: `demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`, `real_order`, `transfer`, `withdraw`, `execution_permission`, `runtime_observed`.
- Final release remains fail-closed pending independent integrator review, committed-handoff verification, current-main identity, canonical-browser acceptance, and rollback-point verification.
