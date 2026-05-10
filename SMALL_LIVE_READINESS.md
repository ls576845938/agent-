# Small-Live Review-Only Design Freeze

Go/no-go criteria for micro-live human review after paper trading validation.
This document is a design freeze and human review artifact. It is not execution approval and not a start/run/submit procedure.

---

## Go Criteria

ALL of the following must be true before any micro-live review can be considered:

1. **Paper 30-day clean**: `consecutive_clean_days >= 30`, `days_completed >= 30`, no errors in any daily result.
2. **OMS idempotency**: OrderManagementSystem accepts `idempotency_path` parameter.
3. **KillSwitch coverage**: KillSwitchConfig has all required thresholds (`max_daily_loss_pct`, `max_drawdown_pct`, `max_consecutive_order_failures`, `max_broker_disconnect_seconds`, `max_data_staleness_seconds`, `max_consecutive_recon_failures`, `max_slippage_bps`).
4. **Recon hard gate**: ReconciliationService implements `reconcile_all` with the `initial_cash` parameter and halt flow.
5. **Fill traceability**: Fill -> Order -> Signal chain is intact (Fill.order_id, Order.signal_id, Signal.signal_id).
6. **Order recovery**: OrderManagementSystem has `recover_from_ledger` method.
7. **Daily report**: `quant_us.monitoring.report.daily_report` exists and is callable.
8. **Monitoring**: MetricsCollector exists with `snapshot()` and `to_prometheus_text()`.
9. **Manual approval**: human approval defaults fail closed until explicitly approved.
10. **Allowlist**: symbol allowlist surfaces exist in strategy freeze, dossier safety, and risk envelope evidence.
11. **Max notional / order count**: conservative max order notional and daily order-count caps are present.
12. **Reduce-only exit plan**: rollback instructions remain reduce-only and require manual review.
13. **Emergency stop**: trigger / acknowledge / resolve / status lifecycle is present.
14. **Endpoint guard**: live endpoint access remains behind `ReadOnlyLiveBrokerProxy`.
15. **Review-only defaults**: `allow_live_orders=False`, `confirm_live=False`, read-only wording explicit.

All checks must pass for readiness review. Passing does not authorize automatic submission or any automatic live execution loop.

---

## No-Go Criteria

Micro-live review MUST remain blocked if any of the following is true:

- Any CRITICAL blocker from `PAPER_TRADING_AUDIT_REPORT.md` remains unresolved.
- OMS idempotency is not configured (duplicate orders would not be detected).
- KillSwitch coverage is incomplete (at least one threshold not configured).
- Paper trading validation has not achieved 30 consecutive clean days.

---

## Micro-Live Review Parameters

Trading constraints documented for review-only assessment:

Design freeze metadata for this review-only scope:

| Field | Value |
|-------|-------|
| version | `micro-live-review-only-v1` |
| frozen | `true` |
| scope | `review_only` |
| no_continuous_loop | `true` |
| manual_approval_required | `true` |
| max_symbols | `2` |
| max_notional | `100.0` |
| max_orders | `3` |

| Parameter | Value |
|-----------|-------|
| Max position size | 1% of account per trade |
| Max concurrent positions | 2 |
| Max daily order count | 3 |
| Allowed symbols | SPY, QQQ only |
| Trading session | Regular (9:30 AM -- 4:00 PM ET) only |
| KillSwitch max_daily_loss | 1% |
| Human confirmation | Required at start of each trading day |
| Reduce-only exit plan | Required before review can pass |
| Endpoint mode | Read-only guarded |

These parameters are enforced by:
- `PreTradeRiskEngine` (position limits, symbol allowlist)
- `KillSwitch` (daily loss limit)
- Strategy configuration (symbol universe)
- Session gate in the trading loop (regular session only)

---

## Rollback Plan

If the micro-live review path must be halted:

1. **Review reduce-only exit plan**: confirm rollback instructions only permit exits and block new entries.
2. **Disable live orders**: keep `allow_live_orders=False` and preserve endpoint guard state.
3. **Revert to paper-only**: restore the pre-live configuration and re-run paper validation before any future review.

---

## Sign-Off Checklist

Before any human review decision, verify each item:

- [ ] OMS idempotency verified (duplicate order IDs rejected, `idempotency_path` functional).
- [ ] KillSwitch tested (trigger at 1% daily loss, confirm orders stop).
- [ ] Reconciliation clean for 5 consecutive days (no position/cash/order/fill diffs).
- [ ] Daily report generated and readable (report exists in ledger root).
- [ ] Monitoring alerts configured (Telegram or equivalent, alert on kill-switch trigger, recon failure, stale data).
- [ ] Manual approval artifact exists and is explicitly approved by a named reviewer.
- [ ] Symbol allowlist is documented and matches the risk envelope.
- [ ] Max order notional and max daily order count are explicitly capped.
- [ ] Emergency stop is armed and rollback instructions are reduce-only.
- [ ] Review output clearly states design freeze / human review only / no execution approval.

---

## Verification

Run the automated gate:

```bash
quant-us readiness --small-live --validation-state data/paper_ledger/validation_state.json
```

Expected output for review pass:

```
=== SMALL-LIVE READINESS GATE ===
All review-only checks PASSED.
Paper 30-day clean: 30/30 consecutive clean days, 30/30 days completed, no errors.
RESULT: READY FOR HUMAN REVIEW ONLY.

=== MICRO-LIVE REVIEW PARAMETERS ===
Max position size: 1% of account
Max concurrent positions: 2
Max daily order count: 3
Allowed symbols: SPY, QQQ
Session: Regular only
KillSwitch max daily loss: 1%
Human confirmation: Required daily
Submission ready: false
```
