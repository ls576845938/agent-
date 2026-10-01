from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_paper_session_dry_run_manifest_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_paper_session_dry_run_manifest/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_session_dry_run_manifest_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_session_dry_run_manifest_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_PATHS = {
    "paper_candidate_packet": Path("artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"),
    "manual_paper_review_approval": Path(
        "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
    ),
    "paper_readiness": Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"),
    "promotion_gate_control": Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"),
    "kill_switch": Path("artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json"),
    "runtime_replay": Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json"),
    "account_attestation": Path(
        "artifacts/btc_exchange_runtime/latest/btc_paper_account_runtime_attestation_report.json"
    ),
    "dirty_worktree_boundary": Path(
        "artifacts/btc_dirty_worktree_boundary/latest/btc_dirty_worktree_boundary_report.json"
    ),
    "gate_report_consistency": Path(
        "artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json"
    ),
}

REBUILD_COMMANDS = {
    "gate_chain": "py scripts/build_btc_gate_aggregation_chain.py",
    "manual_approval_check": "py scripts/build_btc_manual_paper_review_approval.py",
    "current_packet_approval_check": "py scripts/sign_btc_current_packet_approval.py",
    "runtime_replay": "py scripts/build_btc_perpetual_paper_runtime_replay_report.py",
    "promotion_gate_control": "py scripts/research/build_btc_promotion_gate_control.py",
    "root_cause_ci": "py scripts/check_btc_promotion_gate_root_cause_ci.py",
    "paper_session_manifest": "py scripts/build_btc_paper_session_dry_run_manifest.py",
}


def build_btc_paper_session_dry_run_manifest(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    freshness_sla_hours: float = 24.0,
    source_paths: Mapping[str, Path] | None = None,
    ledger_root: Path = Path("data/paper_ledger/btc_paper_session_dry_run"),
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = dict(DEFAULT_PATHS)
    paths.update(source_paths or {})

    artifacts = {
        name: _artifact_status(name, _resolve(root, path), root=root, generated=generated, freshness_sla_hours=freshness_sla_hours)
        for name, path in paths.items()
    }
    checklist = _checklist(artifacts)
    blockers = _dedupe([blocker for item in checklist for blocker in _list_of_strings(item.get("blockers"))])
    ready = not blockers and all(item.get("passed") is True for item in checklist)
    report_path = output / DEFAULT_REPORT_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "dry_run_checklist_passed_research_only" if ready else "blocked_fail_closed_research_only",
        "decision": "btc_paper_session_dry_run_manifest_no_queue_no_live",
        "scope": "paper_session_start_checklist_only_no_paper_queue_no_broker",
        "code_commit": _git_commit(),
        "freshness_sla_hours": float(freshness_sla_hours),
        "required_artifacts": artifacts,
        "paper_start_checklist": checklist,
        "paper_start_checklist_passed": bool(ready),
        "start_command_enabled": False,
        "start_command": "",
        "rebuild_commands": REBUILD_COMMANDS,
        "ledger_output_manifest": _ledger_output_manifest(ledger_root),
        "rollback_steps": _rollback_steps(ledger_root),
        "operator_summary": _operator_summary(ready=ready, blockers=blockers, checklist=checklist),
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
        "blockers": blockers,
        "warnings": _warnings(ready=ready),
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_paper_session_dry_run_manifest_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_paper_session_dry_run_manifest_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC Paper Session Dry-run Manifest",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- checklist passed：`{report.get('paper_start_checklist_passed')}`",
        f"- 写 paper 队列：`{report.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{report.get('live_unlock_allowed')}`",
        "- 边界：只读启动清单，不写 paper queue，不接 broker/private/order。",
        "",
        "## Checklist",
        "",
        "| 项 | 通过 | 阻断 |",
        "|---|---:|---|",
    ]
    for item in report.get("paper_start_checklist", []):
        blockers = ", ".join(f"`{blocker}`" for blocker in _list_of_strings(_mapping(item).get("blockers"))) or "-"
        lines.append(f"| `{_mapping(item).get('check_id')}` | `{_mapping(item).get('passed')}` | {blockers} |")
    lines.extend(["", "## 下一步命令", ""])
    for name, command in _mapping(report.get("rebuild_commands")).items():
        lines.append(f"- `{name}`：`{command}`")
    lines.extend(["", "## 回滚步骤", ""])
    for step in report.get("rollback_steps", []):
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


def _artifact_status(
    name: str,
    path: Path,
    *,
    root: Path,
    generated: datetime,
    freshness_sla_hours: float,
) -> dict[str, Any]:
    payload = _read_json(path)
    generated_at = _timestamp_or_none(payload.get("generated_at_utc") or payload.get("generated_at") or payload.get("as_of_utc"))
    age_hours = None
    freshness_blockers: list[str] = []
    if not path.exists():
        freshness_blockers.append(f"paper_session_manifest:{name}:source_artifact_missing")
    elif generated_at is None:
        freshness_blockers.append(f"paper_session_manifest:{name}:source_generated_at_missing")
    else:
        age_hours = max(0.0, (generated - generated_at).total_seconds() / 3600.0)
        if age_hours > float(freshness_sla_hours):
            freshness_blockers.append(f"paper_session_manifest:{name}:source_artifact_stale_age_hours_gt_sla")
    return {
        "artifact_id": name,
        "path": _portable_path(path.relative_to(root) if _is_relative_to(path, root) else path),
        "exists": path.exists(),
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "generated_at_utc": generated_at.isoformat() if generated_at else "",
        "age_hours": round(age_hours, 6) if age_hours is not None else None,
        "blockers": _dedupe([*freshness_blockers, *[str(item) for item in payload.get("blockers", []) if str(item)]]),
        "payload": payload,
    }


def _checklist(artifacts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        _check("all_required_artifacts_present_and_fresh", _all_artifacts_fresh(artifacts)),
        _check("manual_review_approval_current", _manual_review_check(_payload(artifacts, "manual_paper_review_approval"))),
        _check("paper_candidate_packet_fail_closed", _packet_check(_payload(artifacts, "paper_candidate_packet"))),
        _check("account_attestation_current", _account_attestation_check(_payload(artifacts, "account_attestation"))),
        _check("paper_readiness_gate_passed", _paper_readiness_check(_payload(artifacts, "paper_readiness"))),
        _check("promotion_gate_control_passed", _promotion_check(_payload(artifacts, "promotion_gate_control"))),
        _check("kill_switch_clear_for_start", _kill_switch_check(_payload(artifacts, "kill_switch"))),
        _check("current_runtime_non_flat_gate_evidence_present", _runtime_replay_check(_payload(artifacts, "runtime_replay"))),
        _check("dirty_worktree_clean_or_reviewed", _dirty_worktree_check(_payload(artifacts, "dirty_worktree_boundary"))),
        _check("gate_report_consistency_passed", _consistency_check(_payload(artifacts, "gate_report_consistency"))),
    ]


def _check(check_id: str, blockers: Sequence[str]) -> dict[str, Any]:
    return {"check_id": check_id, "passed": not blockers, "blockers": list(blockers)}


def _all_artifacts_fresh(artifacts: Mapping[str, Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for name, artifact in artifacts.items():
        blockers.extend(
            item
            for item in _list_of_strings(artifact.get("blockers"))
            if item.startswith(f"paper_session_manifest:{name}:source_")
        )
    return _dedupe(blockers)


def _manual_review_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload.get("manual_approval_recorded") is not True:
        blockers.append("paper_session_manifest_manual_review_approval_not_recorded")
    if payload.get("manual_review_missing_cleared") is not True:
        blockers.append("paper_session_manifest_manual_review_missing_not_cleared")
    blockers.extend(f"manual_review:{item}" for item in _list_of_strings(payload.get("blockers")))
    if payload.get("paper_queue_write_allowed") is not False or payload.get("live_unlock_allowed") is not False:
        blockers.append("paper_session_manifest_manual_review_safety_flag_not_false")
    return _dedupe(blockers)


def _packet_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    gate = _mapping(payload.get("gate"))
    if gate.get("paper_queue_write_allowed") is True or gate.get("live_unlock_allowed") is True:
        blockers.append("paper_session_manifest_packet_safety_flag_true")
    if payload.get("private_endpoint_used") is True or payload.get("order_endpoint_used") is True:
        blockers.append("paper_session_manifest_packet_endpoint_flag_true")
    return blockers


def _account_attestation_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload.get("attestation_current") is not True:
        blockers.append("paper_session_manifest_account_attestation_not_current")
    if payload.get("credential_permissions_verified") is not True:
        blockers.append("paper_session_manifest_account_permissions_not_verified")
    if payload.get("credential_separation_verified") is not True:
        blockers.append("paper_session_manifest_account_key_separation_not_verified")
    blockers.extend(f"account_attestation:{item}" for item in _list_of_strings(payload.get("blockers")))
    return _dedupe(blockers)


def _paper_readiness_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if str(payload.get("status") or "") != "ready_for_paper_start":
        blockers.append("paper_session_manifest_paper_readiness_not_ready")
    if payload.get("paper_start_allowed") is not True:
        blockers.append("paper_session_manifest_paper_start_not_allowed")
    if payload.get("paper_execution_authorized") is not True:
        blockers.append("paper_session_manifest_paper_execution_not_authorized")
    blockers.extend(f"paper_readiness:{item}" for item in _list_of_strings(payload.get("blockers")))
    return _dedupe(blockers)


def _promotion_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload.get("blockers"):
        blockers.extend(f"promotion_gate:{item}" for item in _list_of_strings(payload.get("blockers"))[:20])
    status = str(payload.get("status") or "").lower()
    if status not in {"pass", "passed", "complete", "complete_research_only"}:
        blockers.append("paper_session_manifest_promotion_gate_not_passed")
    if payload.get("paper_queue_write_allowed") is True or payload.get("live_unlock_allowed") is True:
        blockers.append("paper_session_manifest_promotion_safety_flag_true")
    return _dedupe(blockers)


def _kill_switch_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    engaged = payload.get("engaged")
    if engaged is None:
        engaged = payload.get("kill_switch_engaged")
    if engaged is not False:
        blockers.append("paper_session_manifest_kill_switch_not_clear")
    blockers.extend(f"kill_switch:{item}" for item in _list_of_strings(payload.get("blockers")))
    return _dedupe(blockers)


def _runtime_replay_check(payload: Mapping[str, Any]) -> list[str]:
    summary = _mapping(payload.get("summary"))
    blockers: list[str] = []
    if summary.get("paper_runtime_gate_evidence") is not True:
        blockers.append("paper_session_manifest_current_gate_evidence_pending")
    if int(summary.get("gate_eligible_current_capture_count") or 0) <= 0:
        blockers.append("paper_session_manifest_current_non_flat_sample_missing")
    blockers.extend(f"runtime_replay:{item}" for item in _list_of_strings(payload.get("blockers")))
    return _dedupe(blockers)


def _dirty_worktree_check(payload: Mapping[str, Any]) -> list[str]:
    if str(payload.get("status") or "") == "clean_worktree":
        return []
    return ["paper_session_manifest_dirty_worktree_not_clean"]


def _consistency_check(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload.get("source_timeline_consistent") is not True and payload.get("timeline_consistent") is not True:
        blockers.append("paper_session_manifest_gate_report_timeline_not_consistent")
    blockers.extend(f"gate_consistency:{item}" for item in _list_of_strings(payload.get("blockers")))
    return _dedupe(blockers)


def _ledger_output_manifest(ledger_root: Path) -> dict[str, str]:
    root = _portable_path(ledger_root)
    return {
        "ledger_root": root,
        "order_ledger_path": f"{root}/order_ledger.csv",
        "fill_ledger_path": f"{root}/fill_ledger.csv",
        "cash_ledger_path": f"{root}/cash_ledger.csv",
        "funding_cashflow_path": f"{root}/funding_cashflow.csv",
        "reconciliation_report_path": f"{root}/reconciliation/session_reconciliation_report.json",
        "audit_lock_path": f"{root}/audit/btc_paper_session_start.lock.json",
    }


def _rollback_steps(ledger_root: Path) -> list[str]:
    return [
        "Do not delete or rewrite prior ledgers; stop before paper queue intake because this manifest is read-only.",
        f"If a dry-run artifact is stale, rebuild it with `{REBUILD_COMMANDS['gate_chain']}` and rerun this manifest.",
        f"If a test session directory was created manually, archive `{_portable_path(ledger_root)}` before another dry run.",
        "Keep kill switch engaged unless a separate audited checklist explicitly clears it; this report cannot clear it.",
    ]


def _operator_summary(*, ready: bool, blockers: Sequence[str], checklist: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failed = [item for item in checklist if item.get("passed") is not True]
    return {
        "current_stage": "paper_session_manifest_ready_for_manual_review" if ready else "paper_session_manifest_blocked",
        "unique_next_action": "do_not_start_paper_fix_first_failed_check" if failed else "manual_review_of_start_packet_only",
        "first_failed_check": failed[0]["check_id"] if failed else "",
        "blocked_reason_count": len(blockers),
        "forbidden_actions": [
            "do_not_write_paper_queue",
            "do_not_enable_live",
            "do_not_call_private_or_order_endpoint",
            "do_not_treat_fixture_drill_as_gate_evidence",
        ],
        "safety_bits": {
            "paper_queue_write_allowed": False,
            "paper_order_intake_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    }


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "dry_run_manifest_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
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
        "read_only_artifact_checklist": True,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _warnings(*, ready: bool) -> list[str]:
    warnings = ["paper_session_manifest_does_not_authorize_paper_or_live"]
    if ready:
        warnings.append("ready_status_requires_separate_manual_operator_review_before_any_start")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_session_dry_run_manifest_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "paper_start_checklist_passed": report.get("paper_start_checklist_passed") is True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _payload(artifacts: Mapping[str, Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    return _mapping(_mapping(artifacts.get(name)).get("payload"))


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


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp_or_none(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
