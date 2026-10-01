# Exchange Outage Playbook

Purpose: define how the system reacts when a crypto venue enters outage, maintenance, cancel-only mode, degraded quoting, or data-pipeline failure.

## Outage states

- `normal`: all required public/private/data/order paths are healthy.
- `degraded`: some paths are slow or stale, but reconciliation is possible.
- `data_stale`: market data cannot support new decisions.
- `private_stream_down`: order/fill/account stream unavailable.
- `order_entry_down`: cannot submit/amend/cancel reliably.
- `cancel_only`: new orders blocked, cancellation allowed.
- `exchange_outage`: venue cannot be trusted for trading.
- `unknown`: system cannot classify state safely.

## Immediate response

1. Freeze new position-increasing orders.
2. Preserve raw logs and state snapshot.
3. Reconcile orders, fills, balances, and positions if possible.
4. Decide whether reduce-only or cancel-all is safer than holding stale orders.
5. Switch dashboards and reports to outage mode.
6. Emit a human-visible incident event.

## Cancel-only mode

If the venue is cancel-only:

- cancel stale maker orders;
- block new open-risk orders;
- allow only explicitly approved reduce-only actions;
- log whether cancels are acknowledged;
- keep position valuation separate from order-management status.

## Recovery and reopen

Trading may resume only after:

- public market data freshness passes;
- private order stream is connected or reconciled;
- REST order endpoint passes health check;
- account and positions match exchange snapshot;
- open orders are known and intentional;
- reference price passes cross-venue checks;
- risk engine recomputes liquidation and exposure;
- incident record is created.

## Post-incident review

Every outage must create an incident review with:

- timeline;
- affected venues;
- affected instruments;
- affected strategies;
- blocked orders;
- stale orders;
- missed fills;
- reconciliation differences;
- data gaps;
- PnL impact estimate;
- rule changes or tests added.

## Architecture implications

1. Matching-engine, data-pipeline, and broker-adapter failure are different failure domains.
2. A venue outage can affect data correctness even if no order is submitted.
3. Cloud/vendor outages can propagate through Kafka, queues, databases, and dashboards.
4. The system needs runbooks and production failover exercises before live size increases.
5. Personal trading systems do not need institutional complexity, but they do need deterministic fail-closed behavior.

