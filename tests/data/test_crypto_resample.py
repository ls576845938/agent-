from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.app.services.data_management as data_management
from backend.app.core.exceptions import DataSyncError
from backend.app.services.data_management import (
    DEFAULT_EXCHANGE,
    CryptoResampleSpec,
    KlineRecord,
    MarketDataRepository,
    MarketDataService,
)


UTC = timezone.utc


def _seed_minute_klines(db_path: Path, *, minute_count: int = 120, skip_index: int | None = None) -> None:
    repository = MarketDataRepository(str(db_path))
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    records: list[KlineRecord] = []
    for index in range(minute_count):
        if skip_index is not None and index == skip_index:
            continue
        open_time = base + timedelta(minutes=index)
        open_price = 100.0 + index
        close_price = open_price + 0.5
        volume = float(index + 1)
        records.append(
            KlineRecord(
                exchange=DEFAULT_EXCHANGE,
                symbol="BTCUSDT",
                interval="1m",
                open_time_ms=int(open_time.timestamp() * 1000),
                open_time=open_time.isoformat(),
                close_time_ms=int((open_time + timedelta(minutes=1)).timestamp() * 1000) - 1,
                close_time=(open_time + timedelta(minutes=1) - timedelta(milliseconds=1)).isoformat(),
                open=open_price,
                high=open_price + 2.0,
                low=open_price - 1.0,
                close=close_price,
                volume=volume,
                quote_volume=volume * 10.0,
                trade_count=index + 10,
                taker_buy_base_volume=volume * 0.4,
                taker_buy_quote_volume=volume * 4.0,
            )
        )
    repository.upsert_klines(records)


@pytest.fixture
def isolated_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        data_management,
        "settings",
        replace(data_management.settings, repo_root=tmp_path),
    )
    return tmp_path


def test_resample_crypto_klines_aggregates_1h_ohlcv_and_writes_manifest(
    tmp_path: Path,
    isolated_repo_root: Path,
) -> None:
    db_path = tmp_path / "market_data.sqlite"
    _seed_minute_klines(db_path)
    service = MarketDataService()

    result = service.resample_crypto_klines(
        CryptoResampleSpec(
            symbol="BTCUSDT",
            target_interval="1h",
            db_path=str(db_path),
            persist_manifest=True,
        )
    )

    assert result.status == "completed"
    assert result.rows_written == 2
    assert result.source_rows == 120
    assert result.expected_source_rows == 120
    assert result.coverage_pct == 100.0
    assert result.quality_score == 100.0
    assert Path(result.manifest_path).exists()
    assert result.data_version.startswith("qs-sqlite-BTCUSDT-1h-")

    repository = MarketDataRepository(str(db_path))
    rows = repository.load_klines(
        exchange=DEFAULT_EXCHANGE,
        symbol="BTCUSDT",
        interval="1h",
        start_open_time_ms=int(datetime(2024, 1, 1, 0, 0, tzinfo=UTC).timestamp() * 1000),
        end_open_time_ms=int(datetime(2024, 1, 1, 1, 0, tzinfo=UTC).timestamp() * 1000),
    )

    assert len(rows) == 2
    first = rows[0]
    assert float(first["open"]) == 100.0
    assert float(first["high"]) == 161.0
    assert float(first["low"]) == 99.0
    assert float(first["close"]) == 159.5
    assert float(first["volume"]) == pytest.approx(sum(float(index + 1) for index in range(60)))
    assert float(first["quote_volume"]) == pytest.approx(sum(float(index + 1) * 10.0 for index in range(60)))
    assert int(first["trade_count"]) == sum(index + 10 for index in range(60))
    assert float(first["taker_buy_base_volume"]) == pytest.approx(sum(float(index + 1) * 0.4 for index in range(60)))
    assert float(first["taker_buy_quote_volume"]) == pytest.approx(sum(float(index + 1) * 4.0 for index in range(60)))
    assert str(first["source"]) == "sqlite_resample_1m"


def test_resample_crypto_klines_is_idempotent_and_overwrites_existing_target_rows(
    tmp_path: Path,
    isolated_repo_root: Path,
) -> None:
    db_path = tmp_path / "market_data.sqlite"
    _seed_minute_klines(db_path)
    service = MarketDataService()
    repository = MarketDataRepository(str(db_path))

    first = service.resample_crypto_klines(
        CryptoResampleSpec(symbol="BTCUSDT", target_interval="1h", db_path=str(db_path), persist_manifest=False)
    )
    second = service.resample_crypto_klines(
        CryptoResampleSpec(symbol="BTCUSDT", target_interval="1h", db_path=str(db_path), persist_manifest=False)
    )

    rows = repository.load_klines(
        exchange=DEFAULT_EXCHANGE,
        symbol="BTCUSDT",
        interval="1h",
        start_open_time_ms=int(datetime(2024, 1, 1, 0, 0, tzinfo=UTC).timestamp() * 1000),
        end_open_time_ms=int(datetime(2024, 1, 1, 1, 0, tzinfo=UTC).timestamp() * 1000),
    )
    assert first.rows_written == 2
    assert second.rows_written == 2
    assert len(rows) == 2
    assert float(rows[0]["open"]) == 100.0

    updated_minute = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    repository.upsert_klines(
        [
            KlineRecord(
                exchange=DEFAULT_EXCHANGE,
                symbol="BTCUSDT",
                interval="1m",
                open_time_ms=int(updated_minute.timestamp() * 1000),
                open_time=updated_minute.isoformat(),
                close_time_ms=int((updated_minute + timedelta(minutes=1)).timestamp() * 1000) - 1,
                close_time=(updated_minute + timedelta(minutes=1) - timedelta(milliseconds=1)).isoformat(),
                open=500.0,
                high=505.0,
                low=499.0,
                close=504.0,
                volume=999.0,
                quote_volume=9_999.0,
                trade_count=999,
                taker_buy_base_volume=333.0,
                taker_buy_quote_volume=3_333.0,
            )
        ]
    )

    service.resample_crypto_klines(
        CryptoResampleSpec(symbol="BTCUSDT", target_interval="1h", db_path=str(db_path), persist_manifest=False)
    )
    overwritten_rows = repository.load_klines(
        exchange=DEFAULT_EXCHANGE,
        symbol="BTCUSDT",
        interval="1h",
        start_open_time_ms=int(datetime(2024, 1, 1, 0, 0, tzinfo=UTC).timestamp() * 1000),
        end_open_time_ms=int(datetime(2024, 1, 1, 1, 0, tzinfo=UTC).timestamp() * 1000),
    )
    assert len(overwritten_rows) == 2
    assert float(overwritten_rows[0]["open"]) == 500.0
    assert float(overwritten_rows[0]["high"]) == 505.0
    assert float(overwritten_rows[0]["low"]) == 100.0


def test_resample_crypto_klines_fails_when_source_1m_has_missing_rows(
    tmp_path: Path,
    isolated_repo_root: Path,
) -> None:
    db_path = tmp_path / "market_data.sqlite"
    _seed_minute_klines(db_path, skip_index=17)
    service = MarketDataService()
    repository = MarketDataRepository(str(db_path))

    with pytest.raises(DataSyncError, match="Insufficient source 1m klines"):
        service.resample_crypto_klines(
            CryptoResampleSpec(symbol="BTCUSDT", target_interval="1h", db_path=str(db_path), persist_manifest=False)
        )

    rows = repository.load_klines(
        exchange=DEFAULT_EXCHANGE,
        symbol="BTCUSDT",
        interval="1h",
        start_open_time_ms=int(datetime(2024, 1, 1, 0, 0, tzinfo=UTC).timestamp() * 1000),
        end_open_time_ms=int(datetime(2024, 1, 1, 1, 0, tzinfo=UTC).timestamp() * 1000),
    )
    assert rows == []
