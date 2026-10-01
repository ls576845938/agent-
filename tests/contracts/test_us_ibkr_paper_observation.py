from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from scripts.build_us_ibkr_paper_observation import run as run_cli
from quant_us.live.ibkr_paper_observation import (
    CONFIRMATION_BLOCKER,
    WINDOW_BLOCKER,
    IbkrPaperObservationError,
    append_daily_observation_receipt,
    build_daily_observation_receipt,
    build_input_envelope,
    build_observation_report,
    load_observation_ledger,
    write_observation_report_artifact,
)


HEAD_A = "d3f1e3f7f770bfdf35336257cf1eaecc18f3d6b6"
HEAD_B = "b" * 40
BASE_TIME = datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc)
HASHES = {
    "strategy_hash": "1" * 64,
    "data_identity": "2" * 64,
    "account_hash": "3" * 64,
    "parameters_hash": "4" * 64,
    "risk_hash": "5" * 64,
    "oms_hash": "6" * 64,
    "ledger_contract_hash": "7" * 64,
}


def test_thirty_natural_days_complete_operational_stability_only() -> None:
    receipts = _receipts(30)
    report = _report(receipts)

    assert report["status"] == (
        "complete_operational_paper_stability_observation"
    )
    assert report["current_run"]["consecutive_eligible_natural_days"] == 30
    assert report["current_run"]["window_complete"] is True
    assert WINDOW_BLOCKER not in report["blockers"]
    assert CONFIRMATION_BLOCKER in report["blockers"]
    assert report["readiness"] == {
        "operational_paper_stability_observed": True,
        "strategy_alpha_promotion_ready": False,
        "independent_252_trading_day_confirmation_complete": False,
        "promotion_evidence_ready": False,
        "live_ready": False,
    }
    assert all(value is False for value in report["safety_flags"].values())
    assert set(receipts[-1]["counts"]) == {
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
    }
    for field in (
        "observation_run_id",
        "session_id",
        "data_freshness",
        "position_drift",
        "cash_drift",
        "commission",
        "slippage",
        "kill_switch_state",
        "safety_flags",
    ):
        assert field in receipts[-1]


def test_report_matches_json_schema() -> None:
    schema = json.loads(
        Path("schemas/us_ibkr_paper_observation_report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(_report(_receipts(2)), schema)


def test_empty_heartbeat_is_recorded_but_never_counts() -> None:
    receipt = _receipt(
        day_offset=0,
        previous=None,
        runtime_overrides={
            "signal_count": 0,
            "target_count": 0,
            "intent_count": 0,
            "observed_event_count": 0,
        },
        broker_overrides={"observed_event_count": 0},
        reconciliation_overrides={"check_count": 0},
    )
    report = _report([receipt])

    assert receipt["counts_toward_30_day_window"] is False
    assert "paper_observation_empty_heartbeat_not_counted" in receipt["blockers"]
    assert report["current_run"]["consecutive_eligible_natural_days"] == 0
    assert WINDOW_BLOCKER in report["blockers"]


def test_stale_data_is_owned_by_data_steward_and_resets_window() -> None:
    receipts = _receipts(2)
    stale = _receipt(
        day_offset=2,
        previous=str(receipts[-1]["receipt_sha256"]),
        data_overrides={"freshness_status": "stale", "stale": True},
    )
    recovered = _receipt(
        day_offset=3,
        previous=str(stale["receipt_sha256"]),
    )
    report = _report([*receipts, stale, recovered])

    assert (
        "owner:data_steward paper_observation_data_stale" in stale["blockers"]
    )
    assert report["current_run"]["consecutive_eligible_natural_days"] == 1
    assert report["segments"][-1]["reset_reason"] == "previous_day_ineligible"


def test_missing_natural_day_restarts_continuity_without_backfill() -> None:
    first = _receipt(day_offset=0, previous=None)
    third = _receipt(
        day_offset=2,
        previous=str(first["receipt_sha256"]),
    )
    report = _report([first, third])

    assert len(report["segments"]) == 2
    assert report["segments"][-1]["reset_reason"] == "natural_day_gap"
    assert report["current_run"]["consecutive_eligible_natural_days"] == 1


@pytest.mark.parametrize(
    "field",
    [
        "code_head",
        "strategy_hash",
        "data_identity",
        "account_hash",
        "parameters_hash",
        "risk_hash",
        "oms_hash",
        "ledger_contract_hash",
    ],
)
def test_identity_drift_restarts_continuity(field: str) -> None:
    receipts = _receipts(2)
    changed = _receipt_with_identity_change(
        field=field,
        day_offset=2,
        previous=str(receipts[-1]["receipt_sha256"]),
    )
    report = build_observation_report(
        receipts=[*receipts, changed],
        current_head=str(changed["identity"]["code_head"]),
        current_observation_run_id="run-current",
        generated_at_utc=BASE_TIME + timedelta(days=4),
    )

    assert len(report["segments"]) == 2
    assert report["segments"][-1]["reset_reason"] == "identity_or_run_drift"
    assert report["current_run"]["consecutive_eligible_natural_days"] == 1
    assert report["historical_accumulation"]["metrics"]["receipt_days"] == 2


def test_current_run_and_historical_accumulation_are_strictly_separate() -> None:
    receipts = _receipts(2, run_id="run-history")
    previous = str(receipts[-1]["receipt_sha256"])
    for offset in (2, 3):
        receipt = _receipt(
            day_offset=offset,
            previous=previous,
            run_id="run-current",
        )
        receipts.append(receipt)
        previous = str(receipt["receipt_sha256"])
    report = _report(receipts)

    assert report["current_run"]["metrics"]["receipt_days"] == 2
    assert report["historical_accumulation"]["metrics"]["receipt_days"] == 2
    assert report["all_time_audit_only"]["metrics"]["receipt_days"] == 4
    assert report["historical_accumulation"]["excluded_from_current_run"] is True
    assert report["all_time_audit_only"][
        "never_used_for_current_run_window"
    ] is True


def test_append_is_idempotent_and_rejects_same_day_conflict(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "daily_receipts.jsonl"
    receipt = _receipt(day_offset=0, previous=None)

    assert append_daily_observation_receipt(
        ledger_path=ledger, receipt=receipt
    )["appended"] is True
    assert append_daily_observation_receipt(
        ledger_path=ledger, receipt=receipt
    )["duplicate"] is True

    conflict = _receipt(
        day_offset=0,
        previous=str(receipt["receipt_sha256"]),
        session_id="session-conflict",
    )
    with pytest.raises(
        IbkrPaperObservationError,
        match="paper_observation_natural_day_conflict",
    ):
        append_daily_observation_receipt(ledger_path=ledger, receipt=conflict)
    assert len(load_observation_ledger(ledger)) == 1


def test_historical_backfill_is_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "daily_receipts.jsonl"
    newer = _receipt(day_offset=2, previous=None)
    append_daily_observation_receipt(ledger_path=ledger, receipt=newer)
    older = _receipt(
        day_offset=1,
        previous=str(newer["receipt_sha256"]),
    )

    with pytest.raises(
        IbkrPaperObservationError,
        match="paper_observation_historical_backfill_forbidden",
    ):
        append_daily_observation_receipt(ledger_path=ledger, receipt=older)


def test_tampering_fails_closed() -> None:
    receipt = _receipt(day_offset=0, previous=None)
    receipt["counts"]["fills"] = 99
    report = _report([receipt])

    assert report["status"] == "blocked_fail_closed"
    assert "paper_observation_receipt_hash_mismatch" in report["blockers"]
    assert report["current_run"]["window_complete"] is False


def test_two_integrations_and_submit_authority_are_required_to_count() -> None:
    receipt = _receipt(
        day_offset=0,
        previous=None,
        runtime_overrides={
            "independent_integration_receipts": ["8" * 64],
            "paper_submit_authorized": False,
            "read_only": True,
            "no_submit": True,
        },
    )

    assert receipt["counts_toward_30_day_window"] is False
    assert (
        "paper_observation_two_independent_integration_receipts_required"
        in receipt["blockers"]
    )
    assert (
        "paper_observation_real_paper_runtime_or_submit_authority_missing"
        in receipt["blockers"]
    )


def test_cli_refuses_real_run_before_two_integrations_and_submit_authority(
    tmp_path: Path,
) -> None:
    inputs = _inputs(
        runtime_overrides={
            "independent_integration_receipts": ["8" * 64],
            "paper_submit_authorized": False,
            "read_only": True,
            "no_submit": True,
        }
    )
    paths: dict[str, Path] = {}
    for kind, payload in inputs.items():
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[kind] = path
    ledger = tmp_path / "ledger.jsonl"

    with pytest.raises(
        IbkrPaperObservationError,
        match="paper_observation_two_independent_integrations_required",
    ):
        run_cli(
            [
                "--strategy-identity",
                str(paths["strategy_identity"]),
                "--data-manifest",
                str(paths["data_manifest"]),
                "--runtime-receipt",
                str(paths["runtime_receipt"]),
                "--broker-receipt",
                str(paths["broker_receipt"]),
                "--reconciliation-report",
                str(paths["reconciliation_report"]),
                "--ledger",
                str(ledger),
                "--output-root",
                str(tmp_path / "artifacts"),
                "--observed-at-utc",
                BASE_TIME.isoformat(),
            ]
        )
    assert not ledger.exists()


def test_input_envelope_tamper_is_rejected() -> None:
    envelope = build_input_envelope(
        input_kind="strategy_identity",
        source_commit=HEAD_A,
        payload={
            "strategy_hash": HASHES["strategy_hash"],
            "parameters_hash": HASHES["parameters_hash"],
        },
    )
    envelope["payload"]["strategy_hash"] = "f" * 64
    inputs = _inputs()
    inputs["strategy_identity"] = envelope

    with pytest.raises(
        IbkrPaperObservationError, match="strategy_identity:payload_hash_mismatch"
    ):
        build_daily_observation_receipt(
            **inputs,
            observed_at_utc=BASE_TIME,
            previous_receipt_sha256=None,
        )


def test_immutable_report_artifact_has_hashes_and_no_latest_pointer(
    tmp_path: Path,
) -> None:
    report = _report(_receipts(1))
    artifact = write_observation_report_artifact(
        report=report,
        output_root=tmp_path / "observation",
    )
    report_path = Path(artifact["report_path"])
    manifest_path = Path(artifact["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert hashlib.sha256(report_path.read_bytes()).hexdigest() == artifact[
        "report_file_sha256"
    ]
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == artifact[
        "manifest_sha256"
    ]
    assert manifest["latest_pointer_updated"] is False
    assert manifest["promotion_evidence_ready"] is False
    assert not (tmp_path / "observation" / "latest.json").exists()


def _report(receipts: list[dict[str, object]]) -> dict[str, object]:
    return build_observation_report(
        receipts=receipts,
        current_head=HEAD_A,
        current_observation_run_id="run-current",
        generated_at_utc=BASE_TIME + timedelta(days=40),
    )


def _receipts(
    count: int,
    *,
    run_id: str = "run-current",
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    previous = None
    for offset in range(count):
        receipt = _receipt(
            day_offset=offset,
            previous=previous,
            run_id=run_id,
        )
        receipts.append(receipt)
        previous = str(receipt["receipt_sha256"])
    return receipts


def _receipt(
    *,
    day_offset: int,
    previous: str | None,
    run_id: str = "run-current",
    session_id: str | None = None,
    strategy_overrides: dict[str, object] | None = None,
    data_overrides: dict[str, object] | None = None,
    runtime_overrides: dict[str, object] | None = None,
    broker_overrides: dict[str, object] | None = None,
    reconciliation_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    inputs = _inputs(
        run_id=run_id,
        session_id=session_id or f"session-{day_offset}",
        strategy_overrides=strategy_overrides,
        data_overrides=data_overrides,
        runtime_overrides=runtime_overrides,
        broker_overrides=broker_overrides,
        reconciliation_overrides=reconciliation_overrides,
    )
    return build_daily_observation_receipt(
        **inputs,
        observed_at_utc=BASE_TIME + timedelta(days=day_offset),
        previous_receipt_sha256=previous,
    )


def _inputs(
    *,
    run_id: str = "run-current",
    session_id: str = "session-0",
    strategy_overrides: dict[str, object] | None = None,
    data_overrides: dict[str, object] | None = None,
    runtime_overrides: dict[str, object] | None = None,
    broker_overrides: dict[str, object] | None = None,
    reconciliation_overrides: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    strategy = {
        "strategy_hash": HASHES["strategy_hash"],
        "parameters_hash": HASHES["parameters_hash"],
    }
    data = {
        "data_identity": HASHES["data_identity"],
        "freshness_status": "fresh",
        "stale": False,
        "as_of": "2026-07-01T16:00:00Z",
    }
    runtime = {
        "code_head": HEAD_A,
        "observation_run_id": run_id,
        "session_id": session_id,
        "risk_hash": HASHES["risk_hash"],
        "oms_hash": HASHES["oms_hash"],
        "ledger_contract_hash": HASHES["ledger_contract_hash"],
        "runtime_mode": "ibkr_paper",
        "real_paper_session": True,
        "paper_submit_authorized": True,
        "independent_integration_receipts": ["8" * 64, "9" * 64],
        "fixture": False,
        "read_only": False,
        "no_submit": False,
        "signal_count": 1,
        "target_count": 1,
        "intent_count": 1,
        "observed_event_count": 3,
        "kill_switch_state": "armed",
    }
    broker = {
        "code_head": HEAD_A,
        "session_id": session_id,
        "account_hash": HASHES["account_hash"],
        "order_count": 1,
        "fill_count": 1,
        "partial_fill_count": 0,
        "reject_count": 0,
        "cancel_count": 0,
        "reconnect_count": 0,
        "observed_event_count": 2,
        "commission": 1.25,
        "slippage": 0.01,
    }
    reconciliation = {
        "code_head": HEAD_A,
        "session_id": session_id,
        "account_hash": HASHES["account_hash"],
        "status": "reconciled",
        "check_count": 2,
        "unmatched_count": 0,
        "duplicate_count": 0,
        "position_drift": 0.0,
        "cash_drift": 0.0,
    }
    for payload, overrides in (
        (strategy, strategy_overrides),
        (data, data_overrides),
        (runtime, runtime_overrides),
        (broker, broker_overrides),
        (reconciliation, reconciliation_overrides),
    ):
        if overrides:
            payload.update(overrides)
    code_head = str(runtime["code_head"])
    broker["code_head"] = code_head
    reconciliation["code_head"] = code_head
    broker["session_id"] = str(runtime["session_id"])
    reconciliation["session_id"] = str(runtime["session_id"])
    reconciliation["account_hash"] = str(broker["account_hash"])
    return {
        "strategy_identity": build_input_envelope(
            input_kind="strategy_identity",
            source_commit=HEAD_A,
            payload=strategy,
        ),
        "data_manifest": build_input_envelope(
            input_kind="data_manifest",
            source_commit=HEAD_A,
            payload=data,
        ),
        "runtime_receipt": build_input_envelope(
            input_kind="runtime_receipt",
            source_commit=code_head,
            payload=runtime,
        ),
        "broker_receipt": build_input_envelope(
            input_kind="broker_receipt",
            source_commit=code_head,
            payload=broker,
        ),
        "reconciliation_report": build_input_envelope(
            input_kind="reconciliation_report",
            source_commit=code_head,
            payload=reconciliation,
        ),
    }


def _receipt_with_identity_change(
    *,
    field: str,
    day_offset: int,
    previous: str,
) -> dict[str, object]:
    value = HEAD_B if field == "code_head" else "a" * 64
    kwargs: dict[str, dict[str, object]] = {}
    if field in {"strategy_hash", "parameters_hash"}:
        kwargs["strategy_overrides"] = {field: value}
    elif field == "data_identity":
        kwargs["data_overrides"] = {field: value}
    elif field == "account_hash":
        kwargs["broker_overrides"] = {field: value}
    else:
        kwargs["runtime_overrides"] = {field: value}
    return _receipt(
        day_offset=day_offset,
        previous=previous,
        **kwargs,
    )
