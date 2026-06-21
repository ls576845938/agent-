from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_l2_feature_diagnostics_report import (
    build_btc_true_scalping_l2_feature_diagnostics_report,
)


SCHEMA = Path("schemas/btc_true_scalping_l2_feature_diagnostics_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_feature_diagnostics_report.json")


def test_btc_true_scalping_l2_feature_diagnostics_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_l2_feature_diagnostics_blocks_backtest_join() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    diagnostics = payload["feature_diagnostics"]
    alignment = payload["historical_alignment"]

    assert payload["status"] == "l2_feature_diagnostics_ready_research_only_backtest_blocked"
    assert payload["decision"] == "collect_timestamp_aligned_l2_history_before_event_ledger_feature_validation"
    assert diagnostics["book_snapshot_count"] >= 1
    assert diagnostics["trade_flow_sample_count"] >= 1
    assert diagnostics["joined_sample_count"] >= 1
    assert diagnostics["spread_bps"]["mean"] is not None
    assert diagnostics["depth_imbalance_top5"]["mean"] is not None
    assert diagnostics["trade_notional_imbalance"]["mean"] is not None
    assert alignment["timestamp_aligned_l2_history_available"] is False
    assert alignment["causal_event_ledger_join_allowed"] is False
    assert "btc_l2_features_bounded_sample_not_historical_l2" in payload["blockers"]
    assert "btc_l2_feature_event_ledger_validation_blocked_without_timestamp_aligned_history" in payload["blockers"]
    assert all(candidate["sample_observed"] is True for candidate in payload["feature_candidates"])
    assert all(candidate["event_ledger_backtest_usable"] is False for candidate in payload["feature_candidates"])
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["lookahead_used_for_signal"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False


def test_l2_feature_diagnostics_builder_computes_fixture_features(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    _write_text(
        bundle / "agg_trades_samples.csv",
        "\n".join(
            [
                "sample_index,sample_captured_at,timestamp,ts,symbol,trade_id,price,size,side,source_record_id",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:00Z,1781960000000,BTCUSDT,1,100.0,0.1,buy,t1",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:01Z,1781960001000,BTCUSDT,2,100.1,0.2,sell,t2",
                "2,2026-06-20T00:00:01Z,2026-06-20T00:00:02Z,1781960002000,BTCUSDT,3,100.2,0.3,buy,t3",
            ]
        )
        + "\n",
    )
    _write_text(
        bundle / "order_book_depth_samples.csv",
        "\n".join(
            [
                "sample_index,sample_captured_at,timestamp,ts,symbol,side,level,price,size,liquidation_orders,order_count,source_record_id",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:00Z,1781960000100,BTCUSDT,bid,1,99.9,2.0,0,1,b1",
                "1,2026-06-20T00:00:00Z,2026-06-20T00:00:00Z,1781960000100,BTCUSDT,ask,1,100.1,1.0,0,1,a1",
                "2,2026-06-20T00:00:01Z,2026-06-20T00:00:01Z,1781960001100,BTCUSDT,bid,1,100.0,1.0,0,1,b2",
                "2,2026-06-20T00:00:01Z,2026-06-20T00:00:01Z,1781960001100,BTCUSDT,ask,1,100.2,3.0,0,1,a2",
            ]
        )
        + "\n",
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json",
        {"status": "public_l2_sample_evidence_ready_research_only", "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture"},
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json",
        {"status": "verified", "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture"},
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_event_ledger/latest/btc_true_scalping_event_definition_redesign_report.json",
        {"data_context": {"start": "2026-05-01T00:00:00+00:00", "end": "2026-05-12T00:00:00+00:00"}},
    )

    payload = build_btc_true_scalping_l2_feature_diagnostics_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    diagnostics = payload["feature_diagnostics"]
    assert payload["status"] == "l2_feature_diagnostics_ready_research_only_backtest_blocked"
    assert diagnostics["book_snapshot_count"] == 2
    assert diagnostics["trade_flow_sample_count"] == 2
    assert diagnostics["joined_sample_count"] == 2
    assert diagnostics["spread_bps"]["mean"] == pytest.approx(19.990009990010274)
    assert diagnostics["microprice_edge_bps"]["mean"] == pytest.approx(-0.8308358308357835)
    assert diagnostics["depth_imbalance_top1"]["mean"] == pytest.approx(-0.08333333333333334)
    assert diagnostics["trade_size_imbalance"]["mean"] == pytest.approx(0.33333333333333337)
    assert payload["historical_alignment"]["overlaps_backtest_window"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False


def test_l2_feature_diagnostics_builder_blocks_missing_samples(tmp_path: Path) -> None:
    payload = build_btc_true_scalping_l2_feature_diagnostics_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "l2_feature_diagnostics_blocked_missing_sample_evidence"
    assert "btc_l2_sample_quality_not_ready" in payload["blockers"]
    assert "btc_l2_feature_diagnostics_no_valid_book_snapshots" in payload["blockers"]
    assert "btc_l2_feature_diagnostics_no_trade_flow_rows" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_l2_feature_diagnostics_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["event_ledger_feature_validation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
