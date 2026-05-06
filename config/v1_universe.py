"""V1 universe: 10 symbols only.

Do NOT expand this list without updating:
- ADR-001-system-boundary.md
- Data quality baselines
- Backtest expected results
"""

V1_SYMBOLS = [
    "SPY",   # S&P 500 ETF
    "QQQ",   # Nasdaq-100 ETF
    "IWM",   # Russell 2000 ETF
    "DIA",   # Dow Jones ETF
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "NVDA",  # NVIDIA
    "META",  # Meta
    "AMZN",  # Amazon
    "GOOGL", # Alphabet
]

V1_INTERVALS = ["1d"]
V1_SOURCE = "yfinance"
V1_ASSET_CLASS = "equity"
V1_START = "2020-01-01"
