#!/usr/bin/env python3
"""Audit the US equity strategy evidence packet against the standard report schema."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_standard_report_schema_audit_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 标准报告 Schema 审计.md")
DEFAULT_RESEARCH_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json")
DEFAULT_VALIDATION_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json"
)
DEFAULT_WALK_FORWARD_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json"
)
DEFAULT_STRATEGY_GATE_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_FORWARD_EVALUATION_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"
)
DEFAULT_SMALL_ACCOUNT_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"
)
DEFAULT_LIVE_READINESS_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json"
)
DEFAULT_PIT_HANDOFF_REPORT = Path(
    "artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json"
)
DEFAULT_PIT_HANDOFF_SCHEMA = Path("schemas/us_equity_pit_operator_handoff_summary.schema.json")
DEFAULT_DAILY_PRODUCTION_LINE_REPORT = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"
)
DEFAULT_DAILY_PRODUCTION_LINE_SCHEMA = Path("schemas/us_equity_daily_production_line_run_report.schema.json")
DEFAULT_COMPLETION_DEPENDENCY_REPORT = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_completion_dependency_report.json"
)
DEFAULT_COMPLETION_DEPENDENCY_SCHEMA = Path("schemas/us_equity_completion_dependency_report.schema.json")
DEFAULT_COMPLETION_AUDIT_REPORT = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_completion_audit_report.json"
)
DEFAULT_COMPLETION_AUDIT_SCHEMA = Path("schemas/us_equity_completion_audit_report.schema.json")
DEFAULT_NEXT_ACTION_QUEUE_REPORT = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json"
)
DEFAULT_NEXT_ACTION_QUEUE_SCHEMA = Path("schemas/us_equity_next_action_queue_report.schema.json")

REQUIRED_STANDARD_FIELDS = [
    "strategy_id",
    "candidate_variant",
    "data_status",
    "metrics",
    "benchmarks",
    "cost_stress",
    "liquidity",
    "attribution",
    "walk_forward",
    "parameter_stability",
    "pit_operator_handoff_schema",
    "production_control_schema",
    "guardrails",
    "decision",
]
REQUIRED_BENCHMARKS = {"SPY", "QQQ", "60_40_SPY_IEF", "SHV"}
REQUIRED_COST_LEVELS = {"0bps", "10bps", "25bps", "50bps"}
REQUIRED_METRIC_FIELDS = {"CAGR", "Vol", "Sharpe", "MDD", "Calmar", "Turnover", "CostStressedReturn", "LiquidityPass"}
UNSAFE_FLAG_NAMES = {
    "live_order_allowed",
    "order_endpoint_allowed",
    "private_endpoint_allowed",
    "paper_or_live_unlock_allowed",
    "real_order_submitted",
}


def build_us_equity_standard_report_schema_audit(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    research_report: Path = DEFAULT_RESEARCH_REPORT,
    validation_report: Path = DEFAULT_VALIDATION_REPORT,
    walk_forward_report: Path = DEFAULT_WALK_FORWARD_REPORT,
    strategy_gate_report: Path = DEFAULT_STRATEGY_GATE_REPORT,
    forward_evaluation_report: Path = DEFAULT_FORWARD_EVALUATION_REPORT,
    small_account_report: Path = DEFAULT_SMALL_ACCOUNT_REPORT,
    live_readiness_report: Path = DEFAULT_LIVE_READINESS_REPORT,
    pit_operator_handoff_report: Path = DEFAULT_PIT_HANDOFF_REPORT,
    pit_operator_handoff_schema: Path = DEFAULT_PIT_HANDOFF_SCHEMA,
    daily_production_line_report: Path = DEFAULT_DAILY_PRODUCTION_LINE_REPORT,
    daily_production_line_schema: Path = DEFAULT_DAILY_PRODUCTION_LINE_SCHEMA,
    completion_dependency_report: Path = DEFAULT_COMPLETION_DEPENDENCY_REPORT,
    completion_dependency_schema: Path = DEFAULT_COMPLETION_DEPENDENCY_SCHEMA,
    completion_audit_report: Path = DEFAULT_COMPLETION_AUDIT_REPORT,
    completion_audit_schema: Path = DEFAULT_COMPLETION_AUDIT_SCHEMA,
    next_action_queue_report: Path = DEFAULT_NEXT_ACTION_QUEUE_REPORT,
    next_action_queue_schema: Path = DEFAULT_NEXT_ACTION_QUEUE_SCHEMA,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "research_report": _resolve(root, research_report),
        "validation_report": _resolve(root, validation_report),
        "walk_forward_report": _resolve(root, walk_forward_report),
        "strategy_gate_report": _resolve(root, strategy_gate_report),
        "forward_evaluation_report": _resolve(root, forward_evaluation_report),
        "small_account_report": _resolve(root, small_account_report),
        "live_readiness_report": _resolve(root, live_readiness_report),
        "pit_operator_handoff_report": _resolve(root, pit_operator_handoff_report),
        "pit_operator_handoff_schema": _resolve(root, pit_operator_handoff_schema),
        "daily_production_line_report": _resolve(root, daily_production_line_report),
        "daily_production_line_schema": _resolve(root, daily_production_line_schema),
        "completion_dependency_report": _resolve(root, completion_dependency_report),
        "completion_dependency_schema": _resolve(root, completion_dependency_schema),
        "completion_audit_report": _resolve(root, completion_audit_report),
        "completion_audit_schema": _resolve(root, completion_audit_schema),
        "next_action_queue_report": _resolve(root, next_action_queue_report),
        "next_action_queue_schema": _resolve(root, next_action_queue_schema),
    }
    reports = {name: _read_json(path) for name, path in paths.items() if name.endswith("_report")}
    schemas = {name: _read_json(path) for name, path in paths.items() if name.endswith("_schema")}
    field_checks = _field_checks(reports, schemas)
    missing_inputs = [name for name, path in paths.items() if not path.exists()]
    unsafe_flags = _unsafe_flags(reports)
    blockers = [f"us_equity_standard_schema_missing_input:{name}" for name in missing_inputs]
    blockers.extend(f"us_equity_standard_schema_field_missing:{name}" for name, check in field_checks.items() if not check["passed"])
    blockers.extend(f"us_equity_standard_schema_unsafe_flag:{name}" for name in unsafe_flags)
    status = "schema_audit_pass" if not blockers else "schema_audit_action_required"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "strategy_id": _first_string(
            _nested(reports["strategy_gate_report"], "strategy_id"),
            _nested(reports["forward_evaluation_report"], "strategy_id"),
            _nested(reports["validation_report"], "strategy_id"),
        ),
        "candidate_variant": _first_string(
            _nested(reports["strategy_gate_report"], "candidate_variant"),
            _nested(reports["forward_evaluation_report"], "candidate_variant"),
            _nested(reports["small_account_report"], "candidate_variant"),
        ),
        "status": status,
        "decision": "standard_schema_ready_for_manual_review" if status == "schema_audit_pass" else "repair_standard_schema_evidence",
        "required_fields": REQUIRED_STANDARD_FIELDS,
        "field_checks": field_checks,
        "coverage_summary": {
            "required_field_count": len(REQUIRED_STANDARD_FIELDS),
            "passed_field_count": sum(1 for check in field_checks.values() if check["passed"]),
            "missing_input_count": len(missing_inputs),
            "unsafe_flag_count": len(unsafe_flags),
        },
        "blockers": _dedupe(blockers),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "schema_audit_only": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
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


def _field_checks(reports: Mapping[str, Mapping[str, Any]], schemas: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    research = reports["research_report"]
    validation = reports["validation_report"]
    walk = reports["walk_forward_report"]
    gate = reports["strategy_gate_report"]
    forward = reports["forward_evaluation_report"]
    small = reports["small_account_report"]
    live = reports["live_readiness_report"]
    handoff = reports["pit_operator_handoff_report"]
    rows = _list(_nested(validation, "standardized_report_schema.rows", []))
    row_ids = {str(row.get("id", "")) for row in rows if isinstance(row, Mapping)}
    metric_missing = {}
    for row in rows:
        if isinstance(row, Mapping):
            missing = sorted(REQUIRED_METRIC_FIELDS - set(str(key) for key in row.keys()))
            if missing:
                metric_missing[str(row.get("id", "unknown"))] = missing
    cost_levels = set(_mapping(validation.get("cost_stress")).keys())
    return {
        "strategy_id": _check(
            bool(gate.get("strategy_id") or forward.get("strategy_id") or validation.get("strategy_id")),
            ["strategy_gate_report", "forward_evaluation_report", "validation_report"],
        ),
        "candidate_variant": _check(
            bool(gate.get("candidate_variant") or forward.get("candidate_variant") or small.get("candidate_variant")),
            ["strategy_gate_report", "forward_evaluation_report", "small_account_report"],
        ),
        "data_status": _check(
            bool(_mapping(research.get("data"))) and bool(_nested(gate, "checks.data_coverage_and_quality")),
            ["research_report.data", "strategy_gate_report.checks.data_coverage_and_quality"],
        ),
        "metrics": _check(bool(rows) and not metric_missing, ["validation_report.standardized_report_schema.rows"], {"missing_by_row": metric_missing}),
        "benchmarks": _check(
            REQUIRED_BENCHMARKS <= row_ids,
            ["validation_report.standardized_report_schema.rows"],
            {"required": sorted(REQUIRED_BENCHMARKS), "present": sorted(row_ids)},
        ),
        "cost_stress": _check(
            REQUIRED_COST_LEVELS <= cost_levels,
            ["validation_report.cost_stress"],
            {"required": sorted(REQUIRED_COST_LEVELS), "present": sorted(cost_levels)},
        ),
        "liquidity": _check(
            bool(validation.get("constrained_tradability")) and all(
                isinstance(row, Mapping) and "LiquidityPass" in row for row in rows
            ),
            ["validation_report.constrained_tradability", "validation_report.standardized_report_schema.LiquidityPass"],
        ),
        "attribution": _check(
            bool(validation.get("source_attribution"))
            and bool(validation.get("extreme_year_attribution"))
            and bool(validation.get("yearly_breakdown")),
            ["validation_report.source_attribution", "validation_report.extreme_year_attribution", "validation_report.yearly_breakdown"],
        ),
        "walk_forward": _check(bool(validation.get("walk_forward")), ["validation_report.walk_forward"]),
        "parameter_stability": _check(
            bool(_nested(walk, "stability.stable_enough_for_next_research_stage")) and bool(walk.get("parameter_grid")),
            ["walk_forward_report.stability", "walk_forward_report.parameter_grid"],
        ),
        "pit_operator_handoff_schema": _json_schema_check(
            handoff,
            schemas.get("pit_operator_handoff_schema", {}),
            ["pit_operator_handoff_report", "pit_operator_handoff_schema"],
        ),
        "production_control_schema": _multi_json_schema_check(
            {
                "daily_production_line_report": reports.get("daily_production_line_report", {}),
                "completion_dependency_report": reports.get("completion_dependency_report", {}),
                "completion_audit_report": reports.get("completion_audit_report", {}),
                "next_action_queue_report": reports.get("next_action_queue_report", {}),
            },
            {
                "daily_production_line_schema": schemas.get("daily_production_line_schema", {}),
                "completion_dependency_schema": schemas.get("completion_dependency_schema", {}),
                "completion_audit_schema": schemas.get("completion_audit_schema", {}),
                "next_action_queue_schema": schemas.get("next_action_queue_schema", {}),
            },
            [
                "daily_production_line_report",
                "completion_dependency_report",
                "completion_audit_report",
                "next_action_queue_report",
            ],
        ),
        "guardrails": _check(
            all(_safe_false(report, "live_order_allowed") for report in (gate, forward, small, live))
            and all(_safe_false(_mapping(report.get("guardrails")), "live_order_allowed") for report in (gate, forward, small, live, handoff)),
            ["strategy_gate_report", "forward_evaluation_report", "small_account_report", "live_readiness_report", "pit_operator_handoff_report"],
        ),
        "decision": _check(
            bool(validation.get("decision")) and bool(gate.get("decision")) and bool(forward.get("decision")),
            ["validation_report.decision", "strategy_gate_report.decision", "forward_evaluation_report.decision"],
        ),
    }


def _check(passed: bool, sources: list[str], extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"passed": bool(passed), "sources": sources}
    if extra:
        payload.update(dict(extra))
    return payload


def _json_schema_check(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    sources: list[str],
) -> dict[str, Any]:
    if not payload:
        return _check(False, sources, {"error": "report_missing"})
    if not schema:
        return _check(False, sources, {"error": "schema_missing"})
    try:
        import jsonschema

        jsonschema.validate(dict(payload), dict(schema))
    except Exception as exc:
        return _check(False, sources, {"error": str(exc).splitlines()[0]})
    return _check(True, sources, {"schema_version": payload.get("schema_version")})


def _multi_json_schema_check(
    reports: Mapping[str, Mapping[str, Any]],
    schemas: Mapping[str, Mapping[str, Any]],
    sources: list[str],
) -> dict[str, Any]:
    schema_pairs = {
        "daily_production_line_report": "daily_production_line_schema",
        "completion_dependency_report": "completion_dependency_schema",
        "completion_audit_report": "completion_audit_schema",
        "next_action_queue_report": "next_action_queue_schema",
    }
    errors: dict[str, str] = {}
    versions: dict[str, str] = {}
    for report_name, schema_name in schema_pairs.items():
        result = _json_schema_check(reports.get(report_name, {}), schemas.get(schema_name, {}), [report_name, schema_name])
        if result.get("passed") is not True:
            errors[report_name] = str(result.get("error", "schema_validation_failed"))
        else:
            versions[report_name] = str(result.get("schema_version", ""))
    return _check(not errors, sources, {"schema_versions": versions, "errors": errors})


def _unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for report_name, report in reports.items():
        for key in UNSAFE_FLAG_NAMES:
            if report.get(key) is True:
                out.append(f"{report_name}.{key}")
            guardrails = _mapping(report.get("guardrails"))
            if guardrails.get(key) is True:
                out.append(f"{report_name}.guardrails.{key}")
    return _dedupe(out)


def _safe_false(payload: Mapping[str, Any], key: str) -> bool:
    return payload.get(key) in {False, None}


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 标准报告 Schema 审计",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 策略：`{payload.get('strategy_id', '')}`",
        f"- 候选：`{payload.get('candidate_variant', '')}`",
        "",
        "| 字段 | 通过 | 来源 |",
        "| --- | --- | --- |",
    ]
    for field, check in _mapping(payload.get("field_checks")).items():
        lines.append(f"| `{field}` | `{check.get('passed')}` | {', '.join(f'`{item}`' for item in _list_of_str(check.get('sources')))} |")
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend(f"- `{item}`" for item in blockers) if blockers else lines.append("- 无")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 本报告只审计 evidence schema。",
            "- 不修改策略参数。",
            "- 不解锁 paper/live。",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    value: Any = payload
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "")
        if text:
            return text
    return ""


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_equity_standard_report_schema_audit(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
