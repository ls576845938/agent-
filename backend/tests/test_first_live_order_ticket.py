"""Tests for FirstLiveOrderTicket and FinalHumanConfirmationGate."""

from __future__ import annotations

import tempfile, json
from pathlib import Path

import pytest

from quant_us.live.first_live_order_ticket import (
    FirstLiveOrderTicket,
    FirstLiveOrderTicketBuilder,
    FinalHumanConfirmationGate,
)


class TestFirstLiveOrderTicket:
    def test_creation(self) -> None:
        ticket = FirstLiveOrderTicket(ticket_id="T1", symbol="SPY", side="buy", quantity=1.0, limit_price=500.0, estimated_notional=500.0)
        assert ticket.status == "DRAFT"
        assert not ticket.is_executable

    def test_is_expired_future(self) -> None:
        ticket = FirstLiveOrderTicket(ticket_id="T1")
        assert not ticket.is_expired

    def test_to_dict(self) -> None:
        ticket = FirstLiveOrderTicket(ticket_id="T1", symbol="SPY", side="buy")
        d = ticket.to_dict()
        assert d["ticket_id"] == "T1"
        assert d["symbol"] == "SPY"

    def test_to_markdown(self) -> None:
        ticket = FirstLiveOrderTicket(ticket_id="T1", symbol="SPY")
        md = ticket.to_markdown()
        assert "T1" in md
        assert "Manual Confirmation Checklist" in md


class TestTicketBuilder:
    def test_build_creates_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = FirstLiveOrderTicketBuilder(data_root=tmp)
            ticket = builder.build(approval_id="A1", envelope_id="E1", symbol="SPY")
            assert ticket.ticket_id.startswith("ticket_")
            assert ticket.approval_id == "A1"

    def test_save_ticket_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = FirstLiveOrderTicketBuilder(data_root=tmp)
            ticket = builder.build(approval_id="A1", envelope_id="E1")
            path = builder.save_ticket(ticket, output_path=f"{tmp}/ticket.md")
            assert Path(path).exists()
            assert Path(path.replace(".md", ".json")).exists()


class TestFinalHumanConfirmationGate:
    def test_all_missing_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = FinalHumanConfirmationGate(audit_dir=f"{tmp}/audit")
            result = gate.check()
            assert result.passed is False

    def test_no_real_money_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = FinalHumanConfirmationGate(audit_dir=f"{tmp}/audit")
            result = gate.check(ticket_id="T1", confirm_live=True, execute_one_shot=True)
            assert result.passed is False

    def test_no_confirm_live_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = FinalHumanConfirmationGate(audit_dir=f"{tmp}/audit")
            result = gate.check(ticket_id="T1", i_understand_real_money=True, execute_one_shot=True)
            assert result.passed is False

    def test_confirm_ticket_mismatch_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = FinalHumanConfirmationGate(audit_dir=f"{tmp}/audit")
            result = gate.check(ticket_id="T1", confirm_ticket="T2")
            assert result.passed is False
