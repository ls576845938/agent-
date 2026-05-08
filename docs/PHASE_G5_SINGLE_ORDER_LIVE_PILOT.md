# Phase G5: Single Order Live Pilot

## Current G4 Completion Status

G4 (Small Live Pilot Execution) is complete:
- `LiveOrderSubmissionGate` with all 17 checks implemented
- `LivePilotExecutor` with `--execute-live-pilot` and `--confirm-live` flags
- `LiveOrderAuditTrail` for immutable order records
- `ReadOnlyBrokerProxy` ensures no real orders from non-G4 paths
- 30-day paper production validation completed (Phase G1)
- Order limits, CLI tools, and journaling (Phase G1)
- All G4 tests pass: gate chain, submission, dry-run, and the single
  fake-broker test that verifies `submit_order` is called when all gates pass

## G5 Objectives

1. **First real-money order**: execute exactly one live order through the
   production broker API.
2. **Safety validation**: prove that all safety gates work correctly with
   real broker infrastructure.
3. **Post-trade reconciliation**: verify that the system can reconcile
   broker fills against expectations.
4. **Execution quality assessment**: generate a quality report from the
   first real order execution.
5. **Immutable audit**: every step (ticket, confirmation, execution,
   reconciliation, dossier) is recorded in an immutable audit trail.
6. **No-second-order guarantee**: architectural proof that G5 cannot
   submit a second order, enforced by `SubmitOnceLock`.

## What G5 Allows

- Generating a `FirstLiveOrderTicket` via `FirstLiveOrderTicketBuilder`
- Confirming the ticket via `FinalHumanConfirmationGate` with all flags
- Dry-running the execution (no broker call) any number of times
- Executing exactly ONE live order with `OneShotLivePilotExecutor`
  when ALL safety checks pass
- Post-trade reconciliation via `PostTradeReconciler`
- Execution quality assessment via `ExecutionQualityReport`
- Generating a `G5PostTradeDossier` with decision `STOP_AND_REVIEW`
- Manual release of the submit-once lock after review
- Manual release of the post-trade freeze after review

## What G5 Prohibits

- **No second order**: `SubmitOnceLock` prevents any second `submit_order`
  call, even if the first order was rejected, partial, or timed out.
- **No automated re-submission**: rejected or timed-out orders are NOT
  automatically retried. A new ticket and new approval are required.
- **No G6 progression**: the dossier decision is `STOP_AND_REVIEW`, not
  `CONTINUE`. Manual review by an operator is required before G6.
- **No bypass of FinalHumanConfirmationGate**: the confirmation gate is
  the only path to set `i_understand_this_is_real_money=True`.
- **No automatic freeze release**: both `SubmitOnceLock` and
  `LivePilotFreezeState` require explicit manual release.
- **No order modification**: G5 does not support modifying a live
  order through the system. Use the broker dashboard.
- **No emergency stop bypass**: if emergency stop is triggered, the
  executor blocks submission regardless of other flags.

## G5 Components

```
Operator
    │
    ▼
FirstLiveOrderTicketBuilder ──→ FirstLiveOrderTicket (.md + .json)
    │
    ▼
FinalHumanConfirmationGate ──── check(i_understand, confirm_live, ...)
    │
    ▼
OneShotLivePilotExecutor ────── execute(ticket)
    │                               │
    ├── Dry run? ───→ DRY_RUN      │
    ├── Lock active? ─→ BLOCKED    │
    ├── E-stop? ───→ BLOCKED       │
    └── Submit ───→ broker.submit_order()
    │
    ▼
SubmitOnceLockManager.lock() ──── filesystem lock created
    │
    ▼
PostTradeReconciler.reconcile() ── CLEAN_FILLED / PARTIAL_FILL / REJECTED / BROKER_TIMEOUT
    │
    ▼
LivePilotFreezeState.freeze() ──── frozen state saved
    │
    ▼
ExecutionQualityReport.generate_execution_quality() ── STOP / REVIEW
    │
    ▼
G5PostTradeDossier ────────────── STOP_AND_REVIEW
    │
    ▼
Manual operator review ────────── release lock + freeze → G6 readiness
```

## G5 Completion Criteria

1. **Ticket generation**: `FirstLiveOrderTicketBuilder.build()` produces
   valid tickets. All validation gates (notional, approval, e-stop) are
   enforced.
2. **Confirmation gate**: `FinalHumanConfirmationGate.check()` blocks
   when any required flag is missing or ticket is expired. Approved
   only when all conditions are met.
3. **Dry-run execution**: `OneShotLivePilotExecutor.execute()` with
   default config returns `DRY_RUN_COMPLETED` with `real_submit_occurred=False`.
4. **Real execution**: `OneShotLivePilotExecutor.execute()` with explicit
   config returns `SUBMITTED` with `real_submit_occurred=True`. Broker
   `submit_order` is called exactly once.
5. **Submit-once lock**: After submission, `SubmitOnceLockManager.is_locked()`
   returns `True`. A second `lock()` call raises `RuntimeError`.
6. **No second order**: Any attempt to execute a second live order is
   blocked by the lock, regardless of how the first order resolved.
7. **Post-trade reconcile**: `PostTradeReconciler.reconcile()` returns
   correct outcome for filled, partial, rejected, and timeout scenarios.
8. **Execution quality**: `ExecutionQualityReport.generate_execution_quality()`
   returns `STOP` for filled/rejected/timeout and `REVIEW` for partial fill.
9. **Dossier**: `G5PostTradeDossier` produces the correct decision
   (`NOT_READY`, `BLOCKED`, or `STOP_AND_REVIEW`) and contains all evidence.
10. **All tests pass**: all 6 G5 test files pass with no real API keys
    and no real broker calls.

## G6 Entry Conditions

G6 (Multiple Live Orders) may begin only when ALL of the following are true:

1. **G5 completion criteria met**: all tests pass, all components verified.
2. **First real order executed**: at least one G5 order has been submitted
   to the live broker and reconciled.
3. **G5 dossier reviewed**: the `G5PostTradeDossier` has been reviewed
   by a human operator. Decision is documented.
4. **Submit-once lock released**: the lock has been manually released.
5. **Post-trade freeze released**: the freeze has been manually released.
6. **Lessons learned documented**: any issues encountered during G5 are
   documented and addressed.
7. **Operator sign-off**: a human operator signs off on G6 progression.
8. **No emergency stop active**: the emergency stop is not in `TRIGGERED` state.

G6 design must:
- Support multiple sequential orders (not one-shot)
- Maintain per-order safety gates
- Keep the `SubmitOnceLock` concept but make it per-session rather than global
- Add order-level idempotency for the multi-order case
- Not remove any G5 safety guarantees
