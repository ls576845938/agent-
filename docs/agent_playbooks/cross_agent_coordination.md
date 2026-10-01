# Cross-Agent Coordination Contract

## Purpose

Git worktrees isolate writers. This contract adds discovery and durable handoff without sharing dirty files or creating a second mutable source of truth.

## Four planes

1. Work plane: each writer owns one dedicated worktree. Uncommitted content is private.
2. Data plane: the data steward atomically publishes immutable versions to the shared data root. Consumers are read-only.
3. Handoff plane: committed append-only events reference committed deliverables and manifests.
4. Read plane: `team_context.py` performs bounded discovery from Git refs, manifests, and local domain operator reports. Consumers run the full Git/hash validator before use.

## Required producer sequence

1. Record base commit, touch set, and dirty baseline.
2. Build and test the deliverable in the producer worktree.
3. Commit the deliverable.
4. For data, publish the immutable physical version and commit its manifest.
5. Create a separate handoff event referencing the deliverable commit and exact SHA-256 values.
6. Commit the handoff event. A chat message is optional notification, not durable evidence.

## Required consumer sequence

1. Read the injected Team Context packet or run `team_context.py`.
2. Verify producer commit, schema, readiness class, blockers, hash, and shared data publication marker. Resolve branch-owned manifests with `shared_data.py resolve --manifest-git-spec <branch>:<path>`.
3. Reject missing, stale, conflicting, expired, superseded, or unauthorized handoffs.
4. Publish an `acknowledged` or `rejected` event from the consumer branch.
5. Never consume another worktree's uncommitted path.

## Readiness semantics

- `quality_checked`: quality checks ran; downstream suitability is not established.
- `research_ready`: suitable only for bounded research.
- `backtest_ready`: clean enough for the named backtest contract; not promotion evidence by itself.
- `promotion_evidence_ready`: eligible to enter a current-HEAD gate rebuild; does not pass the gate.

Every handoff and shared data manifest keeps promotion, paper, live, private, and order unlock flags false.

## Integration

The architect approves scope and dependencies but remains read-only. A short-lived `agent/integrator/<ticket>` worktree performs one integration at a time from a clean main base. It validates the handoff, base ancestry, tests, artifact freshness, and conflicts before merge or cherry-pick. The dirty main worktree is never used as the integration surface.

### Change-risk exception for Demo transport

`demo_transport_hotfix` is the only source-delivery fastpath. A dedicated sparse
producer still commits the bounded change and publishes an append-only handoff
when another agent consumes it. After the main agent validates the handoff,
deliverable commit, exact touch set, failure-first regression, and Demo safety
attestation, it may fast-forward `main` without a separate integrator. Promotion
artifact/read-model rebuild is not part of this path; backend restart is.

Team Context may derive `integrated_fastpath` only when `gate_impact=none`,
`promotion_eligible=false`, and the deliverable commit is already an ancestor of
current main. This derived read state removes only obsolete integration or
promotion-artifact rebuild noise and never rewrites a historical handoff.
`demo_execution_semantics`, promotion, and live changes still require an
independent integrator.

## BTC runtime artifact plane

BTC runtime delivery has three separate stages and none implies the next:

1. Source integration commits and validates resolver, reader, writer, builder, and shared wiring code.
2. Root bootstrap explicitly provisions the absolute path named only by `QS_BTC_RUNTIME_ARTIFACT_ROOT` and writes the exact repository-owner marker.
3. Artifact publication runs separately under the single-writer lock, publishes immutable batch content, and replaces the latest pointer last.

The physical root is outside every Git worktree and is the direct physical counterpart of logical `artifacts/...` paths. Writers hold the exclusive lock; backend, Team Context, frontend-facing APIs, and other consumers use read-only resolvers. Readers never create directories, copy repo-local artifacts, fall back to a worktree `artifacts/` tree, or expose the physical root. A missing, relative, unreadable, overlapping, or owner-marker-invalid root fails only the BTC artifact read plane closed with `runtime_artifact_root_unavailable`. Source integration does not bootstrap the root, artifact publication does not run during app startup, and handoff/integration never unlocks promotion, paper, private, order, or live permissions.

## Ownership

- Data steward: physical datasets, data manifests, lineage, freshness, and quality.
- BTC developer: BTC code and BTC-specific evidence.
- Super developer: US equity and approved shared infrastructure.
- A-share developer: CN equity domain code and A-share-specific evidence; consumes data-steward manifests read-only.
- Integrator: approved Git integration only; no domain redesign.
- Researcher and architect: read Team Context and report decisions; they do not publish Git events.

## Failure behavior

If Team Context cannot be built, independent local work may continue. Work that depends on another agent's delivery must stop with `team_context_unavailable`. Coordination failures never relax quantitative gates or trading safety flags.
