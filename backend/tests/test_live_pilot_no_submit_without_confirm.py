"""Verify that missing --confirm-live blocks ALL live order paths.

The confirm_live flag is the CLI-level safety catch: even if execute_live_pilot
is set, missing confirm_live prevents submission at config level (ValueError)
and at the submission gate level (BLOCKED).
"""

from __future__ import annotations

import tempfile

import pytest

from quant_us.live.live_pilot_executor import LivePilotExecutor, LivePilotExecutorConfig
from quant_us.live.live_order_submission_gate import LiveOrderSubmissionGate


# ---------------------------------------------------------------------------
# Config level — executes live without confirm raises
# ---------------------------------------------------------------------------


class TestConfigRequiresConfirm:
    def test_execute_live_pilot_without_confirm_raises_value_error(self) -> None:
        """Config raises ValueError when execute_live_pilot=True but confirm_live=False."""
        with pytest.raises(ValueError):
            LivePilotExecutorConfig(execute_live_pilot=True, confirm_live=False)

    def test_execute_live_pilot_with_confirm_ok(self) -> None:
        """Config is valid when both execute_live_pilot and confirm_live are set."""
        config = LivePilotExecutorConfig(execute_live_pilot=True, confirm_live=True)
        assert config.is_dry_run is False

    def test_all_env_set_but_confirm_false_raises(self, monkeypatch) -> None:
        """Even with all env vars set, config still raises without confirm_live."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        monkeypatch.setenv("allow_live_orders", "true")
        with pytest.raises(ValueError):
            LivePilotExecutorConfig(execute_live_pilot=True, confirm_live=False)


# ---------------------------------------------------------------------------
# Executor level — confirm_live=False = dry-run
# ---------------------------------------------------------------------------


class TestExecutorWithoutConfirm:
    def test_executor_with_confirm_false_is_dry_run(self) -> None:
        """When confirm_live=False, executor stays in dry-run (config forces is_dry_run)."""
        # Note: execute_live_pilot=False here because True+False raises
        config = LivePilotExecutorConfig(execute_live_pilot=False, confirm_live=False)
        assert config.is_dry_run is True

    def test_execute_live_pilot_false_with_confirm_true_still_dry_run(self) -> None:
        """Even with confirm_live=True, execute_live_pilot=False means dry-run."""
        config = LivePilotExecutorConfig(execute_live_pilot=False, confirm_live=True)
        assert config.is_dry_run is True

    def test_executor_without_confirm_stays_dry(self) -> None:
        """Executor with dry-run defaults never submits."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                execute_live_pilot=False,
                confirm_live=False,
                data_root=td,
                audit_dir=td,
            )
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert result["real_submit_occurred"] is False
            assert result["status"] == "DRY_RUN_COMPLETED"


# ---------------------------------------------------------------------------
# Submission gate level
# ---------------------------------------------------------------------------


class TestSubmissionGateWithoutConfirm:
    def test_confirm_live_false_blocked(self) -> None:
        """Submission gate blocks when confirm_live=False."""
        with tempfile.TemporaryDirectory() as td:
            gate = LiveOrderSubmissionGate(audit_dir=td)
            d = gate.check(
                is_dry_run=False,
                execute_live_pilot=True,
                confirm_live=False,
                approval_id="",
                envelope_id="",
            )
            assert d.blocked
            assert "missing_confirm_live" in d.block_reasons

    def test_confirm_live_true_with_env_but_no_approval(self) -> None:
        """confirm_live=True alone is not enough; other gates still block."""
        with tempfile.TemporaryDirectory() as td:
            gate = LiveOrderSubmissionGate(audit_dir=td)
            d = gate.check(
                is_dry_run=False,
                execute_live_pilot=True,
                confirm_live=True,
                env_enabled=True,
                approval_id="",
                envelope_id="",
            )
            assert "missing_approval" in d.block_reasons
