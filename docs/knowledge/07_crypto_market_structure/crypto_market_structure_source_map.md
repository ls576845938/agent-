# Crypto Market Structure Source Map

Purpose: define which modern crypto sources can be used to extend the quant-system rules. These sources are constraints and evidence inputs, not trade signals by themselves.

## First-priority sources

| Source | Use in this knowledge base | Do not use for |
| --- | --- | --- |
| [Fundamentals of Perpetual Futures](https://arxiv.org/html/2212.06888v5) | Perpetual contract mechanics, funding, basis, no-arbitrage bounds, funding-rate arbitrage caveats. | Blind funding arbitrage without margin, liquidation, borrow, fee, and exit-risk modeling. |
| [Designing funding rates for perpetual futures in cryptocurrency markets](https://arxiv.org/abs/2506.08573) | Funding-rate design, perp price anchoring, exchange/issuer risk. | Assuming any exchange's current funding formula is optimal or stable. |
| [Microstructure and Market Dynamics in Crypto Markets](https://stoye.economics.cornell.edu/docs/Easley_ssrn-4814346.pdf) | Liquidity, price discovery, cross-market effects, VPIN/Roll-style diagnostics. | Treating microstructure indicators as plug-in alpha without out-of-sample validation. |
| [ESMA Crypto assets: Market structures and EU relevance](https://www.esma.europa.eu/sites/default/files/2024-04/ESMA50-524821-3153_risk_article_crypto_assets_market_structures_and_eu_relevance.pdf) | Exchange concentration, fiat on/off ramps, liquidity concentration, regulatory market-structure framing. | Assuming reported exchange volume is reliable without data-vendor cleaning. |
| [CME CF Cryptocurrency Reference Rates Methodology](https://docs.cfbenchmarks.com/CME%20CF%20Reference%20Rates%20Methodology.pdf) | Reference-price construction, outlier/missing-data handling, market-failure events. | Using a single venue last trade as a canonical BTC price. |
| [Tardis.dev Documentation](https://docs.tardis.dev/) | Tick, order book, funding, open interest, liquidation, replay data requirements. | Assuming OHLCV candles are enough to validate execution-sensitive strategies. |

## Market structure rules

1. Crypto market data is fragmented by venue, instrument type, quote currency, margin currency, and data vendor normalization.
2. BTC spot, BTC USDT perpetual, BTC USD inverse perpetual, CME futures, and ETF flow proxies are different instruments.
3. A strategy document must state the exact tradable instrument, settlement currency, margin mode, fee tier, and funding model.
4. Reported volume is not enough to infer tradability. Use spread, depth, resiliency, outage history, and order acceptance constraints.
5. Venue concentration is a risk factor. A BTC-only system still has venue risk, stablecoin risk, API risk, and reference-price risk.
6. Any cross-venue comparison must normalize timestamp, timezone, symbol, contract multiplier, quote currency, and fee/funding conventions.
7. Institutional/research reports from exchanges and data vendors must be cross-checked against regulator or academic sources before becoming hard rules.

## Required source metadata

Every crypto data or execution adapter must expose:

- `venue`
- `instrument_id`
- `instrument_type`: `spot`, `linear_perp`, `inverse_perp`, `dated_future`, `option`, `etf_proxy`
- `base_asset`
- `quote_asset`
- `settlement_asset`
- `margin_asset`
- `contract_multiplier`
- `price_precision`
- `size_precision`
- `min_notional`
- `fee_tier`
- `maker_fee`
- `taker_fee`
- `funding_interval`
- `funding_source`
- `mark_price_source`
- `index_price_source`
- `server_time_source`
- `data_visible_time`
- `vendor_collection_time`

## Promotion rule

No BTC crypto strategy can move from research to paper trading until the evidence package includes:

1. Exact instrument and venue definition.
2. Reference price policy.
3. Funding and fee policy.
4. Exchange outage and API failure policy.
5. Minimum liquidity and spread checks.
6. Liquidation and leverage limits.
7. Data gap and candle-finalization policy.

