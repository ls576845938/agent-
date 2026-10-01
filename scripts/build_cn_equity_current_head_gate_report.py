#!/usr/bin/env python3
"""Build the serialized, fail-closed CN current-HEAD gate DAG.

The builder consumes only the committed handoffs used by the CN operator
read-model contract.  It does not read ``latest`` market data, use the
network, inspect secrets, call a broker, or write a paper queue.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_cn.operations.read_model import (  # noqa: E402
    validate_cn_operator_read_model_payload,
)
from scripts.materialize_cn_current_head_read_model import (  # noqa: E402
    build_current_head_read_model,
)


SCHEMA_VERSION = "cn_equity_current_head_gate_report_v1"
STAGE_SCHEMA_VERSION = "cn_equity_gate_stage_report_v1"
STAGE_SCHEMA = Path("schemas/cn_equity_gate_stage_report.schema.json")
FINAL_SCHEMA = Path("schemas/cn_equity_current_head_gate_report.schema.json")
FINAL_ARTIFACT = Path(
    "artifacts/cn_equity_current_head_gate/latest/"
    "cn_equity_current_head_gate_report.json"
)
LOCK_PATH = Path("artifacts/cn_equity_current_head_gate/.build.lock")
MAX_ARTIFACT_AGE = timedelta(hours=24)

STAGE_ORDER: tuple[str, ...] = (
    "dataready",
    "market_rules",
    "research_backtest",
    "risk_oms_ledger",
    "replay",
    "qmt_broker",
    "paper_readiness",
)

STAGE_ARTIFACTS: Mapping[str, Path] = {
    "dataready": Path(
        "artifacts/cn_equity_dataready_gate/latest/"
        "cn_equity_dataready_gate_report.json"
    ),
    "market_rules": Path(
        "artifacts/cn_equity_market_rules_gate/latest/"
        "cn_equity_market_rules_gate_report.json"
    ),
    "research_backtest": Path(
        "artifacts/cn_equity_research_backtest_gate/latest/"
        "cn_equity_research_backtest_gate_report.json"
    ),
    "risk_oms_ledger": Path(
        "artifacts/cn_equity_risk_oms_ledger_gate/latest/"
        "cn_equity_risk_oms_ledger_gate_report.json"
    ),
    "replay": Path(
        "artifacts/cn_equity_replay_gate/latest/"
        "cn_equity_replay_gate_report.json"
    ),
    "qmt_broker": Path(
        "artifacts/cn_equity_qmt_broker_gate/latest/"
        "cn_equity_qmt_broker_gate_report.json"
    ),
    "paper_readiness": Path(
        "artifacts/cn_equity_paper_readiness/latest/"
        "cn_equity_paper_readiness_report.json"
    ),
}

STAGE_SOURCE_LAYERS: Mapping[str, tuple[str, ...]] = {
    "dataready": ("data",),
    "market_rules": ("market_rules",),
    "research_backtest": ("backtest",),
    "risk_oms_ledger": ("oms",),
    "replay": ("replay",),
    "qmt_broker": ("qmt",),
    "paper_readiness": (),
}

SAFETY_FLAGS: Mapping[str, bool] = {
    "promotion_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "private_endpoint_allowed": False,
    "order_endpoint_allowed": False,
    "broker_access_allowed": False,
    "withdraw_allowed": False,
    "demo_allowed": False,
    "paper_queue_allowed": False,
    "real_order_allowed": False,
    "network_allowed": False,
    "secret_access_allowed": False,
    "qmt_sdk_allowed": False,
}

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SELF_REFERENCE_PREFIXES = (
    "cn_equity_current_head_gate_report_",
    "cn_equity_gate_report_",
    "cn_equity_paper_readiness_report_",
    "derived:",
)

StageHook = Callable[[str], None]


class CNCurrentHeadGateError(RuntimeError):
    """Raised when a fail-closed gate contract cannot be produced safely."""


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


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise CNCurrentHeadGateError(
            f"cn_gate_input_unreadable:{path.as_posix()}"
        ) from error


def _hash_mapping(value: Mapping[str, str]) -> str:
    return _sha256_bytes(
        json.dumps(
            dict(sorted(value.items())),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _utc_datetime(value: datetime | str, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise CNCurrentHeadGateError(
                f"cn_gate_timestamp_invalid:{field_name}"
            ) from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise CNCurrentHeadGateError(
            f"cn_gate_timestamp_invalid:{field_name}"
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CNCurrentHeadGateError(
            f"cn_gate_timestamp_naive:{field_name}"
        )
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _commit(value: object, field_name: str) -> str:
    text = str(value).lower()
    if _COMMIT_RE.fullmatch(text) is None:
        raise CNCurrentHeadGateError(
            f"cn_gate_commit_invalid:{field_name}"
        )
    return text


def _git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CNCurrentHeadGateError(
            "cn_gate_current_head_unavailable"
        ) from error
    return _commit(result.stdout.strip(), "git_head")


def _git_blob_sha256(
    repo_root: Path,
    *,
    current_head: str,
    relative_path: str,
) -> str:
    try:
        result = subprocess.run(
            ["git", "show", f"{current_head}:{relative_path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CNCurrentHeadGateError(
            f"cn_gate_committed_input_missing:{relative_path}"
        ) from error
    return _sha256_bytes(result.stdout)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CNCurrentHeadGateError(
            f"cn_gate_json_invalid:{path.as_posix()}"
        ) from error
    if not isinstance(payload, dict):
        raise CNCurrentHeadGateError(
            f"cn_gate_json_object_required:{path.as_posix()}"
        )
    return payload


def _validate_schema(
    payload: Mapping[str, Any],
    *,
    schema_path: Path,
) -> None:
    schema = _read_json(schema_path)
    try:
        jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        ).validate(dict(payload))
    except jsonschema.ValidationError as error:
        location = "/".join(str(item) for item in error.absolute_path)
        raise CNCurrentHeadGateError(
            f"cn_gate_schema_invalid:{schema_path.name}:{location}:"
            f"{error.message}"
        ) from error


def _assert_all_false(
    value: object,
    *,
    field_name: str,
) -> None:
    if not isinstance(value, Mapping):
        raise CNCurrentHeadGateError(
            f"cn_gate_safety_mapping_required:{field_name}"
        )
    if not value or any(item is not False for item in value.values()):
        raise CNCurrentHeadGateError(
            f"cn_gate_unsafe_flag:{field_name}"
        )


def _is_self_reference(code: str) -> bool:
    lowered = code.lower()
    return (
        lowered == "domain_read_model_missing"
        or lowered.startswith("classification:")
        or lowered.startswith(_SELF_REFERENCE_PREFIXES)
    )


def _classify_blocker_stage(code: str, source_layer: str) -> str:
    lowered = code.lower()
    if any(token in lowered for token in ("qmt", "broker")):
        return "qmt_broker"
    if "replay" in lowered:
        return "replay"
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
        return "market_rules"
    if any(
        token in lowered
        for token in (
            "backtest",
            "research",
            "holdout",
            "fixture_research",
        )
    ):
        return "research_backtest"
    if any(
        token in lowered
        for token in (
            "promotion",
            "paper",
            "manual_approval",
        )
    ):
        return "paper_readiness"
    if any(
        token in lowered
        for token in (
            "oms",
            "ledger",
            "fill_",
            "position_",
            "cash_",
            "reconciliation",
        )
    ):
        return "risk_oms_ledger"
    if any(
        token in lowered
        for token in (
            "dataready",
            "data_",
            "manifest",
            "pilot",
            "coverage",
            "common_date",
            "pit",
            "license",
            "listing",
            "delisting",
            "risk_warning",
            "suspension",
            "corporate_action",
            "adjustment",
        )
    ):
        return "dataready"
    return {
        "data": "dataready",
        "market_rules": "market_rules",
        "backtest": "research_backtest",
        "oms": "risk_oms_ledger",
        "replay": "replay",
        "qmt": "qmt_broker",
        "gate": "paper_readiness",
    }.get(source_layer, "paper_readiness")


def extract_root_blockers(
    operator_payload: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    """Collapse the read-model blockers to unique, non-self root causes."""

    raw = operator_payload.get("blockers")
    if not isinstance(raw, list):
        raise CNCurrentHeadGateError("cn_gate_operator_blockers_invalid")
    roots: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, Mapping):
            raise CNCurrentHeadGateError(
                "cn_gate_operator_blocker_invalid"
            )
        code = str(value.get("code", "")).strip()
        if not code or _is_self_reference(code) or code in seen:
            continue
        seen.add(code)
        source_layer = str(value.get("layer", "gate")).strip() or "gate"
        roots.append(
            {
                "code": code,
                "owner": str(value.get("owner", "a_share_developer")).strip()
                or "a_share_developer",
                "next_action": str(
                    value.get(
                        "next_action",
                        f"resolve_cn_gate_root_blocker:{code}",
                    )
                ).strip(),
                "source_layer": source_layer,
                "detail": str(
                    value.get("detail", f"source=cn_operator_read_model:{code}")
                ).strip(),
                "stage_id": _classify_blocker_stage(code, source_layer),
            }
        )
    if operator_payload.get("status") == "blocked" and not roots:
        roots.append(
            {
                "code": "cn_operator_read_model_blocked_without_root_cause",
                "owner": "a_share_developer",
                "next_action": (
                    "repair_current_head_cn_operator_root_blocker_contract"
                ),
                "source_layer": "gate",
                "detail": "blocked operator read model had no usable root blocker",
                "stage_id": "paper_readiness",
            }
        )
    return tuple(roots)


def _validate_operator_payload(
    payload: Mapping[str, Any],
    *,
    current_head: str,
) -> None:
    try:
        validate_cn_operator_read_model_payload(
            payload,
            expected_head=current_head,
        )
    except (TypeError, ValueError) as error:
        raise CNCurrentHeadGateError(
            f"cn_gate_operator_contract_invalid:{error}"
        ) from error
    _assert_all_false(
        payload.get("safety"),
        field_name="operator_read_model",
    )


def _source_evidence(
    operator_payload: Mapping[str, Any],
    *,
    stage_id: str,
) -> list[dict[str, str]]:
    allowed = set(STAGE_SOURCE_LAYERS[stage_id])
    raw = operator_payload.get("evidence")
    if not isinstance(raw, list):
        raise CNCurrentHeadGateError("cn_gate_operator_evidence_invalid")
    rows: list[dict[str, str]] = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise CNCurrentHeadGateError(
                "cn_gate_operator_evidence_row_invalid"
            )
        layer = str(value.get("layer", ""))
        if layer not in allowed:
            continue
        sha256 = str(value.get("sha256", "")).lower()
        if _HASH_RE.fullmatch(sha256) is None:
            raise CNCurrentHeadGateError(
                f"cn_gate_evidence_hash_invalid:{layer}"
            )
        rows.append(
            {
                "layer": layer,
                "event_id": str(value.get("event_id", "")),
                "path": str(value.get("path", "")).replace("\\", "/"),
                "sha256": sha256,
                "deliverable_commit": _commit(
                    value.get("deliverable_commit"),
                    f"{layer}.deliverable_commit",
                ),
            }
        )
    return rows


def _stage_payload(
    *,
    stage_id: str,
    ordinal: int,
    current_head: str,
    generated_at: datetime,
    data_version: str,
    operator_payload: Mapping[str, Any],
    operator_sha256: str,
    stage_schema_sha256: str,
    roots: Sequence[Mapping[str, str]],
    inherited_codes: Sequence[str],
    dependency: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_evidence = _source_evidence(
        operator_payload,
        stage_id=stage_id,
    )
    own_roots = [
        {
            "code": str(item["code"]),
            "owner": str(item["owner"]),
            "next_action": str(item["next_action"]),
            "source_layer": str(item["source_layer"]),
            "detail": str(item["detail"]),
        }
        for item in roots
        if item["stage_id"] == stage_id
    ]
    own_codes = [item["code"] for item in own_roots]
    inherited = list(dict.fromkeys(str(item) for item in inherited_codes))
    effective = list(dict.fromkeys([*inherited, *own_codes]))
    dependencies: list[dict[str, Any]] = []
    input_hashes = {
        "inline:cn_operator_read_model": operator_sha256,
        STAGE_SCHEMA.as_posix(): stage_schema_sha256,
    }
    for item in source_evidence:
        input_hashes[item["path"]] = item["sha256"]
    if dependency is not None:
        dependencies.append(dict(dependency))
        input_hashes[str(dependency["path"])] = str(dependency["sha256"])
    blocked = bool(effective)
    return {
        "schema_version": STAGE_SCHEMA_VERSION,
        "domain": "cn_equity",
        "stage_id": stage_id,
        "stage_ordinal": ordinal,
        "generated_at_utc": _iso(generated_at),
        "source_head": current_head,
        "data_version": data_version,
        "status": "blocked" if blocked else "quality_checked",
        "decision": (
            "blocked_fail_closed"
            if blocked
            else "manual_review_required"
        ),
        "freshness": "current_head",
        "readiness_class": "quality_checked",
        "source_evidence": source_evidence,
        "dependencies": dependencies,
        "input_hashes": dict(sorted(input_hashes.items())),
        "input_set_sha256": _hash_mapping(input_hashes),
        "root_blockers": own_roots,
        "inherited_blocker_codes": inherited,
        "effective_blocker_codes": effective,
        "root_blocker_count": len(own_roots),
        "effective_blocker_count": len(effective),
        "builder_contract": {
            "builder_id": f"build_cn_equity_{stage_id}_report",
            "read_only_inputs": True,
            "network_used": False,
            "secret_used": False,
            "paper_queue_written": False,
            "real_order_submitted": False,
        },
        "safety_flags": dict(SAFETY_FLAGS),
    }


def _stage_reference(
    *,
    stage_id: str,
    payload: Mapping[str, Any],
    raw: bytes,
) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "path": STAGE_ARTIFACTS[stage_id].as_posix(),
        "sha256": _sha256_bytes(raw),
        "source_head": payload["source_head"],
        "decision": payload["decision"],
    }


def _final_payload(
    *,
    current_head: str,
    generated_at: datetime,
    data_version: str,
    operator_sha256: str,
    stage_schema_sha256: str,
    final_schema_sha256: str,
    roots: Sequence[Mapping[str, str]],
    stage_payloads: Mapping[str, Mapping[str, Any]],
    stage_raw: Mapping[str, bytes],
) -> dict[str, Any]:
    stage_reports: dict[str, dict[str, Any]] = {}
    input_hashes = {
        "inline:cn_operator_read_model": operator_sha256,
        STAGE_SCHEMA.as_posix(): stage_schema_sha256,
        FINAL_SCHEMA.as_posix(): final_schema_sha256,
    }
    for stage_id in STAGE_ORDER:
        payload = stage_payloads[stage_id]
        path = STAGE_ARTIFACTS[stage_id].as_posix()
        sha256 = _sha256_bytes(stage_raw[stage_id])
        input_hashes[path] = sha256
        stage_reports[stage_id] = {
            "path": path,
            "sha256": sha256,
            "source_head": payload["source_head"],
            "generated_at_utc": payload["generated_at_utc"],
            "status": payload["status"],
            "decision": payload["decision"],
            "freshness": payload["freshness"],
            "input_set_sha256": payload["input_set_sha256"],
            "root_blocker_count": payload["root_blocker_count"],
            "effective_blocker_count": payload["effective_blocker_count"],
        }
    final_roots = [
        {
            "code": str(item["code"]),
            "owner": str(item["owner"]),
            "next_action": str(item["next_action"]),
            "source_layer": str(item["source_layer"]),
            "stage_id": str(item["stage_id"]),
        }
        for item in roots
    ]
    derived = [
        {
            "code": item["code"],
            "stage_ids": [
                stage_id
                for stage_id in STAGE_ORDER
                if item["code"]
                in stage_payloads[stage_id]["effective_blocker_codes"]
            ],
        }
        for item in final_roots
    ]
    blocked = bool(final_roots)
    return {
        "schema_version": SCHEMA_VERSION,
        "domain": "cn_equity",
        "generated_at_utc": _iso(generated_at),
        "source_head": current_head,
        "data_version": data_version,
        "status": "blocked" if blocked else "manual_review_required",
        "wrapper_status": "success",
        "decision": (
            "blocked_fail_closed"
            if blocked
            else "manual_review_required"
        ),
        "freshness": "current_head",
        "builder_order": list(STAGE_ORDER),
        "stage_reports": stage_reports,
        "input_hashes": dict(sorted(input_hashes.items())),
        "input_set_sha256": _hash_mapping(input_hashes),
        "root_blockers": final_roots,
        "root_blocker_count": len(final_roots),
        "derived_blocker_references": derived,
        "derived_reference_count": sum(
            len(item["stage_ids"]) for item in derived
        ),
        "validation_checks": {
            "single_writer_lock_held": True,
            "required_builder_order_preserved": True,
            "all_report_schemas_valid": True,
            "all_reports_current_head": True,
            "all_report_hashes_verified": True,
            "all_declared_input_hashes_verified": True,
            "all_safety_flags_false": True,
            "self_reference_blockers_filtered": True,
            "network_or_secret_used": False,
            "paper_queue_written": False,
            "real_order_submitted": False,
        },
        "readiness": {
            "quality_checked": True,
            "research_ready": False,
            "backtest_ready": False,
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
        },
        "safety_flags": dict(SAFETY_FLAGS),
    }


@contextmanager
def _writer_lock(output_root: Path):
    path = output_root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as error:
        raise CNCurrentHeadGateError(
            f"cn_gate_writer_lock_conflict:{LOCK_PATH.as_posix()}"
        ) from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema_version": "cn_equity_gate_writer_lock_v1",
                    "pid": os.getpid(),
                },
                handle,
                sort_keys=True,
            )
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


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


def _publish_transaction(
    outputs: Mapping[Path, bytes],
) -> None:
    previous: dict[Path, bytes | None] = {}
    written: list[Path] = []
    try:
        for path, raw in outputs.items():
            previous[path] = path.read_bytes() if path.exists() else None
            _atomic_write(path, raw)
            written.append(path)
    except OSError as error:
        for path in reversed(written):
            before = previous[path]
            try:
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write(path, before)
            except OSError:
                pass
        raise CNCurrentHeadGateError(
            "cn_gate_publication_rolled_back"
        ) from error


def _resolve_input_path(
    relative: str,
    *,
    repo_root: Path,
    output_root: Path,
) -> Path:
    path = Path(relative)
    if path.parts and path.parts[0] == "artifacts":
        return output_root / path
    return repo_root / path


def _verify_input_hash(
    relative: str,
    expected_sha256: str,
    *,
    repo_root: Path,
    output_root: Path,
    current_head: str,
) -> None:
    if relative.startswith(".agent/handoffs/"):
        actual = _git_blob_sha256(
            repo_root,
            current_head=current_head,
            relative_path=relative,
        )
    else:
        actual = _sha256_file(
            _resolve_input_path(
                relative,
                repo_root=repo_root,
                output_root=output_root,
            )
        )
    if actual != expected_sha256:
        raise CNCurrentHeadGateError(
            f"cn_gate_input_hash_mismatch:{relative}"
        )


def validate_gate_bundle(
    report: Mapping[str, Any],
    *,
    repo_root: Path,
    output_root: Path,
    expected_head: str,
    evaluated_at: datetime,
    operator_payload: Mapping[str, Any] | None = None,
    max_age: timedelta = MAX_ARTIFACT_AGE,
) -> None:
    """Validate schema, current-HEAD, hashes, freshness, and safety."""

    root = repo_root.resolve()
    output = output_root.resolve()
    expected = _commit(expected_head, "expected_head")
    _validate_schema(report, schema_path=root / FINAL_SCHEMA)
    if report.get("source_head") != expected:
        raise CNCurrentHeadGateError("cn_gate_current_head_mismatch")
    generated = _utc_datetime(
        report.get("generated_at_utc"),
        "report.generated_at_utc",
    )
    now = _utc_datetime(evaluated_at, "evaluated_at")
    if generated > now + timedelta(minutes=5):
        raise CNCurrentHeadGateError("cn_gate_generated_at_in_future")
    if now - generated > max_age:
        raise CNCurrentHeadGateError("cn_gate_artifact_stale")
    if tuple(report.get("builder_order", ())) != STAGE_ORDER:
        raise CNCurrentHeadGateError("cn_gate_builder_order_invalid")
    _assert_all_false(
        report.get("safety_flags"),
        field_name="current_head_gate",
    )
    input_hashes = report.get("input_hashes")
    if not isinstance(input_hashes, Mapping):
        raise CNCurrentHeadGateError("cn_gate_input_hashes_invalid")
    if report.get("input_set_sha256") != _hash_mapping(input_hashes):
        raise CNCurrentHeadGateError("cn_gate_input_set_hash_mismatch")
    if operator_payload is not None:
        expected_operator = _sha256_bytes(
            _canonical_bytes(operator_payload)
        )
        if (
            input_hashes.get("inline:cn_operator_read_model")
            != expected_operator
        ):
            raise CNCurrentHeadGateError(
                "cn_gate_operator_input_hash_mismatch"
            )
    for relative, expected_sha256 in input_hashes.items():
        if relative.startswith("inline:"):
            continue
        _verify_input_hash(
            relative,
            str(expected_sha256),
            repo_root=root,
            output_root=output,
            current_head=expected,
        )
    stage_reports = report.get("stage_reports")
    if not isinstance(stage_reports, Mapping):
        raise CNCurrentHeadGateError("cn_gate_stage_reports_invalid")
    for ordinal, stage_id in enumerate(STAGE_ORDER, start=1):
        record = stage_reports.get(stage_id)
        if not isinstance(record, Mapping):
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_record_missing:{stage_id}"
            )
        path = output / STAGE_ARTIFACTS[stage_id]
        raw = path.read_bytes()
        if _sha256_bytes(raw) != record.get("sha256"):
            raise CNCurrentHeadGateError(
                f"cn_gate_artifact_hash_mismatch:{stage_id}"
            )
        payload = _read_json(path)
        _validate_schema(payload, schema_path=root / STAGE_SCHEMA)
        if payload.get("stage_id") != stage_id:
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_identity_mismatch:{stage_id}"
            )
        if payload.get("stage_ordinal") != ordinal:
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_ordinal_mismatch:{stage_id}"
            )
        if payload.get("source_head") != expected:
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_head_mismatch:{stage_id}"
            )
        if payload.get("generated_at_utc") != report.get(
            "generated_at_utc"
        ):
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_timestamp_mismatch:{stage_id}"
            )
        _assert_all_false(
            payload.get("safety_flags"),
            field_name=stage_id,
        )
        stage_inputs = payload.get("input_hashes")
        if not isinstance(stage_inputs, Mapping):
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_input_hashes_invalid:{stage_id}"
            )
        if payload.get("input_set_sha256") != _hash_mapping(stage_inputs):
            raise CNCurrentHeadGateError(
                f"cn_gate_stage_input_set_hash_mismatch:{stage_id}"
            )
        for relative, expected_sha256 in stage_inputs.items():
            if relative.startswith("inline:"):
                continue
            try:
                _verify_input_hash(
                    relative,
                    str(expected_sha256),
                    repo_root=root,
                    output_root=output,
                    current_head=expected,
                )
            except CNCurrentHeadGateError as error:
                raise CNCurrentHeadGateError(
                    f"cn_gate_stage_input_hash_mismatch:"
                    f"{stage_id}:{relative}"
                ) from error
    roots = report.get("root_blockers")
    if not isinstance(roots, list):
        raise CNCurrentHeadGateError("cn_gate_root_blockers_invalid")
    codes = [str(item.get("code", "")) for item in roots]
    if len(codes) != len(set(codes)):
        raise CNCurrentHeadGateError("cn_gate_root_blocker_duplicate")
    if any(_is_self_reference(code) for code in codes):
        raise CNCurrentHeadGateError(
            "cn_gate_self_reference_blocker_present"
        )
    if report.get("root_blocker_count") != len(codes):
        raise CNCurrentHeadGateError(
            "cn_gate_root_blocker_count_mismatch"
        )
    if codes and (
        report.get("status") != "blocked"
        or report.get("decision") != "blocked_fail_closed"
    ):
        raise CNCurrentHeadGateError(
            "cn_gate_blockers_not_fail_closed"
        )
    if report.get("wrapper_status") != "success":
        raise CNCurrentHeadGateError("cn_gate_wrapper_status_invalid")


def build_cn_equity_current_head_gate(
    *,
    repo_root: Path,
    output_root: Path | None = None,
    current_head: str | None = None,
    generated_at: datetime | None = None,
    operator_payload: Mapping[str, Any] | None = None,
    stage_hook: StageHook | None = None,
    before_publish: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Build and atomically publish all seven stage reports and the summary."""

    root = repo_root.resolve()
    output = (output_root or root).resolve()
    head = _commit(
        current_head or _git_head(root),
        "current_head",
    )
    now = _utc_datetime(
        generated_at or datetime.now(timezone.utc),
        "generated_at",
    )
    with _writer_lock(output):
        operator = dict(
            operator_payload
            or build_current_head_read_model(
                repo_root=root,
                generated_at=now,
                current_head=head,
            )
        )
        _validate_operator_payload(operator, current_head=head)
        data_version = str(operator.get("data_version", "")).strip()
        if not data_version:
            raise CNCurrentHeadGateError(
                "cn_gate_data_version_missing"
            )
        operator_sha256 = _sha256_bytes(_canonical_bytes(operator))
        stage_schema_sha256 = _sha256_file(root / STAGE_SCHEMA)
        final_schema_sha256 = _sha256_file(root / FINAL_SCHEMA)
        roots = extract_root_blockers(operator)

        stage_payloads: dict[str, dict[str, Any]] = {}
        stage_raw: dict[str, bytes] = {}
        inherited_codes: list[str] = []
        dependency: dict[str, Any] | None = None
        for ordinal, stage_id in enumerate(STAGE_ORDER, start=1):
            payload = _stage_payload(
                stage_id=stage_id,
                ordinal=ordinal,
                current_head=head,
                generated_at=now,
                data_version=data_version,
                operator_payload=operator,
                operator_sha256=operator_sha256,
                stage_schema_sha256=stage_schema_sha256,
                roots=roots,
                inherited_codes=inherited_codes,
                dependency=dependency,
            )
            _validate_schema(payload, schema_path=root / STAGE_SCHEMA)
            raw = _canonical_bytes(payload)
            stage_payloads[stage_id] = payload
            stage_raw[stage_id] = raw
            dependency = _stage_reference(
                stage_id=stage_id,
                payload=payload,
                raw=raw,
            )
            inherited_codes = list(payload["effective_blocker_codes"])
            if stage_hook is not None:
                stage_hook(stage_id)

        report = _final_payload(
            current_head=head,
            generated_at=now,
            data_version=data_version,
            operator_sha256=operator_sha256,
            stage_schema_sha256=stage_schema_sha256,
            final_schema_sha256=final_schema_sha256,
            roots=roots,
            stage_payloads=stage_payloads,
            stage_raw=stage_raw,
        )
        _validate_schema(report, schema_path=root / FINAL_SCHEMA)
        _assert_all_false(
            report["safety_flags"],
            field_name="current_head_gate",
        )
        if before_publish is not None:
            before_publish()
        outputs = {
            output / STAGE_ARTIFACTS[stage_id]: stage_raw[stage_id]
            for stage_id in STAGE_ORDER
        }
        outputs[output / FINAL_ARTIFACT] = _canonical_bytes(report)
        _publish_transaction(outputs)
        validate_gate_bundle(
            report,
            repo_root=root,
            output_root=output,
            expected_head=head,
            evaluated_at=now,
            operator_payload=operator,
        )
        return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--generated-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generated_at = (
        _utc_datetime(args.generated_at, "generated_at")
        if args.generated_at
        else datetime.now(timezone.utc)
    )
    try:
        report = build_cn_equity_current_head_gate(
            repo_root=args.repo_root,
            output_root=args.output_root,
            generated_at=generated_at,
        )
        path = (
            (args.output_root or args.repo_root).resolve()
            / FINAL_ARTIFACT
        )
        print(
            json.dumps(
                {
                    "wrapper_status": report["wrapper_status"],
                    "status": report["status"],
                    "decision": report["decision"],
                    "source_head": report["source_head"],
                    "data_version": report["data_version"],
                    "root_blocker_count": report["root_blocker_count"],
                    "root_blockers": [
                        item["code"]
                        for item in report["root_blockers"]
                    ],
                    "artifact_path": FINAL_ARTIFACT.as_posix(),
                    "artifact_sha256": _sha256_file(path),
                    "safety_flags": report["safety_flags"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        CNCurrentHeadGateError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {
                    "wrapper_status": "failed",
                    "status": "blocked",
                    "decision": "blocked_fail_closed",
                    "blocker": str(error),
                    "artifact_written": False,
                    "safety_flags": dict(SAFETY_FLAGS),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
