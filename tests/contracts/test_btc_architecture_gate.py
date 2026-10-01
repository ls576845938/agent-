from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path("scripts/check_btc_architecture_gate.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("btc_architecture_gate", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_btc_architecture_gate_fixes_64_plus_91_contract_suites_without_unlocking(tmp_path: Path) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def runner(argv, cwd):
        calls.append(list(argv))
        return {"command": " ".join(argv), "returncode": 0, "stdout_tail": "ok", "stderr_tail": ""}

    report = module.build_btc_architecture_gate_report(
        repo_root=tmp_path,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
        runner=runner,
    )

    assert report["schema_version"] == "btc_architecture_gate_v1"
    assert report["ci_passed"] is True
    assert report["expected_contract_test_count_by_suite"] == {
        "gate_security_governance_contracts": 64,
        "runtime_oms_ws_kill_switch_contracts": 91,
    }
    assert report["expected_contract_test_count_total"] == 155
    assert len(calls) == 2
    assert "tests/contracts/test_btc_promotion_gate_control.py" in calls[0]
    assert "tests/contracts/test_btc_perpetual_paper_runtime_replay_report.py" in calls[1]
    assert "tests/contracts/test_btc_true_scalping_ws_l2_raw_capture_quality_report.py::test_ws_l2_raw_capture_quality_builder_blocks_missing_files" in calls[1]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False


def test_btc_architecture_gate_failure_emits_blocker_artifact_shape(tmp_path: Path) -> None:
    module = _load_module()

    def runner(argv, cwd):
        if "test_btc_perpetual_paper_runtime_replay_report.py" in " ".join(argv):
            return {"command": " ".join(argv), "returncode": 1, "stdout_tail": "failed", "stderr_tail": "boom"}
        return {"command": " ".join(argv), "returncode": 0, "stdout_tail": "ok", "stderr_tail": ""}

    report = module.build_btc_architecture_gate_report(
        repo_root=tmp_path,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
        runner=runner,
    )

    assert report["ci_passed"] is False
    assert report["status"] == "fail"
    assert "btc_architecture_gate_suite_failed:runtime_oms_ws_kill_switch_contracts" in report["blockers"]
    failed = next(row for row in report["suite_results"] if row["suite_id"] == "runtime_oms_ws_kill_switch_contracts")
    assert failed["returncode"] == 1
    assert failed["stderr_tail"] == "boom"
    assert report["guardrails"]["paper_queue_write_allowed"] is False
    assert report["guardrails"]["live_unlock_allowed"] is False


def test_btc_architecture_gate_collect_only_adds_pytest_collect_flag(tmp_path: Path) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def runner(argv, cwd):
        calls.append(list(argv))
        return {"command": " ".join(argv), "returncode": 0, "stdout_tail": "collected", "stderr_tail": ""}

    report = module.build_btc_architecture_gate_report(
        repo_root=tmp_path,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
        collect_only=True,
        runner=runner,
    )

    assert report["collect_only"] is True
    assert all("--collect-only" in call for call in calls)
    assert report["ci_passed"] is True
