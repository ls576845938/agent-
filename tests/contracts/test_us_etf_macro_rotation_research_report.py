from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import jsonschema

from quant_us.research.us_etf_macro_momentum_rotation import (
    UsEtfMacroMomentumRotationConfig,
    build_price_matrix_from_bars,
    run_us_etf_macro_momentum_rotation,
)
from scripts.build_us_etf_macro_rotation_research_report import (
    build_us_etf_macro_rotation_research_report,
    write_report,
)


SCHEMA_PATH = Path("schemas/us_etf_macro_rotation_research_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_required_symbols_are_unique_and_include_defense_assets() -> None:
    cfg = UsEtfMacroMomentumRotationConfig()

    required = cfg.required_symbols()

    assert len(required) == len(set(required))
    assert "SPY" in required
    assert "IEF" in required
    assert "SHV" in required
    assert required.count("GLD") == 1


def test_report_runs_research_only_with_complete_prices_and_missing_macro(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    _write_data_status(tmp_path, promotion_clean=True, blockers=[])
    _write_cleaned_prices(tmp_path, cfg.required_symbols(), periods=420)

    report = build_us_etf_macro_rotation_research_report(repo_root=tmp_path, config=cfg, external_data_lake=None)
    path = write_report(report, tmp_path / "artifacts/us_equity_etf_macro_rotation/latest")

    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_schema(payload)
    assert payload["status"] == "partial"
    assert payload["allowed_next_action"] == "research_only"
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["macro_data"]["neutral_regime_used"] is True
    assert payload["architecture"]["separation_status"] == "signals_portfolio_execution_decoupled"
    assert payload["architecture"]["alpha_signal_module"] == "quant_us.signals.us_etf_rotation_alpha"
    assert payload["architecture"]["portfolio_construction_module"] == "quant_us.portfolio.us_etf_rotation_portfolio"
    assert payload["architecture"]["execution_simulation_module"] == "quant_us.execution.us_etf_rotation_execution"
    assert payload["backtest"]["status"] == "complete"
    assert payload["backtest"]["metrics"]["rows"] > 300
    assert payload["signal_integrity"]["t_plus_1_execution"] is True
    assert payload["outputs"]["target_weights_csv"]
    assert (tmp_path / payload["outputs"]["target_weights_csv"]).exists()
    assert "us_etf_macro_rotation_macro_data_missing_neutral_regime_used" in payload["blockers"]


def test_report_blocks_when_required_etf_prices_are_missing(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=50)
    _write_data_status(tmp_path, promotion_clean=True, blockers=[])
    _write_cleaned_prices(tmp_path, ["SPY", "QQQ"], periods=120)

    report = build_us_etf_macro_rotation_research_report(repo_root=tmp_path, config=cfg, external_data_lake=None)

    _validate_schema(report)
    assert report["status"] == "blocked"
    assert report["backtest"]["status"] == "blocked"
    assert "IEF" in report["data"]["missing_symbols"]
    assert report["outputs"]["target_weights_csv"] is None
    assert "us_etf_macro_rotation_required_price_symbols_missing" in report["blockers"]


def test_rotation_backtest_keeps_rebalance_signal_t_plus_1(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    bars = _synthetic_bars(cfg.required_symbols(), periods=420)
    prices = build_price_matrix_from_bars(bars, cfg.required_symbols())

    result = run_us_etf_macro_momentum_rotation(prices, pd.DataFrame(), cfg)

    assert result.diagnostics["t_plus_1_execution"] is True
    assert result.daily_weights.abs().sum(axis=1).iloc[0] == 0.0
    assert result.daily_weights.abs().sum(axis=1).max() > 0.0


def test_report_uses_external_data_lake_when_canonical_prices_are_missing(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    _write_data_status(tmp_path, promotion_clean=True, blockers=[])
    external_lake = tmp_path / "external_lake"
    _write_external_data_lake(external_lake, cfg.required_symbols(), periods=420)
    _write_external_macro(external_lake, periods=420)

    report = build_us_etf_macro_rotation_research_report(
        repo_root=tmp_path,
        config=cfg,
        external_data_lake=external_lake,
    )

    assert report["status"] == "partial"
    assert report["data"]["price_source"] == "external_data_lake"
    assert report["data"]["missing_symbols"] == []
    assert report["macro_data"]["status"] == "available"
    assert report["backtest"]["status"] == "complete"
    assert report["outputs"]["target_weights_csv"]
    assert "us_etf_macro_rotation_required_price_symbols_missing" not in report["blockers"]


def test_report_prefers_tiingo_eod_lake_when_available(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    _write_data_status(tmp_path, promotion_clean=True, blockers=[])
    tiingo_lake = tmp_path / "tiingo_eod_lake"
    _write_tiingo_data_lake(tiingo_lake, cfg.required_symbols(), periods=420)

    report = build_us_etf_macro_rotation_research_report(
        repo_root=tmp_path,
        config=cfg,
        tiingo_data_lake=tiingo_lake,
        external_data_lake=None,
    )

    assert report["data"]["price_source"] == "tiingo_eod"
    assert report["data"]["price_source_precedence"][0] == "tiingo_eod"
    assert report["data"]["missing_symbols"] == []
    assert report["data"]["tiingo_eod_coverage"]["SPY"]["status"] == "available"
    assert report["backtest"]["status"] == "complete"


def test_research_report_schema_rejects_live_ready(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    _write_data_status(tmp_path, promotion_clean=True, blockers=[])
    _write_cleaned_prices(tmp_path, cfg.required_symbols(), periods=420)

    report = build_us_etf_macro_rotation_research_report(repo_root=tmp_path, config=cfg, external_data_lake=None)
    report["live_ready"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("schema accepted live_ready=true")


def test_report_falls_back_when_tiingo_lake_is_incomplete(tmp_path: Path) -> None:
    cfg = UsEtfMacroMomentumRotationConfig(min_rows=300)
    _write_data_status(tmp_path, promotion_clean=True, blockers=[])
    tiingo_lake = tmp_path / "tiingo_eod_lake"
    external_lake = tmp_path / "external_lake"
    _write_tiingo_data_lake(tiingo_lake, ["SPY", "QQQ"], periods=420)
    _write_external_data_lake(external_lake, cfg.required_symbols(), periods=420)
    _write_external_macro(external_lake, periods=420)

    report = build_us_etf_macro_rotation_research_report(
        repo_root=tmp_path,
        config=cfg,
        tiingo_data_lake=tiingo_lake,
        external_data_lake=external_lake,
    )

    assert report["data"]["price_source"] == "external_data_lake"
    tiingo_candidate = next(row for row in report["data"]["fallback_price_sources"] if row["source"] == "tiingo_eod")
    assert tiingo_candidate["complete"] is False
    assert "IEF" in tiingo_candidate["missing_symbols"]
    assert report["data"]["missing_symbols"] == []


def _write_data_status(tmp_path: Path, *, promotion_clean: bool, blockers: list[str]) -> None:
    path = tmp_path / "artifacts/us_equity_data_status/latest/data_status_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "promotion_clean": promotion_clean,
                "blockers": blockers,
                "data_lineage_grade": {"value": "L4_promotion_clean" if promotion_clean else "L1_sample_non_pit"},
            }
        ),
        encoding="utf-8",
    )


def _write_cleaned_prices(tmp_path: Path, symbols: list[str] | tuple[str, ...], *, periods: int) -> None:
    bars = _synthetic_bars(symbols, periods=periods)
    cleaned_root = tmp_path / "data/cleaned/vendor=yfinance/asset_class=equity/bar_size=1d"
    for symbol, frame in bars.groupby("symbol"):
        symbol_dir = cleaned_root / f"symbol={symbol}"
        symbol_dir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(symbol_dir / "date=fixture.parquet", index=False)


def _write_external_data_lake(root: Path, symbols: list[str] | tuple[str, ...], *, periods: int) -> None:
    bars = _synthetic_bars(symbols, periods=periods)
    kline_root = root / "kline"
    for symbol, frame in bars.groupby("symbol"):
        kline_root.mkdir(parents=True, exist_ok=True)
        external = frame.rename(
            columns={
                "timestamp_utc": "datetime",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
        )[["datetime", "Open", "High", "Low", "Close", "Volume"]]
        external.to_parquet(kline_root / f"{symbol}.parquet", index=False)


def _write_tiingo_data_lake(root: Path, symbols: list[str] | tuple[str, ...], *, periods: int) -> None:
    _write_external_data_lake(root, symbols, periods=periods)


def _write_external_macro(root: Path, *, periods: int) -> None:
    dates = pd.bdate_range("2020-01-01", periods=periods, tz="UTC")
    macro = pd.DataFrame(
        {
            "datetime": dates,
            "WALCL": np.linspace(1.0, 2.0, periods),
            "WTREGEN": np.linspace(0.1, 0.2, periods),
            "RRPONTSYD": np.linspace(0.1, 0.15, periods),
            "BAMLC0A0CM": np.linspace(1.0, 0.8, periods),
            "DGS10": np.linspace(4.0, 4.2, periods),
            "DGS2": np.linspace(3.5, 3.8, periods),
        }
    )
    macro_root = root / "macro"
    macro_root.mkdir(parents=True, exist_ok=True)
    macro.to_parquet(macro_root / "FRED_MACRO.parquet", index=False)


def _synthetic_bars(symbols: list[str] | tuple[str, ...], *, periods: int) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=periods, tz="UTC")
    rows = []
    x = np.arange(periods, dtype=float)
    for index, symbol in enumerate(symbols):
        drift = 0.02 + index * 0.002
        seasonal = np.sin(x / (18.0 + index)) * (0.4 + index * 0.03)
        close = 50.0 + index * 3.0 + x * drift + seasonal
        close = np.maximum(close, 3.0)
        frame = pd.DataFrame(
            {
                "timestamp_utc": dates,
                "symbol": symbol,
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 1_000_000 + index,
            }
        )
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)
