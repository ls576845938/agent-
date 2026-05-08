# Phase G8: Supervised Micro Live Session

## What G8 Is (NOT Auto Trading)

G8 introduces a **Supervised Micro Live Session**: a managed, one-shot-at-a-time trading session with manual supervision at every step.

G8 is NOT:
- Automated live trading
- Continuous/loop trading
- Unattended operation
- High-frequency trading

G8 IS:
- One order at a time, with human confirmation
- Session-frozen after every order
- Manual review + resume required for next order
- Hard daily and session-level caps

## Session Lifecycle

```
       +-----------+
       |   DRAFT   |  Created but not ready
       +-----+-----+
             |
             | arm (human action)
             v
       +-----------+
       |   ARMED   |  Ready, awaiting activation
       +-----+-----+
             |
             | activate (human action)
             v
       +----------------------+
       | ACTIVE_MANUAL_        |  Can submit one order
       | SUPERVISION           |
       +----------+-----------+
                  |
         +--------+--------+
         |                 |
         v                 v
   +---------+       +---------+
   |  FROZEN |       |  PAUSED |  (optional pause)
   +----+----+       +----+----+
        |                 |
        | resume           | resume
        | (human)          |
        +--------+---------+
                 |
                 v
       +----------------------+
       | ACTIVE_MANUAL_        |  Ready for next order
       | SUPERVISION           |
       +----------+-----------+
                  |
         (loop back, each order = freeze + resume)
                  |
                  v
       +-----------+
       | COMPLETED |  Session done
       +-----------+

Any state can go to TERMINATED (irreversible).
```

### State Transitions

| From | To | Requires |
|------|----|----------|
| DRAFT | ARMED | Human arm() action |
| ARMED | ACTIVE_MANUAL_SUPERVISION | Human activate() action |
| ACTIVE_MANUAL_SUPERVISION | FROZEN | Order submission |
| ACTIVE_MANUAL_SUPERVISION | PAUSED | Manual pause |
| FROZEN | ACTIVE_MANUAL_SUPERVISION | Human resume() action |
| FROZEN | COMPLETED | Manual complete |
| FROZEN | PAUSED | Manual pause |
| PAUSED | ACTIVE_MANUAL_SUPERVISION | Human resume() action |
| Any | TERMINATED | Reason required |

## How SessionExecutionBridge Reuses OneShotExecutor

The `SessionExecutionBridge` is the ONLY bridge between G8 and the G5 `OneShotLivePilotExecutor`:

```
SessionExecutionBridge.execute_one_shot()
       |
       | 1. Load session state (verify ARMED/ACTIVE_MANUAL_SUPERVISION)
       | 2. Check SessionGate (all 10 checks)
       | 3. Import OneShotLivePilotExecutor
       | 4. Execute exactly one order
       v
       | 5. Freeze session (ACTIVE_MANUAL_SUPERVISION -> FROZEN)
       | 6. Record against daily cap
       | 7. Write session audit
```

CRITICAL RULES:
- NEVER calls `submit_order()` or `AlpacaBroker` directly
- NEVER creates new submit paths
- NEVER loops or auto-continues
- One call = one attempt, then freeze

## SessionGate Block Reasons

The `SessionGate` checks 10 conditions in order (returns on first failure):

| # | Check | Block Reason | Type |
|---|-------|-------------|------|
| 1 | Dry run mode | `dry_run_mode` | Always blocked |
| 2 | Manual confirmation | `missing_manual_confirm` | Human req'd |
| 3 | Promotion manifest | `missing_promotion` | Governance |
| 4 | Promotion status | `promotion_not_approved` | Governance |
| 5 | Session state | `session_not_armed` | Lifecycle |
| 6 | Frozen state | `session_frozen` | Lifecycle |
| 7 | Daily cap | `max_orders_per_day_exceeded` | Limit |
| 8 | Session limits | `max_orders_per_session_exceeded` | Limit |
| 9 | Session notional | `session_notional_exceeded` | Limit |
| 10 | Emergency stop | `emergency_stop_triggered` | Safety |
| 11 | Reconciliation | `reconciliation_dirty` | Safety |
| 12 | Missing ticket | `missing_ticket` | Operational |

Default decision is always BLOCKED.

## DailyTradingCap Enforcement

Daily caps are tracked per-session, per-date:

```
DailyTradingCap:
  max_orders_per_day:    1 (default)
  max_notional_per_day:  100.0 (default)
  max_loss_per_day:      10.0 (default)
```

- Caps reset daily (by UTC date)
- Each executed order is recorded against the cap
- `check()` returns (allowed, reason) before every order

## SessionReport Format

The session status report (from `SessionRuntimeStateManager.status()`):

```
session_id:       g8_session_abc123
promotion_id:     promo_xyz
status:           FROZEN
submitted_order_count: 1
completed_order_count: 0
real_submit_count: 0
incident_count:   0
current_freeze_reason: ORDER_SUBMITTED
manual_review_required: true
order_ticket_ids: ["ticket_001"]
```

## CLI Reference

```bash
# Create a new session
quant-us session create --promotion-id <promotion_id>

# Arm a session
quant-us session arm --session-id <session_id>

# Activate a session
quant-us session activate --session-id <session_id>

# Execute one-shot order in session
quant-us session execute --session-id <session_id> --ticket-id <ticket_id> --confirm

# Resume a frozen session
quant-us session resume --session-id <session_id>

# Pause a session
quant-us session pause --session-id <session_id>

# Complete a session
quant-us session complete --session-id <session_id>

# Terminate a session
quant-us session terminate --session-id <session_id> --reason "reason"

# Show session status
quant-us session status --session-id <session_id>

# Show daily cap
quant-us session daily-cap --session-id <session_id> --date YYYY-MM-DD
```
