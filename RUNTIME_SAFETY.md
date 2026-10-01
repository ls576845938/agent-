# Runtime Safety Rules

## Mode Summary

| Mode | Market Data | Order Submission | Broker | Safety Gates |
|------|-------------|------------------|--------|--------------|
| **PAPER** | Real (yfinance/Alpaca) | SimulatedBroker | In-memory | KillSwitch, Recon, OMS Risk |
| **SHADOW_LIVE** | Real (Alpaca) | PaperBroker only | Real broker read-only | KillSwitch, Recon, OMS Risk, ReadOnlyBrokerProxy |
| **LIVE** | Real (Alpaca) | Disabled by default on this surface | Real broker | Review-only gate, runtime shell, explicit fail-closed flags |

## submit_orders() Safety Rules

All order submission passes through `LiveRuntime.submit_orders()` which enforces:

### Gate Order (checked sequentially)
1. **Live mode gate** — `_live_order_block_reasons()`
2. **OMS configured** — rejects if `self.oms is None`
3. **Kill switch** — rejects all if active
4. **Reconciliation** — rejects all if not clean (when `require_reconciliation_clean=True`)
5. **Duplicate client_order_id** — rejects individual duplicate intents
6. **OMS risk** — `PreTradeRiskEngine` validates each intent

### Live Mode Requirements
All conditions below are necessary but still not sufficient for any future real submission:
1. `live_readiness_gate` PASS (18 review-only checks)
2. `config.allow_live_orders == True`
3. `config.confirm_live == True`
4. `config.live_submission_enabled == True`
5. `QUANT_LIVE_SUBMISSION_ENABLED=true` in environment
6. `LiveOrderSubmissionGate.check()` still returns `REQUIRES_MANUAL_REVIEW` on this repo surface

Current repository rule: micro-live readiness output is a design freeze for human review only, not execution approval, and `submission_ready=false`.

## Simulated Paper Production Loop (Phase F.7)

`live start --simulate-days N` runs an accelerated N-day paper production loop using historical data.

- **No real orders** — runs against SimulatedBroker only
- **No real market data** — uses cached historical yfinance data
- **Full lifecycle per day** — market data → signals → positions → risk → OMS → fill → reconcile → report
- **Generates validation_state.json** — feed to `live readiness --validation-state <path>` for readiness gate

```bash
python3 -m quant_us.cli live start --simulate-days 30 --symbols SPY,QQQ
```

## Promotion Gate Re-evaluation (Phase F.7)

The CLI readiness command now supports:
- `--force-rerun`: force fresh evaluation, ignore stale results
- `--no-cache`: skip persisted manifest reads

Each run outputs `run_id`, `generated_at`, and `gate_version` for traceability.
Promotion gate manifests now include `gate_version`, `config_version`, `generated_at` fields.

If any condition fails, orders are rejected with a clear reason string.

## Idempotency (Anti-Duplicate Orders)

Two layers prevent duplicate order submission:

1. **LiveRuntime._submitted_order_ids** — in-memory set, checked before OMS. Session-scoped.
2. **OMS._client_order_ids** — persisted to JSON file at `idempotency_path`. Survives restarts.

On restart, `oms.load_idempotency()` reads the file. `oms.recover_from_ledger()` scans `orders.jsonl` to rebuild the set.

## Kill Switch

7 trigger conditions, all configurable via `KillSwitchConfig`:

| Trigger | Default Threshold |
|---------|-------------------|
| Daily loss | -3% of day-start equity |
| Drawdown | -12% from peak |
| Consecutive order failures | 3 |
| Broker disconnect | 120 seconds |
| Data staleness | 600 seconds |
| Consecutive reconciliation failures | 2 |
| Slippage | 200 bps |

Once tripped, the kill switch stays tripped until the next trading session (`reset_daily()`). Manual trips (`trip()`) are permanent.

## Reconciliation Gate

`ReconciliationService.reconcile_all()` checks 4 dimensions:
- **Cash**: ledger-reconstructed vs broker-reported
- **Positions**: per-symbol quantity comparison (1e-6 tolerance)
- **Orders**: status and quantity comparison
- **Fills**: fill_id, quantity, price comparison

If breaks are detected:
- `halt_new_orders = True` — blocks all new order submission
- JSON report written to `{ledger_root}/reconciliation/`
- Optional Telegram alert sent

## Live Readiness Gate

Review-only checks in `LiveReadinessGate.check_all()` include:

1. `paper_30_day_clean` — 30 consecutive clean paper trading days
2. `oms_idempotency` — OMS accepts idempotency_path
3. `kill_switch_coverage` — All 7 thresholds configured
4. `recon_hard_gate` — ReconciliationService has reconcile_all
5. `fill_traceability` — Fill → Order → Signal chain
6. `order_recovery` — OMS has recover_from_ledger
7. `daily_report` — Daily report module exists
8. `monitoring` — MetricsCollector with snapshot + prometheus
9. `broker_credentials` — Alpaca API keys reachable
10. `data_vendor_health` — Data vendor returns bars
11. `telegram_connectivity` — Telegram alerts configured
12. `manual_approval_required` — approval defaults fail closed until explicitly approved
13. `allowlist_surface` — allowlist evidence present in dossier / risk envelope
14. `micro_live_limits` — max notional and order-count caps present
15. `reduce_only_exit_plan` — rollback plan exists for reduce-only exits
16. `emergency_stop_readiness` — emergency stop lifecycle present
17. `endpoint_guard` — read-only live endpoint guard present
18. `review_only_defaults` — `allow_live_orders=False`, `confirm_live=False`, review-only wording

Design freeze metadata emitted by readiness and dossier payloads:
- `version=micro-live-review-only-v1`
- `hash=<sha256 of canonical freeze payload>`
- `frozen=true`
- `scope=review_only`
- `no_continuous_loop=true`
- `manual_approval_required=true`
- `max_symbols=2`
- `max_notional=100.0`
- `max_orders=3`

Manual approval artifacts must bind the dossier/design-freeze `version` / `hash` / `scope`, and remain `review_only=true` with `execution_authorized=false`. A binding mismatch invalidates the approval artifact rather than authorizing execution.
