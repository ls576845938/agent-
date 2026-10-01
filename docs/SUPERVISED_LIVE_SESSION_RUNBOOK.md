# Supervised Live Session Runbook

Step-by-step process for running a G8 Supervised Micro Live Session.

## Prerequisites

- Approved G7 Strategy Promotion Manifest (is_valid_for_g8 = True)
- Promotion manifest ID recorded

## Step 1: Create Session

1. Create a new session:
   ```
   quant-us session create --promotion-id <promotion_id>
   ```

2. Save the session ID: `session_id = <output_id>`

3. Session status: DRAFT

## Step 2: Arm Session

1. Arm the session (human action required):
   ```
   quant-us session arm --session-id <session_id>
   ```

2. Session status: ARMED

3. The session is now ready, but will not accept orders until activated.

## Step 3: Activate Session

1. Activate the session (human action required):
   ```
   quant-us session activate --session-id <session_id>
   ```

2. Session status: ACTIVE_MANUAL_SUPERVISION

3. The session can now accept one order (subject to all gate checks).

## Step 4: One-Shot Execution

1. Generate a ticket (via G5 FirstLiveOrderTicketBuilder).

2. Execute the one-shot order within the session:
   ```
   quant-us session execute --session-id <session_id> --ticket-id <ticket_id> --confirm
   ```
   The `--confirm` flag sets `manual_confirm=True`.

3. The SessionGate checks:
   - Not dry-run (you must pass `--confirm`)
   - Promotion manifest is valid
   - Session is ARMED or ACTIVE_MANUAL_SUPERVISION
   - Session is not FROZEN
   - Daily cap is not exceeded
   - Session limits not exceeded
   - Emergency stop not triggered
   - Reconciliation clean
   - Ticket ID provided

4. If all checks pass: OneShotLivePilotExecutor runs exactly one order.

5. After execution: session is frozen (ACTIVE_MANUAL_SUPERVISION -> FROZEN).

6. Session status: FROZEN (reason: ORDER_SUBMITTED)

## Step 5: Post-Trade Review

1. Review the executed order:
   - Check fill status
   - Review execution quality
   - Verify reconciliation

2. Session is frozen -- no more orders can be submitted.

## Step 6: Resume Session (If Another Order Needed)

1. Only if another order is needed:
   ```
   quant-us session resume --session-id <session_id>
   ```

2. Session status: ACTIVE_MANUAL_SUPERVISION

3. Return to Step 4 for the next order.

4. Each order = freeze + manual resume. No auto-continuation.

## Step 7: Complete Session

1. When all orders are done:
   ```
   quant-us session complete --session-id <session_id>
   ```

2. Session status: COMPLETED

3. Resume is not possible from COMPLETED.

## Emergency: Pause Session

1. At any point:
   ```
   quant-us session pause --session-id <session_id>
   ```

2. Session status: PAUSED

3. To resume:
   ```
   quant-us session resume --session-id <session_id>
   ```

## Emergency: Terminate Session

1. If session must be stopped permanently:
   ```
   quant-us session terminate --session-id <session_id> --reason "reason"
   ```

2. Session status: TERMINATED (irreversible)

## Session Status Reference

| Status | Meaning | Can Submit? |
|--------|---------|-------------|
| DRAFT | Created, not ready | No |
| ARMED | Ready, awaiting activation | No (must activate) |
| ACTIVE_MANUAL_SUPERVISION | Can accept one order | Yes |
| FROZEN | Order submitted, under review | No (must resume) |
| PAUSED | Temporarily stopped | No (must resume) |
| COMPLETED | Session done | No |
| TERMINATED | Session stopped permanently | No |

## Daily Cap Reference

```
# Check daily cap status
quant-us session daily-cap --session-id <session_id> --date YYYY-MM-DD

# Default limits:
#   - 1 order per day
#   - $100 notional per day
#   - $10 max loss per day
```
