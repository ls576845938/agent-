# Trading Calendar Configuration Notes

## SEC T+1 Settlement (Effective May 28, 2024)

The SEC shortened the standard settlement cycle from T+2 to T+1 for most
securities transactions. This means:

- Trade date (T): order executed
- Settlement date (T+1): cash and securities exchanged

Impact on this system:
- `USEquityCalendar.is_trading_day()` already returns correct trading days
- Settlement lag does not affect backtest fill simulation (fills are instant
  in simulation)
- Paper/live trading: cash from sells is available 1 business day after fill
- `AccountState.cash` should distinguish `settled_cash` from `total_cash`
  when live trading is enabled (future work)

## FINRA Intraday Margin Rules (Effective June 4, 2026)

FINRA Rule 4210 amendments introduce intraday margin requirements with a
phased implementation through October 20, 2027.

Key changes:
- Intraday position monitoring at 15-minute intervals
- Margin calls triggered intraday, not just end-of-day
- Higher margin requirements for concentrated positions

Impact on this system:
- `PreTradeRiskEngine` already checks gross_exposure, symbol_weight,
  and cash_buffer per order
- Intraday monitoring is not yet implemented (requires real-time data feed)
- For backtest, daily bar frequency makes intraday checks not applicable
- TODO: `PostTradeRiskEngine` should add concentration checks when live
  trading is enabled

## Nasdaq 23/5 Extended Trading (SEC Accelerated Approval)

Nasdaq's proposal to allow 23-hour trading, 5 days a week has received
SEC accelerated approval. This will introduce a "night session" between
after-hours close and pre-market open.

Current session model:
```
PRE_MARKET  (04:00-09:30 ET)
REGULAR     (09:30-16:00 ET)
AFTER_HOURS (16:00-20:00 ET)
CLOSED      (20:00-04:00 ET)
```

Future model (when 23/5 is live):
```
PRE_MARKET  (04:00-09:30 ET)
REGULAR     (09:30-16:00 ET)
AFTER_HOURS (16:00-20:00 ET)
OVERNIGHT   (20:00-04:00 ET)  ← new session
```

Impact on this system:
- `SessionName` enum already has `OVERNIGHT` value
- `USEquityCalendar.session_for()` currently never returns OVERNIGHT
- `PreTradeRiskConfig.allowed_sessions` defaults to `{REGULAR, AFTER_HOURS}`
- When 23/5 goes live:
  1. Update `session_for()` to map 20:00-04:00 ET to OVERNIGHT
  2. Decide whether OVERNIGHT bars should trigger signals
  3. Update gap detection for overnight gaps (wider than regular overnight)
  4. Consider separate slippage model for overnight sessions (lower liquidity)

## Configuration

All trading calendar settings are centralized in:
- `quant_us/core/nyse_holidays.py` — holiday calendar
- `quant_us/core/calendar.py` — session mapping and calendar queries
- `quant_us/risk/pre_trade.py` — session-based trading restrictions

To change session trading rules, modify `PreTradeRiskConfig.allowed_sessions`.
