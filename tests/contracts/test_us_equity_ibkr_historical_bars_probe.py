from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from scripts.fetch_us_equity_ibkr_historical_bars import probe_ibkr_historical_bars


def test_ibkr_historical_bars_probe_blocks_when_gateway_unavailable(tmp_path: Path) -> None:
    payload = probe_ibkr_historical_bars(
        repo_root=tmp_path,
        symbols=["QQQ"],
        generated_at="2026-07-07T00:00:00Z",
        ib_client=UnavailableClient(),
        stock_factory=stock_factory,
    )

    assert payload["status"] == "blocked"
    assert payload["blockers"] == ["ibkr_tws_or_gateway_not_connected"]
    assert payload["readonly_connection_requested"] is True
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_ibkr_historical_bars_probe_writes_readonly_probe_parquet(tmp_path: Path) -> None:
    payload = probe_ibkr_historical_bars(
        repo_root=tmp_path,
        symbols=["QQQ"],
        generated_at="2026-07-07T00:00:00Z",
        ib_client=FakeClient(),
        stock_factory=stock_factory,
    )

    assert payload["status"] == "pass"
    assert payload["readonly_connection_requested"] is True
    assert payload["guardrails"]["broker_order_endpoint_used"] is False
    assert payload["symbol_reports"]["QQQ"]["promotion_clean_allowed"] is False

    frame = pd.read_parquet(tmp_path / "data/external/us_equity_intraday/ibkr_probe/interval=1m/kline/QQQ.parquet")
    assert len(frame) == 2
    assert set(frame["source"]) == {"ibkr_historical_data"}
    assert set(frame["adjustment_policy"]) == {"ibkr_returned_values_no_pit_replay"}
    assert not (tmp_path / "data/external/us_equity_intraday/ibkr/interval=1m/kline/QQQ.parquet").exists()


def stock_factory(symbol: str, exchange: str, currency: str) -> dict[str, str]:
    return {"symbol": symbol, "exchange": exchange, "currency": currency}


class UnavailableClient:
    def connect(self, host: str, port: int, clientId: int, timeout: float) -> None:
        raise ConnectionError("simulated gateway unavailable")

    def disconnect(self) -> None:
        return None

    def isConnected(self) -> bool:
        return False


class FakeClient:
    def connect(self, host: str, port: int, clientId: int, timeout: float) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def isConnected(self) -> bool:
        return True

    def qualifyContracts(self, contract: object) -> list[object]:
        return [contract]

    def reqHistoricalData(
        self,
        contract: object,
        endDateTime: str,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
        keepUpToDate: bool,
    ) -> list[Bar]:
        return [
            Bar(pd.Timestamp("2026-07-06T13:30:00Z"), 100.0, 101.0, 99.0, 100.5, 10_000),
            Bar(pd.Timestamp("2026-07-06T13:31:00Z"), 100.5, 101.5, 100.0, 101.0, 11_000),
        ]


@dataclass
class Bar:
    date: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
