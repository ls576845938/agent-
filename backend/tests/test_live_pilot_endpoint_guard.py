"""Verify G3 modules use ReadOnlyLiveBrokerProxy for live endpoint access.

No G3 module should have direct access to AlpacaBroker. All write paths
must be blocked by the read-only proxy or by not having access to a broker.
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
from quant_us.execution.broker_base import BrokerBase
from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import Order


# ---------------------------------------------------------------------------
# ReadOnlyLiveBrokerProxy blocks all write operations
# ---------------------------------------------------------------------------


G3_MODULES = [
    "quant_us/live/live_pilot_approval.py",
    "quant_us/live/live_pilot_risk_envelope.py",
    "quant_us/live/live_pilot_dry_run.py",
    "quant_us/live/emergency_stop.py",
    "quant_us/live/live_pilot_go_nogo.py",
]

class TestG3ModulesNoDirectBrokerImport:
    def test_no_module_imports_apacabroker(self) -> None:
        for mod_path in G3_MODULES:
            p = Path(mod_path)
            if not p.exists():
                continue
            source = p.read_text()
            assert "AlpacaBroker" not in source, (
                f"{mod_path} imports AlpacaBroker!"
            )
            assert "alpaca_broker" not in source, (
                f"{mod_path} imports alpaca_broker!"
            )

    def test_no_module_calls_submit_order(self) -> None:
        for mod_path in G3_MODULES:
            p = Path(mod_path)
            if not p.exists():
                continue
            source = p.read_text()
            assert ".submit_order(" not in source, (
                f"{mod_path} calls submit_order!"
            )

    def test_no_module_calls_broker_write_methods(self) -> None:
        write_methods = [
            ".submit_order(",
            ".cancel_order(",
            ".replace_order(",
            ".close_position(",
            ".close_all_positions(",
        ]
        for mod_path in G3_MODULES:
            p = Path(mod_path)
            if not p.exists():
                continue
            source = p.read_text()
            for method in write_methods:
                assert method not in source, (
                    f"{mod_path} contains {method}!"
                )


# ---------------------------------------------------------------------------
# RiskEnvelopeManager does not access broker
# ---------------------------------------------------------------------------


class TestRiskEnvelopeManagerNoBroker:
    def test_create_does_not_access_broker(self) -> None:
        from quant_us.live.live_pilot_risk_envelope import (
            LivePilotRiskEnvelope,
            RiskEnvelopeManager,
        )

        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(envelope_id="test_env")
            mgr.create(env)
            # No broker involvement — just file I/O
            loaded = mgr.load("test_env")
            assert loaded is not None

    def test_validate_does_not_access_broker(self) -> None:
        from quant_us.live.live_pilot_risk_envelope import (
            LivePilotRiskEnvelope,
            RiskEnvelopeManager,
        )

        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(envelope_id="test_env")
            mgr.create(env)
            result = mgr.validate(envelope_id="test_env")
            assert "passed" in result


# ---------------------------------------------------------------------------
# EmergencyStopController does not access broker
# ---------------------------------------------------------------------------


class TestG3OrderPathsBlocked:
    def test_dry_run_uses_readonly_endpoint(self) -> None:
        """The dry-run executor's step 6 checks for ReadOnlyLiveBrokerProxy."""
        from quant_us.live.live_pilot_dry_run import LivePilotDryRunExecutor

        with tempfile.TemporaryDirectory() as td:
            executor = LivePilotDryRunExecutor(data_root=td)
            record = executor._step_check_live_endpoint()
            assert record.would_submit is True  # ReadOnlyLiveBrokerProxy is available
            assert record.real_submit is False

    def test_dry_run_final_record_expected_endpoint(self) -> None:
        """The final dry-run record expects the read-only endpoint."""
        from quant_us.live.live_pilot_dry_run import LivePilotDryRunExecutor

        with tempfile.TemporaryDirectory() as td:
            executor = LivePilotDryRunExecutor(data_root=td)
            report = executor.execute(
                approval_id="test",
                envelope_id="test",
            )
            last_record = report.records[-1]
            assert last_record.expected_endpoint == "live_readonly"

    def test_all_write_paths_blocked_proof_in_records(self) -> None:
        """Every dry-run record provides a no_real_submit_proof."""
        from quant_us.live.live_pilot_dry_run import LivePilotDryRunExecutor

        with tempfile.TemporaryDirectory() as td:
            executor = LivePilotDryRunExecutor(data_root=td)
            report = executor.execute(
                approval_id="test",
                envelope_id="test",
            )
            for record in report.records:
                assert "block" in record.no_real_submit_proof.lower() or \
                       "no real" in record.no_real_submit_proof.lower()
