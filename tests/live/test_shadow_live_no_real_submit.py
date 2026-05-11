from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, OrderIntent
from quant_us.live.modes import RuntimeMode
from quant_us.live.runtime import LiveRuntime
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.live.shadow_live import ShadowLiveConfig


UTC = timezone.utc


def test_shadow_live_config_rejects_real_order_submission_flag() -> None:
    with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
        ShadowLiveConfig(submit_real_orders=True)


def test_shadow_live_runtime_uses_paper_oms_even_when_live_env_flags_are_set() -> None:
    runtime = LiveRuntime(
        LiveRuntimeConfig(
            mode=RuntimeMode.SHADOW_LIVE,
            submit_orders=True,
            allow_live_orders=False,
        )
    )
    runtime.bootstrap()
    decision = MagicMock()
    decision.approved = True
    order = MagicMock()
    order.order_id = "shadow_paper_order_001"
    oms_result = MagicMock()
    oms_result.risk_decision = decision
    oms_result.order = order
    runtime.oms = MagicMock()
    runtime.oms.handle_intent.return_value = oms_result

    intent = OrderIntent(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        strategy_id="shadow_fixture",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1.0,
        client_order_id="shadow_live_no_real_submit_001",
    )
    account = AccountState(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        account_id="shadow_paper",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )

    with patch.dict(
        "os.environ",
        {
            "QUANT_LIVE_SUBMISSION_ENABLED": "true",
            "QUANT_CONFIRM_LIVE": "true",
            "APCA_API_KEY_ID": "live_key",
            "APCA_API_SECRET_KEY": "live_secret",
        },
        clear=True,
    ):
        result = runtime.submit_orders([intent], account=account, market_price=500.0)

    assert runtime.config.real_order_submission_enabled is False
    assert len(result["submitted"]) == 1
    assert result["rejected"] == []
    assert result["audit_events"][0]["event"] == "shadow_order_submitted"
    assert result["audit_events"][0]["note"] == "paper broker only, real broker untouched"
    runtime.oms.handle_intent.assert_called_once()
