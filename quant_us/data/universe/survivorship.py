"""Survivorship bias detection and point-in-time universe construction.

美股回测最大的隐藏偏差不是模型，是拿了现在还活着的股票去做历史回测。
This module enforces that backtests only use symbols known to be active at each
point in time, and flags any survivorship bias in the universe definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class TickerChange:
    old_symbol: str
    new_symbol: str
    effective_date: date
    reason: str = ""


@dataclass
class SurvivorshipReport:
    as_of_date: date
    total_symbols_available: int
    active_symbols: int
    delisted_symbols: int
    delisted_tickers: list[str] = field(default_factory=list)
    changed_tickers: list[str] = field(default_factory=list)
    excluded_by_price: int = 0
    excluded_by_volume: int = 0
    excluded_by_history: int = 0

    @property
    def survivorship_bias_detected(self) -> bool:
        return self.delisted_symbols > 0 or len(self.changed_tickers) > 0

    @property
    def bias_pct(self) -> float:
        if self.total_symbols_available == 0:
            return 0.0
        return self.delisted_symbols / self.total_symbols_available * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "total_symbols_available": self.total_symbols_available,
            "active_symbols": self.active_symbols,
            "delisted_symbols": self.delisted_symbols,
            "delisted_tickers": self.delisted_tickers,
            "changed_tickers": self.changed_tickers,
            "excluded_by_price": self.excluded_by_price,
            "excluded_by_volume": self.excluded_by_volume,
            "excluded_by_history": self.excluded_by_history,
            "survivorship_bias_detected": self.survivorship_bias_detected,
            "bias_pct": round(self.bias_pct, 2),
        }


class SurvivorshipBiasDetector:
    """Checks whether a backtest universe has survivorship bias.

    If you run a backtest from 2020 to 2024 using only today's active tickers,
    you are implicitly assuming you knew in 2020 which stocks would survive to 2024.
    This detector flags that.
    """

    def __init__(
        self,
        instruments: pd.DataFrame,
        ticker_changes: list[TickerChange] | None = None,
    ) -> None:
        self._instruments = instruments.copy()
        self._instruments["symbol"] = self._instruments["symbol"].astype(str).str.upper()
        for col in ("listing_date", "delisting_date"):
            if col in self._instruments.columns:
                converted: list[date | None] = []
                for val in self._instruments[col]:
                    if pd.isna(val) or val is None:
                        converted.append(None)
                    else:
                        converted.append(pd.Timestamp(val).date())
                self._instruments[col] = converted
        self._ticker_changes = ticker_changes or []

    def active_symbols_at(self, target_date: date) -> set[str]:
        """Return symbols that were active (listed and not yet delisted) at target_date."""
        inst = self._instruments
        rows: list[str] = []
        for _, row in inst.iterrows():
            symbol = str(row["symbol"]).upper()
            listing = row.get("listing_date")
            delisting = row.get("delisting_date")

            if listing is not None and isinstance(listing, date) and listing > target_date:
                continue
            if listing is not None and not isinstance(listing, date):
                continue
            if delisting is not None and isinstance(delisting, date) and delisting <= target_date:
                continue
            rows.append(symbol)
        return set(rows)

    def check_backtest_universe(
        self,
        universe_symbols: list[str],
        backtest_end: date,
        as_of: date | None = None,
    ) -> SurvivorshipReport:
        """Check if the backtest universe contains survivorship bias.

        Args:
            universe_symbols: The symbols used in the backtest.
            backtest_end: The end date of the backtest period.
            as_of: The date of the backtest run (default: today). If the universe
                   was defined using only symbols active at as_of, but the backtest
                   goes back years, this detects the bias.
        """
        eval_date = as_of or date.today()
        backtest_symbols = {s.upper() for s in universe_symbols}
        active_now = self.active_symbols_at(eval_date)

        delisted = backtest_symbols - active_now
        changed: list[str] = []
        for tc in self._ticker_changes:
            if tc.old_symbol in backtest_symbols:
                changed.append(f"{tc.old_symbol}→{tc.new_symbol} ({tc.effective_date})")

        return SurvivorshipReport(
            as_of_date=eval_date,
            total_symbols_available=len(backtest_symbols),
            active_symbols=len(backtest_symbols & active_now),
            delisted_symbols=len(delisted),
            delisted_tickers=sorted(delisted),
            changed_tickers=changed,
        )

    def point_in_time_symbols(
        self,
        symbols: list[str],
        target_date: date,
    ) -> list[str]:
        """Filter a symbol list to only those active at target_date."""
        active = self.active_symbols_at(target_date)
        changed_map: dict[str, str] = {}
        for tc in self._ticker_changes:
            if tc.effective_date <= target_date:
                changed_map[tc.old_symbol.upper()] = tc.new_symbol.upper()

        result: list[str] = []
        for s in symbols:
            upper = s.upper()
            if upper in active:
                result.append(upper)
            elif upper in changed_map and changed_map[upper] in active:
                result.append(changed_map[upper])
        return result


def build_instruments_from_yfinance(symbols: list[str]) -> pd.DataFrame:
    """Build a minimal instruments DataFrame from yfinance metadata.

    Falls back to a default structure when yfinance metadata is unavailable.
    """
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            rows.append({
                "symbol": symbol.upper(),
                "name": info.get("longName", info.get("shortName", symbol)),
                "asset_type": info.get("quoteType", "equity").upper(),
                "currency": info.get("currency", "USD"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "listing_date": None,
                "delisting_date": None,
                "is_active": True,
            })
        except Exception:
            rows.append({
                "symbol": symbol.upper(),
                "name": symbol,
                "asset_type": "EQUITY",
                "currency": "USD",
                "sector": "",
                "industry": "",
                "listing_date": None,
                "delisting_date": None,
                "is_active": True,
            })
    return pd.DataFrame(rows)


SECTOR_ETF_MAP: dict[str, str] = {
    "XLF": "Financials", "XLE": "Energy", "XLK": "Technology",
    "XLV": "Health Care", "XLI": "Industrials", "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication Services",
    "SPY": "Large Cap", "QQQ": "Large Cap Growth", "IWM": "Small Cap",
    "DIA": "Large Cap", "MDY": "Mid Cap",
}

KNOWN_SECTORS: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Communication Services",
    "AMZN": "Consumer Discretionary", "NVDA": "Technology", "META": "Communication Services",
    "TSLA": "Consumer Discretionary", "BRK.B": "Financials", "JPM": "Financials",
    "V": "Financials", "JNJ": "Health Care", "WMT": "Consumer Staples",
    "PG": "Consumer Staples", "MA": "Financials", "UNH": "Health Care",
    "HD": "Consumer Discretionary", "DIS": "Communication Services",
    "BAC": "Financials", "XOM": "Energy", "CVX": "Energy",
    "PFE": "Health Care", "CSCO": "Technology", "ADBE": "Technology",
    "NFLX": "Communication Services", "CRM": "Technology", "AMD": "Technology",
    "INTC": "Technology", "QCOM": "Technology", "TXN": "Technology",
    "AVGO": "Technology", "ORCL": "Technology", "IBM": "Technology",
    "ABBV": "Health Care", "MRK": "Health Care", "LLY": "Health Care",
    "KO": "Consumer Staples", "PEP": "Consumer Staples", "COST": "Consumer Staples",
    "T": "Communication Services", "VZ": "Communication Services",
    "WFC": "Financials", "GS": "Financials", "MS": "Financials",
    "CAT": "Industrials", "BA": "Industrials", "GE": "Industrials",
    "NEE": "Utilities", "DUK": "Utilities",
}


def lookup_sector(symbol: str) -> str:
    return SECTOR_ETF_MAP.get(symbol.upper()) or KNOWN_SECTORS.get(symbol.upper(), "")


def lookup_industry(symbol: str) -> str:
    sector = lookup_sector(symbol)
    if not sector:
        return ""
    industry_map: dict[str, str] = {
        "Technology": "Software & Services",
        "Financials": "Banking & Finance",
        "Health Care": "Pharmaceuticals & Biotech",
        "Energy": "Oil & Gas",
        "Consumer Discretionary": "Retail & E-Commerce",
        "Consumer Staples": "Food & Beverage",
        "Communication Services": "Media & Telecom",
        "Industrials": "Manufacturing & Transport",
        "Utilities": "Electric Utilities",
        "Real Estate": "REITs",
        "Materials": "Chemicals & Mining",
    }
    return industry_map.get(sector, "")
