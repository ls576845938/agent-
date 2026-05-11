from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.data.storage.parquet_store import ParquetBarStore
from quant_us.research.automation.promotion_gate import ResearchPromotionGate
from quant_us.research.lab.manifest import ExperimentManager


UTC = timezone.utc


def _write_cleaned_bars(data_root: Path) -> tuple[str, str]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    rows = []
    for index in range(20):
        price = 100.0 + index
        rows.append(
            {
                "timestamp_utc": start + timedelta(minutes=index),
                "symbol": "AAPL",
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 100_000.0,
            }
        )
    frame = pd.DataFrame(rows)
    ParquetBarStore(data_root / "cleaned").write_bars(
        frame=frame,
        vendor="yfinance",
        asset_class="equity",
        bar_size="1d",
        symbol="AAPL",
    )
    return start.isoformat(), (start + timedelta(minutes=19)).isoformat()


def _write_data_manifest(data_root: Path, start: str, end: str) -> str:
    data_version = "qs-yfinance-AAPL-1d-test"
    DataManifestStore(data_root / "manifests").write(
        DataManifest(
            data_version=data_version,
            source="yfinance",
            symbol="AAPL",
            interval="1d",
            asset_class="equity",
            timezone="UTC",
            start=start,
            end=end,
            row_count=20,
            expected_rows=20,
            coverage_pct=100.0,
            fingerprint="test-fingerprint",
            checksum="test-fingerprint",
            quality_score=95.0,
            universe_id="unit-test-universe",
            universe_source="unit-test",
            survivorship_bias_risk="clean",
        )
    )
    return data_version


def test_experiment_promote_materializes_canonical_backtest_manifest(
    tmp_path: Path,
) -> None:
    start, end = _write_cleaned_bars(tmp_path)
    data_version = _write_data_manifest(tmp_path, start, end)
    manager = ExperimentManager(data_root=str(tmp_path))
    experiment = manager.create(
        strategy_id="trend_momentum",
        symbols=["AAPL"],
        params={"lookback_bars": 1, "entry_threshold": 0.0001},
        start_date=start,
        end_date=end,
        data_version=data_version,
        strategy_version="trend_momentum_test_v1",
    )

    summary = manager.run(experiment.experiment_id)
    candidate = manager.promote_to_candidate(experiment.experiment_id)

    canonical_path = (
        tmp_path
        / "research"
        / "backtests"
        / candidate.candidate_id
        / "run_manifest.json"
    )
    candidate_path = (
        tmp_path
        / "research"
        / "candidates"
        / candidate.candidate_id
        / "candidate.json"
    )
    experiment_manifest_path = (
        tmp_path
        / "research"
        / "experiments"
        / experiment.experiment_id
        / "manifest.json"
    )

    assert summary["backtest_manifest_path"]
    assert Path(summary["backtest_manifest_path"]).exists()
    assert canonical_path.exists()
    assert candidate.backtest_manifest_path == str(canonical_path)

    candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))
    experiment_data = json.loads(experiment_manifest_path.read_text(encoding="utf-8"))
    manifest = json.loads(canonical_path.read_text(encoding="utf-8"))

    assert candidate_data["backtest_manifest_path"] == str(canonical_path)
    assert candidate_data["metrics"]["backtest_manifest_path"] == str(canonical_path)
    assert candidate_data["ledger_artifact_path"] == summary["ledger_artifact_path"]
    assert candidate_data["ledger_artifact_hash"] == summary["ledger_artifact_hash"]
    assert experiment_data["backtest_manifest_path"] == summary["backtest_manifest_path"]
    assert experiment_data["ledger_artifact_path"] == summary["ledger_artifact_path"]

    assert manifest["candidate_id"] == candidate.candidate_id
    assert manifest["experiment_id"] == experiment.experiment_id
    assert manifest["engine"] == "event_driven"
    assert manifest["canonical_for_promotion"] is True
    assert manifest["data_manifest_exists"] is True
    assert manifest["missing_data_manifest"] is False
    assert manifest["data_manifest"]["path"] == str(tmp_path / "manifests" / f"{data_version}.json")
    assert manifest["ledger_artifact_path"] == summary["ledger_artifact_path"]
    assert json.loads(Path(manifest["ledger_artifact_path"]).read_text(encoding="utf-8")) == manifest["ledger_artifact"]

    gate = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate.candidate_id)
    assert gate.evidence["backtest_manifest_present"] is True
    assert gate.evidence["backtest_manifest_resolved_path"] == str(canonical_path)
    assert gate.evidence["ledger_artifact_file_present"] is True
    assert gate.evidence["ledger_artifact_file_payload_match"] is True
    assert gate.evidence["data_manifest_exists"] is True
    assert "missing_canonical_backtest_manifest_path" not in gate.reasons
    assert "missing_backtest_manifest_evidence" not in gate.reasons
