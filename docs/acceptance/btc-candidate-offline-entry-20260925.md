# BTC candidate offline entry acceptance

Ticket BTC-CANDIDATE-OFFLINE-ENTRY-20260925; role super_developer;
change_risk=unclassified. Independent acceptance/integration remains required via
INTEGRATE-BTC-CANDIDATE-OFFLINE-ENTRY-20260925. No main integration or deployment.
Base: 15b2ea256de08c37e5d6cf15f1d5d0ece4178221. Source commits/hashes will be
authoritatively listed in the append-only published handoff; this report is not a
promotion receipt. Main baseline: 9c1dac906f4b4527aa247d14f18497f56e9d8464.

## Business result and explicit limitation

Default bootstrap, explicit immutable source publication, authenticated HTTP and
thin CLI, one persistent job coordinator, stop/resume and exact existing-page
result links are implemented. Complete sealed SYNTHETIC inputs drive the actual
AlphaFactoryService, ResearchArchiveCatalog, ResearchDeliverySources,
DeliveryAccounts, DeliveryService and existing registered BTC offline runtime.
No permissive Sources/Accounts substitute establishes the entry acceptance.

Initial P1 public context replacement is rejected before economic construction;
the context is issued, exact-type, non-subclassable, immutable at its public
boundary and revalidated through unbound validation/forecast methods. This is
not a sandbox for malicious arbitrary Python or module modification.

The registered OCO now uses frozen candidate SL/TP/mark/price-reference semantics,
Decimal conversion and existing policy hash, bounds and price ticks. Missing or
unsupported TP/semantics blocks before runtime construction. The old Demo policy
and original Strategy/Portfolio/Risk/OMS/ledger algorithms were not changed.

PROTECTION EXECUTION IS NOT SUPPORTED by this Qlib registered adapter. The separate
donchian_historical_venue engine has that capability but was not migrated/copied.
Actual long/short OCO prices, restart and sampled SL/TP touch are tested. A touch
persists a blocker before subsequent economics, preserves position/fills/ledger,
and prevents advancing/retrying past the same event after restart. No synthetic
protection fill/cancel or forced flat is generated. Missing/ambiguous effective
protection also blocks. The observed facts are discrete samples, not evidence
that no intrainterval trigger occurred. This capability limit is architect-
approved for the entry ticket and is not reported as TP/SL fill acceptance.

## Ownership, scope and artifacts

Planner worktree: D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-btc-candidate-offline-entry-20260925.
Branch agent/super_developer/btc-candidate-offline-entry-20260925. Initial scoped
dirty=0. Resumed scoped dirty=7, all this ticket's prior work; subsequently 33
scoped dirty paths at the checkpoint, no overlapping writer or other dirty read,
rollback or overwrite. Ignored frontend/node_modules junction points at existing
canonical dependencies for TypeScript/SSR checks; no worktree frontend server.

Exact touch set is recorded in the architecture document. Responsibilities:

- bootstrap/config/access/router/CLI: explicit configuration, default-off local
  authentication and opaque-ref entrypoints, shared persistent use case.
- delivery index/sources/FactoryDeliveryReader/service: create-only publication,
  atomic explicit revisions, pinned old package recompilation; no latest fallback.
- offline inputs/store/service/views and offline_contract: server-only hash-bound
  inputs, identity/idempotency/reservations, event-boundary lifecycle, bounded
  projections and paged exact decision/economic references, not another ledger.
- registered application and account internal resolver: P1 trusted contexts,
  frozen OCO mapping, durable unsupported-trigger blocker and validated external
  state-path resolution; public account output continues to hide physical paths.
- CandidateDelivery/ResearchRunDetails and new small components/API: independent
  offline consent, disabled reasons, exact result selectors and truthful limits.
- dedicated tests and these two documents; append-only acknowledgement/handoff.

No production artifact/latest/manifest/ledger was rebuilt. Economic state and
source/model fixtures live only under unique pytest temporary directories. Their
source HEAD is the producer test HEAD, not current-main deployment evidence.
Repository-owned management SQLite is outside the worktree in those fixtures;
it is not committed. No real candidate was resealed, retrained or promoted.
Temporary tiny model fixtures are expressly synthetic; short-case model leaves
are changed using the library API BEFORE first seal, never by rewriting a real
model or an already reviewed source. Full-year and genuine-market validation are
not claimed. .01 min/max/lot and FOK stay unchanged; IOC .03 tests below are not
registered-candidate legal partial-fill acceptance.

## Original source checkpoint tests (82cb044ed; not correction reruns)

Working directory is the planner worktree. Python prefix for every pytest command:

```text
D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider
```

PYTHONUTF8=1. Counts below are individual runs/checkpoints, not additive totals.

1. tests/contracts/test_candidate_offline_entry.py -k review_p1:
   initial 5 failed/71.64s; after correction 5 passed/67.11s.
2. tests/contracts/test_candidate_offline_entry.py plus
   tests/contracts/test_registered_candidate_execution.py at first checkpoint:
   18 passed/1087.23s. Real registered two-model FOK/ledger/restart, duplicate
   event, durable-intent unknown and ledger-before-evidence crash, expiry/revoke,
   account/currency/input and pre-constructor denial, single runtime writer.
3. tests/contracts/test_candidate_offline_entry.py -k
   'actual_registered or unrepresentable or legacy_missing':
   10 passed, 5 deselected/402.98s. Long/short actual policy prices, 2 percent
   sampled adverse move versus 4 percent OCO (not disabling original 3 percent
   trailing policy), SL/TP touch→block, duplicate/restart preservation, missing/
   unsupported contract rejection. Protection fill execution is NOT a passing item.
4. tests/contracts/test_candidate_offline_access.py plus
   tests/cli/test_candidate_offline_cli.py plus
   tests/contracts/test_candidate_offline_entry.py -k 'not actual_registered':
   19 passed, 4 deselected/151.76s. Access/body/default-off/readonly/local auth,
   actual full app composition and SSR/selector contracts; exact P1 negatives.
   Later API query/result-integrity hardening: access+CLI 8 passed/49.11s.
5. tests/cli/test_candidate_offline_cli.py plus
   tests/contracts/test_candidate_delivery_api.py plus
   tests/contracts/test_strategy_delivery.py: 60 passed/77.74s. Original management
   and V2/V3 compiler behavior, currency/binding/expiry and local TCP CLI capability.
6. tests/contracts/test_candidate_package_runtime.py plus
   tests/integrations/test_candidate_package_inference.py: 53 passed/53.23s.
   Real tiny LightGBM/factor/policy evidence verification, immutable source and
   inference parity, content tamper/missing data/versions and no future inputs.
7. tests/integrations/test_candidate_offline_lifecycle.py first two-model run:
   2 passed/599.41s. Actual default bootstrap publication→review/bind/register→
   asynchronous HTTP job→result/fees/funding/ledger; same-key stable, second-job
   denial, GET no runtime reconstruction and new-service no auto restart.
   CLI same-key start/result over actual local TCP: one model passed/275.78s.
   Safe stop while position held, service restart and resume same job:
   1 passed/320.83s. Final expanded combined run: 4 passed/1116.63s,
   including CLI resume and authority-commit/projection-failure recovery.
   After close-before-terminal hardening, focused -k worker_crash -x:
   1 passed, 3 deselected/313.46s; no duplicate economics after same-job resume.
8. tests/contracts/test_strategy_v0_freeze.py,
   tests/contracts/test_strategy_v1_donchian_offline.py,
   tests/contracts/test_btc_okx_demo_adapter.py::test_partial_fill_drill_opt_in_allows_only_0p03_ioc_opening,
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_fill_order_plan_uses_one_ioc_entry_with_0p03_cap,
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_entry_truth_requires_matching_order_fill_position_and_oco,
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_entry_truth_rejects_duplicate_fill_identity_before_deduplication,
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_reconciliation_covers_order_fill_position_oco_ledger_and_ws,
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_fok_partial_fill_enters_risk_reducing_only,
   tests/contracts/test_btc_paper_oms_lifecycle.py,
   tests/contracts/test_btc_paper_oms_session_reconciliation.py:
   51 passed, 1 skipped/33.88s. V0 archived-data opt-in unchanged; no live drill CLI.
9. node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json:
   exit0. SSR test bundles frontend/e2e/candidate-offline.spec.ts with esbuild and
   Node test runner, checking exact selectors, legacy links, mismatches, default-
   disabled controls and truthful unbound result. This is NOT browser visual QA.
10. py -3 -B -m compileall -q on the declared Python paths; scoped git diff
    --check: exit0 (only normal Git LF/CRLF conversion warnings).
11. Final expanded access+CLI + tests/integrations/test_qlib_candidate_policy.py
    + tests/contracts/test_strategy_v3_qlib_offline.py: 36 passed/493.89s.
    Includes store integrity/reservation/idempotency, malformed query/timestamp/
    input hash, full legacy sealed 1392 predictions and zero-fill behavior,
    nonzero long/short original policy, unknown intent and economic recovery.
12. Final access+CLI regression: 10 passed/76.61s; subsequent TypeScript
    --noEmit exit0. Only dependency deprecation warnings remain.

Failures preserved: initial five P1 reproductions; external directory '.' rejection
(fixed without accepting traversal); first entry timeout at 240s (no completion
claim, final window increased to 600s and status polling reduced from 50ms to 500ms);
protection blocker not restored by controller reconstruction (fixed via exact
durable event/input identity); synthetic short model text-size corruption caused
LightGBM process abort (fixture fixed using set_leaf_output/model_to_string before
first seal; all ten targeted tests subsequently passed); initial TS prop/event
types fixed. No invalid/aborted/old-ticket run is counted as current success.

## Remaining gates, owners and next action

Read AGENTS, super_developer role, knowledge README/nonnegotiables, shared and
super_developer playbooks, delivery_risk_policy, data reliability, research/
execution/architecture rules and quant-agent-preflight/handoff. Team Context is
discovery-only; upstream handoff was validated before consumption. No raw pitfall
log bulk loading. Catalog hash:
6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af.
Active IDs: GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,
GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,
GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001.

Independent integrator owns final review of combined upstream+this source and
shared contracts. Data/source owner must supply qualifying real frozen candidate
and observation evidence; no fake substitute enables them. Deployment owner needs
separate authorization/current-main identity acceptance and canonical 3000 browser
QA. Protection execution remains an explicit unsupported capability; this ticket
does not automatically open a venue-migration ticket. The full suite, production
deployment, real credentials, actual private/broker/order endpoints, real candidate
training, annual replay, and browser visual QA were NOT run.

## Same-ticket P1 identity correction after independent rejection

Correction base c3a6fb0bd4e06ebcfa8e42b0090617796f5f729a. Original source 82cb044ed
was rejected for incomplete result identity; it is NOT independently accepted.
Review consumed only from committed report 47a2dca48 and rejected handoff c0471225,
official validate_handoff plus validate_handoff_against_git returned valid=true.
No integrator-private/uncommitted file was consumed or copied.

This correction's initial scoped dirty=0; single business writer; same planner
worktree/branch and change_risk=unclassified. Narrowed touch set:

- backend/app/services/candidate_offline_service.py and candidate_offline_views.py:
  server sealing, immutable updates, resume checks, result/decision authority binding.
- quant_shared/strategy_delivery/offline_contract.py: complete canonical identity.
- frontend/src/workspaces/research/candidate-offline-api.ts and
  RegisteredCandidateOfflineEvidence.tsx: matching identity contract and display.
- tests/contracts/test_candidate_offline_access.py,
  tests/integrations/test_candidate_offline_lifecycle.py,
  frontend/e2e/candidate-offline.spec.ts: negative identity and recovery assertions.
- This acceptance report, the matching architecture document and this ticket's
  append-only handoff directory.

The sealed identity has 15 stable fields plus its schema and digest, covering
job/registration/package, binding/account/runtime/state, input revision/digest/head/
kind, source/execution heads and catalogue SHA. Job/result/decision envelopes v2
require exact identity equality and recomputed canonical digest against the stored
job, not only an evidence self-hash. Every returned decision page is checked.
The frontend compares all identity fields/digest with the job. Worker mutation,
changed-identity resume and old/incomplete records reject; no old evidence or
economic ledger is rewritten. Mutable progress and deployment HEAD are not sealed.

Current correction commands use the same pytest prefix above:

1. tests/contracts/test_candidate_offline_access.py -k identity, failure-first:
   33 failed, 7 passed, 9 deselected/174.25s. Wrong identity was accepted even with
   result/record/identity SHA values consistently recomputed. This is preserved
   as failure evidence, not counted as success.
2. tests/contracts/test_candidate_offline_access.py tests/cli/test_candidate_offline_cli.py:
   50 passed, 3 dependency-deprecation warnings/255.44s. Includes all 40 original
   identity regressions, default-off/research_readonly denial, local authentication,
   CLI loopback and five Node SSR/identity tests. The two later supplemental cases
   are separately reported below; counts are not presented as one suite execution.
3. tests/contracts/test_candidate_offline_access.py -k
   'complete_cross_job or resume_rechecks':
   2 passed, 49 deselected/16.30s. Complete cross-job swaps, top-level alias-only
   mutation, legacy records and rehashed changed binding refuse without dispatch
   or resealing the original job.
4. tests/integrations/test_candidate_offline_lifecycle.py -k
   'worker_crash or stop_at_committed' -x: already running when independent
   review requested reduced duplicated long tests; completed normally:
   2 passed, 2 deselected, 3 dependency warnings/482.71s. Held-position stop,
   actual loopback CLI resume and ledger-commit/projection-failure same-job
   recovery preserve all 15 identity fields and digest across service restart,
   result and paged decisions; original first fill survives with two final fills,
   not three, and original ledger reconciles. No duplicated economics.
5. node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json:
   exit0. No browser server or canonical visual acceptance.
6. py -3 -B -m compileall -q on the five touched Python files; scoped git diff
   --check: exit0. Only normal LF/CRLF conversion warnings.

The full four-case lifecycle, original P1 issued-context/frozen protection matrix,
package/inference/V0/V1/V2/Qlib/IOC/OMS long matrices and full repository suite have
NOT been rerun for this correction. Their earlier counts above remain historical,
not new-revision independent evidence. The existing independent integrator owns
the final committed-source full lifecycle/recovery review. No new ticket is opened.
P2 PID reuse conservative liveness is documented only; no availability repair.
Actual protection-trigger fill execution stays unsupported and sampled touch
remains durably blocked. No strategy, risk, OMS, ledger or trading permission change.

The same playbooks/active IDs/catalog hash listed above were refreshed; no raw
pitfall log bulk-read. No production artifact/manifest/runtime/ledger rebuild,
real source qualification, environment change, deployment or backend restart.
Synthetic state is test-only, from pre-commit producer HEAD, never current-main
promotion evidence. Independent acceptance and all existing external gates remain
blocked; no other agent's unmerged changes were integrated.

All deployment safety flags remain false: demo_control_enabled,promotion,paper,
live,private,order,real_order,transfer,withdraw,execution_permission,
runtime_worker_enabled,runtime_observed. Offline job progress is separately named
offline_job_executed. Candidate records and synthetic jobs are not promotion,
paper/live or real-account evidence. No merge, push, service restart or enablement.
