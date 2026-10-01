from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_manual_paper_review_approval_report_v1"
RECORD_SCHEMA_VERSION = "btc_manual_paper_review_approval_record_v1"

DEFAULT_OUTPUT_DIR = Path("artifacts/btc_manual_paper_review_approval/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_manual_paper_review_approval_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_manual_paper_review_approval_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_PENDING_RECORD_PATH = DEFAULT_OUTPUT_DIR / "btc_manual_paper_review_approval_pending_record.json"
DEFAULT_RECORD_PATH = Path("configs/btc/paper_runtime/manual_paper_review_approval.json")
DEFAULT_PACKET_PATH = Path("artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json")

APPROVAL_SCOPE = "review_only_no_auto_paper_no_live"
APPROVAL_DECISION = "approve_review_only_no_auto_paper_no_live"


def build_btc_manual_paper_review_approval(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    approval_record_path: Path = DEFAULT_RECORD_PATH,
    reviewed_packet_path: Path = DEFAULT_PACKET_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    record_abs = _resolve(root, approval_record_path)
    packet_abs = _resolve(root, reviewed_packet_path)
    record = _read_json(record_abs)
    packet = _read_json(packet_abs)
    packet_hash = _packet_hash_summary(packet=packet, packet_path=packet_abs)
    current_code_commit = _git_commit()
    validation = _validate_record(
        record=record,
        record_path=record_abs,
        packet=packet,
        packet_path=packet_abs,
        packet_input_path=reviewed_packet_path,
        packet_sha256=str(packet_hash.get("sha256", "")),
        packet_file_sha256=str(packet_hash.get("file_sha256", "")),
        current_code_commit=current_code_commit,
        now=generated,
    )
    report_path = output / DEFAULT_REPORT_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    pending_record_path = output / DEFAULT_PENDING_RECORD_PATH.name
    pending_record = _pending_record(
        record=record,
        reviewed_packet_path=reviewed_packet_path,
        packet_hash=packet_hash,
        generated=generated,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "recorded_research_only" if validation["valid"] else "missing_or_invalid_research_only",
        "decision": (
            "btc_manual_paper_review_approval_recorded_review_only_no_auto_paper_no_live"
            if validation["valid"]
            else "btc_manual_paper_review_approval_missing_or_invalid_no_paper_no_live"
        ),
        "scope": "manual_review_approval_attestation_only_no_paper_no_live",
        "code_commit": current_code_commit,
        "input": {
            "approval_record_path": _portable_path(approval_record_path),
            "reviewed_packet_path": _portable_path(reviewed_packet_path),
        },
        "approval_record": _redacted_record_summary(record),
        "approval_hash_comparison": _approval_hash_comparison(record=record, packet_hash=packet_hash),
        "reviewed_packet": {
            "path": _portable_path(reviewed_packet_path),
            "exists": packet_abs.exists(),
            "sha256": packet_hash["sha256"],
            "file_sha256": packet_hash["file_sha256"],
            "hash_method": packet_hash["hash_method"],
            "hash_schema_version": packet_hash["hash_schema_version"],
            "schema_version": str(packet.get("schema_version", "")),
            "code_commit": str(packet.get("code_commit", "")),
            "source_code_commit_current_head_match": (
                str(packet.get("code_commit", "")) == current_code_commit
                if packet.get("code_commit") and current_code_commit
                else None
            ),
            "decision": str(packet.get("decision", "")),
            "status": str(packet.get("status", "")),
            "aggregation_batch_id": str(packet.get("aggregation_batch_id", "")),
            "packet_status": str(_nested(packet, "paper_candidate_packet", "packet_status") or ""),
            "paper_queue_write_allowed": bool(_nested(packet, "gate", "paper_queue_write_allowed")),
            "live_unlock_allowed": bool(_nested(packet, "gate", "live_unlock_allowed")),
        },
        "pending_review_only_approval_record": {
            "status": "not_required_current_record_valid" if validation["valid"] else "pending_signature_required_current_packet_hash",
            "path": _portable_path(pending_record_path),
            "reviewed_packet_path": pending_record["reviewed_packet_path"],
            "reviewed_packet_hash": pending_record["reviewed_packet_hash"],
            "reviewed_source_code_commit": pending_record["reviewed_source_code_commit"],
            "paper_queue_write_allowed": False,
            "paper_order_intake_allowed": False,
            "live_unlock_allowed": False,
            "note": "This draft is not a signature and cannot clear manual approval until a human reviewer completes it.",
        },
        "manual_approval_recorded": bool(validation["valid"]),
        "manual_review_missing_cleared": bool(validation["valid"]),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": validation["blockers"],
        "warnings": _warnings(validation["valid"], validation.get("warnings", [])),
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_manual_paper_review_approval_markdown(report))
    _write_json(safety_path, _safety_status(report))
    _write_json(pending_record_path, pending_record)
    return report


def render_btc_manual_paper_review_approval_markdown(report: Mapping[str, Any]) -> str:
    record = _mapping(report.get("approval_record"))
    packet = _mapping(report.get("reviewed_packet"))
    pending = _mapping(report.get("pending_review_only_approval_record"))
    gate = _mapping(report.get("gate"))
    blockers = _list(report.get("blockers"))
    lines = [
        "# BTC 人工 Paper Review Approval 记录",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- reviewer：`{record.get('reviewer')}`",
        f"- decision date：`{record.get('decision_date_utc')}`",
        f"- approval scope：`{record.get('approval_scope')}`",
        f"- expiry：`{record.get('expiry_utc')}`",
        f"- reviewed packet：`{packet.get('path')}`",
        f"- reviewed packet sha256：`{packet.get('sha256')}`",
        f"- reviewed packet hash method：`{packet.get('hash_method')}`",
        f"- reviewed packet file sha256：`{packet.get('file_sha256')}`",
        f"- 待签 approval record：`{pending.get('status')}` / `{pending.get('path')}`",
        f"- manual missing cleared：`{report.get('manual_review_missing_cleared')}`",
        f"- 写 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- paper 接单：`{gate.get('paper_order_intake_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 阻断项",
        "",
    ]
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "边界：本记录只能证明人工复核记录存在；不能写 paper 队列，不能自动打开 paper/live，不能替代 runtime current sample、风控、执行和数据 gate。",
        ]
    )
    return "\n".join(lines) + "\n"


def _validate_record(
    *,
    record: Mapping[str, Any],
    record_path: Path,
    packet: Mapping[str, Any],
    packet_path: Path,
    packet_input_path: Path,
    packet_sha256: str,
    packet_file_sha256: str,
    current_code_commit: str,
    now: datetime,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if not record:
        blockers.append("btc_manual_paper_review_approval_record_missing")
    if not record_path.exists():
        blockers.append("btc_manual_paper_review_approval_record_file_missing")
    if not packet:
        blockers.append("btc_manual_paper_review_approval_packet_missing_or_invalid")
    if not packet_path.exists():
        blockers.append("btc_manual_paper_review_approval_packet_file_missing")
    if str(record.get("schema_version", "")) != RECORD_SCHEMA_VERSION:
        blockers.append("btc_manual_paper_review_approval_record_schema_invalid")
    if not str(record.get("reviewer", "")).strip():
        blockers.append("btc_manual_paper_review_approval_reviewer_missing")
    if not _parse_utc(record.get("decision_date_utc")):
        blockers.append("btc_manual_paper_review_approval_decision_date_invalid")
    expiry = _parse_utc(record.get("expiry_utc"))
    if not expiry:
        blockers.append("btc_manual_paper_review_approval_expiry_invalid")
    elif expiry <= now:
        blockers.append("btc_manual_paper_review_approval_expired")
    if str(record.get("approval_scope", "")) != APPROVAL_SCOPE:
        blockers.append("btc_manual_paper_review_approval_scope_invalid")
    if str(record.get("decision", "")) != APPROVAL_DECISION:
        blockers.append("btc_manual_paper_review_approval_decision_invalid")
    if record.get("approve_review_only_no_auto_paper_no_live") is not True:
        blockers.append("btc_manual_paper_review_approval_explicit_review_only_flag_missing")
    reviewed_artifacts = _list(record.get("reviewed_artifacts"))
    normalized_reviewed = {_portable_path(item) for item in reviewed_artifacts}
    accepted_packet_paths = {
        _portable_path(packet_input_path),
        _portable_path(packet_path),
        packet_path.as_posix(),
    }
    record_packet_path = _portable_path(record.get("reviewed_packet_path", ""))
    if record_packet_path not in accepted_packet_paths:
        blockers.append("btc_manual_paper_review_approval_reviewed_packet_path_mismatch")
    if not (normalized_reviewed & accepted_packet_paths) and record_packet_path not in normalized_reviewed:
        blockers.append("btc_manual_paper_review_approval_reviewed_packet_not_listed")
    record_hash = _record_packet_hash(record)
    if not packet_sha256:
        blockers.append("btc_manual_paper_review_approval_packet_sha256_missing")
    elif record_hash["sha256"] != packet_sha256:
        blockers.append("btc_manual_paper_review_approval_packet_sha256_mismatch")
    if record_hash["file_sha256"] and packet_file_sha256 and record_hash["file_sha256"] != packet_file_sha256:
        warnings.append("btc_manual_paper_review_approval_packet_file_sha256_changed_non_blocking")
    packet_code_commit = str(packet.get("code_commit") or "")
    record_code_commit = str(record.get("reviewed_source_code_commit") or "")
    if packet_code_commit:
        if not record_code_commit:
            blockers.append("btc_manual_paper_review_approval_review_only_stale_code_version")
        elif record_code_commit != packet_code_commit:
            blockers.append("btc_manual_paper_review_approval_review_only_stale_code_version")
    if record.get("paper_queue_write_allowed") is not False:
        blockers.append("btc_manual_paper_review_approval_paper_queue_flag_not_false")
    if record.get("paper_order_intake_allowed") is not False:
        blockers.append("btc_manual_paper_review_approval_paper_order_intake_flag_not_false")
    if record.get("live_unlock_allowed") is not False:
        blockers.append("btc_manual_paper_review_approval_live_unlock_flag_not_false")
    if _nested(packet, "gate", "paper_queue_write_allowed") is True:
        blockers.append("btc_manual_paper_review_approval_packet_has_paper_queue_true")
    if _nested(packet, "gate", "live_unlock_allowed") is True:
        blockers.append("btc_manual_paper_review_approval_packet_has_live_unlock_true")
    return {"valid": not blockers, "blockers": sorted(set(blockers)), "warnings": sorted(set(warnings))}


def _redacted_record_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    record_hash = _record_packet_hash(record)
    return {
        "schema_version": str(record.get("schema_version", "")),
        "reviewer": str(record.get("reviewer", "")),
        "decision_date_utc": str(record.get("decision_date_utc", "")),
        "approval_scope": str(record.get("approval_scope", "")),
        "expiry_utc": str(record.get("expiry_utc", "")),
        "decision": str(record.get("decision", "")),
        "reviewed_packet_path": str(record.get("reviewed_packet_path", "")),
        "reviewed_packet_sha256": record_hash["sha256"],
        "reviewed_packet_hash": record_hash,
        "reviewed_source_code_commit": str(record.get("reviewed_source_code_commit", "")),
        "reviewed_artifact_count": len(_list(record.get("reviewed_artifacts"))),
        "approve_review_only_no_auto_paper_no_live": record.get("approve_review_only_no_auto_paper_no_live") is True,
        "paper_queue_write_allowed": record.get("paper_queue_write_allowed") is True,
        "paper_order_intake_allowed": record.get("paper_order_intake_allowed") is True,
        "live_unlock_allowed": record.get("live_unlock_allowed") is True,
    }


def _record_packet_hash(record: Mapping[str, Any]) -> dict[str, str]:
    reviewed_hash = _mapping(record.get("reviewed_packet_hash"))
    sha256 = str(reviewed_hash.get("sha256") or record.get("reviewed_packet_sha256") or "").strip()
    file_sha256 = str(reviewed_hash.get("file_sha256") or record.get("reviewed_packet_file_sha256") or "").strip()
    return {
        "schema_version": str(reviewed_hash.get("schema_version") or ""),
        "hash_method": str(reviewed_hash.get("hash_method") or ("legacy_reviewed_packet_sha256" if sha256 else "")),
        "sha256": sha256,
        "file_sha256": file_sha256,
    }


def _approval_hash_comparison(*, record: Mapping[str, Any], packet_hash: Mapping[str, Any]) -> dict[str, Any]:
    record_hash = _record_packet_hash(record)
    current_sha = str(packet_hash.get("sha256") or "")
    current_file_sha = str(packet_hash.get("file_sha256") or "")
    return {
        "schema_version": "btc_manual_paper_review_approval_hash_comparison_v1",
        "comparison_key": "reviewed_packet_hash.sha256",
        "record_reviewed_packet_sha256": record_hash["sha256"],
        "current_packet_reviewed_hash_sha256": current_sha,
        "record_file_sha256": record_hash["file_sha256"],
        "current_packet_file_sha256": current_file_sha,
        "record_reviewed_source_code_commit": str(record.get("reviewed_source_code_commit") or ""),
        "current_packet_source_code_commit": str(_mapping(packet_hash).get("code_commit") or ""),
        "canonical_hash_matches": bool(current_sha and record_hash["sha256"] == current_sha),
        "file_hash_matches": (
            True
            if not record_hash["file_sha256"] or not current_file_sha
            else record_hash["file_sha256"] == current_file_sha
        ),
        "old_approval_auto_invalidated": bool(current_sha and record_hash["sha256"] and record_hash["sha256"] != current_sha),
    }


def _pending_record(
    *,
    record: Mapping[str, Any],
    reviewed_packet_path: Path,
    packet_hash: Mapping[str, Any],
    generated: datetime,
) -> dict[str, Any]:
    reviewer = str(record.get("reviewer") or "<human reviewer id or operator handle>")
    expiry = str(record.get("expiry_utc") or "YYYY-MM-DDTHH:MM:SSZ")
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_status": "pending_human_signature_current_packet_hash",
        "reviewer": reviewer,
        "decision_date_utc": "YYYY-MM-DDTHH:MM:SSZ",
        "approval_scope": APPROVAL_SCOPE,
        "expiry_utc": expiry,
        "reviewed_artifacts": [_portable_path(reviewed_packet_path)],
        "reviewed_packet_path": _portable_path(reviewed_packet_path),
        "reviewed_packet_sha256": str(packet_hash.get("sha256") or ""),
        "reviewed_packet_file_sha256": str(packet_hash.get("file_sha256") or ""),
        "reviewed_packet_hash": {
            "schema_version": str(packet_hash.get("hash_schema_version") or ""),
            "hash_method": str(packet_hash.get("hash_method") or ""),
            "sha256": str(packet_hash.get("sha256") or ""),
            "file_sha256": str(packet_hash.get("file_sha256") or ""),
        },
        "reviewed_source_code_commit": str(packet_hash.get("code_commit") or ""),
        "decision": APPROVAL_DECISION,
        "approve_review_only_no_auto_paper_no_live": True,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "generated_at_utc": generated.isoformat(),
        "notes": "Unsigned draft. Do not put API keys, secrets, passphrases, account numbers, or private endpoint output here.",
    }


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "manual_review_approval_record_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "read_only_validation_only": True,
        "approval_does_not_unlock_paper": True,
        "approval_does_not_unlock_live": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }


def _warnings(valid: bool, validation_warnings: Sequence[str] = ()) -> list[str]:
    warnings = ["manual_approval_record_is_not_paper_or_live_permission"]
    warnings.extend(str(item) for item in validation_warnings if str(item))
    if not valid:
        warnings.append("manual_approval_missing_keeps_gate_fail_closed")
    return warnings


def _packet_hash_summary(*, packet: Mapping[str, Any], packet_path: Path) -> dict[str, str]:
    file_sha256 = _sha256(packet_path) if packet_path.exists() else ""
    reviewed_hash = _mapping(packet.get("reviewed_packet_hash"))
    code_commit = str(packet.get("code_commit") or "")
    stable_sha256 = str(reviewed_hash.get("sha256", "") or "").strip()
    if _is_sha256(stable_sha256):
        return {
            "sha256": stable_sha256,
            "file_sha256": file_sha256,
            "hash_method": str(reviewed_hash.get("hash_method", "") or "stable_reviewed_packet_hash"),
            "hash_schema_version": str(reviewed_hash.get("schema_version", "") or ""),
            "code_commit": code_commit,
        }
    return {
        "sha256": file_sha256,
        "file_sha256": file_sha256,
        "hash_method": "legacy_file_sha256",
        "hash_schema_version": "",
        "code_commit": code_commit,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_manual_paper_review_approval_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "manual_approval_recorded": report.get("manual_approval_recorded") is True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
