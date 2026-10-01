# BTC Perpetual Funding And Basis Rules

Purpose: prevent BTC perpetual systems from treating funding, basis, or mark/index price mechanics as simple add-ons. Perpetual futures are not spot with leverage.

## Definitions

- `spot_price`: executable or reference spot BTC price from a defined source.
- `perp_trade_price`: actual traded price on a perpetual contract.
- `mark_price`: exchange-defined valuation price used for margin and liquidation.
- `index_price`: exchange-defined basket or reference price used in mark/funding calculations.
- `basis`: difference between perpetual price and spot/reference price.
- `funding_rate`: periodic transfer between longs and shorts intended to anchor perp price.
- `funding_payment`: realized cash flow from position size and funding rate.

## Non-negotiable rules

1. Funding is a cash flow, not a free yield.
2. Positive funding received by a short can be overwhelmed by adverse basis, liquidation, borrow, spread, and execution costs.
3. Funding-rate arbitrage is not risk-free because perpetuals have no fixed maturity convergence.
4. Backtests must model the exact funding timestamp and whether the position was open at that timestamp.
5. Funding should be recorded in the ledger as a separate cash-flow type, not merged into price PnL.
6. Strategy logic must not use funding values whose publication time is after the decision time.
7. Mark price and trade price must not be substituted silently. Liquidation uses exchange risk rules, not research candle close.
8. Multi-venue funding comparisons require synchronized timestamps and consistent annualization.

## Required data fields

For each funding observation:

- `venue`
- `instrument_id`
- `funding_interval_start`
- `funding_interval_end`
- `funding_settlement_time`
- `funding_rate`
- `funding_rate_visible_time`
- `mark_price`
- `index_price`
- `premium_index`
- `next_predicted_funding_rate` if available
- `source_raw_payload_hash`

For each strategy run:

- `funding_model_version`
- `funding_included`: true/false
- `funding_realized_total`
- `funding_realized_by_side`
- `funding_stress_multiplier`
- `basis_entry`
- `basis_exit`
- `basis_max_adverse_excursion`

## Backtest requirements

1. Use event-time funding settlements, not daily approximations, when strategy holds intraday or crosses funding windows.
2. If using OHLCV-only data, label the result as `funding_approximation`.
3. Stress test funding with at least:
   - observed historical funding,
   - zero funding,
   - adverse funding shock,
   - delayed funding data,
   - missing funding interval.
4. Separate:
   - price PnL,
   - funding PnL,
   - fee PnL,
   - slippage PnL,
   - liquidation/ADL losses.
5. A strategy that only works because of funding income must be reported separately from directional trend alpha.

## Research questions before use

- Is funding used as an alpha input, a cost input, or an accounting cash flow?
- Does the strategy trade spot, linear USDT perp, inverse coin-margined perp, or a mix?
- Is the backtest using mark price, index price, trade price, or candle close?
- Can the strategy survive funding inversion during crisis periods?
- Can the strategy survive a basis widening before convergence?

## Implementation constraints

- Add `FundingEvent` as a first-class event if the system trades perpetuals.
- Add `funding_cashflow` to the ledger.
- Add `mark_price` and `index_price` to risk checks.
- Add `liquidation_buffer` to position sizing.
- Fail the promotion gate if funding is approximated but the strategy trades around funding timestamps.

