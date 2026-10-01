# US Equity Factor Momentum Quality Strategy Card

## Identity

- Strategy id: `us_equity_factor_momentum_quality_research_placeholder`
- Family: `equity_factor`
- Current status: `hypothesis_registered_only`
- Current stage: `strategy_hypothesis_registration`
- Paper/live status: locked

## Hypothesis

The strategy tests whether momentum plus quality signals can add diversifying alpha beyond ETF rotation. It is deferred until point-in-time fundamentals, survivorship controls, and delisting evidence are available.

## Expected Return Sources

- Momentum continuation.
- Quality premium from profitability, stability, or lower leverage.
- Diversification versus ETF-only rotation.

## Required Data

- Point-in-time prices and universe membership.
- Point-in-time fundamentals with filing or availability dates.
- Delisting returns and corporate actions.
- Liquidity and minimum trade amount data.

## Validation Contract

- Must use purged or properly time-split validation if labels overlap.
- Must report factor contribution, turnover, cost stress, and capacity.
- Must compare to ETF rotation and simple factor ETF proxies.
- Must prove no future fundamentals or survivorship leakage.

## Stop Or Disable Conditions

- PIT fundamentals are unavailable.
- Delisting and symbol mapping evidence is incomplete.
- Portfolio size is not executable for USD 10,000.
- Excess return disappears after realistic cost and liquidity filters.

## Guardrails

- This is a registered hypothesis only.
- It is not eligible for paper or live until data lineage and validation gates are complete.
