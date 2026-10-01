# BTC Live Promotion Checklist

Purpose: define the gate from research to paper trading and from paper trading to small live trading for BTC strategies.

## Research to paper

Required:

- backtest manifest complete;
- no-lookahead audit passed;
- cost/slippage/funding model documented;
- parameter sensitivity acceptable;
- walk-forward or out-of-sample evidence acceptable;
- max drawdown and intraperiod stress acceptable;
- liquidation buffer policy defined;
- data gaps documented;
- reference-price policy documented;
- order sizing respects venue filters;
- risk engine blocks are tested;
- paper adapter can run in no-order dry mode.

Decision:

- `reject`: structural issue or no edge after costs.
- `revise`: evidence incomplete or implementation risk unresolved.
- `paper_candidate`: eligible for paper trading only.

## Paper to small live

Required:

- paper run duration defined and completed;
- real-time data gaps recorded;
- WebSocket reconnect/gapfill tested in production-like conditions;
- private stream reconciliation tested;
- open order reconciliation tested;
- cancel-all tested;
- fee/funding estimates match observed venue data;
- paper fills compared against real spread/depth;
- risk engine generated expected blocks;
- no unexplained state divergence;
- human operator runbook exists;
- API keys follow permission policy;
- live mode has explicit size cap.

## Small live constraints

Initial live must enforce:

- max notional cap;
- max leverage cap;
- max daily loss;
- max daily orders;
- max position change per order;
- reduce-only emergency mode;
- no trading during data stale state;
- no trading during private stream unknown state;
- no trading if liquidation buffer below threshold;
- no trading around unreviewed exchange API changes.

## Kill switches

Immediate stop conditions:

- unknown open order;
- unreconciled fill;
- balance mismatch;
- position mismatch;
- API key permission anomaly;
- exchange data stale;
- reference price dislocation;
- repeated order rejection;
- rate limit near ban threshold;
- unexpected funding cashflow;
- drawdown breach;
- human operator unavailable during required monitoring window.

## Promotion record

Each promotion decision must record:

- strategy version;
- config version;
- data version;
- venue and instrument;
- evidence artifacts;
- known weaknesses;
- approved size;
- rollback plan;
- reviewer;
- decision date.

