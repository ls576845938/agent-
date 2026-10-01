# BTC Trend Research Gate

Purpose: define what a BTC trend strategy must prove before it can leave research.

## Scope

This applies to BTC-only strategies using:

- spot BTC;
- linear USDT/USDC perpetuals;
- inverse coin-margined perpetuals;
- dated BTC futures;
- ETF or CME proxies for research context.

## Required research statement

Every BTC trend experiment must declare:

- tradable instrument;
- venue;
- timeframe;
- signal definition;
- bar construction rule;
- candle finalization rule;
- cost model;
- slippage model;
- funding model if perp;
- leverage and liquidation policy;
- data source and data version;
- walk-forward or out-of-sample design;
- fail conditions.

## Minimum validation

1. No look-ahead in bar close, funding, mark/index, or exchange metadata.
2. Costs include maker/taker fees, spread, slippage, funding, and borrow/margin cost if applicable.
3. Funding is separated from price PnL.
4. Results are shown net of all costs.
5. Parameter selection is validated out-of-sample.
6. Performance is stress-tested across bull, bear, sideways, and crash windows.
7. Drawdown is measured both close-to-close and intraperiod when data allows.
8. Liquidation distance is measured for every leveraged position.
9. Order size is checked against historical depth and min-notional rules.
10. Exchange outage and data gaps are included in the evidence package.

## BTC-only cautions

BTC-only has no cross-sectional breadth. It must compensate with:

- conservative risk target;
- multiple independent validation windows;
- robust parameter bands;
- volatility-based sizing;
- cash state;
- stop-trading state;
- regime diagnostics;
- long flat or long short policy explicitly defined.

Do not claim diversification from multiple timeframes if all signals are computed from the same BTC price path. Multiple timeframes can reduce noise, but they are correlated evidence.

## Reject conditions

Reject the strategy if:

- profitability disappears after realistic taker fees and slippage;
- performance depends on one narrow parameter;
- performance depends mainly on one crash or one bull market;
- funding is omitted for a perp strategy;
- the strategy assumes fills at candle close without execution model;
- liquidation can occur under historically observed intraday moves;
- data gaps are ignored;
- live order path has not been paper-tested.

## Research deliverables

Required files/artifacts:

- experiment manifest;
- raw data manifest;
- feature manifest;
- backtest report;
- cost and slippage report;
- funding report for perps;
- walk-forward report;
- parameter sensitivity report;
- drawdown and liquidation stress report;
- promotion recommendation: `reject`, `revise`, `paper_candidate`.

