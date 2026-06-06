# BTC Perpetual Data Bundle Contract

BTC perpetual evidence must come from a local, explicitly selected bundle. Public API capability is not local verification.

Required bundle files:
- `btc_perpetual_bundle_manifest.json`
- `klines_1h.csv`
- `klines_4h.csv`
- `klines_1d.csv`
- `mark_price_klines_1h.csv`
- `premium_index_klines_1h.csv`
- `funding_rate.csv`
- `funding_info.json`
- `exchange_info.json`

Optional diagnostic files:
- `open_interest_hist_1h.csv`
- `open_interest_current.json`
- `agg_trades.csv`
- `liquidation_snapshots.csv`

Rules:
- `source_type=fixture` or `source_type=sample` can never pass candidate gate.
- Missing funding, mark price, premium index, or exchangeInfo keeps BTC fail-closed.
- Open interest is diagnostic unless local coverage is explicitly proven for the relevant sample; latest-month data must not be presented as full history.
- Liquidation snapshots are diagnostic only and never complete liquidation history.
- A preflight pass only means the selected bundle is structurally verifiable. It does not mean perpetual evidence is ready, and it does not imply alpha readiness.
- No private, account, order, broker, leverage, margin, transfer, listen-key, or user-data endpoint may be used.
