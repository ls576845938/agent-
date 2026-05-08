# Paper Trading Runbook

## 1. Configure Alpaca Paper Credentials

```bash
export APCA_API_KEY_ID="PK..."      # Your Alpaca Paper API Key ID
export APCA_API_SECRET_KEY="..."    # Your Alpaca Paper API Secret Key
```

Verify you're using the **Paper** (not Live) API keys from https://app.alpaca.markets/paper/dashboard.

## 2. Credential Check

```bash
python3 -m quant_us.cli readiness --profile paper --check-credentials
```

Expected output:
```
============================================================
  Alpaca Paper Credential Check
============================================================
  Key ID:    ****XXXX
  Endpoint:  https://paper-api.alpaca.markets
  Account:   abcd...wxyz
  Equity:    $100,000.00
  Cash:      $50,000.00
  Positions: 0 | Open Orders: 0
  RESULT: PASS — Paper account reachable, credentials valid
============================================================
```

## 3. Smoke Test

```bash
python3 -m quant_us.cli paper smoke-test --symbols SPY,QQQ,IWM,DIA --strategy trend_momentum --bar-size 1d
```

This runs 5 read-only checks: account, positions, orders, market data, signal generation. **No orders submitted.**

## 4. Readiness Check

```bash
python3 -m quant_us.cli readiness --profile paper --force-rerun \
  --validation-state data/reports/paper_production/validation_state.json
```

All 11 checks must PASS before paper trading.

## 5. Dry-Run Paper Start

```bash
python3 -m quant_us.cli paper start --symbols SPY,QQQ,IWM,DIA --strategy trend_momentum --bar-size 1d
```

Default: dry-run mode. Runs smoke test, no orders submitted.

## 6. Enable Paper Orders

```bash
python3 -m quant_us.cli paper start --symbols SPY,QQQ,IWM,DIA --enable-paper-orders
```

**WARNING:** This submits orders to Alpaca Paper API. Only proceed after:
- Credential check PASS
- Smoke test PASS
- Readiness paper profile 11/11 PASS
- Human confirmation

## 7. Daily Reports

```bash
ls data/paper_ledger/daily_reports/
cat data/paper_ledger/daily_reports/daily_report_2026-05-08.json
```

## 8. Reconciliation

```bash
python3 -m quant_us.cli reconcile --broker alpaca --initial-cash 100000
```

Reports: `data/paper_ledger/reconciliation/recon_*.json`

## 9. Stop the System

Paper production runs until:
- Market close (session end)
- max_runtime_hours reached (default: 8h)
- Kill switch triggered
- SIGINT (Ctrl+C)

## 10. Troubleshooting

| Issue | Action |
|-------|--------|
| BROKER_ERROR | Check Alpaca API status, verify credentials, retry |
| RECON_FAIL | Check `data/paper_ledger/reconciliation/` for detailed diff. System auto-enters reduce_only mode. |
| Duplicate order warning | Check `data/paper_ledger/.idempotency.json`. Restart should recover. |
| DATA_STALE | Check internet connection. Verify yfinance/Alpaca data feed. |
