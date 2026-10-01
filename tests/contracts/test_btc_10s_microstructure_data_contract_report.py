from __future__ import annotations

import inspect
import json
from pathlib import Path

import jsonschema
import pytest

from quant_crypto.research.btc_10s_microstructure_data_contract import (
    ContractError,
    _feed_windows,
    build_contract_lock,
    build_report,
    derive_measured_metrics,
    evaluate_readiness,
    inspect_resolved_source,
    resolve_source,
    write_immutable_artifact_bundle,
)
from scripts.build_btc_10s_microstructure_data_contract_report import (
    exact_manifest_specs,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = ROOT / "docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"
SCHEMA_PATH = ROOT / "schemas/btc_10s_microstructure_data_contract_report.schema.json"


def _prereg() -> dict[str, object]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _ready_metrics() -> dict[str, object]:
    information = {
        horizon: {
            "eligible_labeled_windows": 1_200,
            "autocorrelation_adjusted_ess": 600.0,
            "joined_coverage_pct": 99.5,
            "future_label_availability_pct": 99.5,
        }
        for horizon in ("10s", "30s", "60s")
    }
    return {
        "raw_counts": {},
        "information_by_horizon": information,
        "utc_4h_bucket_independent_60s_windows": [120] * 6,
        "weekday_independent_60s_windows": [120] * 7,
        "regime_cell_ess": [60.0] * 9,
        "quality": {
            "duplicate_count": 0,
            "out_of_order_count": 0,
            "unrecovered_sequence_gap_count": 0,
            "crossed_book_count": 0,
            "one_sided_book_count": 0,
            "reconnect_snapshot_reset_verified": True,
            "gap_resync_embargo_seconds": 60,
            "receive_lag_p99_ms": 400.0,
            "trade_book_alignment_p99_ms": 200.0,
        },
        "cost": {
            "sample_completeness_pct": 99.5,
            "spread_available": True,
            "fee_available": True,
            "depth_impact_available": True,
            "stratified_stability_verified": True,
        },
        "coverage": {},
        "reference_data": {},
        "fields": {
            "unique_tick_trade_ids": True,
            "exchange_timestamps": True,
            "aggressor_side": True,
            "two_sided_bbo": True,
            "trade_bbo_joined": True,
            "trade_ordered_l2_joined": False,
            "l2_price_levels": False,
            "ordered_l2_updates": False,
            "volume_depth_shock": True,
            "recovery_events": False,
            "time_aligned_open_interest": False,
            "liquidation_events": False,
        },
    }


def test_prereg_freezes_information_gates_without_natural_day_requirement() -> None:
    prereg = _prereg()
    serialized = json.dumps(prereg, sort_keys=True).lower()
    assert "natural_day" not in serialized
    assert "30_days" not in serialized
    thresholds = prereg["information_thresholds"]
    assert thresholds["eligible_labeled_windows_by_horizon"] == {
        "10s": 1000,
        "30s": 1000,
        "60s": 1000,
    }
    assert thresholds["autocorrelation_adjusted_ess_by_horizon"] == {
        "10s": 500,
        "30s": 500,
        "60s": 500,
    }
    assert thresholds["utc_4h_bucket_count"] == 6
    assert thresholds["min_independent_60s_windows_per_utc_4h_bucket"] == 100
    assert thresholds["volatility_liquidity_regime_grid"] == [3, 3]
    assert thresholds["min_ess_per_applicable_regime_cell"] == 50
    assert thresholds["joined_coverage_pct"] == 99
    assert thresholds["future_label_availability_pct"] == 99
    assert thresholds["receive_lag_p99_ms"] == 500
    assert thresholds["trade_book_alignment_p99_ms"] == 250
    assert thresholds["gap_resync_embargo_seconds"] == 60


def test_family_specific_gate_does_not_spill_liquidation_requirements() -> None:
    result = evaluate_readiness(_prereg(), _ready_metrics())
    matrix = {(row["family"], row["horizon"]): row for row in result}
    for horizon in ("10s", "30s", "60s"):
        trade = matrix[("trade_imbalance_continuation", horizon)]
        assert trade["status"] == "ready"
        assert trade["capabilities"]["trade_imbalance"] is True
        assert trade["capabilities"]["order_flow_imbalance"] is False
        assert "time_aligned_open_interest_missing" not in trade["blockers"]
        assert "liquidation_events_missing" not in trade["blockers"]

        liquidation = matrix[("liquidation_cascade_recovery", horizon)]
        assert liquidation["status"] == "blocked"
        assert "time_aligned_open_interest_missing" in liquidation["blockers"]
        assert "liquidation_events_missing" in liquidation["blockers"]

        maker = matrix[("maker_queue", horizon)]
        assert maker["status"] == "not_applicable"
        assert maker["execution_baseline"] == "taker_only"


def test_short_fragment_stays_blocked_insufficient_information() -> None:
    metrics = _ready_metrics()
    metrics["information_by_horizon"]["10s"]["eligible_labeled_windows"] = 8
    metrics["information_by_horizon"]["10s"]["autocorrelation_adjusted_ess"] = 8.0
    result = evaluate_readiness(_prereg(), metrics)
    applicable = [
        row
        for row in result
        if row["horizon"] == "10s" and row["status"] != "not_applicable"
    ]
    assert applicable
    assert all(row["status"] == "blocked" for row in applicable)
    assert all("blocked_insufficient_information" in row["blockers"] for row in applicable)


def test_missing_physical_version_has_no_mutable_or_latest_fallback(tmp_path: Path) -> None:
    manifest = {
        "dataset_id": "btc-okx-timestamp-aligned-public-l2-history",
        "dataset_version": "missing-version",
        "aggregate_sha256": "a" * 64,
        "storage_relative_path": "datasets/x/y",
        "files": [{"path": "payload.jsonl", "sha256": "b" * 64, "bytes": 1}],
    }
    calls: list[bool] = []

    def resolver(payload: object, *, shared_root: Path, verify_files: bool) -> Path:
        calls.append(verify_files)
        raise ValueError("shared_data_physical_version_missing")

    result = resolve_source(
        repo_root=tmp_path,
        shared_root=tmp_path / "shared",
        manifest_git_spec="HEAD:.agent/data_manifests/missing.json",
        manifest_loader=lambda *_: manifest,
        manifest_resolver=resolver,
        blob_reader=lambda *_: b"{}\n",
    )
    assert calls == [True]
    assert result["resolution_status"] == "physical_version_missing"
    assert result["physical_path"] is None
    assert result["fallback_used"] is False
    assert "latest" not in inspect.signature(resolve_source).parameters
    assert "sqlite" not in inspect.signature(resolve_source).parameters


def test_builder_accepts_only_repeatable_exact_committed_manifest_specs() -> None:
    value = (
        "a" * 40
        + ":.agent/data_manifests/btc-okx-10s-microstructure-immutable-feed/v1.json"
    )
    assert exact_manifest_specs(manifest_ref="b" * 40, explicit_specs=[value]) == [value]
    for invalid in (
        "HEAD:.agent/data_manifests/x/v1.json",
        "latest:.agent/data_manifests/x/v1.json",
        "a" * 40 + ":.agent/data_manifests/x/*.json",
        "a" * 40 + ":artifacts/latest/report.json",
    ):
        with pytest.raises(ValueError, match="exact_committed_manifest_git_spec_required"):
            exact_manifest_specs(manifest_ref="b" * 40, explicit_specs=[invalid])


def test_same_version_feed_computes_real_windows_ess_and_family_gate(tmp_path: Path) -> None:
    immutable = tmp_path / "immutable_export"
    trades_path = immutable / "normalized-trades/venue=okx/instrument_id=BTC-USDT-SWAP/date=2026-08-27/part-00000.jsonl"
    trades_path.parent.mkdir(parents=True)
    rows = []
    for index in range(13):
        second = index * 10
        minute, remainder = divmod(second, 60)
        timestamp = f"2026-08-27T00:{minute:02d}:{remainder:02d}.000Z"
        rows.append(
            {
                "trade_id": f"t{index}",
                "event_time": timestamp,
                "available_time": timestamp,
                "capture_sequence": index * 2 + 2,
                "connection_sequence": 1,
                "price": 100.0 + index,
                "aggressor_side": "buy" if index % 2 == 0 else "sell",
                "book_joined": True,
                "book_capture_sequence": index * 2 + 1,
                "book_available_time": timestamp,
                "best_bid": 99.5 + index,
                "best_ask": 100.5 + index,
                "mid": 100.0 + index,
                "spread_bps": 100.0,
                "depth_impact_bps": 1.0,
                "taker_fee_bps": 5.0,
                "estimated_one_way_cost_bps": 56.0,
            }
        )
    trades_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    attestation = {
        "coverage_start": rows[0]["event_time"],
        "coverage_end": rows[-1]["event_time"],
        "joined_coverage_pct": 100.0,
        "cost_sample_completeness_pct": 100.0,
        "receive_lag_p99_ms": 0.0,
        "trade_book_alignment_p99_ms": 0.0,
        "duplicate_trade_count": 0,
        "same_connection_trade_ordered_l2": True,
        "ordered_l2": {
            "snapshot_count": 1,
            "update_count": 12,
            "duplicate_sequence_count": 0,
            "out_of_order_sequence_count": 0,
            "unrecovered_gap_count": 0,
            "reconnect_count": 0,
            "resync_snapshot_count": 0,
            "two_sided_coverage_pct": 100.0,
        },
    }
    _assert_physical_fixture(tmp_path, immutable, rows, attestation, trades_path)


def _window_rows(*, seconds: int = 300, reconnect_at: int | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for second in range(0, seconds + 1, 10):
        minute, remainder = divmod(second, 60)
        timestamp = f"2026-08-27T00:{minute:02d}:{remainder:02d}.000Z"
        epoch = 1 if reconnect_at is None or second < reconnect_at else 2
        mid = 100.0 + second / 1_000.0
        rows.append({
            "event_time": timestamp,
            "capture_sequence": second + 1,
            "connection_sequence": epoch,
            "price": mid + (0.25 if second % 20 == 0 else -0.25),
            "mid": mid,
            "book_joined": True,
            "estimated_one_way_cost_bps": 5.0,
        })
    return rows


def test_feed_windows_apply_epoch_embargo_and_exclude_cross_epoch_labels() -> None:
    assert _feed_windows(_window_rows(seconds=50), 10)["potential"] == 0
    assert _feed_windows(_window_rows(seconds=50), 10)["windows"] == []
    long_result = _feed_windows(_window_rows(seconds=300), 60)
    assert long_result["potential"] > 0
    assert long_result["windows"]
    reconnected = _feed_windows(_window_rows(seconds=300, reconnect_at=180), 60)
    assert all(row["connection_sequence"] in {"1", "2"} for row in reconnected["windows"])
    assert all(row["start"].minute not in {2, 3} for row in reconnected["windows"])


def test_feed_window_label_uses_mid_and_regime_features_are_future_invariant() -> None:
    baseline_rows = _window_rows(seconds=180)
    baseline = _feed_windows(baseline_rows, 60)["windows"]
    mutated = json.loads(json.dumps(baseline_rows))
    for row in mutated:
        if row["event_time"] > "2026-08-27T00:01:00.000Z":
            row["mid"] = float(row["mid"]) * 1.02
            row["price"] = float(row["price"]) * 0.80
    changed = _feed_windows(mutated, 60)["windows"]
    assert baseline[0]["decision_volatility"] == changed[0]["decision_volatility"]
    assert baseline[0]["decision_liquidity_cost_bps"] == changed[0]["decision_liquidity_cost_bps"]
    assert baseline[0]["cost_adjusted_return"] != changed[0]["cost_adjusted_return"]
    bounce_only = json.loads(json.dumps(baseline_rows))
    for row in bounce_only:
        row["price"] = float(row["price"]) + 25.0
    assert _feed_windows(bounce_only, 60)["windows"][0]["cost_adjusted_return"] == baseline[0]["cost_adjusted_return"]


def _assert_physical_fixture(
    tmp_path: Path,
    immutable: Path,
    rows: list[dict[str, object]],
    attestation: dict[str, object],
    trades_path: Path,
) -> None:
    attestation_path = immutable / "btc_okx_10s_microstructure_immutable_feed_attestation.json"
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    ordered_path = immutable / "ordered-l2" / "part-00000.jsonl"
    ordered_path.parent.mkdir(parents=True)
    ordered_path.write_text(
        "".join(
            json.dumps({"best_bid": 99.0, "best_ask": 101.0}) + "\n"
            for _ in rows
        ),
        encoding="utf-8",
    )
    relative = trades_path.relative_to(tmp_path).as_posix()
    ordered_relative = ordered_path.relative_to(tmp_path).as_posix()
    source = inspect_resolved_source(
        {
            "dataset_id": "btc-okx-10s-microstructure-immutable-feed",
            "dataset_version": "fixture-v1",
            "resolution_status": "resolved_verified",
            "full_file_hash_verified": True,
            "fallback_used": False,
            "_resolved_root": tmp_path,
            "_manifest": {
                "files": [{"path": relative}, {"path": ordered_relative}]
            },
        }
    )
    metrics = derive_measured_metrics([source])
    assert metrics["information_by_horizon"]["10s"]["eligible_labeled_windows"] == 6
    assert metrics["information_by_horizon"]["30s"]["eligible_labeled_windows"] == 2
    assert metrics["information_by_horizon"]["60s"]["eligible_labeled_windows"] == 1
    assert metrics["information_by_horizon"]["10s"]["autocorrelation_adjusted_ess"] > 0
    assert metrics["fields"]["trade_ordered_l2_joined"] is True
    assert metrics["quality"]["one_sided_book_count"] == 0
    assert metrics["coverage"]["ordered_l2_two_sided_coverage_pct"] == 100.0
    second = json.loads(json.dumps(source))
    second["measured"]["coverage_start"] = "2026-08-27T01:00:00Z"
    second["measured"]["coverage_end"] = "2026-08-27T01:02:00Z"
    combined = derive_measured_metrics([source, second])
    assert combined["raw_counts"]["trade_rows"] == 26
    assert combined["information_by_horizon"]["10s"]["eligible_labeled_windows"] == 12
    assert combined["information_by_horizon"]["30s"]["eligible_labeled_windows"] == 4
    assert combined["information_by_horizon"]["60s"]["eligible_labeled_windows"] == 2
    matrix = evaluate_readiness(_prereg(), metrics)
    trade_10s = next(row for row in matrix if row["family"] == "trade_imbalance_continuation" and row["horizon"] == "10s")
    assert trade_10s["status"] == "blocked"
    assert "blocked_insufficient_information" in trade_10s["blockers"]
    ordered_path.write_text(
        json.dumps({"best_bid": 101.0, "best_ask": 100.0})
        + "\n"
        + json.dumps({"best_bid": 99.0, "best_ask": None})
        + "\n",
        encoding="utf-8",
    )
    degraded = derive_measured_metrics(
        [
            inspect_resolved_source(
                {
                    "dataset_id": "btc-okx-10s-microstructure-immutable-feed",
                    "dataset_version": "fixture-v1",
                    "resolution_status": "resolved_verified",
                    "full_file_hash_verified": True,
                    "fallback_used": False,
                    "_resolved_root": tmp_path,
                    "_manifest": {
                        "files": [
                            {"path": relative},
                            {"path": ordered_relative},
                        ]
                    },
                }
            )
        ]
    )
    assert degraded["quality"]["crossed_book_count"] == 1
    assert degraded["quality"]["one_sided_book_count"] == 1


def test_multi_slice_coverage_and_regimes_are_recomputed_from_global_pool() -> None:
    observations = [
        {
            "segment_id": f"slice-{index % 2}",
            "cost_adjusted_return": 0.001 * (index + 1),
            "decision_volatility": float(volatility),
            "decision_liquidity_cost_bps": float(liquidity),
        }
        for index, (volatility, liquidity) in enumerate(
            (volatility, liquidity)
            for volatility in (1, 2, 3)
            for liquidity in (1, 2, 3)
        )
    ]
    sources = []
    for index in range(2):
        metrics = _ready_metrics()
        metrics["raw_counts"] = {"trade_rows": 100, "unique_trade_ids": 100}
        metrics["coverage"] = {
            "max_verified_capture_span_seconds": 300.0,
            "ordered_l2_two_sided_coverage_pct": 100.0,
            "utc_hour_coverage_complete": False,
            "weekday_coverage_complete": False,
            "volatility_liquidity_regime_coverage_complete": False,
        }
        metrics["utc_4h_bucket_independent_60s_windows"] = [
            1 if bucket % 2 == index else 0 for bucket in range(6)
        ]
        metrics["weekday_independent_60s_windows"] = [
            1 if bucket % 2 == index else 0 for bucket in range(7)
        ]
        metrics["regime_cell_ess"] = [999.0] * 9
        metrics["_internal_regime_observations"] = observations[index::2]
        sources.append({
            "measured": {
                "source_kind": "immutable_same_connection_trades_ordered_l2",
                "coverage_start": f"2026-08-2{7 + index}T00:00:00Z",
                "coverage_end": f"2026-08-2{7 + index}T00:05:00Z",
                "capture_span_seconds": 300.0,
                "contract_metrics": metrics,
            }
        })
    combined = derive_measured_metrics(sources)
    assert combined["coverage"]["utc_hour_coverage_complete"] is True
    assert combined["coverage"]["weekday_coverage_complete"] is True
    assert combined["coverage"]["volatility_liquidity_regime_coverage_complete"] is True
    assert combined["cost"]["stratified_stability_verified"] is True
    assert combined["regime_cell_ess"] == [1.0] * 9


def test_report_sanitizes_internal_window_evidence() -> None:
    metrics = _ready_metrics()
    metrics["_internal_regime_observations"] = [{"secret_internal": 1}]
    source = {
        "resolution_status": "resolved_verified",
        "blockers": [],
        "measured": {"contract_metrics": metrics},
    }
    report = build_report(
        prereg=_prereg(),
        source_head="1" * 40,
        generated_at="2026-08-27T00:00:00Z",
        source_evaluations=[source],
        measured_metrics=metrics,
    )
    assert "_internal_regime_observations" not in json.dumps(report)


def test_report_schema_and_safety_boundary(tmp_path: Path) -> None:
    metrics = _ready_metrics()
    report = build_report(
        prereg=_prereg(),
        source_head="1" * 40,
        generated_at="2026-08-27T00:00:00Z",
        source_evaluations=[],
        measured_metrics=metrics,
    )
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(report, schema)
    assert len(report["readiness_matrix"]) == 15
    assert report["decision"] == "blocked_insufficient_information"
    assert report["prediction_target"] == (
        "future_10_30_60s_cost_adjusted_return_distribution"
    )
    assert report["guardrails"] == {
        "model_or_ga_run": False,
        "network_used": False,
        "mutable_fallback_used": False,
        "promotion_unlock_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "transfer_or_withdraw_used": False,
    }

    lock = build_contract_lock(
        prereg=_prereg(),
        source_head="1" * 40,
        source_evaluations=[],
    )
    output = tmp_path / "immutable-version"
    receipt = write_immutable_artifact_bundle(report=report, lock=lock, output=output)
    assert receipt["report_file_sha256"]
    assert receipt["contract_lock_file_sha256"]
    assert receipt["artifact_manifest_file_sha256"]
    with pytest.raises(ContractError, match="artifact_output_already_exists"):
        write_immutable_artifact_bundle(report=report, lock=lock, output=output)
