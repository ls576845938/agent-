#!/usr/bin/env python3
"""Build an evidence-only kill-switch drill report for US equity execution readiness."""

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


SCHEMA_VERSION = "us_equity_kill_switch_drill_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_kill_switch_drill_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Kill Switch 演练.md")
DEFAULT_REPORT_PATHS = {
    "daily_production_line": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"),
    "forward_daily_health": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json"),
    "monitoring_rules": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json"),
    "order_reconciliation_drill": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_order_reconciliation_drill_report.json"),
    "manual_stop_reset_drill": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_stop_reset_drill_report.json"),
    "live_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json"),
}


def build_us_equity_kill_switch_drill_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    report_paths: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = dict(DEFAULT_REPORT_PATHS)
    if report_paths:
        paths.update(report_paths)
    reports = {name: _read_report(_resolve(root, path), root) for name, path in paths.items()}
    payloads = {name: _mapping(report.get("payload")) for name, report in reports.items()}
    scenarios = _scenarios(payloads)
    proven_count = sum(1 for item in scenarios if item["status"] == "proven")
    blocked_count = len(scenarios) - proven_count
    if proven_count == len(scenarios):
        status = "kill_switch_drill_proven"
    elif proven_count:
        status = "kill_switch_drill_partial"
    else:
        status = "kill_switch_drill_blocked"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "kill_switch_drill_blocked",
            "kill_switch_drill_partial",
            "kill_switch_drill_proven",
        ],
        "scenario_count": len(scenarios),
        "proven_count": proven_count,
        "blocked_count": blocked_count,
        "scenarios": scenarios,
        "blockers": _dedupe([blocker for item in scenarios for blocker in _list_of_str(item.get("blockers"))]),
        "source_reports": {
            name: {"path": report["path"], "exists": report["exists"], "status": _string(_mapping(report.get("payload")).get("status"))}
            for name, report in reports.items()
        },
        "guardrails": {
            "evidence_only": True,
            "simulated_or_policy_evidence_only": True,
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


def _scenarios(reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    daily = reports["daily_production_line"]
    health = reports["forward_daily_health"]
    monitoring = reports["monitoring_rules"]
    order_reconciliation = reports["order_reconciliation_drill"]
    manual_stop = reports["manual_stop_reset_drill"]
    live = reports["live_readiness"]
    return [
        _scenario(
            "data_stale_stop",
            "Data stale stop",
            _has_monitor(monitoring, "data_monitors", "etf_price_stale_stop")
            and _health_contract_present(health),
            [
                "monitoring rules include etf_price_stale_stop",
                "forward daily health exposes observation freshness and continuity",
            ],
            ["data_stale_stop_contract_not_proven"],
        ),
        _scenario(
            "unsafe_endpoint_flag_stop",
            "Unsafe endpoint flag stop",
            _has_monitor(monitoring, "position_and_execution_monitors", "kill_switch_required")
            and _daily_unsafe_scan_present(daily),
            [
                "monitoring rules include kill_switch_required",
                "daily production line records unsafe endpoint flags",
            ],
            ["unsafe_endpoint_flag_stop_contract_not_proven"],
        ),
        _scenario(
            "reconciliation_failure_stop",
            "Ledger and reconciliation failure stop",
            _has_monitor(monitoring, "position_and_execution_monitors", "cash_and_financing_reconciliation")
            and _order_reconciliation_drill_proven(order_reconciliation),
            [
                "monitoring rules define cash/financing reconciliation stop",
                "order reconciliation drill proves target/fill/snapshot/fee recomputation",
            ],
            ["order_reconciliation_drill_not_proven"],
        ),
        _scenario(
            "drawdown_loss_stop",
            "Drawdown and loss limit stop",
            _has_retirement_rule(monitoring, "risk_limit_failure") and _live_loss_limits_present(live),
            [
                "monitoring rules define risk_limit_failure retirement/manual-review trigger",
                "live readiness risk constitution records loss-limit policy",
            ],
            ["drawdown_loss_limit_drill_not_proven"],
        ),
        _scenario(
            "manual_stop_reset",
            "Manual stop and reset drill",
            _live_manual_reset_policy_present(live) and _manual_stop_reset_drill_proven(manual_stop),
            [
                "manual stop procedure is documented",
                "manual reset evidence exists after stop state",
            ],
            ["manual_stop_reset_drill_not_proven"],
        ),
    ]


def _scenario(
    scenario_id: str,
    title: str,
    passed: bool,
    required_evidence: list[str],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "title": title,
        "status": "proven" if passed else "blocked",
        "required_evidence": required_evidence,
        "blockers": [] if passed else blockers,
    }


def _has_monitor(report: Mapping[str, Any], section: str, key: str) -> bool:
    return report.get("status") == "monitoring_rules_defined" and isinstance(_nested(report, f"rules.{section}.{key}"), Mapping)


def _has_retirement_rule(report: Mapping[str, Any], key: str) -> bool:
    return report.get("status") == "monitoring_rules_defined" and isinstance(_nested(report, f"rules.retirement_rules.{key}"), Mapping)


def _health_contract_present(report: Mapping[str, Any]) -> bool:
    if report.get("status") not in {"daily_health_pass", "daily_health_observing_stale"}:
        return False
    continuity = _mapping(report.get("observation_continuity"))
    return "passed" in continuity and "unique_observation_days" in continuity


def _daily_unsafe_scan_present(report: Mapping[str, Any]) -> bool:
    if report.get("status") not in {"PASS", "BLOCKED"}:
        return False
    if not isinstance(report.get("unsafe_flags"), list):
        return False
    guardrails = _mapping(report.get("guardrails"))
    return (
        guardrails.get("live_order_allowed") is False
        and guardrails.get("private_endpoint_allowed") is False
        and guardrails.get("order_endpoint_allowed") is False
        and guardrails.get("broker_calls_used") is False
    )


def _order_reconciliation_drill_proven(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "order_reconciliation_drill_proven" or report.get("blocked_count") != 0:
        return False
    reconciliation = _mapping(report.get("reconciliation"))
    return (
        reconciliation.get("cash_recomputable") is True
        and reconciliation.get("positions_recomputable") is True
        and reconciliation.get("fees_recomputable") is True
    )


def _live_loss_limits_present(report: Mapping[str, Any]) -> bool:
    risk = _mapping(report.get("risk_constitution"))
    limits = _mapping(risk.get("loss_limits"))
    return bool(limits) and report.get("live_order_allowed") is False


def _live_manual_reset_policy_present(report: Mapping[str, Any]) -> bool:
    risk = _mapping(report.get("risk_constitution"))
    return (
        risk.get("manual_reset_required_after_stop") is True
        or _nested(risk, "loss_limits.manual_reset_required_after_stop") is True
        or report.get("manual_reset_required_after_stop") is True
    )


def _manual_stop_reset_drill_proven(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "manual_stop_reset_proven":
        return False
    return report.get("event_count") == 4 and report.get("checklist_count") == 6 and not _list(report.get("blockers"))


def _read_report(path: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relpath(path, root), "exists": False, "payload": {}}
    try:
        return {"path": _relpath(path, root), "exists": True, "payload": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:  # noqa: BLE001
        return {"path": _relpath(path, root), "exists": True, "payload": {"status": "unreadable_report", "blockers": [type(exc).__name__]}}


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity Kill Switch 演练",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- proven: `{payload.get('proven_count')}` / `{payload.get('scenario_count')}`",
        "",
        "| scenario | status | first blocker |",
        "| --- | --- | --- |",
    ]
    for scenario in _list(payload.get("scenarios")):
        if isinstance(scenario, Mapping):
            blockers = _list_of_str(scenario.get("blockers"))
            lines.append(f"| `{scenario.get('scenario_id')}` | `{scenario.get('status')}` | `{blockers[0] if blockers else ''}` |")
    lines.extend(["", "## Guardrails", "", "- evidence only", "- live_order_allowed=false", "- order_endpoint_allowed=false"])
    return "\n".join(lines)


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
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _string(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _nested(value: Any, dotted: str, default: Any = None) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_us_equity_kill_switch_drill_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
