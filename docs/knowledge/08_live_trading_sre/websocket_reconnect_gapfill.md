# WebSocket Reconnect And Gapfill Rules

Purpose: make BTC market-data and private-order streams recoverable and auditable under disconnections, packet gaps, and exchange maintenance.

## Stream classes

- public trades;
- public order book;
- public klines/candles;
- mark/index/funding streams;
- private orders;
- private fills;
- private balances;
- private positions.

Each class must have its own freshness threshold and recovery procedure.

## Core rules

1. WebSocket is not a database. Persist raw messages or normalized events before use.
2. Public and private streams must have independent heartbeats.
3. A reconnect without gapfill is not recovery.
4. A candle must not be treated as final until the exchange or aggregator marks it final, or the local bar-builder policy finalizes it.
5. Order book streams must validate sequence numbers when the venue provides them.
6. If sequence validation is unavailable, use depth checksum, snapshot refresh, or conservative stale-state policy.
7. After reconnect, orders and positions must be reconciled through REST or private snapshots.
8. If gapfill fails, the trading state becomes `data_stale` or `unknown`; no new risk-increasing order is allowed.

## Public market-data recovery

Required steps:

1. Mark stream status `degraded`.
2. Stop signal generation for affected instruments.
3. Fetch fresh snapshot or REST backfill.
4. Replay missing events if available.
5. Validate timestamp continuity and sequence continuity.
6. Rebuild derived bars/features.
7. Emit a `DataGapRecovered` event with gap duration and method.
8. Resume trading only after freshness and reference-price checks pass.

## Private stream recovery

Required steps:

1. Mark private stream status `degraded`.
2. Block new non-reduce-only orders.
3. Fetch open orders.
4. Fetch recent fills.
5. Fetch balances and positions.
6. Reconcile local state.
7. Cancel unknown stale orders if policy requires.
8. Emit `PrivateStreamRecovered`.
9. Resume only when all orders and fills are accounted for.

## Gap event schema

Every gap must be logged with:

- `venue`
- `stream`
- `instrument_id`
- `gap_start_time`
- `gap_end_time`
- `duration_ms`
- `last_good_sequence`
- `first_recovered_sequence`
- `recovery_method`
- `events_backfilled`
- `bars_rebuilt`
- `orders_reconciled`
- `fills_reconciled`
- `trading_blocked`

## Promotion gate

A BTC system cannot enter live trading unless automated tests simulate:

- public stream disconnect;
- private stream disconnect;
- sequence gap;
- stale candle;
- duplicate messages;
- out-of-order private order events;
- REST backfill failure;
- reconnect during open position;
- reconnect during open order.

