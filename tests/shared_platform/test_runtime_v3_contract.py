from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from quant_shared.runtime.contracts import (
    V3_CONTRACT_VERSION,
    V3_CAPABILITIES,
    ActionAuthorizationV3,
    ReadModelEnvelopeV3,
    RuntimeAuditEventV3,
    RuntimeStateEnvelopeV3,
    validate_blocker_code,
    validate_reason_code,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/governance/shared_platform_v3_compatibility_v1.json"
SCHEMA = ROOT / "schemas/shared_platform_v3_compatibility.schema.json"
UTC = timezone.utc

EXPECTED_DELIVERY_SEQUENCE = [
    {
        "sequence": 0,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-01",
        "owner_scope": "shared developer + independent integrator",
        "acceptance": "ADR/schema/compatibility matrix and shared safety-kernel BTC/US/CN import boundary",
    },
    {
        "sequence": 1,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T1",
        "owner_scope": "quant_shared/runtime",
        "acceptance": "reverse the first three failed probes; after kill allow only proven reduction, opening-order removal, and protection addition",
    },
    {
        "sequence": 2,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T2",
        "owner_scope": "quant_crypto/risk",
        "acceptance": "risk constitution, ActionRiskEffect, portfolio loss, leverage, and protection feasibility pure functions",
    },
    {
        "sequence": 3,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T3",
        "owner_scope": "quant_crypto/portfolio",
        "acceptance": "reuse Forecast/TargetPosition; independent RiskReductionPlan on limits; research and runtime exit share the contract",
    },
    {
        "sequence": 4,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T4",
        "owner_scope": "quant_crypto/application",
        "acceptance": "pure guardian, single-writer supervisor, durable sticky latch; human confirmation alone cannot restore",
    },
    {
        "sequence": 5,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T5",
        "owner_scope": "quant_crypto/oms",
        "acceptance": "progressive OMS migration that retains the large runtime facade and delegates incrementally",
    },
    {
        "sequence": 6,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T6",
        "owner_scope": "BTC application schema -> backend adapter -> integrator",
        "acceptance": "per-action server authorization, stable blockers, idempotency, and operation read model",
    },
    {
        "sequence": 7,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T7",
        "owner_scope": "frontend/src",
        "acceptance": "split the giant workspace without deriving permissions or hardcoded risk values; stopped emergency and accessibility",
    },
    {
        "sequence": 8,
        "ticket_id": "BTC-SHARED-PLATFORM-V3-T8",
        "owner_scope": "researcher review + integrator",
        "acceptance": "rebuild current-HEAD immutable evidence and deterministic replay with cost/exit consistency while retaining the human gate",
    },
]


def test_v3_schema_and_matrix_are_machine_readable() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(config, schema)
    assert config["contract_version"] == V3_CONTRACT_VERSION
    assert tuple(config["capabilities"]) == V3_CAPABILITIES
    assert {row["domain"] for row in config["domains"]} >= {
        "quant_crypto",
        "quant_us",
        "quant_cn",
    }
    assert config["delivery_sequence"] == EXPECTED_DELIVERY_SEQUENCE
    assert all(value is False for value in config["safety_flags"].values())


def test_three_domain_adoption_entries_import_shared_contracts() -> None:
    from quant_cn.compat import shared_adapter as cn_adapter
    from quant_crypto.adapters import shared_platform as btc_adapter
    from quant_us.compat import shared_platform as us_adapter

    assert cn_adapter.require_shared_platform_v2() == "shared_platform_v2"
    assert us_adapter.require_shared_platform_v2() == "shared_platform_v2"
    assert btc_adapter.BTC_SHARED_BOUNDARY_VERSION.startswith("btc_shared_platform_")
    for module in (cn_adapter, btc_adapter, us_adapter):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for name in (node.module,)
        }
        assert "quant_shared" in imported


def test_v2_consumers_keep_their_existing_compatibility_entrypoints() -> None:
    from quant_cn.compat.shared_adapter import require_shared_platform_v2 as require_cn_v2
    from quant_us.compat.shared_platform import require_shared_platform_v2 as require_us_v2

    assert require_us_v2() == "shared_platform_v2"
    assert require_cn_v2() == "shared_platform_v2"


def test_v3_reason_and_blocker_codes_are_stable_and_asset_neutral() -> None:
    assert validate_reason_code("runtime_snapshot_stale") == "runtime_snapshot_stale"
    assert validate_blocker_code("ledger_reconciliation_required") == (
        "ledger_reconciliation_required"
    )
    with pytest.raises(ValueError, match="reason_code_invalid"):
        validate_reason_code("BTC_runtime_blocked")
    with pytest.raises(ValueError, match="blocker_code_invalid"):
        validate_blocker_code("order/submit")


def test_v3_runtime_action_audit_and_read_model_envelopes_validate() -> None:
    now = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)
    state = RuntimeStateEnvelopeV3(
        runtime_id="runtime-1",
        state="blocked",
        active=False,
        opening_allowed=False,
        cancel_only=True,
        worker_alive=False,
        heartbeat_at_utc=now,
        blocker_codes=("runtime_snapshot_stale",),
    )
    decision = ActionAuthorizationV3(
        action="observe",
        allowed=False,
        reason_code="runtime_snapshot_stale",
        blocker_codes=("runtime_snapshot_stale",),
        evaluated_at_utc=now,
    )
    event = RuntimeAuditEventV3(
        event_id="event-1",
        runtime_id="runtime-1",
        sequence=1,
        event_type="state_observed",
        occurred_at_utc=now,
        reason_code="runtime_snapshot_stale",
        payload_hash="a" * 64,
        previous_event_hash=None,
    )
    envelope = ReadModelEnvelopeV3(
        snapshot_id="snapshot-1",
        generated_at_utc=now,
        current_head="b" * 40,
        status="blocked",
        decision="research_only",
        runtime=state,
        action=decision,
        audit_event=event,
        data_version="data-v1",
    )
    payload = envelope.to_dict()
    assert payload["schema_version"] == V3_CONTRACT_VERSION
    assert payload["runtime"]["cancel_only"] is True
    assert payload["action"]["allowed"] is False
    assert payload["audit_event"]["payload_hash"] == "a" * 64


def test_shared_runtime_module_has_no_reverse_asset_or_execution_imports() -> None:
    path = ROOT / "quant_shared/runtime/contracts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = {"quant_crypto", "quant_us", "quant_cn", "backend", "frontend"}
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert [item for item in imports if item.split(".", 1)[0] in forbidden] == []
