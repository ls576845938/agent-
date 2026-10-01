from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "btc_demo_observation_accumulator_v3"
RECEIPT_SCHEMA_VERSION = "btc_demo_hourly_observation_receipt_v1"
PRIVATE_READONLY_RECEIPT_SCHEMA_VERSION = (
    "btc_demo_private_readonly_hourly_observation_receipt_v2"
)
MANIFEST_SCHEMA_VERSION = "btc_demo_observation_accumulator_manifest_v3"
DEFAULT_OPERATING_TIMEZONE = "Asia/Shanghai"
REQUIRED_OBSERVATION_HOURS = 25
OBSERVATION_WINDOW_BLOCKER = "btc_okx_native:25_hour_demo_observation_window_incomplete"
AWAITING_RUNTIME_BLOCKER = "awaiting_authorized_observation_runtime"
AUTHORIZED_EVIDENCE_CLASS = "authorized_okx_demo_natural_observation"
PRIVATE_READONLY_EVIDENCE_CLASS = (
    "authorized_okx_demo_private_readonly_observation"
)
_HEX_HEAD = re.compile(r"^[0-9a-f]{40,64}$")


class ObservationReceiptError(ValueError):
    """Raised when an append-only observation receipt violates its contract."""


def build_hourly_observation_receipt(
    *,
    source_head: str,
    strategy_version: str,
    data_version: str,
    runtime_version: str,
    observed_at_utc: datetime,
    heartbeat_status: str,
    natural_sample_count: int,
    fill_count: int,
    funding_observation_count: int,
    funding_cashflow: float,
    reconciliation_status: str,
    outage_count: int,
    gap_flags: Sequence[str] = (),
    previous_receipt_sha256: str | None = None,
    operating_timezone: str = DEFAULT_OPERATING_TIMEZONE,
    authorized_runtime_observed: bool,
    runtime_run_id: str = "runtime-run-unbound",
    backfilled: bool = False,
    fixture: bool = False,
    evidence_class: str = AUTHORIZED_EVIDENCE_CLASS,
    private_read_authorized: bool = False,
    private_read_used: bool = False,
    private_endpoint_called: bool = False,
    network_used: bool = False,
    secret_read: bool = False,
    demo_runtime_started: bool = False,
) -> dict[str, Any]:
    """Build one factual OKX Demo hourly receipt.

    The caller supplies already-observed runtime facts.  This builder never
    opens a socket or endpoint and never turns fixture/backfilled facts into
    promotion evidence.
    """

    observed = _ensure_utc(observed_at_utc)
    _require_identity(
        source_head=source_head,
        strategy_version=strategy_version,
        data_version=data_version,
        runtime_version=runtime_version,
    )
    if backfilled:
        raise ObservationReceiptError("observation_receipt_backfill_forbidden")
    if not runtime_run_id.strip():
        raise ObservationReceiptError("observation_runtime_run_id_missing")
    if not isinstance(authorized_runtime_observed, bool):
        raise ObservationReceiptError(
            "authorized_runtime_observed_boolean_required"
        )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (
            natural_sample_count,
            fill_count,
            funding_observation_count,
            outage_count,
        )
    ):
        raise ObservationReceiptError(
            "observation_receipt_nonnegative_counts_required"
        )
    if not heartbeat_status:
        raise ObservationReceiptError("observation_receipt_heartbeat_required")
    if reconciliation_status not in {
        "reconciled",
        "mismatch",
        "unknown",
        "not_observed",
    }:
        raise ObservationReceiptError(
            "observation_receipt_reconciliation_status_invalid"
        )
    if previous_receipt_sha256 is not None and not _is_sha256(
        previous_receipt_sha256
    ):
        raise ObservationReceiptError(
            "observation_receipt_previous_hash_invalid"
        )
    zone = ZoneInfo(operating_timezone)
    observation_hour = observed.replace(minute=0, second=0, microsecond=0)
    operating_hour = observed.astimezone(zone).replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    private_readonly = evidence_class == PRIVATE_READONLY_EVIDENCE_CLASS
    if not private_readonly and any(
        (
            private_read_authorized,
            private_read_used,
            private_endpoint_called,
            network_used,
            secret_read,
            demo_runtime_started,
        )
    ):
        raise ObservationReceiptError(
            "observation_receipt_v1_private_access_forbidden"
        )
    safety = (
        _private_readonly_safety_flags()
        if private_readonly
        else safety_flags()
    )
    access = (
        _private_readonly_access_profile(
            private_read_authorized=private_read_authorized,
            private_read_used=private_read_used,
            private_endpoint_called=private_endpoint_called,
            network_used=network_used,
            secret_read=secret_read,
            demo_runtime_started=demo_runtime_started,
        )
        if private_readonly
        else None
    )
    private_readonly_profile = _private_readonly_safety_profile_valid(
        evidence_class=evidence_class,
        safety=safety,
        access=access,
    )
    standard_profile = (
        evidence_class == AUTHORIZED_EVIDENCE_CLASS
        and _legacy_safety_profile_valid(safety)
    )
    if evidence_class == PRIVATE_READONLY_EVIDENCE_CLASS and not private_readonly_profile:
        raise ObservationReceiptError(
            "observation_receipt_private_readonly_safety_profile_invalid"
        )
    qualifies = (
        authorized_runtime_observed
        and not fixture
        and (standard_profile or private_readonly_profile)
        and reconciliation_status == "reconciled"
        and outage_count == 0
        and not gap_flags
    )
    payload: dict[str, Any] = {
        "schema_version": (
            PRIVATE_READONLY_RECEIPT_SCHEMA_VERSION
            if private_readonly
            else RECEIPT_SCHEMA_VERSION
        ),
        "receipt_kind": "authorized_okx_demo_hourly_observation",
        "observation_hour_utc": observation_hour.isoformat(),
        "operating_hour": operating_hour.isoformat(),
        "operating_timezone": operating_timezone,
        "observed_at_utc": observed.isoformat(),
        "source_head": source_head,
        "strategy_version": strategy_version,
        "data_version": data_version,
        "runtime_version": runtime_version,
        "runtime_run_id": runtime_run_id,
        "heartbeat_status": heartbeat_status,
        "natural_sample_count": natural_sample_count,
        "fill_count": fill_count,
        "funding": {
            "observation_count": funding_observation_count,
            "cashflow": float(funding_cashflow),
        },
        "reconciliation_status": reconciliation_status,
        "outage_count": outage_count,
        "gap_flags": _dedupe_strings(gap_flags),
        "authorized_runtime_observed": authorized_runtime_observed,
        "natural_time_observation": authorized_runtime_observed,
        "runtime_environment": "okx_demo",
        "evidence_class": evidence_class,
        "fixture": fixture,
        "backfilled": False,
        "counts_toward_25_hour_window": qualifies,
        "previous_receipt_sha256": previous_receipt_sha256,
        "safety": safety,
    }
    if access is not None:
        payload["access"] = access
    payload["receipt_sha256"] = stable_payload_hash(payload)
    return payload


def build_awaiting_authorized_runtime_receipt(
    *,
    source_head: str,
    strategy_version: str,
    data_version: str,
    runtime_version: str,
    generated_at_utc: datetime,
    run_id: str,
    operating_timezone: str = DEFAULT_OPERATING_TIMEZONE,
) -> dict[str, Any]:
    """Emit a non-observation receipt when runtime authority is absent."""

    generated = _ensure_utc(generated_at_utc)
    _require_identity(
        source_head=source_head,
        strategy_version=strategy_version,
        data_version=data_version,
        runtime_version=runtime_version,
    )
    payload: dict[str, Any] = {
        "schema_version": "btc_demo_observation_runtime_receipt_v1",
        "receipt_kind": AWAITING_RUNTIME_BLOCKER,
        "status": AWAITING_RUNTIME_BLOCKER,
        "decision": "blocked_fail_closed_no_demo_no_private_no_order",
        "run_id": run_id,
        "source_head": source_head,
        "code_commit": source_head,
        "strategy_version": strategy_version,
        "data_version": data_version,
        "runtime_version": runtime_version,
        "runtime_run_id": run_id,
        "generated_at_utc": generated.isoformat(),
        "observation_hour_utc": generated.replace(
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat(),
        "operating_hour": generated.astimezone(
            ZoneInfo(operating_timezone)
        ).replace(minute=0, second=0, microsecond=0).isoformat(),
        "operating_timezone": operating_timezone,
        "natural_time_observation": False,
        "authorized_runtime_observed": False,
        "runtime_environment": "okx_demo",
        "evidence_class": "awaiting_authorized_runtime",
        "fixture": False,
        "counts_toward_25_hour_window": False,
        "blockers": [
            AWAITING_RUNTIME_BLOCKER,
            OBSERVATION_WINDOW_BLOCKER,
        ],
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "safety": safety_flags(),
    }
    payload["receipt_sha256"] = stable_payload_hash(payload)
    return payload


def validate_hourly_observation_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_previous_receipt_sha256: str | None,
) -> list[str]:
    blockers: list[str] = []
    schema_version = str(receipt.get("schema_version") or "")
    if receipt.get("receipt_kind") != "authorized_okx_demo_hourly_observation":
        blockers.append("observation_receipt_kind_invalid")
    source_head = str(receipt.get("source_head") or "")
    if not _HEX_HEAD.fullmatch(source_head):
        blockers.append("observation_receipt_source_head_invalid")
    for field in (
        "strategy_version",
        "data_version",
        "runtime_version",
        "runtime_run_id",
    ):
        if not str(receipt.get(field) or "").strip():
            blockers.append(f"observation_receipt_{field}_missing")
    observed = _parse_utc(receipt.get("observed_at_utc"))
    if observed is None:
        blockers.append("observation_receipt_observed_at_invalid")
    observation_hour = _parse_utc(receipt.get("observation_hour_utc"))
    try:
        zone = ZoneInfo(
            str(
                receipt.get("operating_timezone")
                or DEFAULT_OPERATING_TIMEZONE
            )
        )
    except (KeyError, ValueError):
        zone = None
        blockers.append("observation_receipt_timezone_invalid")
    if observed is not None and observation_hour is not None:
        if observed.replace(minute=0, second=0, microsecond=0) != observation_hour:
            blockers.append("observation_receipt_hour_mismatch")
    if zone is not None:
        operating_hour = _parse_datetime(receipt.get("operating_hour"))
        if operating_hour is None:
            blockers.append("observation_receipt_operating_hour_invalid")
        elif observed is not None and observed.astimezone(zone).replace(
            minute=0,
            second=0,
            microsecond=0,
        ) != operating_hour.astimezone(zone):
            blockers.append("observation_receipt_operating_hour_mismatch")
    if receipt.get("backfilled") is not False:
        blockers.append("observation_receipt_backfill_forbidden")
    if receipt.get("authorized_runtime_observed") is not True:
        blockers.append("observation_receipt_runtime_authority_missing")
    if receipt.get("natural_time_observation") is not True:
        blockers.append("observation_receipt_not_natural_time")
    if receipt.get("runtime_environment") != "okx_demo":
        blockers.append("observation_receipt_not_okx_demo")
    evidence_class = str(receipt.get("evidence_class") or "")
    if evidence_class not in {
        AUTHORIZED_EVIDENCE_CLASS,
        PRIVATE_READONLY_EVIDENCE_CLASS,
    }:
        blockers.append("observation_receipt_not_authorized_demo_evidence")
    if receipt.get("fixture") is not False:
        blockers.append("observation_receipt_fixture_forbidden")
    safety = receipt.get("safety")
    access = receipt.get("access")
    standard_safety = (
        schema_version == RECEIPT_SCHEMA_VERSION
        and evidence_class == AUTHORIZED_EVIDENCE_CLASS
        and isinstance(safety, Mapping)
        and _legacy_safety_profile_valid(safety)
        and access is None
    )
    private_readonly_safety = (
        schema_version == PRIVATE_READONLY_RECEIPT_SCHEMA_VERSION
        and isinstance(safety, Mapping)
        and _private_readonly_safety_profile_valid(
            evidence_class=evidence_class,
            safety=safety,
            access=access,
        )
    )
    if not (standard_safety or private_readonly_safety):
        blockers.append("observation_receipt_schema_mismatch")
    if not (standard_safety or private_readonly_safety):
        blockers.append("observation_receipt_safety_boundary_violation")
    expected_counts = (
        receipt.get("authorized_runtime_observed") is True
        and receipt.get("natural_time_observation") is True
        and receipt.get("runtime_environment") == "okx_demo"
        and (standard_safety or private_readonly_safety)
        and receipt.get("fixture") is False
        and receipt.get("backfilled") is False
        and receipt.get("reconciliation_status") == "reconciled"
        and int(receipt.get("outage_count") or 0) == 0
        and not list(receipt.get("gap_flags") or [])
    )
    if receipt.get("counts_toward_25_hour_window") is not expected_counts:
        blockers.append("observation_receipt_eligibility_mismatch")
    if receipt.get("previous_receipt_sha256") != (
        expected_previous_receipt_sha256
    ):
        blockers.append("observation_receipt_hash_chain_mismatch")
    recorded_hash = str(receipt.get("receipt_sha256") or "")
    if not _is_sha256(recorded_hash):
        blockers.append("observation_receipt_hash_invalid")
    elif stable_payload_hash(receipt, exclude={"receipt_sha256"}) != recorded_hash:
        blockers.append("observation_receipt_hash_mismatch")
    return _dedupe_strings(blockers)


def load_observation_receipt_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ObservationReceiptError(
                f"observation_receipt_ledger_truncated_or_invalid:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ObservationReceiptError(
                f"observation_receipt_object_required:{line_number}"
            )
        rows.append(row)
    integrity = _ledger_integrity(rows)
    if integrity["blockers"]:
        raise ObservationReceiptError(integrity["blockers"][0])
    return rows


def append_hourly_observation_receipt(
    *,
    ledger_path: Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one receipt, deduplicating exact retries and rejecting backfill."""

    existing = load_observation_receipt_ledger(ledger_path)
    receipt_hash = str(receipt.get("receipt_sha256") or "")
    if any(row.get("receipt_sha256") == receipt_hash for row in existing):
        return {
            "appended": False,
            "duplicate": True,
            "receipt_sha256": receipt_hash,
            "ledger_row_count": len(existing),
        }
    expected_previous = (
        str(existing[-1]["receipt_sha256"]) if existing else None
    )
    blockers = validate_hourly_observation_receipt(
        receipt,
        expected_previous_receipt_sha256=expected_previous,
    )
    if blockers:
        raise ObservationReceiptError(blockers[0])
    new_hour = _parse_utc(receipt.get("observation_hour_utc"))
    if new_hour is None:
        raise ObservationReceiptError("observation_receipt_hour_invalid")
    existing_hours = {
        str(row.get("observation_hour_utc")): str(row.get("receipt_sha256"))
        for row in existing
    }
    if new_hour.isoformat() in existing_hours:
        raise ObservationReceiptError(
            "observation_receipt_observation_hour_conflict"
        )
    if existing:
        previous_hour = _parse_utc(existing[-1].get("observation_hour_utc"))
        previous_time = _parse_utc(existing[-1].get("observed_at_utc"))
        current_time = _parse_utc(receipt.get("observed_at_utc"))
        if previous_hour is not None and new_hour < previous_hour:
            raise ObservationReceiptError(
                "observation_receipt_historical_backfill_forbidden"
            )
        if (
            previous_time is not None
            and current_time is not None
            and current_time <= previous_time
        ):
            raise ObservationReceiptError(
                "observation_receipt_nonmonotonic_time"
            )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        ledger_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_BINARY,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "appended": True,
        "duplicate": False,
        "receipt_sha256": receipt_hash,
        "ledger_row_count": len(existing) + 1,
    }


def build_observation_window_report(
    *,
    receipts: Sequence[Mapping[str, Any]],
    current_head: str,
    current_strategy_version: str,
    current_data_version: str | None = None,
    current_runtime_version: str | None = None,
    run_id: str,
    generated_at_utc: datetime,
    operating_timezone: str = DEFAULT_OPERATING_TIMEZONE,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc)
    integrity = _ledger_integrity(receipts)
    segments = (
        _version_segments(receipts)
        if not integrity["blockers"]
        else []
    )
    latest = segments[-1] if segments else None
    blockers = list(integrity["blockers"])
    if latest is None:
        blockers.append(AWAITING_RUNTIME_BLOCKER)
    elif latest["source_head"] != current_head:
        blockers.append("observation_window_current_head_mismatch")
    elif latest["strategy_version"] != current_strategy_version:
        blockers.append("observation_window_strategy_version_mismatch")
    elif (
        current_data_version is not None
        and latest["data_version"] != current_data_version
    ):
        blockers.append("observation_window_data_version_mismatch")
    elif (
        current_runtime_version is not None
        and latest["runtime_version"] != current_runtime_version
    ):
        blockers.append("observation_window_runtime_version_mismatch")
    observation_hours = (
        int(latest["continuous_observation_hours"]) if latest else 0
    )
    window_25h_complete = observation_hours >= REQUIRED_OBSERVATION_HOURS
    # Demo operations may resume after a frontend/backend restart.  Preserve
    # every eligible, hash-chain-validated receipt for the operator's
    # cumulative observation target while keeping the strict latest-segment
    # window above unchanged for promotion/readiness decisions.
    cumulative_observation_hours = sum(
        int(segment["eligible_receipt_count"])
        for segment in segments
    )
    cumulative_window_25h_complete = (
        cumulative_observation_hours >= REQUIRED_OBSERVATION_HOURS
    )
    cumulative_blockers = list(integrity["blockers"])
    if not cumulative_window_25h_complete:
        cumulative_blockers.append(OBSERVATION_WINDOW_BLOCKER)
    cumulative_blockers = _dedupe_strings(cumulative_blockers)
    if not window_25h_complete:
        blockers.append(OBSERVATION_WINDOW_BLOCKER)
    if latest and latest["current_segment_reset_reason"]:
        blockers.append(str(latest["current_segment_reset_reason"]))
    blockers = _dedupe_strings(blockers)
    version_boundary_detected = len(segments) > 1
    status = (
        AWAITING_RUNTIME_BLOCKER
        if latest is None and not integrity["blockers"]
        else (
            "blocked_fail_closed"
            if integrity["blockers"]
            else (
                "complete_25h_demo_observation_window"
                if window_25h_complete
                else "collecting_natural_observation"
            )
        )
    )
    decision = (
        "observation_window_complete_manual_and_external_gates_still_required"
        if window_25h_complete and not integrity["blockers"]
        else "continue_authorized_demo_observation_no_paper_no_live"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "decision": decision,
        "run_id": run_id,
        "source_head": current_head,
        "code_commit": current_head,
        "strategy_version": current_strategy_version,
        "data_version": (
            current_data_version
            if current_data_version is not None
            else (latest["data_version"] if latest else "")
        ),
        "runtime_version": (
            current_runtime_version
            if current_runtime_version is not None
            else (latest["runtime_version"] if latest else "")
        ),
        "runtime_run_id": latest["runtime_run_id"] if latest else "",
        "generated_at_utc": generated.isoformat(),
        "operating_timezone": operating_timezone,
        "authority": "authorized_okx_demo_accumulator",
        "evidence_class": "authorized_okx_demo_observation_window",
        "required_observation_hours": REQUIRED_OBSERVATION_HOURS,
        "observation_hours": observation_hours,
        "window_25h_complete": window_25h_complete,
        "cumulative_observation_hours": cumulative_observation_hours,
        "cumulative_window_25h_complete": cumulative_window_25h_complete,
        "cumulative_blockers": cumulative_blockers,
        "ledger_integrity": integrity,
        "version_policy": {
            "cross_head_accumulation_allowed": False,
            "cross_strategy_version_accumulation_allowed": False,
            "cross_data_version_accumulation_allowed": False,
            "cross_runtime_version_accumulation_allowed": False,
            "cross_runtime_run_accumulation_allowed": False,
            "cumulative_across_boundaries_allowed": True,
            "cumulative_boundary_action": "count_eligible_receipts_without_retroactive_backfill",
            "version_boundary_detected": version_boundary_detected,
            "boundary_action": (
                "latest_version_segment_restarted"
                if version_boundary_detected
                else "single_version_segment"
            ),
        },
        "segments": segments,
        "summary": {
            "observation_hours": observation_hours,
            "cumulative_observation_hours": cumulative_observation_hours,
            "receipt_count": len(receipts),
            "cumulative_eligible_receipt_count": cumulative_observation_hours,
            "segment_count": len(segments),
            "gap_hours": list(latest["gap_hours"]) if latest else [],
            "eligible_receipt_count": (
                int(latest["eligible_receipt_count"]) if latest else 0
            ),
            "natural_sample_count": (
                int(latest["natural_sample_count"]) if latest else 0
            ),
            "fill_count": int(latest["fill_count"]) if latest else 0,
            "funding_observation_count": (
                int(latest["funding_observation_count"]) if latest else 0
            ),
            "funding_cashflow": (
                float(latest["funding_cashflow"]) if latest else 0.0
            ),
            "reconciliation_failure_hours": (
                list(latest["reconciliation_failure_hours"])
                if latest
                else []
            ),
            "outage_hours": list(latest["outage_hours"]) if latest else [],
            "gap_flag_hours": list(latest["gap_flag_hours"]) if latest else [],
        },
        "readiness": {
            "quality_checked": not integrity["blockers"],
            "research_ready": False,
            "backtest_ready": False,
            "observation_window_ready": (
                window_25h_complete and not integrity["blockers"]
            ),
            "cumulative_observation_target_reached": (
                cumulative_window_25h_complete and not integrity["blockers"]
            ),
            "promotion_evidence_ready": False,
            "manual_approval_still_independent": True,
        },
        "quality_checked": not integrity["blockers"],
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "blockers": blockers,
        "safety": safety_flags(),
    }
    report["artifact_hash"] = stable_payload_hash(report)
    return report


def write_observation_window_artifact(
    *,
    report: Mapping[str, Any],
    output_root: Path,
    run_id: str,
) -> dict[str, Any]:
    """Write an immutable run artifact without mutating a latest pointer."""

    run_directory = output_root / "runs" / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    report_path = run_directory / "btc_demo_observation_accumulator_report.json"
    report_bytes = (
        json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    report_path.write_bytes(report_bytes)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "source_head": report.get("source_head"),
        "generated_at_utc": report.get("generated_at_utc"),
        "immutable": True,
        "latest_pointer_updated": False,
        "report_path": report_path.name,
        "report_sha256": report_sha256,
        "status": report.get("status"),
        "decision": report.get("decision"),
        "quality_checked": report.get("quality_checked") is True,
        "promotion_evidence_ready": False,
        "blockers": list(report.get("blockers") or []),
        "safety": safety_flags(),
    }
    manifest_path = run_directory / "manifest.json"
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    return {
        "run_directory": str(run_directory),
        "report_path": str(report_path),
        "report_sha256": report_sha256,
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "latest_pointer_updated": False,
    }


def stable_payload_hash(
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    exclude: set[str] | None = None,
) -> str:
    value: Any = payload
    if isinstance(payload, Mapping) and exclude:
        value = {
            key: item
            for key, item in payload.items()
            if key not in exclude
        }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safety_flags() -> dict[str, bool]:
    """Return the legacy v1 all-false safety shape used by existing evidence."""

    return {
        "promotion_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "private_endpoint_called": False,
        "order_endpoint_called": False,
        "broker_enabled": False,
        "withdraw_enabled": False,
        "demo_runtime_started": False,
        "paper_queue_written": False,
        "real_order_submitted": False,
        "network_used": False,
        "secret_read": False,
    }


def _private_readonly_access_profile(
    *,
    private_read_authorized: bool = False,
    private_read_used: bool = False,
    private_endpoint_called: bool = False,
    network_used: bool = False,
    secret_read: bool = False,
    demo_runtime_started: bool = False,
) -> dict[str, bool]:
    return {
        "private_read_authorized": bool(private_read_authorized),
        "private_read_used": bool(private_read_used),
        "private_endpoint_called": bool(private_endpoint_called),
        "demo_runtime_started": bool(demo_runtime_started),
        "network_used": bool(network_used),
        "secret_read": bool(secret_read),
    }


def _private_readonly_safety_flags() -> dict[str, bool]:
    return {
        "promotion_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_endpoint_called": False,
        "cancel_endpoint_called": False,
        "broker_enabled": False,
        "transfer_enabled": False,
        "withdraw_enabled": False,
        "paper_queue_written": False,
        "real_order_submitted": False,
    }


def _legacy_safety_profile_valid(safety: Mapping[str, Any]) -> bool:
    expected = safety_flags()
    return set(safety) == set(expected) and all(
        safety.get(key) is expected[key] for key in expected
    )


def _private_readonly_safety_profile_valid(
    *,
    evidence_class: str,
    safety: Mapping[str, Any],
    access: Any,
) -> bool:
    if evidence_class != PRIVATE_READONLY_EVIDENCE_CLASS:
        return False
    if not isinstance(access, Mapping):
        return False
    access_keys = {
        "private_read_authorized",
        "private_read_used",
        "private_endpoint_called",
        "demo_runtime_started",
        "network_used",
        "secret_read",
    }
    expected_safety = _private_readonly_safety_flags()
    return (
        set(safety) == set(expected_safety)
        and all(safety.get(key) is expected_safety[key] for key in expected_safety)
        and set(access) == access_keys
        and all(access.get(key) is True for key in access_keys)
    )


def _ledger_integrity(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    previous: str | None = None
    seen_hashes: set[str] = set()
    seen_hours: set[str] = set()
    previous_hour: datetime | None = None
    previous_time: datetime | None = None
    for row in receipts:
        row_blockers = validate_hourly_observation_receipt(
            row,
            expected_previous_receipt_sha256=previous,
        )
        blockers.extend(row_blockers)
        row_hash = str(row.get("receipt_sha256") or "")
        if row_hash in seen_hashes:
            blockers.append("observation_receipt_duplicate_hash")
        seen_hashes.add(row_hash)
        row_hour = _parse_utc(row.get("observation_hour_utc"))
        if row_hour is not None:
            hour_key = row_hour.isoformat()
            if hour_key in seen_hours:
                blockers.append("observation_receipt_observation_hour_conflict")
            seen_hours.add(hour_key)
            if previous_hour is not None and row_hour < previous_hour:
                blockers.append(
                    "observation_receipt_historical_backfill_forbidden"
                )
            previous_hour = row_hour
        row_time = _parse_utc(row.get("observed_at_utc"))
        if (
            previous_time is not None
            and row_time is not None
            and row_time <= previous_time
        ):
            blockers.append("observation_receipt_nonmonotonic_time")
        if row_time is not None:
            previous_time = row_time
        previous = row_hash
    return {
        "valid": not blockers,
        "receipt_count": len(receipts),
        "ledger_sha256": stable_payload_hash(list(receipts)),
        "last_receipt_sha256": previous,
        "blockers": _dedupe_strings(blockers),
    }


def _version_segments(
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    segments: list[list[Mapping[str, Any]]] = []
    for receipt in receipts:
        identity = _identity(receipt)
        if not segments or _identity(segments[-1][-1]) != identity:
            segments.append([receipt])
        else:
            segments[-1].append(receipt)
    return [
        _summarize_segment(index=index, receipts=rows)
        for index, rows in enumerate(segments, start=1)
    ]


def _summarize_segment(
    *,
    index: int,
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    hours = [
        parsed
        for row in receipts
        for parsed in [_parse_utc(row.get("observation_hour_utc"))]
        if parsed is not None
    ]
    gap_hours: list[str] = []
    for previous, current in zip(hours, hours[1:]):
        cursor = previous + timedelta(hours=1)
        while cursor < current:
            gap_hours.append(cursor.isoformat())
            cursor += timedelta(hours=1)
    continuous_start_index = 0
    reset_reason = ""
    for position, row in enumerate(receipts):
        if row.get("counts_toward_25_hour_window") is not True:
            continuous_start_index = position + 1
            reset_reason = _receipt_reset_reason(row)
        if position > 0 and hours[position] != hours[position - 1] + timedelta(hours=1):
            continuous_start_index = position
            reset_reason = "btc_demo_observation_gap_present"
    continuous_hours = len(hours[continuous_start_index:])
    identity = _identity(receipts[0])
    return {
        "segment_index": index,
        **identity,
        "start_observation_hour_utc": hours[0].isoformat() if hours else None,
        "end_observation_hour_utc": hours[-1].isoformat() if hours else None,
        "receipt_count": len(receipts),
        "eligible_receipt_count": sum(
            row.get("counts_toward_25_hour_window") is True for row in receipts
        ),
        "continuous_observation_hours": continuous_hours,
        "current_segment_reset_reason": (
            reset_reason if continuous_hours < REQUIRED_OBSERVATION_HOURS else ""
        ),
        "gap_hours": gap_hours,
        "gap_records": [
            {
                "observation_hour_utc": missing,
                "status": "gap_missing_receipt",
                "counts_as_success": False,
                "backfilled": False,
            }
            for missing in gap_hours
        ],
        "natural_sample_count": sum(
            int(row.get("natural_sample_count") or 0) for row in receipts
        ),
        "fill_count": sum(int(row.get("fill_count") or 0) for row in receipts),
        "funding_observation_count": sum(
            int((row.get("funding") or {}).get("observation_count") or 0)
            for row in receipts
        ),
        "funding_cashflow": sum(
            float((row.get("funding") or {}).get("cashflow") or 0.0)
            for row in receipts
        ),
        "reconciliation_failure_hours": [
            str(row.get("observation_hour_utc"))
            for row in receipts
            if row.get("reconciliation_status") != "reconciled"
        ],
        "outage_hours": [
            str(row.get("observation_hour_utc"))
            for row in receipts
            if int(row.get("outage_count") or 0) > 0
        ],
        "gap_flag_hours": [
            str(row.get("observation_hour_utc"))
            for row in receipts
            if list(row.get("gap_flags") or [])
        ],
    }


def _identity(receipt: Mapping[str, Any]) -> dict[str, str]:
    return {
        "source_head": str(receipt.get("source_head") or ""),
        "strategy_version": str(receipt.get("strategy_version") or ""),
        "data_version": str(receipt.get("data_version") or ""),
        "runtime_version": str(receipt.get("runtime_version") or ""),
        "runtime_run_id": str(receipt.get("runtime_run_id") or ""),
    }


def _receipt_reset_reason(receipt: Mapping[str, Any]) -> str:
    if receipt.get("reconciliation_status") != "reconciled":
        return "btc_demo_observation_reconciliation_failure_present"
    if int(receipt.get("outage_count") or 0) > 0:
        return "btc_demo_observation_outage_present"
    if list(receipt.get("gap_flags") or []):
        return "btc_demo_observation_gap_present"
    if receipt.get("fixture") is not False:
        return "btc_demo_observation_fixture_receipt_present"
    if receipt.get("authorized_runtime_observed") is not True:
        return AWAITING_RUNTIME_BLOCKER
    return "btc_demo_observation_receipt_not_eligible"


def _require_identity(
    *,
    source_head: str,
    strategy_version: str,
    data_version: str,
    runtime_version: str,
) -> None:
    if not _HEX_HEAD.fullmatch(source_head):
        raise ObservationReceiptError("observation_source_head_invalid")
    for name, value in (
        ("strategy_version", strategy_version),
        ("data_version", data_version),
        ("runtime_version", runtime_version),
    ):
        if not value.strip():
            raise ObservationReceiptError(f"observation_{name}_missing")


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
        raise ObservationReceiptError("timezone_aware_datetime_required")
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


# Transitional aliases for research-only callers.  The authoritative contract
# emitted by both names is hourly; no daily receipt can satisfy the 25h gate.
build_daily_observation_receipt = build_hourly_observation_receipt
validate_daily_observation_receipt = validate_hourly_observation_receipt
append_daily_observation_receipt = append_hourly_observation_receipt
