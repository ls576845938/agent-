# Crypto Reference Price Rules

Purpose: define how BTC systems should construct and validate reference prices instead of relying on one exchange's last trade.

## Price types

The system must distinguish:

- `signal_price`: price used to compute indicators.
- `execution_price`: price used to simulate or place orders.
- `mark_price`: exchange risk price.
- `index_price`: exchange basket/reference price.
- `valuation_price`: price used for reports and NAV.
- `benchmark_price`: external reference used for sanity checks.

## Reference-price requirements

1. A BTC reference price must name its source and construction method.
2. Do not mix prices from different venues without storing venue and timestamp.
3. Do not use a last trade as a reference price when the market is stale, fragmented, or under outage.
4. The system must detect cross-venue dislocations before generating new orders.
5. Stablecoin quote pairs require stablecoin risk handling. `BTC/USDT` is not identical to `BTC/USD`.
6. Reference prices must have missing-data, stale-data, and outlier policies.
7. Recomputed reference prices must be reproducible from raw observations or an immutable vendor snapshot.

## Minimum checks

For every BTC price bar or tick used in research:

- monotonic timestamps;
- timezone stored as UTC;
- bar open/close/finalization status;
- venue;
- instrument type;
- price source;
- volume source;
- data collection time;
- duplicate-tick policy;
- missing interval policy;
- outlier policy;
- vendor normalization version.

## Cross-venue dislocation checks

Before order generation, compute:

- `primary_mid`
- `secondary_reference_mid`
- `mark_price`
- `index_price`
- `spread_bps`
- `cross_venue_deviation_bps`
- `data_age_ms`
- `order_book_depth_usd`

Fail closed when:

- primary venue price deviates beyond configured tolerance;
- reference source is stale;
- mark/index price is unavailable for a perp strategy;
- spread or depth breaches liquidity limits;
- WebSocket sequence is broken and gapfill has not completed.

## Reporting requirements

Every BTC backtest or paper-trading report must include:

- price source;
- reference-price source;
- bar construction method;
- candle finalization rule;
- data gaps count;
- stale-price incidents;
- cross-venue deviation incidents;
- whether mark/index/funding data were available and used.

