from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Fill, Order, PortfolioSnapshot
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from scripts.run_paper_validation import save_report

UTC = timezone.utc


def _broker_state_recovery_artifact(ledger_root: Path) -> dict[str, object]:
    return json.loads(
        (ledger_root / "audit" / "paper_broker_state_recovery.json").read_text(encoding="utf-8")
    )


def test_paper_validation_report_stays_incomplete_when_recovery_is_not_operational(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "validation_report.json"
    state = {
        "days_required": 30,
        "days_completed": 30,
        "consecutive_clean_days": 30,
        "daily_results": [],
        "recovery_summary": {
            "required": True,
            "status": "failed",
            "operationally_complete": False,
            "resume_restores_broker_state": False,
            "resume_restores_validation_counters": True,
        },
    }

    save_report(state, report_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "INCOMPLETE"
    assert report["passed"] is False


def test_paper_validation_report_stays_incomplete_when_recovery_artifact_path_is_missing(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "validation_report.json"
    state = {
        "days_required": 30,
        "days_completed": 30,
        "consecutive_clean_days": 30,
        "daily_results": [],
        "recovery_summary": {
            "required": False,
            "status": "restored",
            "operationally_complete": True,
            "resume_restores_broker_state": True,
            "resume_restores_validation_counters": True,
        },
        "evidence": {},
    }

    save_report(state, report_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "INCOMPLETE"
    assert report["passed"] is False


def test_paper_trading_loop_restores_state_from_ledger_on_resume(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    ledger = JsonlLedgerStore(ledger_root)
    ledger.append_order(
        Order(
            timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
            strategy_id="resume_fixture",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=5.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="resume_client_001",
            order_id="resume_order_001",
            status=OrderStatus.FILLED,
        )
    )
    ledger.append_fill(
        Fill(
            order_id="resume_order_001",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=5.0,
            price=200.0,
            commission=1.0,
            filled_at=datetime(2026, 5, 4, 14, 31, tzinfo=UTC),
            broker="paper",
            fill_id="resume_fill_001",
        )
    )
    ledger.append_snapshot(
        PortfolioSnapshot(
            timestamp_utc=datetime(2026, 5, 4, 20, 0, tzinfo=UTC),
            equity=100_100.0,
            cash=98_999.0,
            gross_exposure=1_100.0,
            net_exposure=1_100.0,
            daily_pnl=100.0,
            drawdown=0.0,
        )
    )

    loop = PaperTradingLoop(
        config=PaperTradingConfig(
            initial_cash=100_000.0,
            ledger_root=str(ledger_root),
        )
    )

    assert loop.broker.cash == 98_999.0
    assert "AAPL" in loop.broker.positions
    assert loop.broker.positions["AAPL"].quantity == 5.0
    assert len(loop.broker.orders) == 1
    assert len(loop.broker.fills) == 1
    assert loop.is_healthy() is True

    artifact = _broker_state_recovery_artifact(ledger_root)
    assert artifact["status"] == "restored"
    assert artifact["resume_detected"] is True
    assert artifact["operationally_complete"] is True
    assert artifact["broker_state_restored"] is True
