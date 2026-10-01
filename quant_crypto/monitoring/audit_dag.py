from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from quant_shared.core.serialization import canonical_payload_hash
from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema


BTC_AUDIT_DAG_VERSION = "btc_audit_dag_v1"


class BTCAuditNodeType(str, Enum):
    DATA_SNAPSHOT = "data_snapshot"
    FEATURE = "feature"
    SIGNAL = "signal"
    FORECAST = "forecast"
    TARGET = "target"
    RISK = "risk"
    ORDER = "order"
    FILL = "fill"
    LEDGER = "ledger"
    PNL = "pnl"
    REPORT = "report"


BTC_AUDIT_NODE_ORDER: tuple[BTCAuditNodeType, ...] = (
    BTCAuditNodeType.DATA_SNAPSHOT,
    BTCAuditNodeType.FEATURE,
    BTCAuditNodeType.SIGNAL,
    BTCAuditNodeType.FORECAST,
    BTCAuditNodeType.TARGET,
    BTCAuditNodeType.RISK,
    BTCAuditNodeType.ORDER,
    BTCAuditNodeType.FILL,
    BTCAuditNodeType.LEDGER,
    BTCAuditNodeType.PNL,
    BTCAuditNodeType.REPORT,
)

STRUCTURED_LOG_FIELDS: tuple[str, ...] = (
    "run_id",
    "strategy_id",
    "data_version",
    "decision_time_utc",
    "signal_id",
    "forecast_id",
    "target_id",
    "risk_decision_id",
    "order_id",
    "fill_id",
    "error_code",
)


@dataclass(frozen=True)
class BTCAuditArtifactRef:
    path: str
    artifact_hash: str
    code_version: str
    input_hashes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("BTC audit artifact path is required.")
        if not _looks_like_hash(self.artifact_hash):
            raise ValueError("BTC audit artifact_hash must be a stable hex hash.")
        if not self.code_version:
            raise ValueError("BTC audit artifact code_version is required.")
        for name, value in self.input_hashes.items():
            if not name or not _looks_like_hash(value):
                raise ValueError("BTC audit input_hashes must map names to stable hex hashes.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "artifact_hash": self.artifact_hash,
            "code_version": self.code_version,
            "input_hashes": dict(self.input_hashes),
        }


@dataclass(frozen=True)
class BTCAuditNode:
    node_type: BTCAuditNodeType
    artifact: BTCAuditArtifactRef
    node_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.node_type, BTCAuditNodeType):
            object.__setattr__(self, "node_type", BTCAuditNodeType(str(self.node_type)))
        if not self.node_id:
            object.__setattr__(self, "node_id", f"btc_{self.node_type.value}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "artifact": self.artifact.to_dict(),
            "depends_on": list(self.depends_on),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BTCAuditDAG:
    run_id: str
    strategy_id: str
    data_version: str
    decision_time_utc: datetime
    nodes: list[BTCAuditNode]
    log_context: dict[str, Any]
    dag_version: str = BTC_AUDIT_DAG_VERSION

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("BTC audit DAG run_id is required.")
        if not self.strategy_id:
            raise ValueError("BTC audit DAG strategy_id is required.")
        if not self.data_version:
            raise ValueError("BTC audit DAG data_version is required.")
        object.__setattr__(self, "decision_time_utc", ensure_utc(self.decision_time_utc))

    def validate(self) -> list[str]:
        blockers: list[str] = []
        node_types = [node.node_type for node in self.nodes]
        expected = list(BTC_AUDIT_NODE_ORDER)
        if node_types != expected:
            blockers.append("btc_audit_dag_node_order_incomplete_or_invalid")
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            blockers.append("btc_audit_dag_duplicate_node_id")
        for index, node in enumerate(self.nodes):
            if index > 0:
                previous = self.nodes[index - 1].node_id
                if previous not in node.depends_on:
                    blockers.append(f"btc_audit_dag_missing_dependency:{node.node_id}->{previous}")
            for dependency in node.depends_on:
                if dependency not in node_ids:
                    blockers.append(f"btc_audit_dag_unknown_dependency:{node.node_id}->{dependency}")
        for field_name in STRUCTURED_LOG_FIELDS:
            if field_name not in self.log_context:
                blockers.append(f"btc_structured_log_field_missing:{field_name}")
        if str(self.log_context.get("run_id", "")) != self.run_id:
            blockers.append("btc_structured_log_run_id_mismatch")
        if str(self.log_context.get("strategy_id", "")) != self.strategy_id:
            blockers.append("btc_structured_log_strategy_id_mismatch")
        if str(self.log_context.get("data_version", "")) != self.data_version:
            blockers.append("btc_structured_log_data_version_mismatch")
        return _dedupe(blockers)

    def to_dict(self) -> dict[str, Any]:
        blockers = self.validate()
        payload = {
            "dag_version": self.dag_version,
            "status": "complete" if not blockers else "blocked",
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "data_version": self.data_version,
            "decision_time_utc": self.decision_time_utc.isoformat(),
            "node_order": [node.value for node in BTC_AUDIT_NODE_ORDER],
            "nodes": [node.to_dict() for node in self.nodes],
            "structured_log_context": dict(self.log_context),
            "blockers": blockers,
        }
        return apply_btc_artifact_schema(
            payload,
            decision="audit_dag_complete" if not blockers else "audit_dag_blocked",
            generated_at_utc=self.decision_time_utc,
            as_of_utc=self.decision_time_utc,
            blockers=blockers,
            warnings=[],
            input_hashes={node.node_id: node.artifact.artifact_hash for node in self.nodes},
        )


def build_btc_audit_dag(
    *,
    run_id: str,
    strategy_id: str,
    data_version: str,
    decision_time_utc: datetime,
    artifacts: Mapping[BTCAuditNodeType | str, BTCAuditArtifactRef],
    log_context: Mapping[str, Any],
) -> BTCAuditDAG:
    nodes: list[BTCAuditNode] = []
    previous_id = ""
    for node_type in BTC_AUDIT_NODE_ORDER:
        artifact = artifacts.get(node_type) or artifacts.get(node_type.value)
        if artifact is None:
            raise ValueError(f"BTC audit DAG artifact missing for {node_type.value}.")
        node = BTCAuditNode(
            node_type=node_type,
            artifact=artifact,
            depends_on=[] if not previous_id else [previous_id],
        )
        nodes.append(node)
        previous_id = node.node_id
    return BTCAuditDAG(
        run_id=run_id,
        strategy_id=strategy_id,
        data_version=data_version,
        decision_time_utc=decision_time_utc,
        nodes=nodes,
        log_context=dict(log_context),
    )


def artifact_ref_from_payload(
    *,
    path: str | Path,
    payload: Mapping[str, Any],
    code_version: str,
    input_hashes: Mapping[str, str] | None = None,
) -> BTCAuditArtifactRef:
    return BTCAuditArtifactRef(
        path=str(path),
        artifact_hash=stable_payload_hash(payload),
        code_version=code_version,
        input_hashes=dict(input_hashes or {}),
    )


def stable_payload_hash(payload: Any) -> str:
    return canonical_payload_hash(payload)


def _looks_like_hash(value: str) -> bool:
    text = str(value)
    return len(text) >= 12 and all(char in "0123456789abcdefABCDEF" for char in text)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
