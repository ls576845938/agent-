# Live Order Safety Architecture (G4)

## Overview

G4 implements the controlled execution layer for Small Live Pilot. Every real live order must pass through the `LiveOrderSubmissionGate` which aggregates ALL safety checks into a single non-bypassable decision point.

## Gate Chain (17 independent checks)

```
CLI --execute-live-pilot --confirm-live
    ↓
LivePilotExecutor.execute()
    ↓
LiveOrderSubmissionGate.check()          ← SINGLE non-bypassable gate
    ├── 1. is_dry_run? → BLOCKED
    ├── 2. execute_live_pilot? → BLOCKED if False
    ├── 3. approval_id provided?
    ├── 4. approval status == APPROVED?
    ├── 5. approval not expired?
    ├── 6. envelope_id provided?
    ├── 7. dossier decision ready?
    ├── 8. QUANT_LIVE_SUBMISSION_ENABLED=true?
    ├── 9. confirm_live=True?
    ├── 10. allow_live_orders=True?
    ├── 11. live endpoint accessible?
    ├── 12. reconciliation clean?
    ├── 13. emergency stop ARMED?
    ├── 14. emergency stop not triggered?
    ├── 15. in regular session?
    ├── 16. order type allowed?
    ├── 17. notional within limits?
    └── → APPROVED_FOR_SUBMIT or BLOCKED
    ↓
AlpacaBroker.submit_order()             ← HTTP POST to live API
    ↓
LiveOrderAuditTrail.record_submitted()
```

## LiveOrderSubmissionGate

The single `check()` method that must return `APPROVED_FOR_SUBMIT` before any real order reaches the broker. All 17 checks are evaluated, and every block reason is recorded in the audit log.

### Block Reasons (complete list)

| Reason | Meaning |
|--------|---------|
| `dry_run_mode` | Executor is in dry-run mode |
| `execute_live_pilot_not_set` | --execute-live-pilot flag not passed |
| `missing_approval` | No approval_id provided |
| `approval_not_approved` | Approval status != APPROVED |
| `approval_expired` | Approval past expiry date |
| `missing_envelope` | No envelope_id provided |
| `dossier_not_ready` | Dossier decision not READY |
| `env_gate_disabled` | QUANT_LIVE_SUBMISSION_ENABLED not set |
| `missing_confirm_live` | --confirm-live not passed |
| `allow_live_orders_false` | Config flag not set |
| `live_endpoint_mismatch` | Cannot connect to live API |
| `reconciliation_not_clean` | Ledger/broker mismatch |
| `emergency_stop_not_armed` | Stop not in ARMED state |
| `emergency_stop_triggered` | Stop is TRIGGERED |
| `outside_regular_session` | Not regular market hours |
| `order_type_not_allowed` | Market/short/pre-post blocked |
| `notional_exceeded` | Order exceeds envelope limits |
| `kill_switch_active` | Kill switch is triggered |
| `oms_idempotency_failed` | Duplicate order intent |

## Audit Trail

Every order attempt produces an immutable `LiveOrderAuditRecord`:
- Dry-run → record with `real_submit=False`
- Blocked → record with `gate_decision=BLOCKED`
- Submitted → record with `real_submit=True`

Records are append-only JSONL. Secrets are always masked.

## Safety Invariants

1. Default: dry-run (no real orders)
2. Real orders require: --execute-live-pilot + --confirm-live + env + approval + envelope + all 17 gates
3. LiveOrderSubmissionGate is the ONLY path to submit_order
4. Emergency stop blocks submit_order at the gate level
5. Every blocked/submitted attempt is audited
6. Secrets never appear in logs or audit records

## G5 One-Shot Safety

G5 adds a one-shot execution layer on top of the G4 gate chain. The
one-shot architecture ensures that exactly ONE real live order can ever
be submitted, regardless of how many times the execution path is invoked.

### OneShotLivePilotExecutor

`OneShotLivePilotExecutor` wraps the G4 `LivePilotExecutor` with a
one-shot contract:

- Default configuration is dry-run (`is_dry_run=True`). No real order
  can be submitted without explicitly setting `execute_one_shot=True`,
  `confirm_live=True`, and `i_understand_real_money=True`.
- Before any submission, the executor checks:
  1. Is this a dry run? If so, return `DRY_RUN_COMPLETED`.
  2. Is the ticket valid and not expired?
  3. Is the submit-once lock already active? If so, block.
  4. Is the emergency stop triggered? If so, block.
- After successful submission, the executor creates the submit-once lock
  and returns `SUBMITTED` with `real_submit_occurred=True`.

### SubmitOnceLock

`SubmitOnceLock` is a filesystem-based immutable lock:

- Created by `SubmitOnceLockManager.lock()` on first successful
  `submit_order` call.
- Written to a JSON file with ticket_id, client_order_id, broker_order_id,
  and timestamp.
- `is_locked()` checks the filesystem state — it survives process restarts.
- Any second `lock()` call raises `RuntimeError("SUBMIT-ONCE LOCK ACTIVE")`.
- Released only by explicit `manager.release(released_by, reason)` call.
- Release sets status to `RELEASED_BY_MANUAL_REVIEW` — it is never deleted.

Lock states:

| State | Meaning |
|-------|---------|
| `ACTIVE` | Lock is live; no second order allowed |
| `RELEASED_BY_MANUAL_REVIEW` | Operator has manually released the lock |

### FinalHumanConfirmationGate

The confirmation gate is the operator's final safety check before
execution. It requires ALL of the following:

- `--i-understand-this-is-real-money`: operator explicitly acknowledges
  real financial risk.
- `--confirm-live`: operator confirms live mode (not paper/simulation).
- `--execute-one-shot`: operator confirms one-shot execution mode.
- `--confirm-ticket`: operator re-types the ticket ID as confirmation.
- Ticket is not expired (within `TICKET_EXPIRY_MINUTES` of creation).

The gate writes every check result to a JSONL audit trail. Both
`confirmation_blocked` and `confirmation_approved` events are recorded
with all block reasons.

### Post-Trade Freeze

After the first order is submitted and reconciled, the system enters a
frozen state via `LivePilotFreezeState`:

- `freeze()` writes a JSON state file marking the system as frozen.
- `is_frozen` returns `True` after freeze, `False` after release.
- `can_submit_new_order` returns `False` while frozen.
- The freeze persists across process restarts (filesystem state).
- `release(released_by)` changes state back to unfrozen.
- The freeze is independent of `SubmitOnceLock` — both must be released
  for G6 progression.

### Second Order Prevention

G5 prevents a second order through multiple independent layers:

1. **Architectural**: `SubmitOnceLockManager.lock()` raises `RuntimeError`
   on any second call. This is in the execution path, before any broker
   call.
2. **State-based**: `LivePilotFreezeState` blocks `can_submit_new_order`.
   The executor checks this before attempting execution.
3. **Dossier-based**: `G5PostTradeDossier` returns `STOP_AND_REVIEW`
   instead of `CONTINUE`. There is no automated path to a second order.
4. **Procedural**: Both lock and freeze require manual operator release.
5. **Audit**: Every blocked execution attempt is recorded in the audit trail.

Execution flow with all checks:

```
execute(ticket)
    │
    ├── is_dry_run? ──────────────→ DRY_RUN_COMPLETED
    ├── ticket missing/expired? ──→ ERROR
    ├── submit_once_lock active? ─→ BLOCKED
    ├── emergency_stop_triggered? ─→ BLOCKED
    ├── can_submit_new_order? ────→ BLOCKED
    └── submit_order() ──────────→ SUBMITTED
         │
         └── lock manager locks
         └── freeze manager freezes
```

### The `--i-understand-this-is-real-money` Gate

This flag is the single most important safety gate in G5. Unlike other
flags that can be set programmatically, this flag represents a conscious
human acknowledgement of financial risk:

- `OneShotExecutorConfig` raises `ValueError` if `execute_one_shot=True`
  but `i_understand_real_money=False`.
- `FinalHumanConfirmationGate` blocks if `i_understand_this_is_real_money`
  is not `True`.
- The flag value is recorded in the audit trail for every execution attempt.
- There is no default value of `True` — it must always be explicit.
- The flag is named to be unmistakable and non-trivial to bypass.
