# Shadow Live Architecture (G2)

## Overview

Shadow Live is a read-only live validation system that verifies the full quant pipeline against a real brokerage account without ever submitting real orders.

```
Signal → TargetPosition → OrderIntent → Risk → OMS → ShadowOrder (would_submit=True, real_submit=False)
```

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    ShadowLiveOrchestrator                     │
│  bootstrap → readiness → credentials → reconcile →           │
│  market_data → signals → targets → intents → risk →          │
│  shadow_orders → shadow_fills → ledger → reports → shutdown  │
└──────────┬──────────────┬──────────────────┬────────────────┘
           │              │                  │
    ┌──────▼──────┐ ┌─────▼──────┐ ┌────────▼────────┐
    │ReadOnlyLive │ │ Shadow     │ │ ShadowLive      │
    │BrokerProxy  │ │ Models     │ │ Orchestrator    │
    │(blocks all  │ │(ShadowOrder│ │(lifecycle mgmt) │
    │ write ops)  │ │ ShadowFill │ │                 │
    └──────┬──────┘ │ ShadowLedger│ └────────────────┘
           │        │ StateDiff)  │
    ┌──────▼──────┐ └─────────────┘
    │ AlpacaBroker│
    │ (live API)  │
    └─────────────┘
```

## Core Components

### ReadOnlyLiveBrokerProxy (`quant_us.live.readonly_live_broker`)

Wraps a real `AlpacaBroker` and blocks ALL write operations.

**Allowed (read-only):**
- `get_account()` — live account state
- `get_positions()` — live positions
- `get_open_orders()` — live open orders
- `get_fills()` / `get_fills_readonly()` — live fills
- `get_latest_bars()` — market data
- `get_clock()` / `get_calendar()` — market clock
- `health_check()` — connection health

**Forbidden (raise RuntimeError):**
- `submit_order()`
- `cancel_order()`
- `replace_order()`
- `close_position()`
- `close_all_positions()`

### LiveEndpointGuard

Enforces endpoint isolation:
- Paper profile → paper endpoint only
- Shadow-live → live endpoint only with explicit allow
- Live profile → default-blocked

### Shadow Models (`quant_us.live.shadow_models`)

- **ShadowOrder**: Captures what the system would have submitted (would_submit=True, real_submit=False). Full traceability: signal_id → target_position_id → order_intent_id → risk_check_id.
- **ShadowFill**: Simulated fill with slippage/commission model info.
- **ShadowLedger**: Tracks shadow portfolio state (cash, positions, equity, PnL).
- **StateDiff**: Compares paper vs shadow vs live positions.

### ShadowLiveOrchestrator (`quant_us.live.shadow_orchestrator`)

Lifecycle manager for a shadow-live run. Executes the full pipeline:
1. bootstrap() — init calendar, kill switch
2. check_shadow_readiness() — verify prereqs
3. check_live_readonly_credentials() — connect to live API
4. reconcile_live_readonly_on_start() — reconcile state
5. load_market_data() — fetch bars
6. calculate_signals() — strategy signals
7. build_target_positions() — target positions
8. generate_order_intents() — order intents
9. run_risk_checks() — pre-trade risk
10. generate_shadow_orders() — shadow orders (would_submit=True)
11. simulate_shadow_fills() — simulated fills
12. update_shadow_ledger() — update shadow portfolio
13. compare_with_paper_state() — paper vs shadow diff
14. compare_with_live_readonly_state() — live vs shadow diff
15. generate_daily_shadow_report() — daily report
16. write_shadow_journal() — journal entry
17. shutdown_safely() — persist state

### MarketDataParityChecker (`quant_us.live.market_data_parity`)

Compares market data across sources:
- Local cleaned bars
- yfinance / historical source
- Alpaca paper data
- Alpaca live readonly data

Rules:
- close diff > 10 bps → WARN
- close diff > 100 bps → CRITICAL (block shadow orders)
- timestamp stale > 60s → WARN
- timestamp stale > 300s → CRITICAL

### ShadowValidationController (`quant_us.live.shadow_validation_controller`)

Manages multi-day shadow-live validation (5-10 trading days).

Tracks:
- days_completed, clean_days, warn_days, failed_days
- shadow_order_count, shadow_fill_count
- real_submit_count (must be 0)
- data_parity_warn_count, recon_warn_count
- incident_count
- manual_review_required

### LivePilotReadinessDossier (`quant_us.live.live_pilot_dossier`)

Generates the G2→G3 transition dossier containing:
1. Paper 30-day summary
2. Shadow Live 5-day summary
3. Strategy Freeze
4. Risk Limits
5. Live Safety verification
6. Go / No-Go decision

## Safety Invariants

1. **NO real order is ever submitted through shadow-live.**
2. **ReadOnlyLiveBrokerProxy blocks all write operations with RuntimeError.**
3. **LiveRuntimeConfig rejects shadow_live + allow_live_orders.**
4. **ShadowOrchestratorConfig requires readonly=True.**
5. **QUANT_LIVE_SUBMISSION_ENABLED=true does NOT enable shadow_live orders.**
6. **All shadow orders have real_submit=False.**
7. **Audit journal proves no_real_order_submitted.**
8. **Endpoint guard prevents paper/live endpoint confusion.**
