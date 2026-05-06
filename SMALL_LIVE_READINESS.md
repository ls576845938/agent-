# Small-Live Readiness Gate

Go/no-go criteria for entering small-live trading after paper trading validation.

---

## Go Criteria

ALL of the following must be true before small-live trading begins:

1. **Paper 30-day clean**: `consecutive_clean_days >= 30`, `days_completed >= 30`, no errors in any daily result.
2. **OMS idempotency**: OrderManagementSystem accepts `idempotency_path` parameter.
3. **KillSwitch coverage**: KillSwitchConfig has all required thresholds (`max_daily_loss_pct`, `max_drawdown_pct`, `max_consecutive_order_failures`, `max_broker_disconnect_seconds`, `max_data_staleness_seconds`, `max_consecutive_recon_failures`, `max_slippage_bps`).
4. **Recon hard gate**: ReconciliationService implements `reconcile_all` with the `initial_cash` parameter and halt flow.
5. **Fill traceability**: Fill -> Order -> Signal chain is intact (Fill.order_id, Order.signal_id, Signal.signal_id).
6. **Order recovery**: OrderManagementSystem has `recover_from_ledger` method.
7. **Daily report**: `quant_us.monitoring.report.daily_report` exists and is callable.
8. **Monitoring**: MetricsCollector exists with `snapshot()` and `to_prometheus_text()`.

All 8 readiness checks must pass (verified by `quant-us readiness --small-live`).

---

## No-Go Criteria

Small-live trading MUST NOT start if any of the following is true:

- Any CRITICAL blocker from `PAPER_TRADING_AUDIT_REPORT.md` remains unresolved.
- OMS idempotency is not configured (duplicate orders would not be detected).
- KillSwitch coverage is incomplete (at least one threshold not configured).
- Paper trading validation has not achieved 30 consecutive clean days.

---

## Small-Live Parameters

Trading constraints enforced during the small-live phase:

| Parameter | Value |
|-----------|-------|
| Max position size | 1% of account per trade |
| Max concurrent positions | 2 |
| Allowed symbols | SPY, QQQ only |
| Trading session | Regular (9:30 AM -- 4:00 PM ET) only |
| KillSwitch max_daily_loss | 1% |
| Human confirmation | Required at start of each trading day |

These parameters are enforced by:
- `PreTradeRiskEngine` (position limits, symbol allowlist)
- `KillSwitch` (daily loss limit)
- Strategy configuration (symbol universe)
- Session gate in the trading loop (regular session only)

---

## Rollback Plan

If small-live trading must be halted:

1. **Flatten all positions**: Cancel all open orders, then submit market orders to close all positions.
2. **Disable live orders**: Set `OrderManagementSystem.reduce_only = True` to reject any new entry orders.
3. **Revert to paper-only**: Restore the pre-live configuration (no live broker adapter, simulated broker only). Re-run paper validation to confirm the system is healthy before re-entering live.

---

## Sign-Off Checklist

Before flipping the small-live switch, verify each item:

- [ ] OMS idempotency verified (duplicate order IDs rejected, `idempotency_path` functional).
- [ ] KillSwitch tested (trigger at 1% daily loss, confirm orders stop).
- [ ] Reconciliation clean for 5 consecutive days (no position/cash/order/fill diffs).
- [ ] Daily report generated and readable (report exists in ledger root).
- [ ] Monitoring alerts configured (Telegram or equivalent, alert on kill-switch trigger, recon failure, stale data).

---

## Verification

Run the automated gate:

```bash
quant-us readiness --small-live --validation-state data/paper_ledger/validation_state.json
```

Expected output for go:

```
=== SMALL-LIVE READINESS GATE ===
All 8 checks PASSED.
Paper 30-day clean: 30/30 consecutive clean days, 30/30 days completed, no errors.
RESULT: GO for small-live trading.

=== SMALL-LIVE PARAMETERS ===
Max position size: 1% of account
Max concurrent positions: 2
Allowed symbols: SPY, QQQ
Session: Regular only
KillSwitch max daily loss: 1%
Human confirmation: Required daily
```
