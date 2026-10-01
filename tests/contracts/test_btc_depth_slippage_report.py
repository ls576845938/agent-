from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from quant_crypto.research.btc_depth_slippage import (
    DepthFillEvidenceDependencies,
    ImmutableEvidenceError,
    build_btc_depth_slippage_fill_mapping_report,
    build_btc_depth_slippage_report,
)


def test_depth_snapshot_produces_positive_slippage_floor_without_history_verification(tmp_path: Path) -> None:
    _write_depth_fixture(tmp_path, available_time="2026-07-01T00:00:00Z")

    report = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc),
    )

    assert report["status"] == "partial_diagnostic_only"
    assert report["positive_slippage_floor_bps"] >= 1.0
    assert report["depth_snapshot_available"] is True
    assert report["depth_aware"] is False
    assert report["depth_aware_slippage_history_verified"] is False
    assert "btc_depth_aware_slippage_history_insufficient" in report["blockers"]
    assert "btc_depth_strategy_fill_mapping_missing" in report["blockers"]
    assert report["selected_venue_depth_evidence"]["same_venue_as_execution_gate"] is True
    assert report["selected_venue_depth_evidence"]["strategy_fill_mapping_verified"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert (tmp_path / "artifacts/btc_cost_model/latest/btc_depth_slippage_report.json").exists()
    assert (tmp_path / "artifacts/btc_cost_model/latest/btc_depth_slippage_summary_cn.md").exists()


def test_future_depth_rows_are_not_visible_for_slippage_floor(tmp_path: Path) -> None:
    _write_depth_fixture(tmp_path, available_time="2026-07-01T01:00:00Z")

    report = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["positive_slippage_floor_bps"] is None
    assert report["depth_snapshot_available"] is False
    assert "btc_order_book_depth_snapshot_missing" in report["blockers"]
    assert "btc_positive_slippage_floor_missing" in report["blockers"]


def test_depth_rows_require_btcusdt_instrument(tmp_path: Path) -> None:
    _write_non_btc_depth_fixture(tmp_path)

    report = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["depth_snapshot_available"] is False
    assert report["positive_slippage_floor_bps"] is None
    assert report["depth_source_row_counts"] == {}
    assert report["snapshot_coverage"]["snapshot_count"] == 0
    assert report["depth_instrument_filter"]["requires_explicit_instrument_field"] is True
    assert "btc_order_book_depth_snapshot_missing" in report["blockers"]


def test_aligned_depth_rows_use_max_exchange_and_receive_time_for_visibility(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)

    early = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc),
    )
    late = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 15, tzinfo=timezone.utc),
    )

    assert early["depth_snapshot_available"] is False
    assert "btc_order_book_depth_snapshot_missing" in early["blockers"]
    assert late["depth_snapshot_available"] is True
    assert late["positive_slippage_floor_bps"] >= 1.0


def test_one_sided_legacy_snapshot_does_not_invalidate_sufficient_two_sided_history(tmp_path: Path) -> None:
    _write_depth_history_fixture(tmp_path)
    _write_fill_mapping_report(tmp_path)

    report = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc),
    )

    assert report["depth_aware_slippage_history_verified"] is True
    assert report["snapshot_coverage"]["snapshot_count"] == 49
    assert report["snapshot_coverage"]["two_sided_snapshot_count"] == 48
    assert report["snapshot_coverage"]["two_sided_coverage_days"] >= 14.0
    assert report["selected_venue_depth_evidence"]["history_coverage_verified"] is True
    assert report["selected_venue_depth_evidence"]["strategy_fill_mapping_verified"] is True
    assert "btc_depth_aware_slippage_history_insufficient" not in report["blockers"]
    assert "btc_depth_strategy_fill_mapping_missing" not in report["blockers"]


def test_sparse_two_sided_history_does_not_verify_depth_gate(tmp_path: Path) -> None:
    _write_sparse_depth_history_fixture(tmp_path)
    _write_fill_mapping_report(tmp_path)

    report = build_btc_depth_slippage_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc),
    )

    assert report["snapshot_coverage"]["two_sided_snapshot_count"] == 48
    assert report["snapshot_coverage"]["two_sided_coverage_days"] >= 14.0
    assert report["snapshot_coverage"]["max_two_sided_gap_hours"] > 12.0
    assert report["snapshot_coverage"]["two_sided_continuity_satisfied"] is False
    assert report["selected_venue_depth_evidence"]["history_coverage_verified"] is False
    assert report["depth_aware_slippage_history_verified"] is False
    assert "btc_depth_aware_slippage_history_sparse" in report["blockers"]


def test_fill_mapping_maps_gate_eligible_fill_to_visible_okx_depth(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is True
    assert report["fill_mapping_state"] == "verified"
    assert report["summary"]["fill_mapping_state"] == "verified"
    assert report["summary"]["gate_fill_count"] == 1
    assert report["summary"]["mapped_gate_fill_count"] == 1
    assert report["summary"]["diagnostic_fill_count"] == 0
    assert report["mapping_rows"][0]["mapping_status"] == "mapped"
    assert report["mapping_rows"][0]["mapping_gap_seconds"] == 120.0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_fill_mapping_does_not_treat_diagnostic_drill_as_gate_evidence(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_event_ledger.csv",
        diagnostic=True,
        fill_time="2026-07-01T00:12:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is False
    assert report["fill_mapping_state"] == "no_gate_eligible_fill"
    assert report["summary"]["fill_mapping_state"] == "no_gate_eligible_fill"
    assert report["summary"]["diagnostic_fill_only_state"] is True
    assert report["summary"]["gate_mapping_logic_failure_count"] == 0
    assert report["summary"]["gate_fill_count"] == 0
    assert report["summary"]["diagnostic_fill_count"] == 1
    assert report["summary"]["mapped_fill_count"] == 1
    assert "btc_depth_strategy_fill_mapping_state_no_gate_eligible_fill" in report["blockers"]
    assert "btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills" in report["blockers"]


def test_fill_mapping_requires_explicit_gate_eligible_flag_in_current_ledger(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
        gate_eligible=False,
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is False
    assert report["fill_mapping_state"] == "no_gate_eligible_fill"
    assert report["summary"]["fill_mapping_state"] == "no_gate_eligible_fill"
    assert report["summary"]["diagnostic_fill_only_state"] is False
    assert report["summary"]["fill_count"] == 1
    assert report["summary"]["gate_fill_count"] == 0
    assert report["summary"]["mapped_fill_count"] == 1
    assert report["mapping_rows"][0]["paper_runtime_gate_eligible"] is False
    assert "btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills" in report["blockers"]


def test_fill_mapping_does_not_use_future_depth_snapshot(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:05:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is False
    assert report["fill_mapping_state"] == "depth_not_visible"
    assert report["summary"]["fill_mapping_state"] == "depth_not_visible"
    assert report["summary"]["gate_depth_not_visible_count"] == 1
    assert report["summary"]["gate_mapping_logic_failure_count"] == 0
    assert report["summary"]["gate_fill_count"] == 1
    assert report["summary"]["mapped_gate_fill_count"] == 0
    assert report["mapping_rows"][0]["mapping_status"] == "no_visible_depth_at_or_before_fill"
    assert "btc_depth_strategy_fill_mapping_state_depth_not_visible" in report["blockers"]


def test_fill_mapping_requires_depth_available_time_before_fill_time(tmp_path: Path) -> None:
    _write_depth_fixture(tmp_path, available_time="2026-07-01T00:15:00Z")
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is False
    assert report["fill_mapping_state"] == "depth_not_visible"
    assert report["summary"]["fill_mapping_state"] == "depth_not_visible"
    assert report["summary"]["gate_depth_not_visible_count"] == 1
    assert report["summary"]["gate_fill_count"] == 1
    assert report["summary"]["mapped_gate_fill_count"] == 0
    assert report["mapping_rows"][0]["mapping_status"] == "nearest_depth_not_visible_by_fill_time"
    assert report["mapping_rows"][0]["depth_visible_after"] == "2026-07-01T00:15:00+00:00"
    assert "btc_depth_strategy_fill_mapping_state_depth_not_visible" in report["blockers"]


def test_fill_mapping_ignores_non_btcusdt_depth_instrument(tmp_path: Path) -> None:
    _write_non_btc_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is False
    assert report["fill_mapping_state"] == "depth_not_visible"
    assert report["summary"]["fill_mapping_state"] == "depth_not_visible"
    assert report["summary"]["gate_fill_count"] == 1
    assert report["summary"]["depth_snapshot_count_for_mapping"] == 0
    assert report["mapping_rows"][0]["mapping_status"] == "no_visible_depth_at_or_before_fill"
    assert "btc_depth_strategy_fill_mapping_no_two_sided_depth_snapshots" in report["blockers"]
    assert "btc_depth_strategy_fill_mapping_state_depth_not_visible" in report["blockers"]


def test_fill_mapping_distinguishes_visible_depth_mapping_logic_failure(tmp_path: Path) -> None:
    _write_thin_aligned_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["strategy_fill_mapping_verified"] is False
    assert report["fill_mapping_state"] == "mapping_logic_failed"
    assert report["summary"]["fill_mapping_state"] == "mapping_logic_failed"
    assert report["summary"]["gate_depth_visible_count"] == 1
    assert report["summary"]["gate_depth_not_visible_count"] == 0
    assert report["summary"]["gate_mapping_logic_failure_count"] == 1
    assert report["mapping_rows"][0]["mapping_status"] == "partial_fill"
    assert report["mapping_rows"][0]["partial_fill"] is True
    assert report["mapping_rows"][0]["unfilled_notional_usdt"] > 0
    assert "btc_depth_strategy_fill_mapping_state_mapping_logic_failed" in report["blockers"]


def test_fill_mapping_models_costs_filters_and_is_deterministic(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
    )
    kwargs = {
        "repo_root": tmp_path,
        "output_root": tmp_path / "artifacts/btc_cost_model/latest",
        "generated_at_utc": datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
        "data_version": "fixture",
        "run_id": "deterministic-run",
        "source_head": "a" * 40,
    }

    first = build_btc_depth_slippage_fill_mapping_report(**kwargs)
    second = build_btc_depth_slippage_fill_mapping_report(**kwargs)

    row = first["mapping_rows"][0]
    assert first["schema_version"] == "btc_depth_slippage_fill_mapping_report_v2"
    assert first["output_hash"] == second["output_hash"]
    assert len(first["params_hash"]) == 64
    assert all(len(value) == 64 for value in first["input_hashes"].values())
    assert row["venue_filter_status"] == "pass"
    assert row["queue_ahead_fraction"] > 0
    assert row["latency_ms"] > 0
    assert row["spread_cost_bps"] > 0
    assert row["market_impact_bps"] > 0
    assert row["delay_cost_bps"] > 0
    assert first["evidence_class"] == "fixture_or_diagnostic_only"
    assert first["promotion_evidence_ready"] is False


def test_fill_mapping_blocks_stale_snapshot_and_venue_filter_rejection(tmp_path: Path) -> None:
    _write_aligned_depth_fixture(tmp_path)
    ledger = tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv"
    _write_event_ledger(ledger, diagnostic=False, fill_time="2026-07-01T02:00:01Z")

    stale = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 2, 30, tzinfo=timezone.utc),
    )
    assert stale["mapping_rows"][0]["mapping_status"] == "nearest_visible_depth_too_stale"

    _write_event_ledger(ledger, diagnostic=False, fill_time="2026-07-01T00:12:00Z", notional=1.0)
    rejected = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )
    assert rejected["mapping_rows"][0]["mapping_status"] == "venue_filter_min_notional_rejected"
    assert rejected["mapping_rows"][0]["mapped"] is False


def test_fill_mapping_blocks_sequence_gap_out_of_order_one_sided_and_zero_liquidity(tmp_path: Path) -> None:
    _write_integrity_depth_fixture(tmp_path)
    _write_event_ledger(
        tmp_path / "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv",
        diagnostic=False,
        fill_time="2026-07-01T00:12:00Z",
    )

    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "artifacts/btc_cost_model/latest",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    integrity = report["depth_integrity"]
    assert integrity["sequence_gap_count"] > 0
    assert integrity["out_of_order_count"] > 0
    assert integrity["one_sided_snapshot_count"] > 0
    assert integrity["zero_liquidity_level_count"] > 0
    assert integrity["valid_for_mapping"] is False
    assert "btc_depth_strategy_fill_mapping_sequence_gap" in report["engineering_blockers"]
    assert "btc_depth_strategy_fill_mapping_out_of_order" in report["engineering_blockers"]
    assert "btc_depth_strategy_fill_mapping_one_sided_book" in report["engineering_blockers"]
    assert "btc_depth_strategy_fill_mapping_zero_liquidity" in report["engineering_blockers"]


def test_official_mapping_rejects_mutable_or_non_manifest_inputs(tmp_path: Path) -> None:
    dependencies = DepthFillEvidenceDependencies(resolve_source=lambda **_: {})
    for invalid in (
        "HEAD:.agent/data_manifests/latest.json",
        f"{'a' * 40}:artifacts/latest/depth.csv",
        f"{'a' * 40}:.agent/data_manifests/depth/*.json",
        f"{'a' * 40}:.agent/data_manifests/depth/staging.json",
        f"{'a' * 40}:.agent/data_manifests/depth/source.sqlite",
    ):
        with pytest.raises(ImmutableEvidenceError, match="exact_committed_manifest_git_spec_required"):
            build_btc_depth_slippage_fill_mapping_report(
                repo_root=tmp_path,
                output_root=tmp_path / "out",
                immutable_l2_manifest_git_specs=[invalid],
                natural_fill_ledger_manifest_git_spec=f"{'b' * 40}:.agent/data_manifests/fills/fills.json",
                dependencies=dependencies,
            )


def test_official_mapping_rejects_manifest_hash_or_attestation_mismatch(tmp_path: Path) -> None:
    l2_spec, fill_spec, bindings = _write_immutable_mapping_fixture(tmp_path, with_fill=True)
    bindings[l2_spec]["full_file_hash_verified"] = False
    dependencies = DepthFillEvidenceDependencies(resolve_source=lambda **kwargs: bindings[kwargs["manifest_git_spec"]])
    with pytest.raises(ImmutableEvidenceError, match="immutable_manifest_or_file_hash_verification_failed"):
        build_btc_depth_slippage_fill_mapping_report(
            repo_root=tmp_path,
            output_root=tmp_path / "out",
            immutable_l2_manifest_git_specs=[l2_spec],
            natural_fill_ledger_manifest_git_spec=fill_spec,
            dependencies=dependencies,
            source_head="c" * 40,
        )

    l2_spec, fill_spec, bindings = _write_immutable_mapping_fixture(tmp_path / "attestation", with_fill=True)
    bindings[l2_spec]["_manifest"]["producer_role"] = "unknown"
    dependencies = DepthFillEvidenceDependencies(resolve_source=lambda **kwargs: bindings[kwargs["manifest_git_spec"]])
    with pytest.raises(ImmutableEvidenceError, match="data_steward_attestation_required"):
        build_btc_depth_slippage_fill_mapping_report(
            repo_root=tmp_path / "attestation",
            output_root=tmp_path / "attestation/out",
            immutable_l2_manifest_git_specs=[l2_spec],
            natural_fill_ledger_manifest_git_spec=fill_spec,
            dependencies=dependencies,
            source_head="c" * 40,
        )


def test_official_mapping_without_natural_fill_is_explicitly_blocked(tmp_path: Path) -> None:
    l2_spec, fill_spec, bindings = _write_immutable_mapping_fixture(tmp_path, with_fill=False)
    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "out",
        immutable_l2_manifest_git_specs=[l2_spec],
        natural_fill_ledger_manifest_git_spec=fill_spec,
        dependencies=DepthFillEvidenceDependencies(
            resolve_source=lambda **kwargs: bindings[kwargs["manifest_git_spec"]]
        ),
        source_head="c" * 40,
        run_id="immutable-no-fill",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["immutable_inputs_verified"] is True
    assert report["fill_mapping_state"] == "no_gate_eligible_fill"
    assert report["promotion_evidence_ready"] is False
    assert "btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills" in report["blockers"]
    assert all(report["gate"][name] is False for name in report["gate"])


def test_official_mapping_uses_time_overlapping_natural_fill_and_binds_every_hash(tmp_path: Path) -> None:
    l2_spec, fill_spec, bindings = _write_immutable_mapping_fixture(tmp_path, with_fill=True)
    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=tmp_path,
        output_root=tmp_path / "out",
        immutable_l2_manifest_git_specs=[l2_spec],
        natural_fill_ledger_manifest_git_spec=fill_spec,
        dependencies=DepthFillEvidenceDependencies(
            resolve_source=lambda **kwargs: bindings[kwargs["manifest_git_spec"]]
        ),
        source_head="c" * 40,
        run_id="immutable-mapped-fill",
        generated_at_utc=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
    )

    assert report["fill_mapping_state"] == "verified"
    assert report["strategy_fill_mapping_verified"] is True
    assert report["promotion_evidence_ready"] is True
    assert report["mapped_fill_count"] == 1
    assert report["source_head"] == "c" * 40
    assert report["immutable_l2_manifest_git_specs"] == [l2_spec]
    assert report["natural_fill_ledger_manifest_git_spec"] == fill_spec
    assert len(report["natural_fill_ledger_sha256"]) == 64
    assert all(len(row["manifest_blob_sha256"]) == 64 for row in report["immutable_source_bindings"])
    assert report["mapping_rows"][0]["diagnostic_drill_only"] is False
    assert report["mapping_rows"][0]["paper_runtime_gate_eligible"] is True
    assert all(report["gate"][name] is False for name in report["gate"])


def _write_immutable_mapping_fixture(root: Path, *, with_fill: bool) -> tuple[str, str, dict[str, dict[str, object]]]:
    root.mkdir(parents=True, exist_ok=True)
    l2_root = root / "immutable-l2"
    fill_root = root / "immutable-fill"
    l2_path = l2_root / "immutable_export/ordered-l2/venue=okx/instrument_id=BTC-USDT-SWAP/date=2026-07-01/part-00000.jsonl"
    attestation_path = l2_root / "immutable_export/ordered-l2/btc_okx_l2_dataready_attestation.json"
    l2_path.parent.mkdir(parents=True, exist_ok=True)
    l2_path.write_text(
        json.dumps({
            "action": "snapshot",
            "event_time": "2026-07-01T00:10:00Z",
            "available_time": "2026-07-01T00:10:00Z",
            "instrument_id": "BTC-USDT-SWAP",
            "venue": "okx",
            "capture_sequence": 1,
            "seq_id": 100,
            "prev_seq_id": -1,
            "bids": [["99999", "1"]],
            "asks": [["100001", "1"]],
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    attestation_path.write_text(json.dumps({"producer_role": "data_steward", "quality_status": "pass"}) + "\n", encoding="utf-8")
    fill_path = fill_root / "ledger/natural_fill_event_ledger.csv"
    fill_path.parent.mkdir(parents=True, exist_ok=True)
    if with_fill:
        _write_event_ledger(fill_path, diagnostic=False, fill_time="2026-07-01T00:12:00Z")
    else:
        fill_path.write_text(
            "event_id,event_type,event_time,diagnostic_drill_only,paper_runtime_gate_eligible\n",
            encoding="utf-8",
        )
    fill_attestation = fill_root / "ledger/data_steward_attestation.json"
    fill_attestation.write_text(json.dumps({"producer_role": "data_steward", "quality_status": "pass"}) + "\n", encoding="utf-8")

    l2_spec = f"{'a' * 40}:.agent/data_manifests/l2/l2-immutable.json"
    fill_spec = f"{'b' * 40}:.agent/data_manifests/fills/natural-fills.json"

    def member(path: Path, base: Path) -> dict[str, object]:
        payload = path.read_bytes()
        return {
            "path": path.relative_to(base).as_posix(),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def binding(spec: str, base: Path, dataset_id: str, files: list[dict[str, object]]) -> dict[str, object]:
        return {
            "manifest_git_spec": spec,
            "manifest_blob_sha256": hashlib.sha256(spec.encode()).hexdigest(),
            "dataset_id": dataset_id,
            "dataset_version": dataset_id + "-v1",
            "aggregate_sha256": hashlib.sha256((dataset_id + "-aggregate").encode()).hexdigest(),
            "resolution_status": "resolved_verified",
            "full_file_hash_verified": True,
            "fallback_used": False,
            "blockers": [],
            "_resolved_root": base,
            "_manifest": {
                "producer_role": "data_steward",
                "readiness_class": "quality_checked",
                "quality_status": "pass",
                "files": files,
            },
        }

    return l2_spec, fill_spec, {
        l2_spec: binding(l2_spec, l2_root, "btc-okx-10s-microstructure-immutable-feed", [member(l2_path, l2_root), member(attestation_path, l2_root)]),
        fill_spec: binding(fill_spec, fill_root, "btc-demo-natural-fill-ledger", [member(fill_path, fill_root), member(fill_attestation, fill_root)]),
    }


def _write_depth_fixture(root: Path, *, available_time: str) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth.csv",
        "\n".join(
            [
                "timestamp,event_time,available_time,ingested_at,processed_at,ts,symbol,side,level,price,size,liquidation_orders,order_count,source_record_id",
                f"2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,{available_time},{available_time},{available_time},1,BTCUSDT,bid,1,99999.0,1.0,0,1,bid1",
                f"2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,{available_time},{available_time},{available_time},1,BTCUSDT,ask,1,100001.0,1.0,0,1,ask1",
            ]
        ),
    )


def _write_non_btc_depth_fixture(root: Path) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth_aligned.csv",
        "\n".join(
            [
                "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,side,level,price,size,best_bid,best_ask,spread_bps,bid_depth_notional,ask_depth_notional,liquidation_orders,order_count,source_record_id",
                "1,2026-07-01T00:10:00Z,1,2026-07-01T00:00:00Z,1,ETH-USDT-SWAP,ETHUSDT,bid,1,2999.0,1.0,2999.0,3001.0,6.66,2999.0,3001.0,0,1,bid1",
                "1,2026-07-01T00:10:00Z,1,2026-07-01T00:00:00Z,1,ETH-USDT-SWAP,ETHUSDT,ask,1,3001.0,1.0,2999.0,3001.0,6.66,2999.0,3001.0,0,1,ask1",
            ]
        ),
    )


def _write_depth_history_fixture(root: Path) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    start = datetime(2026, 6, 15, tzinfo=timezone.utc)
    lines = [
        "timestamp,event_time,available_time,ingested_at,processed_at,ts,symbol,side,level,price,size,liquidation_orders,order_count,source_record_id",
        "2026-06-14T00:00:00Z,2026-06-14T00:00:00Z,2026-06-14T00:00:00Z,2026-06-14T00:00:00Z,2026-06-14T00:00:00Z,1,BTCUSDT,ask,1,100001.0,1.0,0,1,legacy-one-sided",
    ]
    for index in range(48):
        ts = start + timedelta(hours=8 * index)
        iso = ts.isoformat().replace("+00:00", "Z")
        lines.append(f"{iso},{iso},{iso},{iso},{iso},{index},BTCUSDT,bid,1,99999.0,1.0,0,1,bid-{index}")
        lines.append(f"{iso},{iso},{iso},{iso},{iso},{index},BTCUSDT,ask,1,100001.0,1.0,0,1,ask-{index}")
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth.csv",
        "\n".join(lines),
    )


def _write_sparse_depth_history_fixture(root: Path) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    first_cluster = datetime(2026, 6, 15, tzinfo=timezone.utc)
    second_cluster = datetime(2026, 6, 30, tzinfo=timezone.utc)
    lines = [
        "timestamp,event_time,available_time,ingested_at,processed_at,ts,symbol,side,level,price,size,liquidation_orders,order_count,source_record_id",
    ]
    for index in range(24):
        ts = first_cluster + timedelta(hours=index)
        iso = ts.isoformat().replace("+00:00", "Z")
        lines.append(f"{iso},{iso},{iso},{iso},{iso},{index},BTCUSDT,bid,1,99999.0,1.0,0,1,bid-a-{index}")
        lines.append(f"{iso},{iso},{iso},{iso},{iso},{index},BTCUSDT,ask,1,100001.0,1.0,0,1,ask-a-{index}")
    for index in range(24):
        ts = second_cluster + timedelta(hours=index)
        iso = ts.isoformat().replace("+00:00", "Z")
        lines.append(f"{iso},{iso},{iso},{iso},{iso},{index},BTCUSDT,bid,1,99999.0,1.0,0,1,bid-b-{index}")
        lines.append(f"{iso},{iso},{iso},{iso},{iso},{index},BTCUSDT,ask,1,100001.0,1.0,0,1,ask-b-{index}")
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth.csv",
        "\n".join(lines),
    )


def _write_aligned_depth_fixture(root: Path) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth_aligned.csv",
        "\n".join(
            [
                "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,side,level,price,size,best_bid,best_ask,spread_bps,bid_depth_notional,ask_depth_notional,liquidation_orders,order_count,source_record_id",
                "1,2026-07-01T00:10:00Z,1,2026-07-01T00:00:00Z,1,BTC-USDT-SWAP,BTCUSDT,bid,1,99999.0,1.0,99999.0,100001.0,2.0,99999.0,100001.0,0,1,bid1",
                "1,2026-07-01T00:10:00Z,1,2026-07-01T00:00:00Z,1,BTC-USDT-SWAP,BTCUSDT,ask,1,100001.0,1.0,99999.0,100001.0,2.0,99999.0,100001.0,0,1,ask1",
            ]
        ),
    )


def _write_thin_aligned_depth_fixture(root: Path) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth_aligned.csv",
        "\n".join(
            [
                "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,side,level,price,size,best_bid,best_ask,spread_bps,bid_depth_notional,ask_depth_notional,liquidation_orders,order_count,source_record_id",
                "1,2026-07-01T00:10:00Z,1,2026-07-01T00:00:00Z,1,BTC-USDT-SWAP,BTCUSDT,bid,1,99999.0,0.000001,99999.0,100001.0,2.0,0.099999,0.100001,0,1,bid1",
                "1,2026-07-01T00:10:00Z,1,2026-07-01T00:00:00Z,1,BTC-USDT-SWAP,BTCUSDT,ask,1,100001.0,0.000001,99999.0,100001.0,2.0,0.099999,0.100001,0,1,ask1",
            ]
        ),
    )


def _write_integrity_depth_fixture(root: Path) -> None:
    _write_text(
        root / "configs/data/btc_perpetual_sources.yaml",
        "\n".join(
            [
                "providers:",
                "  okx_swap:",
                "    enabled: true",
                "    root: data/external/btc_perpetual/okx_swap/",
                "    selected_bundle_id: depth_fixture",
                "selected_provider: okx_swap",
            ]
        ),
    )
    header = (
        "capture_sequence,exchange_ts,local_receive_ts,venue_symbol,symbol,side,level,price,size,source_record_id"
    )
    rows = [
        "1,2026-07-01T00:10:00Z,2026-07-01T00:10:00Z,BTC-USDT-SWAP,BTCUSDT,bid,1,99999,1,bid-1",
        "1,2026-07-01T00:10:00Z,2026-07-01T00:10:00Z,BTC-USDT-SWAP,BTCUSDT,ask,1,100001,1,ask-1",
        "3,2026-07-01T00:11:00Z,2026-07-01T00:11:00Z,BTC-USDT-SWAP,BTCUSDT,bid,1,99998,1,bid-3",
        "2,2026-07-01T00:09:00Z,2026-07-01T00:09:00Z,BTC-USDT-SWAP,BTCUSDT,bid,1,99997,1,bid-2",
        "4,2026-07-01T00:12:00Z,2026-07-01T00:12:00Z,BTC-USDT-SWAP,BTCUSDT,bid,1,99996,0,bid-4",
        "4,2026-07-01T00:12:00Z,2026-07-01T00:12:00Z,BTC-USDT-SWAP,BTCUSDT,ask,1,100004,0,ask-4",
    ]
    _write_text(
        root / "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth_aligned.csv",
        "\n".join([header, *rows]),
    )


def _write_fill_mapping_report(root: Path) -> None:
    _write_text(
        root / "artifacts/btc_cost_model/latest/btc_depth_slippage_fill_mapping_report.json",
        '{'
        '"strategy_fill_mapping_verified": true,'
        '"mapped_fill_count": 48,'
        '"same_venue_as_execution_gate": true,'
        '"time_aligned_depth_history_verified": true'
        '}',
    )


def _write_event_ledger(
    path: Path,
    *,
    diagnostic: bool,
    fill_time: str,
    gate_eligible: bool | None = None,
    notional: float = 1000.0,
) -> None:
    if gate_eligible is None:
        gate_eligible = not diagnostic
    _write_text(
        path,
        "\n".join(
            [
                (
                    "event_id,ledger_scope,event_type,event_time,event_state,strategy_line,candidate_id,decision_time,"
                    "side,target_exposure,notional_usdt,quantity_btc,execution_price,mark_price,index_price,"
                    "liquidation_price,liquidation_buffer_bps,risk_action,risk_approved,risk_blockers,amount_usdt,"
                    "diagnostic_drill_only,paper_runtime_gate_eligible,paper_queue_write_allowed,live_unlock_allowed"
                ),
                (
                    "fill-1,current_observe_only_paper_runtime_replay,simulated_fill,"
                    f"{fill_time},filled,long_short_donchian_top5,candidate_a,2026-07-01T00:00:00Z,"
                    f"long,1.0,{notional},0.01,100000.0,100000.0,100020.0,50000.0,5000.0,approve,True,[],{notional},"
                    f"{str(diagnostic)},{str(gate_eligible)},False,False"
                ),
            ]
        ),
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
