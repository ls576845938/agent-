# US Equity Supplemental Data Source Boundaries

This note defines what supplemental sources may support in the US equity
production line. It does not approve any source for promotion-clean strategy
validation by itself.

## Boundary

Supplemental data can improve monitoring, price checks, macro features, and
operator diagnostics. It cannot replace the production PIT bundle unless the
data is normalized into the local CSV contract and passes the same local
lineage, hash, schema, survivorship, corporate-action, and adjustment-replay
checks as any other provider.

## Source Roles

| source | allowed role | not sufficient for |
| --- | --- | --- |
| Tiingo EOD | research price refresh, secondary price cross-check, candidate vendor exploration | PIT universe membership, full delisted coverage, effective-dated identifier mapping, macro release calendar, standalone L4 promotion-clean approval |
| IBKR market data | execution-adjacent quote sanity checks, current tradability checks, post-approval monitoring | historical PIT membership, survivorship-bias-free research universe, local adjustment replay proof, standalone L4 promotion-clean approval |
| FRED | macro time series, macro release calendar construction when release timestamps are retained, macro freshness monitoring | equity universe membership, delisted equity coverage, corporate actions, identifier mapping, standalone L4 promotion-clean approval |

## Production PIT Requirement

The production PIT milestone still requires these six files:

- `universe_membership_events.csv`
- `delisted_symbols.csv`
- `corporate_actions.csv`
- `symbol_mapping.csv`
- `adjustment_replay.csv`
- `macro_release_calendar.csv`

Each file must be licensed for local use, reviewed manually, hashed, counted,
and imported through the fail-closed vendor-drop pipeline.

## Operator Rule

Do not mark Tiingo, IBKR, FRED, yfinance, fixture, template, or latest-only
exports as `promotion_clean`. Treat them as supplemental until the imported
bundle proves PIT coverage and adjustment reproducibility through the standard
reports.
