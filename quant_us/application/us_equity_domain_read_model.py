"""Fail-closed US equity domain read-model application service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


SCHEMA_VERSION = "us_equity_domain_read_model_v1"
TEAM_CONTEXT_DISCOVERY_PATH = (
    "artifacts/us_equity_strategy_production_line/latest/"
    "us_equity_operator_read_model.json"
)
LAYER_IDS = ("data", "backtest", "portfolio", "oms", "ledger", "replay")
READINESS_ORDER = {
    "quality_checked": 0,
    "research_ready": 1,
    "backtest_ready": 2,
    "promotion_evidence_ready": 3,
}


class USDomainReadModelSourceRepository(Protocol):
    def read_sources(
        self,
        *,
        source_head: str,
        generated_at_utc: datetime,
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class USDomainReadModelService:
    """Build a projection in memory; API reads never materialize artifacts."""

    repository: USDomainReadModelSourceRepository
    head_resolver: Callable[[], str]
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def read(self) -> dict[str, Any]:
        source_head = self.head_resolver()
        now = _as_utc(self.clock())
        sources = self.repository.read_sources(
            source_head=source_head,
            generated_at_utc=now,
        )
        return build_us_equity_domain_read_model(
            sources=sources,
            source_head=source_head,
            generated_at_utc=now,
        )


def build_us_equity_domain_read_model(
    *,
    sources: Sequence[Mapping[str, Any]],
    source_head: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    now = _as_utc(generated_at_utc)
    source_rows = [dict(row) for row in sources]
    evidence = [_public_source_row(row) for row in source_rows]
    layer_rows = _build_layers(source_rows)
    blockers = _collect_blockers(source_rows, layer_rows)

    head_valid = len(source_head) == 40 and all(
        character in "0123456789abcdef" for character in source_head.lower()
    )
    if not head_valid:
        blockers = _merge_blockers(
            blockers,
            [
                _blocker(
                    "domain_source_head_invalid",
                    source="domain_read_model",
                    owner="integrator",
                    root_cause="The read model is not bound to a full Git commit.",
                    next_action="Rebuild on an exact 40-character current HEAD.",
                )
            ],
        )

    all_layers_present = set(layer_rows) == set(LAYER_IDS)
    all_sources_current = bool(source_rows) and all(
        row.get("freshness") == "current_head" for row in source_rows
    )
    if not all_layers_present:
        blockers = _merge_blockers(
            blockers,
            [
                _blocker(
                    "domain_read_model_layer_missing",
                    source="domain_read_model",
                    owner="super_developer",
                    root_cause="At least one required US domain layer has no evidence binding.",
                    next_action="Restore the missing committed source contract entry.",
                )
            ],
        )

    readiness_class = _minimum_readiness(layer_rows)
    data_blocked = any(row["owner"] == "data_steward" for row in blockers)
    current_stage = (
        "blocked_external_data"
        if data_blocked
        else "research_only_fail_closed"
    )
    status = "blocked" if blockers else "current_read_only"
    freshness = (
        "current_head"
        if head_valid and all_sources_current and all_layers_present
        else "blocked"
    )

    first_blocker = blockers[0] if blockers else None
    owner = first_blocker["owner"] if first_blocker else "researcher"
    next_action = (
        first_blocker["next_action"]
        if first_blocker
        else "Review current-HEAD evidence without changing trading permissions."
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "domain": "us_equity",
        "source_head": source_head,
        "code_commit": source_head,
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "freshness": freshness,
        "status": status,
        "current_stage": current_stage,
        "readiness_class": readiness_class,
        "gate_decision": "blocked_do_not_promote_or_start_paper",
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "layers": layer_rows,
        "evidence": evidence,
        "blockers": blockers,
        "gate": {
            "decision": "blocked_do_not_promote_or_start_paper",
            "first_blocker": first_blocker["code"] if first_blocker else "",
            "root_cause": first_blocker["root_cause"] if first_blocker else "",
            "owner": owner,
            "next_action": next_action,
        },
        "safety": _safety_flags(),
        "api_contract": {
            "method": "GET",
            "path": "/api/research/us-equity/domain-read-model",
            "cache_control": "no-store",
            "read_only": True,
            "side_effects": False,
            "builder_triggered": False,
            "runtime_triggered": False,
            "order_path_registered": False,
        },
        "team_context_contract": {
            "discovery_path": TEAM_CONTEXT_DISCOVERY_PATH,
            "current_head_required": True,
            "missing_is_blocked": True,
            "stale_is_blocked": True,
        },
    }
    payload["artifact_identity_sha256"] = _identity_sha256(payload)
    return payload


def load_materialized_us_equity_domain_read_model(
    *,
    repo_root: Path,
    current_head: str,
    path: Path = Path(TEAM_CONTEXT_DISCOVERY_PATH),
) -> dict[str, Any]:
    """Read a materialized projection and fail closed on drift or corruption."""

    report_path = path if path.is_absolute() else repo_root / path
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blocked_materialized(
            current_head=current_head,
            blocker_code="domain_read_model_artifact_missing_or_invalid",
        )
    if not isinstance(payload, dict):
        return _blocked_materialized(
            current_head=current_head,
            blocker_code="domain_read_model_artifact_not_object",
        )

    recorded_identity = str(payload.get("artifact_identity_sha256") or "")
    without_identity = dict(payload)
    without_identity.pop("artifact_identity_sha256", None)
    if recorded_identity != _identity_sha256(without_identity):
        return _blocked_materialized(
            current_head=current_head,
            blocker_code="domain_read_model_artifact_hash_mismatch",
        )
    if payload.get("source_head") != current_head:
        return _blocked_materialized(
            current_head=current_head,
            blocker_code="domain_read_model_artifact_wrong_head",
        )
    return payload


def _build_layers(
    sources: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    layers: dict[str, dict[str, Any]] = {}
    for source in sources:
        payload = _mapping(source.get("payload"))
        for layer_value in source.get("layers", []):
            layer = _mapping(layer_value)
            layer_id = str(layer.get("id") or "")
            if layer_id not in LAYER_IDS or layer_id in layers:
                continue
            layers[layer_id] = {
                "status": _layer_status(layer_id, payload, source),
                "freshness": str(source.get("freshness") or "blocked"),
                "readiness_class": str(
                    layer.get("readiness_class")
                    or source.get("readiness_class")
                    or "quality_checked"
                ),
                "evidence_id": str(source.get("id") or ""),
                "artifact_path": str(
                    _mapping(source.get("artifact")).get("path") or ""
                ),
                "artifact_sha256": str(
                    _mapping(source.get("artifact")).get("sha256") or ""
                ),
                "manifest_path": str(
                    _mapping(source.get("manifest")).get("path") or ""
                ),
                "manifest_sha256": str(
                    _mapping(source.get("manifest")).get("sha256") or ""
                ),
                "integration_commit": str(source.get("integration_commit") or ""),
            }
    return layers


def _layer_status(
    layer_id: str,
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
) -> str:
    if source.get("freshness") != "current_head":
        return "blocked_evidence_invalid"
    if layer_id == "data":
        return str(
            _mapping(payload.get("production_pit")).get("state")
            or payload.get("status")
            or "missing"
        )
    if layer_id == "oms":
        complete = _mapping(payload.get("lifecycle")).get("complete") is True
        return (
            "fixture_lifecycle_quality_checked"
            if complete
            else str(payload.get("status") or "blocked")
        )
    if layer_id == "ledger":
        return (
            "fixture_uow_quality_checked"
            if _mapping(payload.get("uow")).get("implementation")
            else str(payload.get("status") or "blocked")
        )
    if layer_id == "replay":
        return (
            "fixture_recovery_quality_checked"
            if _mapping(payload.get("recovery"))
            else str(payload.get("status") or "blocked")
        )
    return str(payload.get("status") or source.get("status") or "blocked")


def _collect_blockers(
    sources: Sequence[Mapping[str, Any]],
    layers: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for source in sources:
        source_id = str(source.get("id") or "unknown_source")
        for raw in source.get("validation_blockers", []):
            code = _normalize_blocker(str(raw))
            if code and not _self_referential(code):
                result.append(_classify_blocker(code, source_id))
        payload = _mapping(source.get("payload"))
        for raw in payload.get("blockers", []):
            code = _normalize_blocker(str(raw))
            if code and not _self_referential(code):
                result.append(_classify_blocker(code, source_id))

    for layer_id in LAYER_IDS:
        if layer_id not in layers:
            continue
        if layers[layer_id].get("freshness") != "current_head":
            result.append(
                _blocker(
                    f"{layer_id}_evidence_not_current",
                    source=str(layers[layer_id].get("evidence_id") or layer_id),
                    owner="super_developer",
                    root_cause=f"The {layer_id} layer evidence failed committed-source validation.",
                    next_action=f"Repair the committed {layer_id} evidence binding and rebuild.",
                )
            )
    return _merge_blockers([], result)


def _classify_blocker(code: str, source: str) -> dict[str, str]:
    lowered = code.lower()
    if any(
        token in lowered
        for token in (
            "production_pit",
            "corporate_action",
            "delisted",
            "survivorship",
        )
    ):
        return _blocker(
            code,
            source=source,
            owner="data_steward",
            root_cause="Required immutable production PIT evidence is absent or incomplete.",
            next_action="Publish and validate the immutable seven-file production PIT handoff.",
        )
    if "manual_paper_start_approval" in lowered:
        return _blocker(
            code,
            source=source,
            owner="architect",
            root_cause="No explicit manual paper-start approval exists.",
            next_action="Keep paper disabled until an architect-approved ticket is recorded.",
        )
    if any(token in lowered for token in ("paper_start", "real_paper", "production_event_ledger")):
        return _blocker(
            code,
            source=source,
            owner="paper_operations",
            root_cause="Only fixture execution evidence exists; paper was not started.",
            next_action="Retain fail-closed state and wait for separately authorized paper operations.",
        )
    if "fixture" in lowered:
        return _blocker(
            code,
            source=source,
            owner="researcher",
            root_cause="Fixture evidence cannot receive production or promotion credit.",
            next_action="Use the fixture only for contract validation.",
        )
    return _blocker(
        code,
        source=source,
        owner="super_developer",
        root_cause="A committed domain evidence contract is not satisfied.",
        next_action="Inspect the named source and repair it in its owning ticket.",
    )


def _normalize_blocker(value: str) -> str:
    code = value.strip()
    if code.startswith("owner:") and " " in code:
        code = code.split(" ", 1)[1].strip()
    return code


def _self_referential(code: str) -> bool:
    lowered = code.lower()
    return (
        lowered == "domain_read_model_missing"
        or lowered == "us_equity_domain_read_model_summary_blocked"
        or lowered.startswith("us_equity_domain_read_model:")
    )


def _minimum_readiness(layers: Mapping[str, Mapping[str, Any]]) -> str:
    values = [
        str(row.get("readiness_class") or "quality_checked")
        for row in layers.values()
    ]
    if not values:
        return "quality_checked"
    return min(values, key=lambda value: READINESS_ORDER.get(value, -1))


def _public_source_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "integration_commit": str(row.get("integration_commit") or ""),
        "freshness": str(row.get("freshness") or "blocked"),
        "status": str(row.get("status") or "blocked"),
        "decision": str(row.get("decision") or ""),
        "readiness_class": str(row.get("readiness_class") or "quality_checked"),
        "artifact": dict(_mapping(row.get("artifact"))),
        "manifest": dict(_mapping(row.get("manifest"))),
        "validation_blockers": [
            str(item) for item in row.get("validation_blockers", [])
        ],
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "promotion_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "broker_access_allowed": False,
        "paper_runner_started": False,
        "paper_queue_write_allowed": False,
        "real_order_submitted": False,
        "withdraw_allowed": False,
        "network_used": False,
    }


def _blocked_materialized(
    *,
    current_head: str,
    blocker_code: str,
) -> dict[str, Any]:
    source = {
        "id": "materialized_read_model",
        "integration_commit": current_head,
        "freshness": "blocked",
        "status": "blocked",
        "decision": "fail_closed",
        "readiness_class": "quality_checked",
        "layers": [{"id": layer, "readiness_class": "quality_checked"} for layer in LAYER_IDS],
        "artifact": {"path": TEAM_CONTEXT_DISCOVERY_PATH, "sha256": "0" * 64},
        "manifest": {"path": TEAM_CONTEXT_DISCOVERY_PATH, "sha256": "0" * 64},
        "validation_blockers": [blocker_code],
        "payload": {"blockers": []},
    }
    return build_us_equity_domain_read_model(
        sources=[source],
        source_head=current_head,
        generated_at_utc=datetime.now(timezone.utc),
    )


def _blocker(
    code: str,
    *,
    source: str,
    owner: str,
    root_cause: str,
    next_action: str,
) -> dict[str, str]:
    return {
        "code": code,
        "source": source,
        "root_cause": root_cause,
        "owner": owner,
        "next_action": next_action,
    }


def _merge_blockers(
    left: Sequence[Mapping[str, str]],
    right: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    by_code: dict[str, dict[str, str]] = {}
    for value in [*left, *right]:
        row = dict(value)
        code = str(row.get("code") or "")
        if not code:
            continue
        if code in by_code:
            existing = by_code[code]
            sources = set(existing["source"].split(","))
            sources.add(str(row.get("source") or ""))
            existing["source"] = ",".join(sorted(item for item in sources if item))
            continue
        by_code[code] = row
        merged.append(row)
    return merged


def _identity_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


__all__ = [
    "LAYER_IDS",
    "SCHEMA_VERSION",
    "TEAM_CONTEXT_DISCOVERY_PATH",
    "USDomainReadModelService",
    "build_us_equity_domain_read_model",
    "load_materialized_us_equity_domain_read_model",
]
