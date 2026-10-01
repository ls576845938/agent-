from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from quant_crypto.research.btc_demo_observation_accumulator import (
    ObservationReceiptError,
    load_observation_receipt_ledger,
)


PROJECTION_SCHEMA_VERSION = "btc_private_readonly_observation_projection_v1"
STATE_SCHEMA_VERSION = "btc_demo_private_readonly_observation_state_v1"
OWNER_SCHEMA_VERSION = "btc_demo_private_readonly_observation_owner_v1"
REQUIRED_OBSERVATION_HOURS = 25
MAX_STATE_AGE_SECONDS = 120
MAX_JSON_BYTES = 1_000_000
_HEX_HEAD = re.compile(r"[0-9a-f]{40}")
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}")
_SAFE_CODE = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,159}")
_RUNTIME_SAFETY = {
    "allow_demo_orders": False,
    "allow_demo_cancels": False,
    "allow_transfer": False,
    "allow_withdraw": False,
    "allow_live": False,
    "real_order_allowed": False,
    "promotion_allowed": False,
    "paper_allowed": False,
}
_PUBLIC_SAFETY = {
    "promotion": False,
    "paper": False,
    "live": False,
    "private": False,
    "order": False,
    "real_order": False,
    "transfer": False,
    "withdraw": False,
}


class BTCPrivateReadonlyObservationProjectionError(RuntimeError):
    """Safe, bounded reason for an unavailable observation projection."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        code = str(item or "").strip().lower()
        if _SAFE_CODE.fullmatch(code) and code not in result:
            result.append(code)
    return result


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


class BTCPrivateReadonlyObservationProjection:
    """GET-only, sanitized projection over an already-running external observer.

    This service never creates the runtime root, acquires its writer lease, reads
    credentials, or invokes exchange transports. It consumes only the runner's
    committed local state and validated hourly receipt ledger.
    """

    def __init__(
        self,
        *,
        runtime_root: str | Path,
        repo_root: str | Path,
        head_resolver: Callable[[], str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtime_root = Path(runtime_root)
        self._repo_root = Path(repo_root)
        self._head_resolver = head_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _validated_root(self) -> Path:
        root = self._runtime_root.expanduser()
        repo_root = self._repo_root.expanduser().resolve()
        if not root.is_absolute() or root == Path(root.anchor):
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_root_invalid"
            )
        resolved = root.resolve()
        if not resolved.is_dir() or root.is_symlink():
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_root_unavailable"
            )
        try:
            inside_repo = os.path.commonpath((str(resolved), str(repo_root))) == str(
                repo_root
            )
        except ValueError:
            inside_repo = False
        if resolved == repo_root or inside_repo:
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_root_must_be_external"
            )
        return resolved

    @staticmethod
    def _read_json(root: Path, name: str) -> dict[str, Any]:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise BTCPrivateReadonlyObservationProjectionError(
                f"private_readonly_projection_{name.removesuffix('.json')}_missing"
            )
        if path.stat().st_size > MAX_JSON_BYTES:
            raise BTCPrivateReadonlyObservationProjectionError(
                f"private_readonly_projection_{name.removesuffix('.json')}_oversized"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BTCPrivateReadonlyObservationProjectionError(
                f"private_readonly_projection_{name.removesuffix('.json')}_invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise BTCPrivateReadonlyObservationProjectionError(
                f"private_readonly_projection_{name.removesuffix('.json')}_invalid"
            )
        return payload

    @staticmethod
    def _validate_safety(value: object) -> None:
        safety = _mapping(value)
        if set(safety) != set(_RUNTIME_SAFETY) or any(
            safety.get(key) is not expected
            for key, expected in _RUNTIME_SAFETY.items()
        ):
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_safety_mismatch"
            )

    @staticmethod
    def _identity(owner: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[str, str]:
        if owner.get("schema_version") != OWNER_SCHEMA_VERSION:
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_owner_schema_invalid"
            )
        if state.get("schema_version") != STATE_SCHEMA_VERSION:
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_state_schema_invalid"
            )
        identity_fields = (
            "source_head",
            "run_id",
            "runtime_version",
            "policy_digest",
            "private_authorization_ticket_hash",
        )
        if any(owner.get(field) != state.get(field) for field in identity_fields):
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_owner_state_mismatch"
            )
        source_head = str(state.get("source_head") or "")
        run_id = str(state.get("run_id") or "")
        if not _HEX_HEAD.fullmatch(source_head) or not _SAFE_RUN_ID.fullmatch(run_id):
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_identity_invalid"
            )
        return source_head, run_id

    @staticmethod
    def _receipt_progress(
        *,
        receipts: list[dict[str, Any]],
        source_head: str,
        run_id: str,
    ) -> tuple[int, str]:
        completed = 0
        previous_hour: datetime | None = None
        last_hour = ""
        for receipt in receipts:
            if (
                receipt.get("source_head") != source_head
                or receipt.get("runtime_run_id") != run_id
            ):
                raise BTCPrivateReadonlyObservationProjectionError(
                    "private_readonly_projection_receipt_identity_mismatch"
                )
            hour = _parse_utc(receipt.get("observation_hour_utc"))
            if hour is None:
                raise BTCPrivateReadonlyObservationProjectionError(
                    "private_readonly_projection_receipt_hour_invalid"
                )
            consecutive = previous_hour is None or hour == previous_hour + timedelta(hours=1)
            if receipt.get("counts_toward_25_hour_window") is True:
                completed = completed + 1 if consecutive else 1
            else:
                completed = 0
            previous_hour = hour
            last_hour = hour.isoformat()
        return completed, last_hour

    def read(self) -> dict[str, Any]:
        root = self._validated_root()
        owner = self._read_json(root, "owner.json")
        state = self._read_json(root, "state.json")
        self._validate_safety(owner.get("safety"))
        self._validate_safety(state.get("safety"))
        source_head, run_id = self._identity(owner, state)
        current_head = str(self._head_resolver() or "").strip()
        current_head_valid = _HEX_HEAD.fullmatch(current_head) is not None
        head_match = current_head_valid and source_head == current_head

        receipt_path = root / "observation" / "hourly_observation_receipts.jsonl"
        if receipt_path.is_symlink():
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_receipt_ledger_invalid"
            )
        try:
            receipts = load_observation_receipt_ledger(receipt_path)
        except (OSError, UnicodeError, ObservationReceiptError) as exc:
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_receipt_ledger_invalid"
            ) from exc
        completed_hours, ledger_last_hour = self._receipt_progress(
            receipts=receipts,
            source_head=source_head,
            run_id=run_id,
        )
        state_last_hour = str(state.get("last_receipt_hour_utc") or "")
        if state_last_hour and _parse_utc(state_last_hour) is None:
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_state_receipt_hour_invalid"
            )
        if ledger_last_hour != (
            _parse_utc(state_last_hour).isoformat() if state_last_hour else ""
        ):
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_receipt_state_mismatch"
            )

        now = _utc(self._clock())
        last_observed = _parse_utc(state.get("last_observed_at_utc"))
        eligible_since = _parse_utc(state.get("eligible_since_utc"))
        if last_observed is None or eligible_since is None:
            raise BTCPrivateReadonlyObservationProjectionError(
                "private_readonly_projection_timestamp_invalid"
            )
        age_seconds = (now - last_observed).total_seconds()
        fresh = -MAX_STATE_AGE_SECONDS <= age_seconds <= MAX_STATE_AGE_SECONDS
        state_blockers = _codes(state.get("blockers"))
        gap_flags = _codes(state.get("current_hour_gap_flags"))
        private_ws = _mapping(state.get("private_ws"))
        reconciliation = _mapping(state.get("reconciliation"))
        funding = _mapping(state.get("funding"))
        health_blockers = [
            *_codes(private_ws.get("blockers")),
            *_codes(reconciliation.get("blockers")),
            *_codes(funding.get("blockers")),
        ]
        if not fresh:
            health_blockers.append("private_readonly_projection_state_stale")
        evidence_blockers: list[str] = []
        if not current_head_valid:
            evidence_blockers.append("private_readonly_projection_current_head_invalid")
        elif not head_match:
            evidence_blockers.append("private_readonly_projection_current_head_mismatch")
        runner_blockers = list(dict.fromkeys([*state_blockers, *health_blockers]))
        all_blockers = list(dict.fromkeys([*runner_blockers, *evidence_blockers]))
        runner_active = (
            state.get("phase") == "observing"
            and fresh
            and not runner_blockers
            and private_ws.get("connected") is True
            and private_ws.get("listener_alive") is True
            and private_ws.get("reconciled") is True
            and reconciliation.get("rest_snapshot_observed") is True
            and reconciliation.get("snapshot_reconciled") is True
            and funding.get("reconciled") is True
        )
        eligible_hour_start = eligible_since.replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        if eligible_hour_start < eligible_since:
            eligible_hour_start += timedelta(hours=1)
        partial_start = eligible_hour_start
        parsed_last_hour = _parse_utc(state_last_hour)
        if parsed_last_hour is not None and parsed_last_hour > partial_start:
            partial_start = parsed_last_hour
        partial = 0.0
        if runner_active and not gap_flags:
            partial = min(1.0, max(0.0, (now - partial_start).total_seconds() / 3600))
        progress_hours = min(
            float(REQUIRED_OBSERVATION_HOURS),
            completed_hours + partial,
        )
        remaining_hours = max(0.0, REQUIRED_OBSERVATION_HOURS - progress_hours)

        return {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "status": (
                "observing"
                if runner_active and head_match
                else "historical"
                if runner_active
                else "blocked"
            ),
            "freshness": "current" if fresh else "stale",
            "source_head": source_head,
            "current_head": current_head if current_head_valid else "",
            "head_match": head_match,
            "runner_active": runner_active,
            "gate_eligible": False,
            "run_id": run_id,
            "runtime_version": str(state.get("runtime_version") or ""),
            "phase": str(state.get("phase") or "unknown"),
            "started_at_utc": str(state.get("started_at_utc") or ""),
            "eligible_since_utc": str(state.get("eligible_since_utc") or ""),
            "last_observed_at_utc": str(state.get("last_observed_at_utc") or ""),
            "generated_at_utc": now.isoformat(),
            "state_revision": int(state.get("state_revision") or 0),
            "restart_count": int(state.get("restart_count") or 0),
            "recovery_count": int(state.get("recovery_count") or 0),
            "progress": {
                "required_hours": REQUIRED_OBSERVATION_HOURS,
                "completed_hours": completed_hours,
                "current_hour_fraction": round(partial, 6),
                "progress_hours": round(progress_hours, 6),
                "remaining_hours": round(remaining_hours, 6),
                "receipt_count": len(receipts),
                "last_receipt_hour_utc": ledger_last_hour,
                "complete": completed_hours >= REQUIRED_OBSERVATION_HOURS,
            },
            "private_ws": {
                "connected": private_ws.get("connected") is True,
                "listener_alive": private_ws.get("listener_alive") is True,
                "reconciled": private_ws.get("reconciled") is True,
            },
            "reconciliation": {
                "rest_snapshot_observed": (
                    reconciliation.get("rest_snapshot_observed") is True
                ),
                "snapshot_reconciled": (
                    reconciliation.get("snapshot_reconciled") is True
                ),
                "funding_reconciled": funding.get("reconciled") is True,
            },
            "blockers": all_blockers,
            "gap_flags": gap_flags,
            "safety_flags": dict(_PUBLIC_SAFETY),
        }


__all__ = [
    "BTCPrivateReadonlyObservationProjection",
    "BTCPrivateReadonlyObservationProjectionError",
]
