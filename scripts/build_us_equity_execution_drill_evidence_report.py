#!/usr/bin/env python3
"""Build simulated execution-drill evidence for US equity live readiness."""

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

from quant_us.live.execution_drill_evidence import (  # noqa: E402
    evaluate_execution_drill_evidence,
)


SCHEMA_VERSION = "us_equity_execution_drill_evidence_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 执行演练证据.md")
DEFAULT_REPORT_PATHS = {
    "broker_credentials_review": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json"),
    "small_account_preflight": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"),
    "paper_simulation_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json"),
    "monitoring_rules": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json"),
    "order_reconciliation_drill": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_order_reconciliation_drill_report.json"),
    "kill_switch_drill": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_kill_switch_drill_report.json"),
    "forward_evaluation": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"),
    "live_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json"),
}


def build_us_equity_execution_drill_evidence_report(
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
    evaluation = evaluate_execution_drill_evidence(payloads)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": evaluation.status,
        "allowed_statuses": [
            "execution_drill_evidence_blocked",
            "execution_drill_evidence_partial",
            "execution_drill_evidence_complete",
        ],
        "drill_count": evaluation.drill_count,
        "proven_count": evaluation.proven_count,
        "blocked_count": evaluation.blocked_count,
        "drills": evaluation.drills,
        "oms_exception_scenarios": evaluation.oms_exception_scenarios,
        "oms_exception_coverage_matrix": evaluation.oms_exception_coverage_matrix,
        "blockers": evaluation.blockers,
        "broker_credentials_evidence": evaluation.broker_credentials_evidence,
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


def _read_report(path: Path, root: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _relpath(path, root), "exists": False, "payload": {}}
    try:
        return {"path": _relpath(path, root), "exists": True, "payload": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:  # noqa: BLE001
        return {"path": _relpath(path, root), "exists": True, "payload": {"status": "unreadable_report", "blockers": [type(exc).__name__]}}


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 执行演练证据",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- proven: `{payload.get('proven_count')}` / `{payload.get('drill_count')}`",
        "",
        "| drill | status | first blocker |",
        "| --- | --- | --- |",
    ]
    for drill in _list(payload.get("drills")):
        if isinstance(drill, Mapping):
            blockers = _list_of_str(drill.get("blockers"))
            lines.append(f"| `{drill.get('drill_id')}` | `{drill.get('status')}` | `{blockers[0] if blockers else ''}` |")
    lines.extend(
        [
            "",
            "## OMS Exception Coverage",
            "",
            "| scenario | coverage | reconciliation | first blocker |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in _list(payload.get("oms_exception_coverage_matrix")):
        if isinstance(row, Mapping):
            blockers = _list_of_str(row.get("blockers"))
            reconciliation = "present" if row.get("order_reconciliation_matrix_present") is True else "missing"
            lines.append(
                f"| `{row.get('scenario_id')}` | `{row.get('coverage_status')}` | `{reconciliation}` | `{blockers[0] if blockers else ''}` |"
            )
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


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_us_equity_execution_drill_evidence_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
