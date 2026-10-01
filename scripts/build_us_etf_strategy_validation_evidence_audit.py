#!/usr/bin/env python3
"""Build a requirement-level audit for the US ETF validation gate.

The validation gate gives the decision. This report explains which explicit
strategy-validation requirements are proven by which gate checks and source
reports. It is audit-only and cannot unlock paper/live trading.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_etf_strategy_validation_evidence_audit_v1"
DEFAULT_VALIDATION_GATE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 策略验证证据审计.md")
ALLOWED_STATUSES = {
    "validation_evidence_audit_incomplete",
    "validation_evidence_audit_blocked_data_quality",
    "validation_evidence_audit_ready_for_forward_observation",
}

REQUIREMENTS = [
    {
        "requirement_id": "data_quality_pit",
        "title": "Data coverage, freshness, and PIT quality pass",
        "gate_check_key": "data_coverage_and_quality",
        "source_report_keys": [
            "data_freshness_report",
            "kline_quality_report",
            "fred_preflight_report",
            "pit_intake_status_report",
            "pit_bundle_acceptance_report",
        ],
    },
    {
        "requirement_id": "no_future_function",
        "title": "No future function and T+1/no-order endpoint integrity",
        "gate_check_key": "no_future_function",
        "source_report_keys": ["research_report"],
    },
    {
        "requirement_id": "original_strategy_semantics",
        "title": "Original strategy semantics and deviations explained",
        "gate_check_key": "original_strategy_semantics",
        "source_report_keys": ["top_validation_report"],
    },
    {
        "requirement_id": "benchmark_coverage",
        "title": "SPY, QQQ, 60/40, and cash/SHV benchmarks present",
        "gate_check_key": "benchmark_coverage",
        "source_report_keys": ["top_validation_report"],
    },
    {
        "requirement_id": "standard_metrics",
        "title": "CAGR, Vol, Sharpe, MDD, Calmar, Turnover, stressed return, liquidity included",
        "gate_check_key": "standard_metrics",
        "source_report_keys": ["top_validation_report"],
    },
    {
        "requirement_id": "cost_stress",
        "title": "0/10/25/50bps cost stress survives required thresholds",
        "gate_check_key": "cost_stress",
        "source_report_keys": ["top_validation_report", "cost_stress_report"],
    },
    {
        "requirement_id": "walk_forward",
        "title": "Walk-forward out-of-sample evidence does not collapse",
        "gate_check_key": "walk_forward",
        "source_report_keys": ["top_validation_report"],
    },
    {
        "requirement_id": "parameter_stability",
        "title": "Parameter neighborhood is stable enough; not a single lucky point",
        "gate_check_key": "parameter_stability",
        "source_report_keys": ["walk_forward_report"],
    },
    {
        "requirement_id": "capacity",
        "title": "1万/5万/10万/50万/100万美元 capacity tests are present",
        "gate_check_key": "capacity",
        "source_report_keys": ["top_validation_report"],
    },
    {
        "requirement_id": "return_attribution",
        "title": "Return source attribution separates selection, macro/defense, leverage, financing, and slippage",
        "gate_check_key": "return_attribution",
        "source_report_keys": ["top_validation_report", "year_attribution_report"],
    },
    {
        "requirement_id": "strategy_card",
        "title": "Strategy card documents return sources, risks, boundaries, and disable rules",
        "gate_check_key": "strategy_card",
        "source_report_keys": ["strategy_card"],
    },
    {
        "requirement_id": "execution_guardrails",
        "title": "No private/order/live flags are enabled",
        "gate_check_key": "guardrails",
        "source_report_keys": ["research_report", "top_validation_report"],
    },
]


def build_us_etf_strategy_validation_evidence_audit(
    *,
    repo_root: Path | None = None,
    validation_gate_report: Path = DEFAULT_VALIDATION_GATE,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    gate_path = _resolve(root, validation_gate_report)
    gate = _read_json(gate_path)
    requirements = [_requirement_row(item, gate) for item in REQUIREMENTS]
    complete_count = sum(1 for item in requirements if item["status"] == "complete")
    blocked_count = sum(1 for item in requirements if item["status"] == "blocked")
    incomplete_count = sum(1 for item in requirements if item["status"] == "incomplete")
    gate_status = str(gate.get("status", "missing"))

    if not gate:
        status = "validation_evidence_audit_incomplete"
        decision = "run_strategy_validation_gate_before_auditing_evidence"
    elif gate_status == "blocked_data_quality":
        status = "validation_evidence_audit_blocked_data_quality"
        decision = "repair_data_quality_before_claiming_strategy_validation"
    elif incomplete_count or blocked_count:
        status = "validation_evidence_audit_incomplete"
        decision = "repair_missing_validation_evidence"
    else:
        status = "validation_evidence_audit_ready_for_forward_observation"
        decision = "evidence_supports_forward_observation_only"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "strategy_id": str(gate.get("strategy_id", "")),
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": decision,
        "gate_status": gate_status,
        "gate_decision": gate.get("decision"),
        "summary": {
            "requirement_count": len(requirements),
            "complete_count": complete_count,
            "blocked_count": blocked_count,
            "incomplete_count": incomplete_count,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "requirements": requirements,
        "incomplete_requirements": [
            item["requirement_id"] for item in requirements if item["status"] != "complete"
        ],
        "source_reports": {
            "validation_gate": _relpath(gate_path, root),
            **_mapping(gate.get("source_reports")),
        },
        "blockers": _blockers(gate, requirements),
        "guardrails": {
            "audit_only": True,
            "validation_evidence_audit_is_not_execution_permission": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _requirement_row(spec: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    check_key = str(spec["gate_check_key"])
    source_report_keys = _list_of_str(spec.get("source_report_keys"))
    checks = _mapping(gate.get("checks"))
    source_reports = _mapping(gate.get("source_reports"))
    check = _mapping(checks.get(check_key))
    source_paths = {key: str(source_reports.get(key, "")) for key in source_report_keys}
    missing_sources = [key for key, value in source_paths.items() if not value]
    if not check:
        row_status = "incomplete"
        blocker = f"validation_gate_check_missing:{check_key}"
    elif missing_sources:
        row_status = "incomplete"
        blocker = f"validation_gate_source_reports_missing:{','.join(missing_sources)}"
    elif bool(check.get("passed")):
        row_status = "complete"
        blocker = None
    else:
        row_status = "blocked"
        blocker = f"validation_gate_check_failed:{check_key}"
    return {
        "requirement_id": str(spec["requirement_id"]),
        "title": str(spec["title"]),
        "status": row_status,
        "gate_check_key": check_key,
        "gate_check_passed": bool(check.get("passed", False)) if check else False,
        "source_report_keys": source_report_keys,
        "source_paths": source_paths,
        "blocker": blocker,
    }


def _blockers(gate: Mapping[str, Any], requirements: list[Mapping[str, Any]]) -> list[str]:
    blockers = []
    if not gate:
        blockers.append("strategy_validation_gate_report_missing")
    blockers.extend(_list_of_str(gate.get("blockers")))
    for item in requirements:
        blocker = item.get("blocker")
        if blocker:
            blockers.append(str(blocker))
    return _dedupe(blockers)


def _markdown(payload: Mapping[str, Any]) -> str:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# US ETF 轮动 策略验证证据审计",
        "",
        f"- status: `{payload.get('status')}`",
        f"- gate_status: `{payload.get('gate_status')}`",
        f"- complete: `{summary.get('complete_count')}` / `{summary.get('requirement_count')}`",
        f"- live_order_allowed: `{_nested(payload, 'guardrails.live_order_allowed')}`",
        "",
        "## Requirement Map",
        "",
        "| requirement | status | gate check | blocker |",
        "| --- | --- | --- | --- |",
    ]
    for item in _list(payload.get("requirements")):
        if isinstance(item, Mapping):
            lines.append(
                f"| `{item.get('requirement_id')}` | `{item.get('status')}` | `{item.get('gate_check_key')}` | `{item.get('blocker') or ''}` |"
            )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] or ["- None"])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- audit_only=true",
            "- paper_or_live_unlock_allowed=false",
            "- live_order_allowed=false",
        ]
    )
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _nested(payload: Mapping[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() or None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--validation-gate-report", type=Path, default=DEFAULT_VALIDATION_GATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()
    payload = build_us_etf_strategy_validation_evidence_audit(
        repo_root=args.repo_root,
        validation_gate_report=args.validation_gate_report,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
