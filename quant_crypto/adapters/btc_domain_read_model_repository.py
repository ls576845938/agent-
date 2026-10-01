"""Read-only file adapter for the BTC domain read model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
)
from quant_crypto.application.btc_domain_read_model import (
    BTCPublishedDomainReadModelUnavailable,
    SCHEMA_VERSION,
    TEAM_CONTEXT_DISCOVERY_PATH,
)
from quant_crypto.application.btc_gate_snapshot import load_latest_gate_snapshot
from quant_crypto.monitoring.artifact_schema import stable_payload_hash


DEFAULT_SOURCE_PATHS = {
    "data": Path(
        "artifacts/btc_dataready_consumption/latest/btc_dataready_consumption_report.json"
    ),
    "strategy": Path(
        "artifacts/btc_strategy_promotion_readiness/latest/btc_strategy_promotion_readiness_review.json"
    ),
    "risk": Path(
        "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"
    ),
    "oms": Path(
        "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json"
    ),
    "ledger": Path(
        "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_oms_session_reconciliation_report.json"
    ),
    "replay": Path(
        "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json"
    ),
    "gate": Path(
        "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"
    ),
}


PUBLISHED_READ_MODEL_PATH = Path(TEAM_CONTEXT_DISCOVERY_PATH)
PUBLISHED_GATE_PATH = DEFAULT_SOURCE_PATHS["gate"]


@dataclass(frozen=True)
class BTCPublishedDomainReadModelRepository:
    """Strict reader for the accepted external current-HEAD publication."""

    repo_root: Path
    artifact_reader: BTCRuntimeArtifactReader

    def read_published(self, *, source_head: str) -> Mapping[str, Any]:
        lineage = load_latest_gate_snapshot(
            self.repo_root,
            expected_head=source_head,
            artifact_reader=self.artifact_reader,
        )
        if lineage.get("status") != "valid":
            error = str(lineage.get("error") or "lineage_invalid")
            raise _published_error(error)
        pointer = _mapping(lineage.get("pointer"))
        manifest = _mapping(lineage.get("manifest"))
        checks = _mapping(manifest.get("validation_checks"))
        if (
            manifest.get("status") != "complete_immutable_gate_snapshot"
            or not checks
            or any(value is not True for value in checks.values())
        ):
            raise _published_error("manifest_not_accepted")
        gate = _mapping(manifest.get("gate"))
        guardrails = _mapping(manifest.get("guardrails"))
        if (
            gate.get("research_only") is not True
            or guardrails.get("immutable_snapshot_only") is not True
            or guardrails.get("atomic_latest_pointer_publish") is not True
            or any(
                section.get(key) is not False
                for section, keys in (
                    (
                        gate,
                        (
                            "paper_queue_write_allowed",
                            "paper_allowed",
                            "live_unlock_allowed",
                            "live_order_allowed",
                            "broker_or_order_allowed",
                            "broker_access_allowed",
                            "oms_access_allowed",
                            "order_endpoint_used",
                            "private_endpoint_used",
                            "real_order_submitted",
                        ),
                    ),
                    (
                        guardrails,
                        (
                            "private_endpoint_used",
                            "order_endpoint_used",
                            "paper_queue_write_allowed",
                            "live_unlock_allowed",
                            "broker_or_order_allowed",
                        ),
                    ),
                )
                for key in keys
            )
        ):
            raise _published_error("manifest_safety_contract_mismatch")
        if (
            str(pointer.get("code_commit") or "") != source_head
            or str(manifest.get("code_commit") or "") != source_head
        ):
            raise _published_error("lineage_wrong_head")
        if any(
            pointer.get(key) is not False
            for key in (
                "paper_queue_write_allowed",
                "live_unlock_allowed",
                "broker_or_order_allowed",
            )
        ):
            raise _published_error("pointer_safety_contract_mismatch")

        entry = next(
            (
                row
                for row in _mapping_rows(manifest.get("artifacts"))
                if str(row.get("logical_path") or "")
                == PUBLISHED_READ_MODEL_PATH.as_posix()
            ),
            None,
        )
        if entry is None:
            raise _published_error("logical_entry_missing")
        gate_entry = next(
            (
                row
                for row in _mapping_rows(manifest.get("artifacts"))
                if str(row.get("logical_path") or "")
                == PUBLISHED_GATE_PATH.as_posix()
            ),
            None,
        )
        if gate_entry is None:
            raise _published_error("gate_logical_entry_missing")

        try:
            raw = self.artifact_reader.read_bytes(PUBLISHED_READ_MODEL_PATH)
            payload = json.loads(raw.decode("utf-8"))
        except BTCRuntimeArtifactStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _published_error("json_invalid") from exc
        if not isinstance(payload, dict):
            raise _published_error("json_not_object")
        digest = hashlib.sha256(raw).hexdigest()
        if str(entry.get("file_sha256") or "") != digest:
            raise _published_error("direct_file_sha256_mismatch")
        if (
            str(payload.get("aggregation_batch_id") or "")
            != str(pointer.get("aggregation_batch_id") or "")
        ):
            raise _published_error("aggregation_batch_mismatch")

        try:
            gate_raw = self.artifact_reader.read_bytes(PUBLISHED_GATE_PATH)
            gate_payload = json.loads(gate_raw.decode("utf-8"))
        except BTCRuntimeArtifactStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _published_error("gate_json_invalid") from exc
        if not isinstance(gate_payload, dict):
            raise _published_error("gate_json_not_object")
        gate_digest = hashlib.sha256(gate_raw).hexdigest()
        if str(gate_entry.get("file_sha256") or "") != gate_digest:
            raise _published_error("gate_direct_file_sha256_mismatch")
        if (
            str(gate_payload.get("aggregation_batch_id") or "")
            != str(pointer.get("aggregation_batch_id") or "")
            or str(gate_payload.get("source_head") or "") != source_head
            or str(gate_payload.get("code_commit") or "") != source_head
        ):
            raise _published_error("gate_identity_mismatch")
        canonical_blockers = gate_payload.get("blockers")
        if (
            not isinstance(canonical_blockers, list)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in canonical_blockers
            )
        ):
            raise _published_error("gate_blocker_contract_mismatch")

        self._validate_payload(
            payload,
            source_head=source_head,
            canonical_blockers=canonical_blockers,
        )
        return payload

    def _validate_payload(
        self,
        payload: Mapping[str, Any],
        *,
        source_head: str,
        canonical_blockers: list[Any],
    ) -> None:
        try:
            schema = json.loads(
                (self.repo_root / "schemas/btc_domain_read_model.schema.json")
                .read_text(encoding="utf-8")
            )
            jsonschema.validate(dict(payload), schema)
        except (
            OSError,
            json.JSONDecodeError,
            jsonschema.SchemaError,
            jsonschema.ValidationError,
        ) as exc:
            raise _published_error("schema_invalid") from exc

        from quant_crypto.application.btc_next_stage_current_head_orchestrator import (
            SAFETY,
        )

        if (
            payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("domain") != "btc"
            or payload.get("source_head") != source_head
            or payload.get("code_commit") != source_head
            or payload.get("freshness") != "current_head"
            or payload.get("status") != "blocked"
            or payload.get("current_stage") != "pending_next_stage_gate"
            or payload.get("decision")
            != "blocked_fail_closed_no_paper_no_live"
            or payload.get("readiness_class") != "quality_checked"
        ):
            raise _published_error("semantic_contract_mismatch")
        if (
            payload.get("promotion_evidence_ready") is not False
            or payload.get("paper_ready") is not False
            or payload.get("live_ready") is not False
        ):
            raise _published_error("readiness_flag_not_false")
        if payload.get("safety") != SAFETY or len(SAFETY) != 49:
            raise _published_error("safety_contract_mismatch")
        if any(value is not False for value in SAFETY.values()):
            raise _published_error("safety_flag_not_false")

        required = payload.get("required_blockers")
        canonical = list(canonical_blockers)
        if (
            not isinstance(required, list)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in required
            )
            or len(required) != len(set(required))
            or any(not value.strip() for value in canonical)
            or len(canonical) != len(set(canonical))
            or required != canonical
            or payload.get("required_blocker_count") != len(required)
            or payload.get("required_blockers_sha256")
            != stable_payload_hash(required)
            or payload.get("required_blockers_missing") != []
            or payload.get("required_blockers_preserved") is not True
        ):
            raise _published_error("required_blockers_not_preserved")
        blockers = payload.get("blockers")
        if (
            not isinstance(blockers, list)
            or payload.get("blocker_count") != len(blockers)
        ):
            raise _published_error("blocker_contract_mismatch")
        for blocker in blockers:
            if not isinstance(blocker, Mapping):
                raise _published_error("blocker_not_structured")
            if not all(
                str(blocker.get(key) or "").strip()
                for key in (
                    "code",
                    "category",
                    "owner",
                    "next_executable_action",
                )
            ):
                raise _published_error("blocker_fields_incomplete")
        blocker_codes = [
            str(blocker.get("code") or "").strip() for blocker in blockers
        ]
        if (
            len(blocker_codes) != len(set(blocker_codes))
            or blocker_codes != canonical
        ):
            raise _published_error("required_blockers_not_preserved")
        api_contract = _mapping(payload.get("api_contract"))
        if (
            api_contract.get("method") != "GET"
            or api_contract.get("path")
            != "/api/research/btc/domain-read-model"
            or api_contract.get("cache_control") != "no-store"
            or api_contract.get("read_only") is not True
            or api_contract.get("side_effects") is not False
        ):
            raise _published_error("api_contract_mismatch")


@dataclass(frozen=True)
class BTCFileDomainReadModelRepository:
    repo_root: Path
    source_paths: Mapping[str, Path] | None = None
    expected_hashes: Mapping[str, str] | None = None
    max_age_hours: float = 24.0
    artifact_reader: BTCRuntimeArtifactReader | None = None

    def read_sources(
        self, *, source_head: str, generated_at_utc: datetime
    ) -> Mapping[str, Mapping[str, Any]]:
        paths = self.source_paths or DEFAULT_SOURCE_PATHS
        expected = self.expected_hashes or {}
        reader = self.artifact_reader or BTCRuntimeArtifactReader.from_environment(
            source_repo_root=self.repo_root
        )
        return {
            layer: self._read_one(
                layer=layer,
                relative_path=path,
                artifact_reader=reader,
                expected_hash=expected.get(layer, ""),
                source_head=source_head,
                generated_at_utc=generated_at_utc,
            )
            for layer, path in paths.items()
        }

    def _read_one(
        self,
        *,
        layer: str,
        relative_path: Path,
        artifact_reader: BTCRuntimeArtifactReader,
        expected_hash: str,
        source_head: str,
        generated_at_utc: datetime,
    ) -> dict[str, Any]:
        path = artifact_reader.resolve(relative_path)
        base = {
            "path": relative_path.as_posix(),
            "status": "missing",
            "decision": "",
            "readiness_class": "blocked",
            "sha256": "",
            "source_head": "",
            "generated_at_utc": "",
            "freshness": "missing",
            "blockers": [f"btc_domain_read_model_source_missing:{layer}"],
            "summary": {},
        }
        if not path.is_file():
            return base
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("not_object")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {
                **base,
                "status": "invalid",
                "freshness": "invalid",
                "blockers": [f"btc_domain_read_model_source_invalid:{layer}"],
            }
        digest = hashlib.sha256(raw).hexdigest()
        artifact_head = str(
            payload.get("source_head")
            or payload.get("code_commit")
            or payload.get("commit")
            or ""
        )
        generated_text = str(
            payload.get("generated_at_utc") or payload.get("generated_at") or ""
        )
        freshness = "current"
        validation_blockers: list[str] = []
        if expected_hash and digest != expected_hash:
            freshness = "hash_mismatch"
            validation_blockers.append(
                f"btc_domain_read_model_source_hash_mismatch:{layer}"
            )
        if not artifact_head or artifact_head != source_head:
            freshness = "wrong_head"
            validation_blockers.append(
                f"btc_domain_read_model_source_wrong_head:{layer}"
            )
        generated = _parse_utc(generated_text)
        now = _ensure_utc(generated_at_utc)
        if generated is None:
            freshness = "stale"
            validation_blockers.append(
                f"btc_domain_read_model_source_generated_at_missing:{layer}"
            )
        elif generated > now or (now - generated).total_seconds() > self.max_age_hours * 3600:
            freshness = "stale"
            validation_blockers.append(
                f"btc_domain_read_model_source_stale:{layer}"
            )
        readiness = str(
            payload.get("readiness_class")
            or payload.get("readiness")
            or "quality_checked"
        )
        return {
            "path": relative_path.as_posix(),
            "status": str(payload.get("status") or "unknown"),
            "decision": str(payload.get("decision") or ""),
            "readiness_class": readiness,
            "sha256": digest,
            "source_head": artifact_head,
            "generated_at_utc": generated_text,
            "freshness": freshness,
            "blockers": [
                *validation_blockers,
                *[str(item) for item in payload.get("blockers", [])],
            ],
            "summary": dict(payload.get("summary") or {}),
        }


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _published_error(code: str) -> BTCPublishedDomainReadModelUnavailable:
    normalized = str(code).strip().split(":", 1)[0]
    return BTCPublishedDomainReadModelUnavailable(
        f"btc_published_domain_read_model_{normalized}"
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


__all__ = [
    "BTCFileDomainReadModelRepository",
    "BTCPublishedDomainReadModelRepository",
    "DEFAULT_SOURCE_PATHS",
    "PUBLISHED_READ_MODEL_PATH",
]
