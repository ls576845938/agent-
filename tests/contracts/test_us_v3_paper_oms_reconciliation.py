from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import jsonschema
import pytest

from quant_us.live.paper_ledger_uow import PaperLedgerCommitError
from quant_us.live.paper_oms_reconciliation import (
    FilePaperOmsRepository,
    PaperOmsReconciliationService,
    PaperOmsRecoveryError,
    REQUIRED_LIFECYCLE_STATES,
    build_fixture_evidence,
    credential_review_metadata,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64
COMMIT = "b" * 40


def test_order_fill_position_cash_and_state_commit_in_one_uow(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "ledger")
    service.begin_order(
        order_id="order-1",
        client_order_id="client-1",
        symbol="QQQ",
        side="buy",
        quantity=10.0,
        risk_approved=True,
        market_open=True,
    )
    service.process_callback(_callback("accept-1", "order-1", "accepted"))
    partial = service.process_callback(
        _callback(
            "partial-1",
            "order-1",
            "partial",
            fill_id="fill-1",
            quantity=4.0,
            price=100.0,
        )
    )

    assert partial.lifecycle_state == "partial"
    assert partial.uow_operation_count == 6
    state = service.snapshot()
    assert state["cash"] == pytest.approx(99_600.0)
    assert state["positions"] == {"QQQ": 4.0}
    assert state["ledger_counts"] == {
        "orders": 4,
        "fills": 1,
        "positions": 1,
        "cash": 1,
        "audit": 3,
    }


def test_duplicate_callback_and_fill_do_not_duplicate_accounting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ledger"
    service = _service(root)
    service.begin_order(
        order_id="order-1",
        client_order_id="client-1",
        symbol="QQQ",
        side="buy",
        quantity=4.0,
        risk_approved=True,
        market_open=True,
    )
    service.process_callback(_callback("accept", "order-1", "accepted"))
    callback = _callback(
        "partial-event",
        "order-1",
        "partial",
        fill_id="fill-1",
        quantity=2.0,
        price=100.0,
    )
    service.process_callback(callback)
    before = service.snapshot()

    restarted = _service(root)
    duplicate_event = restarted.process_callback(callback)
    duplicate_fill = restarted.process_callback(
        _callback(
            "second-event-same-fill",
            "order-1",
            "partial",
            fill_id="fill-1",
            quantity=2.0,
            price=100.0,
        )
    )

    assert duplicate_event.status == "duplicate_callback_ignored"
    assert duplicate_event.ledger_mutated is False
    assert duplicate_fill.status == "duplicate_fill_ignored"
    after = restarted.snapshot()
    assert after["cash"] == before["cash"]
    assert after["positions"] == before["positions"]
    assert after["ledger_counts"]["fills"] == before["ledger_counts"]["fills"]


def test_out_of_order_fill_and_broker_outage_fail_closed_without_fill(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "ledger")
    service.begin_order(
        order_id="out-of-order",
        client_order_id="client-out-of-order",
        symbol="QQQ",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=True,
    )
    result = service.process_callback(
        _callback(
            "fill-too-early",
            "out-of-order",
            "filled",
            fill_id="fill-forbidden",
            quantity=1.0,
            price=100.0,
        )
    )
    assert result.status == "callback_blocked_fail_closed"
    assert result.lifecycle_state == "unknown"
    assert result.halt_new_orders is True
    assert service.snapshot()["ledger_counts"]["fills"] == 0

    service.begin_order(
        order_id="outage",
        client_order_id="client-outage",
        symbol="SPY",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=True,
    )
    outage = service.process_callback(
        _callback("outage-event", "outage", "unknown")
    )
    assert outage.lifecycle_state == "unknown"
    assert outage.halt_new_orders is True
    assert outage.ledger_mutated is True


def test_cancel_pending_market_closed_reject_and_reconciliation_break(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "ledger")
    service.begin_order(
        order_id="cancel-order",
        client_order_id="client-cancel",
        symbol="GLD",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=True,
    )
    service.process_callback(
        _callback("accept-cancel", "cancel-order", "accepted")
    )
    pending = service.process_callback(
        _callback("cancel-pending", "cancel-order", "cancel_pending")
    )
    assert pending.halt_new_orders is True
    confirmed = service.process_callback(
        _callback("cancel-confirmed", "cancel-order", "cancel")
    )
    assert confirmed.lifecycle_state == "cancel"

    closed = service.begin_order(
        order_id="closed-order",
        client_order_id="client-closed",
        symbol="DIA",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=False,
    )
    assert closed.lifecycle_state == "rejected"
    state = service.snapshot()
    orders = {"cancel-order": "cancel", "closed-order": "rejected"}
    broken = service.reconcile(
        {
            "snapshot_id": "broken",
            "cash": state["cash"] + 1.0,
            "positions": state["positions"],
            "orders": orders,
        }
    )
    assert broken["status"] == "breaks_detected_fail_closed"
    assert broken["halt_new_orders"] is True
    blocked_order = service.begin_order(
        order_id="must-not-exist",
        client_order_id="client-must-not-exist",
        symbol="SPY",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=True,
    )
    assert blocked_order.status == "blocked_fail_closed"
    assert "must-not-exist" not in service.snapshot()["orders"]

    clean = service.reconcile(
        {
            "snapshot_id": "clean",
            "cash": state["cash"],
            "positions": state["positions"],
            "orders": orders,
        }
    )
    assert clean["status"] == "reconciled_clean"
    assert clean["halt_new_orders"] is False
    assert all(
        order["status"] == "reconciled"
        for order in service.snapshot()["orders"].values()
    )


def test_atomic_uow_rolls_back_every_ledger_on_interruption(
    tmp_path: Path,
) -> None:
    replace_count = 0

    def fail_second_replace(source: object, destination: object) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("fixture interruption")
        os.replace(source, destination)

    root = tmp_path / "ledger"
    service = PaperOmsReconciliationService(
        FilePaperOmsRepository(
            root,
            initial_cash=100_000.0,
            apply_replace=fail_second_replace,
        ),
        clock=lambda: "2026-07-24T13:00:00Z",
    )
    with pytest.raises(PaperLedgerCommitError) as exc_info:
        service.begin_order(
            order_id="atomic-order",
            client_order_id="atomic-client",
            symbol="QQQ",
            side="buy",
            quantity=1.0,
            risk_approved=True,
            market_open=True,
        )
    assert exc_info.value.rollback_succeeded is True
    for relative in (
        "orders.jsonl",
        "fills.jsonl",
        "positions.jsonl",
        "cash_ledger.jsonl",
        "audit.jsonl",
        "oms_state.json",
    ):
        assert not (root / relative).exists()


def test_truncated_log_and_tampered_state_block_restart(
    tmp_path: Path,
) -> None:
    truncated = tmp_path / "truncated"
    truncated.mkdir()
    (truncated / "orders.jsonl").write_bytes(b'{"order_id":"truncated"')
    with pytest.raises(PaperOmsRecoveryError) as exc_info:
        FilePaperOmsRepository(truncated, initial_cash=100_000.0)
    assert any(
        blocker.startswith("jsonl_unreadable:orders.jsonl")
        for blocker in exc_info.value.blockers
    )

    tampered = tmp_path / "tampered"
    service = _service(tampered)
    service.begin_order(
        order_id="order-1",
        client_order_id="client-1",
        symbol="QQQ",
        side="buy",
        quantity=1.0,
        risk_approved=True,
        market_open=True,
    )
    state_path = tampered / "oms_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["cash"] += 10.0
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(PaperOmsRecoveryError) as tampered_error:
        FilePaperOmsRepository(tampered, initial_cash=100_000.0)
    assert "oms_state_hash_mismatch" in tampered_error.value.blockers


def test_credential_review_is_metadata_only_and_rejects_secret_fields() -> None:
    safe = credential_review_metadata(
        {
            "reviewer": "reviewer",
            "reviewed_at": "2026-07-24T13:00:00Z",
            "broker": "fixture-broker",
            "account_hash": "sha256:" + HASH,
            "approval_ticket": "NO-PAPER-START",
            "permission_conclusion": "paper_order_permission_not_authorized",
        }
    )
    assert safe["status"] == "quality_checked"
    assert safe["secret_read"] is False
    assert safe["can_unlock_paper"] is False

    unsafe = credential_review_metadata(
        {
            "reviewer": "reviewer",
            "reviewed_at": "2026-07-24T13:00:00Z",
            "broker": "fixture-broker",
            "account_hash": "sha256:" + HASH,
            "approval_ticket": "NO-PAPER-START",
            "permission_conclusion": "blocked",
            "api_key": "forbidden",
        }
    )
    assert unsafe["status"] == "blocked"
    assert any(
        blocker.startswith("credential_review_secret_like_fields")
        for blocker in unsafe["blockers"]
    )


def test_fixture_evidence_covers_full_lifecycle_and_never_unlocks_paper(
    tmp_path: Path,
) -> None:
    report = build_fixture_evidence(
        work_root=tmp_path,
        generated_at="2026-07-24T13:00:00Z",
        code_commit=COMMIT,
        code_tree_hash="c" * 40,
        config_sha256=HASH,
        initial_cash=100_000.0,
        commission_bps=1.0,
    )
    schema = json.loads(
        (
            ROOT / "schemas/us_v3_paper_oms_reconciliation_report.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        report,
        schema,
        format_checker=jsonschema.FormatChecker(),
    )

    assert report["lifecycle"]["complete"] is True
    assert set(REQUIRED_LIFECYCLE_STATES).issubset(
        report["lifecycle"]["observed_states"]
    )
    assert all(report["scenario_results"].values())
    assert report["evidence_classification"]["real_paper_evidence"] is False
    assert report["guardrails"]["paper_runner_started"] is False
    assert report["guardrails"]["paper_queue_write_allowed"] is False
    assert report["guardrails"]["broker_call_used"] is False


def test_artifact_identity_ignores_generation_time_only(tmp_path: Path) -> None:
    first = build_fixture_evidence(
        work_root=tmp_path / "first",
        generated_at="2026-07-24T13:00:00Z",
        code_commit=COMMIT,
        code_tree_hash="c" * 40,
        config_sha256=HASH,
        initial_cash=100_000.0,
        commission_bps=1.0,
    )
    second = build_fixture_evidence(
        work_root=tmp_path / "second",
        generated_at="2026-07-25T13:00:00Z",
        code_commit=COMMIT,
        code_tree_hash="c" * 40,
        config_sha256=HASH,
        initial_cash=100_000.0,
        commission_bps=1.0,
    )

    assert first["artifact_identity_sha256"] == second["artifact_identity_sha256"]
    changed = deepcopy(second)
    changed["code_binding"]["code_commit"] = "d" * 40
    assert first["code_binding"] != changed["code_binding"]


def _service(root: Path) -> PaperOmsReconciliationService:
    counter = iter(
        f"2026-07-24T13:{minute:02d}:00Z" for minute in range(60)
    )
    return PaperOmsReconciliationService(
        FilePaperOmsRepository(root, initial_cash=100_000.0),
        clock=lambda: next(counter),
    )


def _callback(
    event_id: str,
    order_id: str,
    status: str,
    *,
    fill_id: str = "",
    quantity: float = 0.0,
    price: float = 0.0,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "order_id": order_id,
        "status": status,
        "fill_id": fill_id,
        "quantity": quantity,
        "price": price,
        "commission_bps": 0.0,
    }
