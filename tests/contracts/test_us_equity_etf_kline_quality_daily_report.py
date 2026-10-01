from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import pandas as pd

from scripts.build_us_equity_etf_kline_quality_daily_report import build_us_equity_etf_kline_quality_daily_report


SCHEMA = Path("schemas/us_equity_etf_kline_quality_daily_report.schema.json")


def test_etf_kline_quality_daily_passes_clean_parquet(tmp_path: Path) -> None:
    _write_import_report(tmp_path, ["SPY", "QQQ"])
    _write_kline(tmp_path, "SPY")
    _write_kline(tmp_path, "QQQ")

    payload = build_us_equity_etf_kline_quality_daily_report(
        repo_root=tmp_path,
        required_symbols=("SPY", "QQQ"),
        output=Path("out/quality.json"),
        markdown_output=Path("out/quality.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_etf_kline_quality_daily_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "pass"
    assert payload["promotion_clean"] is True
    assert payload["summary"]["latest_common_date"] == "2026-06-24"
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/quality.json").exists()
    assert (tmp_path / "out/quality.md").exists()


def test_etf_kline_quality_daily_blocks_missing_or_bad_prices(tmp_path: Path) -> None:
    _write_import_report(tmp_path, ["SPY", "QQQ"])
    _write_kline(tmp_path, "SPY", bad_close=True)

    payload = build_us_equity_etf_kline_quality_daily_report(
        repo_root=tmp_path,
        required_symbols=("SPY", "QQQ"),
        output=Path("out/quality.json"),
        markdown_output=Path("out/quality.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert payload["promotion_clean"] is False
    assert any(item.startswith("SPY:non_positive_ohlc_rows") for item in payload["blockers"])
    assert "QQQ:kline_file_missing" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_etf_kline_quality_daily_warns_zero_volume_without_blocking(tmp_path: Path) -> None:
    _write_import_report(tmp_path, ["SPY"])
    _write_kline(tmp_path, "SPY", zero_volume=True)

    payload = build_us_equity_etf_kline_quality_daily_report(
        repo_root=tmp_path,
        required_symbols=("SPY",),
        output=Path("out/quality.json"),
        markdown_output=Path("out/quality.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "warn"
    _validate_schema(payload)
    assert payload["blockers"] == []
    assert any(item.startswith("SPY:zero_or_negative_volume_rows") for item in payload["warnings"])


def test_etf_kline_quality_daily_blocks_key_benchmark_extreme_jump(tmp_path: Path) -> None:
    _write_import_report(tmp_path, ["SPY"])
    _write_kline(tmp_path, "SPY", extreme_jump=True)

    payload = build_us_equity_etf_kline_quality_daily_report(
        repo_root=tmp_path,
        required_symbols=("SPY",),
        output=Path("out/quality.json"),
        markdown_output=Path("out/quality.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert any(item.startswith("SPY:extreme_daily_return_rows") for item in payload["blockers"])


def test_etf_kline_quality_daily_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_import_report(tmp_path, ["SPY"])
    _write_kline(tmp_path, "SPY")
    payload = build_us_equity_etf_kline_quality_daily_report(
        repo_root=tmp_path,
        required_symbols=("SPY",),
        output=Path("out/quality.json"),
        markdown_output=Path("out/quality.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def _write_import_report(root: Path, symbols: list[str]) -> None:
    _write_json(
        root / "artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json",
        {
            "status": "pass",
            "symbols": symbols,
            "blockers": [],
            "guardrails": {
                "token_written_to_artifacts": False,
                "live_order_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
            },
        },
    )


def _write_kline(root: Path, symbol: str, *, bad_close: bool = False, zero_volume: bool = False, extreme_jump: bool = False) -> None:
    kline_root = root / "data/external/us_equity_eod/tiingo/kline"
    kline_root.mkdir(parents=True, exist_ok=True)
    close = [100.0, 101.0, 102.0]
    if bad_close:
        close[-1] = -1.0
    if extreme_jump:
        close[-1] = 150.0
    volume = [1000.0, 1100.0, 1200.0]
    if zero_volume:
        volume[1] = 0.0
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24"], utc=True),
            "symbol": symbol,
            "Open": [100.0, 101.0, close[-1]],
            "High": [101.0, 102.0, max(close[-1], 102.0)],
            "Low": [99.0, 100.0, min(close[-1], 101.0)],
            "Close": close,
            "Volume": volume,
        }
    )
    frame.to_parquet(kline_root / f"{symbol}.parquet", index=False)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False), encoding="utf-8")


def _validate_schema(payload: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
