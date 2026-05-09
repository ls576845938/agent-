from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, OrderIntent
from quant_us.live.live_order_submission_gate import SubmissionGateDecision
from quant_us.live.modes import RuntimeMode
from quant_us.live.runtime import LiveRuntime
from quant_us.live.runtime_config import LiveRuntimeConfig


UTC = timezone.utc


class _GateReport:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def is_ready(self, profile: str = "live") -> bool:
        return self.ready


def _intent(client_order_id: str = "live_safety_001") -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        strategy_id="test",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1.0,
        client_order_id=client_order_id,
    )


def _account() -> AccountState:
    return AccountState(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        account_id="live",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )


def _approving_oms() -> MagicMock:
    decision = MagicMock()
    decision.approved = True
    result = MagicMock()
    result.risk_decision = decision
    result.order.order_id = "mock_order_001"
    oms = MagicMock()
    oms.handle_intent.return_value = result
    return oms


def test_live_readiness_passed_still_blocks_without_apca_credentials() -> None:
    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        allow_live_orders=True,
        confirm_live=True,
        live_submission_enabled=True,
        require_readiness_gate=True,
    )
    runtime = LiveRuntime(config=config)

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("quant_us.live.runtime.LiveReadinessGate") as gate_cls,
    ):
        gate_cls.return_value.check_all.return_value = _GateReport(True)
        runtime.bootstrap()
        assert runtime.oms is None
        runtime.oms = _approving_oms()

        result = runtime.submit_orders([_intent()], account=_account(), market_price=500.0)

    assert result["submitted"] == []
    assert result["rejected"]
    assert result["rejected"][0]["reason"] == "live_runtime_safety_shell_no_order_execution"
    runtime.oms.handle_intent.assert_not_called()


def test_live_runtime_default_readiness_artifact_is_fail_closed() -> None:
    runtime = LiveRuntime()
    health = runtime.bootstrap()
    artifact = runtime.readiness_artifact()

    assert health.ok is True
    assert artifact["mode"] == "paper"
    assert artifact["canonical_runtime"] == "PaperRuntime"
    assert artifact["broker_backend"] == "simulated"
    assert artifact["real_order_submission"] is False
    assert artifact["paper_order_submission"] is False
    assert artifact["adapter_contract"]["fail_closed"] is True
    assert artifact["production_loop_started"] is False


def test_live_readiness_failure_is_passed_to_order_block_reasons() -> None:
    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        allow_live_orders=True,
        confirm_live=True,
        live_submission_enabled=True,
        require_readiness_gate=True,
    )
    runtime = LiveRuntime(config=config)

    with (
        patch.dict(
            "os.environ",
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            clear=True,
        ),
        patch("quant_us.live.runtime.LiveReadinessGate") as gate_cls,
        patch.object(LiveRuntime, "_init_live_oms"),
    ):
        gate_cls.return_value.check_all.return_value = _GateReport(False)
        runtime.bootstrap()

    assert "live_readiness_gate_not_passed" in runtime._live_order_block_reasons()


def test_live_orders_need_all_explicit_flags_even_when_readiness_passes() -> None:
    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        allow_live_orders=False,
        confirm_live=False,
        live_submission_enabled=False,
        require_readiness_gate=True,
    )
    runtime = LiveRuntime(config=config)

    with (
        patch.dict(
            "os.environ",
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            clear=True,
        ),
        patch("quant_us.live.runtime.LiveReadinessGate") as gate_cls,
    ):
        gate_cls.return_value.check_all.return_value = _GateReport(True)
        runtime.bootstrap()

    reasons = runtime._live_order_block_reasons()
    assert "allow_live_orders_false" in reasons
    assert "confirm_live_missing" in reasons
    assert "live_submission_disabled_by_config" in reasons
    assert "live_readiness_gate_not_passed" not in reasons


def test_live_orders_do_not_handle_intent_without_explicit_submission_gate() -> None:
    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        allow_live_orders=True,
        confirm_live=True,
        live_submission_enabled=True,
        require_readiness_gate=True,
    )
    runtime = LiveRuntime(config=config)
    runtime.oms = _approving_oms()

    with (
        patch.dict(
            "os.environ",
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            clear=True,
        ),
        patch("quant_us.live.runtime.LiveReadinessGate") as gate_cls,
    ):
        gate_cls.return_value.check_all.return_value = _GateReport(True)
        runtime.bootstrap()
        result = runtime.submit_orders([_intent("live_safety_003")], account=_account(), market_price=500.0)

    assert result["submitted"] == []
    assert result["rejected"][0]["reason"] == "live_runtime_safety_shell_no_order_execution"
    runtime.oms.handle_intent.assert_not_called()


def test_live_runtime_does_not_construct_real_oms_when_all_config_flags_pass() -> None:
    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        allow_live_orders=True,
        confirm_live=True,
        live_submission_enabled=True,
        require_readiness_gate=True,
    )
    runtime = LiveRuntime(config=config)

    with (
        patch.dict(
            "os.environ",
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            clear=True,
        ),
        patch("quant_us.live.runtime.LiveReadinessGate") as gate_cls,
        patch.object(
            runtime._live_submission_gate,
            "check",
            return_value=SubmissionGateDecision(decision="APPROVED_FOR_SUBMIT"),
        ),
    ):
        gate_cls.return_value.check_all.return_value = _GateReport(True)
        decision = runtime.configure_live_submission_gate(
            approval_id="approved_live_order",
            envelope_id="approved_envelope",
            dossier_decision="GO_FOR_SMALL_LIVE_REVIEW",
            live_endpoint_ok=True,
            reconciliation_clean=True,
            emergency_stop_armed=True,
            in_regular_session=True,
            oms_idempotency_ok=True,
        )
        health = runtime.bootstrap()

    artifact = runtime.readiness_artifact()
    assert decision.approved is True
    assert health.ok is True
    assert runtime.oms is None
    assert artifact["mode"] == "live"
    assert artifact["canonical_runtime"] == "LiveRuntime"
    assert artifact["real_order_submission"] is False
    assert artifact["production_loop_started"] is False


def test_live_orders_do_not_reach_injected_mock_oms_when_all_runtime_gates_clear() -> None:
    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        allow_live_orders=True,
        confirm_live=True,
        live_submission_enabled=True,
        require_readiness_gate=True,
    )
    runtime = LiveRuntime(config=config)
    runtime.oms = _approving_oms()

    with (
        patch.dict(
            "os.environ",
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
            clear=True,
        ),
        patch.object(
            runtime._live_submission_gate,
            "check",
            return_value=SubmissionGateDecision(decision="APPROVED_FOR_SUBMIT"),
        ),
    ):
        runtime._last_live_readiness_passed = True
        decision = runtime.configure_live_submission_gate(
            approval_id="approved_live_order",
            envelope_id="approved_envelope",
            dossier_decision="GO_FOR_SMALL_LIVE_REVIEW",
            live_endpoint_ok=True,
            reconciliation_clean=True,
            emergency_stop_armed=True,
            in_regular_session=True,
            oms_idempotency_ok=True,
        )
        assert decision.approved is True
        result = runtime.submit_orders([_intent("live_safety_004")], account=_account(), market_price=500.0)

    assert result["submitted"] == []
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["reason"] == "live_runtime_safety_shell_no_order_execution"
    runtime.oms.handle_intent.assert_not_called()
