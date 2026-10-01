# BTC-V3-SHARED-RUNTIME-ARTIFACT-ROOT-RESOLVER-01

## Scope and boundary

This ticket starts from
`9166b1b2bb97009b31d03c75ee68ef8674372e85` in the planner-created sparse
worktree and branch
`agent/btc_developer/btc-v3-shared-runtime-artifact-root-resolver-01`.
The first Git command in the worktree confirmed
`core.sparseCheckout=true`.

The declared source touch set was initially clean. The corresponding domain
read-model contract test was added to the touch set after the existing
repository consumer was found; its scoped status was also clean before the
edit. There were no overlapping dirty paths or ownership conflicts.

This ticket does not modify shared backend configuration, API wiring,
cross-domain schemas or enums, shared data, SQLite, `data/**`, or a real
runtime artifact root. It performs no network collection and no private,
order, paper, live, broker, secret, or paper-queue action.

## External runtime-artifact contract

`QS_BTC_RUNTIME_ARTIFACT_ROOT` is the only implicit runtime-artifact root.
It must be an absolute, existing directory that is disjoint from every Git
worktree and represents the physical directory corresponding directly to the
logical `artifacts/` prefix.

The owner marker
`.qs_btc_runtime_artifact_root_owner.json` is schema-exact, bound to the Git
common-directory repository identity, and revalidated on access. Missing or
relative configuration, an overlapping worktree, marker mismatch, malformed
logical paths, path traversal, and symlink or junction escape all fail closed.
There is no repo-local fallback.

Readers expose no write API. Writers require an exclusive root-wide lock;
the second writer fails immediately. JSON and byte publication use a
same-directory temporary file, flush, `fsync`, and atomic `os.replace`.
An exception during replacement does not advance the latest pointer.

## Consumer migration

The following consumers retain logical `artifacts/...` paths while resolving
their physical files through the external root:

- DataReady report publication;
- BTC domain read-model source reads;
- gate run snapshot publication, latest-pointer reads and historical replay;
- current-HEAD gate evidence reads, output publication and immutable snapshot;
- aligned L2 capture quality, WS replay and reconnect/resync builders.

`source_repo_root` remains limited to Git HEAD, scoped dirty state and source
hashing. Gate snapshot readers fail closed when the latest pointer is absent
or invalid and never fall back to a mutable latest artifact. An active gate
writer session is reused for pointer publication, avoiding nested locks while
preserving one process-wide writer.

## Failure-first and verification evidence

Before implementation, the dedicated resolver contract failed during
collection with
`ModuleNotFoundError: No module named
'quant_crypto.adapters.btc_runtime_artifact_store'`.

After implementation:

- dedicated resolver contracts: `9 passed`;
- DataReady contracts: `52 passed`;
- domain read-model contracts: `11 passed`;
- gate snapshot contracts: `9 passed`;
- current-HEAD gate rebuild contracts: `6 passed`;
- three scalping report contracts: `16 passed`;
- combined target suite: `103 passed`;
- no-broker-import guardrail: `3 passed`;
- focused `compileall`: pass;
- five affected builder CLI `--help` invocations: exit `0`;
- scoped `git diff --check`: pass.

Every pytest command used a unique system temporary directory. The final
acceptance run disabled pytest's cache provider. No production artifact was
rebuilt or published. Ruff and Black were unavailable in the active Python
runtime and therefore were not run.

## Governance evidence and remaining gates

Read:

- `AGENTS.md`;
- `docs/knowledge/README.md`;
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`;
- `docs/agent_playbooks/shared_pitfalls.md`;
- `docs/agent_playbooks/btc_developer_pitfalls.md`;
- role-routed data, research, portfolio/risk, OMS, architecture,
  monitoring/replay, crypto market-structure, exchange SRE/security and BTC
  trend rules.

Catalog hash:
`568cf9c4f4d96d1cff4d331f29b69ec40ad28b6c13156d542c586ef5d8314a11`.

Active pitfall IDs:
`GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-HANDOFF-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`,
`QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, and
`GOV-WINDOWS-001`.

Team Context reported no ready upstreams, available deliveries, integration
candidates or invalid handoffs. No other worktree's uncommitted files were
consumed.

This storage repair does not rebuild promotion evidence or change any
readiness class. `promotion=false`, `paper=false`, `live=false`,
`private=false`, `order=false`, `broker=false`, `withdraw=false`,
`network=false`, `secret=false`, `paper_queue=false`, and
`real_order=false` remain fail closed. Existing funding, mark/index,
liquidation-buffer, venue-filter, OMS, reconciliation, outage/cancel-only,
audit-DAG, replay and manual-review blockers remain unchanged.
