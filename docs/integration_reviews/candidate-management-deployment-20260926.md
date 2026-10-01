# Candidate management deployment independent integration review

## Decision and identities

Decision: **validated source-integration candidate, quality_checked**. No P0/P1 was
found in the approved deployment touch set. This review does not merge `main`,
start either service, provision authentication, import a candidate, run an
offline job, or unlock promotion/paper/live.

- Ticket: `INTEGRATE-CANDIDATE-MANAGEMENT-DEPLOY-20260926`
- Change risk: `unclassified`; strict independent-integrator path retained.
- Approved base / current `main` during review:
  `8821b04e599812429d5034c126493379209c59b5`
- Producer source: `3179541b8f362ebd0baf3b6c0cf5b7fb82a1b3ca`
- Derived frontend identity deliverable:
  `9dc28c7f5643369fe24bf3c6d566f30942c0463b`
- Published handoff HEAD / frozen review HEAD:
  `d3a3a8f4b40a18d123468ab9bd7b2a542d25d4c0`
- Planner branch: `agent/integrator/integrate-candidate-management-deploy-20260926`
- Planner sparse worktree:
  `D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-candidate-management-deploy-20260926`
- Initial and pre-report dirty state: clean on every approved source path and
  this integration ticket's report/handoff paths. No overlap or conflict was
  found. The approved history was consumed by `git merge --ff-only d3a3a8f4...`,
  preserving `3179541b8...` as the frontend identity baseline ancestor.

The producer envelope
`.agent/handoffs/CANDIDATE-MANAGEMENT-DEPLOY-20260926/published-candidate-management-deploy-20260926-9dc28c7f5.json`
passed both `validate_handoff` and `validate_handoff_against_git` with zero
errors. All nine deliverable hashes match Git. Base -> source -> derived ->
handoff ancestry is continuous. The approved source has nine deliverable paths;
the tenth changed path is the published handoff itself. `git diff --check`
passed. No backend application permission, Strategy, Risk, OMS, fill, ledger,
private/order/live, governance, or environment file changed.

## Independent source review

- Both official backend launcher layers accept only the added
  `candidate_management` profile and retain the registered-main, sparse/clean,
  loopback `8765`, current-HEAD, listener identity and fixture guards.
  Management requires `QS_BTC_DEMO_CONTROL_ENABLED=false`; Demo construction and
  the Demo writer lock remain outside this mode.
- The Python runtime identity revalidates the candidate configuration before
  launch and on runtime binding. Identity and health retain
  `read_only=true`, `controls_disabled=true`, and false paper/live/order flags.
  Existing listeners must match both current HEAD and the exact evidence
  profile.
- `candidate_management_deployment.py` creates only owner metadata, an existing-
  schema empty catalog, an existing-schema empty account descriptor, a nine-key
  non-secret config and empty factory/qlib directories. It rejects repo/worktree,
  root, symlink/junction, owner, hash, revision, missing metadata and conflicting
  existing-file cases. It never persists or prints `QS_WEB_API_KEY`, reads no
  User/Machine credential, and delegates check/start to the official PowerShell
  launcher rather than invoking Uvicorn itself.
- An empty valid catalog/accounts descriptor is a truthful waiting-for-import
  state. `offline_enabled=false` is the preparation default. Enabling the
  capability remains an explicit operator choice and does not create any
  runnable candidate or waive start-time identity, binding, input or account
  checks.
- `candidate_management + read_only=true + controls_disabled=true` maps the BTC
  page to the existing research-readonly display: public market view/ticker/
  stream remain enabled, Demo runtime remains false, all console controls remain
  disabled and the layout is unchanged. Missing or inconsistent mode flags still
  map to unavailable.
- Frontend identity was generated after producer source commit `3179541b8...`.
  Its baseline is an ancestor of the frozen handoff HEAD and the inspected
  fingerprint is exactly
  `70eb61d16d156eb36f2c33c4f42858c3c3483b7c96f2979df59347ae4ca7df1c`.

No blocking defect was found. One non-blocking operational limitation remains:
the generic listener identity binds HEAD and profile but not a digest of the
external candidate configuration. The current first deployment changes the old
listener's profile, so the official launcher rejects reuse. For any later
same-HEAD/same-profile configuration change, the operator must verify and
restart the owned listener; `already_running` alone is not evidence that a new
external root/catalog/operator configuration was adopted. This limitation does
not authorize a new source contract in this ticket.

## Independent commands and results

All Python tests used canonical `.venv` Python with `PYTHONUTF8=1`, `-B -X utf8`,
`-p no:cacheprovider`, and a unique external `%TEMP%` basetemp.

1. `backend/tests/test_backend_current_main_launcher.py`: **49 passed**, one
   existing Starlette/httpx deprecation warning, 18.37 seconds. This includes the
   real PowerShell profile guard, configuration/authentication failures,
   create-only preparation, empty GET/no-write behavior, main/listener/runtime
   identity and all older launcher profiles.
2. `tests/contracts/test_candidate_delivery_api.py` plus
   `tests/contracts/test_candidate_offline_access.py`, limited to the approved
   management-policy, no-Demo construction, fresh-process import, default-off,
   local-auth, opaque-field, precise allowlist and real-router selectors:
   **10 passed, 69 deselected**, one existing warning, 44.40 seconds.
3. `node frontend/scripts/test-btc-readonly-workspace.mjs`: **exit 0**; existing
   console/tester SSR and hooks remained intact, candidate management used only
   public research endpoints, and actions remained disabled.
4. `node .../typescript/bin/tsc --noEmit -p frontend/tsconfig.json`: **exit 0**.
   The first attempt without a local worktree `node_modules` failed only because
   ESM packages and Node types were unavailable. The successful rerun used the
   canonical installed dependencies through a read-only module loader/baseUrl;
   no dependency, source or main-worktree file was changed.
5. `node frontend/scripts/check-frontend-identity.mjs`: **passed** with
   `manifest_match=true`, `baseline_ancestor=true`, expected `canonical=false`
   in the isolated integrator branch, and the exact fingerprint above.
6. `python -m compileall` on the two launcher/helper Python files and launcher
   tests: **exit 0** with external pycache. Final `git diff --check`: **exit 0**.

Not run: the prior 214-case candidate business matrix, the long four-case
lifecycle, a production external-directory preparation, secret/password input,
service start/restart, real listener/health/API/browser checks, candidate
registration/start/resume, private/broker/order/live endpoints, or any paper/live
execution. `frontend/scripts/test-frontend-identity.mjs` was not presented as an
integrator pass: its Windows canonical section must run after approved source is
merged into registered `main`; before that, it correctly delegates to the old
main manifest and fails `fingerprint_or_object_ids_mismatch`.

## Governance, artifacts and remaining gates

Read: `AGENTS.md`, knowledge README/non-negotiables,
`shared_pitfalls.md`, `candidate_management_readonly_delivery.md`,
`cross_agent_coordination.md`, the integrator role contract, and the
`quant-agent-preflight`, `quant-gate-evidence-review`, and
`quant-agent-handoff` skills. Context packet catalog hash:
`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
Selected IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`,
`GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`,
`QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, and
`GOV-WINDOWS-001`.

No runtime artifact, manifest, database, ledger, replay, candidate evidence or
service receipt was created. Readiness remains `quality_checked`; it is not
promotion evidence. Root owns the separately authorized ordinary no-ff main
merge and then current-main frontend identity, backend identity/health, owned
listener and page acceptance. The operator owns the external empty preparation
and local Web management credential. Until those steps pass, deployment is not
running. Real candidate/source/input/account quality remains unverified.

The following remain false: `promotion_eligible`, `promotion_unlock_allowed`,
`paper_or_live_unlock_allowed`, `paper_allowed`, `live_allowed`,
`private_endpoint_allowed`, `order_endpoint_allowed`, `real_order_submitted`,
`transfer_allowed`, `withdraw_allowed`, `execution_permission`,
`runtime_worker_enabled`, `runtime_observed`, and `demo_control_enabled`.
