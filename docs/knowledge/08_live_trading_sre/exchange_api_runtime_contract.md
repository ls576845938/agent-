# Exchange API Runtime Contract

Purpose: define runtime obligations for exchange adapters before any BTC strategy can trade through them.

## Adapter responsibilities

An exchange adapter must handle:

- REST market data;
- WebSocket market data;
- private order/fill/account streams;
- server time and clock offset;
- symbol and instrument metadata;
- price/size precision;
- min notional and order filters;
- rate limits and order-rate limits;
- order placement, amend, cancel, cancel-all;
- idempotent client order ids;
- execution report normalization;
- reconnect and gapfill;
- error code normalization;
- account, position, and ledger reconciliation.

## Hard rules

1. Strategy code must never call exchange APIs directly.
2. All orders must include a deterministic `client_order_id`.
3. Every outbound order request and inbound exchange response must be persisted.
4. Order state must be event-sourced or otherwise replayable.
5. REST acknowledgements and WebSocket private events may arrive out of order; the state machine must tolerate this.
6. Rate-limit usage must be observable and capped before the exchange bans or throttles the account.
7. Exchange metadata must be refreshed and versioned before each trading session.
8. API changelogs are runtime risk. A live adapter must track last-reviewed documentation date.

## Required runtime state

- `exchange_status`: `ok`, `degraded`, `cancel_only`, `data_stale`, `outage`, `maintenance`, `unknown`
- `public_ws_status`
- `private_ws_status`
- `rest_status`
- `server_time_offset_ms`
- `rate_limit_budget_remaining`
- `order_rate_budget_remaining`
- `last_market_data_time`
- `last_private_event_time`
- `last_reconciliation_time`
- `unreconciled_order_count`
- `unreconciled_fill_count`

## Fail-closed triggers

No new position-increasing order when:

- public market data is stale;
- private order stream is disconnected and not reconciled;
- REST order endpoint is degraded;
- server time offset exceeds tolerance;
- exchange metadata is missing;
- symbol precision/filter validation fails;
- rate-limit budget is below safety threshold;
- mark/index price is unavailable for a perp position;
- account balance or position cannot be reconciled.

## Order validation checklist

Before submit:

- instrument enabled;
- account mode compatible;
- position mode compatible;
- margin mode compatible;
- price precision valid;
- size precision valid;
- min notional satisfied;
- reduce-only flag correct;
- post-only flag intentional;
- leverage within policy;
- liquidation buffer after order acceptable;
- rate-limit budget available;
- risk engine approved.

## Evidence required for live promotion

- adapter integration tests against sandbox/demo where available;
- order-state replay test;
- reconnect/gapfill test;
- rate-limit test;
- precision/filter rejection test;
- reconciliation test;
- cancel-all emergency test;
- dry-run report with zero live orders;
- paper-trading report with real exchange data and simulated orders.

