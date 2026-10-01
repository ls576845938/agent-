from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_perpetual_route_request import build_btc_perpetual_route_request


def test_perpetual_route_request_declares_research_need_without_paper_or_live(tmp_path: Path) -> None:
    long_short = tmp_path / "long_short.json"
    attack = tmp_path / "attack.json"
    high_yield = tmp_path / "high_yield.json"
    _write_json(long_short, _source_report("complete_research_only"))
    _write_json(attack, _source_report("complete_research_only"))
    _write_json(high_yield, _source_report("complete_research_only"))

    report = build_btc_perpetual_route_request(
        output_dir=tmp_path / "artifacts/btc_perpetual_route_request/latest",
        long_short_observer_report_path=long_short,
        attack_observer_report_path=attack,
        high_yield_followup_report_path=high_yield,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    safety = json.loads(
        (tmp_path / "artifacts/btc_perpetual_route_request/latest/paper_live_safety_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "complete_research_only"
    assert report["perpetual_route_requested"] is True
    assert report["eligible_strategy_line_count"] == 3
    assert all(line["requires_perpetual_execution_evidence"] is True for line in report["strategy_lines"])
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["broker_access_allowed"] is False
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False


def test_perpetual_route_request_blocks_unsafe_source_flag(tmp_path: Path) -> None:
    long_short = tmp_path / "long_short.json"
    _write_json(long_short, {**_source_report("complete_research_only"), "gate": {"paper_queue_write_allowed": True}})

    report = build_btc_perpetual_route_request(
        output_dir=tmp_path / "artifacts/btc_perpetual_route_request/latest",
        long_short_observer_report_path=long_short,
        attack_observer_report_path=tmp_path / "missing_attack.json",
        high_yield_followup_report_path=tmp_path / "missing_high_yield.json",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert report["perpetual_route_requested"] is False
    assert any("unsafe_source_flag" in blocker for blocker in report["blockers"])
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _source_report(status: str) -> dict[str, object]:
    return {
        "status": status,
        "decision": "observe_only_no_paper_no_live",
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "guardrails": {
            "broker_access_allowed": False,
            "oms_access_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
