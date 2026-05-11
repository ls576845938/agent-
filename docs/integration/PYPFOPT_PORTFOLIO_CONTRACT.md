# PyPortfolioOpt Portfolio Contract

Status: draft for the Qlib + PyPortfolioOpt integration phase.

## Scope

This contract defines the portfolio-construction step that consumes imported Qlib scores and daily return history and produces target weights.

In scope:

- long-only optimization
- daily or weekly rebalance cadence
- max-sharpe, min-volatility, and HRP modes
- reproducible target-weight artifacts

Out of scope:

- order submission
- broker access
- OMS access
- live or paper execution
- shorting or leverage
- minute data

## Accepted Inputs

The optimizer may read:

- imported Qlib score artifacts
- cleaned daily returns
- optional current weights
- portfolio config

The optimizer must not read future returns, future scores, or any live execution state.

## Required Output Fields

The portfolio artifact must include:

- `portfolio_run_id`
- `source_score_run_id`
- `datetime`
- `symbol`
- `target_weight`
- `raw_weight`
- `clipped_weight`
- `optimizer`
- `constraints_hash`
- `fallback`
- `created_at`

If a run falls back to an equal-weight or top-k rule, that fallback must be explicit in the artifact.

## Constraints

All portfolio outputs must remain target weights or `TargetPosition`-compatible inputs only.

Required constraints:

- long-only
- no negative weights
- no leverage
- no shorting
- total target weight must not exceed `1 - cash_buffer`
- each symbol must respect `max_weight`
- turnover must respect `max_turnover`, or the run must fail or use an explicit fallback

## No-Lookahead Rules

The optimizer must obey strict date cutoffs.

- expected returns for date `T` may use scores observed at or before `T`
- covariance for rebalance date `T` may use only past completed returns
- walk-forward or expanding-window calibration is required for any fitted mapping

## Supported Modes

The initial contract covers three optimization modes:

- `max_sharpe`
- `min_volatility`
- `hrp`

Expected-return proxy modes:

- `rank_zscore`
- `score_zscore`
- `forward_return_fit`, only with prior historical forward-return observations

Covariance modes:

- `sample`
- `shrinkage`, only when PyPortfolioOpt is installed
- `exponential`

All three remain research-only until the rest of the platform consumes them through the normal risk and backtest gates.

## Failure Behavior

The optimizer must fail closed when:

- the score artifact is missing
- the universe is incomplete
- look-ahead cutoffs are violated
- a dependency is unavailable and no supported fallback is configured
- a constraint cannot be satisfied

The optimizer must not convert its output into an order.

## Relationship to Risk and Execution

PyPortfolioOpt is not part of the execution path.

It may produce target weights for downstream research, but:

- all orders still pass the risk engine
- order creation remains outside the optimizer
- broker submission remains outside the optimizer
- paper/live readiness is not implied by portfolio output
