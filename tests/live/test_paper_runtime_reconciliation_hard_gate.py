from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, Bar, OrderIntent
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics


UTC = timezone.utc


def _intent() -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        strategy_id="reconciliation_hard_gate",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1.0,
        client_order_id="reconciliation_hard_gate_001",
    )


def _account() -> AccountState:
    return AccountState(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        account_id="paper",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )


def _bar() -> Bar:
    return Bar(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        symbol="SPY",
        open=500.0,
        high=501.0,
        low=499.0,
        close=500.0,
        volume=10_000.0,
    )


def test_paper_runtime_reconciliation_halt_blocks_before_oms(tmp_path: Path) -> None:
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            reconcile_on_start=False,
            submit_orders=True,
            kill_on_recon_fail=False,
        )
    )
    runtime.oms = MagicMock()
    runtime.oms.reduce_only = False
    runtime._halt_reconciliation = True
    metrics = PaperSessionMetrics()

    runtime._handle_intent(
        _intent(),
        signal=None,
        account=_account(),
        prices={"SPY": 500.0},
        bar=_bar(),
        metrics=metrics,
    )

    runtime.oms.handle_intent.assert_not_called()
    assert metrics.intents_created == 1
    assert metrics.intents_rejected == 1
    assert runtime.audit_events[-1]["event"] == "paper_order_rejected_reconciliation_halt"
    assert runtime.audit_events[-1]["details"]["reason"] == "reconciliation_not_clean"
