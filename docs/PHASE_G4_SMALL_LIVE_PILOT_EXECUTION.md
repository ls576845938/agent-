# Phase G4: Small Live Pilot Controlled Execution

## Current Status

- **Phase G1**: COMPLETE — Paper 30-Day Operational Validation
- **Phase G2**: COMPLETE — Shadow Live Read-Only Validation
- **Phase G3**: COMPLETE — Small Live Pilot Readiness & Human Approval
- **Phase G4**: IN PROGRESS — Small Live Pilot Controlled Execution
- **Phase G5**: NOT STARTED — (requires G4 completion + human authorization)

## G4 Objectives

Establish the controlled execution layer for the first real live order under maximum safety constraints:

1. LivePilotExecutor — single entry point for live order execution
2. LiveOrderSubmissionGate — 17-check non-bypassable gate
3. LiveOrderAuditTrail — immutable audit for every order attempt
4. FirstLiveOrderSimulation — pre-submit simulation with checklist
5. EmergencyStop integration — hard block in execution chain
6. Default dry-run — --execute-live-pilot required to submit

## What G4 Allows

- Running the complete live order pipeline in dry-run mode
- Simulating the first live order with full gate checks
- Submitting a real live order ONLY when ALL of:
  - --execute-live-pilot flag
  - --confirm-live flag
  - QUANT_LIVE_SUBMISSION_ENABLED=true
  - APPROVED approval
  - Matching risk envelope
  - Go/No-Go dossier READY
  - Emergency stop ARMED
  - Reconciliation clean
  - Regular session
  - Limit order only
  - Within envelope limits
  - All 17 submission gate checks pass

## What G4 Prohibits

- Automatic live order submission
- Submitting without human confirmation
- Market orders
- Pre/post market orders
- Short selling
- Exceeding risk envelope
- Submitting without audit trail
- Bypassing LiveOrderSubmissionGate

## G4 Completion Criteria

1. LivePilotExecutor functional (26-step pipeline)
2. LiveOrderSubmissionGate with all 17 block reasons
3. LiveOrderAuditTrail immutable and secret-safe
4. FirstLiveOrderSimulation generates checklist
5. EmergencyStop integrated into gate
6. CLI commands: execute, first-order-simulate, audit, status, stop
7. All tests pass
8. Documentation complete

## G5 Entry Conditions

To enter Phase G5:
1. G4 live pilot (dry-run) completed successfully
2. All 17 gates verified in dry-run
3. First order simulation passes
4. Human reviewer explicitly authorizes G5
5. G4 real_submit_count == 0 (all dry-runs)
6. All safety gates remain at maximum
