# US ETF Rotation Strategy Card

## Identity

- Strategy id: `us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x`
- Family: `us_etf_macro_momentum_rotation`
- Current status: `forward_observation_only`
- Live status: locked
- Paper simulation status: locked until an independent strategy validation gate exists

## Hypothesis

The strategy combines ETF cross-sectional momentum, a macro risk switch, and volatility scaling. It assumes that intermediate-horizon winners across broad ETF sleeves can continue to outperform, but that exposure should be reduced or redirected when macro risk and realized volatility make the payoff less attractive.

## Expected Return Sources

- ETF cross-sectional momentum: rotate toward stronger sleeves.
- Macro risk control: reduce risk exposure in hostile macro regimes.
- Volatility scaling: avoid letting realized volatility dominate account risk.

## Main Risks

- Point-in-time universe and survivorship errors.
- Corporate-action adjustment reproducibility.
- Low-liquidity sleeves such as DBMF or QMOM.
- Financing drag when leverage is used.
- Momentum crash or fast reversal after crowded moves.
- Overstated results if cost, liquidity, and capacity are under-modeled.

## Trading Contract

- Rebalance frequency: daily close / next-session target update.
- Current capital scope: USD 10,000 research account.
- Initial live leverage recommendation: do not start at 1.5x.
- Broker/private/order endpoint: forbidden in this stage.
- Real order submission: forbidden in this stage.

## Layer Boundaries

- Alpha signal: cross-sectional momentum, absolute trend, defensive momentum, macro regime, and yield-curve state.
- Portfolio construction: target weights, volatility scaling, leverage cap, defensive sleeve allocation, and liquidity-constrained replacement.
- Execution simulation: target/current deltas, estimated shares, slippage, financing, simulated fills, snapshots, and ledger reconciliation.
- Orchestration scripts may read data and write reports, but core signal, portfolio, and execution modules must not download market data or produce live-readiness conclusions.

## Stop Or Disable Conditions

- Data quality or point-in-time checks fail.
- Cost stress at required bps levels breaks the edge.
- Walk-forward or parameter-neighborhood evidence deteriorates.
- Forward observation ledger fails reconciliation.
- Manual review is not completed.
- Any private/order/live flag appears before an approved live readiness gate.
