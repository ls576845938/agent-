#!/usr/bin/env python3
"""Service rules for the US equity completion audit report.

The script entrypoint should only parse CLI arguments and call this module.
Completion phase classification, blocker extraction, and fail-closed guardrails
live here so they can be reused by monitoring/tests without shelling out.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_completion_audit_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_completion_audit_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 完成度审计.md")
DEFAULT_REPORT_PATHS = {
    "daily_line": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"),
    "completion_dependency": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_completion_dependency_report.json"),
    "operator_unblock": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_operator_unblock_packet.json"),
    "strategy_card": Path("../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 主候选策略卡.md"),
    "forward_roll": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
    "forward_state": Path("data/forward_observation/us_etf_rotation_v1/validation_state.json"),
    "data_freshness": Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json"),
    "kline_quality": Path("artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json"),
    "fred_preflight": Path("artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json"),
    "pit_status": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json"),
    "pit_procurement_readiness": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json"),
    "strategy_validation": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
    "strategy_validation_evidence_audit": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json"),
    "portfolio_promotion": Path("artifacts/us_equity_portfolio/latest/portfolio_promotion_evidence_report.json"),
    "forward_evaluation": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"),
    "small_account_preflight": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"),
    "manual_decision_record": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json"),
    "manual_review_packet": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json"),
    "paper_simulation_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json"),
    "paper_simulation_roll": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json"),
    "paper_simulation_evaluation": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json"),
    "execution_drill_evidence": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json"),
    "broker_credentials_review": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json"),
    "broker_credentials_handoff": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json"),
    "daily_monitoring": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_daily_monitoring_report.json"),
    "strategy_registry": Path("artifacts/us_equity_strategy_registry/latest/us_equity_strategy_registry_report.json"),
    "live_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json"),
    "risk_constitution": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json"),
}


def build_us_equity_completion_audit_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    report_paths: Mapping[str, Path] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = dict(DEFAULT_REPORT_PATHS)
    if report_paths:
        paths.update(report_paths)
    reports = {name: _read_source(_resolve(root, path), root) for name, path in paths.items()}
    phases = _phase_rows(reports)
    complete = sum(1 for item in phases if item["status"] == "complete")
    blocked = sum(1 for item in phases if item["status"] == "blocked")
    in_progress = sum(1 for item in phases if item["status"] == "in_progress")
    first_incomplete = next((item for item in phases if item["status"] != "complete"), {})
    first_incomplete_blockers = _list_of_str(first_incomplete.get("blockers"))
    operator_summary = _mapping(_payload(reports, "operator_unblock").get("summary"))
    dependency_summary = _mapping(_payload(reports, "completion_dependency").get("summary"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "completion_blocked" if blocked else ("completion_in_progress" if in_progress else "completion_complete"),
        "allowed_statuses": ["completion_blocked", "completion_in_progress", "completion_complete"],
        "decision": "continue_fail_closed_until_all_phases_complete",
        "summary": {
            "phase_count": len(phases),
            "complete_count": complete,
            "in_progress_count": in_progress,
            "blocked_count": blocked,
            "first_incomplete_phase_id": str(first_incomplete.get("phase_id", "")),
            "first_incomplete_phase_status": str(first_incomplete.get("status", "")),
            "first_blocker": first_incomplete_blockers[0] if first_incomplete_blockers else "",
            "next_action": str(first_incomplete.get("next_action", "")),
            "operator_open_input_count": _int(operator_summary.get("open_count")),
            "operator_external_input_count": _int(operator_summary.get("external_input_count")),
            "operator_manual_input_count": _int(operator_summary.get("manual_input_count")),
            "operator_natural_time_count": _int(operator_summary.get("natural_time_count")),
            "completion_dependency_blocked_count": _int(dependency_summary.get("blocked_count")),
            "completion_claim_allowed": blocked == 0 and in_progress == 0,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
        },
        "phases": phases,
        "blockers": _dedupe(blocker for phase in phases for blocker in _list_of_str(phase.get("blockers"))),
        "source_reports": {name: source["path"] for name, source in reports.items()},
        "guardrails": {
            "audit_only": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _phase_rows(reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        _phase(
            "phase_0_candidate_freeze",
            "Freeze current candidate definition",
            _exists(reports, "strategy_card")
            and _status(reports, "forward_roll") in {"PASS", "SKIPPED_ALREADY_COMPLETED"}
            and _exists(reports, "forward_state"),
            ["strategy_card", "forward_roll", "forward_state"],
            _missing(["strategy_card", "forward_roll", "forward_state"], reports),
            "Keep candidate ID fixed during observation.",
        ),
        _phase(
            "phase_1_data_hardening",
            "Data freshness, quality, PIT and macro release hardening",
            _status(reports, "data_freshness") == "pass"
            and _status(reports, "kline_quality") in {"pass", "warn"}
            and _status(reports, "fred_preflight") in {"fred_macro_preflight_pass", "fred_macro_preflight_warn"}
            and _status(reports, "pit_procurement_readiness") == "pit_procurement_ready_for_manual_license_review"
            and _status(reports, "pit_status") == "production_pit_data_intake_ready",
            ["data_freshness", "kline_quality", "fred_preflight", "pit_procurement_readiness", "pit_status"],
            _data_blockers(reports),
            "Acquire licensed PIT bundle and keep daily data gates passing.",
        ),
        _phase(
            "phase_2_strategy_validation_gate",
            "Dedicated strategy validation gate",
            _status(reports, "strategy_validation") == "validation_passed_for_forward_observation"
            and _status(reports, "strategy_validation_evidence_audit") == "validation_evidence_audit_ready_for_forward_observation",
            ["strategy_validation", "strategy_validation_evidence_audit"],
            _strategy_validation_blockers(reports),
            "Rerun strategy validation after production PIT/data-lineage blockers clear.",
        ),
        _phase(
            "phase_3_forward_observation_evaluation",
            "Forward observation 30/60/90 day evaluation",
            _status(reports, "forward_evaluation") == "forward_complete_for_manual_review",
            ["forward_evaluation"],
            _source_blockers(reports, "forward_evaluation", ["forward_observation_not_complete"]),
            "Continue daily production line until minimum observation window completes.",
        ),
        _phase(
            "phase_4_portfolio_promotion_evidence",
            "Portfolio promotion evidence and construction controls",
            _status(reports, "portfolio_promotion") == "portfolio_promotion_evidence_pass",
            ["portfolio_promotion"],
            _source_blockers(reports, "portfolio_promotion", ["portfolio_promotion_evidence_not_passed"]),
            "Rebuild portfolio promotion evidence after strategy validation, event-ledger, ledger PnL, construction controls, cost stress, and walk-forward evidence are available.",
        ),
        _phase(
            "phase_5_small_account_execution_constraints",
            "Small-account sizing, financing and execution constraints",
            _status(reports, "small_account_preflight") == "pass_observation_only",
            ["small_account_preflight"],
            _source_blockers(reports, "small_account_preflight", ["small_account_execution_preflight_not_passed"]),
            "Keep 1.5x as research cap; require preflight before paper/live.",
        ),
        _phase(
            "phase_6_manual_review_and_decision_record",
            "Manual review packet and traceable decision record",
            _status(reports, "manual_review_packet") == "manual_review_ready"
            and _nested(_payload(reports, "manual_review_packet"), "guardrails.manual_approval_recorded", False) is True
            and _status(reports, "manual_decision_record") == "manual_decision_record_valid"
            and _nested(_payload(reports, "manual_decision_record"), "record_summary.decision", "") == "paper_simulation_review_candidate"
            and _nested(_payload(reports, "manual_decision_record"), "guardrails.paper_simulation_allowed", True) is False
            and _nested(_payload(reports, "manual_decision_record"), "guardrails.live_order_allowed", True) is False,
            ["manual_review_packet", "manual_decision_record"],
            _manual_review_blockers(reports),
            "Keep manual review pending until validation, 30-day forward evidence, traceable decision record, and remediation tickets are complete.",
        ),
        _phase(
            "phase_7_paper_simulation_ledger",
            "Independent paper simulation ledger and reconciliation",
            _status(reports, "paper_simulation_readiness") == "paper_simulation_ready_for_manual_start"
            and _status(reports, "paper_simulation_roll") == "PASS"
            and _status(reports, "paper_simulation_evaluation") == "paper_simulation_complete_for_manual_review"
            and _nested(_payload(reports, "paper_simulation_roll"), "guardrails.live_order_allowed", True) is False
            and _nested(_payload(reports, "paper_simulation_evaluation"), "guardrails.live_order_allowed", True) is False,
            ["paper_simulation_readiness", "paper_simulation_roll", "paper_simulation_evaluation"],
            _paper_simulation_blockers(reports),
            "Run independent paper simulation only after manual review readiness and manual start approval; keep live locked.",
        ),
        _phase(
            "phase_8_execution_and_broker_safety",
            "Execution drills and broker credential metadata review",
            _status(reports, "execution_drill_evidence") == "execution_drill_evidence_complete"
            and _status(reports, "broker_credentials_review") == "broker_credentials_review_proven"
            and _nested(_payload(reports, "execution_drill_evidence"), "guardrails.live_order_allowed", True) is False
            and _nested(_payload(reports, "broker_credentials_review"), "guardrails.live_order_allowed", True) is False
            and _nested(_payload(reports, "broker_credentials_review"), "guardrails.order_endpoint_allowed", True) is False,
            ["execution_drill_evidence", "broker_credentials_review", "broker_credentials_handoff"],
            _execution_broker_blockers(reports),
            "Record metadata-only broker credential review and keep execution drills complete with all live/order flags false.",
        ),
        _phase(
            "phase_9_monitoring_replay_incident",
            "Monitoring, replay diff, incident template and operator queue",
            _status(reports, "daily_monitoring") == "daily_monitoring_clear",
            ["daily_monitoring"],
            _source_blockers(reports, "daily_monitoring", ["daily_monitoring_not_clear"]),
            "Keep daily monitoring blocked until every gate has owner, reason, next action, evidence path, and no open queue items.",
        ),
        _phase(
            "phase_10_strategy_registry_expansion",
            "Strategy registry and expansion queue",
            _status(reports, "strategy_registry") == "pass",
            ["strategy_registry"],
            _source_blockers(reports, "strategy_registry", ["strategy_registry_not_passed"]),
            "New strategies must enter registry before formal validation.",
        ),
        _phase(
            "phase_11_paper_live_readiness",
            "Paper/live readiness, risk constitution and execution evidence",
            _status(reports, "manual_review_packet") == "manual_review_ready"
            and _status(reports, "paper_simulation_evaluation") == "paper_simulation_complete_for_manual_review"
            and _status(reports, "broker_credentials_review") == "broker_credentials_review_proven"
            and _status(reports, "live_readiness") == "live_readiness_ready_for_manual_review"
            and _status(reports, "risk_constitution") == "live_readiness_ready_for_manual_review",
            ["manual_review_packet", "paper_simulation_evaluation", "broker_credentials_review", "live_readiness", "risk_constitution"],
            _live_blockers(reports),
            "Keep paper/live locked until validation, paper, broker review, and manual sign-off complete.",
        ),
    ]


def _phase(
    phase_id: str,
    title: str,
    passed: bool,
    evidence_reports: list[str],
    blockers: list[str],
    next_action: str,
) -> dict[str, Any]:
    if passed:
        status = "complete"
    elif phase_id == "phase_3_forward_observation_evaluation" and any(
        "less_than" in item or item == "forward_observation_not_complete" for item in blockers
    ):
        status = "in_progress"
    elif any(
        "blocked" in item
        or "missing" in item
        or "pit" in item
        or "not_passed" in item
        or "not_ready" in item
        or "not_complete" in item
        or "queue_open" in item
        or "not_recorded" in item
        or "not_approved" in item
        or "not_valid" in item
        for item in blockers
    ):
        status = "blocked"
    elif any("less_than" in item or "not_complete" in item for item in blockers):
        status = "in_progress"
    else:
        status = "in_progress"
    return {
        "phase_id": phase_id,
        "title": title,
        "status": status,
        "passed": bool(passed),
        "evidence_reports": evidence_reports,
        "blockers": [] if passed else _dedupe(blockers),
        "next_action": "" if passed else next_action,
    }


def _data_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    expected = {
        "data_freshness": {"pass"},
        "kline_quality": {"pass", "warn"},
        "fred_preflight": {"fred_macro_preflight_pass", "fred_macro_preflight_warn"},
        "pit_procurement_readiness": {"pit_procurement_ready_for_manual_license_review"},
        "pit_status": {"production_pit_data_intake_ready"},
    }
    for name, ok_statuses in expected.items():
        if _status(reports, name) in ok_statuses:
            continue
        blockers.extend(_source_blockers(reports, name, [f"{name}_not_ready"]))
    return blockers


def _live_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        [
            *_source_blockers_unless_status(reports, "manual_review_packet", {"manual_review_ready"}, ["manual_review_packet_not_ready"]),
            *_source_blockers_unless_status(
                reports,
                "paper_simulation_evaluation",
                {"paper_simulation_complete_for_manual_review"},
                ["paper_simulation_evaluation_not_complete"],
            ),
            *_source_blockers_unless_status(
                reports,
                "broker_credentials_review",
                {"broker_credentials_review_proven"},
                ["broker_credentials_review_not_proven"],
            ),
            *_source_blockers_unless_status(reports, "live_readiness", {"live_readiness_ready_for_manual_review"}, ["live_readiness_not_ready"]),
            *_source_blockers_unless_status(reports, "risk_constitution", {"live_readiness_ready_for_manual_review"}, ["risk_constitution_not_ready"]),
        ]
    )


def _manual_review_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    blockers = [
        *_source_blockers_unless_status(reports, "manual_review_packet", {"manual_review_ready"}, ["manual_review_packet_not_ready"]),
        *_source_blockers_unless_status(
            reports,
            "manual_decision_record",
            {"manual_decision_record_valid"},
            ["manual_decision_record_not_valid"],
        ),
    ]
    if _status(reports, "manual_decision_record") == "manual_decision_record_valid" and _nested(
        _payload(reports, "manual_decision_record"), "record_summary.decision", ""
    ) != "paper_simulation_review_candidate":
        blockers.append("manual_decision_record_not_paper_candidate")
    return _dedupe(blockers)


def _paper_simulation_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        [
            *_source_blockers_unless_status(
                reports,
                "paper_simulation_readiness",
                {"paper_simulation_ready_for_manual_start"},
                ["paper_simulation_readiness_not_ready"],
            ),
            *_source_blockers_unless_status(reports, "paper_simulation_roll", {"PASS"}, ["paper_simulation_roll_not_passed"]),
            *_source_blockers_unless_status(
                reports,
                "paper_simulation_evaluation",
                {"paper_simulation_complete_for_manual_review"},
                ["paper_simulation_evaluation_not_complete"],
            ),
        ]
    )


def _execution_broker_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return _dedupe(
        [
            *_source_blockers_unless_status(
                reports,
                "execution_drill_evidence",
                {"execution_drill_evidence_complete"},
                ["execution_drill_evidence_not_complete"],
            ),
            *_source_blockers_unless_status(
                reports,
                "broker_credentials_review",
                {"broker_credentials_review_proven"},
                ["broker_credentials_review_not_proven"],
            ),
            *_source_blockers_unless_status(
                reports,
                "broker_credentials_handoff",
                {"broker_credentials_handoff_ready_for_manual_review"},
                ["broker_credentials_handoff_not_ready"],
            ),
        ]
    )


def _strategy_validation_blockers(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    blockers = [
        *_source_blockers(reports, "strategy_validation", ["strategy_validation_not_passed"]),
        *_source_blockers(reports, "strategy_validation_evidence_audit", ["strategy_validation_evidence_audit_not_ready"]),
    ]
    audit_payload = _payload(reports, "strategy_validation_evidence_audit")
    incomplete = _list_of_str(audit_payload.get("incomplete_requirements"))
    blockers.extend(f"strategy_validation_requirement_incomplete:{item}" for item in incomplete)
    return _dedupe(blockers)


def _source_blockers(reports: Mapping[str, Mapping[str, Any]], name: str, fallback: list[str]) -> list[str]:
    source = reports.get(name, {})
    if not source.get("exists"):
        return [f"{name}_missing"]
    payload = _mapping(source.get("payload"))
    return _list_of_str(payload.get("blockers")) or fallback


def _source_blockers_unless_status(
    reports: Mapping[str, Mapping[str, Any]],
    name: str,
    ok_statuses: set[str],
    fallback: list[str],
) -> list[str]:
    if _status(reports, name) in ok_statuses:
        return []
    return _source_blockers(reports, name, fallback)


def _missing(names: list[str], reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [f"{name}_missing" for name in names if not reports.get(name, {}).get("exists")]


def _exists(reports: Mapping[str, Mapping[str, Any]], name: str) -> bool:
    return reports.get(name, {}).get("exists") is True


def _status(reports: Mapping[str, Mapping[str, Any]], name: str) -> str:
    return str(_payload(reports, name).get("status", ""))


def _payload(reports: Mapping[str, Mapping[str, Any]], name: str) -> dict[str, Any]:
    return _mapping(reports.get(name, {}).get("payload"))


def _read_source(path: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relpath(path, root), "exists": False, "payload": {}}
    if path.suffix.lower() == ".json":
        try:
            return {"path": _relpath(path, root), "exists": True, "payload": json.loads(path.read_text(encoding="utf-8"))}
        except Exception as exc:  # noqa: BLE001
            return {"path": _relpath(path, root), "exists": True, "payload": {"status": "unreadable", "blockers": [type(exc).__name__]}}
    return {"path": _relpath(path, root), "exists": True, "payload": {"status": "present"}}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 完成度审计",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- complete: `{_nested(payload, 'summary.complete_count')}` / `{_nested(payload, 'summary.phase_count')}`",
        f"- blocked: `{_nested(payload, 'summary.blocked_count')}`",
        f"- first incomplete phase: `{_nested(payload, 'summary.first_incomplete_phase_id')}`",
        f"- first blocker: `{_nested(payload, 'summary.first_blocker')}`",
        f"- operator inputs open: `{_nested(payload, 'summary.operator_open_input_count')}` "
        f"(external `{_nested(payload, 'summary.operator_external_input_count')}`, "
        f"manual `{_nested(payload, 'summary.operator_manual_input_count')}`, "
        f"natural time `{_nested(payload, 'summary.operator_natural_time_count')}`)",
        f"- completion_claim_allowed: `{_nested(payload, 'summary.completion_claim_allowed')}`",
        f"- paper_simulation_allowed: `{_nested(payload, 'summary.paper_simulation_allowed')}`",
        f"- live_order_allowed: `{_nested(payload, 'summary.live_order_allowed')}`",
        "",
        "| phase | status | first blocker | next action |",
        "| --- | --- | --- | --- |",
    ]
    for phase in _list(payload.get("phases")):
        if not isinstance(phase, Mapping):
            continue
        blockers = _list_of_str(phase.get("blockers"))
        lines.append(
            f"| `{phase.get('phase_id')}` | `{phase.get('status')}` | `{blockers[0] if blockers else ''}` | {phase.get('next_action')} |"
        )
    lines.extend(["", "## Guardrails", "", "- audit_only=true", "- live_order_allowed=false", "- paper_or_live_unlock_allowed=false"])
    return "\n".join(lines)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in out:
            out.append(text)
    return out


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
