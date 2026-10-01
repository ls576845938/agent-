#!/usr/bin/env python3
"""Service layer for the US equity paper-simulation readiness report.

The service assembles existing gate evidence into a fail-closed report. It
never starts the paper runner and never unlocks live trading.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.paper_simulation_readiness import (
    PAPER_LEDGER_ROOT,
    STRATEGY_ID,
    evaluate_paper_simulation_readiness,
)


SCHEMA_VERSION = "us_equity_paper_simulation_readiness_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 纸面模拟门禁.md")
DEFAULT_MANUAL_REVIEW = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json")
DEFAULT_STRATEGY_GATE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_FORWARD_EVALUATION = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"
)
DEFAULT_SMALL_ACCOUNT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"
)
DEFAULT_PRODUCTION_PIT_INTAKE_STATUS = Path(
    "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json"
)
DEFAULT_PIT_BUNDLE_ACCEPTANCE = Path(
    "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"
)
DEFAULT_BLOCKER_TAXONOMY = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"
)
DEFAULT_MANUAL_DECISION_RECORD = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json"
)


def build_us_equity_paper_simulation_readiness_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    manual_review: Path = DEFAULT_MANUAL_REVIEW,
    manual_decision_record: Path = DEFAULT_MANUAL_DECISION_RECORD,
    strategy_gate: Path = DEFAULT_STRATEGY_GATE,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    small_account_preflight: Path = DEFAULT_SMALL_ACCOUNT,
    production_pit_intake_status: Path = DEFAULT_PRODUCTION_PIT_INTAKE_STATUS,
    pit_bundle_acceptance: Path = DEFAULT_PIT_BUNDLE_ACCEPTANCE,
    blocker_taxonomy: Path = DEFAULT_BLOCKER_TAXONOMY,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "manual_review": _resolve(root, manual_review),
        "manual_decision_record": _resolve(root, manual_decision_record),
        "strategy_gate": _resolve(root, strategy_gate),
        "forward_evaluation": _resolve(root, forward_evaluation),
        "small_account_preflight": _resolve(root, small_account_preflight),
        "production_pit_intake_status": _resolve(root, production_pit_intake_status),
        "pit_bundle_acceptance": _resolve(root, pit_bundle_acceptance),
        "blocker_taxonomy": _resolve(root, blocker_taxonomy),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}
    evaluation = evaluate_paper_simulation_readiness(reports)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": evaluation.status,
        "asset": "us_equity",
        "strategy_id": STRATEGY_ID,
        "paper_runner_allowed": False,
        "paper_ledger_root": _relpath(_resolve(root, PAPER_LEDGER_ROOT), root),
        "decision": evaluation.decision,
        "required_runner_contract": evaluation.required_runner_contract,
        "required_ledger_evidence_contract": evaluation.required_ledger_evidence_contract,
        "blockers": evaluation.blockers,
        "unsafe_flags": evaluation.unsafe_flags,
        "manual_review_evidence": evaluation.manual_review_evidence,
        "remediation_tickets": evaluation.remediation_tickets,
        "paper_start_gate_matrix": evaluation.paper_start_gate_matrix,
        "guardrails": evaluation.guardrails,
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    remediation = _mapping(payload.get("remediation_tickets"))
    ledger_contract = _mapping(payload.get("required_ledger_evidence_contract"))
    lines = [
        "# US Equity 纸面模拟门禁",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- paper ledger root：`{payload.get('paper_ledger_root', '')}`",
        f"- remediation tickets：`{remediation.get('ticket_count')}`",
        "",
        "本报告不启动 paper runner，只定义启动前门禁。",
        "",
        "## Required Ledger Evidence",
        "",
        "| item | requirement |",
        "| --- | --- |",
        f"| ledger root | `{ledger_contract.get('ledger_root', '')}` |",
        f"| files | `{', '.join(str(item) for item in _list(ledger_contract.get('required_files')))}` |",
        f"| reconciliation | `{', '.join(str(item) for item in _list(ledger_contract.get('required_reconciliation_checks')))}` |",
        f"| simulated fills only | `{ledger_contract.get('simulated_fills_only')}` |",
        f"| live ready claim allowed | `{ledger_contract.get('live_ready_claim_allowed')}` |",
        "",
        "## Paper Start Gate Matrix",
        "",
        "| gate | passed | blocker |",
        "| --- | ---: | --- |",
    ]
    for gate in _list(payload.get("paper_start_gate_matrix")):
        if isinstance(gate, Mapping):
            lines.append(f"| `{gate.get('gate_id')}` | `{gate.get('passed')}` | `{gate.get('blocker')}` |")
    lines.extend(["", "## Blockers", ""])
    blockers = _list(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- 无"])
    lines.extend(["", "## Remediation Tickets", ""])
    tickets = [item for item in _list(remediation.get("tickets")) if isinstance(item, Mapping)]
    if tickets:
        for ticket in tickets:
            lines.append(
                f"- `{ticket.get('ticket_id')}`：`{ticket.get('status')}`，owner=`{ticket.get('owner')}`，"
                f"dependency=`{ticket.get('dependency_type')}`"
            )
    else:
        lines.append("- None")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "unreadable", "read_error": type(exc).__name__}
    return dict(payload) if isinstance(payload, Mapping) else {"schema_version": "unreadable"}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
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


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
