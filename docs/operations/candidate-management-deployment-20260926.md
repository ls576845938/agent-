# Candidate management deployment (operator procedure, not performed by producer)

Ticket CANDIDATE-MANAGEMENT-DEPLOY-20260926; change_risk=unclassified.
Base main 8821b04e599812429d5034c126493379209c59b5. Independent integration and
root-session deployment acceptance are required before executing this procedure.
This producer does not merge main, launch services, set User/Machine environment,
register candidates, start/resume jobs, or enable Demo/paper/live.

## What this release does

Both official backend guards accept candidate_management with
QS_ALLOW_FIXTURE_FALLBACK=false and QS_BTC_DEMO_CONTROL_ENABLED=false.
Loopback 127.0.0.1:8765, registered main/current HEAD, sparse/clean, listener
identity and existing concurrency guards remain mandatory. Old promotion_strict,
demo_quasi_live and research_readonly defaults/requirements are unchanged.
Candidate configuration failures are blocked with stable missing-field/error codes.
Do not interpret configuration_checked or HTTP health as a candidate-run permit.

The BTC workspace treats candidate_management + read_only=true +
controls_disabled=true as its existing research-only display: public market and
stream, original console/tester/layout and research links remain; Demo controller
polls/actions are disabled. Missing/wrong flags reject. No backend permissions,
economic source, Strategy, Risk, OMS or ledger semantics are changed.

The single helper scripts/candidate_management_deployment.py only prepares/checks
deployment metadata and delegates check/start to the same PS1 called by
start-backend.cmd. It is not a replacement server entrypoint. Its process-local
PowerShell ExecutionPolicy Bypass does not change system/User execution policy.

## 1. Preflight and rollback anchor

In the canonical registered main directory, root operator verifies the reviewed
source commits/handoff, current HEAD and clean scoped files. Record current HEAD,
official backend/frontend identities, old non-secret deployment config and actual
listener PIDs before stopping anything. Do not enumerate or print environment
values, password files, exchange credentials, or account secrets.

```powershell
Set-Location -LiteralPath 'D:\vibe coding\Obsidian\量化系统\agent-'
git rev-parse HEAD
Get-NetTCPConnection -State Listen -LocalPort 8765,3000 |
    Select-Object LocalAddress,LocalPort,OwningProcess
Invoke-RestMethod http://127.0.0.1:8765/__backend_identity
Invoke-RestMethod http://127.0.0.1:3000/__frontend_identity
```

Only act on listeners proven to belong to this canonical project. A different
profile/head listener must not be reused as management or stopped blindly.

## 2. Prepare an explicitly empty external deployment

Example external directory below is an operator-chosen dedicated target, not a
directory already prepared in this task. It must not equal/contain/be inside any
Git worktree, be a drive root, symlink or junction. The helper binds its owner to
the registered main's resolved path (same hash convention as existing catalogues).
Run from the reviewed, merged canonical checkout with its existing interpreter:

```powershell
& .\.venv\Scripts\python.exe -B -X utf8 scripts/candidate_management_deployment.py prepare --root 'D:/quantstation-runtime/candidate-management-20260926' --operator 'local-operator' --revision 'empty-v1'
```

Creates only .candidate-deployment-owner.json, offline-catalog.json,
accounts.json, deployment.json and empty factory/qlib directories.
Catalogue uses existing candidate_offline_catalog_v1, sources=[] and inputs=[];
accounts uses existing delivery_account_catalog_v1, accounts=[].
No synthetic model, account, observation, SQLite or economic state is copied.
Exact same invocation is idempotent; conflicting existing files/unowned nonempty
directories block without overwrite. A partial interrupted preparation may be
retried only with identical arguments; otherwise inspect, never delete to force it.

deployment.json contains only nine whitelisted non-secret environment settings.
It records external management root, operator, catalogue path, SHA-256, revision,
explicit offline-enabled=false, profile and the two safety flags. Changing the
catalogue later requires a separately reviewed new immutable version/hash/revision.
Preparation cannot import real candidates, reseal evidence, or bless account facts.

## 3. Local Web authentication — human only

This is the existing QS_WEB_API_KEY local Web mechanism, NOT an exchange API key.
The root session reports the value is currently absent; the producer has not read
any actual value and cannot confirm authentication or a running deployment.
Do not send a password in chat, command arguments, screenshots, files, logs or
registry. The helper does not generate one, hydrate User/Machine secrets or load
dotenv. Use an existing operator-controlled process credential, or run the hidden
local terminal prompt yourself:

```powershell
& .\.venv\Scripts\python.exe -B -X utf8 scripts/candidate_management_deployment.py check --config 'D:/quantstation-runtime/candidate-management-20260926/deployment.json' --prompt-auth
```

The TTY prompt uses getpass and fails if hidden input is unavailable. The password
is held only in the helper/child process environment; no parent environment or
file is updated. Without --prompt-auth, an already configured process credential
is inherited, never printed. If absent, output contains
candidate_management_authentication_missing and exit 2, with no service spawned.
An empty/prepared catalogue is honest waiting-for-import state, not fake readiness.

## 4. Approved startup, identity and page verification

Only after independent acceptance and root-session release approval:

```powershell
& .\.venv\Scripts\python.exe -B -X utf8 scripts/candidate_management_deployment.py start --config 'D:/quantstation-runtime/candidate-management-20260926/deployment.json' --prompt-auth
```

This stays foreground, calling official scripts/start_backend_current_main.ps1,
which calls guarded start_backend_current_main.py. Never run uvicorn directly.
If the nine non-secret values and local Web credential were securely set by the
operator in the current terminal already, the equivalent official commands are
start-backend.cmd -Check and start-backend.cmd (or the same PS1 with process-local
ExecutionPolicy Bypass). Do not change User/Machine environment to make it work.

Frontend identity must be refreshed by identity:refresh after the final committed
frontend source, then committed/reviewed by the integration flow. Producer refresh
is not proof the canonical page is running. From canonical main:

```powershell
node frontend/scripts/check-frontend-identity.mjs --canonical
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_frontend_current_main.ps1 -Check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_frontend_current_main.ps1
```

Use another terminal for read-only verification after launcher return:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8765,3000 |
    Select-Object LocalAddress,LocalPort,OwningProcess
Invoke-RestMethod http://127.0.0.1:8765/__backend_identity
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:3000/__frontend_identity
Invoke-RestMethod http://127.0.0.1:8765/api/candidate-offline/capabilities
```

Require canonical=true, runtime_stale=false, source/main HEAD matching reviewed
main, management profile, read_only=true, controls_disabled=true, correct listener
owners and final frontend fingerprint. Anonymous capabilities do not authenticate
the operator. For an authenticated GET without putting a key in arguments:
`python -m backend.app.cli.candidate_offline capabilities` and
`python -m backend.app.cli.candidate_offline catalog` use the existing hidden CLI
prompt (no --key-stdin via pasted plaintext). Verify empty inventory and no jobs,
then canonical browser /crypto and existing candidate-management pages: public
market display remains visible; console controls disabled; missing candidates and
evidence shown truthfully. No registration/start/resume POST is part of this ticket.

Do not silently change offline-enabled=false to true. Capability enablement is a
separate explicit operator choice and still does not make any candidate runnable.
Actual candidate/source/input/account review and all gates remain independent.

## 5. Stop and rollback

For a foreground session use Ctrl+C in that exact launcher terminal, then verify
its 8765 listener has exited. Stop the frontend likewise in its own terminal.
For an orphan, first verify PID, executable/command, canonical identity and owner;
only then an authorized operator may use `Stop-Process -Id <verified-PID>`.
Never Stop-Process by broad executable name or kill an unrelated port owner.

Keep the external directory, owner marker, configs and all future evidence intact.
No reset/cleanup of accounts, jobs, SQLite or ledgers is a rollback technique.
If returning to the old research-only profile, use a fresh terminal with only:

```powershell
$env:QS_BACKEND_EVIDENCE_PROFILE = 'research_readonly'
$env:QS_BTC_DEMO_CONTROL_ENABLED = 'false'
$env:QS_ALLOW_FIXTURE_FALLBACK = 'false'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_backend_current_main.ps1 -Check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_backend_current_main.ps1
```

A code rollback is a separately reviewed revert to the recorded source anchor,
followed by identity:refresh/commit and canonical acceptance; never hard reset a
dirty main. Promotion artifacts may remain missing/stale and do not block a
truthful research display; they still block promotion/paper/live.

## Remaining limits

No real candidate/account/input has been validated here. Existing PID reuse may
conservatively report an offline worker alive. Protection-trigger fills and legal
registered partial opening remain unsupported; sampled protection touch stays
durably blocked. Management availability is not trading readiness. All
demo_control, promotion, paper, live, private, order, real_order, transfer, withdraw,
execution_permission, runtime_worker_enabled and runtime_observed flags remain
false for this delivery; no service or actual environment was enabled by producer.
