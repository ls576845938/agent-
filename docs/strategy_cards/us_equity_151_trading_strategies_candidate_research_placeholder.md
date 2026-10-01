# US Equity 151 Trading Strategies Migration Card

## Identity

- Strategy id: `us_equity_151_trading_strategies_candidate_research_placeholder`
- Family: `151_trading_strategies_migration`
- Current status: `hypothesis_registered_only`
- Current stage: `strategy_hypothesis_registration`
- Paper/live status: locked

## Hypothesis

Published strategy ideas from 151 Trading Strategies can enter the US equity system only as registered hypotheses. They must be translated into executable, cost-aware, point-in-time rules before any backtest result is considered.

## Expected Return Sources

- Published anomaly candidates such as momentum, reversal, volatility, liquidity, or seasonality.
- Possible cross-sectional or time-series risk premia.
- Potential ETF-proxy implementations for small-account feasibility.

## Required Data

- Point-in-time tradable universe.
- Adjusted prices, delistings, corporate actions, and symbol mappings.
- Borrow, short, or financing data if a candidate needs short exposure.
- ADV and turnover data for capacity and cost stress.

## Validation Contract

- Each migrated idea must receive its own immutable strategy id.
- Must record original hypothesis, executable interpretation, parameter space, and exclusions.
- Must avoid ranking candidates by in-sample return alone.
- Must pass standard backtest, cost, walk-forward, parameter stability, and manual review gates.

## Stop Or Disable Conditions

- Required data is unavailable or not point-in-time.
- Candidate requires shorting, leverage, or borrow assumptions that cannot be executed.
- Performance depends on a single mined parameter.
- Turnover or slippage invalidates the edge.

## Guardrails

- This is a research migration bucket only.
- No strategy from this bucket can be promoted without its own card, source reports, and validation gate evidence.
