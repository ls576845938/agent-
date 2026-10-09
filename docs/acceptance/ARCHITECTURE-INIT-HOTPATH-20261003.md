# Architecture Initialization Hotpath Producer Acceptance

- Ticket: `ARCHITECTURE-INIT-HOTPATH-20261003`
- Role: `super_developer` (sole producer)
- Change risk: `research_readonly_release`
- Base commit: `8407236769b52088ec2483fc5bfeb9e7c8653c31`
- Readiness ceiling: `quality_checked`
- Delivery state: committed producer candidate only; independent integration and canonical-main acceptance remain required

## Scope and responsibility boundary

This producer ticket changes only architecture-editor initialization cost:

- `ArchitectureMapWorkspace.tsx` initializes all catalog module buckets, then scans `catalog.files` once and appends each file to the bucket returned by the existing `moduleOf` function. It does not change `moduleOf`, catalog order, prefix specificity, stable tie behavior, empty buckets, or legacy fallback behavior.
- `btcPanoramaLayout.ts` loads ELK only inside the existing explicit asynchronous `arrangeBtcPanorama` operation. Layout options, group positions, routing, catch behavior, draft semantics, and editor status/ready behavior are unchanged.
- `test-architecture-initialization.mjs` executes the real `byModule` initializer extracted through the TypeScript AST and inspects a Vite `write:false` module graph for the layout entry. A Git-object injection mode proves the old base fails the new contract.

No package, Vite configuration, E2E timeout/budget, route, ready state, draft behavior, status text, model, catalog, data, strategy, position, risk, OMS, protection, ledger, broker/private transport, security, permission, runtime artifact, promotion, paper, or live behavior changed.

## Failure-first and focused validation

### Old base injected into the new regression

Command:

```powershell
$env:ARCHITECTURE_INIT_BASE_REF='8407236769b52088ec2483fc5bfeb9e7c8653c31'
node --experimental-strip-types ./scripts/test-architecture-initialization.mjs
```

Result: expected exit `1`; `1/3` passed and `2/3` failed.

- Old grouping called `moduleOf` `62,875` times instead of the required `2,515` calls (`25` modules x `2,515` files).
- Old static graph included `elkjs/lib/elk.bundled.js?commonjs-module`.
- Explicit `arrangeBtcPanorama` still passed, isolating the initialization defects from the existing layout behavior.

### Updated source

```powershell
node --experimental-strip-types ./scripts/test-architecture-initialization.mjs
```

Result: exit `0`, `3/3` passed. The test proves:

- exactly one `moduleOf` call per catalog file;
- all 25 buckets have exactly the same file identities and order as the previous per-module filter algorithm;
- `scripts/` and `schemas/` equal-length ties still resolve to `quality`, `alpha-radar/` still resolves to `legacy`, and `operation_scripts`, `evidence_schemas`, and `legacy_audit` remain empty;
- unmatched catalog paths retain their order in the `legacy` fallback bucket;
- ELK is emitted but is absent from the layout entry's static import closure;
- explicit arrangement dynamically loads ELK and returns nodes/routes.

```powershell
node --experimental-strip-types ./scripts/test-btc-system-panorama.mjs
```

Result: exit `0`, `7/7` passed, including the existing complete A-I snapshot, boundary, layered layout/routing, editor control, and draft parser checks.

### TypeScript check limitation

`npm.cmd run lint` was attempted but is **not recorded as passed**:

1. The first run failed before project type analysis because an interrupted `npm ci --ignore-scripts --no-audit --no-fund` left the ticket-local ignored dependency directory without the installed Phosphor declarations and executable shim.
2. That producer-created partial directory was preserved as `frontend/node_modules.partial`; `frontend/node_modules` was changed to a local directory junction to the registered main worktree's complete locked dependencies. No tracked dependency or main-worktree file was modified.
3. The second run invoked the expected `typescript/bin/tsc --noEmit` process, but produced no diagnostics or exit after several minutes. PID sampling showed the responding process progress only from CPU `7.296875s` to `8.046875s` over about 40 seconds, with working set near 77 MB. It was terminated once as an environment-level low-progress/hung check and was not rerun.

Therefore full TypeScript validation is outstanding and must pass in the independent integrator worktree before this candidate can be accepted or published. The focused executable tests above passed; they do not substitute for full type checking.

## Context, evidence, and remaining acceptance

- Playbooks read: `AGENTS.md`, `docs/knowledge/README.md`, `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`, `docs/agent_playbooks/shared_pitfalls.md`, `docs/agent_playbooks/super_developer_pitfalls.md`, `docs/agent_playbooks/delivery_risk_policy.json`, and `docs/agent_playbooks/research_readonly_release.md`.
- Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
- Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `MONITOR-AUDIT-001`, `QSYS-GATE-001`, `RESEARCH-HOLDOUT-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.
- Initial declared touch paths were clean; no overlapping tracked producer changes were found or overwritten.
- No data, artifact, manifest, ledger, replay, runtime store, or frontend identity artifact was generated or rebuilt.
- Root-owned external timing evidence exists at `D:/quantstation-runtime/architecture-init-timing-20261003/`; it is not a producer artifact and is not claimed as current integrated-main acceptance.
- Producer did not start a server or preview and did not run the canonical browser matrix. The independent integrator/root owns current-main frontend fingerprinting, canonical port 3000 startup, the unchanged 29-case/1-worker/0-retry browser matrix, timing acceptance, ELK-load-failure browser behavior, restart, and rollback verification.

This candidate remains blocked from integration/release until an independent integrator validates the committed hashes and touch set, obtains a completed TypeScript check, and passes current-main canonical acceptance. It is not promotion evidence and does not unlock research readiness beyond the contract ceiling.

All required false flags remain false: `demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`, `real_order`, `transfer`, `withdraw`, `execution_permission`, and `runtime_observed`.
