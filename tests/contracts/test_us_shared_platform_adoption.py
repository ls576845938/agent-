from __future__ import annotations

import ast
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

from quant_shared.core import ensure_utc as shared_ensure_utc
from quant_shared.core import utc_now as shared_utc_now
from quant_us.compat.shared_platform import (
    SAFETY_FLAGS,
    ReplayEventAdapterInput,
    ReplaySnapshotAdapterInput,
    build_evidence_bundle,
    build_evidence_reference,
    build_freshness_assessment,
    build_ledger_record,
    build_read_model_snapshot,
    build_replay_input,
    canonical_us_payload_hash,
    reconcile_us_ledger,
    require_shared_platform_v2,
    to_shared_utc,
    us_identity,
)
from quant_us.core import clock as legacy_clock
from quant_us.core.enums import (
    OrderSide,
    OrderType,
    SignalDirection,
    TimeInForce,
)
from quant_us.core.types import OrderIntent, RiskDecision, Signal, TargetPosition


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/governance/us_shared_platform_adoption_v1.json"
SCHEMA = ROOT / "schemas/us_shared_platform_adoption.schema.json"
UTC = timezone.utc
ET = timezone(timedelta(hours=-5))
NOW = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
HEAD = "a" * 40
SHA = "b" * 64


def test_adapter_dependency_direction_and_shared_reverse_dependency() -> None:
    adapter = ROOT / "quant_us/compat/shared_platform.py"
    tree = ast.parse(adapter.read_text(encoding="utf-8"), filename=str(adapter))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any(module.startswith("quant_shared") for module in imports)
    assert not any(
        module.startswith(("quant_crypto", "quant_cn", "backend", "frontend"))
        for module in imports
    )

    reverse_dependencies: list[str] = []
    for path in sorted((ROOT / "quant_shared").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "quant_us" in source:
            reverse_dependencies.append(path.relative_to(ROOT).as_posix())
    assert reverse_dependencies == []


def test_legacy_utc_facade_uses_shared_implementation_without_breaking_naive_inputs() -> None:
    assert legacy_clock.ensure_utc is shared_ensure_utc
    assert legacy_clock.utc_now is shared_utc_now
    assert legacy_clock.ensure_utc(datetime(2026, 1, 2, 14, 30)) == NOW
    assert to_shared_utc(datetime(2026, 1, 2, 9, 30, tzinfo=ET)) == NOW
    with pytest.raises(ValueError, match="timezone_aware_timestamp_required"):
        to_shared_utc(datetime(2026, 1, 2, 14, 30))


def test_shared_version_identity_and_serialization_are_deterministic() -> None:
    assert require_shared_platform_v2() == "shared_platform_v2"
    identity = us_identity("security", "US.SECURITY.SPY")
    assert identity.qualified == "us_equity.security:US.SECURITY.SPY"
    windows = canonical_us_payload_hash(
        {
            "price": Decimal("10.00"),
            "event_time": NOW,
            "artifact": Path(r"C:\repo\artifacts\evidence.json"),
        }
    )
    posix = canonical_us_payload_hash(
        {
            "artifact": Path("C:/repo/artifacts/evidence.json"),
            "event_time": NOW,
            "price": Decimal("10"),
        }
    )
    assert windows == posix


def test_evidence_ledger_replay_and_read_model_adapters_are_fail_closed() -> None:
    reference = build_evidence_reference(
        evidence_id="evidence-1",
        path=r"artifacts\us\evidence.json",
        sha256=SHA,
        schema_version="us_evidence_v1",
        generated_at=NOW,
        code_commit=HEAD,
    )
    bundle = build_evidence_bundle(
        bundle_id="bundle-1",
        created_at=NOW,
        references=(reference,),
        data_version="fixture-v1",
    )
    assert reference.path == "artifacts/us/evidence.json"
    assert bundle.metadata["domain_id"] == "us_equity"

    expected = build_ledger_record(
        stream_id="stream-1",
        record_id="fill-1",
        sequence=0,
        occurred_at=NOW,
        record_type="fill",
        domain_record={
            "symbol": "SPY",
            "session": "regular",
            "quantity": 1,
            "price": Decimal("500"),
        },
        evidence_ids=("evidence-1",),
    )
    assert set(expected.payload) == {
        "adapter_version",
        "domain_id",
        "domain_record_hash",
        "evidence_ids",
    }
    assert "regular" not in str(expected.payload)
    assert reconcile_us_ledger((expected,), (expected,)).reconciled

    snapshot = ReplaySnapshotAdapterInput(
        snapshot_id="snapshot-1",
        as_of=NOW,
        data_version="fixture-v1",
        domain_payload={"calendar": "XNYS"},
    )
    event = ReplayEventAdapterInput(
        event_id="event-1",
        occurred_at=NOW,
        event_type="signal",
        domain_payload={"corporate_action_adjusted": True},
    )
    replay = build_replay_input(
        replay_id="replay-1",
        fixed_clock=NOW + timedelta(minutes=1),
        random_seed=7,
        snapshots=(snapshot,),
        events=(event,),
        parameters={"fee_rate": Decimal("0.0001")},
    )
    assert replay.source_mode == "injected_history"
    assert "XNYS" not in str(replay.snapshots[0].payload)
    future = ReplayEventAdapterInput(
        event_id="event-2",
        occurred_at=NOW + timedelta(minutes=2),
        event_type="order",
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
    read_model = build_read_model_snapshot(
        snapshot_id="read-model-1",
        generated_at=NOW,
        code_commit=HEAD,
        data_version="fixture-v1",
        status="blocked",
        decision="research_only",
        freshness=freshness,
        blockers=(
            (
                "domain_read_model_missing",
                "super_developer",
                "publish_current_head_read_model",
                "no fresh projection",
            ),
        ),
        evidence=(reference,),
        source_manifest_hash=SHA,
    )
    assert read_model.domain_id == "us_equity"
    assert read_model.status == "blocked"
    assert all(value is False for value in SAFETY_FLAGS.values())


def test_migration_matrix_preserves_us_types_and_btc_wire_compatibility() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    jsonschema.validate(config, json.loads(SCHEMA.read_text(encoding="utf-8")))
    rows = {row["legacy_symbol"]: row for row in config["migration_matrix"]}
    required = {
        "quant_us.core.clock.ensure_utc",
        "quant_us.core.types.Signal",
        "quant_us.core.types.TargetPosition",
        "quant_us.core.types.OrderIntent",
        "quant_us.core.types.RiskDecision",
        "quant_us.core.enums.OrderSide",
        "quant_us.core.enums.OrderType",
        "quant_us.core.enums.SignalDirection",
        "quant_us.core.enums.TimeInForce",
    }
    assert required <= rows.keys()
    assert all(row["btc_dependents"] == [] for row in rows.values())
    assert config["deferred_breaking_cleanup"] == {
        "required": False,
        "status": "completed",
        "owner": "integrator",
        "ticket_condition": (
            "Completed by the validated BTC current-main forward-port successor; "
            "no BTC runtime imports or class-identity dependency on quant_us remain."
        ),
        "btc_contract_module": "quant_crypto.trading_contracts",
        "completion_handoff": (
            "published-btc-v3-current-main-forwardport-successor-05-8adf033a2"
        ),
    }
    assert all(config["safety"][flag] is False for flag in config["safety"])

    btc_bridge = importlib.import_module("quant_crypto.adapters.legacy_quant_us")
    btc_contracts = importlib.import_module("quant_crypto.trading_contracts")
    dataclass_pairs = (
        (btc_bridge.Signal, btc_contracts.Signal, Signal),
        (btc_bridge.TargetPosition, btc_contracts.TargetPosition, TargetPosition),
        (btc_bridge.OrderIntent, btc_contracts.OrderIntent, OrderIntent),
        (btc_bridge.RiskDecision, btc_contracts.RiskDecision, RiskDecision),
    )
    for bridge_type, btc_type, us_type in dataclass_pairs:
        assert bridge_type is btc_type
        assert btc_type is not us_type
        assert [item.name for item in fields(btc_type)] == [
            item.name for item in fields(us_type)
        ]

    enum_pairs = (
        (btc_bridge.OrderSide, btc_contracts.OrderSide, OrderSide),
        (btc_bridge.OrderType, btc_contracts.OrderType, OrderType),
        (btc_bridge.SignalDirection, btc_contracts.SignalDirection, SignalDirection),
        (btc_bridge.TimeInForce, btc_contracts.TimeInForce, TimeInForce),
    )
    for bridge_type, btc_type, us_type in enum_pairs:
        assert bridge_type is btc_type
        assert btc_type is not us_type
        assert [item.value for item in btc_type] == [item.value for item in us_type]


def test_read_only_validator_accepts_contract() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_us_shared_platform_adoption.py",
            "--config",
            str(CONFIG),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["status"] == "valid"
    assert output["quant_shared_reverse_dependencies"] == 0
    assert output["safety_flags_all_false"] is True
