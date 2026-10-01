"""Read-only runtime validation for the CN operator read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

import jsonschema

from quant_cn.operations.read_model import (
    ARTIFACT_RELATIVE_PATH,
    METADATA_RELATIVE_PATH,
    RUNTIME_METADATA_SCHEMA_VERSION,
    SAFETY_FLAGS,
    SCHEMA_RELATIVE_PATH,
    SCHEMA_VERSION,
    cn_operator_generation_hash,
    validate_cn_operator_read_model_payload,
)


CN_READ_MODEL_METADATA_MISSING = "cn_read_model_runtime_metadata_missing"
CN_READ_MODEL_METADATA_INVALID = "cn_read_model_runtime_metadata_invalid"
CN_READ_MODEL_ARTIFACT_MISSING = "cn_read_model_artifact_missing"
CN_READ_MODEL_ARTIFACT_INVALID = "cn_read_model_artifact_invalid"
CN_READ_MODEL_GENERATION_MISSING = "cn_read_model_generation_artifact_missing"
CN_READ_MODEL_GENERATION_MISMATCH = "cn_read_model_generation_artifact_mismatch"
CN_READ_MODEL_SCHEMA_MISSING = "cn_read_model_schema_missing"
CN_READ_MODEL_SCHEMA_INVALID = "cn_read_model_schema_invalid"
CN_READ_MODEL_SCHEMA_MISMATCH = "cn_read_model_artifact_schema_mismatch"
CN_READ_MODEL_HASH_MISMATCH = "cn_read_model_artifact_hash_mismatch"
CN_READ_MODEL_GENERATION_HASH_MISMATCH = (
    "cn_read_model_generation_hash_mismatch"
)
CN_READ_MODEL_INPUT_HASH_MISMATCH = "cn_read_model_input_hash_mismatch"
CN_READ_MODEL_HEAD_MISMATCH = "cn_read_model_current_head_mismatch"
CN_READ_MODEL_STALE = "cn_read_model_runtime_metadata_stale"
CN_READ_MODEL_FUTURE = "cn_read_model_runtime_metadata_future"
CN_READ_MODEL_HEAD_UNAVAILABLE = "cn_read_model_current_head_unavailable"


class CNEquityReadModelUnavailable(RuntimeError):
    def __init__(self, blocker: str) -> None:
        self.blocker = blocker
        super().__init__(blocker)


def _current_head(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise CNEquityReadModelUnavailable(
            CN_READ_MODEL_HEAD_UNAVAILABLE
        ) from error


def _read_bytes(path: Path, missing: str, invalid: str) -> bytes:
    if not path.is_file():
        raise CNEquityReadModelUnavailable(missing)
    try:
        return path.read_bytes()
    except OSError as error:
        raise CNEquityReadModelUnavailable(invalid) from error


def _json_object(raw: bytes, blocker: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CNEquityReadModelUnavailable(blocker) from error
    if not isinstance(value, dict):
        raise CNEquityReadModelUnavailable(blocker)
    return value


def _parse_utc(value: object, blocker: str) -> datetime:
    if not isinstance(value, str):
        raise CNEquityReadModelUnavailable(blocker)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CNEquityReadModelUnavailable(blocker) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CNEquityReadModelUnavailable(blocker)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class CNEquityReadModelService:
    repo_root: Path
    artifact_path: Path | None = None
    metadata_path: Path | None = None
    schema_path: Path | None = None
    head_resolver: Callable[[], str] | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    max_age: timedelta = timedelta(hours=24)

    def read(self) -> dict[str, Any]:
        root = self.repo_root.resolve()
        artifact_path = (
            self.artifact_path or root / ARTIFACT_RELATIVE_PATH
        ).resolve()
        metadata_path = (
            self.metadata_path or root / METADATA_RELATIVE_PATH
        ).resolve()
        schema_path = (
            self.schema_path or root / SCHEMA_RELATIVE_PATH
        ).resolve()
        current_head = (
            self.head_resolver() if self.head_resolver else _current_head(root)
        )
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_METADATA_INVALID
            )
        now = now.astimezone(timezone.utc)

        metadata_raw = _read_bytes(
            metadata_path,
            CN_READ_MODEL_METADATA_MISSING,
            CN_READ_MODEL_METADATA_INVALID,
        )
        metadata = _json_object(
            metadata_raw, CN_READ_MODEL_METADATA_INVALID
        )
        self._validate_metadata(
            metadata,
            artifact_path=artifact_path,
            schema_path=schema_path,
            current_head=current_head,
            now=now,
        )

        schema_raw = _read_bytes(
            schema_path,
            CN_READ_MODEL_SCHEMA_MISSING,
            CN_READ_MODEL_SCHEMA_INVALID,
        )
        if hashlib.sha256(schema_raw).hexdigest() != metadata.get(
            "schema_sha256"
        ):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_SCHEMA_MISMATCH
            )
        schema = _json_object(schema_raw, CN_READ_MODEL_SCHEMA_INVALID)

        artifact_raw = _read_bytes(
            artifact_path,
            CN_READ_MODEL_ARTIFACT_MISSING,
            CN_READ_MODEL_ARTIFACT_INVALID,
        )
        if hashlib.sha256(artifact_raw).hexdigest() != metadata.get(
            "artifact_sha256"
        ):
            raise CNEquityReadModelUnavailable(CN_READ_MODEL_HASH_MISMATCH)

        generation_name = metadata.get("generation_artifact_path")
        if (
            not isinstance(generation_name, str)
            or Path(generation_name).name != generation_name
        ):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_METADATA_INVALID
            )
        generation_path = artifact_path.parent / generation_name
        generation_raw = _read_bytes(
            generation_path,
            CN_READ_MODEL_GENERATION_MISSING,
            CN_READ_MODEL_GENERATION_MISMATCH,
        )
        if (
            generation_raw != artifact_raw
            or hashlib.sha256(generation_raw).hexdigest()
            != metadata.get("generation_artifact_sha256")
        ):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_GENERATION_MISMATCH
            )

        payload = _json_object(
            artifact_raw, CN_READ_MODEL_ARTIFACT_INVALID
        )
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(payload)
        except (jsonschema.SchemaError, jsonschema.ValidationError) as error:
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_SCHEMA_MISMATCH
            ) from error
        try:
            validate_cn_operator_read_model_payload(
                payload, expected_head=current_head
            )
        except (TypeError, ValueError) as error:
            code = str(error)
            if "current_head" in code:
                blocker = CN_READ_MODEL_HEAD_MISMATCH
            elif "generation_hash" in code:
                blocker = CN_READ_MODEL_GENERATION_HASH_MISMATCH
            elif "input_hash" in code:
                blocker = CN_READ_MODEL_INPUT_HASH_MISMATCH
            else:
                blocker = CN_READ_MODEL_ARTIFACT_INVALID
            raise CNEquityReadModelUnavailable(blocker) from error
        if payload.get("generation_hash") != metadata.get(
            "generation_hash"
        ):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_GENERATION_HASH_MISMATCH
            )
        if payload.get("input_sha256") != metadata.get("input_sha256"):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_INPUT_HASH_MISMATCH
            )
        generation_inputs = payload.get("generation_inputs")
        if (
            not isinstance(generation_inputs, Mapping)
            or cn_operator_generation_hash(generation_inputs)
            != metadata.get("generation_hash")
        ):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_GENERATION_HASH_MISMATCH
            )
        metadata_after = _read_bytes(
            metadata_path,
            CN_READ_MODEL_METADATA_MISSING,
            CN_READ_MODEL_METADATA_INVALID,
        )
        if metadata_after != metadata_raw:
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_METADATA_INVALID
            )
        return payload

    def _validate_metadata(
        self,
        metadata: Mapping[str, Any],
        *,
        artifact_path: Path,
        schema_path: Path,
        current_head: str,
        now: datetime,
    ) -> None:
        if (
            metadata.get("schema_version")
            != RUNTIME_METADATA_SCHEMA_VERSION
            or metadata.get("artifact_schema_version") != SCHEMA_VERSION
            or metadata.get("artifact_path") != artifact_path.name
            or metadata.get("schema_path") != SCHEMA_RELATIVE_PATH
            or metadata.get("immutable_generation") is not True
            or metadata.get("api_read_only") is not True
            or metadata.get("runtime_builder_enabled") is not False
        ):
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_METADATA_INVALID
            )
        for field_name in (
            "artifact_sha256",
            "generation_artifact_sha256",
            "generation_hash",
            "input_sha256",
            "schema_sha256",
        ):
            value = metadata.get(field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise CNEquityReadModelUnavailable(
                    CN_READ_MODEL_METADATA_INVALID
                )
        if metadata.get("code_commit") != current_head:
            raise CNEquityReadModelUnavailable(
                CN_READ_MODEL_HEAD_MISMATCH
            )
        generated = _parse_utc(
            metadata.get("generated_at_utc"),
            CN_READ_MODEL_METADATA_INVALID,
        )
        if generated > now:
            raise CNEquityReadModelUnavailable(CN_READ_MODEL_FUTURE)
        if now - generated > self.max_age:
            raise CNEquityReadModelUnavailable(CN_READ_MODEL_STALE)


def cn_equity_fail_closed_payload(blocker: str) -> dict[str, Any]:
    return {
        "schema_version": "cn_equity_operator_read_model_error_v1",
        "domain": "cn_equity",
        "status": "blocked",
        "decision": "fail_closed",
        "readiness_class": "quality_checked",
        "blockers": [
            {
                "code": blocker,
                "owner": "a_share_developer",
                "next_action": (
                    "materialize_and_validate_current_head_cn_read_model"
                ),
            }
        ],
        "safety": dict(SAFETY_FLAGS),
    }


__all__ = [
    "CNEquityReadModelService",
    "CNEquityReadModelUnavailable",
    "CN_READ_MODEL_ARTIFACT_MISSING",
    "CN_READ_MODEL_HEAD_MISMATCH",
    "CN_READ_MODEL_METADATA_MISSING",
    "CN_READ_MODEL_SCHEMA_MISMATCH",
    "cn_equity_fail_closed_payload",
]
