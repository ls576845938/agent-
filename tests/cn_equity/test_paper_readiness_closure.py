from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_cn.paper import (
    PAPER_SAFETY_FLAGS,
    OfflineKillSwitch,
    build_offline_fixture,
    run_offline_paper_drill,
)
from scripts.build_cn_equity_current_head_gate_report import (
    SAFETY_FLAGS as CURRENT_GATE_SAFETY_FLAGS,
)
from scripts.build_cn_equity_paper_readiness_closure_report import (
    CNPaperReadinessClosureError,
    SCHEMA_PATH,
    _atomic_write,
    _validate_schema,
    _writer_lock,
    compose_paper_readiness_closure_report,
)


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 25, 4, 0, tzinfo=timezone.utc)
HEAD = "7" * 40


def _current_gate(*, head: str = HEAD) -> dict[str, object]:
    roots = [
        {
            "code": "cn_dataready_current_main_manifest_missing",
            "owner": "data_steward",
            "next_action": "publish_formal_cn_dataready_manifest",
            "source_layer": "data",
        },
        {
            "code": "board_lot_rule_missing",
            "owner": "data_steward",
            "next_action": "publish_formal_board_lot_rule",
            "source_layer": "market_rules",
        },
        {
            "code": "real_data_backtest_evidence_not_produced",
            "owner": "researcher",
            "next_action": "produce_real_data_backtest_evidence",
            "source_layer": "backtest",
        },
        {
            "code": "cn_qmt_reconciliation_unproven",
            "owner": "paper_operations",
            "next_action": "prove_qmt_runtime_reconciliation",
            "source_layer": "qmt",
        },
    ]
    return {
        "schema_version": "cn_equity_current_head_gate_report_v1",
        "domain": "cn_equity",
        "generated_at_utc": NOW.isoformat().replace("+00:00", "Z"),
        "source_head": head,
        "data_version": "blocked:no-current-main-cn-dataready",
        "status": "blocked",
        "wrapper_status": "success",
        "decision": "blocked_fail_closed",
        "freshness": "current_head",
        "root_blockers": roots,
        "root_blocker_count": len(roots),
        "input_set_sha256": "a" * 64,
        "safety_flags": dict(CURRENT_GATE_SAFETY_FLAGS),
    }


def _drills():
    return tuple(
        run_offline_paper_drill(
            build_offline_fixture(source_kind, fixed_clock=NOW)
        )
        for source_kind in ("synthetic_fixture", "recorded_fixture")
    )


def _input_hashes() -> dict[str, str]:
    return {
        "quant_cn/paper/__init__.py": "1" * 64,
        "quant_cn/paper/readiness.py": "2" * 64,
        "scripts/build_cn_equity_paper_readiness_closure_report.py": "3"
        * 64,
        "schemas/cn_equity_paper_readiness_closure_report.schema.json": "4"
        * 64,
        ".agent/handoffs/CN-V3-CURRENT-HEAD-GATE-01/integrated.json": "5"
        * 64,
    }


@pytest.mark.parametrize(
    "source_kind",
    ["synthetic_fixture", "recorded_fixture"],
)
def test_offline_drill_exercises_full_chain_without_runtime_capability(
    source_kind: str,
) -> None:
    result = run_offline_paper_drill(
        build_offline_fixture(source_kind, fixed_clock=NOW)
    )

    assert result.status == "quality_checked"
    assert result.decision == "quality_checked_offline_only"
    assert result.reconciliation_status == "reconciled"
    assert result.replay_status == "reconciled"
    assert dict(result.checks) == {
        name: True for name, _ in result.checks
    }
    assert result.lifecycle == (
        "accepted",
        f"fill:fill:cn-paper-{source_kind}-v1",
        "partially_filled",
        "cancel_requested",
        "cancelled",
    )
    assert "cn_paper_offline_fixture_only" in result.blockers
    assert "cn_broker_capability_unproven" in result.blockers
    assert not result.runtime_eligible
    assert not result.paper_start_authorized
    assert not result.promotion_eligible
    assert all(value is False for value in dict(result.safety_flags).values())


def test_offline_drill_is_deterministic_and_fixture_kinds_are_distinct() -> None:
    synthetic = build_offline_fixture(
        "synthetic_fixture",
        fixed_clock=NOW,
    )
    first = run_offline_paper_drill(synthetic)
    second = run_offline_paper_drill(synthetic)
    recorded = run_offline_paper_drill(
        build_offline_fixture("recorded_fixture", fixed_clock=NOW)
    )

    assert first == second
    assert first.evidence_sha256 == second.evidence_sha256
    assert first.fixture_sha256 != recorded.fixture_sha256
    assert first.replay_sha256 != recorded.replay_sha256


def test_kill_switch_fails_closed_for_new_order_admission() -> None:
    result = run_offline_paper_drill(
        build_offline_fixture("synthetic_fixture", fixed_clock=NOW)
    )
    assert dict(result.checks)["kill_switch_blocks_admission"] is True
    assert OfflineKillSwitch().active is False


def test_closure_report_is_valid_but_blocked() -> None:
    report = compose_paper_readiness_closure_report(
        current_head=HEAD,
        generated_at=NOW,
        current_gate=_current_gate(),
        drills=_drills(),
        committed_input_hashes=_input_hashes(),
    )
    _validate_schema(report, ROOT / SCHEMA_PATH)

    codes = {item["code"] for item in report["root_blockers"]}
    assert report["wrapper_status"] == "success"
    assert report["status"] == "blocked"
    assert report["decision"] == "blocked_fail_closed"
    assert report["freshness"] == "current_head"
    assert report["paper_start_authorized"] is False
    assert report["promotion_eligible"] is False
    assert report["readiness"] == {
        "offline_drills_quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
    }
    assert {
        "cn_dataready_current_main_manifest_missing",
        "board_lot_rule_missing",
        "real_data_backtest_evidence_not_produced",
        "cn_qmt_reconciliation_unproven",
        "cn_paper_offline_fixture_only",
        "cn_paper_runtime_observation_missing",
        "cn_paper_manual_approval_missing",
        "paper_start_not_authorized",
    } <= codes
    assert report["dependency_statuses"] == {
        "dataready": "blocked",
        "market_rules": "blocked",
        "research_backtest": "blocked",
        "oms_ledger_replay": "blocked",
        "qmt_broker": "blocked",
        "manual_approval": "blocked",
    }
    assert all(value is False for value in report["safety_flags"].values())


def test_current_gate_head_mismatch_is_rejected() -> None:
    with pytest.raises(
        CNPaperReadinessClosureError,
        match="cn_paper_closure_current_gate_head_mismatch",
    ):
        compose_paper_readiness_closure_report(
            current_head=HEAD,
            generated_at=NOW,
            current_gate=_current_gate(head="8" * 40),
            drills=_drills(),
            committed_input_hashes=_input_hashes(),
        )


def test_unsafe_current_gate_is_rejected() -> None:
    gate = _current_gate()
    gate["safety_flags"] = {
        **CURRENT_GATE_SAFETY_FLAGS,
        "paper_allowed": True,
    }
    with pytest.raises(
        CNPaperReadinessClosureError,
        match="cn_paper_closure_unsafe_flag:current_head_gate",
    ):
        compose_paper_readiness_closure_report(
            current_head=HEAD,
            generated_at=NOW,
            current_gate=gate,
            drills=_drills(),
            committed_input_hashes=_input_hashes(),
        )


def test_both_fixture_kinds_are_required() -> None:
    synthetic = run_offline_paper_drill(
        build_offline_fixture("synthetic_fixture", fixed_clock=NOW)
    )
    with pytest.raises(
        CNPaperReadinessClosureError,
        match="cn_paper_closure_both_fixture_kinds_required",
    ):
        compose_paper_readiness_closure_report(
            current_head=HEAD,
            generated_at=NOW,
            current_gate=_current_gate(),
            drills=(synthetic,),
            committed_input_hashes=_input_hashes(),
        )


def test_writer_lock_prevents_overlapping_latest_writer(
    tmp_path: Path,
) -> None:
    with _writer_lock(tmp_path):
        with pytest.raises(
            CNPaperReadinessClosureError,
            match="cn_paper_closure_writer_lock_conflict",
        ):
            with _writer_lock(tmp_path):
                pass


def test_atomic_publish_preserves_existing_report_on_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "latest" / "report.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")

    def fail() -> None:
        raise RuntimeError("injected_publish_failure")

    with pytest.raises(RuntimeError, match="injected_publish_failure"):
        _atomic_write(path, b"new", before_publish=fail)
    assert path.read_bytes() == b"old"


def test_domain_module_has_no_external_runtime_import_surface() -> None:
    source = (ROOT / "quant_cn/paper/readiness.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imports.isdisjoint(
        {"requests", "socket", "urllib", "websocket", "xtquant"}
    )
    assert all(value is False for value in PAPER_SAFETY_FLAGS.values())
