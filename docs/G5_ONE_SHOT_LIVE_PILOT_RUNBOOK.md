# G5 One-Shot Live Pilot Runbook

## What G5 Is and Why Only One Order

G5 (Phase G5) is the **Single Order Live Pilot** — the first time real money reaches
a broker. Its defining constraint is **exactly one live order, ever**.

Why only one order:
- **Auditability**: every safety check is validated once. A second order would require
  re-validation of all gates, which G5 intentionally does not automate.
- **Loss containment**: the maximum financial exposure of G5 is one order within the
  approved envelope. Any problem (wrong symbol, wrong side, wrong quantity) affects
  only one trade.
- **Learning opportunity**: the post-trade dossier records every dimension of execution
  quality. Manual review of the first real order informs whether the system is ready
  for G6 (multiple live orders).
- **Technical safety**: the `SubmitOnceLock` is a filesystem-level lock that prevents
  any code path from submitting a second order. This is architectural, not procedural.

## How to Generate a Ticket

Use the `FirstLiveOrderTicketBuilder`:

```python
from quant_us.live.first_live_order_ticket import FirstLiveOrderTicketBuilder

builder = FirstLiveOrderTicketBuilder(
    strategy_id="etf_rotation",
    symbol="SPY",
    side="buy",
    quantity=10.0,
    order_type="limit",
    limit_price=450.0,
    time_in_force="day",
    envelope_id="env_g5_001",
    envelope_max_notional=10000.0,
    approval_id="approval_g5_001",
    approval_status="APPROVED",
    emergency_stop_triggered=False,
    created_by="operator_name",
)
ticket = builder.build()
ticket.save_ticket(store_path="/path/to/g5/tickets")
```

The builder validates:
- Notional (quantity x limit_price) does not exceed `envelope_max_notional`
- Approval status is `APPROVED` (not `DRAFT` or `REJECTED`)
- Emergency stop is not `TRIGGERED`

The ticket is saved as both `.md` (human-readable) and `.json` (machine-readable).

## How to Confirm a Ticket

Confirmation is handled by `FinalHumanConfirmationGate`:

```python
from quant_us.live.first_live_order_ticket import FinalHumanConfirmationGate

gate = FinalHumanConfirmationGate(audit_path="/path/to/audit")
result = gate.check(
    ticket_id="ticket_g5_001",
    confirm_ticket="ticket_g5_001",
    i_understand_this_is_real_money=True,
    confirm_live=True,
    execute_one_shot=True,
)
```

The gate requires:
- `--i-understand-this-is-real-money` flag (acknowledges real financial risk)
- `--confirm-live` flag (acknowledges live mode)
- `--execute-one-shot` flag (acknowledges one-shot execution)
- `--confirm-ticket` matches the actual `ticket_id`
- Ticket is not expired

All checks are logged to the confirmation audit trail.

## How to Dry-Run One-Shot

Dry-run mode validates the execution pipeline without submitting to the broker:

```python
from quant_us.live.one_shot_executor import (
    OneShotLivePilotExecutor, OneShotExecutorConfig,
)

config = OneShotExecutorConfig()  # is_dry_run=True by default
executor = OneShotLivePilotExecutor(
    config=config,
    state_dir="/path/to/g5/state",
    broker=broker_instance,
)
result = executor.execute(ticket=ticket)
# result.status == "DRY_RUN_COMPLETED"
# result.real_submit_occurred == False
```

The dry run:
- Loads and validates the ticket
- Checks the submit-once lock (should be inactive)
- Checks emergency stop status
- Generates a dry-run result but does NOT call `broker.submit_order()`
- Records the dry run in the audit trail

Always run at least one dry run before attempting a real execution.

## How to Real Execute One-Shot

Real execution requires explicit flags:

```python
config = OneShotExecutorConfig(
    execute_one_shot=True,
    confirm_live=True,
    i_understand_real_money=True,
)
# config.is_dry_run is False

executor = OneShotLivePilotExecutor(
    config=config,
    state_dir="/path/to/g5/state",
    broker=broker_instance,
)
result = executor.execute(ticket=ticket)
# On success: result.status == "SUBMITTED", result.real_submit_occurred == True
```

If execution succeeds, the `SubmitOnceLockManager` creates an immutable lock file
preventing any future submission.

## How to Check Submit Lock

```python
from quant_us.live.one_shot_executor import SubmitOnceLockManager

lock_mgr = SubmitOnceLockManager(lock_path="/path/to/g5/state/submit_once_lock.json")
status = lock_mgr.status()
# status["locked"] == True/False
# status["ticket_id"] == "ticket_g5_001"
# status["status"] == "ACTIVE" or "RELEASED_BY_MANUAL_REVIEW"
```

The lock is:
- Created on first successful `submit_order` call
- Checked before EVERY execution attempt
- Released only by manual operator intervention

## How to Post-Trade Reconcile

```python
from quant_us.live.g5_post_trade import PostTradeReconciler

reconciler = PostTradeReconciler()
result = reconciler.reconcile(
    ticket_id="ticket_g5_001",
    broker_order_id="broker_order_123",
    expected_qty=10.0,
    filled_qty=10.0,
    status="filled",
)
# result.outcome == ReconOutcome.CLEAN_FILLED
```

Possible outcomes:
| Outcome | Meaning | Manual Review |
|---------|---------|---------------|
| `CLEAN_FILLED` | Full fill, no issues | No |
| `PARTIAL_FILL` | Partial fill | Yes |
| `REJECTED` | Order rejected by broker | Yes |
| `BROKER_TIMEOUT` | No response from broker | Yes |

## How to Generate Execution Quality Report

```python
from quant_us.live.g5_post_trade import ExecutionQualityReport

report = ExecutionQualityReport.generate_execution_quality(reconcile_result)
# report.quality == ExecutionQuality.STOP  (for filled/rejected/timeout)
# report.quality == ExecutionQuality.REVIEW (for partial fill)
```

Quality levels:
- **STOP**: execution is complete. No action needed (filled) or full stop (rejected/timeout).
- **REVIEW**: manual review required (partial fill).

## How to Generate G5 Dossier

```python
from quant_us.live.g5_post_trade import G5PostTradeDossier

dossier = G5PostTradeDossier(
    state_dir="/path/to/g5/state",
    ticket_id="ticket_g5_001",
    has_order_evidence=True,
    reconcile_result=reconcile_result,
)
print(dossier.to_markdown())
print(dossier.to_dict())
```

Dossier decisions:
| Decision | Meaning |
|----------|---------|
| `NOT_READY` | Missing ticket_id or order evidence |
| `BLOCKED` | Submit-once lock missing or second order detected |
| `STOP_AND_REVIEW` | All evidence collected, ready for manual review |

## Handling Partial Fill / Rejected / Timeout

### Partial Fill
1. The reconcile result has `needs_manual_review=True`
2. The execution quality report is `REVIEW`
3. Check the filled quantity vs expected quantity
4. Determine whether to accept the partial or escalate
5. If acceptable, release the freeze manually and proceed to G6 readiness review

### Rejected
1. The reconcile result includes the broker's `reject_reason`
2. The execution quality is `STOP`
3. Common reasons: insufficient buying power, invalid symbol, invalid side
4. Correct the issue (if fixable) before considering re-submission
5. Re-submission requires a NEW ticket and NEW approval — G5 does not auto-retry

### Timeout
1. The broker did not respond within the expected window
2. The execution quality is `STOP`
3. Check broker status and order status via the broker dashboard
4. Do NOT assume the order was not placed — verify externally first

## Why No Automatic Second Order

G5 enforces a hard architectural limit of one order through:

1. **SubmitOnceLock**: a filesystem lock created on first `submit_order`. Any code path
   that attempts a second order is blocked at the lock manager level.
2. **LivePilotFreezeState**: a frozen state set after post-trade reconciliation.
   The freeze prevents any new execution until manually released.
3. **G5PostTradeDossier**: the dossier decision is `STOP_AND_REVIEW`, not
   `CONTINUE`. The system is designed to stop after one order.

There is no automated path from G5 to G6. Manual review of the dossier is required.

## Emergency Stop Procedures

If something goes wrong during G5 execution:

1. **During ticket generation / confirmation**: Do not proceed. Diagnose the issue.
2. **During execution**: If the executor is still running, the emergency stop controller
   will block submission if triggered. Trigger the emergency stop:
   ```python
   ctrl.trigger("manual_stop", triggered_by="operator")
   ```
3. **After submission (order live)**: The freeze is already active. Use the broker's
   dashboard or API to cancel the order if needed. Do not attempt a second order
   through the system.
4. **After reconciliation**: If the outcome is unexpected (rejected, partial, timeout),
   the dossier is `STOP_AND_REVIEW`. Call the emergency stop if not already triggered:
   ```python
   ctrl.trigger("post_trade_anomaly", triggered_by="operator")
   ```
5. **Rollback**: There is no automated rollback for a submitted order. Manual
   broker intervention (cancel order, close position) is the only rollback.
