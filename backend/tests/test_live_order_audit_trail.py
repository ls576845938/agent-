"""Test LiveOrderAuditTrail and LiveOrderAuditRecord for G4.

Covers record creation, serialization, masking, append-only behavior,
filtering, and markdown output. ALL tests use tempfile for audit storage.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from quant_us.live.live_order_audit import LiveOrderAuditTrail, LiveOrderAuditRecord


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------


class TestLiveOrderAuditRecord:
    def test_creation_defaults(self) -> None:
        """Default fields are set correctly on creation."""
        r = LiveOrderAuditRecord(audit_id="rec_1")
        assert r.real_submit is False
        assert r.gate_decision == "BLOCKED"
        assert r.status == "DRAFT"
        assert r.created_at != ""

    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict returns expected keys and values."""
        r = LiveOrderAuditRecord(
            audit_id="rec_2",
            run_id="run_abc",
            symbol="SPY",
            side="buy",
            qty=10.0,
            notional=5000.0,
            real_submit=True,
            gate_decision="APPROVED_FOR_SUBMIT",
            status="SUBMITTED",
        )
        d = r.to_dict()
        assert d["symbol"] == "SPY"
        assert d["real_submit"] is True
        assert d["audit_id"] == "rec_2"
        assert d["run_id"] == "run_abc"

    def test_broker_order_id_is_masked_in_to_dict(self) -> None:
        """broker_order_id is masked via mask_secret in to_dict output."""
        r = LiveOrderAuditRecord(
            audit_id="rec_3",
            broker_order_id="super-secret-broker-id-99999",
        )
        d = r.to_dict()
        raw = r.broker_order_id
        masked = d["broker_order_id"]
        assert masked != raw
        assert "super-secret" not in masked
        assert "9999" in masked  # last 4 chars visible
        assert len(masked) > 0

    def test_to_summary_line_dry_run(self) -> None:
        """to_summary_line shows DRY for non-real submissions."""
        r = LiveOrderAuditRecord(
            audit_id="rec_4",
            symbol="QQQ",
            side="sell",
            qty=5.0,
            notional=2000.0,
            real_submit=False,
        )
        line = r.to_summary_line()
        assert "[DRY]" in line
        assert "QQQ" in line
        assert "sell" in line

    def test_to_summary_line_real_submit(self) -> None:
        """to_summary_line shows REAL for actual submissions."""
        r = LiveOrderAuditRecord(
            audit_id="rec_5",
            symbol="AAPL",
            side="buy",
            qty=1.0,
            notional=150.0,
            real_submit=True,
            gate_decision="APPROVED_FOR_SUBMIT",
            status="SUBMITTED",
        )
        line = r.to_summary_line()
        assert "[REAL]" in line
        assert "AAPL" in line


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestLiveOrderAuditTrailRecord:
    def test_record_appends_to_jsonl(self) -> None:
        """record() appends a JSONL line to the audit file."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            r = LiveOrderAuditRecord(audit_id="a1", symbol="SPY")
            trail.record(r)
            entries = trail.read_all()
            assert len(entries) == 1
            assert entries[0]["audit_id"] == "a1"

    def test_record_blocked_sets_fields(self) -> None:
        """record_blocked creates a record with real_submit=False and BLOCKED status."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_blocked(
                audit_id="b1",
                reasons=["missing_approval"],
                order_intent_id="int_1",
                symbol="SPY",
                notional=500.0,
            )
            entries = trail.read_all()
            assert len(entries) == 1
            e = entries[0]
            assert e["real_submit"] is False
            assert e["status"] == "BLOCKED"
            assert e["gate_decision"] == "BLOCKED"
            assert "missing_approval" in e["gate_block_reasons"]

    def test_record_dry_run_sets_fields(self) -> None:
        """record_dry_run creates a record with real_submit=False and DRY_RUN status."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_dry_run(
                audit_id="d1",
                run_id="run_1",
                symbol="SPY",
                side="buy",
                qty=1.0,
                notional=500.0,
            )
            entries = trail.read_all()
            assert len(entries) == 1
            e = entries[0]
            assert e["real_submit"] is False
            assert e["status"] == "DRY_RUN"
            assert e["gate_decision"] == "BLOCKED"

    def test_record_submitted_sets_fields(self) -> None:
        """record_submitted creates a record with real_submit=True and SUBMITTED status."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s1",
                run_id="run_1",
                symbol="AAPL",
                side="buy",
                qty=1.0,
                notional=150.0,
                broker_order_id="brk_abc123",
            )
            entries = trail.read_all()
            assert len(entries) == 1
            e = entries[0]
            assert e["real_submit"] is True
            assert e["status"] == "SUBMITTED"
            assert e["gate_decision"] == "APPROVED_FOR_SUBMIT"

    def test_record_submitted_masks_broker_order_id(self) -> None:
        """record_submitted stores masked broker_order_id in JSONL."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s2",
                broker_order_id="raw-broker-id-99999",
            )
            entries = trail.read_all()
            masked = entries[0]["broker_order_id"]
            assert "raw-broker-id" not in masked
            assert masked != "raw-broker-id-99999"


# ---------------------------------------------------------------------------
# Query methods
# ---------------------------------------------------------------------------


class TestLiveOrderAuditTrailQueries:
    def test_real_submit_count(self) -> None:
        """real_submit_count returns correct count of submitted orders."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_dry_run("d1")
            trail.record_blocked("b1", ["test"])
            trail.record_submitted("s1", broker_order_id="x")
            trail.record_submitted("s2", broker_order_id="y")
            assert trail.real_submit_count() == 2

    def test_read_by_run_filters_correctly(self) -> None:
        """read_by_run returns only entries matching the given run_id."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_dry_run("a1", run_id="run_X")
            trail.record_dry_run("a2", run_id="run_Y")
            trail.record_blocked("a3", ["test"])
            assert len(trail.read_by_run("run_X")) == 1
            assert len(trail.read_by_run("run_Y")) == 1
            assert len(trail.read_by_run("nonexistent")) == 0

    def test_audit_file_is_append_only(self) -> None:
        """Records accumulate; the file is never truncated."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_blocked("a1", ["t1"])
            count1 = len(trail.read_all())
            trail.record_blocked("a2", ["t2"])
            count2 = len(trail.read_all())
            assert count2 == count1 + 1

    def test_to_markdown_contains_expected_columns(self) -> None:
        """to_markdown output includes the key table columns."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_blocked("a1", ["dry_run"], symbol="SPY")
            trail.record_submitted("a2", symbol="AAPL", broker_order_id="brk_1")
            md = trail.to_markdown()
            assert "Live Order Audit Trail" in md
            assert "Real" in md
            assert "Gate" in md
            assert "SPY" in md
            assert "AAPL" in md


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class TestLiveOrderAuditTrailSecrets:
    def test_no_raw_secrets_in_audit_file(self) -> None:
        """The audit JSONL file never contains raw broker_order_id values."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s1",
                broker_order_id="super-secret-key-abc123",
            )
            # Read raw file content
            raw_content = trail.audit_path.read_text()
            assert "super-secret-key-abc123" not in raw_content
            assert "super-secret" not in raw_content

    def test_no_raw_secrets_in_read_output(self) -> None:
        """read_all entries do not contain raw secret values."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s2",
                broker_order_id="my_api_key_XYZ",
            )
            for e in trail.read_all():
                raw = str(e)
                assert "my_api_key_XYZ" not in raw
                # masked broker_order_id shows last 4 chars, do not check for partial match
                broker_id = e.get("broker_order_id", "")
                assert "my_api_key_XYZ" not in broker_id

    def test_no_raw_secrets_in_markdown(self) -> None:
        """to_markdown never contains raw secret patterns."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s3",
                broker_order_id="hidden-secret-999",
            )
            md = trail.to_markdown()
            assert "hidden-secret-999" not in md
            assert "hidden-secret" not in md
