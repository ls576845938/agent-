from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd

from scripts.fetch_us_equity_tiingo_eod import import_tiingo_eod


SCHEMA = Path("schemas/us_equity_tiingo_eod_import_report.schema.json")
COMPAT_SCHEMA = Path("schemas/tiingo_eod_import_report.schema.json")


def test_tiingo_eod_import_dry_run_writes_no_market_data(tmp_path: Path) -> None:
    payload = import_tiingo_eod(
        repo_root=tmp_path,
        symbols=["SPY", "QQQ"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=False,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_tiingo_eod_import_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "dry_run"
    assert payload["network_called"] is False
    assert payload["writes_performed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert not (tmp_path / "data/external/us_equity_eod/tiingo/kline/SPY.parquet").exists()


def test_tiingo_eod_import_writes_parquet_and_masks_token(tmp_path: Path) -> None:
    def fetcher(symbol: str, _start: str, _end: str) -> list[dict[str, object]]:
        return _rows(symbol)

    payload = import_tiingo_eod(
        repo_root=tmp_path,
        symbols=["SPY", "QQQ"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=True,
        generated_at="2026-06-25T00:00:00Z",
        token="secret-token-that-must-not-leak",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    _validate_schema(payload)
    _validate_schema(payload, COMPAT_SCHEMA)
    assert payload["network_called"] is True
    assert payload["token_printed"] is False
    assert payload["guardrails"]["token_written_to_artifacts"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["blockers"] == []

    report_text = (tmp_path / "artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json").read_text(
        encoding="utf-8"
    )
    assert "secret-token-that-must-not-leak" not in report_text

    spy = pd.read_parquet(tmp_path / "data/external/us_equity_eod/tiingo/kline/SPY.parquet")
    assert list(spy["symbol"].unique()) == ["SPY"]
    assert {"datetime", "Open", "High", "Low", "Close", "Volume", "DivCash", "SplitFactor", "source"} <= set(
        spy.columns
    )
    assert spy["Close"].iloc[-1] > spy["Close"].iloc[0]


def test_tiingo_eod_import_can_use_ignored_local_env_file_without_leaking_token(tmp_path: Path) -> None:
    local_token = "local-token-that-must-not-leak"
    (tmp_path / ".env.local").write_text(f"\ufeffTIINGO_API_KEY={local_token}\n", encoding="utf-8")

    def fetcher(symbol: str, _start: str, _end: str) -> list[dict[str, object]]:
        return _rows(symbol)

    payload = import_tiingo_eod(
        repo_root=tmp_path,
        symbols=["SPY"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=True,
        generated_at="2026-06-25T00:00:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["token_present"] is True
    assert payload["token_printed"] is False
    assert payload["guardrails"]["token_written_to_artifacts"] is False
    assert local_token not in json.dumps(payload)


def test_tiingo_eod_import_blocks_bad_ohlc(tmp_path: Path) -> None:
    def fetcher(_symbol: str, _start: str, _end: str) -> list[dict[str, object]]:
        rows = _rows("SPY")
        rows[-1]["adjClose"] = -1.0
        return rows

    payload = import_tiingo_eod(
        repo_root=tmp_path,
        symbols=["SPY"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=True,
        generated_at="2026-06-25T00:00:00Z",
        token="secret-token-that-must-not-leak",
        fetcher=fetcher,
    )

    assert payload["status"] == "partial"
    _validate_schema(payload)
    assert "tiingo_required_symbols_missing" in payload["blockers"]
    assert "tiingo_spy_non_positive_ohlc" in payload["symbol_reports"]["SPY"]["blockers"]
    assert "secret-token-that-must-not-leak" not in json.dumps(payload)


def test_tiingo_eod_import_schema_rejects_token_written_flag(tmp_path: Path) -> None:
    payload = import_tiingo_eod(
        repo_root=tmp_path,
        symbols=["SPY"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=False,
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["token_written_to_artifacts"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted token_written_to_artifacts=true")


def _rows(symbol: str) -> list[dict[str, object]]:
    base = 100.0 if symbol == "SPY" else 200.0
    return [
        {
            "date": "2026-06-22T00:00:00.000Z",
            "open": base,
            "high": base + 2.0,
            "low": base - 1.0,
            "close": base + 1.0,
            "volume": 1_000_000,
            "adjOpen": base,
            "adjHigh": base + 2.0,
            "adjLow": base - 1.0,
            "adjClose": base + 1.0,
            "adjVolume": 1_000_000,
            "divCash": 0.0,
            "splitFactor": 1.0,
        },
        {
            "date": "2026-06-23T00:00:00.000Z",
            "open": base + 1.0,
            "high": base + 3.0,
            "low": base,
            "close": base + 2.0,
            "volume": 1_100_000,
            "adjOpen": base + 1.0,
            "adjHigh": base + 3.0,
            "adjLow": base,
            "adjClose": base + 2.0,
            "adjVolume": 1_100_000,
            "divCash": 0.0,
            "splitFactor": 1.0,
        },
        {
            "date": "2026-06-24T00:00:00.000Z",
            "open": base + 2.0,
            "high": base + 4.0,
            "low": base + 1.0,
            "close": base + 3.0,
            "volume": 1_200_000,
            "adjOpen": base + 2.0,
            "adjHigh": base + 4.0,
            "adjLow": base + 1.0,
            "adjClose": base + 3.0,
            "adjVolume": 1_200_000,
            "divCash": 0.0,
            "splitFactor": 1.0,
        },
    ]


def _validate_schema(payload: dict[str, object], schema_path: Path = SCHEMA) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
