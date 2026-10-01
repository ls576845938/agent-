from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_architecture_gate/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_architecture_gate_report.json"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

GATE_GOVERNANCE_TESTS = [
    "tests/contracts/test_btc_gate_report_consistency.py",
    "tests/contracts/test_btc_promotion_gate_control.py",
    "tests/contracts/test_btc_paper_readiness_report.py",
    "tests/contracts/test_btc_current_packet_approval.py",
    "tests/contracts/test_btc_manual_paper_review_approval.py",
    "tests/contracts/test_btc_paper_session_dry_run_manifest.py",
    "tests/contracts/test_btc_operator_root_cause_view.py",
    "tests/contracts/test_btc_api_key_permission_audit.py",
    "tests/contracts/test_btc_order_surface_audit.py",
    "tests/contracts/test_no_broker_import_in_evidence_builders.py",
    "tests/contracts/test_btc_root_cause_dag.py",
    "tests/contracts/test_btc_promotion_gate_root_cause_ci.py",
]

RUNTIME_OMS_WS_TESTS = [
    "tests/contracts/test_btc_exchange_runtime_contract.py",
    "tests/contracts/test_btc_exchange_public_runtime_dry_probe.py",
    "tests/contracts/test_btc_exchange_runtime_replay_gap_report.py",
    "tests/contracts/test_btc_exchange_paper_runtime_replay_report.py",
    "tests/contracts/test_btc_perpetual_paper_runtime_replay_report.py",
    "tests/contracts/test_btc_perpetual_paper_runtime_reconciliation.py",
    "tests/contracts/test_btc_paper_oms_lifecycle.py",
    "tests/contracts/test_btc_paper_oms_session_reconciliation.py",
    "tests/contracts/test_btc_execution_quality.py",
    "tests/contracts/test_btc_paper_exchange_rule_preflight.py",
    "tests/contracts/test_btc_paper_account_runtime_attestation.py",
    "tests/contracts/test_btc_paper_live_kill_switch_status.py",
    "tests/contracts/test_btc_micro_live_preflight.py",
    "tests/contracts/test_btc_runtime_gate_local_ci.py",
    "tests/contracts/test_btc_true_scalping_ws_order_book_replay_report.py",
    "tests/contracts/test_btc_true_scalping_ws_reconnect_resync_policy_report.py",
    "tests/contracts/test_btc_true_scalping_ws_latency_queue_diagnostics_report.py",
    "tests/contracts/test_btc_true_scalping_ws_l2_capture_coverage_report.py",
    "tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py::test_btc_true_scalping_ws_l2_raw_capture_quality_schema_valid",
    "tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py::test_current_btc_true_scalping_ws_l2_raw_capture_quality_keeps_scalping_locked",
    "tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py::test_ws_l2_raw_capture_quality_builder_accepts_format_but_blocks_replay_and_history",
    "tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py::test_ws_l2_raw_capture_quality_builder_blocks_missing_files",
]

ARCHITECTURE_SUITES = [
    {
        "suite_id": "gate_security_governance_contracts",
        "label": "Gate consistency, promotion control, paper readiness, API key, order surface",
        "expected_contract_test_count": 64,
        "selectors": GATE_GOVERNANCE_TESTS,
        "coverage": [
            "gate_consistency",
            "promotion_control",
            "paper_readiness",
            "manual_approval",
            "dry_run_manifest",
            "api_key_redaction",
            "order_surface",
            "root_cause_dashboard",
            "no_broker_import",
        ],
    },
    {
        "suite_id": "runtime_oms_ws_kill_switch_contracts",
        "label": "Runtime replay, OMS, reconciliation, public runtime, WS, kill switch",
        "expected_contract_test_count": 91,
        "selectors": RUNTIME_OMS_WS_TESTS,
        "coverage": [
            "runtime_replay_fixture",
            "oms_lifecycle",
            "session_reconciliation",
            "public_runtime_dry_probe",
            "exchange_runtime_gap",
            "paper_exchange_rule",
            "account_attestation",
            "kill_switch",
            "micro_live_preflight",
            "ws_gapfill",
        ],
    },
]


Runner = Callable[[Sequence[str], Path], Mapping[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fixed BTC architecture gate contract suites.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--collect-only", action="store_true", help="Collect tests without executing them.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    report = build_btc_architecture_gate_report(
        repo_root=root,
        generated_at_utc=datetime.now(timezone.utc),
        collect_only=args.collect_only,
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
    return 0 if report["ci_passed"] else 1


def build_btc_architecture_gate_report(
    *,
    repo_root: Path,
    generated_at_utc: datetime,
    collect_only: bool = False,
    runner: Runner | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    run = runner or _run_command
    command_results = []
    for suite in ARCHITECTURE_SUITES:
        argv = _pytest_argv(suite["selectors"], collect_only=collect_only)
        result = dict(run(argv, root))
        result["suite_id"] = suite["suite_id"]
        result["label"] = suite["label"]
        result["expected_contract_test_count"] = suite["expected_contract_test_count"]
        result["selector_count"] = len(suite["selectors"])
        result["selectors"] = list(suite["selectors"])
        result["coverage"] = list(suite["coverage"])
        command_results.append(result)
    blockers = [
        f"btc_architecture_gate_suite_failed:{row['suite_id']}"
        for row in command_results
        if _int(row.get("returncode")) != 0
    ]
    ci_passed = not blockers
    return {
        "schema_version": "btc_architecture_gate_v1",
        "generated_at_utc": generated_at_utc.astimezone(timezone.utc).isoformat(),
        "status": "pass" if ci_passed else "fail",
        "decision": (
            "btc_architecture_gate_passed_read_only_no_paper_no_live"
            if ci_passed
            else "btc_architecture_gate_failed_blocker_artifact_emitted_no_paper_no_live"
        ),
        "ci_passed": ci_passed,
        "collect_only": collect_only,
        "suite_count": len(ARCHITECTURE_SUITES),
        "expected_contract_test_count_total": sum(_int(suite["expected_contract_test_count"]) for suite in ARCHITECTURE_SUITES),
        "expected_contract_test_count_by_suite": {
            str(suite["suite_id"]): _int(suite["expected_contract_test_count"]) for suite in ARCHITECTURE_SUITES
        },
        "coverage": sorted({item for suite in ARCHITECTURE_SUITES for item in suite["coverage"]}),
        "suite_results": command_results,
        "blockers": blockers,
        "gate": _gate(),
        "guardrails": _gate(),
        "warnings": ["btc_architecture_gate_read_only_no_paper_no_live"],
    }


def _pytest_argv(selectors: Sequence[str], *, collect_only: bool) -> list[str]:
    argv = [sys.executable, "-m", "pytest"]
    if collect_only:
        argv.extend(["--collect-only"])
    argv.extend([*selectors, "-q"])
    return argv


def _run_command(argv: Sequence[str], cwd: Path) -> dict[str, Any]:
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
            timeout=900,
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


def _console_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "decision": report.get("decision"),
        "ci_passed": report.get("ci_passed"),
        "collect_only": report.get("collect_only"),
        "expected_contract_test_count_by_suite": report.get("expected_contract_test_count_by_suite"),
        "blockers": report.get("blockers", []),
        "outputs": report.get("outputs", {}),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_architecture_gate_safety_status_v1",
        "generated_at_utc": report.get("generated_at_utc", ""),
        "status": report.get("status"),
        "decision": report.get("decision"),
        **_gate(),
        "blockers": list(report.get("blockers", [])),
    }


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _display_argv(argv: Sequence[str]) -> list[str]:
    if argv and Path(argv[0]).name.lower().startswith("python"):
        return ["py", *[str(item) for item in argv[1:]]]
    return [str(item) for item in argv]


def _tail(text: str, *, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _portable_path(path: Path) -> str:
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
