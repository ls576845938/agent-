from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.research.btc_demo_manual_approval_observer import (
    MANUAL_APPROVAL_BLOCKER,
    ManualApprovalObserverError,
    append_manual_approval_fact,
    build_btc_demo_manual_approval_observer,
    build_manual_approval_fact,
    write_btc_demo_manual_approval_observer_evidence,
)


HEAD = "a" * 40
OTHER_HEAD = "b" * 40
NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


def test_missing_approval_remains_awaiting_and_cannot_be_inferred() -> None:
    report = _report(None)

    assert report["status"] == "awaiting_manual_approval"
    assert report["manual_approval_recorded"] is False
    assert MANUAL_APPROVAL_BLOCKER in report["blockers"]
    assert (
        report["observer_contract"][
            "approval_may_be_inferred_from_code_completion"
        ]
        is False
    )
    assert report["promotion_evidence_ready"] is False
    assert all(value is False for value in report["safety"].values())


def test_valid_reviewer_fact_is_recorded_but_does_not_unlock_runtime() -> None:
    fact = _fact()
    report = _report(fact)

    assert report["status"] == "recorded_review_only"
    assert report["manual_approval_recorded"] is True
    assert report["blockers"] == []
    assert report["approval_record"]["reviewer"] == "risk-reviewer-01"
    assert report["approval_record"]["approval_ticket"] == "APPROVAL-42"
    assert report["observer_contract"]["observer_can_approve"] is False
    assert report["observer_contract"]["observer_can_enable_runtime"] is False
    assert report["promotion_evidence_ready"] is False
    assert all(value is False for value in report["safety"].values())


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("reviewer", "", "manual_approval_reviewer_missing"),
        ("approval_ticket", "", "manual_approval_ticket_missing"),
        ("account_hash_sha256", "not-a-hash", "manual_approval_account_hash_invalid"),
        ("source_head", OTHER_HEAD, "manual_approval_source_head_mismatch"),
    ],
)
def test_required_approval_fact_fields_fail_closed(
    field: str,
    value: object,
    blocker: str,
) -> None:
    fact = _fact()
    fact[field] = value
    fact["fact_sha256"] = _rehash(fact)
    report = _report(fact)

    assert report["manual_approval_recorded"] is False
    assert blocker in report["blockers"]


def test_hash_tamper_and_stale_time_fail_closed() -> None:
    tampered = _fact()
    tampered["reviewer"] = "different-reviewer"
    tampered_report = _report(tampered)

    assert "manual_approval_fact_hash_mismatch" in tampered_report["blockers"]

    stale = _fact(approved_at=NOW - timedelta(days=8))
    stale_report = _report(stale)

    assert "manual_approval_fact_stale" in stale_report["blockers"]
    assert stale_report["manual_approval_recorded"] is False


def test_secret_screenshot_or_withdraw_permission_is_rejected() -> None:
    secret = _fact()
    secret["api_key"] = "must-not-be-stored"
    secret["fact_sha256"] = _rehash(secret)
    secret_report = _report(secret)

    assert (
        "manual_approval_forbidden_sensitive_field_present"
        in secret_report["blockers"]
    )
    assert "api_key" not in (secret_report["approval_record"] or {})

    withdraw = _fact()
    withdraw["permission_conclusion"]["withdraw_allowed"] = True
    withdraw["fact_sha256"] = _rehash(withdraw)
    withdraw_report = _report(withdraw)

    assert (
        "manual_approval_withdraw_must_remain_disabled"
        in withdraw_report["blockers"]
    )


def test_append_only_manual_fact_ledger_deduplicates_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "approved_facts.jsonl"
    fact = _fact()
    first = append_manual_approval_fact(
        ledger_path=ledger,
        approval_fact=fact,
        expected_source_head=HEAD,
        generated_at_utc=NOW,
    )
    duplicate = append_manual_approval_fact(
        ledger_path=ledger,
        approval_fact=fact,
        expected_source_head=HEAD,
        generated_at_utc=NOW,
    )

    assert first["appended"] is True
    assert duplicate["duplicate"] is True
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

    conflict = _fact(reviewer="risk-reviewer-02")
    with pytest.raises(
        ManualApprovalObserverError,
        match="manual_approval_ticket_fact_conflict",
    ):
        append_manual_approval_fact(
            ledger_path=ledger,
            approval_fact=conflict,
            expected_source_head=HEAD,
            generated_at_utc=NOW,
        )


def test_manual_artifact_is_immutable_and_has_no_latest_pointer(
    tmp_path: Path,
) -> None:
    report = _report(None)
    artifact = write_btc_demo_manual_approval_observer_evidence(
        report=report,
        output_root=tmp_path / "output",
        run_id="manual-immutable",
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


def _report(
    fact: dict[str, object] | None,
) -> dict[str, object]:
    return build_btc_demo_manual_approval_observer(
        approval_fact=fact,
        source_head=HEAD,
        run_id="manual-test",
        generated_at_utc=NOW,
    )


def _fact(
    *,
    reviewer: str = "risk-reviewer-01",
    approved_at: datetime = NOW - timedelta(minutes=5),
) -> dict[str, object]:
    return build_manual_approval_fact(
        reviewer=reviewer,
        approval_ticket="APPROVAL-42",
        approved_at_utc=approved_at,
        account_hash_sha256="c" * 64,
        permission_conclusion={
            "paper_allowed": False,
            "live_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "withdraw_allowed": False,
        },
        source_head=HEAD,
    )


def _rehash(fact: dict[str, object]) -> str:
    payload = {
        key: value
        for key, value in fact.items()
        if key != "fact_sha256"
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
