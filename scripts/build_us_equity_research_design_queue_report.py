#!/usr/bin/env python3
"""Build the US equity research-design queue from the research-start gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_research_design_queue_report_v1"
DEFAULT_RESEARCH_START_GATE = Path("artifacts/us_equity_strategy_registry/latest/us_equity_research_start_gate_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_research_design_queue_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 策略研究设计队列.md")
DESIGN_SPEC_REPORTS = {
    "us_equity_dual_momentum_research_placeholder": Path(
        "artifacts/us_equity_strategy_registry/latest/us_equity_dual_momentum_design_spec_report.json"
    ),
    "us_equity_absolute_momentum_research_placeholder": Path(
        "artifacts/us_equity_strategy_registry/latest/us_equity_absolute_momentum_design_spec_report.json"
    ),
    "us_equity_etf_topn_rotation_research_placeholder": Path(
        "artifacts/us_equity_strategy_registry/latest/us_equity_topn_etf_rotation_design_spec_report.json"
    ),
    "us_equity_regime_overlay_research_placeholder": Path(
        "artifacts/us_equity_strategy_registry/latest/us_equity_regime_overlay_design_spec_report.json"
    ),
    "us_equity_factor_momentum_quality_research_placeholder": Path(
        "artifacts/us_equity_strategy_registry/latest/us_equity_factor_momentum_quality_design_spec_report.json"
    ),
    "us_equity_151_trading_strategies_candidate_research_placeholder": Path(
        "artifacts/us_equity_strategy_registry/latest/us_equity_151_trading_strategies_migration_design_spec_report.json"
    ),
}

FAMILY_PRIORITY = {
    "dual_momentum": 10,
    "absolute_momentum": 20,
    "topn_etf_rotation": 30,
    "regime_overlay": 40,
    "equity_factor": 60,
    "151_trading_strategies_migration": 90,
}


def build_us_equity_research_design_queue_report(
    *,
    repo_root: Path | None = None,
    research_start_gate: Path = DEFAULT_RESEARCH_START_GATE,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    gate_path = _resolve(root, research_start_gate)
    gate = _read_json(gate_path)
    blockers: list[str] = []
    if not gate:
        blockers.append("us_equity_research_design_queue_research_start_gate_missing")
    if str(gate.get("status", "")) == "research_start_blocked":
        blockers.append("us_equity_research_design_queue_research_start_gate_blocked")

    production_data_gate = _production_data_gate(gate)
    design_specs = {strategy_id: _read_json(_resolve(root, path)) for strategy_id, path in DESIGN_SPEC_REPORTS.items()}
    tasks = [
        _task_from_strategy(row, design_specs=design_specs, production_data_gate=production_data_gate)
        for row in _list(gate.get("strategies"))
        if isinstance(row, Mapping)
    ]
    tasks = sorted(tasks, key=lambda item: (item["priority"], item["strategy_id"]))
    design_tasks = [item for item in tasks if item["status"] == "design_ready"]
    completed_tasks = [item for item in tasks if item["status"] == "design_complete_waiting_for_research_start"]
    waiting_tasks = [item for item in tasks if item["status"] == "waiting_for_production_data"]
    blocked_tasks = [item for item in tasks if item["status"] == "blocked"]
    blockers.extend(f"us_equity_research_design_queue_task_blocked:{item['strategy_id']}" for item in blocked_tasks)
    status = "research_design_queue_ready" if design_tasks and not blocked_tasks and not blockers else "research_design_queue_blocked"
    if waiting_tasks and not design_tasks and not blocked_tasks and not blockers:
        status = "research_design_queue_waiting_for_data"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "research_design_queue_ready",
            "research_design_queue_waiting_for_data",
            "research_design_queue_blocked",
        ],
        "decision": "design_hypotheses_only_keep_standard_backtests_locked",
        "task_count": len(tasks),
        "design_ready_count": len(design_tasks),
        "design_complete_count": len(completed_tasks),
        "waiting_for_production_data_count": len(waiting_tasks),
        "blocked_count": len(blocked_tasks),
        "production_data_gate": production_data_gate,
        "next_task": design_tasks[0] if design_tasks else waiting_tasks[0] if waiting_tasks else blocked_tasks[0] if blocked_tasks else None,
        "tasks": tasks,
        "blockers": _dedupe(blockers),
        "source_reports": {
            "research_start_gate": _relpath(gate_path, root),
        },
        "guardrails": {
            "queue_only": True,
            "hypothesis_design_only": True,
            "standardized_backtest_allowed_by_this_report": False,
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
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _production_data_gate(gate: Mapping[str, Any]) -> dict[str, Any]:
    production_data = _mapping(gate.get("production_data"))
    blockers = [
        item
        for item in _list_of_str(gate.get("blockers"))
        if item
        in {
            "us_equity_research_start_production_pit_intake_not_ready",
            "us_equity_research_start_pit_bundle_acceptance_not_ready",
        }
    ]
    return {
        "production_pit_ready_for_formal_research": bool(
            production_data.get("production_pit_ready_for_formal_research")
        ),
        "pit_intake_status": str(production_data.get("pit_intake_status", "missing")),
        "pit_acceptance_status": str(production_data.get("pit_acceptance_status", "missing")),
        "blockers": blockers,
    }


def _task_from_strategy(
    row: Mapping[str, Any],
    *,
    design_specs: Mapping[str, Mapping[str, Any]],
    production_data_gate: Mapping[str, Any],
) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id", ""))
    family = str(row.get("family", ""))
    gate_status = str(row.get("status", ""))
    blockers = _list_of_str(row.get("blockers"))
    design_spec = design_specs.get(strategy_id, {})
    design_spec_ready = str(design_spec.get("status", "")) == "design_spec_ready"
    if gate_status == "hypothesis_design_only" and design_spec_ready:
        status = "design_complete_waiting_for_research_start"
        next_required_action = "wait_for_production_pit_data_and_research_start_gate"
    elif gate_status == "hypothesis_design_only":
        status = "design_ready"
        next_required_action = "complete_hypothesis_design_spec_before_any_backtest"
    elif gate_status == "existing_formal_candidate_waiting_for_production_data":
        status = "waiting_for_production_data"
        next_required_action = "wait_for_production_pit_data_before_rerun_validation"
    else:
        status = "blocked"
        next_required_action = "repair_research_start_gate_row"
    return {
        "strategy_id": strategy_id,
        "family": family,
        "priority": FAMILY_PRIORITY.get(family, 999),
        "status": status,
        "research_start_gate_status": gate_status,
        "strategy_card": str(row.get("strategy_card", "")),
        "design_spec_report": str(design_spec.get("outputs", {}).get("json", "")) if design_spec_ready else "",
        "design_spec_ready": design_spec_ready,
        "production_data_gate": dict(production_data_gate),
        "next_required_action": next_required_action,
        "required_design_outputs": _required_design_outputs(family),
        "standardized_backtest_allowed": False,
        "paper_or_live_allowed": False,
        "blockers": blockers,
    }


def _required_design_outputs(family: str) -> list[str]:
    common = [
        "immutable_strategy_id",
        "explicit_alpha_hypothesis",
        "parameter_space_before_backtest",
        "data_dependencies_and_pit_requirements",
        "cost_liquidity_capacity_model",
        "failure_conditions_and_stop_rules",
    ]
    family_specific = {
        "regime_overlay": ["macro_release_lag_policy", "macro_revision_policy"],
        "equity_factor": ["pit_fundamentals_availability", "delisting_return_policy"],
        "151_trading_strategies_migration": ["source_strategy_mapping", "implementation_exclusions"],
        "topn_etf_rotation": ["top_n_weighting_rule", "correlation_and_concentration_check"],
    }
    return common + family_specific.get(family, [])


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 策略研究设计队列",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- design ready：`{payload.get('design_ready_count', 0)}`",
        f"- waiting data：`{payload.get('waiting_for_production_data_count', 0)}`",
        "",
        "本队列只允许完善假设设计，不允许启动标准化回测、paper 或 live。",
        "",
        "| priority | strategy | status | next action |",
        "| ---: | --- | --- | --- |",
    ]
    for item in _list(payload.get("tasks")):
        if isinstance(item, Mapping):
            lines.append(
                f"| `{item.get('priority')}` | `{item.get('strategy_id')}` | `{item.get('status')}` | `{item.get('next_required_action')}` |"
            )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", "", "- standardized_backtest_allowed_by_this_report=false", "- live_order_allowed=false"])
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity research design queue.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--research-start-gate", default=str(DEFAULT_RESEARCH_START_GATE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_research_design_queue_report(
        repo_root=Path(args.repo_root),
        research_start_gate=Path(args.research_start_gate),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
