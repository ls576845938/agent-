# Phase G2: Shadow Live Read-Only Validation

## Current Status

- **Phase G1**: COMPLETE — Paper 30-Day Operational Validation
- **Phase G2**: IN PROGRESS — Shadow Live Read-Only Validation
- **Phase G3**: NOT STARTED — Small Live Pilot (requires G2 completion)

## G2 Objectives

Use real live environment for **read-only shadow validation**:
1. Read live account, positions, open orders
2. Read live market data
3. Run full pipeline: signal → target → risk → OMS
4. Generate **shadow orders** only (would_submit=True, real_submit=False)
5. Compare paper / shadow / live-readonly states
6. Run 5-10 trading days of validation
7. Generate Live Pilot Readiness Dossier

## What G2 Is NOT

- NOT real live order submission
- NOT IBKR integration
- NOT Redis integration
- NOT WebSocket implementation
- NOT new strategy development
- NOT promotion gate lowering
- NOT frontend refactoring
- NOT strategy alpha modification

## G2 Completion Criteria

1. shadow_live readiness profile → PASS (all 12 checks)
2. 5+ consecutive shadow-live validation days completed
3. real_submit_count == 0 across all days
4. No live order path touched
5. Data parity shows no CRITICAL issues
6. Reconciliation shows no CRITICAL issues
7. All incidents documented with reports
8. Manual review completed and signed off
9. Live Pilot Readiness Dossier generated
10. All tests passing

## G3 Entry Conditions

To enter Phase G3 (Small Live Pilot):
1. Paper 30-day validation PASS (from G1)
2. Shadow 5-day validation PASS (from G2)
3. Strategy frozen (no changes during validation)
4. Risk limits approved
5. Live Pilot Readiness Dossier → GO_FOR_SMALL_LIVE_REVIEW
6. Human review and explicit authorization
7. live profile remains NOT READY by default

## Safety Rules (Permanent)

**Even after G2 completion:**
- Live order submission remains default-blocked
- QUANT_LIVE_SUBMISSION_ENABLED does not enable shadow_live orders
- ReadOnlyBrokerProxy remains active in shadow_live mode
- Endpoint guard remains enforced
- Human confirmation required for ANY live order

## Key Files

| File | Purpose |
|------|---------|
| `quant_us/live/readonly_live_broker.py` | ReadOnlyLiveBrokerProxy + LiveEndpointGuard |
| `quant_us/live/shadow_models.py` | ShadowOrder, ShadowFill, ShadowLedger, StateDiff |
| `quant_us/live/shadow_orchestrator.py` | ShadowLiveOrchestrator lifecycle |
| `quant_us/live/market_data_parity.py` | MarketDataParityChecker |
| `quant_us/live/shadow_validation_controller.py` | Multi-day validation controller |
| `quant_us/live/live_pilot_dossier.py` | LivePilotReadinessDossier |
| `quant_us/reports/live_readiness.py` | shadow_live readiness profile (12 checks) |
| `quant_us/cli.py` | CLI commands for shadow-live |
| `docs/SHADOW_LIVE_RUNBOOK.md` | Operations runbook |
| `docs/SHADOW_LIVE_ARCHITECTURE.md` | Architecture documentation |
| `docs/RUNTIME_SAFETY.md` | Runtime safety guarantees |
