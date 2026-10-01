# BTC candidate offline entry independent integration review

Ticket: `INTEGRATE-BTC-CANDIDATE-OFFLINE-ENTRY-20260925`  
Role: short-lived `integrator`  
Change risk: `unclassified`  
Decision: `rejected` / `blocked` at source-candidate acceptance  
Readiness ceiling: `quality_checked`; not integrated, deployed, or promotion eligible

## Commit and worktree identity

- Registered-main baseline: `9c1dac906f4b4527aa247d14f18497f56e9d8464`.
- Upstream source: `3950f16ca20246e91a7f0a3ceee1eb04c33910d7`.
- Producer development base / upstream handoff commit:
  `15b2ea256de08c37e5d6cf15f1d5d0ece4178221`.
- Producer source under review: `82cb044ed9eaa2e7619d3ada5639f3bc5a96c091`.
- Producer published-handoff HEAD and integration test HEAD before this report:
  `c3a6fb0bd4e06ebcfa8e42b0090617796f5f729a`.
- Integration branch:
  `agent/integrator/integrate-btc-candidate-offline-entry-20260925`.
- Planner worktree:
  `D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-btc-candidate-offline-entry-20260925`.
- `core.sparseCheckout=true`. The planner created this worktree from the
  approved `c3a6fb0...` handoff commit. No producer-private or uncommitted path
  was read.

The business source identity is `82cb044e...`; this report and its later handoff
commits are review-only commits and do not change that source identity.

## Pre-consumption validation and initial dirty state

The following append-only events validated as `status=valid` with the repository
validator before source consumption:

- `published-btc-candidate-offline-entry-20260925-82cb044ed`;
- `published-btc-candidate-package-runtime-20260925-3950f16ca`;
- `acknowledged-btc-candidate-offline-entry-upstream-20260925`.

Ancestry checks passed for `15b2ea... -> 82cb044e... -> c3a6fb0...` and
`3950f16c... -> 82cb044e...`. All 32 declared deliverables were read from the
`82cb044e...` Git objects and their SHA-256 values matched the published envelope.
The 32 declared paths plus this ticket's report/handoff paths were checked with
`safe_status.py`: 34 explicit scopes, `dirty_count=0`. No overlapping writer or
unmerged dirty change was found.

No production artifact, manifest, runtime pointer, economic ledger, candidate,
or observation data was rebuilt. Test-only state used
`D:/vibe coding/Obsidian/量化系统/integration_tmp/INTEGRATE-BTC-CANDIDATE-OFFLINE-ENTRY-20260925-20260925T1700`,
outside the repository and worktree; it is not a deliverable.

## Blocking P1: result projection is not bound to the full job identity

The candidate is rejected because a self-consistent but wrong/stale projection
can be accepted as the current job's result:

- `backend/app/services/candidate_offline_views.py:9-23` constructs a result
  projection with only part of the durable job identity. It does not bind the
  complete account/runtime/state binding identity, including `binding_digest`
  and `catalog_sha256`.
- `backend/app/services/candidate_offline_service.py:79-94` accepts a result when
  `registration_id`, `content_digest`, and `input_digest` match and its internal
  `sha256` recomputes. It does not compare `job_id`, `source_head`,
  `execution_head`, `input_revision_id`, `input_head`, or the complete binding
  identity against the current job. Decision rows add only `job_id` to the same
  three-field comparison.
- The durable job created at
  `backend/app/services/candidate_offline_service.py:126-132` carries additional
  identity fields: `source_head`, `execution_head`, `input_head`,
  `input_evidence_kind`, `catalog_sha256`, and `binding_digest`.

The parallel independent static reviewer supplied a read-only in-memory probe at
this exact source: `accepted=true`, with all five wrong-identity variants accepted
for wrong `job_id`, `source_head`, `execution_head`, `input_revision_id`, and
`input_head` after recomputing a valid self-hash. The integrator independently
confirmed the missing comparisons in the committed source. This does not alter
the authoritative economic ledger, but it breaks the documented exact result
linkage and allows evidence returned by GET to be attributed to the wrong job or
calculation identity. It is therefore a P1 evidence-integrity blocker.

The earlier issued-context polymorphism and actual frozen OCO SL/TP findings were
statically closed in `82cb044e...`. Conservative PID-reuse liveness is retained
as a P2 limitation and is not expanded into this ticket.

## Executed validation

All pytest commands used the canonical registered-main virtual environment with
`PYTHONUTF8=1`, `-B -X utf8`, `-p no:cacheprovider`, and a unique external
`--basetemp`.

1. Handoff validation, ancestry, exact Git-object SHA-256 verification, and
   scoped dirty checks: passed as recorded above.
2. First B run:
   `tests/contracts/test_candidate_offline_access.py tests/cli/test_candidate_offline_cli.py`
   produced `9 passed, 1 failed, 3 warnings in 53.83s`. The only failure was
   `MODULE_NOT_FOUND: esbuild` because the sparse worktree did not contain
   `frontend/node_modules`; no business assertion failed.
3. The worktree then used a read-only junction to the registered-main canonical
   `frontend/node_modules`; no package install or write to the main tree occurred.
   The same complete B command passed: `10 passed, 3 warnings in 49.80s`.
   This covers default-off and read-only denials, local Host/Origin/auth,
   opaque identifiers, GET side-effect boundaries, CLI loopback, and the four
   Node SSR selector/contract checks. It is not browser visual QA.
4. `node <canonical frontend/node_modules>/typescript/bin/tsc --noEmit -p frontend/tsconfig.json`:
   exit `0`.

After the first reproducible P1 was reported, the integration task stopped the
long matrix to avoid wasting approximately 40 minutes on a candidate already
blocked. The following were not run in this integration attempt:

- A: full `test_candidate_offline_entry.py` plus
  `test_registered_candidate_execution.py`;
- C: all four `test_candidate_offline_lifecycle.py` cases;
- D: package/runtime/inference, original candidate/strategy delivery, V0/V1,
  legacy Qlib/V3, and IOC/OMS compatibility selectors;
- full repository suite, compileall, production deployment, backend restart,
  canonical browser acceptance, real candidate/market qualification, annual
  replay, protection-trigger execution, and legal partial opening.

Producer-reported results for those groups remain producer evidence and are not
represented here as independent passing results.

## Ownership, next action, and safety state

Owner `super_developer` must bind stored result and decision projections to the
complete durable job/source/input/execution/account/runtime identity, add a
regression that rejects self-consistent wrong/stale projections, then publish a
new committed source and append-only superseding handoff. The same integration
ticket may resume failure-first validation of that new candidate. This review
does not create a new engineering ticket and does not prescribe a broader
redesign.

No business code, source schema, execution behavior, environment, launcher,
permission, service, artifact, or ledger was changed. No merge to main, push,
deployment, or backend/frontend service start was performed. No secret, external
network, broker, exchange, private, order, or live endpoint was accessed.

`demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`,
`real_order`, `transfer`, `withdraw`, `execution_permission`,
`runtime_worker_enabled`, and `runtime_observed` all remain false. The candidate
is rejected for this revision; the report and handoff do not unlock any gate.

## Governance evidence

Read: `AGENTS.md`, `.codex/agents/integrator.toml`, knowledge README,
non-negotiables, shared pitfalls, cross-agent coordination, delivery risk policy,
the source architecture/acceptance documents, and the
`quant-agent-preflight`, `quant-gate-evidence-review`, and
`quant-agent-handoff` skills. There is no separate
`docs/agent_playbooks/integrator_pitfalls.md`; the integrator role TOML and
cross-agent coordination contract supplied the role-specific rules. No raw
pitfall log was bulk-read.

Catalog hash:
`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.

Active IDs:
`GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001`.
