# Known Gaps

## Current Gaps

- Real Alpaca paper adapter is not yet integrated.
- `paper_broker=alpaca` remains fail-closed.
- The documentation boundary still stops at manual or read-only evidence review.
- The baseline does not introduce automatic paper trading.
- The baseline does not introduce live trading.

## Documentation Gaps To Watch

- any wording that implies a paper session can start automatically
- any wording that implies live orders can flow without a separate gate
- any wording that suggests promotion equals execution

## Operational Gaps To Watch

- missing or stale evidence in the registry
- full-test runs executed without `PYTHONPATH=.`
- mismatched language between README, boundary docs, and CLI report docs
