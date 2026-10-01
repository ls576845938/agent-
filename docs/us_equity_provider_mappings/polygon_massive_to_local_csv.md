# Polygon / Massive to Local CSV Mapping

## Provider Role

Polygon / Massive can be a candidate source for reference data, ticker events,
corporate actions, and price bars. It is not a verified local lineage source
until exported files pass QuantStation verification.

## Expected Source Files or Tables

- Ticker reference snapshots
- Ticker event history
- Delisting or inactive ticker export
- Splits/dividends/corporate actions
- Price bars for replay comparison

## Mapping

- `universe_membership_events.csv`: map listing, active/inactive, exchange, and
  delisting events into dated membership events.
- `delisted_symbols.csv`: map inactive or delisted tickers to delisting records
  with source ids.
- `corporate_actions.csv`: map splits, dividends, ticker changes, and other
  events.
- `symbol_mapping.csv`: map ticker, composite FIGI, CIK, CUSIP, and dated
  exchange/ticker intervals where available.
- `adjustment_replay.csv`: replay adjusted prices locally from raw bars and
  corporate action events.

## Identifier Strategy

Prefer stable provider identifiers such as composite FIGI when available, and
keep ticker as a dated alias. Reused tickers must remain separate securities.

## Known Gaps

PIT universe membership may require combining multiple reference exports.
Corporate action and delisting coverage must be validated locally.

## Verification Blockers

Missing historical membership, delisting coverage, action source, identifier
mapping, or replay reproducibility blocks promotion.

## Expected Max Lineage Grade Before Verification

At most `L2_static_snapshot` before local verification.

## Why Local Verification Is Required

API or export capability is not equivalent to a complete verified local bundle.
