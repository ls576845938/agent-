# US Equity ETF Top-N Rotation Strategy Card

## Identity

- Strategy id: `us_equity_etf_topn_rotation_research_placeholder`
- Family: `topn_etf_rotation`
- Current status: `hypothesis_registered_only`
- Current stage: `strategy_hypothesis_registration`
- Paper/live status: locked

## Hypothesis

The strategy tests whether holding several top-ranked ETF momentum sleeves improves stability compared with top-1 concentration. The goal is not simply higher CAGR, but a better tradeoff among drawdown, turnover, capacity, and small-account executability.

## Expected Return Sources

- ETF cross-sectional momentum.
- Diversification across multiple strong sleeves.
- Potentially lower single-asset timing error than top-1 rotation.

## Required Data

- Point-in-time ETF universe membership.
- Adjusted ETF OHLCV and ADV.
- Corporate-action and symbol mapping evidence.
- Liquidity data for minimum ADV and small-account trade sizing.

## Validation Contract

- Must test Top 2, Top 3, and Top 5 variants.
- Must compare equal-weight and inverse-volatility weighting.
- Must decompose whether diversification improves risk or merely dilutes alpha.
- Must include cost, liquidity, capacity, and whole-share/fractional-share constraints.

## Stop Or Disable Conditions

- Top-N becomes benchmark-like without improving risk.
- Higher turnover destroys net return.
- Holdings remain highly correlated during drawdowns.
- Weight-to-share conversion fails for a USD 10,000 account.

## Guardrails

- This is a registered hypothesis only.
- No parameter optimization result can promote it without the standard evidence pack.
