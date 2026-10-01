# External Engine Architecture Study

Date: 2026-07-08

Scope: NautilusTrader, QuantConnect LEAN, and Zipline Reloaded are reference
engines for architecture study only. They do not replace `quant_us`, do not
define promotion gates, and do not unlock paper or live trading.

## Borrowing Boundary

The local system remains authoritative for:

- data lineage and PIT evidence;
- strategy interface;
- event-driven ledger backtest;
- cost, slippage, liquidity, and capacity stress;
- promotion gates;
- forward observation;
- paper/live safety.

Reference engines may influence module design, naming, replay semantics, and
operator workflow. Their native backtest reports are not accepted as local
validation evidence.

## NautilusTrader Mapping

Useful concepts:

- event bus and deterministic replay;
- cache separation from execution adapters;
- order lifecycle and fill semantics;
- market-data adapter boundary;
- account/position state reconciliation.

Local mapping:

| Nautilus concept | Local target |
| --- | --- |
| event-driven engine | `quant_us.backtest.engine`, `quant_us.backtest.replay` |
| order state machine | `quant_us.execution.order_lifecycle` |
| adapter boundary | `quant_us.execution.broker_base`, `quant_us.data.connectors` |
| deterministic replay | ledger-first backtest and paper reconciliation reports |
| account cache | broker-state sync and portfolio snapshots |

Borrowing ticket:

Create an OMS replay field audit for US equities mirroring the existing BTC
audit style: every order/fill/snapshot field must have a local source of truth,
idempotency key, and replay rule.

## QuantConnect LEAN Mapping

Useful concepts:

- algorithm lifecycle separation;
- brokerage/data normalization model;
- scheduled events;
- warm-up periods;
- report generation pipeline;
- CLI-driven reproducible runs.

Local mapping:

| LEAN concept | Local target |
| --- | --- |
| algorithm lifecycle | strategy `Signal -> TargetPosition` contract |
| scheduled events | `USEquityCalendar`, rebalance scheduler, forward observation |
| normalization mode | local adjustment policy and PIT replay |
| brokerage model | broker adapter + risk preflight, not strategy code |
| result packet | standardized research and promotion reports |

Borrowing ticket:

Add a US ETF run manifest checklist matching LEAN-style lifecycle stages:
initialize, warm-up, data-ready, signal, portfolio, execution simulation,
ledger reconciliation, report finalization.

## Zipline Reloaded Mapping

Useful concepts:

- trading calendars and sessions;
- data bundles;
- asset finder and adjustments;
- Pipeline-style factor computation;
- event-driven daily/minute backtests.

Local mapping:

| Zipline Reloaded concept | Local target |
| --- | --- |
| exchange calendar | `quant_us.core.calendar` using external calendar providers |
| data bundle | local PIT vendor bundle and data manifests |
| asset finder | future PIT membership / symbol mapping layer |
| adjustment reader | local `adjustment_replay.csv` import and validation |
| Pipeline factors | `quant_us.factors` and research feature snapshots |

Borrowing ticket:

Design a local ETF-only bundle registry first; defer single-stock asset-finder
work until a licensed PIT stock data bundle is available.

## Current Recommendation

Do not migrate the US equity system to any of these engines. The immediate
highest-value borrowing path is:

1. keep external calendar providers inside `quant_us.core.calendar`;
2. keep QuantStats downstream of ledger-derived returns;
3. keep PyPortfolioOpt downstream of local forecasts and upstream of local risk;
4. keep vectorbt as parameter-screening evidence only;
5. keep Qlib/OpenBB as research surfaces;
6. use Nautilus/LEAN/Zipline to harden event/replay/data-bundle boundaries.
