#!/usr/bin/env python3
"""Build the fail-closed CN paper-readiness closure report.

The builder runs only injected synthetic/recorded drills and rebuilds the
upstream CN current-HEAD gate in an isolated temporary output root.  Wrapper
success is deliberately separate from the always-fail-closed paper decision.
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

from quant_cn.paper import (  # noqa: E402
    PAPER_SAFETY_FLAGS,
    PaperDrillResult,
    build_offline_fixture,
    run_offline_paper_drill,
)
from scripts.build_cn_equity_current_head_gate_report import (  # noqa: E402
    SCHEMA_VERSION as CURRENT_GATE_SCHEMA_VERSION,
    build_cn_equity_current_head_gate,
)


SCHEMA_VERSION = "cn_equity_paper_readiness_closure_report_v1"
SCHEMA_PATH = Path(
    "schemas/cn_equity_paper_readiness_closure_report.schema.json"
)
ARTIFACT_PATH = Path(
    "artifacts/cn_equity_paper_readiness/latest/"
    "cn_equity_paper_readiness_closure_report.json"
)
LOCK_PATH = Path(
    "artifacts/cn_equity_paper_readiness/.closure-build.lock"
)
MAX_ARTIFACT_AGE = timedelta(hours=24)
G11_HANDOFF_PATH = Path(
    ".agent/handoffs/CN-V3-CURRENT-HEAD-GATE-01/"
    "integrated-cn-v3-current-head-gate-01-goal11-batch-01.json"
)
COMMITTED_INPUTS: tuple[Path, ...] = (
    Path("quant_cn/paper/__init__.py"),
    Path("quant_cn/paper/readiness.py"),
    Path("scripts/build_cn_equity_paper_readiness_closure_report.py"),
    SCHEMA_PATH,
    G11_HANDOFF_PATH,
)
DIRECT_ROOT_BLOCKERS: tuple[dict[str, str], ...] = (
    {
        "code": "cn_paper_offline_fixture_only",
        "owner": "a_share_developer",
        "next_action": "retain_offline_drills_as_contract_evidence_only",
        "source_layer": "paper",
    },
    {
        "code": "cn_paper_runtime_observation_missing",
        "owner": "paper_operations",
        "next_action": "produce_separately_authorized_runtime_observation",
        "source_layer": "paper",
    },
    {
        "code": "cn_paper_manual_approval_missing",
        "owner": "architect",
        "next_action": "review_current_head_external_evidence_before_authorization",
        "source_layer": "approval",
    },
    {
        "code": "paper_start_not_authorized",
        "owner": "paper_operations",
        "next_action": "keep_paper_start_locked",
        "source_layer": "approval",
    },
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CNPaperReadinessClosureError(RuntimeError):
    """Raised when closure evidence cannot be built or validated safely."""


def _canonical_bytes(value: Any) -> bytes:
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


def _hash_mapping(value: Mapping[str, str]) -> str:
    return _sha256_bytes(
        json.dumps(
            dict(sorted(value.items())),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _commit(value: object, field_name: str) -> str:
    text = str(value).strip().lower()
    if _COMMIT_RE.fullmatch(text) is None:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_commit_invalid:{field_name}"
        )
    return text


def _aware_utc(value: datetime | str, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise CNPaperReadinessClosureError(
                f"cn_paper_closure_timestamp_invalid:{field_name}"
            ) from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_timestamp_invalid:{field_name}"
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_timestamp_naive:{field_name}"
        )
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_head_unavailable"
        ) from error
    return _commit(result.stdout.strip(), "git_head")


def _git_blob_sha256(
    repo_root: Path,
    *,
    current_head: str,
    relative_path: Path,
) -> str:
    relative = relative_path.as_posix()
    try:
        result = subprocess.run(
            ["git", "show", f"{current_head}:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_committed_input_missing:{relative}"
        ) from error
    return _sha256_bytes(result.stdout)


def _validate_schema(payload: Mapping[str, Any], schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        ).validate(dict(payload))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        jsonschema.ValidationError,
        jsonschema.SchemaError,
    ) as error:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_schema_invalid:{error}"
        ) from error


def _assert_all_false(
    value: object,
    *,
    field_name: str,
) -> None:
    if not isinstance(value, Mapping) or not value:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_safety_invalid:{field_name}"
        )
    if any(type(flag) is not bool or flag for flag in value.values()):
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_unsafe_flag:{field_name}"
        )


def _validate_current_gate(
    gate: Mapping[str, Any],
    *,
    expected_head: str,
) -> None:
    if gate.get("schema_version") != CURRENT_GATE_SCHEMA_VERSION:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_schema_invalid"
        )
    if gate.get("source_head") != expected_head:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_head_mismatch"
        )
    if gate.get("freshness") != "current_head":
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_not_current"
        )
    if gate.get("decision") not in {
        "blocked_fail_closed",
        "manual_review_required",
    }:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_decision_invalid"
        )
    roots = gate.get("root_blockers")
    if not isinstance(roots, list):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_blockers_invalid"
        )
    codes: list[str] = []
    for item in roots:
        if not isinstance(item, Mapping):
            raise CNPaperReadinessClosureError(
                "cn_paper_closure_current_gate_blocker_invalid"
            )
        code = str(item.get("code", "")).strip()
        if not code:
            raise CNPaperReadinessClosureError(
                "cn_paper_closure_current_gate_blocker_code_missing"
            )
        codes.append(code)
    if len(codes) != len(set(codes)):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_blocker_duplicate"
        )
    if gate.get("root_blocker_count") != len(codes):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_blocker_count_mismatch"
        )
    if roots and gate.get("decision") != "blocked_fail_closed":
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_not_fail_closed"
        )
    _assert_all_false(
        gate.get("safety_flags"),
        field_name="current_head_gate",
    )


def _root_blockers(
    gate: Mapping[str, Any],
) -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in (*gate["root_blockers"], *DIRECT_ROOT_BLOCKERS):
        code = str(value.get("code", "")).strip()
        if code in seen:
            continue
        seen.add(code)
        roots.append(
            {
                "code": code,
                "owner": str(value.get("owner", "a_share_developer")).strip()
                or "a_share_developer",
                "next_action": str(
                    value.get(
                        "next_action",
                        f"resolve_cn_paper_readiness_blocker:{code}",
                    )
                ).strip(),
                "source_layer": str(
                    value.get("source_layer", "paper")
                ).strip()
                or "paper",
            }
        )
    return roots


def _dependency_statuses(codes: set[str]) -> dict[str, str]:
    groups = {
        "dataready": (
            "dataready",
            "manifest",
            "coverage",
            "common_date",
            "pit",
            "license",
            "listing",
            "delisting",
            "st_",
            "suspension",
            "corporate_action",
        ),
        "market_rules": (
            "market_rule",
            "board_lot",
            "price_limit",
            "sellability",
            "fee_schedule",
            "session_rule",
            "settlement_rule",
        ),
        "research_backtest": ("research", "backtest", "holdout"),
        "oms_ledger_replay": (
            "oms",
            "ledger",
            "replay",
            "reconciliation",
        ),
        "qmt_broker": ("qmt", "broker"),
        "manual_approval": ("approval", "paper_start"),
    }
    return {
        name: (
            "blocked"
            if any(
                any(token in code.lower() for token in tokens)
                for code in codes
            )
            else "quality_checked"
        )
        for name, tokens in groups.items()
    }


def compose_paper_readiness_closure_report(
    *,
    current_head: str,
    generated_at: datetime,
    current_gate: Mapping[str, Any],
    drills: Sequence[PaperDrillResult],
    committed_input_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Compose a deterministic closure report from already-validated inputs."""

    head = _commit(current_head, "current_head")
    now = _aware_utc(generated_at, "generated_at")
    _validate_current_gate(current_gate, expected_head=head)
    if {item.source_kind for item in drills} != {
        "synthetic_fixture",
        "recorded_fixture",
    }:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_both_fixture_kinds_required"
        )
    drill_payloads = [
        item.to_dict() for item in sorted(drills, key=lambda row: row.source_kind)
    ]
    for drill in drill_payloads:
        _assert_all_false(
            drill.get("safety_flags"),
            field_name=f"drill:{drill['source_kind']}",
        )
        if (
            drill.get("status") != "quality_checked"
            or drill.get("decision") != "quality_checked_offline_only"
            or drill.get("runtime_eligible") is not False
            or drill.get("paper_start_authorized") is not False
            or drill.get("promotion_eligible") is not False
        ):
            raise CNPaperReadinessClosureError(
                f"cn_paper_closure_drill_invalid:{drill['source_kind']}"
            )
    roots = _root_blockers(current_gate)
    codes = {item["code"] for item in roots}
    input_hashes = dict(committed_input_hashes)
    if any(_SHA256_RE.fullmatch(str(value)) is None for value in input_hashes.values()):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_input_hash_invalid"
        )
    input_hashes["inline:cn_current_head_gate"] = _sha256_bytes(
        _canonical_bytes(current_gate)
    )
    input_hashes["inline:offline_paper_drills"] = _sha256_bytes(
        _canonical_bytes(drill_payloads)
    )
    input_hashes = dict(sorted(input_hashes.items()))
    report = {
        "schema_version": SCHEMA_VERSION,
        "domain": "cn_equity",
        "generated_at_utc": _iso(now),
        "source_head": head,
        "data_version": str(current_gate.get("data_version", "blocked")).strip()
        or "blocked",
        "status": "blocked",
        "wrapper_status": "success",
        "decision": "blocked_fail_closed",
        "freshness": "current_head",
        "current_head_gate": {
            "schema_version": current_gate["schema_version"],
            "source_head": current_gate["source_head"],
            "status": current_gate["status"],
            "decision": current_gate["decision"],
            "freshness": current_gate["freshness"],
            "root_blocker_count": current_gate["root_blocker_count"],
            "input_set_sha256": current_gate["input_set_sha256"],
            "report_sha256": input_hashes["inline:cn_current_head_gate"],
        },
        "offline_drills": drill_payloads,
        "dependency_statuses": _dependency_statuses(codes),
        "input_hashes": input_hashes,
        "input_set_sha256": _hash_mapping(input_hashes),
        "root_blockers": roots,
        "root_blocker_count": len(roots),
        "readiness": {
            "offline_drills_quality_checked": True,
            "research_ready": False,
            "backtest_ready": False,
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
        },
        "paper_start_authorized": False,
        "promotion_eligible": False,
        "validation_checks": {
            "current_head_gate_valid": True,
            "current_head_gate_blocked": (
                current_gate["decision"] == "blocked_fail_closed"
            ),
            "both_fixture_modes_exercised": True,
            "pre_trade_risk_exercised": True,
            "partial_fill_exercised": True,
            "kill_switch_exercised": True,
            "restart_exercised": True,
            "reconciliation_clean_in_fixture": True,
            "replay_reconciled_in_fixture": True,
            "audit_chain_hashed": True,
            "all_safety_flags_false": True,
            "network_or_secret_used": False,
            "paper_queue_written": False,
            "qmt_sdk_imported": False,
            "private_or_order_endpoint_called": False,
            "real_order_submitted": False,
        },
        "safety_flags": dict(PAPER_SAFETY_FLAGS),
    }
    return report


@contextmanager
def _writer_lock(output_root: Path):
    path = output_root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise CNPaperReadinessClosureError(
            f"cn_paper_closure_writer_lock_conflict:{LOCK_PATH.as_posix()}"
        ) from error
    try:
        os.write(
            descriptor,
            _canonical_bytes(
                {
                    "schema_version": "cn_paper_closure_writer_lock_v1",
                    "pid": os.getpid(),
                }
            ),
        )
        os.close(descriptor)
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(
    path: Path,
    raw: bytes,
    *,
    before_publish: Callable[[], None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_bytes() if path.exists() else None
    temp_path: Path | None = None
    try:
        if before_publish is not None:
            before_publish()
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
        temp_path = None
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        raise


def validate_paper_readiness_closure(
    report: Mapping[str, Any],
    *,
    repo_root: Path,
    expected_head: str,
    evaluated_at: datetime,
    current_gate: Mapping[str, Any],
    drills: Sequence[PaperDrillResult],
    max_age: timedelta = MAX_ARTIFACT_AGE,
) -> None:
    root = repo_root.resolve()
    head = _commit(expected_head, "expected_head")
    _validate_schema(report, root / SCHEMA_PATH)
    if report.get("source_head") != head:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_head_mismatch"
        )
    generated = _aware_utc(
        report.get("generated_at_utc"),
        "report.generated_at_utc",
    )
    now = _aware_utc(evaluated_at, "evaluated_at")
    if generated > now + timedelta(minutes=5):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_generated_at_in_future"
        )
    if now - generated > max_age:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_artifact_stale"
        )
    _validate_current_gate(current_gate, expected_head=head)
    _assert_all_false(
        report.get("safety_flags"),
        field_name="closure",
    )
    if (
        report.get("status") != "blocked"
        or report.get("decision") != "blocked_fail_closed"
        or report.get("paper_start_authorized") is not False
        or report.get("promotion_eligible") is not False
    ):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_not_fail_closed"
        )
    roots = report.get("root_blockers")
    if not isinstance(roots, list) or not roots:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_root_blockers_missing"
        )
    codes = [str(item.get("code", "")) for item in roots]
    if len(codes) != len(set(codes)):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_root_blocker_duplicate"
        )
    if report.get("root_blocker_count") != len(codes):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_root_blocker_count_mismatch"
        )
    for required in {
        "cn_paper_offline_fixture_only",
        "cn_paper_runtime_observation_missing",
        "cn_paper_manual_approval_missing",
        "paper_start_not_authorized",
    }:
        if required not in codes:
            raise CNPaperReadinessClosureError(
                f"cn_paper_closure_required_blocker_missing:{required}"
            )
    input_hashes = report.get("input_hashes")
    if not isinstance(input_hashes, Mapping):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_input_hashes_invalid"
        )
    if report.get("input_set_sha256") != _hash_mapping(input_hashes):
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_input_set_hash_mismatch"
        )
    expected_gate_hash = _sha256_bytes(_canonical_bytes(current_gate))
    if input_hashes.get("inline:cn_current_head_gate") != expected_gate_hash:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_current_gate_hash_mismatch"
        )
    drill_payloads = [
        item.to_dict() for item in sorted(drills, key=lambda row: row.source_kind)
    ]
    expected_drill_hash = _sha256_bytes(_canonical_bytes(drill_payloads))
    if input_hashes.get("inline:offline_paper_drills") != expected_drill_hash:
        raise CNPaperReadinessClosureError(
            "cn_paper_closure_drill_hash_mismatch"
        )
    for relative in COMMITTED_INPUTS:
        expected = _git_blob_sha256(
            root,
            current_head=head,
            relative_path=relative,
        )
        if input_hashes.get(relative.as_posix()) != expected:
            raise CNPaperReadinessClosureError(
                f"cn_paper_closure_committed_input_hash_mismatch:"
                f"{relative.as_posix()}"
            )


def build_cn_equity_paper_readiness_closure(
    *,
    repo_root: Path,
    output_root: Path | None = None,
    current_head: str | None = None,
    generated_at: datetime | None = None,
    current_gate: Mapping[str, Any] | None = None,
    before_publish: Callable[[], None] | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = (output_root or root).resolve()
    head = _commit(current_head or _git_head(root), "current_head")
    now = _aware_utc(
        generated_at or datetime.now(timezone.utc),
        "generated_at",
    )
    with _writer_lock(output):
        if current_gate is None:
            with tempfile.TemporaryDirectory(
                prefix="cn-paper-closure-g11-"
            ) as temporary:
                gate = build_cn_equity_current_head_gate(
                    repo_root=root,
                    output_root=Path(temporary),
                    current_head=head,
                    generated_at=now,
                )
        else:
            gate = dict(current_gate)
        _validate_current_gate(gate, expected_head=head)
        drills = tuple(
            run_offline_paper_drill(
                build_offline_fixture(source_kind, fixed_clock=now)
            )
            for source_kind in ("synthetic_fixture", "recorded_fixture")
        )
        committed_hashes = {
            path.as_posix(): _git_blob_sha256(
                root,
                current_head=head,
                relative_path=path,
            )
            for path in COMMITTED_INPUTS
        }
        report = compose_paper_readiness_closure_report(
            current_head=head,
            generated_at=now,
            current_gate=gate,
            drills=drills,
            committed_input_hashes=committed_hashes,
        )
        _validate_schema(report, root / SCHEMA_PATH)
        validate_paper_readiness_closure(
            report,
            repo_root=root,
            expected_head=head,
            evaluated_at=now,
            current_gate=gate,
            drills=drills,
        )
        _atomic_write(
            output / ARTIFACT_PATH,
            _canonical_bytes(report),
            before_publish=before_publish,
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
        _aware_utc(args.generated_at, "generated_at")
        if args.generated_at
        else None
    )
    try:
        report = build_cn_equity_paper_readiness_closure(
            repo_root=args.repo_root,
            output_root=args.output_root,
            generated_at=generated_at,
        )
    except CNPaperReadinessClosureError as error:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "wrapper_status": "failed",
                    "decision": "blocked_fail_closed",
                    "error": str(error),
                    "paper_start_authorized": False,
                    "promotion_eligible": False,
                    "safety_flags": dict(PAPER_SAFETY_FLAGS),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "wrapper_status": report["wrapper_status"],
                "status": report["status"],
                "decision": report["decision"],
                "source_head": report["source_head"],
                "root_blocker_count": report["root_blocker_count"],
                "paper_start_authorized": report["paper_start_authorized"],
                "promotion_eligible": report["promotion_eligible"],
                "safety_flags": report["safety_flags"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
