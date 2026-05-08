"""Tests for Live Pilot Approval Gate (G3).

Tests HumanApprovalGate and LivePilotApprovalRequest.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from quant_us.live.live_pilot_approval import (
    HumanApprovalGate,
    LivePilotApprovalRequest,
    APPROVAL_EXPIRY_DAYS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store_path() -> str:
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def gate(store_path: str) -> HumanApprovalGate:
    return HumanApprovalGate(store_path=store_path)


@pytest.fixture
def draft_approval(gate: HumanApprovalGate) -> LivePilotApprovalRequest:
    return gate.create(
        approval_id="approval_001",
        strategy_id="etf_rotation",
        strategy_version="1.2.3",
        symbols=["SPY", "QQQ"],
        requested_by="test_user",
        proposed_capital=1000.0,
    )


# ---------------------------------------------------------------------------
# LivePilotApprovalRequest basics
# ---------------------------------------------------------------------------


class TestLivePilotApprovalRequest:
    def test_create_defaults(self) -> None:
        req = LivePilotApprovalRequest(approval_id="test_001")
        assert req.approval_id == "test_001"
        assert req.status == "DRAFT"
        assert req.requested_at != ""
        assert req.proposed_capital == 1000.0
        assert req.max_order_notional == 100.0
        assert req.max_daily_loss == 50.0
        assert req.max_gross_exposure == 0.10

    def test_initial_status_draft(self) -> None:
        req = LivePilotApprovalRequest(approval_id="test_001")
        assert req.status == "DRAFT"
        assert not req.is_approved()

    def test_approved_status(self) -> None:
        req = LivePilotApprovalRequest(approval_id="test_001", status="APPROVED")
        assert req.is_approved()

    def test_rejected_status(self) -> None:
        req = LivePilotApprovalRequest(approval_id="test_001", status="REJECTED")
        assert not req.is_approved()

    def test_is_expired_no_expiry(self) -> None:
        req = LivePilotApprovalRequest(approval_id="test_001", status="APPROVED")
        assert not req.is_expired()

    def test_is_expired_future(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        req = LivePilotApprovalRequest(
            approval_id="test_001", status="APPROVED", expires_at=future
        )
        assert not req.is_expired()

    def test_is_expired_past(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req = LivePilotApprovalRequest(
            approval_id="test_001", status="APPROVED", expires_at=past
        )
        assert req.is_expired()

    def test_is_valid_approved_not_expired(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        req = LivePilotApprovalRequest(
            approval_id="test_001", status="APPROVED", expires_at=future
        )
        assert req.is_valid()

    def test_is_valid_not_approved(self) -> None:
        req = LivePilotApprovalRequest(approval_id="test_001", status="DRAFT")
        assert not req.is_valid()

    def test_is_valid_approved_but_expired(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        req = LivePilotApprovalRequest(
            approval_id="test_001", status="APPROVED", expires_at=past
        )
        assert not req.is_valid()

    def test_to_dict_roundtrip(self) -> None:
        req = LivePilotApprovalRequest(
            approval_id="test_001",
            run_id="run_abc",
            strategy_id="etf_rotation",
            strategy_version="1.2.3",
            symbols=["SPY", "QQQ"],
            requested_by="alice",
            proposed_capital=2000.0,
            status="APPROVED",
            approver="bob",
        )
        d = req.to_dict()
        assert d["approval_id"] == "test_001"
        assert d["strategy_id"] == "etf_rotation"
        assert d["status"] == "APPROVED"
        assert d["approver"] == "bob"

    def test_from_dict_roundtrip(self) -> None:
        original = LivePilotApprovalRequest(
            approval_id="test_002",
            run_id="run_xyz",
            strategy_id="momentum",
            strategy_version="2.0.0",
            symbols=["AAPL", "MSFT"],
            requested_by="carol",
            proposed_capital=5000.0,
            status="REJECTED",
            rejection_reason="insufficient paper evidence",
        )
        data = original.to_dict()
        restored = LivePilotApprovalRequest.from_dict(data)
        assert restored.approval_id == original.approval_id
        assert restored.strategy_version == original.strategy_version
        assert restored.symbols == original.symbols
        assert restored.status == original.status
        assert restored.rejection_reason == original.rejection_reason

    def test_from_dict_empty(self) -> None:
        restored = LivePilotApprovalRequest.from_dict({})
        assert restored.approval_id == ""
        assert restored.status == "DRAFT"

    def test_is_expired_invalid_format(self) -> None:
        req = LivePilotApprovalRequest(
            approval_id="test_001", status="APPROVED", expires_at="not-a-date"
        )
        assert req.is_expired()

    def test_is_expired_empty_string(self) -> None:
        req = LivePilotApprovalRequest(
            approval_id="test_001", status="APPROVED", expires_at=""
        )
        assert not req.is_expired()


# ---------------------------------------------------------------------------
# HumanApprovalGate.check
# ---------------------------------------------------------------------------


class TestHumanApprovalGateCheck:
    def test_no_approval_id_blocked(self, gate: HumanApprovalGate) -> None:
        result = gate.check(approval_id="")
        assert not result.passed
        assert "No approval_id" in result.reason
        assert result.checks == {"approval_id_provided": False}

    def test_nonexistent_approval_blocked(self, gate: HumanApprovalGate) -> None:
        result = gate.check(approval_id="does_not_exist")
        assert not result.passed
        assert "not found" in result.reason
        assert result.checks == {"approval_exists": False}

    def test_draft_status_blocked(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        result = gate.check(approval_id=draft_approval.approval_id)
        assert not result.passed
        assert "DRAFT" in result.reason
        assert not result.checks.get("status_approved", True)

    def test_approved_but_expired_blocked(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        # Manually expire the approval by setting expires_at in the past
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        approval = draft_approval
        approval.status = "APPROVED"
        approval.approver = "admin"
        approval.approved_at = past
        approval.expires_at = past
        gate._save_approval(approval)

        result = gate.check(approval_id=approval.approval_id)
        assert not result.passed
        assert "expired" in result.reason

    def test_approved_valid_passes(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        result = gate.check(
            approval_id=draft_approval.approval_id,
            strategy_id="etf_rotation",
            strategy_version="1.2.3",
            symbols=["SPY", "QQQ"],
        )
        assert result.passed
        assert "valid and authorized" in result.reason

    def test_strategy_version_mismatch(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        result = gate.check(
            approval_id=draft_approval.approval_id,
            strategy_id="etf_rotation",
            strategy_version="9.9.9",
            symbols=["SPY", "QQQ"],
        )
        assert not result.passed
        assert "version mismatch" in result.reason

    def test_symbol_not_in_approved_list(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        result = gate.check(
            approval_id=draft_approval.approval_id,
            strategy_id="etf_rotation",
            strategy_version="1.2.3",
            symbols=["SPY", "BTC"],
        )
        assert not result.passed
        assert "not in approval" in result.reason

    def test_empty_symbols_skips_symbol_check(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        result = gate.check(
            approval_id=draft_approval.approval_id,
            strategy_id="etf_rotation",
            strategy_version="1.2.3",
        )
        assert result.passed

    def test_empty_strategy_version_skips_version_check(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        result = gate.check(
            approval_id=draft_approval.approval_id,
            symbols=["SPY"],
        )
        assert result.passed

    def test_case_insensitive_symbol_match(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        result = gate.check(
            approval_id=draft_approval.approval_id,
            symbols=["spy", "qqq"],
        )
        assert result.passed


# ---------------------------------------------------------------------------
# HumanApprovalGate CRUD
# ---------------------------------------------------------------------------


class TestHumanApprovalGateCrud:
    def test_approve_changes_status(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        approved = gate.approve(
            approval_id=draft_approval.approval_id, approver="admin"
        )
        assert approved.status == "APPROVED"
        assert approved.approver == "admin"
        assert approved.approved_at != ""
        assert approved.expires_at != ""

    def test_approve_sets_expiry(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        approved = gate.approve(
            approval_id=draft_approval.approval_id, approver="admin"
        )
        expiry = datetime.fromisoformat(approved.expires_at)
        expected = datetime.now(timezone.utc) + timedelta(days=APPROVAL_EXPIRY_DAYS)
        # Within 10s tolerance
        assert abs((expiry - expected).total_seconds()) < 10

    def test_approve_nonexistent_raises(
        self, gate: HumanApprovalGate
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            gate.approve(approval_id="nonexistent", approver="admin")

    def test_approve_already_approved_raises(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        with pytest.raises(ValueError, match="Cannot approve"):
            gate.approve(approval_id=draft_approval.approval_id, approver="admin2")

    def test_reject_changes_status(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        rejected = gate.reject(
            approval_id=draft_approval.approval_id, reason="not ready"
        )
        assert rejected.status == "REJECTED"
        assert rejected.rejection_reason == "not ready"

    def test_reject_nonexistent_raises(
        self, gate: HumanApprovalGate
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            gate.reject(approval_id="nonexistent", reason="bad")

    def test_list_approvals_empty(self, gate: HumanApprovalGate) -> None:
        approvals = gate.list_approvals()
        assert approvals == []

    def test_list_approvals_returns_all(
        self, gate: HumanApprovalGate
    ) -> None:
        a1 = gate.create(approval_id="a1")
        a2 = gate.create(approval_id="a2")
        a3 = gate.create(approval_id="a3")
        approvals = gate.list_approvals()
        assert len(approvals) == 3
        ids = {a.approval_id for a in approvals}
        assert ids == {"a1", "a2", "a3"}

    def test_list_approvals_returns_sorted(
        self, gate: HumanApprovalGate
    ) -> None:
        gate.create(approval_id="b")
        gate.create(approval_id="a")
        gate.create(approval_id="c")
        approvals = gate.list_approvals()
        assert [a.approval_id for a in approvals] == ["a", "b", "c"]

    def test_inspect_returns_approval(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        found = gate.inspect(approval_id=draft_approval.approval_id)
        assert found is not None
        assert found.approval_id == draft_approval.approval_id

    def test_inspect_nonexistent_returns_none(
        self, gate: HumanApprovalGate
    ) -> None:
        assert gate.inspect(approval_id="ghost") is None


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_audit_written_on_create(
        self, gate: HumanApprovalGate, store_path: str
    ) -> None:
        gate.create(approval_id="audit_test")
        audit_path = gate.store_path / "approval_audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["event"] == "approval_created"

    def test_audit_written_on_approve(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        audit_path = gate.store_path / "approval_audit.jsonl"
        lines = audit_path.read_text().strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "approval_approved" in events

    def test_audit_written_on_reject(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.reject(approval_id=draft_approval.approval_id, reason="bad")
        audit_path = gate.store_path / "approval_audit.jsonl"
        lines = audit_path.read_text().strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "approval_rejected" in events

    def test_audit_written_on_gate_pass(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        gate.approve(approval_id=draft_approval.approval_id, approver="admin")
        gate.check(approval_id=draft_approval.approval_id)
        audit_path = gate.store_path / "approval_audit.jsonl"
        lines = audit_path.read_text().strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "approval_gate_passed" in events

    def test_audit_not_written_on_failed_gate(
        self, gate: HumanApprovalGate
    ) -> None:
        gate.check(approval_id="")
        audit_path = gate.store_path / "approval_audit.jsonl"
        if audit_path.exists():
            content = audit_path.read_text().strip()
            if content:
                events = [json.loads(l)["event"] for l in content.split("\n")]
                assert "approval_gate_passed" not in events


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_approval_saved_to_disk(
        self, gate: HumanApprovalGate, draft_approval: LivePilotApprovalRequest
    ) -> None:
        path = gate.store_path / f"{draft_approval.approval_id}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["approval_id"] == draft_approval.approval_id

    def test_gate_reloads_from_disk(
        self, store_path: str, draft_approval: LivePilotApprovalRequest
    ) -> None:
        # Create a new gate pointing to the same store path
        gate2 = HumanApprovalGate(store_path=store_path)
        found = gate2.inspect(approval_id=draft_approval.approval_id)
        assert found is not None
        assert found.approval_id == draft_approval.approval_id
