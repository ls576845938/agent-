from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from quant_us.research.lab.manifest import ExperimentManager


def test_factor_rank_experiment_passes_factor_features_to_unified_runner(
    monkeypatch,
    tmp_path,
) -> None:
    seen: dict[str, object] = {}

    def fake_read_cleaned_bars(
        self,
        *,
        symbol,
        start,
        end,
        bar_size,
        vendor,
        asset_class,
    ):
        return pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(
                    "2024-01-01 14:30",
                    periods=4,
                    freq="5min",
                    tz="UTC",
                ),
                "symbol": [symbol] * 4,
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [101.0, 102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0, 102.0],
                "close": [100.5, 101.5, 102.5, 103.5],
                "volume": [1_000_000] * 4,
            }
        )

    def fake_compute(
        self,
        *,
        factor_ids,
        symbols,
        start,
        end,
        bar_size,
        timeframe=None,
    ):
        assert factor_ids == ["momentum_20d"]
        assert symbols == ["AAPL", "MSFT"]
        assert bar_size == "5m"
        assert timeframe == "5m"
        return pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(
                    "2024-01-01 14:30",
                    periods=4,
                    freq="5min",
                    tz="UTC",
                ).tolist()
                * 2,
                "date": [pd.Timestamp("2024-01-01").date()] * 8,
                "symbol": ["AAPL"] * 4 + ["MSFT"] * 4,
                "momentum_20d": [0.9, 0.8, 0.7, 0.6, 0.1, 0.2, 0.3, 0.4],
            }
        )

    def fake_runner_run(
        self,
        *,
        strategies,
        frame,
        features_frame=None,
        data_version="",
        strategy_version="",
        bars_override=None,
    ):
        seen["features_frame"] = features_frame
        seen["strategy_id"] = strategies[0].strategy_id
        return SimpleNamespace(
            summary={
                "sharpe_ratio": 1.1,
                "total_return_pct": 0.08,
                "max_drawdown_pct": 0.10,
                "trade_count": 12,
            },
            evidence={
                "data_manifest": {},
                "ledger_artifact_path": "",
                "ledger_artifact_hash": "",
                "ledger_hash": "ledgerhash",
                "fills_hash": "fillshash",
                "orders_hash": "ordershash",
                "data_manifest_exists": False,
                "missing_data_manifest": True,
            },
            manifest_path="",
            manifest_id="ubt_test",
            equity_consistent=True,
            orders=[object()] * 12,
            fills=[object()] * 12,
        )

    monkeypatch.setattr(
        "quant_us.data.pipeline.DataLakeService.read_cleaned_bars",
        fake_read_cleaned_bars,
    )
    monkeypatch.setattr(
        "quant_us.factors.pipeline.FactorPipeline.compute",
        fake_compute,
    )
    monkeypatch.setattr(
        "quant_us.backtest.unified_runner.UnifiedBacktestRunner.run",
        fake_runner_run,
    )

    manager = ExperimentManager(data_root=str(tmp_path))
    manifest = manager.create(
        strategy_id="factor_rank",
        symbols=["AAPL", "MSFT"],
        params={"factor_name": "momentum_20d", "top_n": 1, "min_symbols": 2},
        start_date="2024-01-01",
        end_date="2024-01-02",
        timeframe="5m",
        data_version="unit_factor_rank",
    )

    result = manager.run(manifest.experiment_id)

    assert result["engine"] == "event_driven"
    assert seen["strategy_id"] == "factor_rank"
    assert isinstance(seen["features_frame"], pd.DataFrame)
    features_frame = seen["features_frame"]
    assert "momentum_20d" in features_frame.columns
    loaded = manager.load(manifest.experiment_id)
    assert loaded is not None
    assert loaded.status == "COMPLETED"
