"""Fail-closed service for US-equity production PIT bundle intake."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from quant_us.data.lineage.local_csv_provider import (
    REQUIRED_BUNDLE_FILE_FIELDS,
    REQUIRED_BUNDLE_MANIFEST_FIELDS,
    REQUIRED_LOCAL_CSV_FILES,
)


SCHEMA_VERSION = "us_equity_production_pit_intake_report_v1"
REQUIRED_COMPONENTS = tuple(REQUIRED_LOCAL_CSV_FILES)
REQUIRED_METADATA = (
    "provider",
    "license",
    "sample_range",
    "record_counts",
    "file_hashes",
)
COMPONENT_MISSING_BLOCKERS = tuple(
    f"production_pit_bundle_missing:{component}" for component in REQUIRED_COMPONENTS
)
METADATA_MISSING_BLOCKERS = tuple(
    f"production_pit_bundle_metadata_missing:{field}" for field in REQUIRED_METADATA
)


def find_committed_production_pit_events(scan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only committed data-steward events that claim a PIT bundle delivery."""

    matches: list[dict[str, Any]] = []
    for item in _list(scan.get("events")):
        if not isinstance(item, Mapping):
            continue
        event = item.get("event")
        if not isinstance(event, Mapping):
            continue
        haystack = " ".join(
            [
                str(event.get("ticket_id", "")),
                str(event.get("event_id", "")),
                str(event.get("domain", "")),
                str(item.get("path", "")),
                " ".join(str(deliverable) for deliverable in _list(event.get("deliverables"))),
            ]
        ).lower()
        is_pit_bundle = "production" in haystack and "pit" in haystack
        if (
            event.get("producer_role") == "data_steward"
            and event.get("event_type") in {"published", "integrated"}
            and is_pit_bundle
            and str(event.get("deliverable_commit", ""))
            and str(item.get("path", ""))
        ):
            matches.append(
                {
                    "event_id": str(event.get("event_id")),
                    "ticket_id": str(event.get("ticket_id")),
                    "event_type": str(event.get("event_type")),
                    "deliverable_commit": str(event.get("deliverable_commit")),
                    "path": str(item.get("path")),
                    "deliverables": list(_list(event.get("deliverables"))),
                }
            )
    return matches


def build_production_pit_intake_report(
    *,
    scan: Mapping[str, Any],
    validation_status_by_event: Mapping[str, str],
    code_commit: str,
    branch: str,
    outputs: Mapping[str, str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build an intake decision without reading unvalidated bundle data."""

    candidates = find_committed_production_pit_events(scan)
    validations = [
        {
            **candidate,
            "validation_status": validation_status_by_event.get(
                candidate["event_id"], "not_validated"
            ),
        }
        for candidate in candidates
    ]
    valid = [item for item in validations if item["validation_status"] == "valid"]
    if valid:
        # Resolver consumption is deliberately a later, explicit step.  A valid
        # envelope alone cannot make its data promotion-clean.
        blockers = [
            "production_pit_immutable_manifest_not_resolved",
            "production_pit_bundle_acceptance_not_run",
        ]
        component_state = "pending_immutable_manifest_resolution"
        metadata_state = "pending_immutable_manifest_resolution"
        handoff_state = "valid_committed_handoff_discovered"
    else:
        blockers = [
            "production_pit_committed_handoff_missing",
            *COMPONENT_MISSING_BLOCKERS,
            *METADATA_MISSING_BLOCKERS,
            "production_pit_immutable_manifest_missing",
        ]
        component_state = "missing_external_data"
        metadata_state = "missing_external_data"
        handoff_state = "missing"

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "asset": "us_equity",
        "code_commit": code_commit,
        "branch": branch,
        "status": "blocked_external_data",
        "decision": "wait_for_valid_committed_production_pit_bundle_no_goal3_no_promotion_no_paper_no_live",
        "handoff_discovery": {
            "verification_mode": str(scan.get("verification_mode", "unknown")),
            "scanned_event_count": len(_list(scan.get("events"))),
            "invalid_event_count": len(_list(scan.get("invalid"))),
            "production_pit_candidate_count": len(candidates),
            "valid_production_pit_handoff_count": len(valid),
            "state": handoff_state,
            "candidates": validations,
            "branch_presence_is_delivery": False,
            "uncommitted_worktree_files_consumed": False,
        },
        "required_components": [
            {
                "component": component,
                "state": component_state,
                "exact_missing_blocker": f"production_pit_bundle_missing:{component}",
            }
            for component in REQUIRED_COMPONENTS
        ],
        "required_metadata": [
            {
                "field": field,
                "state": metadata_state,
                "exact_missing_blocker": f"production_pit_bundle_metadata_missing:{field}",
            }
            for field in REQUIRED_METADATA
        ],
        "adapter_contract_audit": {
            "required_component_names": list(REQUIRED_COMPONENTS),
            "required_component_count": len(REQUIRED_COMPONENTS),
            "manifest_required_fields": list(REQUIRED_BUNDLE_MANIFEST_FIELDS),
            "per_file_required_fields": list(REQUIRED_BUNDLE_FILE_FIELDS),
            "supports_provider_and_license_metadata": True,
            "supports_sample_range_metadata": True,
            "supports_record_count_validation": True,
            "supports_file_hash_validation": True,
            "fixture_can_prove_plumbing_only": True,
            "fixture_can_unlock_promotion_clean": False,
        },
        "source_classification": {
            "hf_etf26": {
                "readiness_class": "research_ready",
                "promotion_clean": False,
                "promotion_unlock_allowed": False,
            },
            "qqq_tqqq_raw_minute": {
                "readiness_class": "raw_evidence",
                "promotion_clean": False,
                "promotion_unlock_allowed": False,
            },
        },
        "blockers": _dedupe(blockers),
        "guardrails": {
            "research_only": True,
            "fixture_only": False,
            "immutable_manifest_consumed": False,
            "source_vendor_data_modified": False,
            "configuration_mutated_by_this_report": False,
            "promotion_clean": False,
            "promotion_unlock_allowed": False,
            "paper_queue_write_allowed": False,
            "paper_order_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_used": False,
            "broker_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
            "network_used": False,
            "secret_read": False,
        },
        "outputs": dict(outputs),
    }
    return report


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
