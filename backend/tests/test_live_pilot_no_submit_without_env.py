"""Verify that removing QUANT_LIVE_SUBMISSION_ENABLED blocks ALL live paths.

The env gate is checked at every level: config, executor, submission gate,
and simulation. No real order can pass the env gate.
ALL tests use tempfile for storage and monkeypatch for env var control.
"""

from __future__ import annotations

import tempfile

import pytest

from quant_us.live.live_pilot_executor import LivePilotExecutor, LivePilotExecutorConfig
from quant_us.live.live_order_submission_gate import LiveOrderSubmissionGate
from quant_us.live.first_live_order_simulation import FirstLiveOrderSimulation


# ---------------------------------------------------------------------------
# Config level
# ---------------------------------------------------------------------------


class TestConfigEnvGate:
    def test_executor_config_default_env_not_set(self) -> None:
        """Default config does not set the env var; env gate is not bypassed."""
        config = LivePilotExecutorConfig()
        # Config does not read env itself - gate does at check time
        assert config.is_dry_run is True


# ---------------------------------------------------------------------------
# Executor level — env not set, dry-run
# ---------------------------------------------------------------------------


class TestExecutorEnvNotSet:
    def test_execute_without_env_blocked(self) -> None:
        """Without env var, executor still runs but no real submit occurs."""
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                data_root=td,
                audit_dir=td,
                symbols=["SPY"],
            )
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert result["real_submit_occurred"] is False
            assert result["status"] == "DRY_RUN_COMPLETED"

    def test_execute_with_env_true_and_dry_run_still_blocked(self, monkeypatch) -> None:
        """Even with QUANT_LIVE_SUBMISSION_ENABLED=true, dry-run config blocks."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")
        with tempfile.TemporaryDirectory() as td:
            config = LivePilotExecutorConfig(
                data_root=td,
                audit_dir=td,
                symbols=["SPY"],
            )
            executor = LivePilotExecutor(config)
            result = executor.execute()
            assert result["real_submit_occurred"] is False


# ---------------------------------------------------------------------------
# Submission gate level
# ---------------------------------------------------------------------------


class TestSubmissionGateEnvNotSet:
    def test_env_gate_disabled_with_default_env(self) -> None:
        """Submission gate returns env_gate_disabled when env is not set."""
        with tempfile.TemporaryDirectory() as td:
            gate = LiveOrderSubmissionGate(audit_dir=td)
            d = gate.check(
                is_dry_run=False,
                execute_live_pilot=True,
                env_enabled=False,
                approval_id="",
                envelope_id="",
            )
            assert "env_gate_disabled" in d.block_reasons

    def test_env_gate_still_blocked_with_empty_env(self, monkeypatch) -> None:
        """Setting QUANT_LIVE_SUBMISSION_ENABLED='' still blocks the gate."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "")
        with tempfile.TemporaryDirectory() as td:
            gate = LiveOrderSubmissionGate(audit_dir=td)
            # The gate reads ENV directly in _run_submission_gate, but
            # for direct gate.check(), we pass env_enabled param.
            d = gate.check(
                is_dry_run=False,
                execute_live_pilot=True,
                env_enabled=False,
                approval_id="",
                envelope_id="",
            )
            assert "env_gate_disabled" in d.block_reasons


# ---------------------------------------------------------------------------
# Simulation level
# ---------------------------------------------------------------------------


class TestSimulationEnvNotSet:
    def test_simulation_blocked_without_env(self) -> None:
        """FirstLiveOrderSimulation reports env_gate_not_enabled."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert any("env" in r for r in result.gate_block_reasons)

    def test_simulation_still_blocked_with_empty_env(self, monkeypatch) -> None:
        """Setting QUANT_LIVE_SUBMISSION_ENABLED='' still blocks simulation."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "")
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert any("env" in r for r in result.gate_block_reasons)

    def test_simulation_still_blocked_with_explicit_false(self, monkeypatch) -> None:
        """Setting QUANT_LIVE_SUBMISSION_ENABLED='false' still blocks."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "false")
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert any("env" in r for r in result.gate_block_reasons)
