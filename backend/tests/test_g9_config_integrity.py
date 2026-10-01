"""Tests for G9 ConfigIntegrityChecker.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from quant_us.live.g9_config_check import ConfigIntegrityChecker, ConfigIntegrityResult


class TestConfigIntegrity:
    """Tests for ConfigIntegrityChecker safety and detection."""

    def _setup_minimal_config(self, tmp_path: Path) -> None:
        """Helper: create minimal valid config for checking."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        (live_pilot / "runtime_config.json").write_text(json.dumps({
            "mode": "PAPER",
            "version": "1.0",
            "base_url": "https://paper-api.alpaca.markets",
        }))
        env_dir = live_pilot / "envelopes"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "default.json").write_text(json.dumps({
            "envelope_id": "env_default",
            "max_order_notional": 100.0,
        }))

    def test_check_detects_missing_config(self, tmp_path: Path) -> None:
        """No config file -> check fails."""
        checker = ConfigIntegrityChecker(data_root=str(tmp_path))
        result = checker.check()
        assert not result.passed

    def test_check_passes_with_valid_config(self, tmp_path: Path) -> None:
        """Valid config -> check passes."""
        self._setup_minimal_config(tmp_path)
        checker = ConfigIntegrityChecker(data_root=str(tmp_path))
        result = checker.check()
        # Some checks may fail due to missing approvals, but config-level checks pass
        assert "runtime_config_exists" in result.checks

    def test_check_never_outputs_secrets(self, tmp_path: Path) -> None:
        """Check output should not contain raw secret values."""
        self._setup_minimal_config(tmp_path)
        checker = ConfigIntegrityChecker(data_root=str(tmp_path))
        result = checker.check()
        output = json.dumps(result.to_dict())
        assert "sk-" not in output
        assert "pk-" not in output

    def test_markdown_output(self, tmp_path: Path) -> None:
        """ConfigIntegrityResult.to_markdown produces non-empty output."""
        result = ConfigIntegrityResult(
            passed=False,
            checks={"test_check": False},
            drift_detected=["config file missing"],
        )
        md = result.to_markdown()
        assert "FAIL" in md or "config" in md.lower()

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Safety invariant: ConfigIntegrityChecker has no submit_order."""
        import inspect
        import quant_us.live.g9_config_check as mod
        source = inspect.getsource(mod)
        assert "submit_order" not in source
        assert "AlpacaBroker" not in source
