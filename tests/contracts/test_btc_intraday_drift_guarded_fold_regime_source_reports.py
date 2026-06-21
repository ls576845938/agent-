from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_btc_intraday_drift_guarded_fold_regime_source_reports as builder


RUN = Path("artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger")


def test_current_drift_guarded_fold_regime_source_reports_pass_locked() -> None:
    data_status = json.loads((RUN / "btc_data_fold_regime_status_report.json").read_text(encoding="utf-8"))
    audit = json.loads((RUN / "fold_regime_contract_audit.json").read_text(encoding="utf-8"))

    assert data_status["schema_version"] == "btc_data_fold_regime_status_report_v1"
    assert data_status["source_event_ledger_report"] == (
        "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger/"
        "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"
    )
    assert data_status["fold_status"]["status"] == "pass"
    assert data_status["fold_status"]["fold_count"] == 6
    intervals = {row["interval"]: row for row in data_status["intervals"]}
    assert intervals["1m"]["status"] == "pass"
    assert intervals["1m"]["manifest_status"] == "pass"
    assert intervals["1m"]["data_version"].startswith("qs-sqlite-BTCUSDT-1m-")
    assert data_status["regime_status"]["status"] == "pass"
    assert data_status["regime_status"]["gate_pass_rate"] == pytest.approx(0.8)
    assert data_status["regime_status"]["dragging_regimes"] == ["expansion"]

    assert audit["schema_version"] == "btc_fold_regime_contract_audit_v1"
    assert audit["fold_contract"]["status"] == "pass"
    assert audit["regime_contract"]["status"] == "pass"
    assert audit["regime_contract"]["pass_rate"] == pytest.approx(0.8)
    assert audit["promotion_contract"]["paper_ready_allowed"] is False
    assert audit["promotion_contract"]["live_ready_allowed"] is False
    assert audit["promotion_contract"]["live_enabled_allowed"] is False


def test_drift_guarded_fold_regime_source_builder_writes_fixture_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "artifacts/btc_intraday_event_ledger/drift_fixture"
    coverage = tmp_path / "artifacts/coverage/btc_data_fold_regime_status_report.json"
    _write_json(
        run_dir / "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        {
            "run_id": "drift_fixture",
            "strategy_id": "btc_fixture_strategy",
        },
    )
    _write_json(
        run_dir / "walk_forward_report.json",
        {
            "method": "fixture_walk_forward",
            "fold_count": 2,
            "windows": [
                {
                    "fold": 1,
                    "validation_start": "2026-01-01T00:00:00+00:00",
                    "validation_end": "2026-01-02T00:00:00+00:00",
                    "validation_rows": 288,
                    "event_count": 5,
                    "passed": True,
                },
                {
                    "fold": 2,
                    "validation_start": "2026-01-02T00:05:00+00:00",
                    "validation_end": "2026-01-03T00:00:00+00:00",
                    "validation_rows": 287,
                    "event_count": 4,
                    "passed": False,
                },
            ],
        },
    )
    _write_json(
        run_dir / "regime_report.json",
        {
            "pass_rate": 0.8,
            "dragging_regimes": ["expansion"],
            "regimes": [{"regime": "high_vol_trend"}, {"regime": "trending_up"}],
        },
    )
    _write_json(
        coverage,
        {
            "sqlite": {"status": "pass", "symbol": "BTCUSDT", "exchange": "binance_spot"},
            "intervals": [
                {
                    "interval": "5m",
                    "status": "pass",
                    "manifest_status": "pass",
                    "row_count": 575,
                    "expected_rows": 575,
                    "missing_rows": 0,
                    "data_version": "qs-sqlite-BTCUSDT-5m-fixture",
                    "latest_manifest_path": "data/manifests/btc-5m-fixture.json",
                    "start": "2026-01-01T00:00:00+00:00",
                    "end": "2026-01-03T00:00:00+00:00",
                }
            ],
            "manifest_lineage": {"status": "pass"},
        },
    )
    monkeypatch.setattr(builder, "_bar_regime_counts", lambda: {"high_vol_trend": 42})

    data_status, audit = builder.build_drift_guarded_fold_regime_source_reports(
        repo_root=tmp_path,
        run_dir=run_dir,
        coverage_source=coverage,
        generated_at="2026-06-20T00:00:00Z",
    )
    outputs = builder.write_drift_guarded_fold_regime_source_reports(data_status, audit, run_dir)

    assert [Path(output).name for output in outputs] == [
        "btc_data_fold_regime_status_report.json",
        "fold_regime_contract_audit.json",
    ]
    assert data_status["run_id"] == "drift_fixture"
    assert data_status["fold_status"]["status"] == "pass"
    assert data_status["fold_status"]["fold_count"] == 2
    assert data_status["fold_status"]["event_table_fold_counts"] == {"1": 5, "2": 4}
    assert data_status["regime_status"]["status"] == "pass"
    assert data_status["regime_status"]["bar_counts"] == {"high_vol_trend": 42}
    assert audit["promotion_contract"]["paper_ready_allowed"] is False
    assert audit["promotion_contract"]["live_ready_allowed"] is False
    assert audit["promotion_contract"]["live_enabled_allowed"] is False
    assert json.loads((run_dir / "fold_regime_contract_audit.json").read_text(encoding="utf-8"))["run_id"] == (
        "drift_fixture"
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
