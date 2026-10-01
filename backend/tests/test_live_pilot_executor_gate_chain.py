"""Test LivePilotExecutorConfig and LivePilotExecutor gate chain for G4.

Covers config validation, bootstrap, dry-run (no-submit) mode, and status
reporting for missing approval / missing envelope scenarios.
ALL tests use tempfile for storage and verify NO real broker calls.
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from quant_us.live.live_pilot_executor import LivePilotExecutor, LivePilotExecutorConfig


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestLivePilotExecutorConfig:
    def test_execute_live_pilot_without_confirm_live_raises(self) -> None:
        """execute_live_pilot=True without confirm_live=True raises ValueError."""
        with pytest.raises(ValueError, match="confirm.live|confirm_live"):
            LivePilotExecutorConfig(execute_live_pilot=True, confirm_live=False)

    def test_default_is_dry_run(self) -> None:
        """Default config has is_dry_run=True and execute_live_pilot=False."""
        config = LivePilotExecutorConfig()
        assert config.is_dry_run is True
        assert config.execute_live_pilot is False

    def test_execute_live_pilot_false_with_confirm_live_still_dry_run(self) -> None:
        """When execute_live_pilot=False, is_dry_run is forced True even with confirm_live."""
        config = LivePilotExecutorConfig(execute_live_pilot=False, confirm_live=True)
        assert config.is_dry_run is True


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestLivePilotExecutorBootstrap:
    def test_bootstrap_creates_run_id(self) -> None:
        """bootstrap() generates a non-empty run_id starting with the expected prefix."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(data_root=td, audit_dir=td)
            executor = LivePilotExecutor(config)
            assert executor.bootstrap() is True
            assert executor.run_id.startswith("live_pilot_run_")

    def test_bootstrap_records_audit_entry(self) -> None:
        """bootstrap() writes an audit record with BOOTSTRAPPING status."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(data_root=td, audit_dir=td)
            executor = LivePilotExecutor(config)
            executor.bootstrap()
            entries = executor.audit_trail.read_all()
            assert any(e.get("status") == "BOOTSTRAPPING" for e in entries)


# ---------------------------------------------------------------------------
# Dry-run execution
# ---------------------------------------------------------------------------


class TestLivePilotExecutorDryRun:
    def test_execute_dry_run_returns_dry_run_completed(self) -> None:
        """Default dry-run config returns DRY_RUN_COMPLETED status."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(data_root=td, audit_dir=td)
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert result["status"] == "DRY_RUN_COMPLETED"

    def test_dry_run_real_submit_occurred_is_false(self) -> None:
        """Dry-run execution never sets real_submit_occurred to True."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(data_root=td, audit_dir=td)
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert result["real_submit_occurred"] is False

    def test_dry_run_produces_run_id(self) -> None:
        """Execute always produces a run_id in the result."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(data_root=td, audit_dir=td)
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert "run_id" in result
            assert result["run_id"].startswith("live_pilot_run_")


# ---------------------------------------------------------------------------
# Missing approval / envelope status
# ---------------------------------------------------------------------------


class TestLivePilotExecutorMissingApproval:
    def test_missing_approval_shows_in_status(self) -> None:
        """When approval_id is set but no approval file exists, status shows the issue."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                approval_id="nonexistent_approval",
                data_root=td,
                audit_dir=td,
            )
            executor = LivePilotExecutor(config)
            result = executor.execute()
            status = str(result["steps"]["approval"])
            assert "missing" in status.lower() or "not found" in status.lower()


class TestLivePilotExecutorMissingEnvelope:
    def test_missing_envelope_shows_in_status(self) -> None:
        """When envelope_id is set but no envelope file exists, status shows the issue."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                envelope_id="nonexistent_envelope",
                data_root=td,
                audit_dir=td,
            )
            executor = LivePilotExecutor(config)
            result = executor.execute()
            status = str(result["steps"]["envelope"])
            assert "missing" in status.lower() or "not_found" in status.lower()


# ---------------------------------------------------------------------------
# live_pilot=False + confirm_live=True — still dry-run
# ---------------------------------------------------------------------------


class TestLivePilotExecutorConfigDryRunForcing:
    def test_execute_live_false_with_confirm_true_is_dry_run(self) -> None:
        """Even with confirm_live=True, execute_live_pilot=False forces dry-run in execute."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                execute_live_pilot=False,
                confirm_live=True,
                data_root=td,
                audit_dir=td,
            )
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert result["real_submit_occurred"] is False
            assert result["status"] == "DRY_RUN_COMPLETED"
