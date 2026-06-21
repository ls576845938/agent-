from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_ws_l2_capture_coverage_report import (
    build_btc_true_scalping_ws_l2_capture_coverage_report,
)


SCHEMA = Path("schemas/btc_true_scalping_ws_l2_capture_coverage_report.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json")


def test_btc_true_scalping_ws_l2_capture_coverage_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_ws_l2_capture_coverage_tracks_progress_and_locks_scalping() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    thresholds = payload["thresholds"]
    totals = payload["coverage_totals"]
    validation = payload["validation"]
    minimum_research_seconds = float(thresholds["minimum_research_capture_seconds"])

    assert payload["status"] in {
        "ws_l2_capture_coverage_accumulating_research_only_history_insufficient",
        "ws_l2_capture_coverage_thresholds_met_research_only_execution_queue_locked",
    }
    assert payload["decision"] == "continue_accumulating_public_ws_l2_history_before_true_scalping"
    assert totals["verified_public_session_count"] >= 2
    assert totals["total_capture_duration_seconds"] > 0
    research_seconds_satisfied = totals["total_capture_duration_seconds"] >= minimum_research_seconds
    assert validation["minimum_research_capture_seconds_satisfied"] is research_seconds_satisfied
    if research_seconds_satisfied:
        assert totals["remaining_research_capture_seconds"] == pytest.approx(0.0)
        assert not any(item.startswith("btc_ws_l2_capture_coverage_research_seconds_short_") for item in payload["blockers"])
    else:
        assert totals["remaining_research_capture_seconds"] > 0
        assert any(item.startswith("btc_ws_l2_capture_coverage_research_seconds_short_") for item in payload["blockers"])
    assert validation["required_channels_observed"] is True
    assert validation["resync_policy_exercised"] is True
    if not validation["minimum_event_ledger_history_days_satisfied"]:
        assert totals["remaining_event_ledger_history_days"] > 0
    if not validation["minimum_calendar_span_days_satisfied"]:
        assert totals["remaining_calendar_span_days"] > 0
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    if validation["coverage_contract_satisfied"]:
        assert payload["status"] == "ws_l2_capture_coverage_thresholds_met_research_only_execution_queue_locked"
    else:
        assert payload["status"] == "ws_l2_capture_coverage_accumulating_research_only_history_insufficient"
    assert payload["coverage_contract_satisfied"] is validation["coverage_contract_satisfied"]
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert "btc_execution_latency_model_missing_public_ws_coverage_is_not_order_latency" in payload["blockers"]
    assert "btc_queue_model_missing_public_l2_coverage_is_not_exchange_queue_position" in payload["blockers"]


def test_ws_l2_capture_coverage_builder_can_mark_coverage_thresholds_without_unlock(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "s1",
        duration_seconds=15 * 86_400.0,
        start="2026-01-01T00:00:00Z",
        end="2026-01-16T00:00:00Z",
        exercised=True,
    )
    _write_session(
        tmp_path,
        "s2",
        duration_seconds=15 * 86_400.0,
        start="2026-02-01T00:00:00Z",
        end="2026-02-16T00:00:00Z",
        exercised=False,
    )

    payload = build_btc_true_scalping_ws_l2_capture_coverage_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    totals = payload["coverage_totals"]
    validation = payload["validation"]
    assert payload["status"] == "ws_l2_capture_coverage_thresholds_met_research_only_execution_queue_locked"
    assert totals["verified_public_session_count"] == 2
    assert totals["total_capture_duration_seconds"] == pytest.approx(30 * 86_400.0)
    assert totals["total_event_ledger_history_days"] == pytest.approx(30.0)
    assert totals["calendar_span_days"] >= 30.0
    assert validation["coverage_contract_satisfied"] is True
    assert payload["coverage_contract_satisfied"] is True
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["contract_satisfied"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_l2_capture_coverage_builder_blocks_missing_sessions(tmp_path: Path) -> None:
    payload = build_btc_true_scalping_ws_l2_capture_coverage_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "ws_l2_capture_coverage_missing_or_invalid_research_only"
    assert payload["sessions"] == []
    assert payload["coverage_contract_satisfied"] is False
    assert "btc_ws_l2_capture_coverage_reports_missing" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_l2_capture_coverage_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["broker_calls_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_session(
    root: Path,
    session_id: str,
    *,
    duration_seconds: float,
    start: str,
    end: str,
    exercised: bool,
) -> None:
    session = root / "artifacts/btc_scalping_readiness" / session_id
    _write_json(
        session / "btc_okx_public_ws_l2_raw_capture_report.json",
        {
            "status": "verified_preflight",
            "selected_bundle_dir": f"data/external/btc_perpetual/okx_swap/bundles/{session_id}",
            "public_ws_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
            "message_count": 100,
            "data_message_count": 90,
            "channel_counts": {"trades": 10, "books": 80},
            "connection_count": 2,
            "forced_reconnect_count": 1 if exercised else 0,
            "manifest": {
                "capture_start": start,
                "capture_end": end,
                "capture_duration_seconds": duration_seconds,
                "public_ws_only": True,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "broker_calls_used": False,
                "message_count": 100,
                "data_message_count": 90,
                "channel_counts": {"trades": 10, "books": 80},
                "connection_count": 2,
                "forced_reconnect_count": 1 if exercised else 0,
            },
        },
    )
    _write_json(
        session / "btc_true_scalping_ws_order_book_replay_report.json",
        {
            "replay_sequence_ready": True,
        },
    )
    _write_json(
        session / "btc_true_scalping_ws_reconnect_resync_policy_report.json",
        {
            "resync_policy_ready": True,
            "validation": {"actual_reconnect_or_gap_exercised": exercised},
        },
    )
    _write_json(
        session / "btc_true_scalping_ws_latency_queue_diagnostics_report.json",
        {
            "proxy_diagnostics_ready": True,
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
