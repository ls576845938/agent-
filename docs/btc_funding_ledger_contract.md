# BTC Funding Ledger Contract

Funding PnL must be replayed from funding-time positions and funding-rate events.

Rules:
- Funding payment uses `fundingTime`.
- Position at `fundingTime` must be derived from fills or ledger state, not target-active signals.
- Positive funding means longs pay and shorts receive.
- No open position at `fundingTime` produces zero funding payment.
- Missing funding-rate data, missing fills, or missing funding schedule keeps candidate gate failed.
- Fixture funding reports can validate plumbing but cannot become promotion evidence.
- A funding-adjusted trade ledger must expose `funding_pnl`,
  `net_pnl_before_funding`, and `net_pnl_after_funding` per closed trade.

Metadata policy:

- `funding_info.json` can be a public endpoint response, manual offline capture, or an inferred interval overlay.
- Inferred interval overlays are not endpoint verification.
- `funding_interval_hours` can be used only when `fundingTime` spacing is high-confidence and monotonic.
- Funding-rate sample coverage must align to the bundle sample range before fundingInfo can be treated as verified.
- Funding PnL computed separately is not enough; it must be merged into net ledger PnL before candidate gate can pass.
- The current compression-expansion replay writes
  `artifacts/btc_cost_model/latest/funding_adjusted_trade_ledger.csv` and reports
  `funding_payment_in_ledger=true`, but it is not promotion evidence while
  fundingInfo remains inferred-only and exchangeInfo is missing.
