from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_exchange_paper_runtime_replay import build_btc_exchange_paper_runtime_replay_report


def test_paper_runtime_replay_marks_legacy_spot_replay_not_applicable_to_perp(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path, route_requires_perp=True, replay_perp=False)

    report = build_btc_exchange_paper_runtime_replay_report(
        output_dir=tmp_path / "out",
        route_request_path=paths["route"],
        paper_start_path=paths["start"],
        paper_runtime_path=paths["runtime"],
        paper_evaluation_path=paths["evaluation"],
        paper_replay_path=paths["replay"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    safety = json.loads((tmp_path / "out/btc_exchange_paper_runtime_replay_safety_status.json").read_text(encoding="utf-8"))
    assert report["status"] == "incomplete_research_only"
    assert report["legacy_paper_runtime"]["ready"] is True
    assert report["current_route_applicability"]["current_route_requires_perpetual"] is True
    assert report["current_route_applicability"]["current_perpetual_paper_runtime_replay_ready"] is False
    assert "btc_current_perpetual_paper_runtime_replay_missing" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False


def test_paper_runtime_replay_can_be_ready_for_matching_perp_route_without_unlocking(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path, route_requires_perp=True, replay_perp=True)

    report = build_btc_exchange_paper_runtime_replay_report(
        output_dir=tmp_path / "out",
        route_request_path=paths["route"],
        paper_start_path=paths["start"],
        paper_runtime_path=paths["runtime"],
        paper_evaluation_path=paths["evaluation"],
        paper_replay_path=paths["replay"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "paper_runtime_replay_ready_for_manual_review"
    assert report["blockers"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _write_sources(tmp_path: Path, *, route_requires_perp: bool, replay_perp: bool) -> dict[str, Path]:
    paths = {
        "route": tmp_path / "route.json",
        "start": tmp_path / "start.json",
        "runtime": tmp_path / "runtime.json",
        "evaluation": tmp_path / "evaluation.json",
        "replay": tmp_path / "replay.json",
    }
    _write_json(
        paths["route"],
        {
            "status": "complete_research_only",
            "perpetual_route_requested": route_requires_perp,
            "eligible_strategy_line_count": 3,
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
        },
    )
    _write_json(
        paths["start"],
        {
            "status": "complete",
            "decision": "paper_validation_start_ready",
            "strategy_id": "legacy_or_perp_strategy",
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )
    _write_json(
        paths["runtime"],
        {
            "status": "complete",
            "decision": "paper_validation_runtime_complete",
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
        },
    )
    _write_json(
        paths["evaluation"],
        {
            "status": "complete",
            "decision": "paper_validation_evaluation_complete",
            "days_completed": 30,
            "total_orders": 4,
            "total_fills": 4,
            "total_rejected": 0,
            "blockers": [],
        },
    )
    _write_json(
        paths["replay"],
        {
            "status": "replay_pass",
            "decision": "replay_pass",
            "blockers": [],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
            "perpetual_risk_policy": {
                "perpetual_allowed": replay_perp,
                "liquidation_risk_required": replay_perp,
                "status": "perpetual_risk_required" if replay_perp else "not_applicable_spot_or_unlevered_path",
            },
            "replayed_outputs": {"signal": {"strategy_id": "legacy_or_perp_strategy"}},
        },
    )
    return paths


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
