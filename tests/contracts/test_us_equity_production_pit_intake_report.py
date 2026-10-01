from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from quant_us.data.production_pit_intake import (
    COMPONENT_MISSING_BLOCKERS,
    REQUIRED_COMPONENTS,
    build_production_pit_intake_report,
    find_committed_production_pit_events,
)


SCHEMA = Path("schemas/us_equity_production_pit_intake_report.schema.json")


def test_missing_committed_handoff_blocks_all_six_components() -> None:
    scan = {
        "events": [],
        "invalid": [],
        "refs": ["agent/data_steward/us-production-pit-bundle"],
        "verification_mode": "full_git",
    }

    report = _build(scan)

    _validate(report)
    assert report["status"] == "blocked_external_data"
    assert report["handoff_discovery"]["production_pit_candidate_count"] == 0
    assert report["handoff_discovery"]["branch_presence_is_delivery"] is False
    assert set(COMPONENT_MISSING_BLOCKERS) <= set(report["blockers"])
    assert [item["component"] for item in report["required_components"]] == list(
        REQUIRED_COMPONENTS
    )
    assert report["guardrails"]["promotion_clean"] is False
    assert report["source_classification"]["hf_etf26"]["readiness_class"] == "research_ready"
    assert report["source_classification"]["qqq_tqqq_raw_minute"]["readiness_class"] == "raw_evidence"


def test_fixture_or_non_data_steward_event_never_counts_as_production_handoff() -> None:
    scan = {
        "events": [
            {
                "path": ".agent/handoffs/us-production-pit/fixture.json",
                "event": {
                    "event_id": "fixture-production-pit",
                    "ticket_id": "us-production-pit-fixture",
                    "event_type": "published",
                    "producer_role": "super_developer",
                    "deliverable_commit": "a" * 40,
                    "domain": "data",
                    "deliverables": [{"readiness_class": "quality_checked"}],
                },
            }
        ],
        "invalid": [],
        "verification_mode": "full_git",
    }

    assert find_committed_production_pit_events(scan) == []
    report = _build(scan)
    assert report["status"] == "blocked_external_data"
    assert report["adapter_contract_audit"]["fixture_can_unlock_promotion_clean"] is False


def test_unvalidated_data_steward_candidate_remains_blocked() -> None:
    scan = _production_handoff_scan()

    report = _build(scan, {"published-us-production-pit-bundle": "invalid"})

    assert report["handoff_discovery"]["production_pit_candidate_count"] == 1
    assert report["handoff_discovery"]["valid_production_pit_handoff_count"] == 0
    assert "production_pit_committed_handoff_missing" in report["blockers"]
    assert report["guardrails"]["immutable_manifest_consumed"] is False


def test_valid_handoff_still_requires_immutable_manifest_resolution() -> None:
    scan = _production_handoff_scan()

    report = _build(scan, {"published-us-production-pit-bundle": "valid"})

    _validate(report)
    assert report["status"] == "blocked_external_data"
    assert report["handoff_discovery"]["valid_production_pit_handoff_count"] == 1
    assert report["blockers"] == [
        "production_pit_immutable_manifest_not_resolved",
        "production_pit_bundle_acceptance_not_run",
    ]
    assert report["guardrails"]["immutable_manifest_consumed"] is False


def test_provider_config_names_all_six_required_files() -> None:
    config = yaml.safe_load(
        Path("configs/data/us_equity_provider_sources.yaml").read_text(encoding="utf-8")
    )

    assert set(REQUIRED_LOCAL_CSV_FILES) <= set(
        config["providers"]["local_csv"]["files"]
    )


def test_schema_rejects_any_unlock_flag() -> None:
    report = _build({"events": [], "invalid": [], "verification_mode": "full_git"})
    report["guardrails"]["promotion_unlock_allowed"] = True

    try:
        _validate(report)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_unlock_allowed=true")


def _build(
    scan: dict[str, object], validations: dict[str, str] | None = None
) -> dict[str, object]:
    return build_production_pit_intake_report(
        scan=scan,
        validation_status_by_event=validations or {},
        code_commit="a" * 40,
        branch="agent/super_developer/us-development-v2",
        outputs={"json": "out/report.json", "markdown": "out/report.md"},
        generated_at="2026-07-13T00:00:00Z",
    )


def _validate(report: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report, schema)


def _production_handoff_scan() -> dict[str, object]:
    return {
        "events": [
            {
                "path": ".agent/handoffs/us-production-pit-bundle/published.json",
                "event": {
                    "event_id": "published-us-production-pit-bundle",
                    "ticket_id": "us-production-pit-bundle",
                    "event_type": "published",
                    "producer_role": "data_steward",
                    "deliverable_commit": "b" * 40,
                    "domain": "data",
                    "deliverables": [{"type": "data_manifest"}],
                },
            }
        ],
        "invalid": [],
        "verification_mode": "full_git",
    }
