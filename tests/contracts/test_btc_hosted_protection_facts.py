from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from quant_crypto.application.hosted_protection_facts import (
    HOSTED_PROTECTION_FACTS_SCHEMA_VERSION,
    normalize_hosted_protection_facts,
)


SOURCE_HEAD = "a" * 40
ACCOUNT_HASH = "b" * 64
SNAPSHOT_HASH = "c" * 64


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _case(*, position_side: str = "long") -> dict[str, object]:
    parent = f"btc-parent-{position_side}"
    algo_client = f"{parent}A"
    algo_id = f"algo-{position_side}"
    side = "sell" if position_side == "long" else "buy"
    opening_side = "buy" if position_side == "long" else "sell"
    binding = {
        "runtime_identity": "v1-offline",
        "run_id": "v1-protection-facts",
        "source_head": SOURCE_HEAD,
        "account_identity_hash": ACCOUNT_HASH,
        "liveness_epoch": 7,
        "strategy_id": "long_short_donchian_top5",
        "strategy_version": "v1",
    }
    row = {
        "algo_id": algo_id,
        "algo_client_order_id": algo_client,
        "parent_client_order_id": parent,
        "instrument_id": "BTC-USDT-SWAP",
        "side": side,
        "position_side": position_side,
        "size": "0.01",
        "order_type": "oco",
        "state": "live",
        "reduce_only": None,
        "reduce_only_status": "unknown",
        "updated_at_ms": "",
    }
    owner = {
        "algo_id": algo_id,
        "algo_client_order_id": algo_client,
        "parent_client_order_id": parent,
        "instrument_id": "BTC-USDT-SWAP",
        "opening_intent": True,
        "status": "active",
        "fact_binding": binding,
    }
    receipt = {
        "status": "exchange_accepted",
        "parent_client_order_id": parent,
        "algo_id": algo_id,
        "algo_client_order_id": algo_client,
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": position_side,
        "contracts": "0.01",
        "fact_binding": binding,
    }
    parent_intent = {
        "status": "terminal",
        "client_order_id": parent,
        "risk_reducing_only": False,
        "fact_binding": binding,
        "order": {
            "instId": "BTC-USDT-SWAP",
            "side": opening_side,
            "posSide": position_side,
            "sz": "0.01",
            "clOrdId": parent,
        },
    }
    return {
        "pending_algo_orders": [row],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": position_side,
                "contracts": "0.01",
            }
        ],
        "account": {
            "position_mode": "long_short_mode",
            "identity": {"hash": ACCOUNT_HASH},
        },
        "runtime_facts": {
            "runtime_identity": "v1-offline",
            "run_id": "v1-protection-facts",
            "source_head": SOURCE_HEAD,
            "authoritative_liveness_epoch": 7,
            "strategy_id": "long_short_donchian_top5",
            "strategy_version": "v1",
        },
        "ownership_facts": {
            "schema_version": HOSTED_PROTECTION_FACTS_SCHEMA_VERSION,
            "snapshot_sha256": SNAPSHOT_HASH,
            "fact_binding": binding,
            "owned_attached_algos": {algo_client: owner},
            "active_protection": receipt,
            "parent_order_intents": {parent: parent_intent},
        },
        "snapshot_sha256": SNAPSHOT_HASH,
    }


@pytest.mark.parametrize("position_side", ["long", "short"])
def test_long_short_mode_close_semantics_require_complete_local_lifecycle_proof(
    position_side: str,
) -> None:
    case = _case(position_side=position_side)
    before = _digest(case)

    result = normalize_hosted_protection_facts(**case)

    assert result["schema_version"] == HOSTED_PROTECTION_FACTS_SCHEMA_VERSION
    assert result["blockers"] == []
    assert result["rows"][0]["owned_by_runtime"] is True
    assert result["rows"][0]["owner_identity"] == "v1-offline"
    assert result["rows"][0]["close_position"] is True
    assert result["rows"][0]["reduce_only"] is None
    assert result["rows"][0]["reduce_only_status"] == "unknown"
    assert (
        result["rows"][0]["reduce_only_applicability"]
        == "not_applicable_long_short_mode"
    )
    assert _digest(case) == before


@pytest.mark.parametrize(
    ("mutator", "blocker"),
    [
        (
            lambda case: case["pending_algo_orders"][0].update({"side": "buy"}),
            "hosted_protection_close_side_mismatch",
        ),
        (
            lambda case: case["account"].update({"position_mode": "net_mode"}),
            "hosted_protection_position_mode_unsupported",
        ),
        (
            lambda case: case["ownership_facts"]["fact_binding"].update(
                {"run_id": "foreign-run"}
            ),
            "hosted_protection_envelope_binding_mismatch",
        ),
        (
            lambda case: case["ownership_facts"]["owned_attached_algos"][
                next(iter(case["ownership_facts"]["owned_attached_algos"]))
            ]["fact_binding"].update({"account_identity_hash": "d" * 64}),
            "hosted_protection_owner_binding_mismatch",
        ),
        (
            lambda case: case["ownership_facts"]["active_protection"].update(
                {"contracts": "0.02"}
            ),
            "hosted_protection_receipt_quantity_mismatch",
        ),
        (
            lambda case: case["ownership_facts"]["active_protection"].update(
                {"status": "cancelled_terminal"}
            ),
            "hosted_protection_receipt_not_active",
        ),
        (
            lambda case: case["ownership_facts"].update(
                {"snapshot_sha256": "e" * 64}
            ),
            "hosted_protection_snapshot_binding_mismatch",
        ),
    ],
)
def test_missing_conflicting_or_foreign_proof_remains_unowned(
    mutator: object,
    blocker: str,
) -> None:
    case = _case()
    mutator(case)

    result = normalize_hosted_protection_facts(**case)

    assert blocker in result["blockers"]
    assert result["rows"][0].get("owned_by_runtime") is not True
    assert result["rows"][0].get("close_position") is not True


def test_duplicate_and_future_exchange_rows_remain_unproved() -> None:
    duplicate = _case()
    duplicate["pending_algo_orders"].append(
        deepcopy(duplicate["pending_algo_orders"][0])
    )
    result = normalize_hosted_protection_facts(**duplicate)
    assert "hosted_protection_exchange_identity_ambiguous" in result["blockers"]
    assert all(row.get("owned_by_runtime") is not True for row in result["rows"])

    future = _case()
    future["pending_algo_orders"][0]["updated_at_ms"] = "9999999999999"
    future["snapshot_captured_at_utc"] = "2026-09-15T00:00:00+00:00"
    result = normalize_hosted_protection_facts(**future)
    assert "hosted_protection_exchange_time_future" in result["blockers"]
    assert result["rows"][0].get("close_position") is not True


@pytest.mark.parametrize("position_side", ["long", "short"])
def test_missing_raw_parent_joins_only_from_unique_exact_owned_algo_pair(
    position_side: str,
) -> None:
    case = _case(position_side=position_side)
    raw = case["pending_algo_orders"][0]
    raw["parent_client_order_id"] = ""
    before = _digest(case)

    result = normalize_hosted_protection_facts(**case)

    assert result["blockers"] == []
    assert result["rows"][0]["parent_client_order_id"] == f"btc-parent-{position_side}"
    assert result["rows"][0]["owned_by_runtime"] is True
    assert result["rows"][0]["close_position"] is True
    assert _digest(case) == before


def test_nonempty_raw_parent_must_match_local_owned_parent() -> None:
    case = _case()
    case["pending_algo_orders"][0]["parent_client_order_id"] = "foreign-parent"

    result = normalize_hosted_protection_facts(**case)

    assert "hosted_protection_parent_identity_mismatch" in result["blockers"]
    assert result["rows"][0].get("owned_by_runtime") is not True
    assert result["rows"][0].get("close_position") is not True


@pytest.mark.parametrize("conflict_field", ["algo_id", "algo_client_order_id"])
def test_single_identifier_owner_conflict_rejects_even_with_one_exact_pair(
    conflict_field: str,
) -> None:
    case = _case()
    owner = next(iter(case["ownership_facts"]["owned_attached_algos"].values()))
    conflicting = deepcopy(owner)
    if conflict_field == "algo_id":
        conflicting["algo_client_order_id"] = "foreign-client"
        key = "foreign-client"
    else:
        conflicting["algo_id"] = "foreign-algo"
        key = "conflicting-key"
    case["ownership_facts"]["owned_attached_algos"][key] = conflicting

    result = normalize_hosted_protection_facts(**case)

    assert "hosted_protection_owner_missing_or_ambiguous" in result["blockers"]
    assert result["rows"][0].get("owned_by_runtime") is not True
    assert result["rows"][0].get("close_position") is not True
