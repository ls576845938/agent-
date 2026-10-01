# CRSP to Local CSV Mapping

## Provider Role

CRSP can be used as a candidate source for PIT membership, delistings,
corporate actions, identifiers, and adjustment replay inputs. It is not locally
verified until exported data passes QuantStation verification.

## Expected Source Files or Tables

- Security names and identifiers
- Historical exchange/listing records
- Delisting events and delisting returns
- Distribution and split events
- Price series used to replay adjustments

## Mapping

- `universe_membership_events.csv`: map listing/add/remove/delist events by
  stable security identifier and effective date.
- `delisted_symbols.csv`: map delisting date, reason, last trade date, and
  delisting return where available.
- `corporate_actions.csv`: map splits, dividends, symbol changes, mergers, and
  other security events.
- `symbol_mapping.csv`: map ticker intervals to `security_id`; include PERMNO
  where available.
- `adjustment_replay.csv`: replay adjusted close from raw close plus split and
  distribution factors.

## Identifier Strategy

Use a stable internal `security_id` derived from CRSP identifiers, with ticker
as a dated alias. Do not merge reused tickers without a valid mapping interval.

## Known Gaps

Index membership may need a separate index constituent export depending on the
target universe. Adjustment replay must be recomputed locally.

## Verification Blockers

Missing dated membership, delisting records, corporate action events,
identifier intervals, or replay accuracy remains blocking.

## Expected Max Lineage Grade Before Verification

At most `L2_static_snapshot` before local verification. It may reach
`L4_promotion_clean` only after the bundle passes provider verification.

## Why Local Verification Is Required

Vendor capability and table availability do not prove that this project has
complete, correctly mapped, reproducible local evidence.
