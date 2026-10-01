from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_manual_stop_reset_drill_report import (
    build_us_equity_manual_stop_reset_drill_report,
)


SCHEMA = Path("schemas/us_equity_manual_stop_reset_drill_report.schema.json")


def test_manual_stop_reset_drill_proves_stop_block_reset_and_incident_review(tmp_path: Path) -> None:
    payload = build_us_equity_manual_stop_reset_drill_report(
        repo_root=tmp_path,
        output=Path("out/manual_stop.json"),
        markdown_output=Path("out/manual_stop.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_stop_reset_proven"
    assert payload["event_count"] == 4
    assert payload["checklist_count"] == 6
    assert payload["incident_review_field_count"] == 8
    assert payload["blockers"] == []
    event_types = {event["event_type"] for event in payload["events"]}
    assert {
        "manual_stop_requested",
        "downstream_orders_blocked",
        "manual_reset_reviewed",
        "manual_reset_recorded",
    } <= event_types
    assert all(item["passed"] is True for item in payload["reset_checklist"])
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["broker_calls_used"] is False
    assert (tmp_path / "out/manual_stop.json").exists()
    assert (tmp_path / "out/manual_stop.md").exists()


def test_manual_stop_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    payload = build_us_equity_manual_stop_reset_drill_report(
        repo_root=tmp_path,
        output=Path("out/manual_stop.json"),
        markdown_output=Path("out/manual_stop.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
