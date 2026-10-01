from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.research.btc_demo_observation_accumulator import (
    OBSERVATION_WINDOW_BLOCKER,
    PRIVATE_READONLY_EVIDENCE_CLASS,
    PRIVATE_READONLY_RECEIPT_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    ObservationReceiptError,
    append_hourly_observation_receipt,
    build_awaiting_authorized_runtime_receipt,
    build_hourly_observation_receipt,
    build_observation_window_report,
    load_observation_receipt_ledger,
    safety_flags,
    stable_payload_hash,
    validate_hourly_observation_receipt,
    write_observation_window_artifact,
)


HEAD_A = "a" * 40
HEAD_B = "b" * 40
STRATEGY_A = "btc-trend@1"
STRATEGY_B = "btc-trend@2"
DATA_A = "btc-data-v1"
DATA_B = "btc-data-v2"
RUNTIME_A = "btc-demo-runtime-v1"
RUNTIME_B = "btc-demo-runtime-v2"
BASE_TIME = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)


def test_25_consecutive_real_hours_retire_only_window_blocker() -> None:
    report_24 = _report(_receipts(24))
    assert report_24["observation_hours"] == 24
    assert report_24["window_25h_complete"] is False
    assert OBSERVATION_WINDOW_BLOCKER in report_24["blockers"]

    report_25 = _report(_receipts(25))
    assert report_25["observation_hours"] == 25
    assert report_25["window_25h_complete"] is True
    assert OBSERVATION_WINDOW_BLOCKER not in report_25["blockers"]
    assert report_25["status"] == "complete_25h_demo_observation_window"
    assert report_25["readiness"]["observation_window_ready"] is True
    assert report_25["promotion_evidence_ready"] is False
    assert all(value is False for value in report_25["safety"].values())


def test_missing_hour_fails_closed_and_restarts_consecutive_segment() -> None:
    report = _report(_receipts_for_offsets([0, 1, 3, 4]))

    assert report["observation_hours"] == 2
    assert report["summary"]["gap_hours"] == [
        "2026-01-01T02:00:00+00:00"
    ]
    assert report["segments"][0]["gap_records"] == [
        {
            "observation_hour_utc": "2026-01-01T02:00:00+00:00",
            "status": "gap_missing_receipt",
            "counts_as_success": False,
            "backfilled": False,
        }
    ]
    assert "btc_demo_observation_gap_present" in report["blockers"]


def test_head_strategy_data_and_runtime_boundaries_restart_segments() -> None:
    identities = [
        (HEAD_A, STRATEGY_A, DATA_A, RUNTIME_A),
        (HEAD_B, STRATEGY_A, DATA_A, RUNTIME_A),
        (HEAD_B, STRATEGY_B, DATA_A, RUNTIME_A),
        (HEAD_B, STRATEGY_B, DATA_B, RUNTIME_A),
        (HEAD_B, STRATEGY_B, DATA_B, RUNTIME_B),
    ]
    receipts: list[dict[str, object]] = []
    previous = None
    for offset, (head, strategy, data, runtime) in enumerate(identities):
        receipt = _receipt(
            hour_offset=offset,
            previous=previous,
            head=head,
            strategy=strategy,
            data=data,
            runtime=runtime,
        )
        receipts.append(receipt)
        previous = str(receipt["receipt_sha256"])

    report = build_observation_window_report(
        receipts=receipts,
        current_head=HEAD_B,
        current_strategy_version=STRATEGY_B,
        current_data_version=DATA_B,
        current_runtime_version=RUNTIME_B,
        run_id="segmented",
        generated_at_utc=BASE_TIME + timedelta(hours=8),
    )

    assert len(report["segments"]) == 5
    assert report["observation_hours"] == 1
    assert report["version_policy"]["version_boundary_detected"] is True
    assert report["version_policy"]["boundary_action"] == (
        "latest_version_segment_restarted"
    )


def test_runtime_process_restart_starts_new_segment() -> None:
    first = _receipt(
        hour_offset=0,
        previous=None,
        runtime_run_id="run-a",
    )
    second = _receipt(
        hour_offset=1,
        previous=str(first["receipt_sha256"]),
        runtime_run_id="run-b",
    )
    report = _report([first, second])

    assert len(report["segments"]) == 2
    assert report["observation_hours"] == 1
    assert report["version_policy"]["version_boundary_detected"] is True


def test_cumulative_target_spans_boundaries_without_unlocking_strict_window() -> None:
    receipts: list[dict[str, object]] = []
    previous: str | None = None
    identities = [
        (HEAD_A, STRATEGY_A, DATA_A, RUNTIME_A),
        (HEAD_A, STRATEGY_A, DATA_A, RUNTIME_A),
        (HEAD_B, STRATEGY_A, DATA_A, RUNTIME_A),
        (HEAD_B, STRATEGY_B, DATA_A, RUNTIME_A),
        (HEAD_B, STRATEGY_B, DATA_B, RUNTIME_B),
    ]
    for offset, (head, strategy, data, runtime) in enumerate(identities):
        receipt = _receipt(
            hour_offset=offset,
            previous=previous,
            head=head,
            strategy=strategy,
            data=data,
            runtime=runtime,
        )
        receipts.append(receipt)
        previous = str(receipt["receipt_sha256"])

    report = build_observation_window_report(
        receipts=receipts,
        current_head=HEAD_B,
        current_strategy_version=STRATEGY_B,
        current_data_version=DATA_B,
        current_runtime_version=RUNTIME_B,
        run_id="cumulative-boundaries",
        generated_at_utc=BASE_TIME + timedelta(hours=8),
    )

    assert report["cumulative_observation_hours"] == 5
    assert report["cumulative_window_25h_complete"] is False
    assert report["observation_hours"] == 1
    assert report["window_25h_complete"] is False
    assert report["version_policy"]["cumulative_across_boundaries_allowed"] is True
    assert report["readiness"]["observation_window_ready"] is False


def test_cumulative_25_hours_can_complete_while_strict_segment_remains_blocked() -> None:
    receipts: list[dict[str, object]] = []
    previous: str | None = None
    for offset in range(25):
        identity = (
            (HEAD_A, STRATEGY_A, DATA_A, RUNTIME_A)
            if offset < 12
            else (HEAD_B, STRATEGY_B, DATA_B, RUNTIME_B)
        )
        receipt = _receipt(
            hour_offset=offset,
            previous=previous,
            head=identity[0],
            strategy=identity[1],
            data=identity[2],
            runtime=identity[3],
        )
        receipts.append(receipt)
        previous = str(receipt["receipt_sha256"])

    report = build_observation_window_report(
        receipts=receipts,
        current_head=HEAD_B,
        current_strategy_version=STRATEGY_B,
        current_data_version=DATA_B,
        current_runtime_version=RUNTIME_B,
        run_id="cumulative-complete",
        generated_at_utc=BASE_TIME + timedelta(hours=30),
    )

    assert report["cumulative_observation_hours"] == 25
    assert report["cumulative_window_25h_complete"] is True
    assert report["readiness"]["cumulative_observation_target_reached"] is True
    assert report["observation_hours"] == 13
    assert report["window_25h_complete"] is False
    assert OBSERVATION_WINDOW_BLOCKER in report["blockers"]
    assert report["promotion_evidence_ready"] is False


def test_append_is_idempotent_but_conflicting_hour_is_rejected(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "receipts.jsonl"
    first = _receipt(hour_offset=0, previous=None)
    assert append_hourly_observation_receipt(
        ledger_path=ledger, receipt=first
    )["appended"] is True
    assert append_hourly_observation_receipt(
        ledger_path=ledger, receipt=first
    )["duplicate"] is True

    conflict = _receipt(
        hour_offset=0,
        previous=str(first["receipt_sha256"]),
        heartbeat_status="degraded",
    )
    with pytest.raises(
        ObservationReceiptError,
        match="observation_receipt_observation_hour_conflict",
    ):
        append_hourly_observation_receipt(
            ledger_path=ledger,
            receipt=conflict,
        )
    assert len(load_observation_receipt_ledger(ledger)) == 1


def test_backfill_and_nonmonotonic_receipts_are_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "receipts.jsonl"
    newer = _receipt(hour_offset=2, previous=None)
    append_hourly_observation_receipt(ledger_path=ledger, receipt=newer)
    older = _receipt(
        hour_offset=1,
        previous=str(newer["receipt_sha256"]),
    )
    with pytest.raises(
        ObservationReceiptError,
        match="observation_receipt_historical_backfill_forbidden",
    ):
        append_hourly_observation_receipt(ledger_path=ledger, receipt=older)


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        (
            {"reconciliation_status": "mismatch"},
            "btc_demo_observation_reconciliation_failure_present",
        ),
        (
            {"outage_count": 1},
            "btc_demo_observation_outage_present",
        ),
        (
            {"gap_flags": ("private_ws_sequence_gap",)},
            "btc_demo_observation_gap_present",
        ),
    ],
)
def test_runtime_failure_hour_restarts_window(
    overrides: dict[str, object],
    blocker: str,
) -> None:
    receipts = _receipts(2)
    failed = _receipt(
        hour_offset=2,
        previous=str(receipts[-1]["receipt_sha256"]),
        **overrides,
    )
    recovered = _receipt(
        hour_offset=3,
        previous=str(failed["receipt_sha256"]),
    )
    report = _report([*receipts, failed, recovered])

    assert report["observation_hours"] == 1
    assert blocker in report["blockers"]
    assert OBSERVATION_WINDOW_BLOCKER in report["blockers"]


def test_fixture_and_awaiting_receipts_never_count() -> None:
    fixture = _receipt(hour_offset=0, previous=None, fixture=True)
    report = _report([fixture])
    awaiting = build_awaiting_authorized_runtime_receipt(
        source_head=HEAD_A,
        strategy_version=STRATEGY_A,
        data_version=DATA_A,
        runtime_version=RUNTIME_A,
        generated_at_utc=BASE_TIME,
        run_id="awaiting",
    )

    assert report["observation_hours"] == 0
    assert report["ledger_integrity"]["valid"] is False
    assert awaiting["counts_toward_25_hour_window"] is False
    assert awaiting["authorized_runtime_observed"] is False
    assert all(value is False for value in awaiting["safety"].values())


def test_hash_tamper_fails_closed() -> None:
    receipt = _receipt(hour_offset=0, previous=None)
    receipt["fill_count"] = 99
    report = _report([receipt])
    assert report["status"] == "blocked_fail_closed"
    assert "observation_receipt_hash_mismatch" in report["blockers"]
    assert report["observation_hours"] == 0


def test_private_readonly_hour_records_actual_restricted_side_effects() -> None:
    receipt = build_hourly_observation_receipt(
        source_head=HEAD_A,
        strategy_version=STRATEGY_A,
        data_version=DATA_A,
        runtime_version=RUNTIME_A,
        observed_at_utc=BASE_TIME,
        heartbeat_status="healthy",
        natural_sample_count=1,
        fill_count=0,
        funding_observation_count=1,
        funding_cashflow=0.0,
        reconciliation_status="reconciled",
        outage_count=0,
        previous_receipt_sha256=None,
        authorized_runtime_observed=True,
        runtime_run_id="private-readonly-run",
        evidence_class=PRIVATE_READONLY_EVIDENCE_CLASS,
        private_read_authorized=True,
        private_read_used=True,
        private_endpoint_called=True,
        network_used=True,
        secret_read=True,
        demo_runtime_started=True,
    )

    assert receipt["schema_version"] == PRIVATE_READONLY_RECEIPT_SCHEMA_VERSION
    assert receipt["counts_toward_25_hour_window"] is True
    assert receipt["access"]["private_read_authorized"] is True
    assert receipt["access"]["private_read_used"] is True
    assert receipt["access"]["private_endpoint_called"] is True
    assert receipt["access"]["network_used"] is True
    assert receipt["access"]["secret_read"] is True
    assert receipt["access"]["demo_runtime_started"] is True
    for key in (
        "order_endpoint_called",
        "cancel_endpoint_called",
        "transfer_enabled",
        "withdraw_enabled",
        "live_enabled",
        "paper_enabled",
        "promotion_enabled",
    ):
        assert receipt["safety"][key] is False
    assert validate_hourly_observation_receipt(
        receipt, expected_previous_receipt_sha256=None
    ) == []


def test_standard_v1_receipt_and_shared_safety_flags_keep_legacy_shape() -> None:
    legacy_keys = {
        "promotion_enabled",
        "paper_enabled",
        "live_enabled",
        "private_endpoint_called",
        "order_endpoint_called",
        "broker_enabled",
        "withdraw_enabled",
        "demo_runtime_started",
        "paper_queue_written",
        "real_order_submitted",
        "network_used",
        "secret_read",
    }
    assert set(safety_flags()) == legacy_keys
    assert all(value is False for value in safety_flags().values())

    receipt = _receipt(hour_offset=0, previous=None)
    assert receipt["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert set(receipt["safety"]) == legacy_keys
    assert "access" not in receipt


def test_standard_v1_builder_rejects_private_access_facts() -> None:
    with pytest.raises(
        ObservationReceiptError,
        match="observation_receipt_v1_private_access_forbidden",
    ):
        build_hourly_observation_receipt(
            source_head=HEAD_A,
            strategy_version=STRATEGY_A,
            data_version=DATA_A,
            runtime_version=RUNTIME_A,
            observed_at_utc=BASE_TIME,
            heartbeat_status="healthy",
            natural_sample_count=1,
            fill_count=0,
            funding_observation_count=0,
            funding_cashflow=0.0,
            reconciliation_status="reconciled",
            outage_count=0,
            authorized_runtime_observed=True,
            private_endpoint_called=True,
        )


def test_private_readonly_v2_cannot_be_relabelled_as_v1() -> None:
    receipt = build_hourly_observation_receipt(
        source_head=HEAD_A,
        strategy_version=STRATEGY_A,
        data_version=DATA_A,
        runtime_version=RUNTIME_A,
        observed_at_utc=BASE_TIME,
        heartbeat_status="healthy",
        natural_sample_count=1,
        fill_count=0,
        funding_observation_count=0,
        funding_cashflow=0.0,
        reconciliation_status="reconciled",
        outage_count=0,
        authorized_runtime_observed=True,
        evidence_class=PRIVATE_READONLY_EVIDENCE_CLASS,
        private_read_authorized=True,
        private_read_used=True,
        private_endpoint_called=True,
        network_used=True,
        secret_read=True,
        demo_runtime_started=True,
    )
    receipt["schema_version"] = RECEIPT_SCHEMA_VERSION
    receipt["receipt_sha256"] = stable_payload_hash(
        receipt, exclude={"receipt_sha256"}
    )

    blockers = validate_hourly_observation_receipt(
        receipt, expected_previous_receipt_sha256=None
    )
    assert "observation_receipt_schema_mismatch" in blockers
    assert "observation_receipt_safety_boundary_violation" in blockers


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "order_endpoint_called",
        "cancel_endpoint_called",
        "transfer_enabled",
        "withdraw_enabled",
        "live_enabled",
        "paper_enabled",
        "promotion_enabled",
    ],
)
def test_private_readonly_hour_rejects_any_write_or_readiness_capability(
    forbidden_key: str,
) -> None:
    receipt = build_hourly_observation_receipt(
        source_head=HEAD_A,
        strategy_version=STRATEGY_A,
        data_version=DATA_A,
        runtime_version=RUNTIME_A,
        observed_at_utc=BASE_TIME,
        heartbeat_status="healthy",
        natural_sample_count=1,
        fill_count=0,
        funding_observation_count=1,
        funding_cashflow=0.0,
        reconciliation_status="reconciled",
        outage_count=0,
        previous_receipt_sha256=None,
        authorized_runtime_observed=True,
        runtime_run_id="private-readonly-run",
        evidence_class=PRIVATE_READONLY_EVIDENCE_CLASS,
        private_read_authorized=True,
        private_read_used=True,
        private_endpoint_called=True,
        network_used=True,
        secret_read=True,
        demo_runtime_started=True,
    )
    receipt["safety"][forbidden_key] = True
    receipt["receipt_sha256"] = stable_payload_hash(
        receipt, exclude={"receipt_sha256"}
    )

    blockers = validate_hourly_observation_receipt(
        receipt, expected_previous_receipt_sha256=None
    )
    assert "observation_receipt_safety_boundary_violation" in blockers


def test_immutable_artifact_has_verified_hash_and_no_latest_pointer(
    tmp_path: Path,
) -> None:
    report = _report([])
    artifact = write_observation_window_artifact(
        report=report,
        output_root=tmp_path / "output",
        run_id="immutable-run",
    )
    report_path = Path(artifact["report_path"])
    manifest_path = Path(artifact["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(report_path.read_bytes()).hexdigest() == artifact[
        "report_sha256"
    ]
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == artifact[
        "manifest_sha256"
    ]
    assert manifest["latest_pointer_updated"] is False
    assert not (tmp_path / "output" / "latest_manifest.json").exists()


def _report(receipts: list[dict[str, object]]) -> dict[str, object]:
    return build_observation_window_report(
        receipts=receipts,
        current_head=HEAD_A,
        current_strategy_version=STRATEGY_A,
        current_data_version=DATA_A,
        current_runtime_version=RUNTIME_A,
        run_id="test-window",
        generated_at_utc=BASE_TIME + timedelta(hours=40),
    )


def _receipts(count: int) -> list[dict[str, object]]:
    return _receipts_for_offsets(list(range(count)))


def _receipts_for_offsets(offsets: list[int]) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    previous = None
    for offset in offsets:
        receipt = _receipt(hour_offset=offset, previous=previous)
        receipts.append(receipt)
        previous = str(receipt["receipt_sha256"])
    return receipts


def _receipt(
    *,
    hour_offset: int,
    previous: str | None,
    head: str = HEAD_A,
    strategy: str = STRATEGY_A,
    data: str = DATA_A,
    runtime: str = RUNTIME_A,
    heartbeat_status: str = "flat_healthy",
    reconciliation_status: str = "reconciled",
    outage_count: int = 0,
    gap_flags: tuple[str, ...] = (),
    fixture: bool = False,
    runtime_run_id: str = "runtime-run-unbound",
) -> dict[str, object]:
    return build_hourly_observation_receipt(
        source_head=head,
        strategy_version=strategy,
        data_version=data,
        runtime_version=runtime,
        observed_at_utc=BASE_TIME + timedelta(hours=hour_offset),
        heartbeat_status=heartbeat_status,
        natural_sample_count=0,
        fill_count=0,
        funding_observation_count=1,
        funding_cashflow=0.0,
        reconciliation_status=reconciliation_status,
        outage_count=outage_count,
        gap_flags=gap_flags,
        previous_receipt_sha256=previous,
        authorized_runtime_observed=True,
        fixture=fixture,
        runtime_run_id=runtime_run_id,
    )
