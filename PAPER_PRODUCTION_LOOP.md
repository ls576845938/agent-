# Paper Production Loop Guide

## Quick Start

### 3-Day Smoke Test

```bash
python3 -m quant_us.cli live start --simulate-days 3 --symbols SPY --strategy etf_rotation --bar-size 1d
```

Expected output:
```
real_order_submission: DISABLED (simulated paper mode, 3 days)
Warmup: 120 bars loaded for strategy context
[  1/3] 2026-05-05 ... SKIPPED_NO_SIGNAL  PnL=$+0.00  fills=0/0  clean=0
[  2/3] 2026-05-06 ... RECON_PASS  PnL=$+5.23  fills=2/2  clean=1
[  3/3] 2026-05-07 ... SKIPPED_NO_SIGNAL  PnL=$+0.00  fills=0/0  clean=2
```

### 30-Day Simulated Loop

```bash
python3 -m quant_us.cli live start --simulate-days 30 \
  --symbols SPY,QQQ,IWM,DIA \
  --strategy etf_rotation \
  --bar-size 1d \
  --initial-cash 100000
```

## Status Labels

| Status | Meaning | Clean Streak? |
|--------|---------|---------------|
| RECON_PASS | Trades executed, reconciliation clean | Advances |
| SKIPPED_NO_SIGNAL | No signals today (strategy idle) | Maintains (not broken) |
| DATA_INSUFFICIENT | No bars available for this date | Breaks |
| RECON_FAIL | Ledger vs broker mismatch | Breaks |
| BLOCKED_BY_KILL_SWITCH | Kill switch active, orders blocked | Breaks |
| ERROR | Unexpected exception | Breaks |

## validation_state.json

Generated at `data/reports/paper_production/validation_state.json`:

```json
{
  "generated_at": "2026-05-08T04:00:00+00:00",
  "days_requested": 30,
  "days_run": 30,
  "days_passed": 28,
  "days_data_insufficient": 0,
  "recon_pass_count": 28,
  "recon_fail_count": 0,
  "skipped_no_signal_days": 2,
  "duplicate_order_count": 0,
  "kill_switch_events": 0,
  "consecutive_clean_days": 28,
  "errors_total": 0,
  "final_equity": 105000.0,
  "final_cash": 25000.0,
  "daily_results": [...]
}
```

### Readiness Check After 30 Days

```bash
python3 -m quant_us.cli readiness --profile paper \
  --force-rerun \
  --validation-state data/reports/paper_production/validation_state.json
```

## When to Enter Real Alpaca Paper

Prerequisites:
1. 30 consecutive clean days (RECON_PASS or SKIPPED_NO_SIGNAL)
2. 0 RECON_FAIL days
3. 0 duplicate orders
4. readines --profile paper 全部 PASS
5. Alpaca paper API credentials set (APCA_API_KEY_ID, APCA_API_SECRET_KEY)

## When to Enter Real Live

NEVER without:
1. All paper prerequisites met
2. 5-day shadow-live validation clean
3. QUANT_LIVE_SUBMISSION_ENABLED=true
4. --confirm-live --allow-live-orders
5. readiness --profile live ALL PASS
6. Human approval
