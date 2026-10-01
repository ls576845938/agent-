from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from scripts.fetch_us_equity_ibkr_minute_backfill import import_ibkr_minute_backfill


def test_ibkr_minute_backfill_dry_run_writes_no_market_data(tmp_path: Path) -> None:
    payload = import_ibkr_minute_backfill(
        repo_root=tmp_path,
        symbols=["QQQ", "TQQQ"],
        start_date="2026-06-01",
        end_date="2026-06-30",
        execute_network=False,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert payload["status"] == "dry_run"
    assert payload["network_called"] is False
    assert payload["writes_performed"] is False
    assert payload["readonly_connection_requested"] is True
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert not (tmp_path / "data/external/us_equity_intraday/ibkr/interval=1m/kline/QQQ.parquet").exists()


def test_ibkr_minute_backfill_blocks_when_gateway_unavailable(tmp_path: Path) -> None:
    payload = import_ibkr_minute_backfill(
        repo_root=tmp_path,
        symbols=["QQQ"],
        start_date="2026-06-01",
        end_date="2026-06-30",
        execute_network=True,
        generated_at="2026-07-01T00:00:00Z",
        ib_client=UnavailableClient(),
        stock_factory=stock_factory,
    )

    assert payload["status"] == "blocked"
    assert payload["raw_data_blockers"] == ["ibkr_tws_or_gateway_not_connected"]
    assert payload["guardrails"]["broker_order_endpoint_used"] is False
    assert payload["guardrails"]["real_order_submitted"] is False


def test_ibkr_minute_backfill_promotes_complete_raw_chunks_to_main_kline(tmp_path: Path) -> None:
    payload = import_ibkr_minute_backfill(
        repo_root=tmp_path,
        symbols=["QQQ"],
        start_date="2026-06-01",
        end_date="2026-06-30",
        execute_network=True,
        generated_at="2026-07-01T00:00:00Z",
        min_coverage_ratio=0.0,
        ib_client=FakeClient(),
        stock_factory=stock_factory,
    )

    assert payload["status"] == "pass"
    assert payload["research_ready_status"] == "blocked"
    assert payload["network_called"] is True
    assert payload["symbol_reports"]["QQQ"]["write_mode"] == "complete_backfill_promoted_to_main_kline"
    assert payload["symbol_reports"]["QQQ"]["promotion_clean_allowed"] is False
    assert payload["research_blockers"] == ["qqq_ibkr_minute_pit_adjustment_replay_required"]

    frame = pd.read_parquet(tmp_path / "data/external/us_equity_intraday/ibkr/interval=1m/kline/QQQ.parquet")
    assert len(frame) == 2
    assert set(frame["source"]) == {"ibkr_historical_data"}
    assert set(frame["adjustment_policy"]) == {"ibkr_returned_values_no_pit_replay"}
    assert set(frame["data_version"]) == {"ibkr_historical_intraday_backfill_v1"}


def test_ibkr_minute_backfill_preserves_existing_kline_when_run_is_partial(tmp_path: Path) -> None:
    existing_path = tmp_path / "data/external/us_equity_intraday/ibkr/interval=1m/kline/QQQ.parquet"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-06-30T13:30:00Z"], utc=True),
            "symbol": ["QQQ"],
            "Open": [500.0],
            "High": [501.0],
            "Low": [499.0],
            "Close": [500.5],
            "Volume": [10000],
        }
    )
    existing.to_parquet(existing_path, index=False)

    payload = import_ibkr_minute_backfill(
        repo_root=tmp_path,
        symbols=["QQQ"],
        start_date="2026-05-01",
        end_date="2026-06-30",
        execute_network=True,
        generated_at="2026-07-01T00:00:00Z",
        max_new_chunks_per_run=1,
        min_coverage_ratio=0.0,
        ib_client=FakeClient(),
        stock_factory=stock_factory,
    )

    retained = pd.read_parquet(existing_path)
    assert payload["status"] == "partial"
    assert payload["attempted_new_chunk_count"] == 1
    assert payload["symbol_reports"]["QQQ"]["write_mode"] == "partial_chunks_not_promoted_existing_kline_retained"
    assert payload["symbol_reports"]["QQQ"]["main_kline_write_suppressed"] is True
    assert "ibkr_qqq_minute_backfill_incomplete" in payload["raw_data_blockers"]
    assert retained["Close"].tolist() == [500.5]


def test_ibkr_minute_backfill_can_limit_new_chunks_per_symbol(tmp_path: Path) -> None:
    payload = import_ibkr_minute_backfill(
        repo_root=tmp_path,
        symbols=["QQQ", "TQQQ"],
        start_date="2026-06-01",
        end_date="2026-07-15",
        execute_network=True,
        generated_at="2026-07-16T00:00:00Z",
        max_new_chunks_per_symbol=1,
        min_coverage_ratio=0.0,
        ib_client=FakeClient(),
        stock_factory=stock_factory,
    )

    assert payload["status"] == "partial"
    assert payload["attempted_new_chunk_count"] == 2
    assert payload["symbol_reports"]["QQQ"]["available_chunk_count"] == 1
    assert payload["symbol_reports"]["TQQQ"]["available_chunk_count"] == 1
    assert payload["symbol_reports"]["QQQ"]["deferred_chunk_count"] == 1
    assert payload["symbol_reports"]["TQQQ"]["deferred_chunk_count"] == 1


def test_ibkr_minute_backfill_marks_empty_chunk_as_not_available(tmp_path: Path) -> None:
    payload = import_ibkr_minute_backfill(
        repo_root=tmp_path,
        symbols=["QQQ"],
        start_date="2026-06-01",
        end_date="2026-06-30",
        execute_network=True,
        generated_at="2026-07-01T00:00:00Z",
        min_coverage_ratio=0.0,
        ib_client=EmptyClient(),
        stock_factory=stock_factory,
    )

    assert payload["status"] == "partial"
    assert payload["symbol_reports"]["QQQ"]["chunk_reports"][0]["status"] == "empty"
    assert "ibkr_qqq_minute_chunk_empty" in payload["raw_data_blockers"]
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
        symbol = str(contract["symbol"]) if isinstance(contract, dict) else "QQQ"
        base = 100.0 if symbol == "TQQQ" else 500.0
        return [
            Bar(pd.Timestamp("2026-06-03T13:30:00Z"), base, base + 1.0, base - 1.0, base + 0.5, 10000),
            Bar(pd.Timestamp("2026-06-03T13:31:00Z"), base + 0.5, base + 1.5, base, base + 1.0, 11000),
        ]


class EmptyClient(FakeClient):
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
        return []


@dataclass
class Bar:
    date: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
