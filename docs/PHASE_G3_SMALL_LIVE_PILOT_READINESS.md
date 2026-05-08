# Phase G3: Small Live Pilot Readiness & Human Approval System

## Current Status

- **Phase G1**: COMPLETE — Paper 30-Day Operational Validation
- **Phase G2**: COMPLETE — Shadow Live Read-Only Validation
- **Phase G3**: IN PROGRESS — Small Live Pilot Readiness & Human Approval
- **Phase G4**: NOT STARTED — First Live Order (requires G3 completion + human authorization)

## G3 Objectives

Establish the governance, approval, risk, and emergency response framework for eventual small live trading. G3 itself does NOT submit any real orders.

1. Human Approval System — mandatory sign-off before any live activity
2. Risk Envelope — ultra-conservative limits ($1,000 capital, $100 max order)
3. Dry-Run Executor — full pipeline simulation with real_submit=False
4. Emergency Stop — armed panic button with reduce-only enforcement
5. Rollback Plan — structured recovery after incidents
6. Go/No-Go Dossier — comprehensive evidence for human review

## What G3 Is NOT

- NOT real live order submission
- NOT automatic live trading
- NOT lowering any safety gate
- NOT IBKR, Redis, WebSocket, new strategies

## G3 Completion Criteria

1. HumanApprovalGate implemented and tested
2. LivePilotRiskEnvelope implemented with all limiters
3. LivePilotDryRunExecutor completes 14-step pipeline (real_submit=False)
4. EmergencyStopController cycles through all states
5. RollbackPlanGenerator produces structured plans
6. LivePilotGoNoGoDossier generates markdown+JSON
7. All CLI commands functional
8. All tests passing (no real broker calls)
9. Documentation complete

## G4 Entry Conditions

To enter Phase G4 (First Live Order):
1. G3 Go/No-Go Dossier → READY_FOR_HUMAN_REVIEW
2. Human reviewer explicitly authorizes
3. Risk envelope approved
4. Emergency stop verified armed
5. All tests passing
6. No safety gates lowered

## Safety Rules (Permanent)

**Even after G3 completion:**
- Live order submission remains default-blocked
- Human approval is mandatory for any live activity
- Risk envelope limits are hard limits
- Emergency stop must be armed
- Dry-run must pass before any live order
- Live profile remains NOT READY until G4 human authorization
