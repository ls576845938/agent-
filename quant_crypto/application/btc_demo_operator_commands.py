"""Server-owned commands for BTC Demo operator actions.

Browser payloads carry operator intent and optimistic-concurrency fences.  They
must not be responsible for copying runtime magic constants into controller
commands.  These immutable command objects make that application boundary
explicit before any private read adapter is reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .btc_operator_contract_v2 import SAFETY_FLAGS


REFRESH_ACCOUNT_SNAPSHOT_COMMAND_SCHEMA_VERSION = (
    "btc_demo_refresh_account_snapshot_command_v1"
)


@dataclass(frozen=True, slots=True)
class RefreshAccountSnapshotCommand:
    """Authoritative, read-only Demo account refresh command."""

    instrument_id: str
    confirmation_text: str

    def __post_init__(self) -> None:
        if not str(self.instrument_id).strip():
            raise ValueError("btc_demo_refresh_instrument_identity_missing")
        if not str(self.confirmation_text).strip():
            raise ValueError("btc_demo_refresh_confirmation_policy_missing")

    def to_controller_payload(self) -> dict[str, Any]:
        return {
            "schema_version": REFRESH_ACCOUNT_SNAPSHOT_COMMAND_SCHEMA_VERSION,
            "environment": "demo",
            "instrument_id": self.instrument_id,
            "confirmation_text": self.confirmation_text,
            "read_scope": "account_positions_orders_ledger",
            "confirm_demo_only": True,
            "read_only": True,
            "order_submission_allowed": False,
            "safety_flags": {name: False for name in SAFETY_FLAGS},
        }


__all__ = [
    "REFRESH_ACCOUNT_SNAPSHOT_COMMAND_SCHEMA_VERSION",
    "RefreshAccountSnapshotCommand",
]
