from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


HOSTED_PROTECTION_FACTS_SCHEMA_VERSION = "btc_hosted_protection_facts_v1"
_INSTRUMENT_ID = "BTC-USDT-SWAP"
_BINDING_FIELDS = (
    "runtime_identity",
    "run_id",
    "source_head",
    "account_identity_hash",
    "liveness_epoch",
    "strategy_id",
    "strategy_version",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return candidate if candidate.is_finite() else None


def _parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _binding(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    return {field: source.get(field) for field in _BINDING_FIELDS}


def _same_binding(value: Any, expected: Mapping[str, Any]) -> bool:
    return _binding(value) == dict(expected)


def _expected_binding(
    *, account: Mapping[str, Any], runtime_facts: Mapping[str, Any]
) -> dict[str, Any]:
    identity = _mapping(account.get("identity"))
    return {
        "runtime_identity": str(runtime_facts.get("runtime_identity") or ""),
        "run_id": str(runtime_facts.get("run_id") or ""),
        "source_head": str(runtime_facts.get("source_head") or "").lower(),
        "account_identity_hash": str(identity.get("hash") or "").lower(),
        "liveness_epoch": runtime_facts.get("authoritative_liveness_epoch"),
        "strategy_id": str(runtime_facts.get("strategy_id") or ""),
        "strategy_version": str(runtime_facts.get("strategy_version") or ""),
    }


def _binding_complete(value: Mapping[str, Any]) -> bool:
    return bool(
        value["runtime_identity"]
        and value["run_id"]
        and len(str(value["source_head"])) == 40
        and len(str(value["account_identity_hash"])) == 64
        and type(value["liveness_epoch"]) is int
        and value["liveness_epoch"] >= 0
        and value["strategy_id"]
        and value["strategy_version"]
    )


def _owner_candidates(
    owners: Mapping[str, Any], *, algo_id: str, algo_client_order_id: str
) -> list[Mapping[str, Any]]:
    """Return every registry row related to either exchange identifier.

    A single exact pair is authoritative only when no second persisted row
    claims either member of the pair.  Looking up the exact pair alone would
    hide a contradictory ownership registration.
    """

    candidates: list[Mapping[str, Any]] = []
    for key, raw in owners.items():
        row = _mapping(raw)
        row_client_id = str(row.get("algo_client_order_id") or key or "")
        row_algo_id = str(row.get("algo_id") or "")
        if row_client_id == algo_client_order_id or row_algo_id == algo_id:
            candidates.append(row)
    return candidates


def normalize_hosted_protection_facts(
    *,
    pending_algo_orders: Sequence[Mapping[str, Any]] | Any,
    positions: Sequence[Mapping[str, Any]] | Any,
    account: Mapping[str, Any] | Any,
    runtime_facts: Mapping[str, Any] | Any,
    ownership_facts: Mapping[str, Any] | Any,
    snapshot_sha256: str,
    snapshot_captured_at_utc: Any = None,
    expected_instrument_id: str = _INSTRUMENT_ID,
) -> dict[str, Any]:
    """Return a detached Guardian projection of exchange-hosted protection.

    The exchange snapshot remains immutable.  Runtime ownership is proved only
    by an exact current identity binding plus the persisted parent intent,
    owned-algo lifecycle row and verified active readback receipt.  In OKX
    ``long_short_mode`` an explicit ``sell+long`` or ``buy+short`` pair is a
    close fact; a missing ``reduceOnly`` field stays unknown and is recorded as
    not applicable rather than silently converted to ``True``.
    """

    raw_rows = _rows(pending_algo_orders)
    output_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    if not raw_rows:
        return {
            "schema_version": HOSTED_PROTECTION_FACTS_SCHEMA_VERSION,
            "rows": [],
            "blockers": [],
            "snapshot_sha256": str(snapshot_sha256 or ""),
        }

    account_row = _mapping(account)
    runtime = _mapping(runtime_facts)
    proof = _mapping(ownership_facts)
    expected_binding = _expected_binding(account=account_row, runtime_facts=runtime)
    envelope_valid = True
    if proof.get("schema_version") != HOSTED_PROTECTION_FACTS_SCHEMA_VERSION:
        blockers.append("hosted_protection_schema_mismatch")
        envelope_valid = False
    if str(proof.get("snapshot_sha256") or "") != str(snapshot_sha256 or ""):
        blockers.append("hosted_protection_snapshot_binding_mismatch")
        envelope_valid = False
    if not _binding_complete(expected_binding) or not _same_binding(
        proof.get("fact_binding"), expected_binding
    ):
        blockers.append("hosted_protection_envelope_binding_mismatch")
        envelope_valid = False

    owners = _mapping(proof.get("owned_attached_algos"))
    active = _mapping(proof.get("active_protection"))
    intents = _mapping(proof.get("parent_order_intents"))
    position_rows = _rows(positions)
    position_mode = str(account_row.get("position_mode") or "").lower()
    if position_mode != "long_short_mode":
        blockers.append("hosted_protection_position_mode_unsupported")
        envelope_valid = False

    identities = [
        (
            str(row.get("algo_id") or ""),
            str(row.get("algo_client_order_id") or ""),
        )
        for row in raw_rows
    ]
    ambiguous = (
        any(not all(identity) for identity in identities)
        or len(set(identities)) != len(identities)
    )
    if ambiguous:
        blockers.append("hosted_protection_exchange_identity_ambiguous")

    captured = _parse_utc(snapshot_captured_at_utc)
    for raw in raw_rows:
        row = dict(raw)
        for untrusted_field in (
            "owned",
            "owned_by_runtime",
            "owner_identity",
            "close_position",
        ):
            row.pop(untrusted_field, None)
        row_blockers: list[str] = []
        algo_id = str(row.get("algo_id") or "")
        algo_client = str(row.get("algo_client_order_id") or "")
        raw_parent_id = str(row.get("parent_client_order_id") or "")
        instrument = str(row.get("instrument_id") or "")
        side = str(row.get("side") or "").lower()
        position_side = str(row.get("position_side") or "").lower()
        quantity = _decimal(row.get("size"))
        state = str(row.get("state") or "").lower()
        order_type = str(row.get("order_type") or "").lower()
        reduce_status = str(row.get("reduce_only_status") or "unknown").lower()
        raw_reduce = row.get("reduce_only")
        if reduce_status not in {"true", "false", "unknown"}:
            row_blockers.append("hosted_protection_reduce_only_fact_invalid")
        elif (
            (reduce_status == "true" and raw_reduce is not True)
            or (reduce_status == "false" and raw_reduce is not False)
            or (reduce_status == "unknown" and raw_reduce is not None)
        ):
            row_blockers.append("hosted_protection_reduce_only_fact_conflict")

        close_pair = (side, position_side) in {("sell", "long"), ("buy", "short")}
        if not close_pair:
            row_blockers.append("hosted_protection_close_side_mismatch")
        if instrument != expected_instrument_id:
            row_blockers.append("hosted_protection_instrument_mismatch")
        if state not in {"live", "effective", "partially_effective", "open", "pending"}:
            row_blockers.append("hosted_protection_exchange_state_not_active")
        if order_type not in {"oco", "conditional_oco"}:
            row_blockers.append("hosted_protection_order_type_mismatch")
        if quantity is None or quantity <= 0:
            row_blockers.append("hosted_protection_quantity_invalid")
        updated_ms = str(row.get("updated_at_ms") or "")
        if captured is not None and updated_ms:
            try:
                updated = datetime.fromtimestamp(
                    int(updated_ms) / 1000, tz=timezone.utc
                )
            except (OverflowError, TypeError, ValueError):
                row_blockers.append("hosted_protection_exchange_time_invalid")
            else:
                if updated > captured:
                    row_blockers.append("hosted_protection_exchange_time_future")

        owner_matches = _owner_candidates(
            owners, algo_id=algo_id, algo_client_order_id=algo_client
        )
        owner = owner_matches[0] if len(owner_matches) == 1 else {}
        owner_pair_exact = bool(
            owner
            and str(owner.get("algo_id") or "") == algo_id
            and str(owner.get("algo_client_order_id") or "") == algo_client
        )
        if len(owner_matches) != 1 or not owner_pair_exact:
            row_blockers.append("hosted_protection_owner_missing_or_ambiguous")
        elif not _same_binding(owner.get("fact_binding"), expected_binding):
            row_blockers.append("hosted_protection_owner_binding_mismatch")
        local_parent_id = str(owner.get("parent_client_order_id") or "")
        parent_id = local_parent_id
        if (
            not owner_pair_exact
            or not local_parent_id
            or (raw_parent_id and raw_parent_id != local_parent_id)
            or algo_client != f"{local_parent_id}A"
        ):
            row_blockers.append("hosted_protection_parent_identity_mismatch")
        if not (
            owner.get("opening_intent") is True
            and local_parent_id == parent_id
            and str(owner.get("instrument_id") or "") == instrument
            and str(owner.get("status") or "") == "active"
        ):
            row_blockers.append("hosted_protection_owner_lifecycle_mismatch")

        parent = _mapping(intents.get(parent_id))
        parent_order = _mapping(parent.get("order"))
        expected_open_side = "buy" if position_side == "long" else "sell"
        if not parent or not _same_binding(parent.get("fact_binding"), expected_binding):
            row_blockers.append("hosted_protection_parent_binding_mismatch")
        if not (
            str(parent.get("client_order_id") or "") == parent_id
            and parent.get("risk_reducing_only") is False
            and str(parent.get("status") or "") == "terminal"
            and str(parent_order.get("instId") or "") == instrument
            and str(parent_order.get("side") or "").lower() == expected_open_side
            and str(parent_order.get("posSide") or "").lower() == position_side
            and _decimal(parent_order.get("sz")) == quantity
        ):
            row_blockers.append("hosted_protection_parent_intent_mismatch")

        if not _same_binding(active.get("fact_binding"), expected_binding):
            row_blockers.append("hosted_protection_receipt_binding_mismatch")
        if str(active.get("status") or "") != "exchange_accepted":
            row_blockers.append("hosted_protection_receipt_not_active")
        if not (
            str(active.get("algo_id") or "") == algo_id
            and str(active.get("algo_client_order_id") or "") == algo_client
            and str(active.get("parent_client_order_id") or "") == parent_id
            and str(active.get("instrument_id") or "") == instrument
            and str(active.get("position_side") or "").lower() == position_side
        ):
            row_blockers.append("hosted_protection_receipt_identity_mismatch")
        if _decimal(active.get("contracts")) != quantity:
            row_blockers.append("hosted_protection_receipt_quantity_mismatch")

        exact_positions = [
            position
            for position in position_rows
            if str(position.get("instrument_id") or position.get("instId") or "")
            == instrument
            and str(position.get("position_side") or position.get("posSide") or "").lower()
            == position_side
            and _decimal(
                position.get("contracts", position.get("pos", position.get("quantity")))
            )
            == quantity
            and quantity is not None
            and quantity > 0
        ]
        if len(exact_positions) != 1:
            row_blockers.append("hosted_protection_position_quantity_mismatch")

        if ambiguous or not envelope_valid:
            row_blockers.append("hosted_protection_proof_incomplete")
        if not row_blockers:
            row.update(
                {
                    "parent_client_order_id": parent_id,
                    "owned_by_runtime": True,
                    "owner_identity": str(expected_binding["runtime_identity"]),
                    "close_position": True,
                    "reduce_only_applicability": "not_applicable_long_short_mode",
                    "ownership_evidence": {
                        "schema_version": HOSTED_PROTECTION_FACTS_SCHEMA_VERSION,
                        "snapshot_sha256": str(snapshot_sha256),
                        "fact_binding": dict(expected_binding),
                        "source": "persisted_parent_owner_active_readback_intersection",
                    },
                }
            )
        output_rows.append(row)
        blockers.extend(row_blockers)

    return {
        "schema_version": HOSTED_PROTECTION_FACTS_SCHEMA_VERSION,
        "rows": output_rows,
        "blockers": _dedupe(blockers),
        "snapshot_sha256": str(snapshot_sha256 or ""),
    }


__all__ = [
    "HOSTED_PROTECTION_FACTS_SCHEMA_VERSION",
    "normalize_hosted_protection_facts",
]
