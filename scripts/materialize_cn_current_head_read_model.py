"""Materialize the CN current-HEAD operator read model from committed handoffs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_cn.application.operations_ux import build_cn_operations_read_model
from quant_cn.operations.read_model import (
    ARTIFACT_RELATIVE_PATH,
    CNUpstreamEvidence,
    METADATA_RELATIVE_PATH,
    RUNTIME_METADATA_SCHEMA_VERSION,
    SCHEMA_RELATIVE_PATH,
    SCHEMA_VERSION,
    validate_cn_operator_read_model_payload,
)
from tools.agent_governance.handoff import (
    validate_handoff,
    validate_handoff_against_git,
)


UPSTREAM_HANDOFFS: tuple[tuple[str, str], ...] = (
    (
        "data",
        ".agent/handoffs/CN-V3-DATAREADY-CONSUMER-01/"
        "integrated-cn-v3-dataready-consumer-01-goal4-batch-01.json",
    ),
    (
        "market_rules",
        ".agent/handoffs/CN-V3-MARKET-RULE-CONSUMER-01/"
        "integrated-cn-v3-market-rule-consumer-01-goal5-batch-01.json",
    ),
    (
        "backtest",
        ".agent/handoffs/CN-V3-RESEARCH-BACKTEST-EVIDENCE-01/"
        "integrated-cn-v3-research-backtest-evidence-01-goal7-batch-01.json",
    ),
    (
        "oms",
        ".agent/handoffs/CN-V3-OMS-LEDGER-REPLAY-01/"
        "integrated-cn-v3-oms-ledger-replay-01-goal6-batch-01.json",
    ),
    (
        "replay",
        ".agent/handoffs/CN-V3-OMS-LEDGER-REPLAY-01/"
        "integrated-cn-v3-oms-ledger-replay-01-goal6-batch-01.json",
    ),
    (
        "qmt",
        ".agent/handoffs/CN-V3-QMT-OFFLINE-CONTRACT-01/"
        "integrated-cn-v3-qmt-offline-contract-01-goal8-batch-01.json",
    ),
)

LATEST_ARTIFACT_NAME = "cn_equity_operator_read_model.json"
RUNTIME_METADATA_NAME = "runtime_metadata.json"


class CNReadModelMaterializationError(RuntimeError):
    pass


def _git_bytes(repo_root: Path, spec: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", spec],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise CNReadModelMaterializationError(
            "cn_read_model_committed_input_missing"
        ) from error


def _git_text(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise CNReadModelMaterializationError(
            "cn_read_model_current_head_unavailable"
        ) from error


def _json_object(raw: bytes, blocker: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CNReadModelMaterializationError(blocker) from error
    if not isinstance(value, dict):
        raise CNReadModelMaterializationError(blocker)
    return value


def _aware(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise CNReadModelMaterializationError(
                f"cn_read_model_timestamp_invalid:{field_name}"
            ) from error
    else:
        raise CNReadModelMaterializationError(
            f"cn_read_model_timestamp_invalid:{field_name}"
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CNReadModelMaterializationError(
            f"cn_read_model_timestamp_naive:{field_name}"
        )
    return parsed.astimezone(timezone.utc)


def _readiness(payload: Mapping[str, Any]) -> str:
    declared = [
        str(item.get("readiness_class", ""))
        for item in payload.get("deliverables", ())
        if isinstance(item, Mapping)
    ]
    for value in (
        "quality_checked",
        "research_ready",
        "backtest_ready",
        "promotion_evidence_ready",
    ):
        if value in declared:
            return value
    return "quality_checked"


def _committed_evidence(
    *,
    repo_root: Path,
    current_head: str,
    layer: str,
    path: str,
) -> CNUpstreamEvidence:
    raw = _git_bytes(repo_root, f"{current_head}:{path}")
    payload = _json_object(raw, "cn_read_model_handoff_invalid_json")
    errors = [
        *validate_handoff(payload),
        *validate_handoff_against_git(payload, repo_root=repo_root),
    ]
    if errors:
        raise CNReadModelMaterializationError(
            "cn_read_model_handoff_invalid:" + ",".join(sorted(set(errors)))
        )
    if payload.get("event_type") != "integrated":
        raise CNReadModelMaterializationError(
            "cn_read_model_handoff_not_integrated"
        )
    if payload.get("domain") != "cn_equity":
        raise CNReadModelMaterializationError(
            "cn_read_model_handoff_domain_mismatch"
        )
    raw_blockers = tuple(str(item) for item in payload.get("blockers", ()))
    return CNUpstreamEvidence(
        layer=layer,
        event_id=str(payload["event_id"]),
        ticket_id=str(payload["ticket_id"]),
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        deliverable_commit=str(payload["deliverable_commit"]),
        created_at=_aware(payload["created_at"], "handoff.created_at"),
        readiness_class=_readiness(payload),
        gate_impact=str(payload["gate_impact"]),
        promotion_eligible=bool(payload["promotion_eligible"]),
        blockers=tuple(
            item for item in raw_blockers if not item.startswith("classification:")
        ),
        classifications=tuple(
            item for item in raw_blockers if item.startswith("classification:")
        ),
    )


def build_current_head_read_model(
    *,
    repo_root: Path,
    generated_at: datetime,
    current_head: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    head = current_head or _git_text(root, "rev-parse", "HEAD")
    evidence = tuple(
        _committed_evidence(
            repo_root=root,
            current_head=head,
            layer=layer,
            path=path,
        )
        for layer, path in UPSTREAM_HANDOFFS
    )
    model = build_cn_operations_read_model(
        upstream_evidence=evidence,
        current_head=head,
        generated_at=_aware(generated_at, "generated_at"),
        data_version="unavailable_until_current_main_dataready",
    )
    payload = model.to_dict()
    validate_cn_operator_read_model_payload(payload, expected_head=head)
    return payload


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _immutable_write(path: Path, raw: bytes) -> None:
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise CNReadModelMaterializationError(
                "cn_read_model_generation_read_failed"
            ) from error
        if existing != raw:
            raise CNReadModelMaterializationError(
                "cn_read_model_generation_immutable_conflict"
            )
        return
    _atomic_write(path, raw)


def materialize_current_head_read_model(
    *,
    repo_root: Path,
    output_dir: Path,
    generated_at: datetime,
    current_head: str | None = None,
) -> dict[str, str]:
    root = repo_root.resolve()
    payload = build_current_head_read_model(
        repo_root=root,
        generated_at=generated_at,
        current_head=current_head,
    )
    schema_raw = (root / SCHEMA_RELATIVE_PATH).read_bytes()
    artifact_raw = _canonical_bytes(payload)
    artifact_sha256 = hashlib.sha256(artifact_raw).hexdigest()
    generation_hash = str(payload["generation_hash"])
    generation_name = (
        f"cn_equity_operator_read_model.{generation_hash}.json"
    )
    generation_path = output_dir / generation_name
    latest_path = output_dir / LATEST_ARTIFACT_NAME
    metadata_path = output_dir / RUNTIME_METADATA_NAME
    _immutable_write(generation_path, artifact_raw)
    _atomic_write(latest_path, artifact_raw)
    metadata = {
        "schema_version": RUNTIME_METADATA_SCHEMA_VERSION,
        "artifact_schema_version": SCHEMA_VERSION,
        "artifact_path": LATEST_ARTIFACT_NAME,
        "generation_artifact_path": generation_name,
        "schema_path": SCHEMA_RELATIVE_PATH,
        "schema_sha256": hashlib.sha256(schema_raw).hexdigest(),
        "artifact_sha256": artifact_sha256,
        "generation_artifact_sha256": artifact_sha256,
        "generation_hash": generation_hash,
        "input_sha256": payload["input_sha256"],
        "code_commit": payload["code_commit"],
        "generated_at_utc": payload["generated_at_utc"],
        "immutable_generation": True,
        "api_read_only": True,
        "runtime_builder_enabled": False,
    }
    metadata_raw = _canonical_bytes(metadata)
    _atomic_write(metadata_path, metadata_raw)
    return {
        "artifact_path": latest_path.as_posix(),
        "artifact_sha256": artifact_sha256,
        "generation_artifact_path": generation_path.as_posix(),
        "generation_hash": generation_hash,
        "input_sha256": str(payload["input_sha256"]),
        "metadata_path": metadata_path.as_posix(),
        "metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
        "code_commit": str(payload["code_commit"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize the CN current-HEAD operator read model."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / Path(ARTIFACT_RELATIVE_PATH).parent,
    )
    parser.add_argument("--generated-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generated_at = (
        _aware(args.generated_at, "generated_at")
        if args.generated_at
        else datetime.now(timezone.utc)
    )
    try:
        result = materialize_current_head_read_model(
            repo_root=args.repo_root,
            output_dir=args.output_dir,
            generated_at=generated_at,
        )
    except (
        CNReadModelMaterializationError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blocker": str(error),
                    "artifact_written": False,
                    "safety_flags": {
                        "paper": False,
                        "live": False,
                        "private": False,
                        "order": False,
                        "promotion": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "materialized", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
