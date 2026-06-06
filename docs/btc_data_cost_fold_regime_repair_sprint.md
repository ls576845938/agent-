# BTC Data Cost Fold Regime Repair Sprint

Current BTC data is Binance spot kline research input. It is not complete USD-M perpetual evidence.

This sprint adds fail-closed contracts for local perpetual bundles, public data collection boundaries, provider verification, funding replay, mark/premium/exchange-rule reporting, tail dependency reporting, and compression archive boundaries.

The current system remains locked:
- paper queue: locked
- live: frozen
- internal candidate gate: 0

BTC candidate pass requires fee, slippage, funding, mark price, premium index, exchangeInfo, event ledger, walk-forward, regime, and tail dependency evidence. Open interest and liquidation snapshots are diagnostic unless a future contract explicitly upgrades their coverage.
