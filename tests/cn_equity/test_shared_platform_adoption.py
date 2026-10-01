from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_cn.compat.shared_adapter import (
    CN_SHARED_ADAPTER_VERSION,
    SAFETY_FLAGS,
    ReplayEventAdapterInput,
    ReplaySnapshotAdapterInput,
    build_backtest_evidence,
    build_backtest_identity,
    build_evidence_bundle,
    build_evidence_reference,
    build_freshness_assessment,
    build_ledger_record,
    build_read_model_snapshot,
    build_replay_input,
    canonical_cn_payload_hash,
    cn_identity,
    reconcile_cn_ledger,
    require_shared_platform_v2,
    to_shared_utc,
)
from quant_shared.backtest import validate_backtest_evidence


UTC = timezone.utc
CN_TZ = timezone(timedelta(hours=8))
NOW = datetime(2025, 1, 2, 8, tzinfo=UTC)
HEAD = "a" * 40
SHA = "b" * 64
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependency_direction_and_shared_kernel_remain_asset_neutral() -> None:
    adapter = REPO_ROOT / "quant_cn" / "compat" / "shared_adapter.py"
    tree = ast.parse(adapter.read_text(encoding="utf-8"), filename=str(adapter))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any(module.startswith("quant_shared") for module in imports)
    assert not any(
        module.startswith(("quant_us", "quant_crypto", "backend", "frontend"))
        for module in imports
    )

    forbidden = ("qmt", "price_limit", "board_lot", "xshg", "xshe")
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "quant_shared").rglob("*.py")):
        content = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in content:
                violations.append(f"{path.relative_to(REPO_ROOT)}:{token}")
    assert violations == []


def test_shared_version_utc_identity_and_serialization_are_deterministic() -> None:
    assert require_shared_platform_v2() == "shared_platform_v2"
    assert to_shared_utc(
        datetime(2025, 1, 2, 16, tzinfo=CN_TZ),
    ) == NOW
    with pytest.raises(ValueError, match="timezone_aware_timestamp_required"):
        to_shared_utc(datetime(2025, 1, 2))
    identity = cn_identity("security", "CN.SECURITY.600000")
    assert identity.qualified == "cn_equity.security:CN.SECURITY.600000"
    first = canonical_cn_payload_hash(
        {"price": Decimal("10.00"), "event_time": NOW}
    )
    second = canonical_cn_payload_hash(
        {"event_time": NOW, "price": Decimal("10")}
    )
    assert first == second


def test_evidence_and_freshness_adapters_keep_current_head_binding() -> None:
    reference = build_evidence_reference(
        evidence_id="market-semantics",
        path="artifacts/cn/market.json",
        sha256=SHA,
        schema_version="cn_market_v1",
        generated_at=NOW,
        code_commit=HEAD,
    )
    bundle = build_evidence_bundle(
        bundle_id="cn-bundle",
        created_at=NOW,
        references=(reference,),
        data_version="cn-data-v1",
    )
    assert bundle.metadata == {
        "adapter_version": CN_SHARED_ADAPTER_VERSION,
        "data_version": "cn-data-v1",
        "domain_id": "cn_equity",
    }
    freshness = build_freshness_assessment(
        source_id="market-semantics",
        available=True,
        generated_at=NOW,
        code_commit=HEAD,
        dependency_generated_at=(NOW - timedelta(minutes=1),),
        current_head=HEAD,
        evaluated_at=NOW + timedelta(minutes=5),
        max_age=timedelta(hours=1),
    )
    assert freshness.status == "pass"
    blocked = build_freshness_assessment(
        source_id="market-semantics",
        available=True,
        generated_at=NOW,
        code_commit="c" * 40,
        dependency_generated_at=(),
        current_head=HEAD,
        evaluated_at=NOW,
        max_age=timedelta(hours=1),
    )
    assert blocked.status == "blocked"
    assert blocked.blockers == (
        "commit_mismatch:cn_equity.evidence:market-semantics",
    )


def test_ledger_adapter_exports_hashes_not_cn_market_enums() -> None:
    domain_fill = {
        "stable_security_id": "CN.SECURITY.600000",
        "board": "main",
        "price_limit_state": "upper_locked",
        "quantity": 100,
        "price": Decimal("10"),
    }
    record = build_ledger_record(
        stream_id="run-1",
        record_id="fill-1",
        sequence=0,
        occurred_at=NOW,
        record_type="fill",
        domain_record=domain_fill,
        evidence_ids=("market-semantics",),
    )
    assert set(record.payload) == {
        "adapter_version",
        "domain_id",
        "domain_record_hash",
        "evidence_ids",
    }
    assert "board" not in str(record.payload).lower()
    assert "price_limit" not in str(record.payload).lower()
    assert reconcile_cn_ledger((record,), (record,)).reconciled
    changed = build_ledger_record(
        stream_id="run-1",
        record_id="fill-1",
        sequence=0,
        occurred_at=NOW,
        record_type="fill",
        domain_record={**domain_fill, "quantity": 200},
    )
    result = reconcile_cn_ledger((record,), (changed,))
    assert not result.reconciled
    assert result.mismatched == ("cn_equity.ledger:fill-1",)


def test_replay_adapter_accepts_only_ordered_injected_history() -> None:
    snapshot = ReplaySnapshotAdapterInput(
        snapshot_id="snapshot-1",
        as_of=NOW,
        data_version="cn-data-v1",
        domain_payload={"board": "main"},
    )
    first = ReplayEventAdapterInput(
        event_id="event-1",
        occurred_at=NOW,
        event_type="data",
        domain_payload={"price_limit_state": "normal"},
    )
    replay = build_replay_input(
        replay_id="replay-1",
        fixed_clock=NOW + timedelta(minutes=1),
        random_seed=7,
        snapshots=(snapshot,),
        events=(first,),
        parameters={"fee_rate": Decimal("0.0003")},
    )
    assert replay.source_mode == "injected_history"
    assert replay.parameters["parameters_hash"]
    assert "board" not in str(replay.snapshots[0].payload).lower()
    future = ReplayEventAdapterInput(
        event_id="event-2",
        occurred_at=NOW + timedelta(minutes=2),
        event_type="signal",
        domain_payload={},
    )
    with pytest.raises(ValueError, match="replay_input_blocked"):
        build_replay_input(
            replay_id="replay-2",
            fixed_clock=NOW + timedelta(minutes=1),
            random_seed=7,
            snapshots=(snapshot,),
            events=(future,),
            parameters={},
        )


def test_backtest_adapter_preserves_cost_ledger_replay_and_head_gates() -> None:
    identity = build_backtest_identity(
        run_id="run-1",
        strategy_version="strategy-v1",
        data_version="cn-data-v1",
        parameters={"window": 20},
        code_commit=HEAD,
    )
    assert identity.run_id == "cn_equity.backtest:run-1"
    evidence = build_backtest_evidence(
        cost_model="cn-cost-v1",
        slippage_model="cn-slippage-v1",
        decision_time_rule="available_time_lte_decision_time",
        execution_time_rule="next_eligible_event",
        candidate_count=1,
        trial_count=1,
        walk_forward_valid=False,
        no_lookahead_valid=True,
        ledger_reconciled=True,
        ledger_hash=SHA,
        replay_hash=SHA,
        current_head_match=True,
    )
    assert evidence.pnl_source == "ledger_derived"
    assert validate_backtest_evidence(evidence) == ("walk_forward_not_valid",)


def test_read_model_adapter_is_fail_closed_and_asset_neutral() -> None:
    reference = build_evidence_reference(
        evidence_id="evidence-1",
        path="artifacts/cn/evidence.json",
        sha256=SHA,
        schema_version="cn_evidence_v1",
        generated_at=NOW,
        code_commit=HEAD,
    )
    freshness = build_freshness_assessment(
        source_id="read-model",
        available=False,
        generated_at=None,
        code_commit="",
        dependency_generated_at=(),
        current_head=HEAD,
        evaluated_at=NOW,
        max_age=timedelta(hours=1),
    )
    snapshot = build_read_model_snapshot(
        snapshot_id="snapshot-1",
        generated_at=NOW,
        code_commit=HEAD,
        data_version="cn-data-v1",
        status="blocked",
        decision="blocked",
        freshness=freshness,
        blockers=(
            (
                "domain_read_model_missing",
                "a_share_developer",
                "publish_current_head_read_model",
                "no fresh projection",
            ),
        ),
        evidence=(reference,),
        source_manifest_hash=SHA,
    )
    payload = snapshot.to_dict()
    assert payload["domain_id"] == "cn_equity"
    assert payload["status"] == "blocked"
    assert set(payload["metadata"]) == {
        "adapter_version",
        "source_manifest_hash",
    }
    assert all(value is False for value in SAFETY_FLAGS.values())
