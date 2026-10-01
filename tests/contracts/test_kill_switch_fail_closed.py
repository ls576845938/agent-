from __future__ import annotations

from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig


def test_kill_switch_default_thresholds_are_enabled() -> None:
    config = KillSwitchConfig()

    assert config.max_daily_loss_pct > 0
    assert config.max_drawdown_pct > 0
    assert config.max_consecutive_order_failures > 0
    assert config.max_data_staleness_seconds > 0


def test_kill_switch_trips_on_daily_loss() -> None:
    kill_switch = KillSwitch()

    kill_switch.update_equity(100_000.0)
    triggered = kill_switch.update_equity(96_000.0)

    assert triggered is True
    assert kill_switch.triggered is True
    assert kill_switch.reason == "daily_loss_limit"


def test_kill_switch_trips_on_order_failures() -> None:
    kill_switch = KillSwitch(KillSwitchConfig(max_consecutive_order_failures=2))

    assert kill_switch.record_order_failure() is False
    assert kill_switch.record_order_failure() is True
    assert kill_switch.reason == "order_failure_limit"


def test_kill_switch_manual_trip_is_fail_closed() -> None:
    kill_switch = KillSwitch()

    assert kill_switch.trip("manual_contract_test") is True
    assert kill_switch.triggered is True
    assert kill_switch.reason == "manual_contract_test"
