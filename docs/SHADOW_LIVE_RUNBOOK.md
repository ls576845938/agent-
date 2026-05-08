# Shadow Live Runbook

## What is Shadow Live?

Shadow Live is the G2 validation phase that connects to a **real live brokerage account** but operates in **read-only mode**. It runs the full quant pipeline (signal → target → risk → OMS) but generates **shadow orders** instead of real orders.

**Core invariant: NO real order is ever submitted.**

## Prerequisites

- Phase G1 Paper 30-Day Validation completed
- Alpaca live trading account (read-only access sufficient)
- API key with read access to the live account

## Configuration

### 1. Set Live Read-Only Credentials

```bash
export APCA_API_KEY_ID="your_live_key_id"
export APCA_API_SECRET_KEY="your_live_secret_key"
```

### 2. Verify Credentials (No Orders)

```bash
python3 -m quant_us.cli readiness --profile shadow_live --force-rerun
```

## Operations

### Run Shadow Readiness Check

```bash
python3 -m quant_us.cli readiness --profile shadow_live --force-rerun
```

This runs 12 safety checks including:
- Paper 30-day validation
- Live readonly credentials
- Endpoint readonly guard
- No live order path verification
- ReadOnlyBrokerProxy verification
- Data parity smoke test
- Strategy whitelist
- Risk/OMS/Reconciliation
- Shadow journal writable
- Incident report writable
- Live submission shadow safety

### Run Data Parity Check

```bash
python3 -m quant_us.cli shadow-live data-parity --symbols SPY,QQQ,IWM,DIA
```

Compares data across sources: local, yfinance, Alpaca paper, Alpaca live.
Generates report at `data/shadow_ledger/data_parity_report.json`.

### Run Shadow-Live 5-Day Validation

```bash
python3 -m quant_us.cli shadow-live start \
  --symbols SPY,QQQ,IWM,DIA \
  --strategy etf_rotation \
  --days 5 \
  --readonly
```

### Check Status

```bash
python3 -m quant_us.cli shadow-live status
```

### View Shadow Journal

```bash
python3 -m quant_us.cli shadow-live audit --latest
```

### View Latest Report

```bash
python3 -m quant_us.cli shadow-live report --latest
```

### Generate Live Pilot Readiness Dossier

```bash
python3 -m quant_us.cli shadow-live readiness-dossier \
  --output reports/live_readiness_dossier.md
```

## Safety Verification

### Confirm real_submit_count == 0

```bash
python3 -m quant_us.cli shadow-live status
```

Look for: `Real Submits: **0** (must be 0)`

### Verify Audit Trail

```bash
python3 -m quant_us.cli shadow-live audit --latest
```

All shadow orders have `would_submit: true, real_submit: false`.

## Handling Issues

### Data Parity WARN

1. Check the data parity report: `data/shadow_ledger/data_parity_report.json`
2. Verify data sources are healthy
3. If stale data is isolated to one source, continue with WARN
4. If multiple sources are stale, pause and investigate

### Manual Review Required

If `manual_review_required` is true:
1. Check the shadow journal for incident entries
2. Review reconciliation failures
3. Check data parity warnings
4. Resolve issues before promoting to live

### Shadow Orders == 0

1. Check strategy signals are generating
2. Verify market data is fresh
3. Review risk checks — orders may be blocked by risk constraints
4. Check kill switch status

## Important Safety Notes

- **NEVER** set QUANT_LIVE_SUBMISSION_ENABLED=true during shadow-live
- Shadow-live is read-only even if the env var is accidentally set
- All write operations to the live broker are blocked at the proxy level
- The ReadOnlyBrokerProxy raises RuntimeError on any write attempt
