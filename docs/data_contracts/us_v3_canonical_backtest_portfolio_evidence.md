# US V3 Canonical Backtest / Portfolio Evidence

Goal: `US-V3-CANONICAL-BACKTEST-PORTFOLIO-EVIDENCE-01`

This US-only workflow rebuilds the already-frozen ETF26 candidate through:

`data -> signal -> forecast -> target portfolio -> risk -> order intent ->
simulated fill -> position/cash ledger -> ledger PnL -> report`

It reuses the current canonical simulator and candidate-portfolio analyzer. It
does not select a new symbol, timeframe, parameter set, leverage level, or cost
grid.

## Calendar and execution

The canonical candidate decides from a completed XNYS session and fills no
earlier than the next eligible session open. For any monthly consumer, the
schedule is derived from observed XNYS sessions: the decision date is the last
actual trading session of the month and execution is the next actual trading
session. Calendar month-end labels are never treated as trading sessions.

## PnL and costs

PnL is derived only from simulated fills, position ledger, cash ledger and the
corporate-action ledger. Commission, spread, slippage and impact remain the
frozen candidate assumptions. Delay cost is attributed from the signed
completed-session-close to next-session-open gap already embedded in fill
settlement, without double charging.

## Fail-closed production boundary

ETF26 remains `research_ready`. The current G06 consumer is
`blocked_external_data`; production membership, delistings, corporate-action
available-time replay and survivorship-clean evidence are absent. Therefore:

- fixture ledgers prove plumbing only;
- simulated fills are not a production event ledger;
- sector/style and liquidity outputs remain research evidence;
- no promotion, paper, live, private, broker or order path is unlocked.

## Durable artifact boundary

The builder executes the complete event replay and validates its canonical and
portfolio manifests before producing the aggregate report. Full JSONL event
logs are transient engineering outputs and are not committed as durable Git
identity. The durable report binds the replay run IDs, canonical/portfolio
manifest hashes, report hashes, immutable data version, strategy/parameter/cost
versions, code commit and tree hash. Re-running the committed builder against
the same immutable input reconstructs the full fixture replay.
