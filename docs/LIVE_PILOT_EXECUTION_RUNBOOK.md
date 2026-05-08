# Live Pilot Execution Runbook (G4)

## What is G4?

G4 is the **controlled execution** phase for Small Live Pilot. It allows real live orders ONLY when all safety gates pass and the operator explicitly passes `--execute-live-pilot --confirm-live`.

**Default behavior: DRY-RUN. No orders are ever submitted by default.**

## Why Not Full Auto-Trading

- Every live order requires explicit human confirmation
- Multiple independent safety gates must ALL pass
- Emergency stop is always armed
- Maximum capital: $1,000
- Maximum order: $100
- Market orders: BLOCKED
- Pre/post market: BLOCKED
- Short selling: BLOCKED

## Prerequisites

1. G1 Paper 30-day validation PASS
2. G2 Shadow Live 5-day validation PASS
3. G3 Go/No-Go dossier → READY_FOR_HUMAN_REVIEW
4. Human approval APPROVED
5. Risk envelope configured and approved
6. Emergency stop ARMED
7. Live broker credentials configured
8. `QUANT_LIVE_SUBMISSION_ENABLED=true` in environment

## CLI Commands

### First Order Simulation (NO real submit)

```bash
python3 -m quant_us.cli live-pilot first-order-simulate \
  --approval-id pilot-001 \
  --envelope-id env-001 \
  --symbols SPY,QQQ
```

This runs ALL gates and produces a manual confirmation checklist. No orders submitted.

### Dry-Run Execution (DEFAULT)

```bash
python3 -m quant_us.cli live-pilot execute \
  --approval-id pilot-001 \
  --envelope-id env-001 \
  --symbols SPY,QQQ,IWM,DIA \
  --dry-run
```

Runs the complete 26-step pipeline without submitting any real orders.

### Real Live Order Execution (EXPLICIT only)

```bash
export QUANT_LIVE_SUBMISSION_ENABLED=true

python3 -m quant_us.cli live-pilot execute \
  --approval-id pilot-001 \
  --envelope-id env-001 \
  --symbols SPY,QQQ,IWM,DIA \
  --execute-live-pilot \
  --confirm-live
```

**WARNING**: This submits a real order to Alpaca Live API.
Only use after all dry-run tests pass and human review complete.

### Check Status

```bash
python3 -m quant_us.cli live-pilot status
```

### View Audit Trail

```bash
python3 -m quant_us.cli live-pilot audit --latest
python3 -m quant_us.cli live-pilot audit --run-id <id>
```

### Emergency Stop

```bash
# Trigger immediate stop
python3 -m quant_us.cli live-pilot emergency-stop-trigger --reason manual_stop

# Check status
python3 -m quant_us.cli live-pilot emergency-stop-status

# Acknowledge
python3 -m quant_us.cli live-pilot emergency-stop-acknowledge

# Resolve
python3 -m quant_us.cli live-pilot emergency-stop-resolve
```

### Stop Live Pilot

```bash
python3 -m quant_us.cli live-pilot stop
```

## Confirming real_submit_count == 0

```bash
python3 -m quant_us.cli live-pilot audit --latest
```

Look for "Real Submits: 0" in the output header.

## When to STOP Immediately

- Emergency stop is triggered
- Reconciliation shows mismatch
- Broker returns unexpected order status
- Data goes stale
- Kill switch activates
- Any gate returns BLOCKED
