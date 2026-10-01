# US Equity Regime Overlay Strategy Card

## Identity

- Strategy id: `us_equity_regime_overlay_research_placeholder`
- Family: `regime_overlay`
- Current status: `hypothesis_registered_only`
- Current stage: `strategy_hypothesis_registration`
- Paper/live status: locked

## Hypothesis

The strategy tests whether lagged macro and market-state variables can improve risk exposure decisions for ETF rotation. The overlay must be point-in-time and must not use revised or future macro information.

## Expected Return Sources

- Reduced exposure in unfavorable macro regimes.
- Defensive allocation when market trend and macro stress align.
- Lower drawdown from avoiding high-risk states.

## Required Data

- FRED series with release timestamps and revision policy.
- Macro release calendar with `available_time_utc`.
- ETF prices and trading calendar.
- Explicit lag policy for every macro feature.

## Validation Contract

- Must prove macro values are available before signal timestamp.
- Must compare no-overlay versus overlay variants.
- Must stress release lag assumptions at 1, 3, 7, and 30 days.
- Must attribute gains to macro switch, trend filter, or defensive sleeve.

## Stop Or Disable Conditions

- Overlay only works with post-hoc regime labels.
- Release lag cannot be reproduced.
- Whipsaw costs exceed drawdown benefit.
- Macro switch overrides a validated strategy without evidence.

## Guardrails

- This is a registered hypothesis only.
- Macro data without PIT release evidence cannot be used for promotion.
