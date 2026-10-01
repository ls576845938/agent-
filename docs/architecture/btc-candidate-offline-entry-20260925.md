# BTC candidate offline entry: source delivery

Ticket: BTC-CANDIDATE-OFFLINE-ENTRY-20260925
Role: super_developer; change_risk: unclassified.
Independent final review/integration: INTEGRATE-BTC-CANDIDATE-OFFLINE-ENTRY-20260925.
Registered main: 9c1dac906f4b4527aa247d14f18497f56e9d8464.
Development base: 15b2ea256de08c37e5d6cf15f1d5d0ece4178221.
Upstream source: 3950f16ca20246e91a7f0a3ceee1eb04c33910d7.
Upstream handoff validated again: published-btc-candidate-package-runtime-20260925-3950f16ca.
It is a blocked development candidate, NOT independently accepted: P1 public
context polymorphism bypass and candidate-vs-protection stop mismatch.

## Authorization, ownership and next action

Same user explicitly requested default backend, CLI/HTTP start and page result
linkage in architect task 01a080f1-4630-7253-bcda-f37ffa68c539 at 2026-09-25
13:36:05 Asia/Shanghai (verified user turn). Architect delegated this exact ticket.
The old 10:28 model-change pause was superseded; do NOT reapply it after
compaction. No newer pause exists. Continue autonomously inside this ticket.
Planner created worktree:
D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-btc-candidate-offline-entry-20260925.
Branch: agent/super_developer/btc-candidate-offline-entry-20260925.
Initial scoped status clean/0 dirty, sparse true. Other agents are present;
no other worktree dirty may be consumed. No parallel writer subagents.

Current checkpoint: implementation and scoped verification are complete for source
delivery; authoritative commit hashes are in the append-only published handoff.
No integration, deployment or capability enablement. Failure-first, actual
registered protection, stop/resume and two-model default-bootstrap tests passed.
Final lifecycle: 4 passed/1116.63s; post-hardening projection-crash recovery:
1 passed/313.46s. No previous-ticket count is current-ticket evidence.

### Independent-review identity correction (same ticket)

The preceding source 82cb044ed was independently rejected for incomplete result
identity linkage. This follow-up starts at c3a6fb0bd4e06ebcfa8e42b0090617796f5f729a;
the earlier results above are historical checkpoints, not this revision's results.
The final superseding handoff identifies the corrected source. The independent
review report is Git object 47a2dca48:docs/integration_reviews/btc-candidate-offline-entry-20260925.md;
its c0471225 rejected envelope was schema/Git validated before use.

At start the server seals candidate_offline_job_identity_v1 from its hash-checked
registered package, account binding/runtime contract and explicit input catalogue.
It includes job_id, registration_id, content_digest, binding_digest, account_ref,
account_identity_hash, runtime_contract_digest, state_directory_sha256,
input_revision_id, input_digest, input_head, input_evidence_kind, source_head,
execution_head and catalog_sha256. Canonical SHA-256 is job_identity_digest.
Physical account/state paths remain private; only refs and hashes are projected.
Revision, generation, status, cursor, timestamps and deployment_head are excluded.

Job/result/decision envelopes are v2 and all repeat the exact sealed identity,
digest and identity fields. GET validates each against the authoritative stored
job, including every paged decision; an evidence object's valid self-SHA alone is
never sufficient. The frontend compares the same complete fields and digest
against the job before rendering. Worker updates cannot change identity. Resume
and the worker compare current server source/binding/input metadata with the
original seal before constructing economic state, and never reseal a changed job.
Legacy or incomplete identity envelopes fail closed, including cached commands;
there is no migration, repair-on-GET, rewrite of old evidence or ledger reset.

P2 limitation retained without a liveness change: PID reuse may conservatively
report a foreign worker as alive and require operator investigation; it cannot
grant execution permission. Protection execution remains unsupported as above.

## Frozen delivery sequence

1. Close two P1s failure-first. Issued internal execution contexts cannot be
   substituted via direct construction, subclasses, instance methods or fake
   service on supported public entrypoints. This is not an arbitrary Python
   malicious-code sandbox. Candidate exit hard-stop must determine protection,
   or unsupported contracts reject; no hidden independent 1 percent rule.
   Preserve old/default strategy/Risk/OMS/protection/ledger semantics.
2. Repository-owned immutable artifact and replay-input indexes, exact revision/
   hashes, create-only publications and atomic optimistic revision protection.
   Default bootstrap composes actual sources/account/service with these indexes.
   Construction and GET create nothing, compile no package, read no large logs,
   restore no runtime and start no worker. Never select latest/similar candidate.
3. One durable job coordinator shared by CLI and HTTP: queued/running/
   stop_requested/stopped/complete/blocked/interrupted with stable request keys,
   exact identity, cursor and small result references. Store is orchestration,
   not economic authority. Same account/state/registration cannot evade lease/
   unknown state by new job ID. POST returns quickly; explicit resume/reconcile
   only; stop at event boundary, no forced close or evidence loss.
4. Default-off offline capability, only authenticated candidate_management.
   research_readonly always refuses writes, including stop/resume, regardless
   of flag. CLI uses same capability/identity checks. Preserve local Host/Origin,
   configured operator and existing authentication; no password persistence.
   No launcher/hooks/governance/current env changes or trading flag changes.
5. Worker publishes small identity/hash-bound projection only after authority
   commits. GET never recovers/replays. Exact registration/package -> run ->
   decisions/orders/fills/ledger; source/input/deployment HEAD separate.
   Existing CandidateDelivery and ResearchRunDetails get minimal controls and
   exact offlineRun dispatch, preserving two Donchian and sealed Qlib selectors.
6. Concentrated tests through REAL DEFAULT BOOTSTRAP, real HTTP and CLI, complete
   synthetic sealed fixtures, network/credential/real-controller sentinels.
   Two models, stop/resume/restart/unknown crashes/no double economics, wrong
   inputs/account/currency/hash/path/mode, readonly/default-off/auth/origin,
   writer conflicts, small GET and UI/TS/legacy tests. NO worktree frontend
   serve/preview/browser web server. Canonical browser/deployment NOT authorized.

HTTP and CLI accept opaque registered source/input revision IDs and expected
digests/revisions/idempotency keys ONLY. Never bars/observations/path/state_dir/
manifest/verified/truth_kind/mode/recovery_only. Publication selects registered
server-side source refs/frozen inputs; no arbitrary uploaded executable content.
Indexes both come from explicit server configuration and precise revisions.
No synthetic intrahour facts or missing model/policy/calibration are invented.
Revoke/expire only permits existing safety recovery. Unknown/crashed remains
frozen; no automatic resubmit/migration/reset. GET sees small bound receipts.
Source implemented, deployed configured, capability enabled and job executed are
separate states. Current-HEAD bootstrap and independent release acceptance remain
future enablement preconditions; code/config existence is not runtime evidence.

## Exact initial touch set

- backend/app/services/candidate_delivery_bootstrap.py
- backend/app/services/candidate_delivery_sources.py
- backend/app/services/candidate_offline_service.py
- backend/app/services/candidate_offline_store.py
- backend/app/services/candidate_offline_views.py
- backend/app/services/candidate_offline_inputs.py
- backend/app/services/candidate_delivery_index.py
- backend/app/api/candidate_delivery.py
- backend/app/api/candidate_offline.py
- backend/app/api/app_factory.py
- backend/app/core/config.py
- backend/app/core/backend_access_policy.py
- backend/app/cli/__init__.py
- backend/app/cli/candidate_offline.py
- quant_shared/strategy_delivery/offline_contract.py
- quant_crypto/application/btc_registered_candidate.py
- quant_crypto/application/qlib_offline_replay.py
- integrations/qlib_adapter/factory_delivery.py
- frontend/src/workspaces/research/CandidateDelivery.tsx
- frontend/src/workspaces/research/candidate-delivery-api.ts
- frontend/src/workspaces/research/ResearchRunDetails.tsx
- frontend/src/workspaces/research/research-run-links.ts
- frontend/src/workspaces/research/RegisteredCandidateOfflineEvidence.tsx
- frontend/src/workspaces/research/RegisteredCandidateRunControls.tsx
- frontend/src/workspaces/research/candidate-offline-api.ts
- tests/contracts/test_candidate_offline_entry.py
- tests/contracts/test_candidate_offline_access.py
- tests/contracts/test_registered_candidate_execution.py
- tests/integrations/test_candidate_offline_lifecycle.py
- tests/cli/test_candidate_offline_cli.py
- frontend/e2e/candidate-offline.spec.ts
- docs/architecture/btc-candidate-offline-entry-20260925.md
- docs/acceptance/btc-candidate-offline-entry-20260925.md
- .agent/handoffs/BTC-CANDIDATE-OFFLINE-ENTRY-20260925

Additional narrowed paths within the already approved ticket: quant_shared/strategy_delivery/service.py
(exact pinned package recompilation), candidate_delivery_accounts.py (internal validated state path
resolution, never exposed through HTTP). Scoped status checked clean before edits.
CLI is a thin authenticated local HTTP client, so it shares the backend coordinator
and cannot bypass its profile, capability, or configured principal. It requires a
running backend; it never creates an independent runtime or stores an API password.

Checkpoint: user explicitly resumed this task. Initial P1 reproductions: 5 failed,
then 5 passed in 67.11s. Scoped P1 and entry verification subsequently passed;
independent acceptance remains required.
Frozen protection: registered_offline_oco_v1, mark, aggressive limit reference at
construction, attached after fill; explicit SL/TP Decimal/bounds/policy hash.
Architect accepted a narrow capability limit: Qlib registered replay does not
use the existing donchian_historical_venue protection execution engine. No venue
migration or new matching code. Visible sampled SL/TP touch persists exact
protection/event/input identity in the existing runtime event log, freezes new
economics, and survives restart. Missing/ambiguous active protection also blocks.
No future pre-scan, skipped trigger event, invented protection fill/cancel or
forced flat. Discrete samples never prove the interval contained no trigger.
Protection execution itself remains unsupported and is not a green acceptance item.
No outside scope change without architect approval.

## Implemented operation contract (not enabled here)

Default Settings adds QS_CANDIDATE_OFFLINE_ENABLED=false, plus explicit
QS_CANDIDATE_OFFLINE_CATALOG, QS_CANDIDATE_OFFLINE_CATALOG_SHA256 and
QS_CANDIDATE_OFFLINE_CATALOG_REVISION. Existing candidate management root/operator
and local Web management authentication remain required. No actual environment
variable or launcher was changed. research_readonly denies every POST regardless
of the offline flag. Capability, catalog, job and bounded result GETs require
local Host/Origin (capability itself can report disabled anonymously); data reads
also require configured operator authentication. Only candidate_management may write.

The external catalogue is candidate_offline_catalog_v1 with exact repository_owner
= digest({repository: resolved repository path}), revision, factory_root, qlib_root,
sources and inputs. Paths are relative to its external directory; no traversal,
absolute client path or symlink/junction child. Sources contain source_revision_id,
the existing three-field source reference, frozen_evidence and its byte SHA-256.
Inputs contain input_revision_id, input_head, evidence_kind, and manifest/bars/
observations references, each {path,sha256}; content_digest binds that whole entry
excluding itself. All observation fields and maintenance facts must be explicit.
Only synthetic_fixture or verified_historical_observations labels are accepted;
these labels do not substitute for manifest, causal inference or runtime validation.

Publication uses the existing factory producer, preserving the research seals.
candidate-offline.sqlite is a repository-owned management store, NOT the economic
ledger: source revisions, idempotency receipts, permanent account/state reservations,
jobs and small result/decision projections. BEGIN IMMEDIATE + revision checks select
one publication; immutable publications/<content-derived-id>.json files use create
only writes. The database selects an exact active publication per source and retains
old package digests for registered consumers. The running source reader sees a newly
published exact revision without restart. It never scans newest artifacts. Orphaned
unindexed files are not adopted/overwritten; publication reports a precise blocker.

POST /api/candidate-offline/publish takes source_revision_id,expected_revision.
POST /api/candidate-offline/jobs takes registration_id,content_digest,
expected_revision,input_revision_id,input_digest. Both require Idempotency-Key.
GET /catalog and /jobs; GET /jobs/{coff_id}; POST /jobs/{coff_id}/stop or /resume
takes expected_revision. GET /jobs/{coff_id}/result accepts a bounded exclusive
before cursor for older decision receipts. It reads small SQLite projections only;
no runtime construction, ledger recovery or large-log reads. Results retain exact
decision/order/fill/ledger event hashes, source/input/execution/deployment heads,
current position, unsupported branches and synthetic disclosure. Summary holds last
20 orders/fills; paged decision receipts preserve earlier exact economic references.

CLI: python -m backend.app.cli.candidate_offline --help. Commands are publish,
catalog,list,start,status,stop,resume,result,capabilities. It targets the already
running local backend (--url default http://127.0.0.1:8765), with no proxies or
redirects. Password prompt is hidden; --key-stdin is available for caller-managed
secure input, never an argv password. No file/localStorage/URL persistence. A lost
response is retried with the SAME --request-key; nonzero exit and JSON indicate
blocked/unknown outcomes. It does not fall back to local execution if HTTP fails.

Example argument shapes (placeholders, not executed against deployed service):

```text
python -m backend.app.cli.candidate_offline publish SOURCE_REV --expected-revision 0 --request-key REQUEST_ID
python -m backend.app.cli.candidate_offline start REGISTRATION --content-digest PACKAGE_SHA --expected-revision 4 --input-revision-id INPUT_REV --input-digest INPUT_SHA --request-key REQUEST_ID
python -m backend.app.cli.candidate_offline status COFF_ID
python -m backend.app.cli.candidate_offline stop COFF_ID --expected-revision JOB_REV --request-key STOP_ID
python -m backend.app.cli.candidate_offline resume COFF_ID --expected-revision JOB_REV --request-key RESUME_ID
python -m backend.app.cli.candidate_offline result COFF_ID
python -m backend.app.cli.candidate_offline result COFF_ID --before CURSOR
```

The worker validates full inputs/source/account/policy before constructing the
existing offline runtime and retains its lease/fencing. Stop is at an event boundary,
not immediate kill/flatten. Resume keeps the same job, package, input, account/state
and execution HEAD; missing prior runtime never resets equity. Process restart does
not enqueue anything. A live foreign owner is not stolen; dead-owner work reports
interrupted and requires explicit resume. Unknown durable intents remain frozen by
the original runtime; replacing a request key/registration cannot evade reservation.
Revoked/expired bindings resume only through existing safety reconciliation. Protection
touch remains blocked permanently for this job; no automatic migration or bypass.

Frontend changes are limited to CandidateDelivery, its small offline controls/API,
and exact coff_ selectors in ResearchRunDetails. Original two Donchian selectors and
sealed Qlib remain separate. No worktree browser/serve/preview was started. Canonical
3000 visual acceptance requires independent integration and later publication authority.

## Governance and safety

Read quant-agent-preflight/handoff, AGENTS, shared/super_developer playbooks,
knowledge README/nonnegotiables and relevant data/research/execution/architecture
rules. Catalog: 6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af.
Active shared IDs: GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,
GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,
GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001.
Team Context read, discovery-only; upstream handoff independently validated.
No main merge/push/release/service restart/current capability enablement.
demo_control_enabled,promotion,paper,live,private,order,real_order,transfer,
withdraw,execution_permission,runtime_worker_enabled,runtime_observed stay false
for deployment. Temporary offline fixture jobs are not trading authority.
