"""Versioned, asset-neutral evidence envelope for one strategy decision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .models import StrategyDecisionContext


SCHEMA_VERSION = "strategy_decision_evidence_v2"
LEGACY_SCHEMA_VERSION = "strategy_decision_evidence_v1"


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _context_digest(context: StrategyDecisionContext) -> str:
    clock = context.clock
    return _digest(
        {
            "schema_version": context.schema_version,
            "identity_digest": context.identity.digest,
            "clock": {
                "mode": clock.mode.value,
                "decision_time": clock.decision_time.isoformat() if clock.decision_time else "",
                "event_time": clock.event_time.isoformat() if clock.event_time else "",
                "available_time": clock.available_time.isoformat() if clock.available_time else "",
                "is_new_bar": clock.is_new_bar,
                "is_final": clock.is_final,
            },
            "market": dict(context.market),
            "features": dict(context.features),
            "universe": list(context.universe),
            "exposure": context.exposure,
            "state_digest": context.state.digest,
            "capabilities": sorted(item.value for item in context.capabilities),
            "parameters": dict(context.parameters),
        }
    )


@dataclass(frozen=True)
class DecisionEvidenceEnvelope:
    package_digest: str
    run_id: str
    decision_id: str
    event_id: str
    phase: str
    strategy_id: str
    strategy_version: str
    code_version: str
    data_version: str
    context_digest: str
    links: Mapping[str, Any]
    input_digest: str = ""
    evidence_kind: str = "offline_execution"
    runtime_observed: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}:
            raise ValueError("schema_version_invalid")
        for name in ("package_digest", "decision_id", "event_id", "context_digest"):
            value = str(getattr(self, name) or "")
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name}_invalid")
        if self.evidence_kind != "offline_execution" or self.runtime_observed is not False:
            raise ValueError("offline_evidence_semantics_required")
        for name in ("run_id", "phase", "strategy_id", "strategy_version", "code_version", "data_version"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name}_required")
        if not isinstance(self.links, Mapping) or not self.links:
            raise ValueError("evidence_links_required")
        if self.schema_version == SCHEMA_VERSION:
            value = str(self.input_digest or "")
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("input_digest_invalid")

    @classmethod
    def build(
        cls,
        *,
        context: StrategyDecisionContext,
        package_digest: str,
        event_id: str,
        phase: str,
        links: Mapping[str, Any],
        input_digest: str,
    ) -> "DecisionEvidenceEnvelope":
        decision_id = _digest(
            {
                "package_digest": package_digest,
                "run_id": context.identity.run_id,
                "event_id": event_id,
                "phase": phase,
                "input_digest": input_digest,
            }
        )
        return cls(
            package_digest=package_digest,
            run_id=context.identity.run_id,
            decision_id=decision_id,
            event_id=event_id,
            phase=phase,
            strategy_id=context.identity.strategy_id,
            strategy_version=context.identity.strategy_version,
            code_version=context.identity.code_version,
            data_version=context.identity.data_version,
            context_digest=_context_digest(context),
            links=dict(links),
            input_digest=input_digest,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DecisionEvidenceEnvelope":
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})

    def require_binding(
        self,
        *,
        package_digest: str = "",
        decision_id: str = "",
        links: Mapping[str, Any] | None = None,
        input_digest: str = "",
    ) -> None:
        if package_digest and package_digest != self.package_digest:
            raise ValueError("package_digest_mismatch")
        if decision_id and decision_id != self.decision_id:
            raise ValueError("decision_id_mismatch")
        if input_digest and input_digest != self.input_digest:
            raise ValueError("input_digest_mismatch")
        for name, expected in dict(links or {}).items():
            if self.links.get(name) != expected:
                raise ValueError(f"evidence_link_mismatch:{name}")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "package_digest": self.package_digest,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "event_id": self.event_id,
            "phase": self.phase,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "code_version": self.code_version,
            "data_version": self.data_version,
            "context_digest": self.context_digest,
            "links": dict(self.links),
            "evidence_kind": self.evidence_kind,
            "runtime_observed": self.runtime_observed,
        }
        if self.schema_version == SCHEMA_VERSION:
            payload["input_digest"] = self.input_digest
        return payload


def package_digest(*, strategy_id: str, strategy_version: str, params_hash: str, code_version: str) -> str:
    return _digest(
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "params_hash": params_hash,
            "code_version": code_version,
        }
    )


__all__ = [
    "DecisionEvidenceEnvelope",
    "package_digest",
    "SCHEMA_VERSION",
    "LEGACY_SCHEMA_VERSION",
]
