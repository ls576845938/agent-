# Phase F.5 — Integration Closure Report

**Date:** 2026-05-07
**Branch:** `phase-f5-integration-closure`
**Status:** COMPLETE — all gates pass, zero regressions

## 1. Objective

Close the gap between backtest-only and live-capable runtime by introducing a unified
lifecycle abstraction that spans paper, shadow-live, and guarded live modes. No real
order reaches a broker in this phase. The deliverable is a test-verified safety shell
ready for Paper Production Loop (Phase F.6).

## 2. What Was Built

### 2.1 Runtime Abstraction Layer (5 new files)

| File | Lines | Purpose |
|---|---|---|
| `quant_us/live/modes.py` | 32 | `RuntimeMode` enum: PAPER / SHADOW_LIVE / LIVE |
| `quant_us/live/runtime_config.py` | 60 | `LiveRuntimeConfig` — frozen dataclass, safe defaults, post-init validation |
| `quant_us/live/runtime_state.py` | 47 | `LiveRuntimeState` + `RuntimeHealth` + lifecycle state machine |
| `quant_us/live/runtime_events.py` | 18 | `RuntimeEvent` — immutable audit event per lifecycle transition |
| `quant_us/live/runtime.py` | 303 | `LiveRuntime` — unified lifecycle shell with central safety gate |

### 2.2 Engine Broker Injection

`EventDrivenBacktestEngine` now accepts an optional `broker` parameter. The broker
is injected rather than hardcoded, enabling:

- **Production:** simulated broker (paper) or real broker (future)
- **Testing:** `RecordingBroker` that asserts `update_market()` call count
- **Shadow:** read-only broker proxy

`engine.connection_health()` reports the active broker name.

New streaming path: `engine.run_streaming(events)` accepts an explicit list of
`MarketEvent` objects, decoupling event generation from the engine. The existing
`engine.run(bars)` path is preserved for backward compatibility.

### 2.3 Strategy Stream Adapter

`Strategy.on_market_event(event, context)` is a new entry point that defaults to
the existing `on_bar()` implementation. Strategies overriding `on_bar()` work
unchanged. Strategies can later override `on_market_event()` for tick-level or
multi-bar batching without breaking existing code.

### 2.4 Unified CLI (`quant_us/cli.py`, 830 lines)

```
quant-us ingest        — download and store market data
quant-us backtest      — canonical event-driven backtest
quant-us paper [--run] — paper trading session (dry-run or submit-to-simulated)
quant-us shadow-live   — full broker connectivity, zero real orders
quant-us reconcile     — 4-dimension ledger vs broker reconciliation
quant-us readiness     — pre-live readiness gate (8 checks)
quant-us live dry-run  — safe paper-mode dry-run
quant-us live start    — gate-blocked (always exits 1 in Phase F.5)
```

Every subcommand that touches orders prints the real-order-submission status
explicitly. The `live start` subcommand is permanently blocked with a clear
`gate-blocked` error message and exit code 1.

### 2.5 Safety Gate Matrix

| Gate | Paper | Shadow-Live | Live |
|---|---|---|---|
| Config refuses `allow_live_orders=True` | enforced | enforced | — |
| Kill switch check before submit | ✓ | ✓ | ✓ |
| Reconciliation-clean required before new orders | ✓ | ✓ | ✓ |
| Duplicate `client_order_id` rejected | ✓ | ✓ | ✓ |
| Reduce-only blocks new buys | ✓ | ✓ | ✓ |
| `confirm_live` required for real orders | — | — | enforced |
| Live readiness gate (8 checks) | — | — | enforced |
| Real broker order submission | never | never | stub (Phase F.6) |

### 2.6 Idempotency

`OrderManagementSystem` persists submitted `client_order_id` values to a JSON
file. On restart, the file is loaded and any duplicate intent is rejected with
reason `duplicate_client_order_id`. This prevents double-submission across
runtime restarts.

## 3. Dependency Fix

67 test failures discovered after dependency audit. Root cause: three packages
missing from the system Python environment.

| Package | Failures Resolved |
|---|---|
| `pyarrow` | 33 |
| `yfinance` | 13 |
| `duckdb` | 2 |
| Other (cascading) | 19 |

After `pip3 install pyarrow yfinance duckdb`: **1167 passed, 0 failed, 13 skipped**.

## 4. Test Coverage

### Phase F.5 Integration Tests (11/11)

```
test_runtime_quality_imports_and_killswitch_public_api   PASSED
test_engine_broker_injection                              PASSED
test_engine_streaming_market_events                       PASSED
test_strategy_stream_adapter_falls_back_to_on_bar         PASSED
test_trading_mode_live_is_gate_blocked                    PASSED
test_shadow_live_cannot_submit_real_order                 PASSED
test_reconciliation_fail_blocks_new_orders                PASSED
test_runtime_restart_no_duplicate_order                   PASSED
test_live_command_default_is_safe                         PASSED
test_live_start_is_gate_blocked                           PASSED
test_paper_runtime_full_day_with_simulated_broker         PASSED
```

### Related Module Tests (50/50)

| Test file | Count | Result |
|---|---|---|
| `test_paper_runtime.py` | 28 | all pass |
| `test_runtime_controls.py` | 11 | all pass |
| `test_strategy_factory.py` | 11 | all pass |

### Full Suite

**1167 passed, 0 failed, 13 skipped** (13 skips are deliberate: CI-only, network-dependent,
or broker-credential-gated tests).

## 5. Architecture Decisions

1. **Frozen config.** `LiveRuntimeConfig` is `frozen=True` — post-init validation
   enforces invariants (e.g., shadow mode cannot set `allow_live_orders`) at
   construction time, not at runtime.

2. **Safety by default.** Every config boolean that could lead to real orders
   defaults to `False`. You must explicitly opt in at three levels:
   `mode=LIVE` + `allow_live_orders=True` + `confirm_live=True`.

3. **Audit trail.** Every lifecycle transition and order decision produces a
   `RuntimeEvent` with a unique ID and UTC timestamp. The event list is the
   single source of truth for post-session audit.

4. **OMS remains the order authority.** `LiveRuntime.submit_orders()` is a
   safety wrapper; `OrderManagementSystem.handle_intent()` is the sole path
   that creates orders. No bypass.

5. **Strategy backward compatibility.** `on_market_event()` delegates to
   `on_bar()` by default. All 6 existing strategies work without changes.

## 6. Phase F.6 Readiness

### Gates satisfied

- [x] Runtime abstraction tested across all three modes
- [x] Broker injection verified (simulated + recording)
- [x] Streaming event path exercised
- [x] CLI subcommands implemented and tested
- [x] Safety gate matrix enforced at config and runtime
- [x] Idempotency across restarts verified
- [x] Zero test regressions (1167/1167)

### Blockers for F.6

- Paper Production Loop: multi-day paper trading with real market data feed
- Shadow Live: 5-day shadow run against Alpaca paper API with reconciliation
- Live stub: replace stub rejection with real broker submission (behind gate)
- Market data loop: wire `MarketDataLoop` to a real data vendor (not mock)

## 7. Risk Register

| Risk | Severity | Mitigation | Status |
|---|---|---|---|
| Accidental real order | Critical | 3-level gate + config validation + hardcoded `submit_real_orders=False` in shadow | Mitigated |
| Double submission on restart | High | Idempotency file + `client_order_id` dedup | Mitigated |
| Reconciliation drift | High | `require_reconciliation_clean` blocks orders | Mitigated |
| Kill switch bypass | Medium | Checked in `submit_orders()` before OMS path | Mitigated |
| Live mode escape | Medium | `live start` exits 1 with gate-blocked message | Mitigated |
