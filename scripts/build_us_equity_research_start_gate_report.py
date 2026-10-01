#!/usr/bin/env python3
"""Build the US equity research-start gate report.

This gate sits between strategy-card registration and standardized backtests.
It permits hypothesis design work, but it does not permit formal research,
paper simulation, or live trading unless registry and production-data gates are
clean.
"""

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


SCHEMA_VERSION = "us_equity_research_start_gate_report_v1"
DEFAULT_REGISTRY_REPORT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_strategy_registry_report.json")
DEFAULT_PIT_INTAKE_STATUS = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json")
DEFAULT_PIT_ACCEPTANCE = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_research_start_gate_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 策略研究启动门禁.md")


def build_us_equity_research_start_gate_report(
    *,
    repo_root: Path | None = None,
    registry_report: Path = DEFAULT_REGISTRY_REPORT,
    pit_intake_status: Path = DEFAULT_PIT_INTAKE_STATUS,
    pit_acceptance: Path = DEFAULT_PIT_ACCEPTANCE,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "registry_report": _resolve(root, registry_report),
        "pit_intake_status": _resolve(root, pit_intake_status),
        "pit_acceptance": _resolve(root, pit_acceptance),
    }
    registry = _read_json(paths["registry_report"])
    pit_status = _read_json(paths["pit_intake_status"])
    acceptance = _read_json(paths["pit_acceptance"])

    blockers: list[str] = []
    if not registry:
        blockers.append("us_equity_research_start_registry_report_missing")
    if str(registry.get("status", "")) != "pass":
        blockers.append("us_equity_research_start_registry_not_pass")
    if str(pit_status.get("status", "")) != "production_pit_data_intake_ready":
        blockers.append("us_equity_research_start_production_pit_intake_not_ready")
    if str(acceptance.get("status", "")) != "acceptance_ready_for_manual_config_apply":
        blockers.append("us_equity_research_start_pit_bundle_acceptance_not_ready")

    production_data = _production_data(pit_status, acceptance, blockers)
    rows = [
        _strategy_gate_row(row, pit_status=pit_status, acceptance=acceptance, production_data=production_data)
        for row in _list(registry.get("strategy_rows"))
    ]
    formal_ready_count = sum(1 for row in rows if row["formal_research_allowed"])
    design_only_count = sum(1 for row in rows if row["hypothesis_design_allowed"] and not row["formal_research_allowed"])
    blocked_count = sum(1 for row in rows if row["status"] == "blocked")
    status = "research_start_ready" if formal_ready_count > 0 and not blockers else "research_design_only"
    if blocked_count or str(registry.get("status", "")) not in {"", "pass"}:
        status = "research_start_blocked"
    if blockers and not rows:
        status = "research_start_blocked"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "research_design_only",
            "research_start_ready",
            "research_start_blocked",
        ],
        "decision": _decision(status),
        "strategy_count": len(rows),
        "formal_research_allowed_count": formal_ready_count,
        "hypothesis_design_only_count": design_only_count,
        "blocked_strategy_count": blocked_count,
        "production_data": production_data,
        "strategies": rows,
        "blockers": _dedupe(blockers + [item for row in rows for item in _list_of_str(row.get("blockers"))]),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "gate_only": True,
            "standardized_backtest_started_by_this_report": False,
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


def _production_data(
    pit_status: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    production_blockers = [
        blocker
        for blocker in blockers
        if blocker
        in {
            "us_equity_research_start_production_pit_intake_not_ready",
            "us_equity_research_start_pit_bundle_acceptance_not_ready",
        }
    ]
    return {
        "pit_intake_status": pit_status.get("status", "missing"),
        "pit_acceptance_status": acceptance.get("status", "missing"),
        "production_pit_ready_for_formal_research": not production_blockers,
        "blockers": _dedupe(production_blockers),
    }


def _strategy_gate_row(
    row: Mapping[str, Any],
    *,
    pit_status: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    production_data: Mapping[str, Any],
) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id", ""))
    registry_status = str(row.get("status", ""))
    current_stage = str(row.get("current_stage", ""))
    card_exists = row.get("strategy_card_exists") is True
    blockers: list[str] = []
    if not strategy_id:
        blockers.append("strategy_id_missing")
    if not card_exists:
        blockers.append("strategy_card_missing")
    if registry_status == "hypothesis_registered_only" and current_stage != "strategy_hypothesis_registration":
        blockers.append("hypothesis_stage_mismatch")
    production_ready = (
        str(pit_status.get("status", "")) == "production_pit_data_intake_ready"
        and str(acceptance.get("status", "")) == "acceptance_ready_for_manual_config_apply"
    )
    is_hypothesis = registry_status == "hypothesis_registered_only"
    formal_candidate_contract_ok = row.get("source_report_contract_passed") is True
    formal_research_allowed = bool(card_exists and production_ready and not is_hypothesis and formal_candidate_contract_ok)
    hypothesis_design_allowed = bool(card_exists and is_hypothesis and not blockers)
    existing_formal_waiting_data = bool(card_exists and not is_hypothesis and formal_candidate_contract_ok and not production_ready and not blockers)
    status = (
        "formal_research_allowed"
        if formal_research_allowed
        else "hypothesis_design_only"
        if hypothesis_design_allowed
        else "existing_formal_candidate_waiting_for_production_data"
        if existing_formal_waiting_data
        else "blocked"
    )
    next_required_action = "run_standardized_research_backtest" if formal_research_allowed else (
        "wait_for_production_pit_data_before_rerun_validation"
        if existing_formal_waiting_data
        else
        "complete_strategy_hypothesis_design_and_wait_for_production_pit_data" if hypothesis_design_allowed else "repair_strategy_registration"
    )
    return {
        "strategy_id": strategy_id,
        "family": str(row.get("family", "")),
        "registry_status": registry_status,
        "current_stage": current_stage,
        "strategy_card": str(row.get("strategy_card", "")),
        "strategy_card_exists": card_exists,
        "status": status,
        "production_data_gate": dict(production_data),
        "hypothesis_design_allowed": hypothesis_design_allowed,
        "formal_research_allowed": formal_research_allowed,
        "existing_formal_candidate_waiting_for_production_data": existing_formal_waiting_data,
        "standardized_backtest_allowed": formal_research_allowed,
        "paper_or_live_allowed": False,
        "next_required_action": next_required_action,
        "blockers": _dedupe(blockers),
    }


def _decision(status: str) -> str:
    if status == "research_start_ready":
        return "formal_research_allowed_for_registered_non_live_candidates_only"
    if status == "research_start_blocked":
        return "repair_registry_or_data_before_research"
    return "hypothesis_design_only_keep_backtests_paper_live_locked"


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 策略研究启动门禁",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- formal research allowed：`{payload.get('formal_research_allowed_count', 0)}`",
        f"- hypothesis design only：`{payload.get('hypothesis_design_only_count', 0)}`",
        "",
        "本报告只判断研究启动资格，不启动回测，不解锁 paper/live。",
        "",
        "| strategy | status | formal research | next action |",
        "| --- | --- | --- | --- |",
    ]
    for row in _list(payload.get("strategies")):
        if isinstance(row, Mapping):
            lines.append(
                f"| `{row.get('strategy_id')}` | `{row.get('status')}` | `{row.get('formal_research_allowed')}` | `{row.get('next_required_action')}` |"
            )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", "", "- standardized_backtest_started_by_this_report=false", "- live_order_allowed=false"])
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
    parser = argparse.ArgumentParser(description="Build US equity research-start gate report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--registry-report", default=str(DEFAULT_REGISTRY_REPORT))
    parser.add_argument("--pit-intake-status", default=str(DEFAULT_PIT_INTAKE_STATUS))
    parser.add_argument("--pit-acceptance", default=str(DEFAULT_PIT_ACCEPTANCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_research_start_gate_report(
        repo_root=Path(args.repo_root),
        registry_report=Path(args.registry_report),
        pit_intake_status=Path(args.pit_intake_status),
        pit_acceptance=Path(args.pit_acceptance),
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
