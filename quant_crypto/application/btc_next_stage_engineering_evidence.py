"""Pure, fail-closed BTC next-stage engineering evidence assembly.

This module validates receipts supplied by callers.  It never resolves mutable
``latest`` pointers, reads another worktree, or writes promotion artifacts.
Producer commits for immutable market data are deliberately distinct from the
consumer code HEAD used by strategy/OMS/ledger/replay evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    stable_payload_hash,
)
from quant_shared.core.time import ensure_utc


SCHEMA_VERSION = "btc_next_stage_engineering_evidence_v2"
DATA_HANDOFF_TICKET = "DATA-BTC-V3-IMMUTABLE-PUBLIC-MARKET-EVIDENCE-01"
DATA_INTEGRATED_EVENT_ID = (
    "integrated-data-btc-v3-immutable-public-market-evidence-01"
)
DATA_PUBLISHED_EVENT_ID = (
    "published-data-btc-v3-immutable-public-market-evidence-01-14080d3d"
)
CURRENT_HEAD_LAYERS = ("strategy", "oms", "ledger", "replay")
BUILDER_CHAIN = ("domain_read_model", "promotion_evidence", "gate_decision")
PERMANENT_PROMOTION_BLOCKERS = (
    "btc_next_stage:real_non_flat_fill_evidence_missing",
    "btc_okx_native:25_hour_demo_observation_window_incomplete",
    "btc_next_stage:manual_promotion_approval_missing",
)


def resolve_selected_public_ws_dependency(
    *,
    selected_bundle_sha256: str,
    package_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve one immutable public-WS package for an already selected bundle."""

    blockers: list[str] = []
    if not _is_sha256(selected_bundle_sha256):
        blockers.append("btc_next_stage:public_ws_selected_bundle_sha256_invalid")
    candidates = [
        dict(row)
        for row in package_receipts
        if str(row.get("selected_bundle_sha256") or "") == selected_bundle_sha256
    ]
    if len(candidates) != 1:
        blockers.append(
            "btc_next_stage:public_ws_package_not_unique_for_selected_bundle"
        )
        selected: dict[str, Any] = {}
    else:
        selected = candidates[0]
    package_sha256 = str(selected.get("package_sha256") or "")
    if not _is_sha256(package_sha256):
        blockers.append("btc_next_stage:public_ws_package_sha256_invalid")
    if selected.get("public_only") is not True:
        blockers.append("btc_next_stage:public_ws_dependency_not_public_only")
    if selected.get("import_safe") is not True:
        blockers.append("btc_next_stage:public_ws_dependency_not_import_safe")
    if str(selected.get("distribution_name") or "").lower() != "websocket-client":
        blockers.append("btc_next_stage:public_ws_distribution_identity_invalid")
    if not str(selected.get("distribution_version") or "").strip():
        blockers.append("btc_next_stage:public_ws_distribution_version_missing")
    if not str(selected.get("module_path") or "").strip():
        blockers.append("btc_next_stage:public_ws_module_path_missing")
    if not _is_sha256(str(selected.get("module_sha256") or "")):
        blockers.append("btc_next_stage:public_ws_module_sha256_invalid")
    if selected.get("allowlist_valid") is not True:
        blockers.append("btc_next_stage:public_ws_dependency_not_allowlisted")
    return {
        "resolver_contract_version": "btc_public_ws_dependency_v1",
        "selected_bundle_sha256": selected_bundle_sha256,
        "package_sha256": package_sha256,
        "public_only": selected.get("public_only") is True,
        "import_safe": selected.get("import_safe") is True,
        "package_name": str(
            selected.get("package_name")
            or selected.get("distribution_name")
            or ""
        ),
        "distribution_name": str(selected.get("distribution_name") or ""),
        "distribution_version": str(
            selected.get("distribution_version") or ""
        ),
        "distribution_root": str(selected.get("distribution_root") or ""),
        "module_name": str(selected.get("module_name") or ""),
        "module_version": str(selected.get("module_version") or ""),
        "module_path": str(selected.get("module_path") or ""),
        "module_sha256": str(selected.get("module_sha256") or ""),
        "allowlist_roots": [
            str(item) for item in selected.get("allowlist_roots", [])
        ],
        "allowlist_valid": selected.get("allowlist_valid") is True,
        "user_site_consumed": selected.get("user_site_consumed") is True,
        "valid": not blockers,
        "blockers": _dedupe(blockers),
    }


def build_btc_next_stage_engineering_evidence(
    *,
    current_head: str,
    generated_at_utc: datetime,
    source_evidence: Mapping[str, Mapping[str, Any]],
    public_market_handoff: Mapping[str, Any] | None = None,
    public_ws_dependency: Mapping[str, Any] | None = None,
    l2_evidence: Mapping[str, Any] | None = None,
    builder_chain: Sequence[Mapping[str, Any]] = (),
    funding_evidence: Mapping[str, Any] | None = None,
    private_ws_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an in-memory engineering receipt without unlocking execution.

    ``public_market_handoff.deliverable_commit`` is the integration identity,
    while ``data_producer_commit`` identifies the immutable dataset source.
    Neither is required to equal ``current_head``.  In contrast, the four
    code-derived domain layers and every builder-chain step must identify the
    exact consumer ``current_head``.
    """

    generated = ensure_utc(generated_at_utc)
    blockers: list[str] = []
    if not _is_git_sha(current_head):
        blockers.append("btc_next_stage:current_head_invalid")

    normalized_sources: dict[str, dict[str, Any]] = {}
    for layer in CURRENT_HEAD_LAYERS:
        row = dict(source_evidence.get(layer) or {})
        layer_blockers: list[str] = []
        if not row:
            layer_blockers.append(f"btc_next_stage:source_evidence_missing:{layer}")
        if str(row.get("source_head") or "") != current_head:
            layer_blockers.append(f"btc_next_stage:source_head_mismatch:{layer}")
        if not _is_sha256(str(row.get("sha256") or "")):
            layer_blockers.append(f"btc_next_stage:source_sha256_invalid:{layer}")
        if not str(row.get("path") or "").strip():
            layer_blockers.append(f"btc_next_stage:source_path_missing:{layer}")
        layer_blockers.extend(
            f"btc_next_stage:source_report_blocked:{layer}:{item}"
            for item in row.get("blockers", [])
        )
        blockers.extend(layer_blockers)
        normalized_sources[layer] = {
            "path": str(row.get("path") or ""),
            "sha256": str(row.get("sha256") or ""),
            "source_head": str(row.get("source_head") or ""),
            "status": str(row.get("status") or "unknown"),
            "blockers": _dedupe(layer_blockers),
        }

    handoff_summary, handoff_blockers = _validate_public_market_handoff(
        public_market_handoff
    )
    dependency_summary, dependency_blockers = _validate_public_ws_dependency(
        public_ws_dependency
    )
    l2_summary, l2_blockers = _validate_l2_evidence(
        l2_evidence,
        current_head=current_head,
        producer_commit=str(handoff_summary.get("data_producer_commit") or ""),
    )
    chain_summary, chain_blockers = _validate_builder_chain(
        builder_chain, current_head=current_head
    )
    blockers.extend(handoff_blockers)
    blockers.extend(dependency_blockers)
    blockers.extend(l2_blockers)
    blockers.extend(chain_blockers)

    funding_summary = _runtime_evidence_summary(funding_evidence)
    private_ws_summary = _runtime_evidence_summary(private_ws_evidence)
    if not (
        funding_summary["real_observation"]
        and funding_summary["source_head"] == current_head
        and not funding_summary["fixture_only"]
        and funding_summary["promotion_evidence_ready"]
        and funding_summary["identity_valid"]
    ):
        blockers.append("btc_next_stage:real_funding_cashflow_evidence_missing")
    if not (
        private_ws_summary["real_observation"]
        and private_ws_summary["source_head"] == current_head
        and not private_ws_summary["fixture_only"]
        and private_ws_summary["promotion_evidence_ready"]
        and private_ws_summary["identity_valid"]
    ):
        blockers.append("btc_next_stage:real_private_ws_reconciliation_evidence_missing")
    blockers.extend(PERMANENT_PROMOTION_BLOCKERS)
    blockers = _dedupe(blockers)

    engineering_contracts_valid = not any(
        item.startswith(
            (
                "btc_next_stage:current_head_",
                "btc_next_stage:data_btc_",
                "btc_next_stage:data_handoff_",
                "btc_next_stage:source_",
                "btc_next_stage:public_ws_",
                "btc_next_stage:l2_",
                "btc_next_stage:builder_",
            )
        )
        for item in blockers
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "source_head": current_head,
        "code_commit": current_head,
        "readiness_class": "quality_checked" if engineering_contracts_valid else "blocked",
        "engineering_contracts_valid": engineering_contracts_valid,
        "source_evidence": normalized_sources,
        "public_market_handoff": handoff_summary,
        "public_ws_dependency": dependency_summary,
        "l2_evidence": l2_summary,
        "builder_chain": chain_summary,
        "funding_evidence": funding_summary,
        "private_ws_evidence": private_ws_summary,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "safety": {
            "network_accessed": False,
            "private_endpoint_accessed": False,
            "order_endpoint_accessed": False,
            "paper_queue_write_enabled": False,
            "real_orders_enabled": False,
            "secrets_read": False,
        },
        "blockers": blockers,
    }
    input_hashes = {
        f"{layer}_source": row["sha256"]
        for layer, row in normalized_sources.items()
        if _is_sha256(row["sha256"])
    }
    for key, value in (
        ("data_handoff", handoff_summary.get("handoff_event_sha256")),
        ("selected_bundle", dependency_summary.get("selected_bundle_sha256")),
        ("public_ws_package", dependency_summary.get("package_sha256")),
        ("l2_snapshot", l2_summary.get("sha256")),
    ):
        if _is_sha256(str(value or "")):
            input_hashes[key] = str(value)
    input_hashes["engineering_contract"] = stable_payload_hash(
        {
            "sources": normalized_sources,
            "handoff": handoff_summary,
            "dependency": dependency_summary,
            "l2": l2_summary,
            "builder_chain": chain_summary,
        }
    )
    return apply_btc_artifact_schema(
        payload,
        decision="blocked_fail_closed_engineering_evidence_only",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=[],
        input_hashes=input_hashes,
    )


def _validate_public_market_handoff(
    row: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    value = dict(row or {})
    identity_blockers: list[str] = []
    if not value:
        identity_blockers.append(
            "btc_next_stage:data_btc_v3_immutable_public_market_evidence_handoff_missing"
        )
    if str(value.get("ticket_id") or "") != DATA_HANDOFF_TICKET:
        identity_blockers.append("btc_next_stage:data_handoff_ticket_mismatch")
    if str(value.get("event_id") or "") != DATA_INTEGRATED_EVENT_ID:
        identity_blockers.append("btc_next_stage:data_handoff_event_id_mismatch")
    if str(value.get("event_type") or "") != "integrated":
        identity_blockers.append("btc_next_stage:data_handoff_event_type_not_integrated")
    if str(value.get("transition_for") or "") != DATA_PUBLISHED_EVENT_ID:
        identity_blockers.append(
            "btc_next_stage:data_handoff_producer_transition_mismatch"
        )
    if not _is_git_sha(str(value.get("deliverable_commit") or "")):
        identity_blockers.append(
            "btc_next_stage:data_handoff_deliverable_commit_invalid"
        )
    if not _is_git_sha(str(value.get("data_producer_commit") or "")):
        identity_blockers.append(
            "btc_next_stage:data_handoff_data_producer_commit_invalid"
        )
    if not _is_sha256(str(value.get("handoff_event_sha256") or "")):
        identity_blockers.append("btc_next_stage:data_handoff_event_sha256_invalid")
    if not str(value.get("schema_version") or "").strip():
        identity_blockers.append("btc_next_stage:data_handoff_schema_version_missing")
    if str(value.get("readiness_class") or "") not in {
        "quality_checked",
        "research_ready",
        "backtest_ready",
        "promotion_evidence_ready",
    }:
        identity_blockers.append(
            "btc_next_stage:data_handoff_readiness_class_invalid"
        )
    upstream_blockers = [str(item) for item in value.get("blockers", [])]
    accepted = not identity_blockers
    return {
        "ticket_id": str(value.get("ticket_id") or ""),
        "event_id": str(value.get("event_id") or ""),
        "event_type": str(value.get("event_type") or ""),
        "transition_for": str(value.get("transition_for") or ""),
        "deliverable_commit": str(value.get("deliverable_commit") or ""),
        "data_producer_commit": str(value.get("data_producer_commit") or ""),
        "handoff_event_sha256": str(value.get("handoff_event_sha256") or ""),
        "schema_version": str(value.get("schema_version") or ""),
        "readiness_class": str(value.get("readiness_class") or "blocked"),
        "blockers": upstream_blockers,
        "accepted": accepted,
        "upstream_gate_blocked": bool(upstream_blockers),
    }, [*identity_blockers, *upstream_blockers]


def _validate_public_ws_dependency(
    row: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    value = dict(row or {})
    blockers: list[str] = []
    if not value:
        blockers.append("btc_next_stage:public_ws_dependency_missing")
    for field in ("selected_bundle_sha256", "package_sha256"):
        if not _is_sha256(str(value.get(field) or "")):
            blockers.append(f"btc_next_stage:public_ws_{field}_invalid")
    if not str(value.get("resolver_contract_version") or "").strip():
        blockers.append("btc_next_stage:public_ws_resolver_contract_version_missing")
    if value.get("public_only") is not True:
        blockers.append("btc_next_stage:public_ws_dependency_not_public_only")
    if value.get("import_safe") is not True:
        blockers.append("btc_next_stage:public_ws_dependency_not_import_safe")
    if str(value.get("distribution_name") or "").lower() != "websocket-client":
        blockers.append("btc_next_stage:public_ws_distribution_identity_invalid")
    if not str(value.get("distribution_version") or "").strip():
        blockers.append("btc_next_stage:public_ws_distribution_version_missing")
    if not str(value.get("module_path") or "").strip():
        blockers.append("btc_next_stage:public_ws_module_path_missing")
    if not _is_sha256(str(value.get("module_sha256") or "")):
        blockers.append("btc_next_stage:public_ws_module_sha256_invalid")
    if value.get("allowlist_valid") is not True:
        blockers.append("btc_next_stage:public_ws_dependency_not_allowlisted")
    blockers.extend(str(item) for item in value.get("blockers", []))
    return {
        "resolver_contract_version": str(
            value.get("resolver_contract_version") or ""
        ),
        "selected_bundle_sha256": str(value.get("selected_bundle_sha256") or ""),
        "package_sha256": str(value.get("package_sha256") or ""),
        "public_only": value.get("public_only") is True,
        "import_safe": value.get("import_safe") is True,
        "package_name": str(value.get("package_name") or ""),
        "distribution_name": str(value.get("distribution_name") or ""),
        "distribution_version": str(
            value.get("distribution_version") or ""
        ),
        "distribution_root": str(value.get("distribution_root") or ""),
        "module_name": str(value.get("module_name") or ""),
        "module_version": str(value.get("module_version") or ""),
        "module_path": str(value.get("module_path") or ""),
        "module_sha256": str(value.get("module_sha256") or ""),
        "allowlist_roots": [
            str(item) for item in value.get("allowlist_roots", [])
        ],
        "allowlist_valid": value.get("allowlist_valid") is True,
        "user_site_consumed": value.get("user_site_consumed") is True,
        "valid": not blockers,
    }, blockers


def _validate_l2_evidence(
    row: Mapping[str, Any] | None,
    *,
    current_head: str,
    producer_commit: str,
) -> tuple[dict[str, Any], list[str]]:
    value = dict(row or {})
    blockers: list[str] = []
    if not value:
        blockers.append("btc_next_stage:l2_evidence_missing")
    if str(value.get("consumer_source_head") or "") != current_head:
        blockers.append("btc_next_stage:l2_consumer_source_head_mismatch")
    evidence_producer = str(value.get("producer_commit") or "")
    if not _is_git_sha(evidence_producer):
        blockers.append("btc_next_stage:l2_producer_commit_invalid")
    elif producer_commit and evidence_producer != producer_commit:
        blockers.append("btc_next_stage:l2_producer_commit_handoff_mismatch")
    if not _is_sha256(str(value.get("sha256") or "")):
        blockers.append("btc_next_stage:l2_sha256_invalid")
    if value.get("sequence_contiguous") is not True:
        blockers.append("btc_next_stage:l2_sequence_continuity_unproven")
    if value.get("two_sided") is not True:
        blockers.append("btc_next_stage:l2_two_sided_book_unproven")
    return {
        "consumer_source_head": str(value.get("consumer_source_head") or ""),
        "producer_commit": evidence_producer,
        "sha256": str(value.get("sha256") or ""),
        "sequence_contiguous": value.get("sequence_contiguous") is True,
        "two_sided": value.get("two_sided") is True,
        "valid": not blockers,
    }, blockers


def _validate_builder_chain(
    rows: Sequence[Mapping[str, Any]], *, current_head: str
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    blockers: list[str] = []
    names = [str(row.get("name") or "") for row in rows]
    if tuple(names) != BUILDER_CHAIN:
        blockers.append("btc_next_stage:builder_chain_order_invalid")
    for row in rows:
        name = str(row.get("name") or "")
        source_head = str(row.get("source_head") or "")
        digest = str(row.get("sha256") or "")
        if source_head != current_head:
            blockers.append(f"btc_next_stage:builder_source_head_mismatch:{name}")
        if not _is_sha256(digest):
            blockers.append(f"btc_next_stage:builder_sha256_invalid:{name}")
        normalized.append(
            {
                "name": name,
                "source_head": source_head,
                "sha256": digest,
                "immutable_output": row.get("immutable_output") is True,
            }
        )
        if row.get("immutable_output") is not True:
            blockers.append(f"btc_next_stage:builder_output_not_immutable:{name}")
    return normalized, blockers


def _runtime_evidence_summary(row: Mapping[str, Any] | None) -> dict[str, Any]:
    value = dict(row or {})
    schema_version = str(value.get("schema_version") or "")
    source_head = str(value.get("source_head") or "")
    artifact_hash = str(value.get("artifact_hash") or "")
    return {
        "schema_version": schema_version,
        "source_head": source_head,
        "artifact_hash": artifact_hash,
        "offline_fixture_validated": value.get("offline_fixture_validated") is True,
        "fixture_only": value.get("fixture_only") is not False,
        "real_observation": value.get("real_observation") is True,
        "promotion_evidence_ready": value.get("promotion_evidence_ready") is True,
        "identity_valid": bool(schema_version) and _is_sha256(artifact_hash),
    }


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _is_git_sha(value: str) -> bool:
    return 40 <= len(value) <= 64 and all(
        char in "0123456789abcdef" for char in value.lower()
    )


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "BUILDER_CHAIN",
    "CURRENT_HEAD_LAYERS",
    "DATA_HANDOFF_TICKET",
    "DATA_INTEGRATED_EVENT_ID",
    "DATA_PUBLISHED_EVENT_ID",
    "PERMANENT_PROMOTION_BLOCKERS",
    "SCHEMA_VERSION",
    "build_btc_next_stage_engineering_evidence",
    "resolve_selected_public_ws_dependency",
]
