# Candidate management deployment source acceptance

Ticket CANDIDATE-MANAGEMENT-DEPLOY-20260926; role super_developer;
change_risk=unclassified. Base 8821b04e599812429d5034c126493379209c59b5.
Planner branch agent/super_developer/candidate-management-deploy-20260926;
worktree D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-candidate-management-deploy-20260926.
Source/derived identity/handoff commit hashes are authoritative in the append-only
handoff. Independent integration and canonical deployment acceptance are pending.

## Ownership and scope

Initial scoped dirty=0. The two subsequently authorized frontend paths were also
clean before editing. No other writer's dirty file was read, consumed, reset or
overwritten. Main business source remains frozen. Worktree stays sparse; quant_crypto
and quant_cn were added as read-only import dependencies, not edited; no full
checkout. Canonical frontend node_modules junction is dependency-only, no install.

- scripts/start_backend_current_main.ps1 / .py: accept only the additional management
  profile, fail closed on Demo/fixture and missing config/auth. Preserve main HEAD,
  registered worktree, sparse/clean, 127.0.0.1:8765 and listener/concurrency guards.
- scripts/candidate_management_deployment.py: one scoped empty deployment prepare/
  read-only check/formal-entry delegation, no alternate server or permission API.
- backend/tests/test_backend_current_main_launcher.py: concentrated launcher,
  metadata integrity, missing auth/config, empty bootstrap/GET and command tests.
- frontend/src/workspaces/crypto/workspace-access.ts and
  frontend/scripts/test-btc-readonly-workspace.mjs: architect-authorized direct
  compatibility for management BTC research-only display; no controls or new layout.
- frontend/public/frontend-identity.json: only existing identity:refresh output
  after final source commit, no manual identity field edits.
- docs/operations/candidate-management-deployment-20260926.md, this report and
  .agent/handoffs/CANDIDATE-MANAGEMENT-DEPLOY-20260926/: procedure and evidence.

No governance or backend permissions/API/Strategy/Risk/OMS/ledger edits. The
existing integrated-btc-candidate-offline-entry-20260925-0e0a442ce handoff validated
as valid before use. Its 214-pass/1-skip business matrix is prior independent
evidence, not a test count rerun by this ticket.

## Verification (producer; not running deployment)

Working directory is this worktree. Pytest prefix:
`PYTHONUTF8=1; D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider`.
Temporary configs/accounts are explicitly empty and external, no synthetic
candidate/market/economic fixtures copied. No real secret read or printed.

1. Exact-base Git blob in-memory reproduction: both original PS1 and Python
   reject candidate_management with backend_evidence_profile_invalid. No old
   source restored over working files. First attempted pytest collection was
   blocked by missing quant_cn; dependency added to sparse, not counted as a pass.
2. New management-profile guard subset: 5 passed/16.00s.
   After the final non-secret preparation status label, the complete management
   subset was rerun: 20 passed, 29 deselected/10.87s.
3. Full backend/tests/test_backend_current_main_launcher.py: first
   48 passed, 1 failed/16.10s because the new empty-GET fixture lacked fake Git
   metadata; adjusted only fixture HEAD provider. Final 49 passed/29.23s,
   one existing Starlette deprecation warning. Covers original profiles, main
   identity/sparse/dirty/port/listener/writer guards and actual PowerShell profile
   block execution; create-only/idempotent empty preparation; root/owner/hash/
   revision/missing metadata; no-secret output/delegation; real default composition
   and authenticated GET leave external files byte-for-byte unchanged/no SQLite.
4. node frontend/scripts/test-btc-readonly-workspace.mjs:
   added management assertion failed first (unavailable/publicMarket=false);
   corrected run reports original console/tester/hook compatibility passed.
   Management flags are strict; Demo actions/refresh/polling remain disabled.
5. node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json:
   exit0 (same command cell after successful BTC readonly script).
6. Frontend identity test initially failed manifest_match at the stale manifest,
   as expected before final source commit + derived refresh. Final frontend source
   commit 3179541b8f362ebd0baf3b6c0cf5b7fb82a1b3ca was then used by the existing
   npm.cmd run identity:refresh (no manual manifest edit). Final fingerprint:
   70eb61d16d156eb36f2c33c4f42858c3c3483b7c96f2979df59347ae4ca7df1c.
   node frontend/scripts/check-frontend-identity.mjs passes manifest_match and
   baseline_ancestor; canonical=false correctly identifies this producer worktree.
   Full node frontend/scripts/test-frontend-identity.mjs passes its in-worktree
   checks but exits1 at line257: Windows canonical PS1 -Check delegates to unchanged
   main, whose old frontend manifest rejects with fingerprint_or_object_ids_mismatch.
   This remains an explicit pre-merge canonical deployment blocker, not a passing
   full identity test. Do not bypass or change registered main from this producer.
7. py -3 -B -m compileall -q scripts/start_backend_current_main.py
   scripts/candidate_management_deployment.py backend/tests/test_backend_current_main_launcher.py:
   exit0. Scoped diff --check and staged diff --check: exit0.

Full 214-case business matrix, network/exchange/private/order calls, credentials,
production external directory preparation, formal service startup or restart,
canonical page/browser acceptance and actual capability enablement were NOT run.
Prepared-empty/configuration-checked is not authenticated/running/candidate-ready.
The root session reports actual QS_WEB_API_KEY is absent; this producer has not
read its value or modified User/Machine environment. Human local authentication
is still a deployment blocker, not an excuse to stop this source delivery.

## Governance, gates and next owner

Read AGENTS, super_developer role, knowledge README/nonnegotiables, shared and
super_developer playbooks, preflight/handoff skills; refreshed context with
change_risk unclassified. Team Context discovery completed with invalid/blocked
historical deliveries, not consumed as acceptance; explicit upstream validated.
Catalog hash 6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af.
Active IDs: GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,
GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,
GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001.
No raw pitfall log bulk-read. Main and other worktrees not modified.

Independent integrator owns source/derived identity validation and approved merge;
root operator owns secure authentication, actual external preparation and formal
launch/listener/current-main identity/browser acceptance. See operations document
for exact startup, check, stop and non-destructive rollback instructions.
No production artifact/manifest/ledger rebuilt; frontend manifest is a source
fingerprint only, not proof of current-main serving freshness. Other agents'
unmerged changes were not integrated.

Readiness ceiling quality_checked; gate remains blocked pending independent
acceptance/deployment. PID reuse conservatism, real candidate/input quality,
unsupported protection fills/registered partial opening are retained limits,
not additional work tickets. promotion,paper,live,private,order,real_order,
transfer,withdraw,execution_permission,runtime_worker_enabled,runtime_observed
and demo_control_enabled remain false for this delivery.
