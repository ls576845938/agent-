from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


RECEIPT_SCHEMA_VERSION = "us_ibkr_paper_daily_observation_receipt_v1"
REPORT_SCHEMA_VERSION = "us_ibkr_paper_observation_report_v1"
MANIFEST_SCHEMA_VERSION = "us_ibkr_paper_observation_manifest_v1"
INPUT_ENVELOPE_SCHEMA_VERSION = "us_ibkr_observation_input_envelope_v1"
REQUIRED_NATURAL_DAYS = 30
DEFAULT_OPERATING_TIMEZONE = "America/New_York"
WINDOW_BLOCKER = "us_ibkr_paper_observation:30_natural_day_window_incomplete"
CONFIRMATION_BLOCKER = (
    "us_ibkr_paper_observation:independent_252_trading_day_confirmation_required"
)
_HEX_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INPUT_KINDS = {
    "strategy_identity",
    "data_manifest",
    "runtime_receipt",
    "broker_receipt",
    "reconciliation_report",
}
_IDENTITY_FIELDS = (
    "code_head",
    "strategy_hash",
    "data_identity",
    "account_hash",
    "parameters_hash",
    "risk_hash",
    "oms_hash",
    "ledger_contract_hash",
)
_COUNT_FIELDS = (
    "signals",
    "targets",
    "intents",
    "orders",
    "fills",
    "partial_fills",
    "rejects",
    "cancels",
    "reconnects",
    "unmatched",
    "duplicates",
)


class IbkrPaperObservationError(ValueError):
    """Raised when an observation input or append-only ledger is unsafe."""


def build_input_envelope(
    *,
    input_kind: str,
    source_commit: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a content-addressed envelope for an already-produced input."""

    if input_kind not in _INPUT_KINDS:
        raise IbkrPaperObservationError("observation_input_kind_invalid")
    if not _HEX_COMMIT.fullmatch(source_commit):
        raise IbkrPaperObservationError("observation_input_source_commit_invalid")
    body = dict(payload)
    envelope = {
        "schema_version": INPUT_ENVELOPE_SCHEMA_VERSION,
        "input_kind": input_kind,
        "source_commit": source_commit,
        "payload": body,
        "payload_sha256": stable_payload_hash(body),
    }
    envelope["envelope_sha256"] = stable_payload_hash(envelope)
    return envelope


def validate_input_envelope(
    envelope: Mapping[str, Any],
    *,
    expected_kind: str,
) -> list[str]:
    blockers: list[str] = []
    if envelope.get("schema_version") != INPUT_ENVELOPE_SCHEMA_VERSION:
        blockers.append(f"{expected_kind}:schema_mismatch")
    if envelope.get("input_kind") != expected_kind:
        blockers.append(f"{expected_kind}:kind_mismatch")
    if not _HEX_COMMIT.fullmatch(str(envelope.get("source_commit") or "")):
        blockers.append(f"{expected_kind}:source_commit_invalid")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        blockers.append(f"{expected_kind}:payload_missing")
    else:
        payload_hash = str(envelope.get("payload_sha256") or "")
        if not _SHA256.fullmatch(payload_hash):
            blockers.append(f"{expected_kind}:payload_hash_invalid")
        elif stable_payload_hash(payload) != payload_hash:
            blockers.append(f"{expected_kind}:payload_hash_mismatch")
    envelope_hash = str(envelope.get("envelope_sha256") or "")
    if not _SHA256.fullmatch(envelope_hash):
        blockers.append(f"{expected_kind}:envelope_hash_invalid")
    elif stable_payload_hash(
        envelope, exclude={"envelope_sha256"}
    ) != envelope_hash:
        blockers.append(f"{expected_kind}:envelope_hash_mismatch")
    return _dedupe(blockers)


def build_daily_observation_receipt(
    *,
    strategy_identity: Mapping[str, Any],
    data_manifest: Mapping[str, Any],
    runtime_receipt: Mapping[str, Any],
    broker_receipt: Mapping[str, Any],
    reconciliation_report: Mapping[str, Any],
    observed_at_utc: datetime,
    previous_receipt_sha256: str | None,
    operating_timezone: str = DEFAULT_OPERATING_TIMEZONE,
    backfilled: bool = False,
) -> dict[str, Any]:
    """Build one offline receipt from committed, content-addressed evidence.

    This function has no broker, network, submit, cancel, or data-refresh path.
    It only normalizes already-produced documents into the observation ledger.
    """

    observed = _ensure_utc(observed_at_utc)
    if backfilled:
        raise IbkrPaperObservationError("paper_observation_backfill_forbidden")
    if previous_receipt_sha256 is not None and not _SHA256.fullmatch(
        previous_receipt_sha256
    ):
        raise IbkrPaperObservationError(
            "paper_observation_previous_receipt_hash_invalid"
        )
    try:
        zone = ZoneInfo(operating_timezone)
    except (KeyError, ValueError) as exc:
        raise IbkrPaperObservationError(
            "paper_observation_timezone_invalid"
        ) from exc

    envelopes = {
        "strategy_identity": strategy_identity,
        "data_manifest": data_manifest,
        "runtime_receipt": runtime_receipt,
        "broker_receipt": broker_receipt,
        "reconciliation_report": reconciliation_report,
    }
    input_blockers: list[str] = []
    for kind, envelope in envelopes.items():
        input_blockers.extend(
            validate_input_envelope(envelope, expected_kind=kind)
        )
    if input_blockers:
        raise IbkrPaperObservationError(input_blockers[0])

    strategy = _payload(strategy_identity)
    data = _payload(data_manifest)
    runtime = _payload(runtime_receipt)
    broker = _payload(broker_receipt)
    reconciliation = _payload(reconciliation_report)

    code_head = _required_hash(runtime, "code_head", commit=True)
    for kind, envelope in (
        ("runtime_receipt", runtime_receipt),
        ("broker_receipt", broker_receipt),
        ("reconciliation_report", reconciliation_report),
    ):
        if str(envelope.get("source_commit")) != code_head:
            raise IbkrPaperObservationError(
                f"{kind}:source_commit_code_head_mismatch"
            )
    for kind, payload in (
        ("broker_receipt", broker),
        ("reconciliation_report", reconciliation),
    ):
        if str(payload.get("code_head") or "") != code_head:
            raise IbkrPaperObservationError(f"{kind}:code_head_mismatch")

    observation_run_id = _required_text(runtime, "observation_run_id")
    session_id = _required_text(runtime, "session_id")
    identity = {
        "code_head": code_head,
        "strategy_hash": _required_hash(strategy, "strategy_hash"),
        "data_identity": _required_hash(data, "data_identity"),
        "account_hash": _required_hash(broker, "account_hash"),
        "parameters_hash": _required_hash(strategy, "parameters_hash"),
        "risk_hash": _required_hash(runtime, "risk_hash"),
        "oms_hash": _required_hash(runtime, "oms_hash"),
        "ledger_contract_hash": _required_hash(
            runtime, "ledger_contract_hash"
        ),
    }
    for kind, payload in (
        ("broker_receipt", broker),
        ("reconciliation_report", reconciliation),
    ):
        if str(payload.get("account_hash") or "") != identity["account_hash"]:
            raise IbkrPaperObservationError(f"{kind}:account_hash_mismatch")
        if str(payload.get("session_id") or "") != session_id:
            raise IbkrPaperObservationError(f"{kind}:session_id_mismatch")

    counts = {
        "signals": _nonnegative_int(runtime, "signal_count"),
        "targets": _nonnegative_int(runtime, "target_count"),
        "intents": _nonnegative_int(runtime, "intent_count"),
        "orders": _nonnegative_int(broker, "order_count"),
        "fills": _nonnegative_int(broker, "fill_count"),
        "partial_fills": _nonnegative_int(broker, "partial_fill_count"),
        "rejects": _nonnegative_int(broker, "reject_count"),
        "cancels": _nonnegative_int(broker, "cancel_count"),
        "reconnects": _nonnegative_int(broker, "reconnect_count"),
        "unmatched": _nonnegative_int(reconciliation, "unmatched_count"),
        "duplicates": _nonnegative_int(reconciliation, "duplicate_count"),
    }
    observed_event_count = sum(
        (
            _nonnegative_int(runtime, "observed_event_count"),
            _nonnegative_int(broker, "observed_event_count"),
            _nonnegative_int(reconciliation, "check_count"),
        )
    )
    data_fresh = (
        data.get("freshness_status") == "fresh"
        and data.get("stale") is False
    )
    position_drift = _finite_number(reconciliation, "position_drift")
    cash_drift = _finite_number(reconciliation, "cash_drift")
    commission = _finite_number(broker, "commission")
    slippage = _finite_number(broker, "slippage")
    kill_switch_state = _required_text(runtime, "kill_switch_state")
    integration_receipt_hashes = runtime.get("independent_integration_receipts")
    integrations_confirmed = (
        isinstance(integration_receipt_hashes, list)
        and all(
            isinstance(value, str) and _SHA256.fullmatch(value)
            for value in integration_receipt_hashes
        )
        and len(set(integration_receipt_hashes)) >= 2
    )
    real_paper_runtime = (
        runtime.get("runtime_mode") == "ibkr_paper"
        and runtime.get("real_paper_session") is True
        and runtime.get("paper_submit_authorized") is True
        and integrations_confirmed
        and runtime.get("fixture") is False
        and runtime.get("read_only") is False
        and runtime.get("no_submit") is False
    )
    reconciliation_clean = (
        reconciliation.get("status") == "reconciled"
        and counts["unmatched"] == 0
        and counts["duplicates"] == 0
        and position_drift == 0.0
        and cash_drift == 0.0
    )
    nonempty_observation = observed_event_count > 0
    counts_toward_window = (
        data_fresh
        and real_paper_runtime
        and reconciliation_clean
        and nonempty_observation
        and kill_switch_state == "armed"
    )
    observation_date = observed.astimezone(zone).date().isoformat()
    blockers: list[str] = []
    if not data_fresh:
        blockers.append("owner:data_steward paper_observation_data_stale")
    if not real_paper_runtime:
        blockers.append(
            "paper_observation_real_paper_runtime_or_submit_authority_missing"
        )
    if not integrations_confirmed:
        blockers.append(
            "paper_observation_two_independent_integration_receipts_required"
        )
    if not nonempty_observation:
        blockers.append("paper_observation_empty_heartbeat_not_counted")
    if not reconciliation_clean:
        blockers.append("paper_observation_reconciliation_not_clean")
    if kill_switch_state != "armed":
        blockers.append("paper_observation_kill_switch_not_armed")

    payload: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_kind": "ibkr_real_paper_natural_day_observation",
        "observation_date": observation_date,
        "operating_timezone": operating_timezone,
        "observed_at_utc": observed.isoformat(),
        "observation_run_id": observation_run_id,
        "session_id": session_id,
        "identity": identity,
        "input_evidence": {
            kind: {
                "source_commit": str(envelope["source_commit"]),
                "payload_sha256": str(envelope["payload_sha256"]),
                "envelope_sha256": str(envelope["envelope_sha256"]),
            }
            for kind, envelope in envelopes.items()
        },
        "data_freshness": {
            "status": str(data.get("freshness_status") or "unknown"),
            "stale": data.get("stale"),
            "as_of": str(data.get("as_of") or ""),
        },
        "counts": counts,
        "observed_event_count": observed_event_count,
        "position_drift": position_drift,
        "cash_drift": cash_drift,
        "commission": commission,
        "slippage": slippage,
        "kill_switch_state": kill_switch_state,
        "real_paper_session": runtime.get("real_paper_session") is True,
        "paper_submit_authorized": (
            runtime.get("paper_submit_authorized") is True
        ),
        "independent_integration_receipts": (
            list(integration_receipt_hashes)
            if isinstance(integration_receipt_hashes, list)
            else []
        ),
        "fixture": runtime.get("fixture") is True,
        "read_only": runtime.get("read_only") is True,
        "no_submit": runtime.get("no_submit") is True,
        "natural_time_observation": True,
        "backfilled": False,
        "counts_toward_30_day_window": counts_toward_window,
        "blockers": _dedupe(blockers),
        "previous_receipt_sha256": previous_receipt_sha256,
        "safety_flags": safety_flags(),
    }
    payload["receipt_sha256"] = stable_payload_hash(payload)
    return payload


def validate_daily_observation_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_previous_receipt_sha256: str | None,
) -> list[str]:
    blockers: list[str] = []
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        blockers.append("paper_observation_receipt_schema_mismatch")
    if receipt.get("receipt_kind") != "ibkr_real_paper_natural_day_observation":
        blockers.append("paper_observation_receipt_kind_invalid")
    try:
        observation_date = date.fromisoformat(
            str(receipt.get("observation_date") or "")
        )
    except ValueError:
        observation_date = None
        blockers.append("paper_observation_date_invalid")
    observed = _parse_utc(receipt.get("observed_at_utc"))
    try:
        zone = ZoneInfo(
            str(receipt.get("operating_timezone") or "")
        )
    except (KeyError, ValueError):
        zone = None
        blockers.append("paper_observation_timezone_invalid")
    if observed is None:
        blockers.append("paper_observation_observed_at_invalid")
    elif zone is not None and observation_date != observed.astimezone(zone).date():
        blockers.append("paper_observation_natural_day_mismatch")
    if not str(receipt.get("observation_run_id") or "").strip():
        blockers.append("paper_observation_run_id_missing")
    if not str(receipt.get("session_id") or "").strip():
        blockers.append("paper_observation_session_id_missing")
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping):
        blockers.append("paper_observation_identity_missing")
    else:
        for field in _IDENTITY_FIELDS:
            value = str(identity.get(field) or "")
            if field == "code_head":
                valid = bool(_HEX_COMMIT.fullmatch(value))
            else:
                valid = bool(_SHA256.fullmatch(value))
            if not valid:
                blockers.append(f"paper_observation_{field}_invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping):
        blockers.append("paper_observation_counts_missing")
    else:
        for field in _COUNT_FIELDS:
            value = counts.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                blockers.append(f"paper_observation_{field}_invalid")
    for field in ("position_drift", "cash_drift", "commission", "slippage"):
        value = receipt.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            blockers.append(f"paper_observation_{field}_invalid")
    if receipt.get("backfilled") is not False:
        blockers.append("paper_observation_backfill_forbidden")
    if receipt.get("natural_time_observation") is not True:
        blockers.append("paper_observation_not_natural_time")
    if receipt.get("previous_receipt_sha256") != expected_previous_receipt_sha256:
        blockers.append("paper_observation_hash_chain_mismatch")
    recorded_hash = str(receipt.get("receipt_sha256") or "")
    if not _SHA256.fullmatch(recorded_hash):
        blockers.append("paper_observation_receipt_hash_invalid")
    elif stable_payload_hash(
        receipt, exclude={"receipt_sha256"}
    ) != recorded_hash:
        blockers.append("paper_observation_receipt_hash_mismatch")
    safety = receipt.get("safety_flags")
    if not isinstance(safety, Mapping) or any(
        value is not False for value in safety.values()
    ):
        blockers.append("paper_observation_safety_boundary_violation")
    return _dedupe(blockers)


def load_observation_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IbkrPaperObservationError(
                f"paper_observation_ledger_truncated_or_invalid:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise IbkrPaperObservationError(
                f"paper_observation_receipt_object_required:{line_number}"
            )
        rows.append(row)
    integrity = ledger_integrity(rows)
    if integrity["blockers"]:
        raise IbkrPaperObservationError(str(integrity["blockers"][0]))
    return rows


def append_daily_observation_receipt(
    *,
    ledger_path: Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Append once under a single-writer lock; exact retries are idempotent."""

    lock_path = Path(f"{ledger_path}.lock")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd: int | None = None
    try:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise IbkrPaperObservationError(
                "paper_observation_single_writer_lock_held"
            ) from exc
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        os.fsync(lock_fd)

        existing = load_observation_ledger(ledger_path)
        receipt_hash = str(receipt.get("receipt_sha256") or "")
        if any(row.get("receipt_sha256") == receipt_hash for row in existing):
            return {
                "appended": False,
                "duplicate": True,
                "receipt_sha256": receipt_hash,
                "ledger_row_count": len(existing),
            }
        previous_hash = (
            str(existing[-1]["receipt_sha256"]) if existing else None
        )
        blockers = validate_daily_observation_receipt(
            receipt,
            expected_previous_receipt_sha256=previous_hash,
        )
        if blockers:
            raise IbkrPaperObservationError(blockers[0])
        new_date = date.fromisoformat(str(receipt["observation_date"]))
        existing_dates = {
            str(row["observation_date"]): str(row["receipt_sha256"])
            for row in existing
        }
        if new_date.isoformat() in existing_dates:
            raise IbkrPaperObservationError(
                "paper_observation_natural_day_conflict"
            )
        if existing:
            previous_date = date.fromisoformat(
                str(existing[-1]["observation_date"])
            )
            previous_time = _parse_utc(existing[-1].get("observed_at_utc"))
            new_time = _parse_utc(receipt.get("observed_at_utc"))
            if new_date < previous_date:
                raise IbkrPaperObservationError(
                    "paper_observation_historical_backfill_forbidden"
                )
            if (
                previous_time is not None
                and new_time is not None
                and new_time <= previous_time
            ):
                raise IbkrPaperObservationError(
                    "paper_observation_nonmonotonic_time"
                )
        encoded = (
            json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        with ledger_path.open("ab", buffering=0) as handle:
            handle.write(encoded)
            os.fsync(handle.fileno())
        return {
            "appended": True,
            "duplicate": False,
            "receipt_sha256": receipt_hash,
            "ledger_row_count": len(existing) + 1,
        }
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


def ledger_integrity(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    previous_hash: str | None = None
    previous_date: date | None = None
    previous_time: datetime | None = None
    seen_dates: set[str] = set()
    seen_hashes: set[str] = set()
    for receipt in receipts:
        blockers.extend(
            validate_daily_observation_receipt(
                receipt,
                expected_previous_receipt_sha256=previous_hash,
            )
        )
        current_hash = str(receipt.get("receipt_sha256") or "")
        current_date = _parse_date(receipt.get("observation_date"))
        current_time = _parse_utc(receipt.get("observed_at_utc"))
        if current_hash in seen_hashes:
            blockers.append("paper_observation_duplicate_receipt_hash")
        seen_hashes.add(current_hash)
        if current_date is not None:
            key = current_date.isoformat()
            if key in seen_dates:
                blockers.append("paper_observation_natural_day_conflict")
            seen_dates.add(key)
            if previous_date is not None and current_date < previous_date:
                blockers.append("paper_observation_historical_backfill_forbidden")
            previous_date = current_date
        if (
            previous_time is not None
            and current_time is not None
            and current_time <= previous_time
        ):
            blockers.append("paper_observation_nonmonotonic_time")
        if current_time is not None:
            previous_time = current_time
        previous_hash = current_hash
    return {
        "valid": not blockers,
        "receipt_count": len(receipts),
        "ledger_sha256": stable_payload_hash(list(receipts)),
        "last_receipt_sha256": previous_hash,
        "blockers": _dedupe(blockers),
    }


def build_observation_report(
    *,
    receipts: Sequence[Mapping[str, Any]],
    current_head: str,
    current_observation_run_id: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc)
    if not _HEX_COMMIT.fullmatch(current_head):
        raise IbkrPaperObservationError("paper_observation_current_head_invalid")
    if not current_observation_run_id.strip():
        raise IbkrPaperObservationError("paper_observation_current_run_id_missing")
    integrity = ledger_integrity(receipts)
    segments = _segments(receipts)
    current_segment: dict[str, Any] | None = None
    for segment in reversed(segments):
        if (
            segment["observation_run_id"] == current_observation_run_id
            and segment["identity"]["code_head"] == current_head
        ):
            current_segment = segment
            break
    current_receipt_hashes = set(
        current_segment.get("receipt_hashes", []) if current_segment else []
    )
    historical_rows = [
        receipt
        for receipt in receipts
        if receipt.get("receipt_sha256") not in current_receipt_hashes
    ]
    current_days = int(
        current_segment.get("consecutive_eligible_natural_days", 0)
        if current_segment
        else 0
    )
    complete = integrity["valid"] and current_days >= REQUIRED_NATURAL_DAYS
    blockers = list(integrity["blockers"])
    if current_segment is None:
        blockers.append("paper_observation_current_run_not_found")
    if current_days < REQUIRED_NATURAL_DAYS:
        blockers.append(WINDOW_BLOCKER)
    blockers.append(CONFIRMATION_BLOCKER)
    if receipts and str(receipts[-1].get("observation_run_id")) != (
        current_observation_run_id
    ):
        blockers.append("paper_observation_current_run_not_latest")
    if receipts and (
        (receipts[-1].get("identity") or {}).get("code_head") != current_head
    ):
        blockers.append("paper_observation_current_head_drift")

    current_summary = _aggregate_receipts(
        [
            receipt
            for receipt in receipts
            if receipt.get("receipt_sha256") in current_receipt_hashes
        ]
    )
    historical_summary = _aggregate_receipts(historical_rows)
    all_time_summary = _aggregate_receipts(receipts)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": (
            "complete_operational_paper_stability_observation"
            if complete
            else "blocked_fail_closed"
        ),
        "decision": (
            "operational_paper_stability_observed_not_alpha_promotion"
            if complete
            else "continue_or_await_authorized_paper_observation"
        ),
        "generated_at_utc": generated.isoformat(),
        "current_head": current_head,
        "required_natural_days": REQUIRED_NATURAL_DAYS,
        "current_run": {
            "observation_run_id": current_observation_run_id,
            "segment_found": current_segment is not None,
            "consecutive_eligible_natural_days": current_days,
            "window_complete": complete,
            "first_date": (
                current_segment.get("first_date") if current_segment else None
            ),
            "latest_date": (
                current_segment.get("latest_date") if current_segment else None
            ),
            "identity": (
                current_segment.get("identity") if current_segment else None
            ),
            "metrics": current_summary,
        },
        "historical_accumulation": {
            "excluded_from_current_run": True,
            "metrics": historical_summary,
        },
        "all_time_audit_only": {
            "never_used_for_current_run_window": True,
            "metrics": all_time_summary,
        },
        "segments": [
            {
                key: value
                for key, value in segment.items()
                if key != "receipt_hashes"
            }
            for segment in segments
        ],
        "ledger_integrity": integrity,
        "readiness": {
            "operational_paper_stability_observed": complete,
            "strategy_alpha_promotion_ready": False,
            "independent_252_trading_day_confirmation_complete": False,
            "promotion_evidence_ready": False,
            "live_ready": False,
        },
        "blockers": _dedupe(blockers),
        "safety_flags": safety_flags(),
    }
    report["report_sha256"] = stable_payload_hash(report)
    return report


def write_observation_report_artifact(
    *,
    report: Mapping[str, Any],
    output_root: Path,
) -> dict[str, str]:
    """Write immutable report and manifest; never create a latest pointer."""

    report_hash = str(report.get("report_sha256") or "")
    if not _SHA256.fullmatch(report_hash) or stable_payload_hash(
        report, exclude={"report_sha256"}
    ) != report_hash:
        raise IbkrPaperObservationError("paper_observation_report_hash_invalid")
    run_id = _safe_component(
        str((report.get("current_run") or {}).get("observation_run_id") or "")
    )
    generated = _safe_component(str(report.get("generated_at_utc") or ""))
    artifact_dir = output_root / run_id / f"{generated}-{report_hash[:12]}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    report_path = artifact_dir / "observation_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    written_report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "report_path": str(report_path),
        "report_file_sha256": written_report_hash,
        "report_payload_sha256": report_hash,
        "current_head": str(report.get("current_head") or ""),
        "current_observation_run_id": str(
            (report.get("current_run") or {}).get("observation_run_id") or ""
        ),
        "latest_pointer_updated": False,
        "promotion_evidence_ready": False,
        "live_ready": False,
    }
    manifest_path = artifact_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "report_path": str(report_path),
        "report_file_sha256": written_report_hash,
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
    }


def stable_payload_hash(
    value: Mapping[str, Any] | Sequence[Any],
    *,
    exclude: set[str] | None = None,
) -> str:
    excluded = exclude or set()
    if isinstance(value, Mapping):
        normalized: Any = {
            key: item for key, item in value.items() if key not in excluded
        }
    else:
        normalized = list(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safety_flags() -> dict[str, bool]:
    return {
        "accumulator_network_used": False,
        "accumulator_broker_called": False,
        "accumulator_private_endpoint_called": False,
        "accumulator_order_submitted": False,
        "accumulator_order_cancelled": False,
        "paper_queue_written": False,
        "promotion_ready": False,
        "live_ready": False,
        "withdraw_enabled": False,
    }


def _segments(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    segments: list[list[Mapping[str, Any]]] = []
    reset_reasons: list[str] = []
    for receipt in receipts:
        reason = ""
        if segments:
            previous = segments[-1][-1]
            if _segment_key(previous) != _segment_key(receipt):
                reason = "identity_or_run_drift"
            else:
                previous_date = _parse_date(previous.get("observation_date"))
                current_date = _parse_date(receipt.get("observation_date"))
                if (
                    previous_date is None
                    or current_date is None
                    or current_date != previous_date + timedelta(days=1)
                ):
                    reason = "natural_day_gap"
                elif previous.get("counts_toward_30_day_window") is not True:
                    reason = "previous_day_ineligible"
        if not segments or reason:
            segments.append([receipt])
            reset_reasons.append(reason or "initial_segment")
        else:
            segments[-1].append(receipt)
    return [
        _summarize_segment(index + 1, rows, reset_reasons[index])
        for index, rows in enumerate(segments)
    ]


def _summarize_segment(
    index: int,
    rows: Sequence[Mapping[str, Any]],
    reset_reason: str,
) -> dict[str, Any]:
    eligible_streak = 0
    for row in rows:
        if row.get("counts_toward_30_day_window") is True:
            eligible_streak += 1
        else:
            eligible_streak = 0
    return {
        "segment_index": index,
        "reset_reason": reset_reason,
        "observation_run_id": str(rows[-1].get("observation_run_id") or ""),
        "identity": dict(rows[-1].get("identity") or {}),
        "first_date": str(rows[0].get("observation_date") or ""),
        "latest_date": str(rows[-1].get("observation_date") or ""),
        "receipt_count": len(rows),
        "eligible_receipt_count": sum(
            row.get("counts_toward_30_day_window") is True for row in rows
        ),
        "consecutive_eligible_natural_days": eligible_streak,
        "receipt_hashes": [str(row.get("receipt_sha256") or "") for row in rows],
    }


def _aggregate_receipts(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    totals = {field: 0 for field in _COUNT_FIELDS}
    commission = 0.0
    slippage = 0.0
    eligible_days = 0
    for receipt in receipts:
        counts = receipt.get("counts") or {}
        for field in _COUNT_FIELDS:
            totals[field] += int(counts.get(field) or 0)
        commission += float(receipt.get("commission") or 0.0)
        slippage += float(receipt.get("slippage") or 0.0)
        eligible_days += receipt.get("counts_toward_30_day_window") is True
    return {
        "receipt_days": len(receipts),
        "eligible_days": eligible_days,
        **totals,
        "commission": commission,
        "slippage": slippage,
    }


def _segment_key(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    identity = receipt.get("identity") or {}
    return (
        str(receipt.get("observation_run_id") or ""),
        *(str(identity.get(field) or "") for field in _IDENTITY_FIELDS),
    )


def _payload(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise IbkrPaperObservationError("observation_input_payload_missing")
    return payload


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise IbkrPaperObservationError(f"paper_observation_{field}_missing")
    return value


def _required_hash(
    payload: Mapping[str, Any],
    field: str,
    *,
    commit: bool = False,
) -> str:
    value = _required_text(payload, field)
    pattern = _HEX_COMMIT if commit else _SHA256
    if not pattern.fullmatch(value):
        raise IbkrPaperObservationError(f"paper_observation_{field}_invalid")
    return value


def _nonnegative_int(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IbkrPaperObservationError(
            f"paper_observation_{field}_nonnegative_integer_required"
        )
    return value


def _finite_number(payload: Mapping[str, Any], field: str) -> float:
    value = payload.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise IbkrPaperObservationError(
            f"paper_observation_{field}_number_required"
        )
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise IbkrPaperObservationError(
            f"paper_observation_{field}_finite_required"
        )
    return number


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise IbkrPaperObservationError(
            "paper_observation_timezone_aware_datetime_required"
        )
    return value.astimezone(timezone.utc)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _safe_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    if not component:
        raise IbkrPaperObservationError(
            "paper_observation_artifact_component_invalid"
        )
    return component


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
