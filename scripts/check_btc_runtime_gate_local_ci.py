from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_runtime_gate_local_ci/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_runtime_gate_local_ci_report.json"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_PROMOTION_GATE_PATH = Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json")
DEFAULT_RUNTIME_GAP_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json")
DEFAULT_ORDER_AUDIT_PATH = Path("artifacts/btc_security/latest/btc_order_surface_audit_report.json")


READ_ONLY_BUILD_COMMANDS = [
    ["scripts/build_btc_order_surface_audit.py"],
    ["scripts/build_btc_perpetual_paper_runtime_replay_report.py"],
    ["scripts/build_btc_perpetual_paper_runtime_replay_drill_report.py"],
    ["scripts/build_btc_perpetual_paper_runtime_replay_fixture_drill_report.py"],
    ["scripts/build_btc_perpetual_paper_runtime_reconciliation_report.py"],
    ["scripts/build_btc_exchange_runtime_replay_gap_report.py"],
    ["scripts/build_btc_gate_aggregation_chain.py"],
]

CONTRACT_TEST_COMMAND = [
    "-m",
    "pytest",
    "tests/contracts/test_btc_order_surface_audit.py",
    "tests/contracts/test_btc_perpetual_paper_runtime_replay_report.py",
    "tests/contracts/test_btc_exchange_runtime_replay_gap_report.py",
    "tests/contracts/test_btc_promotion_gate_control.py",
    "tests/contracts/test_btc_gate_aggregation_chain.py",
    "tests/contracts/test_no_broker_import_in_evidence_builders.py",
    "-q",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local read-only BTC runtime/gate CI and emit root-cause-first diagnostics."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument(
        "--strict-promotion",
        action="store_true",
        help="Exit non-zero when the promotion gate remains blocked. Default local mode only checks chain health.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    generated = datetime.now(timezone.utc)
    command_rows = run_local_ci_commands(root=root, include_pytest=not args.skip_pytest)
    promotion = _read_json(root / DEFAULT_PROMOTION_GATE_PATH)
    runtime_gap = _read_json(root / DEFAULT_RUNTIME_GAP_PATH)
    order_audit = _read_json(root / DEFAULT_ORDER_AUDIT_PATH)
    report = build_local_ci_report(
        generated_at_utc=generated,
        command_rows=command_rows,
        promotion=promotion,
        runtime_gap=runtime_gap,
        order_audit=order_audit,
        strict_promotion=args.strict_promotion,
    )
    output = (root / args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / DEFAULT_REPORT_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report["outputs"] = {
        "json": _portable_path(report_path),
        "paper_live_safety_status": _portable_path(safety_path),
    }
    _write_json(report_path, report)
    _write_json(safety_path, _safety_status(report))
    print(json.dumps(_console_payload(report), ensure_ascii=False, indent=2))
    return 0 if report.get("ci_passed") is True else 1


def run_local_ci_commands(*, root: Path, include_pytest: bool) -> list[dict[str, Any]]:
    commands = list(READ_ONLY_BUILD_COMMANDS)
    if include_pytest:
        commands.append(CONTRACT_TEST_COMMAND)
    rows: list[dict[str, Any]] = []
    for command in commands:
        argv = [sys.executable, *command]
        rows.append(_run_command(argv=argv, cwd=root))
    return rows


def build_local_ci_report(
    *,
    generated_at_utc: datetime,
    command_rows: Sequence[Mapping[str, Any]],
    promotion: Mapping[str, Any],
    runtime_gap: Mapping[str, Any],
    order_audit: Mapping[str, Any],
    strict_promotion: bool,
) -> dict[str, Any]:
    command_failures = [row for row in command_rows if _int(row.get("returncode")) != 0]
    freshness = _mapping(promotion.get("artifact_freshness"))
    root_queue = _mapping(promotion.get("root_cause_task_queue"))
    runtime_layers = _mapping(runtime_gap.get("evidence_layers"))
    fixture_layer = _mapping(runtime_layers.get("fixture_capability"))
    historical_layer = _mapping(runtime_layers.get("historical_drill"))
    current_layer = _mapping(runtime_layers.get("current_observe_only_gate_evidence"))
    safety_violations = _list_of_strings(promotion.get("safety_violations"))
    root_causes = _list_of_mappings(promotion.get("root_cause_matrix"))
    gate_blocked = str(promotion.get("status") or "").startswith("blocked") or bool(_list_of_strings(promotion.get("blockers")))
    infrastructure_passed = (
        not command_failures
        and _int(promotion.get("safety_violation_count")) == 0
        and not safety_violations
        and freshness.get("status") == "pass"
        and _int(order_audit.get("finding_count")) == 0
        and fixture_layer.get("passed") is True
        and historical_layer.get("passed") is True
        and current_layer.get("status") in {"pending", "passed"}
    )
    ci_passed = infrastructure_passed and (not strict_promotion or not gate_blocked)
    return {
        "schema_version": "btc_runtime_gate_local_ci_v1",
        "generated_at_utc": generated_at_utc.astimezone(timezone.utc).isoformat(),
        "status": "pass" if ci_passed else "fail",
        "decision": (
            "btc_runtime_gate_local_ci_passed_gate_still_blocked_read_only_no_paper_no_live"
            if infrastructure_passed and gate_blocked and not strict_promotion
            else (
                "btc_runtime_gate_local_ci_passed_strict_promotion"
                if ci_passed
                else "btc_runtime_gate_local_ci_failed_fail_closed_no_paper_no_live"
            )
        ),
        "ci_passed": ci_passed,
        "strict_promotion": strict_promotion,
        "promotion_gate_blocked": gate_blocked,
        "infrastructure_passed": infrastructure_passed,
        "command_failure_count": len(command_failures),
        "artifact_freshness_status": freshness.get("status", ""),
        "safety_violation_count": _int(promotion.get("safety_violation_count")),
        "order_surface_finding_count": _int(order_audit.get("finding_count")),
        "runtime_evidence_layers": {
            "fixture_capability": _layer_summary(fixture_layer),
            "historical_drill": _layer_summary(historical_layer),
            "current_observe_only_gate_evidence": _layer_summary(current_layer),
            "fixture_or_drill_cannot_satisfy_paper_gate": True,
        },
        "root_cause_summary": promotion.get("root_cause_summary", {}),
        "root_cause_task_queue": {
            "dashboard_should_show_root_causes_only": root_queue.get("dashboard_should_show_root_causes_only", True),
            "immediate_development_items": [
                _task_row(row) for row in _list_of_mappings(root_queue.get("immediate_development_items"))
            ],
            "data_wait_items": [_task_row(row) for row in _list_of_mappings(root_queue.get("data_wait_items"))],
        },
        "root_causes": [_root_cause_row(row) for row in root_causes],
        "commands": list(command_rows),
        "gate": _gate(),
        "guardrails": _gate(),
    }


def _run_command(*, argv: Sequence[str], cwd: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
        return {
            "command": " ".join(_display_argv(argv)),
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": " ".join(_display_argv(argv)),
            "returncode": 124,
            "stdout_tail": _tail(exc.stdout or ""),
            "stderr_tail": _tail(exc.stderr or "command timed out"),
        }


def _display_argv(argv: Sequence[str]) -> list[str]:
    if argv and Path(argv[0]).name.lower().startswith("python"):
        return ["py", *[str(item) for item in argv[1:]]]
    return [str(item) for item in argv]


def _console_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "decision": report.get("decision"),
        "ci_passed": report.get("ci_passed"),
        "strict_promotion": report.get("strict_promotion"),
        "promotion_gate_blocked": report.get("promotion_gate_blocked"),
        "command_failure_count": report.get("command_failure_count"),
        "artifact_freshness_status": report.get("artifact_freshness_status"),
        "runtime_evidence_layers": report.get("runtime_evidence_layers"),
        "root_cause_summary": report.get("root_cause_summary"),
        "root_cause_task_queue": report.get("root_cause_task_queue"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "outputs": report.get("outputs", {}),
    }


def _layer_summary(layer: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": layer.get("status", ""),
        "passed": layer.get("passed", False),
        "paper_gate_eligible": layer.get("paper_gate_eligible", False),
        "pending_reason": layer.get("pending_reason", ""),
        "source_path": layer.get("source_path", ""),
    }


def _task_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_id": row.get("root_cause_id", ""),
        "label_cn": row.get("label_cn", ""),
        "owner": row.get("owner", ""),
        "raw_blocker_count": row.get("raw_blocker_count", 0),
        "source_reports": row.get("source_reports", []),
        "next_command": row.get("next_command", ""),
    }


def _root_cause_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_id": row.get("root_cause_id", ""),
        "label_cn": row.get("label_cn", ""),
        "raw_blocker_count": row.get("raw_blocker_count", 0),
        "affected_gates": row.get("affected_gates", []),
        "owner": row.get("owner", ""),
        "source_reports": row.get("source_reports", []),
        "next_command": row.get("next_command", ""),
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_runtime_gate_local_ci_safety_status_v1",
        "generated_at_utc": report.get("generated_at_utc", ""),
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "decision": report.get("decision", ""),
    }


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tail(text: str, *, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _portable_path(path: Path) -> str:
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
