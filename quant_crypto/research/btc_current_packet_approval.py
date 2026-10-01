from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.btc_manual_paper_review_approval import (
    APPROVAL_DECISION,
    APPROVAL_SCOPE,
    DEFAULT_PACKET_PATH,
    DEFAULT_RECORD_PATH,
    RECORD_SCHEMA_VERSION,
    build_btc_manual_paper_review_approval,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_current_packet_approval_signer_report_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_manual_paper_review_approval/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_current_packet_approval_signer_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_current_packet_approval_signer_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_current_packet_approval_signer_safety_status.json"


def build_current_packet_approval_record(
    *,
    packet: Mapping[str, Any],
    reviewed_packet_path: Path = DEFAULT_PACKET_PATH,
    reviewer: str,
    decision_date_utc: datetime,
    expiry_utc: datetime,
    reviewed_artifacts: Sequence[Path | str] = (),
    packet_file_sha256: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    packet_hash = _mapping(packet.get("reviewed_packet_hash"))
    sha256 = str(packet_hash.get("sha256") or "").strip()
    packet_code_commit = str(packet.get("code_commit") or "")
    if not _is_sha256(sha256):
        raise ValueError("Current packet reviewed_packet_hash.sha256 is missing or invalid.")
    file_sha256 = str(packet_file_sha256 or packet_hash.get("file_sha256") or "")
    artifacts = [_portable_path(reviewed_packet_path)]
    for item in reviewed_artifacts:
        text = _portable_path(item)
        if text not in artifacts:
            artifacts.append(text)
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "reviewer": str(reviewer).strip(),
        "decision_date_utc": _ensure_utc(decision_date_utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "approval_scope": APPROVAL_SCOPE,
        "expiry_utc": _ensure_utc(expiry_utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reviewed_artifacts": artifacts,
        "reviewed_packet_path": _portable_path(reviewed_packet_path),
        "reviewed_packet_sha256": sha256,
        "reviewed_packet_file_sha256": file_sha256,
        "reviewed_packet_hash": {
            "schema_version": str(packet_hash.get("schema_version") or ""),
            "hash_method": str(packet_hash.get("hash_method") or ""),
            "sha256": sha256,
            "file_sha256": file_sha256,
        },
        "reviewed_source_code_commit": packet_code_commit,
        "decision": APPROVAL_DECISION,
        "approve_review_only_no_auto_paper_no_live": True,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "notes": notes or "Review-only approval for the current packet hash. No paper/live/order permission.",
    }


def build_btc_current_packet_approval_signer_report(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    approval_record_path: Path = DEFAULT_RECORD_PATH,
    reviewed_packet_path: Path = DEFAULT_PACKET_PATH,
    reviewer: str = "user_directed_review_only_record_2026_07_06",
    decision_date_utc: datetime | None = None,
    expiry_days: int = 14,
    write_record: bool = False,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    decision_date = _ensure_utc(decision_date_utc or generated)
    expiry = decision_date + timedelta(days=max(1, int(expiry_days)))
    packet_path = _resolve(root, reviewed_packet_path)
    record_path = _resolve(root, approval_record_path)
    packet = _read_json(packet_path)
    previous_record = _read_json(record_path)
    previous_hash = _current_record_hash(previous_record)
    current_hash = str(_mapping(packet.get("reviewed_packet_hash")).get("sha256") or "")

    blockers: list[str] = []
    if not packet_path.exists() or not packet:
        blockers.append("btc_current_packet_approval_packet_missing")
    if not _is_sha256(current_hash):
        blockers.append("btc_current_packet_approval_packet_hash_missing")
    if not str(reviewer).strip():
        blockers.append("btc_current_packet_approval_reviewer_missing")

    proposed_record: dict[str, Any] = {}
    if not blockers:
        proposed_record = build_current_packet_approval_record(
            packet=packet,
            reviewed_packet_path=reviewed_packet_path,
            reviewer=reviewer,
            decision_date_utc=decision_date,
            expiry_utc=expiry,
            reviewed_artifacts=(reviewed_packet_path,),
            packet_file_sha256=_sha256(packet_path) if packet_path.exists() else "",
            notes="Recorded from current packet approval signer/checker. Review-only; no paper/live/order permission.",
        )
        if write_record:
            _write_json(record_path, proposed_record)

    validation = build_btc_manual_paper_review_approval(
        repo_root=root,
        output_dir=output,
        approval_record_path=approval_record_path,
        reviewed_packet_path=reviewed_packet_path,
        generated_at_utc=generated,
        aggregation_batch_id=aggregation_batch_id,
    )
    report_path = output / DEFAULT_REPORT_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    current_recorded = validation.get("manual_approval_recorded") is True and not validation.get("blockers")
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "recorded_current_research_only" if current_recorded else "pending_or_invalid_research_only",
        "decision": (
            "btc_current_packet_approval_recorded_review_only_no_auto_paper_no_live"
            if current_recorded
            else "btc_current_packet_approval_pending_or_invalid_no_paper_no_live"
        ),
        "scope": "current_packet_approval_signer_checker_no_paper_no_live",
        "code_commit": _git_commit(),
        "write_record_requested": bool(write_record),
        "approval_record_path": _portable_path(approval_record_path),
        "reviewed_packet_path": _portable_path(reviewed_packet_path),
        "previous_record_reviewed_packet_sha256": previous_hash,
        "current_packet_reviewed_hash_sha256": current_hash,
        "previous_record_auto_invalidated": bool(previous_hash and current_hash and previous_hash != current_hash),
        "proposed_record": _redacted_record(proposed_record),
        "post_approval_gate": _post_approval_gate(current_recorded=current_recorded),
        "manual_approval_validation": {
            "status": validation.get("status"),
            "decision": validation.get("decision"),
            "manual_approval_recorded": validation.get("manual_approval_recorded") is True,
            "manual_review_missing_cleared": validation.get("manual_review_missing_cleared") is True,
            "blockers": list(validation.get("blockers", [])),
            "approval_hash_comparison": validation.get("approval_hash_comparison", {}),
        },
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
        "blockers": sorted(set(blockers + list(validation.get("blockers", [])))),
        "warnings": _warnings(write_record=write_record, current_recorded=current_recorded),
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_current_packet_approval_signer_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_current_packet_approval_signer_markdown(report: Mapping[str, Any]) -> str:
    validation = _mapping(report.get("manual_approval_validation"))
    lines = [
        "# BTC Current Packet Approval Signer/Checker",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 当前 packet hash：`{report.get('current_packet_reviewed_hash_sha256')}`",
        f"- 旧 approval hash：`{report.get('previous_record_reviewed_packet_sha256')}`",
        f"- 写入 record：`{report.get('write_record_requested')}`",
        f"- manual approval recorded：`{validation.get('manual_approval_recorded')}`",
        "- 边界：只签当前 reviewed_packet_hash.sha256；只解除人工复核缺失；不写 paper 队列，不解锁 live，不接 private/order。",
        "",
        "## Blockers",
        "",
    ]
    blockers = [str(item) for item in report.get("blockers", []) if str(item)]
    lines.extend(f"- `{item}`" for item in blockers) if blockers else lines.append("- 无")
    return "\n".join(lines) + "\n"


def _redacted_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    return {
        "schema_version": record.get("schema_version"),
        "reviewer": record.get("reviewer"),
        "decision_date_utc": record.get("decision_date_utc"),
        "approval_scope": record.get("approval_scope"),
        "expiry_utc": record.get("expiry_utc"),
        "reviewed_packet_path": record.get("reviewed_packet_path"),
        "reviewed_packet_hash": record.get("reviewed_packet_hash"),
        "reviewed_source_code_commit": record.get("reviewed_source_code_commit"),
        "decision": record.get("decision"),
        "approve_review_only_no_auto_paper_no_live": record.get("approve_review_only_no_auto_paper_no_live") is True,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
    }


def _current_record_hash(record: Mapping[str, Any]) -> str:
    reviewed_hash = _mapping(record.get("reviewed_packet_hash"))
    return str(reviewed_hash.get("sha256") or record.get("reviewed_packet_sha256") or "").strip()


def _post_approval_gate(*, current_recorded: bool) -> dict[str, Any]:
    return {
        "status": (
            "manual_review_recorded_but_promotion_gates_still_required"
            if current_recorded
            else "manual_review_not_current_or_not_recorded"
        ),
        "clears_only": ["manual_review_approval_missing"] if current_recorded else [],
        "does_not_clear": [
            "data_gate",
            "runtime_current_non_flat_sample_gate",
            "depth_slippage_fill_mapping_gate",
            "kill_switch_gate",
            "promotion_gate_control",
            "paper_start_manifest_gate",
            "live_unlock_gate",
        ],
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "operator_message": (
            "人工已审只表示当前 packet hash/commit 已被 review-only 记录；paper/live 仍必须由数据、样本、执行、风控和 promotion gate 逐项通过。"
            if current_recorded
            else "当前 packet 还没有有效 review-only 签核，旧签核或错误签核自动失效。"
        ),
    }


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "manual_review_approval_record_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "paper_candidate_created": False,
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
        "read_only_or_record_write_only": True,
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


def _warnings(*, write_record: bool, current_recorded: bool) -> list[str]:
    warnings = ["current_packet_approval_is_review_only_no_auto_paper_no_live"]
    if not write_record:
        warnings.append("dry_run_no_approval_record_written")
    if current_recorded:
        warnings.append("manual_review_missing_cleared_but_paper_live_still_blocked")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_current_packet_approval_signer_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "manual_approval_recorded": _mapping(report.get("manual_approval_validation")).get("manual_approval_recorded") is True,
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)
