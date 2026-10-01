from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_perpetual_gate_objective_status import build_btc_perpetual_gate_objective_status


FIXTURE_CODE_COMMIT = "fixture"


def test_btc_perpetual_gate_objective_status_tracks_depth_as_only_remaining_goal_gap(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=False)

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    assert report["status"] == "incomplete_research_only"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["evidence_json_parseable"]["status"] == "pass"
    assert "dashboard_report" not in report["inputs"]
    assert "dashboard_report" not in report["parse_errors"]
    assert "dashboard_references_parseable_evidence" not in by_id
    assert "dashboard_perpetual_evidence_matches_current_artifact" not in by_id
    assert by_id["current_mark_price_available"]["status"] == "pass"
    assert by_id["mark_used_for_liquidation_risk"]["status"] == "pass"
    assert by_id["liquidation_buffer_visible_in_replay"]["status"] == "pass"
    assert by_id["okx_same_venue_depth_source"]["status"] == "pass"
    assert by_id["btc_depth_instrument_filter_verified"]["status"] == "pass"
    assert by_id["binance_cross_venue_not_substituted"]["status"] == "pass"
    assert by_id["depth_artifacts_match_current_code"]["status"] == "pass"
    assert by_id["depth_fill_mapping_sources_consistent"]["status"] == "pass"
    assert by_id["depth_history_coverage_window_satisfied"]["status"] == "fail"
    assert by_id["fill_mapping_not_older_than_runtime_replay"]["status"] == "pass"
    assert by_id["strategy_fill_mapping_verified"]["status"] == "fail"
    assert by_id["depth_aware_slippage_history_verified"]["status"] == "fail"
    assert report["summary"]["remaining_two_sided_coverage_days"] == 13.1
    assert (tmp_path / "out" / "btc_perpetual_gate_objective_status_report.json").exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["broker_access_allowed"] is False


def test_btc_perpetual_gate_objective_status_can_complete_without_paper_or_live_unlock(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    assert report["status"] == "complete_research_only"
    assert report["blockers"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert all(row["status"] == "pass" for row in report["checks"])


def test_btc_perpetual_gate_objective_status_catches_stale_fill_mapping(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)
    _write_json(
        paths["fill_mapping_report_path"],
        {
            "generated_at_utc": "2026-07-02T00:00:00+00:00",
            "input_event_ledgers": {
                "current": "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv"
            },
            "summary": {
                "strategy_fill_mapping_verified": True,
                "gate_fill_count": 2,
                "mapped_gate_fill_count": 2,
            },
        },
    )
    _write_json(paths["replay_report_path"], {"generated_at_utc": "2026-07-02T01:00:00+00:00", "summary": {}})

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["fill_mapping_not_older_than_runtime_replay"]["status"] == "fail"
    assert "btc_perpetual_gate_objective:fill_mapping_not_older_than_runtime_replay" in report["blockers"]


def test_btc_perpetual_gate_objective_status_requires_mark_reference_for_liquidation_buffer(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)
    _write_json(
        paths["drill_report_path"],
        {
            "summary": {
                "liquidation_buffer_visible_in_replay": True,
                "liquidation_buffer_evidence": {
                    "visible_in_replay": True,
                    "uses_mark_price_reference": False,
                    "simulated_fill_count": 2,
                    "buffer_row_count": 2,
                    "mark_price_row_count": 0,
                },
                "paper_runtime_gate_evidence": False,
            }
        },
    )

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["liquidation_buffer_visible_in_replay"]["status"] == "fail"
    assert "btc_perpetual_gate_objective:liquidation_buffer_visible_in_replay" in report["blockers"]


def test_btc_perpetual_gate_objective_status_requires_current_depth_report_continuity(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)
    _write_json(
        paths["depth_report_path"],
        {
            "snapshot_coverage": {
                "two_sided_snapshot_count": 200,
                "two_sided_coverage_days": 14.2,
                "max_two_sided_gap_hours": 48.0,
                "max_allowed_two_sided_gap_hours": 12.0,
                "two_sided_continuity_satisfied": False,
            }
        },
    )

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["depth_history_coverage_window_satisfied"]["status"] == "fail"
    assert "btc_perpetual_gate_objective:depth_history_coverage_window_satisfied" in report["blockers"]


def test_btc_perpetual_gate_objective_status_rejects_stale_depth_artifacts(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)
    depth_payload = json.loads(paths["depth_report_path"].read_text(encoding="utf-8"))
    depth_payload["code_commit"] = "oldcommit"
    _write_json(paths["depth_report_path"], depth_payload)

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["depth_artifacts_match_current_code"]["status"] == "fail"
    assert "btc_perpetual_gate_objective:depth_artifacts_match_current_code" in report["blockers"]
    assert report["status"] == "incomplete_research_only"


def test_btc_perpetual_gate_objective_status_requires_btc_depth_instrument_filter(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)
    depth_payload = json.loads(paths["depth_report_path"].read_text(encoding="utf-8"))
    depth_payload["depth_instrument_filter"] = {
        "accepted_normalized_instruments": ["BTCUSDT"],
        "requires_explicit_instrument_field": False,
    }
    _write_json(paths["depth_report_path"], depth_payload)

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["btc_depth_instrument_filter_verified"]["status"] == "fail"
    assert "btc_perpetual_gate_objective:btc_depth_instrument_filter_verified" in report["blockers"]
    assert report["status"] == "incomplete_research_only"


def test_btc_perpetual_gate_objective_status_rejects_mismatched_depth_fill_sources(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, depth_ready=True)
    fill_payload = json.loads(paths["fill_mapping_report_path"].read_text(encoding="utf-8"))
    fill_payload["selected_bundle_dir"] = "data/external/btc_perpetual/okx_swap/bundles/other_bundle"
    fill_payload["depth_source_paths"] = [
        "data/external/btc_perpetual/okx_swap/bundles/other_bundle/order_book_depth.csv",
        "data/external/btc_perpetual/okx_swap/bundles/other_bundle/order_book_depth_aligned.csv",
    ]
    _write_json(paths["fill_mapping_report_path"], fill_payload)

    report = build_btc_perpetual_gate_objective_status(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
        current_code_commit=FIXTURE_CODE_COMMIT,
        **paths,
    )

    by_id = {row["check_id"]: row for row in report["checks"]}
    assert by_id["depth_fill_mapping_sources_consistent"]["status"] == "fail"
    assert "btc_perpetual_gate_objective:depth_fill_mapping_sources_consistent" in report["blockers"]
    assert report["status"] == "incomplete_research_only"


def _write_fixture(tmp_path: Path, *, depth_ready: bool) -> dict:
    paths = {
        "evidence_report_path": tmp_path / "evidence.json",
        "cost_model_report_path": tmp_path / "cost.json",
        "depth_report_path": tmp_path / "depth.json",
        "fill_mapping_report_path": tmp_path / "fill_mapping.json",
        "l2_batch_report_path": tmp_path / "l2_batch.json",
        "replay_report_path": tmp_path / "replay.json",
        "drill_report_path": tmp_path / "drill.json",
    }
    evidence_status = "pass" if depth_ready else "fail"
    evidence_payload = {
        "status": "complete_research_only" if depth_ready else "incomplete_research_only",
        "blockers": [] if depth_ready else ["btc_perp_exec_depth_aware_slippage_history_verified"],
        "evidence_checklist": [
            {"check_id": "current_mark_price_available", "status": "pass"},
            {"check_id": "mark_used_for_liquidation_risk", "status": "pass"},
            {"check_id": "depth_aware_slippage_history_verified", "status": evidence_status},
        ],
        "l2_depth_diagnostics": {
            "free_public_cross_venue_depth_gate_eligible_for_selected_venue": False,
            "free_public_cross_venue_depth_verified_for_selected_venue": False,
        },
    }
    _write_json(
        paths["evidence_report_path"],
        evidence_payload,
    )
    _write_json(
        paths["cost_model_report_path"],
        {
            "mark_price_model": {
                "mark_price_current_available": True,
                "mark_price_used_for_liquidation_risk": True,
                "current_mark_price_age_hours": 0.25,
            }
        },
    )
    _write_json(
        paths["depth_report_path"],
        {
            "code_commit": FIXTURE_CODE_COMMIT,
            "symbol": "BTCUSDT",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/depth_fixture",
            "depth_source_paths": [
                "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth.csv",
                "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth_aligned.csv",
            ],
            "depth_instrument_filter": {
                "accepted_normalized_instruments": ["BTCUSDT", "BTCUSDTSWAP"],
                "requires_explicit_instrument_field": True,
            },
            "snapshot_coverage": {
                "two_sided_snapshot_count": 200 if depth_ready else 20,
                "two_sided_coverage_days": 14.0 if depth_ready else 0.9,
                "max_two_sided_gap_hours": 8.0 if depth_ready else 2.0,
                "max_allowed_two_sided_gap_hours": 12.0,
                "two_sided_continuity_satisfied": depth_ready,
            }
        },
    )
    _write_json(
        paths["fill_mapping_report_path"],
        {
            "code_commit": FIXTURE_CODE_COMMIT,
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/depth_fixture",
            "depth_source_paths": [
                "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth.csv",
                "data/external/btc_perpetual/okx_swap/bundles/depth_fixture/order_book_depth_aligned.csv",
            ],
            "generated_at_utc": "2026-07-02T01:00:00+00:00",
            "input_event_ledgers": {
                "current": "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv"
            },
            "summary": {
                "strategy_fill_mapping_verified": depth_ready,
                "gate_fill_count": 2 if depth_ready else 0,
                "mapped_gate_fill_count": 2 if depth_ready else 0,
            }
        },
    )
    _write_json(
        paths["l2_batch_report_path"],
        {
            "depth_gate_progress_after": {
                "selected_venue": "okx_swap",
                "same_venue_as_execution_gate": True,
                "history_coverage_days_requirement_satisfied": depth_ready,
                "required_two_sided_coverage_days": 14.0,
                "two_sided_coverage_days": 14.0 if depth_ready else 0.9,
                "remaining_two_sided_coverage_days": 0.0 if depth_ready else 13.1,
                "two_sided_snapshot_count": 200,
                "required_two_sided_snapshot_count": 48,
                "history_continuity_requirement_satisfied": depth_ready,
                "max_allowed_two_sided_gap_hours": 12.0,
                "max_two_sided_gap_hours": 8.0 if depth_ready else 2.0,
                "depth_aware_slippage_history_verified": depth_ready,
            }
        },
    )
    _write_json(
        paths["replay_report_path"],
        {
            "generated_at_utc": "2026-07-02T00:00:00+00:00",
            "summary": {
                "liquidation_buffer_visible_in_replay": False,
                "liquidation_buffer_evidence": {
                    "visible_in_replay": False,
                    "uses_mark_price_reference": False,
                    "simulated_fill_count": 0,
                },
            },
        },
    )
    _write_json(
        paths["drill_report_path"],
        {
            "summary": {
                "liquidation_buffer_visible_in_replay": True,
                "liquidation_buffer_evidence": {
                    "visible_in_replay": True,
                    "uses_mark_price_reference": True,
                    "simulated_fill_count": 2,
                    "buffer_row_count": 2,
                    "mark_price_row_count": 2,
                },
                "paper_runtime_gate_evidence": False,
            }
        },
    )
    return paths


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
