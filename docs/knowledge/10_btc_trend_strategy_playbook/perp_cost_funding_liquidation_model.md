# Perpetual Cost, Funding, And Liquidation Model

Purpose: define the minimum model for BTC perpetual strategy backtests and paper trading.

## Cost components

Every BTC perpetual result must decompose:

- maker fee;
- taker fee;
- spread cost;
- slippage;
- market impact approximation;
- funding payment;
- borrow or margin financing if applicable;
- liquidation penalty or forced-close loss if simulated;
- ADL or exchange risk event if observed/simulated.

## Funding model

The funding model must specify:

- funding interval;
- settlement timestamp;
- rate source;
- visibility timestamp;
- position eligibility rule;
- annualization convention;
- missing-rate fallback;
- adverse-funding stress.

Ledger entry:

- `event_type = funding_cashflow`
- `instrument_id`
- `position_qty`
- `funding_rate`
- `mark_or_notional_base`
- `cashflow`
- `settlement_asset`
- `settlement_time`

## Slippage and depth model

Minimum levels:

1. `basic`: fixed bps plus maker/taker fees.
2. `spread_aware`: half-spread plus order-side fee.
3. `depth_aware`: uses L2 depth snapshots or historical replay.
4. `stress`: expands spread and reduces depth during volatility or outage windows.

A strategy can be promoted only if its model level matches its holding period and turnover. Intraday or high-turnover BTC strategies should not rely only on fixed bps.

## Liquidation model

For every leveraged position, compute:

- initial margin;
- maintenance margin;
- liquidation price estimate;
- mark price path;
- liquidation buffer in bps;
- worst observed intrabar adverse move;
- buffer after new order;
- max allowed leverage;
- forced reduce threshold.

The risk engine must block orders when post-order liquidation buffer is below policy.

## Stress scenarios

At minimum:

- fee tier worsens;
- all fills become taker;
- spread doubles;
- slippage doubles;
- funding turns adverse for multiple intervals;
- mark price deviates from trade price;
- order book depth halves;
- WebSocket gap during open position;
- exchange enters cancel-only mode;
- liquidation cascade move.

## Reporting

Every report must show:

- gross return;
- net return;
- price PnL;
- funding PnL;
- fee PnL;
- slippage PnL;
- max leverage;
- minimum liquidation buffer;
- number of funding intervals held;
- number of forced risk reductions;
- number of times trading was blocked by runtime policy.

