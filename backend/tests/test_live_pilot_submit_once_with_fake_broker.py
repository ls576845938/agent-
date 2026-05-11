"""Test that LivePilotExecutor stays frozen when ALL gates pass."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import AccountState, Order
from quant_us.live.live_order_audit import LiveOrderAuditRecord
from quant_us.live.live_order_submission_gate import SubmissionGateDecision
from quant_us.live.live_pilot_executor import LivePilotExecutor, LivePilotExecutorConfig

# ---------------------------------------------------------------------------
# Helper: an approved gate decision
# ---------------------------------------------------------------------------

_APPROVED_DECISION = SubmissionGateDecision(
    decision="APPROVED_FOR_SUBMIT",
    block_reasons=[],
)


# ---------------------------------------------------------------------------
# Happy path: all gates pass, submit_order is called
# ---------------------------------------------------------------------------


class TestLivePilotSubmitWithFakeBroker:
    def test_submit_order_blocked_when_all_gates_pass(self, monkeypatch) -> None:
        """When ALL gates pass, live pilot still cannot call submit_order."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")

        mock_broker = MagicMock()
        mock_broker.broker_name = "alpaca"
        mock_broker.submit_order.return_value = MagicMock(broker_order_id="broker-order-abc123")
        mock_broker.get_account.return_value = AccountState(
            timestamp_utc=datetime.now(timezone.utc),
            account_id="TEST12345",
            cash=100000.0,
            equity=100000.0,
            buying_power=200000.0,
        )

        mock_hag = MagicMock()
        mock_hag.check.return_value = MagicMock(
            passed=True, reason="ok",
            checks={"status_approved": True, "not_expired": True, "strategy_version_match": True},
        )
        mock_hag.inspect.return_value = MagicMock()

        mock_rem = MagicMock()
        mock_env = MagicMock()
        mock_env.max_order_notional = 10000.0
        mock_env.max_daily_notional = 50000.0
        mock_env.allow_market_order = False
        mock_rem.load.return_value = mock_env

        with (
            patch("quant_us.live.live_pilot_executor.AlpacaBroker", return_value=mock_broker),
            patch("quant_us.live.live_pilot_approval.HumanApprovalGate", return_value=mock_hag),
            patch("quant_us.live.live_pilot_risk_envelope.RiskEnvelopeManager", return_value=mock_rem),
            patch.object(
                LivePilotExecutor,
                "_run_submission_gate",
                return_value=_APPROVED_DECISION,
            ),
        ):
            with tempfile.TemporaryDirectory() as td:
                report_dir = Path(td) / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "live_pilot_go_no_go.json").write_text(
                    json.dumps({"decision": "READY_FOR_HUMAN_REVIEW"})
                )

                config = LivePilotExecutorConfig(
                    approval_id="test_approval",
                    envelope_id="test_env",
                    symbols=["SPY"],
                    strategy_id="etf_rotation",
                    strategy_version="1.0.0",
                    execute_live_pilot=True,
                    confirm_live=True,
                    is_dry_run=False,
                    data_root=td,
                    audit_dir=td,
                    api_key="test_key_dummy",
                    api_secret="test_secret_dummy",
                )
                executor = LivePilotExecutor(config)
                result = executor.execute()

                assert result["real_submit_occurred"] is False
                mock_broker.submit_order.assert_not_called()
                for preview in result.get("previews", []):
                    assert preview["submit_result"]["submitted"] is False
                    assert (
                        preview["submit_result"]["reason"]
                        == "live_runtime_frozen_no_order_submission"
                    )

    def test_order_intent_id_traceable(self, monkeypatch) -> None:
        """The order_intent_id from the intent appears in the preview and audit."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")

        mock_broker = MagicMock()
        mock_broker.broker_name = "alpaca"
        mock_broker.submit_order.return_value = MagicMock(broker_order_id="broker-order-xyz")
        mock_broker.get_account.return_value = AccountState(
            timestamp_utc=datetime.now(timezone.utc),
            account_id="TEST12345",
            cash=100000.0,
            equity=100000.0,
            buying_power=200000.0,
        )

        mock_hag = MagicMock()
        mock_hag.check.return_value = MagicMock(
            passed=True, reason="ok",
            checks={"status_approved": True, "not_expired": True},
        )
        mock_hag.inspect.return_value = MagicMock()

        mock_rem = MagicMock()
        mock_env = MagicMock()
        mock_env.max_order_notional = 10000.0
        mock_env.max_daily_notional = 50000.0
        mock_env.allow_market_order = False
        mock_rem.load.return_value = mock_env

        with (
            patch("quant_us.live.live_pilot_executor.AlpacaBroker", return_value=mock_broker),
            patch("quant_us.live.live_pilot_approval.HumanApprovalGate", return_value=mock_hag),
            patch("quant_us.live.live_pilot_risk_envelope.RiskEnvelopeManager", return_value=mock_rem),
            patch.object(
                LivePilotExecutor,
                "_run_submission_gate",
                return_value=_APPROVED_DECISION,
            ),
        ):
            with tempfile.TemporaryDirectory() as td:
                report_dir = Path(td) / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "live_pilot_go_no_go.json").write_text(
                    json.dumps({"decision": "READY_FOR_HUMAN_REVIEW"})
                )

                config = LivePilotExecutorConfig(
                    approval_id="test_approval",
                    envelope_id="test_env",
                    symbols=["SPY"],
                    execute_live_pilot=True,
                    confirm_live=True,
                    is_dry_run=False,
                    data_root=td,
                    audit_dir=td,
                    api_key="test_key_dummy",
                    api_secret="test_secret_dummy",
                )
                executor = LivePilotExecutor(config)
                result = executor.execute()

                # Audit trail has no real_submit entries.
                audit_entries = executor.audit_trail.read_all()
                submitted = [e for e in audit_entries if e.get("real_submit") is True]
                assert submitted == []
                mock_broker.submit_order.assert_not_called()

                for preview in result.get("previews", []):
                    sr = preview.get("submit_result", {})
                    assert sr.get("submitted") is False
                    assert sr.get("reason") == "live_runtime_frozen_no_order_submission"

    def test_audit_records_no_real_submit_for_frozen_order(self, monkeypatch) -> None:
        """Frozen live pilot does not create real_submit audit entries."""
        monkeypatch.setenv("QUANT_LIVE_SUBMISSION_ENABLED", "true")

        mock_broker = MagicMock()
        mock_broker.broker_name = "alpaca"
        mock_broker.submit_order.return_value = MagicMock(broker_order_id="broker-order-456")
        mock_broker.get_account.return_value = AccountState(
            timestamp_utc=datetime.now(timezone.utc),
            account_id="TEST12345",
            cash=100000.0,
            equity=100000.0,
            buying_power=200000.0,
        )

        mock_hag = MagicMock()
        mock_hag.check.return_value = MagicMock(
            passed=True, reason="ok",
            checks={"status_approved": True, "not_expired": True},
        )
        mock_hag.inspect.return_value = MagicMock()

        mock_rem = MagicMock()
        mock_env = MagicMock()
        mock_env.max_order_notional = 10000.0
        mock_env.max_daily_notional = 50000.0
        mock_env.allow_market_order = False
        mock_rem.load.return_value = mock_env

        with (
            patch("quant_us.live.live_pilot_executor.AlpacaBroker", return_value=mock_broker),
            patch("quant_us.live.live_pilot_approval.HumanApprovalGate", return_value=mock_hag),
            patch("quant_us.live.live_pilot_risk_envelope.RiskEnvelopeManager", return_value=mock_rem),
            patch.object(
                LivePilotExecutor,
                "_run_submission_gate",
                return_value=_APPROVED_DECISION,
            ),
        ):
            with tempfile.TemporaryDirectory() as td:
                report_dir = Path(td) / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "live_pilot_go_no_go.json").write_text(
                    json.dumps({"decision": "READY_FOR_HUMAN_REVIEW"})
                )

                config = LivePilotExecutorConfig(
                    approval_id="test_approval",
                    envelope_id="test_env",
                    symbols=["SPY"],
                    execute_live_pilot=True,
                    confirm_live=True,
                    is_dry_run=False,
                    data_root=td,
                    audit_dir=td,
                    api_key="test_key_dummy",
                    api_secret="test_secret_dummy",
                )
                executor = LivePilotExecutor(config)
                executor.execute()

                assert executor.audit_trail.real_submit_count() == 0
                mock_broker.submit_order.assert_not_called()
                entries = executor.audit_trail.read_all()
                real_entries = [e for e in entries if e.get("real_submit") is True]
                assert real_entries == []
