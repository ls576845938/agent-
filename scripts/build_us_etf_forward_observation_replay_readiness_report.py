#!/usr/bin/env python3
"""Build replay-readiness audit for US ETF forward observation.

This is a static evidence check. It does not recalculate alpha, access current
market data, call broker/private/order endpoints, or grant paper/live approval.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_etf_forward_observation_replay_readiness_v1"
DEFAULT_LEDGER_ROOT = Path("data/forward_observation/us_etf_rotation_v1")
DEFAULT_ROLL_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json")
DEFAULT_EVALUATION_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_VALIDATION_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json")
DEFAULT_MONITORING_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 Forward Observation Replay 预检.md")
REQUIRED_REPLAY_INPUTS = ["data_snapshot", "strategy_version", "params", "risk_config", "current_position", "orders_and_fills"]
REQUIRED_REPLAY_OUTPUTS = ["replayed_signal", "replayed_target_position", "replayed_risk_decision", "diff_vs_original_artifact"]


def build_us_etf_forward_observation_replay_readiness_report(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    roll_report: Path = DEFAULT_ROLL_REPORT,
    evaluation_report: Path = DEFAULT_EVALUATION_REPORT,
    validation_report: Path = DEFAULT_VALIDATION_REPORT,
    monitoring_report: Path = DEFAULT_MONITORING_REPORT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    roll = _read_json(_resolve(root, roll_report))
    evaluation = _read_json(_resolve(root, evaluation_report))
    validation = _read_json(_resolve(root, validation_report))
    monitoring = _read_json(_resolve(root, monitoring_report))
    state = _read_json(ledger / "validation_state.json")
    targets = _read_jsonl(ledger / "target_positions.jsonl")
    fills = _read_jsonl(ledger / "fills.jsonl")
    snapshots = _read_jsonl(ledger / "portfolio_snapshots.jsonl")

    latest_target = targets[-1] if targets else {}
    latest_snapshot = snapshots[-1] if snapshots else {}
    checks = {
        "ledger_artifacts_present": _check_ledger_artifacts(ledger),
        "latest_target_replay_inputs": _check_target_inputs(latest_target),
        "fills_replay_inputs": _check_fills(fills, latest_target),
        "snapshot_replay_inputs": _check_snapshot(latest_snapshot),
        "roll_report_replay_context": _check_roll(roll),
        "validation_report_context": _check_validation(validation),
        "monitoring_replay_contract": _check_monitoring(monitoring),
        "fixed_replay_contract": {
            "passed": True,
            "fixed_clock": generated,
            "fixed_random_seed": 0,
            "access_current_realtime_data": False,
        },
        "unsafe_flags": _check_no_unsafe_flags(
            {
                "roll": roll,
                "evaluation": evaluation,
                "validation": validation,
                "monitoring": monitoring,
                "state": state,
                "targets": targets,
                "fills": fills,
                "snapshots": snapshots,
            }
        ),
    }
    blockers = [f"replay_readiness_{name}_failed" for name, check in checks.items() if not bool(check.get("passed", False))]
    status = "replay_readiness_pass" if not blockers else "replay_readiness_blocked"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "strategy_id": state.get("strategy_id") or roll.get("strategy_id"),
        "candidate_variant": state.get("candidate_variant") or roll.get("candidate_variant"),
        "status": status,
        "decision": "replay_inputs_available_for_manual_audit" if status == "replay_readiness_pass" else "repair_replay_evidence",
        "replay_scope": {
            "static_evidence_check_only": True,
            "alpha_recalculated": False,
            "current_realtime_data_accessed": False,
            "fixed_clock": generated,
            "fixed_random_seed": 0,
            "required_inputs": REQUIRED_REPLAY_INPUTS,
            "required_outputs": REQUIRED_REPLAY_OUTPUTS,
        },
        "latest_observation": {
            "timestamp": latest_target.get("timestamp") or latest_snapshot.get("timestamp"),
            "target_count": _nested(latest_target, "target_position.target_count"),
            "fill_count": len([fill for fill in fills if fill.get("timestamp") == latest_target.get("timestamp")]),
            "snapshot_reconciliation_status": latest_snapshot.get("reconciliation_status"),
        },
        "checks": checks,
        "blockers": _dedupe(blockers),
        "source_files": {
            "ledger_root": _relpath(ledger, root),
            "target_positions": _relpath(ledger / "target_positions.jsonl", root),
            "fills": _relpath(ledger / "fills.jsonl", root),
            "portfolio_snapshots": _relpath(ledger / "portfolio_snapshots.jsonl", root),
            "validation_state": _relpath(ledger / "validation_state.json", root),
            "roll_report": _relpath(_resolve(root, roll_report), root),
            "evaluation_report": _relpath(_resolve(root, evaluation_report), root),
            "validation_report": _relpath(_resolve(root, validation_report), root),
            "monitoring_report": _relpath(_resolve(root, monitoring_report), root),
        },
        "guardrails": {
            "replay_readiness_only": True,
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


def _check_ledger_artifacts(ledger: Path) -> dict[str, Any]:
    files = ["target_positions.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl", "validation_state.json"]
    missing = [name for name in files if not (ledger / name).exists()]
    return {"passed": not missing, "missing": missing}


def _check_target_inputs(row: Mapping[str, Any]) -> dict[str, Any]:
    required = ["timestamp", "strategy_id", "candidate_variant", "target_position", "current_position", "rebalance", "reason"]
    missing = [field for field in required if field not in row]
    target = _mapping(row.get("target_position"))
    target_missing = [field for field in ["date", "weights", "prices", "shares", "notionals", "target_count"] if field not in target]
    return {"passed": bool(row) and not missing and not target_missing, "missing": missing, "target_missing": target_missing}


def _check_fills(fills: list[Mapping[str, Any]], latest_target: Mapping[str, Any]) -> dict[str, Any]:
    ts = latest_target.get("timestamp")
    latest = [fill for fill in fills if fill.get("timestamp") == ts]
    required = ["timestamp", "strategy_id", "candidate_variant", "symbol", "side", "quantity", "price", "notional", "simulated_only"]
    failures = []
    for fill in latest:
        missing = [field for field in required if field not in fill]
        if missing:
            failures.append({"symbol": fill.get("symbol"), "missing": missing})
    turnover = float(_nested(latest_target, "rebalance.turnover", 0.0) or 0.0)
    return {"passed": (turnover <= 1e-12 or bool(latest)) and not failures, "latest_fill_count": len(latest), "failures": failures}


def _check_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    required = ["timestamp", "strategy_id", "prior_equity", "equity", "estimated_slippage", "estimated_financing_daily", "reconciliation_status"]
    missing = [field for field in required if field not in row]
    return {"passed": bool(row) and not missing and row.get("reconciliation_status") == "clean", "missing": missing, "reconciliation_status": row.get("reconciliation_status")}


def _check_roll(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "passed": bool(report) and report.get("status") == "PASS" and _nested(report, "guardrails.paper_or_live_unlock_allowed") is False,
        "status": report.get("status"),
        "cycle_status": report.get("cycle_status"),
    }


def _check_validation(report: Mapping[str, Any]) -> dict[str, Any]:
    selected_variant = (
        _first_present(report, "selected_variant")
        or _first_present(report, "selected_constrained_variant")
        or _first_present(report, "recommended_research_variant")
    )
    has_context = bool(report.get("base_strategy_id") and selected_variant)
    return {"passed": bool(report) and has_context, "base_strategy_id": report.get("base_strategy_id"), "selected_variant": selected_variant}


def _first_present(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if value.get(key):
            return value[key]
        for child in value.values():
            found = _first_present(child, key)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_present(child, key)
            if found:
                return found
    return None


def _check_monitoring(report: Mapping[str, Any]) -> dict[str, Any]:
    inputs = _list_of_str(_nested(report, "replay_requirements.inputs", []))
    outputs = _list_of_str(_nested(report, "replay_requirements.outputs", []))
    return {
        "passed": all(item in inputs for item in REQUIRED_REPLAY_INPUTS) and all(item in outputs for item in REQUIRED_REPLAY_OUTPUTS),
        "inputs": inputs,
        "outputs": outputs,
    }


def _check_no_unsafe_flags(payloads: Mapping[str, Any]) -> dict[str, Any]:
    unsafe = []
    keys = {"live_order_allowed", "paper_or_live_unlock_allowed", "paper_simulation_allowed", "private_endpoint_used", "order_endpoint_used", "real_order_submitted", "broker_calls_used"}
    for name, payload in payloads.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in keys and value is True:
                unsafe.append(f"{name}.{path}=true")
    return {"passed": not unsafe, "unsafe_flags": unsafe}


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US ETF 轮动 Forward Observation Replay 预检",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- latest observation：`{_nested(payload, 'latest_observation.timestamp')}`",
        "",
        "## Checks",
        "",
    ]
    for name, check in _mapping(payload.get("checks")).items():
        lines.append(f"- `{name}`：passed=`{_mapping(check).get('passed')}`")
    lines += ["", "## Blockers", ""]
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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


def _nested(payload: Any, dotted: str, default: Any = None) -> Any:
    current = payload
    for key in dotted.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}[{idx}]"))
    else:
        out.append((prefix, value))
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US ETF forward-observation replay readiness report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--roll-report", default=str(DEFAULT_ROLL_REPORT))
    parser.add_argument("--evaluation-report", default=str(DEFAULT_EVALUATION_REPORT))
    parser.add_argument("--validation-report", default=str(DEFAULT_VALIDATION_REPORT))
    parser.add_argument("--monitoring-report", default=str(DEFAULT_MONITORING_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_etf_forward_observation_replay_readiness_report(
        repo_root=Path(args.repo_root),
        ledger_root=Path(args.ledger_root),
        roll_report=Path(args.roll_report),
        evaluation_report=Path(args.evaluation_report),
        validation_report=Path(args.validation_report),
        monitoring_report=Path(args.monitoring_report),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
