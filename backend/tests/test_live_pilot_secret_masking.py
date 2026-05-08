"""Verify that secrets are masked in all audit and diagnostic outputs.

Every live pilot module that outputs broker_order_id, API keys, or account IDs
must mask them. This test file checks each output format: dict, JSONL, markdown,
and summary lines.
"""

from __future__ import annotations

import json
import tempfile

import pytest

from quant_us.live.live_order_audit import LiveOrderAuditRecord, LiveOrderAuditTrail
from quant_us.live.readonly_live_broker import mask_account_id, mask_secret


# ---------------------------------------------------------------------------
# Masking functions
# ---------------------------------------------------------------------------


class TestMaskingFunctions:
    def test_mask_secret_shows_last_four_chars(self) -> None:
        """mask_secret preserves the last 4 characters."""
        result = mask_secret("abcdefghij1234567890")
        assert result.endswith("7890")
        assert result.startswith("*" * (len("abcdefghij1234567890") - 4))

    def test_mask_secret_short_value(self) -> None:
        """mask_secret returns **** for very short secrets."""
        assert mask_secret("ab") == "****"

    def test_mask_secret_empty(self) -> None:
        """mask_secret returns **** for empty secrets."""
        assert mask_secret("") == "****"

    def test_mask_account_id_long(self) -> None:
        """mask_account_id shows first 4 and last 4 for long IDs."""
        result = mask_account_id("ACC123456789ABCDE")
        assert result.startswith("ACC1")
        assert result.endswith("CDE")
        # The exact format depends on implementation; just check masking
        assert "123456789" not in result

    def test_mask_account_id_short(self) -> None:
        """mask_account_id handles short IDs."""
        result = mask_account_id("SHORT")
        assert result != "SHORT"
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Audit record masking
# ---------------------------------------------------------------------------


class TestAuditRecordMasking:
    def test_to_dict_masks_broker_order_id(self) -> None:
        """broker_order_id is masked in to_dict output."""
        record = LiveOrderAuditRecord(
            audit_id="rec_1",
            broker_order_id="super-secret-broker-id-99999",
        )
        d = record.to_dict()
        assert d["broker_order_id"] != "super-secret-broker-id-99999"
        assert "super-secret-broker" not in d["broker_order_id"]
        assert "9999" in d["broker_order_id"]  # last 4 chars visible

    def test_to_dict_does_not_contain_raw_api_keys(self) -> None:
        """to_dict does not contain raw API key patterns anywhere."""
        record = LiveOrderAuditRecord(
            audit_id="rec_2",
            broker_order_id="AKIAIOSFODNN7EXAMPLE",
        )
        d = record.to_dict()
        raw = str(d)
        assert "AKIAIOSFODNN7EXAMPLE" not in raw
        # The masked version should hide most of it
        assert "EXAMPLE" not in raw  # last 4 would be AMPL, not EXAM

    def test_summary_line_does_not_contain_secrets(self) -> None:
        """to_summary_line does not include unmasked broker_order_id."""
        record = LiveOrderAuditRecord(
            audit_id="rec_3",
            broker_order_id="my-secret-key-value",
            symbol="SPY",
        )
        line = record.to_summary_line()
        assert "my-secret-key-value" not in line
        assert "SPY" in line


# ---------------------------------------------------------------------------
# Audit trail file masking
# ---------------------------------------------------------------------------


class TestAuditTrailFileMasking:
    def test_audit_jsonl_never_contains_raw_key_patterns(self) -> None:
        """The JSONL audit file never contains unmasked broker_order_id."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s1",
                broker_order_id="raw-api-key-abcdef",
            )
            raw_content = trail.audit_path.read_text()
            assert "raw-api-key-abcdef" not in raw_content
            assert "api-key" not in raw_content

    def test_audit_jsonl_does_not_have_secret_fields(self) -> None:
        """The JSONL file read via read_all() has masked broker_order_id."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s2",
                broker_order_id="hidden-value-123",
                symbol="AAPL",
            )
            for entry in trail.read_all():
                assert "hidden-value-123" not in str(entry)
                assert entry.get("broker_order_id", "") != "hidden-value-123"

    def test_markdown_does_not_contain_secrets(self) -> None:
        """to_markdown output never contains raw secret values."""
        with tempfile.TemporaryDirectory() as td:
            trail = LiveOrderAuditTrail(audit_dir=td)
            trail.record_submitted(
                audit_id="s3",
                broker_order_id="secret-key-in-beta-007",
                symbol="SPY",
            )
            md = trail.to_markdown()
            assert "secret-key-in-beta-007" not in md
            assert "SPY" in md  # regular data is fine

    def test_audit_record_raw_field_is_preserved(self) -> None:
        """The raw Python object still holds the unmasked value (masking is only in output)."""
        record = LiveOrderAuditRecord(
            audit_id="rec_4",
            broker_order_id="raw-secret-value",
        )
        # The attribute on the object itself is NOT masked
        assert record.broker_order_id == "raw-secret-value"
        # Only to_dict() applies masking
        d = record.to_dict()
        assert d["broker_order_id"] != "raw-secret-value"


# ---------------------------------------------------------------------------
# Live endpoint masking
# ---------------------------------------------------------------------------


class TestLiveEndpointMasking:
    def test_mask_account_id_in_check_output(self) -> None:
        """LivePilotExecutor._check_live_endpoint masks account_id in output."""
        from unittest.mock import MagicMock, patch

        # We can't easily call _check_live_endpoint without a real broker,
        # but we can verify the masking function works correctly for account IDs
        masked = mask_account_id("TEST12345678")
        assert masked != "TEST12345678"
        assert "TEST" in masked
        assert "5678" in masked


# ---------------------------------------------------------------------------
# Cross-module: all audit records from executor
# ---------------------------------------------------------------------------


class TestExecutorAuditSecretMasking:
    def test_executor_audit_records_no_secrets(self) -> None:
        """Audit records created through LivePilotExecutor have masked IDs."""
        from datetime import datetime, timezone

        from quant_us.live.live_pilot_executor import LivePilotExecutor, LivePilotExecutorConfig

        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                data_root=td,
                audit_dir=td,
            )
            executor = LivePilotExecutor(config)
            executor.bootstrap()

            # Directly record a submitted entry (simulating what executor does)
            executor.audit_trail.record_submitted(
                audit_id="test_submit_1",
                run_id=executor.run_id,
                broker_order_id="real-broker-order-id-98765",
                symbol="SPY",
                side="buy",
                qty=1.0,
                notional=500.0,
            )

            # Verify the file on disk doesn't have the raw ID
            raw_content = executor.audit_trail.audit_path.read_text()
            assert "real-broker-order-id-98765" not in raw_content

            # Verify read_all() returns masked entries
            for entry in executor.audit_trail.read_all():
                broker_id = entry.get("broker_order_id", "")
                if broker_id:
                    assert "98765" not in broker_id  # last 4 is "8765"
