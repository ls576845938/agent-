"""Current-HEAD, fail-closed CN operator read-model contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from quant_cn.compat import (
    build_evidence_reference,
    build_freshness_assessment,
    build_read_model_snapshot,
    canonical_cn_payload_hash,
)


SCHEMA_VERSION = "cn_equity_operator_read_model_v1"
RUNTIME_METADATA_SCHEMA_VERSION = (
    "cn_equity_operator_read_model_runtime_metadata_v1"
)
ARTIFACT_RELATIVE_PATH = (
    "artifacts/cn_equity_operator_read_model/latest/"
    "cn_equity_operator_read_model.json"
)
METADATA_RELATIVE_PATH = (
    "artifacts/cn_equity_operator_read_model/latest/runtime_metadata.json"
)
SCHEMA_RELATIVE_PATH = "schemas/cn_equity_operator_read_model.schema.json"
API_PATH = "/api/research/cn-equity/domain-read-model"
LAYER_IDS = ("data", "market_rules", "backtest", "oms", "replay", "qmt")

SAFETY_FLAGS: Mapping[str, bool] = MappingProxyType(
    {
        "broker_access_allowed": False,
        "live_allowed": False,
        "order_endpoint_allowed": False,
        "paper_allowed": False,
        "paper_queue_allowed": False,
        "private_endpoint_allowed": False,
        "promotion_allowed": False,
        "qmt_sdk_allowed": False,
        "real_order_allowed": False,
        "withdraw_allowed": False,
    }
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SELF_BLOCKERS = frozenset({"domain_read_model_missing"})
_CLASSIFICATION_PREFIX = "classification:"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"cn_operator_read_model_field_missing:{field_name}")
    return value.strip()


def _sha256(value: object, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if _HASH_RE.fullmatch(text) is None:
        raise ValueError(f"cn_operator_read_model_sha256_invalid:{field_name}")
    return text


def _commit(value: object, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if _COMMIT_RE.fullmatch(text) is None:
        raise ValueError(f"cn_operator_read_model_commit_invalid:{field_name}")
    return text


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"cn_operator_read_model_datetime_required:{field_name}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"cn_operator_read_model_datetime_naive:{field_name}")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CNUpstreamEvidence:
    layer: str
    event_id: str
    ticket_id: str
    path: str
    sha256: str
    deliverable_commit: str
    created_at: datetime
    readiness_class: str
    gate_impact: str
    promotion_eligible: bool
    blockers: tuple[str, ...]
    classifications: tuple[str, ...]

    def __post_init__(self) -> None:
        layer = _required_text(self.layer, "layer")
        if layer not in LAYER_IDS:
            raise ValueError("cn_operator_read_model_layer_unknown")
        object.__setattr__(self, "layer", layer)
        for name in (
            "event_id",
            "ticket_id",
            "path",
            "readiness_class",
            "gate_impact",
        ):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "deliverable_commit",
            _commit(self.deliverable_commit, "deliverable_commit"),
        )
        object.__setattr__(
            self, "created_at", _aware_utc(self.created_at, "created_at")
        )
        if type(self.promotion_eligible) is not bool:
            raise TypeError("cn_operator_read_model_promotion_bool_required")
        if self.promotion_eligible:
            raise ValueError("cn_operator_read_model_upstream_promotion_forbidden")
        object.__setattr__(
            self,
            "blockers",
            tuple(dict.fromkeys(_required_text(item, "blocker") for item in self.blockers)),
        )
        object.__setattr__(
            self,
            "classifications",
            tuple(
                dict.fromkeys(
                    _required_text(item, "classification")
                    for item in self.classifications
                )
            ),
        )

    def input_dict(self) -> dict[str, object]:
        return {
            "layer": self.layer,
            "event_id": self.event_id,
            "ticket_id": self.ticket_id,
            "path": self.path,
            "sha256": self.sha256,
            "deliverable_commit": self.deliverable_commit,
            "created_at_utc": self.created_at.isoformat(),
            "readiness_class": self.readiness_class,
            "gate_impact": self.gate_impact,
            "promotion_eligible": self.promotion_eligible,
            "blockers": list(self.blockers),
            "classifications": list(self.classifications),
        }


@dataclass(frozen=True)
class CNOperatorBlocker:
    code: str
    owner: str
    next_action: str
    layer: str
    detail: str

    def __post_init__(self) -> None:
        for name in ("code", "owner", "next_action", "layer", "detail"):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        if self.layer not in LAYER_IDS and self.layer != "gate":
            raise ValueError("cn_operator_blocker_layer_unknown")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "owner": self.owner,
            "next_action": self.next_action,
            "layer": self.layer,
            "detail": self.detail,
        }


def _blocker_owner_action(code: str) -> tuple[str, str]:
    lowered = code.lower()
    if (
        "dataready" in lowered
        or "data_" in lowered
        or "manifest" in lowered
        or "pilot" in lowered
    ):
        return (
            "data_steward",
            "publish_and_validate_current_main_cn_dataready_immutable_bundle",
        )
    if any(
        token in lowered
        for token in (
            "board_lot",
            "price_limit",
            "sellability",
            "fee_schedule",
            "session_rule",
            "settlement_rule",
            "market_rule",
        )
    ):
        return (
            "data_steward",
            "publish_and_validate_current_main_cn_market_rule_bundle",
        )
    if "backtest" in lowered or "fixture_research" in lowered:
        return (
            "researcher",
            "run_current_head_real_data_backtest_after_data_and_rule_gates_pass",
        )
    if "qmt" in lowered or "broker" in lowered:
        return (
            "architect/manual_broker_reviewer",
            "retain_fail_closed_until_qmt_broker_and_authorization_review",
        )
    if "oms" in lowered or "replay" in lowered or "reconciliation" in lowered:
        return (
            "a_share_developer",
            "reconcile_current_head_offline_chain_after_required_evidence_arrives",
        )
    if "promotion" in lowered or "paper" in lowered or "approval" in lowered:
        return (
            "architect/manual_reviewer",
            "manual_review_after_all_evidence_gates_pass",
        )
    return ("a_share_developer", f"resolve_cn_operator_blocker:{code}")


def aggregate_cn_operator_blockers(
    evidence: Sequence[CNUpstreamEvidence],
) -> tuple[CNOperatorBlocker, ...]:
    rows: list[CNOperatorBlocker] = []
    seen: set[str] = set()

    def add(code: str, layer: str, detail: str) -> None:
        canonical = code.strip()
        if (
            not canonical
            or canonical in _SELF_BLOCKERS
            or canonical.startswith(_CLASSIFICATION_PREFIX)
            or canonical in seen
        ):
            return
        seen.add(canonical)
        owner, action = _blocker_owner_action(canonical)
        rows.append(
            CNOperatorBlocker(
                code=canonical,
                owner=owner,
                next_action=action,
                layer=layer,
                detail=detail,
            )
        )

    for item in evidence:
        for code in item.blockers:
            add(code, item.layer, f"source_event={item.event_id}")
        classifications = set(item.classifications)
        if item.layer == "backtest" and any(
            "fixture_evidence_contract=quality_checked" in value
            for value in classifications
        ):
            add(
                "cn_backtest_fixture_only",
                item.layer,
                f"source_event={item.event_id}",
            )
        if item.layer == "oms" and any(
            "offline_fixture_chain=quality_checked" in value
            for value in classifications
        ):
            add(
                "cn_oms_offline_fixture_only",
                item.layer,
                f"source_event={item.event_id}",
            )
        if item.layer == "replay":
            add(
                "cn_replay_injected_history_only",
                item.layer,
                f"source_event={item.event_id}",
            )
    return tuple(rows)


def cn_operator_input_sha256(
    evidence: Sequence[CNUpstreamEvidence],
) -> str:
    return canonical_cn_payload_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "sources": [
                item.input_dict()
                for item in sorted(
                    evidence, key=lambda value: (value.layer, value.event_id)
                )
            ],
        }
    )


def cn_operator_generation_inputs(
    *,
    code_commit: str,
    generated_at: datetime,
    input_sha256: str,
    source_events: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_metadata_schema_version": RUNTIME_METADATA_SCHEMA_VERSION,
        "code_commit": _commit(code_commit, "code_commit"),
        "generated_at_utc": _aware_utc(
            generated_at, "generated_at"
        ).isoformat(),
        "input_sha256": _sha256(input_sha256, "input_sha256"),
        "source_events": sorted(
            _required_text(item, "source_event") for item in source_events
        ),
    }


def cn_operator_generation_hash(
    generation_inputs: Mapping[str, Any],
) -> str:
    return canonical_cn_payload_hash(dict(generation_inputs))


@dataclass(frozen=True)
class CNOperatorReadModel:
    code_commit: str
    generated_at: datetime
    evidence: tuple[CNUpstreamEvidence, ...]
    blockers: tuple[CNOperatorBlocker, ...]
    data_version: str = "unavailable"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code_commit", _commit(self.code_commit, "code_commit")
        )
        object.__setattr__(
            self, "generated_at", _aware_utc(self.generated_at, "generated_at")
        )
        layers = tuple(item.layer for item in self.evidence)
        if tuple(sorted(layers)) != tuple(sorted(LAYER_IDS)):
            raise ValueError("cn_operator_read_model_layers_incomplete")
        if len(set(layers)) != len(layers):
            raise ValueError("cn_operator_read_model_layer_duplicate")
        object.__setattr__(
            self, "data_version", _required_text(self.data_version, "data_version")
        )
        if any(value is not False for value in SAFETY_FLAGS.values()):
            raise ValueError("cn_operator_read_model_safety_enabled")

    @property
    def input_sha256(self) -> str:
        return cn_operator_input_sha256(self.evidence)

    @property
    def generation_inputs(self) -> dict[str, object]:
        return cn_operator_generation_inputs(
            code_commit=self.code_commit,
            generated_at=self.generated_at,
            input_sha256=self.input_sha256,
            source_events=tuple(item.event_id for item in self.evidence),
        )

    @property
    def generation_hash(self) -> str:
        return cn_operator_generation_hash(self.generation_inputs)

    def _shared_snapshot(self) -> dict[str, Any]:
        references = tuple(
            build_evidence_reference(
                evidence_id=f"{item.layer}-{item.event_id}",
                path=item.path,
                sha256=item.sha256,
                schema_version="agent_handoff_envelope_v1",
                generated_at=item.created_at,
                code_commit=item.deliverable_commit,
            )
            for item in self.evidence
        )
        freshness = build_freshness_assessment(
            source_id="cn-operator-read-model-inputs",
            available=True,
            generated_at=self.generated_at,
            code_commit=self.code_commit,
            dependency_generated_at=tuple(
                item.created_at for item in self.evidence
            ),
            current_head=self.code_commit,
            evaluated_at=self.generated_at,
            max_age=timedelta(days=1),
        )
        snapshot = build_read_model_snapshot(
            snapshot_id=f"operator-{self.generation_hash[:24]}",
            generated_at=self.generated_at,
            code_commit=self.code_commit,
            data_version=self.data_version,
            status="blocked" if self.blockers else "pass",
            decision="blocked" if self.blockers else "quality_checked",
            freshness=freshness,
            blockers=tuple(
                (
                    item.code,
                    item.owner,
                    item.next_action,
                    item.detail,
                )
                for item in self.blockers
            ),
            evidence=references,
            source_manifest_hash=self.input_sha256,
        )
        return snapshot.to_dict()

    def to_dict(self) -> dict[str, Any]:
        evidence = tuple(sorted(self.evidence, key=lambda item: LAYER_IDS.index(item.layer)))
        layers = {
            item.layer: {
                "status": "blocked" if item.blockers else "quality_checked",
                "readiness_class": item.readiness_class,
                "source_event": item.event_id,
                "source_path": item.path,
                "source_sha256": item.sha256,
                "deliverable_commit": item.deliverable_commit,
                "gate_impact": item.gate_impact,
                "promotion_eligible": False,
                "blockers": list(item.blockers),
                "classifications": list(item.classifications),
            }
            for item in evidence
        }
        first = self.blockers[0] if self.blockers else None
        status = "blocked" if self.blockers else "current_read_only"
        return {
            "schema_version": SCHEMA_VERSION,
            "domain": "cn_equity",
            "owner": "a_share_developer",
            "code_commit": self.code_commit,
            "source_head": self.code_commit,
            "generated_at_utc": self.generated_at.isoformat(),
            "input_sha256": self.input_sha256,
            "generation_hash": self.generation_hash,
            "generation_inputs": self.generation_inputs,
            "data_version": self.data_version,
            "status": status,
            "decision": "fail_closed" if self.blockers else "read_only_review",
            "readiness_class": "quality_checked",
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
            "current_stage": "blocked_read_only" if self.blockers else "manual_review",
            "layers": layers,
            "evidence": [
                {
                    "layer": item.layer,
                    "event_id": item.event_id,
                    "path": item.path,
                    "sha256": item.sha256,
                    "deliverable_commit": item.deliverable_commit,
                }
                for item in evidence
            ],
            "blockers": [item.to_dict() for item in self.blockers],
            "blocker_count": len(self.blockers),
            "gate": {
                "decision": "blocked_fail_closed"
                if self.blockers
                else "manual_review_required",
                "owner": first.owner if first else "architect/manual_reviewer",
                "next_action": first.next_action
                if first
                else "manual_reviewer_review_current_head_packet",
                "first_blocker": first.code if first else "",
            },
            "safety": dict(SAFETY_FLAGS),
            "api_contract": {
                "method": "GET",
                "path": API_PATH,
                "cache_control": "no-store",
                "read_only": True,
                "side_effects": False,
                "builder_triggered": False,
                "order_path_registered": False,
            },
            "team_context_contract": {
                "discovery_path": ARTIFACT_RELATIVE_PATH,
                "code_commit_field": "code_commit",
                "shared_entry_wiring_owner": "integrator",
            },
            "shared_snapshot": self._shared_snapshot(),
        }


def validate_cn_operator_read_model_payload(
    payload: Mapping[str, Any],
    *,
    expected_head: str | None = None,
) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("cn_operator_read_model_payload_mapping_required")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("cn_operator_read_model_schema_mismatch")
    code_commit = _commit(payload.get("code_commit"), "code_commit")
    if expected_head is not None and code_commit != _commit(
        expected_head, "expected_head"
    ):
        raise ValueError("cn_operator_read_model_current_head_mismatch")
    input_sha256 = _sha256(payload.get("input_sha256"), "input_sha256")
    generation_inputs = payload.get("generation_inputs")
    if not isinstance(generation_inputs, Mapping):
        raise ValueError("cn_operator_read_model_generation_inputs_missing")
    if generation_inputs.get("input_sha256") != input_sha256:
        raise ValueError("cn_operator_read_model_input_hash_mismatch")
    if generation_inputs.get("code_commit") != code_commit:
        raise ValueError("cn_operator_read_model_generation_head_mismatch")
    expected_generation = cn_operator_generation_hash(generation_inputs)
    if payload.get("generation_hash") != expected_generation:
        raise ValueError("cn_operator_read_model_generation_hash_mismatch")
    layers = payload.get("layers")
    if not isinstance(layers, Mapping) or set(layers) != set(LAYER_IDS):
        raise ValueError("cn_operator_read_model_layers_incomplete")
    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        raise ValueError("cn_operator_read_model_blockers_invalid")
    if blockers and (
        payload.get("status") != "blocked"
        or payload.get("decision") != "fail_closed"
    ):
        raise ValueError("cn_operator_read_model_blockers_not_fail_closed")
    safety = payload.get("safety")
    if not isinstance(safety, Mapping) or set(safety) != set(SAFETY_FLAGS):
        raise ValueError("cn_operator_read_model_safety_shape_invalid")
    if any(value is not False for value in safety.values()):
        raise ValueError("cn_operator_read_model_safety_enabled")


__all__ = [
    "API_PATH",
    "ARTIFACT_RELATIVE_PATH",
    "CNOperatorBlocker",
    "CNOperatorReadModel",
    "CNUpstreamEvidence",
    "LAYER_IDS",
    "METADATA_RELATIVE_PATH",
    "RUNTIME_METADATA_SCHEMA_VERSION",
    "SAFETY_FLAGS",
    "SCHEMA_RELATIVE_PATH",
    "SCHEMA_VERSION",
    "aggregate_cn_operator_blockers",
    "cn_operator_generation_hash",
    "cn_operator_input_sha256",
    "validate_cn_operator_read_model_payload",
]
