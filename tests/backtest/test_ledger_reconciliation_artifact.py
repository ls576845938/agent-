from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from quant_us.backtest.ledger_pnl import build_ledger_reconciliation_artifact
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill
from quant_us.execution.fill_idempotency import append_fill_idempotent
from quant_us.execution.ledger import JsonlLedgerStore


def _fill(**overrides: object) -> Fill:
    values = {
        "order_id": "ord_001",
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "quantity": 10.0,
        "price": 100.0,
        "commission": 1.0,
        "filled_at": datetime(2026, 5, 4, 14, 30, tzinfo=timezone.utc),
        "broker": "paper",
        "broker_order_id": "broker_ord_001",
        "fill_id": "fill_001",
    }
    values.update(overrides)
    return Fill(**values)  # type: ignore[arg-type]


def test_artifact_derives_cash_position_and_pnl_from_effective_fills(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    buy = _fill()
    sell = _fill(
        order_id="ord_002",
        side=OrderSide.SELL,
        quantity=4.0,
        price=110.0,
        commission=1.0,
        filled_at=datetime(2026, 5, 4, 15, 30, tzinfo=timezone.utc),
        broker_order_id="broker_ord_002",
        fill_id="fill_002",
    )
    ledger.append_fill(buy)
    ledger.append_fill(sell)

    artifact = build_ledger_reconciliation_artifact(
        ledger,
        initial_cash=10_000.0,
        market_prices_by_time={
            buy.filled_at: {"AAPL": 100.0},
            sell.filled_at: {"AAPL": 120.0},
        },
    )
    data = artifact.to_dict()

    assert data["pnl"]["source"] == "ledger_fills"
    assert data["cash"]["final_cash"] == pytest.approx(9438.0)
    assert data["positions"]["AAPL"]["quantity"] == pytest.approx(6.0)
    assert data["positions"]["AAPL"]["market_value"] == pytest.approx(720.0)
    assert data["fees"]["total_fees"] == pytest.approx(2.0)
    assert data["pnl"]["final_equity"] == pytest.approx(10_158.0)
    assert data["pnl"]["net_pnl"] == pytest.approx(158.0)
    assert data["fills"]["raw_fill_count"] == 2
    assert data["fills"]["effective_fill_count"] == 2
    assert data["fills"]["duplicate_fill_count"] == 0
    assert data["fills"]["conflict_fill_count"] == 0
    json.dumps(data, sort_keys=True)


def test_idempotent_duplicate_skip_does_not_change_artifact(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = _fill(fill_id="fill_idempotent")
    first = append_fill_idempotent(ledger, fill)
    before = build_ledger_reconciliation_artifact(ledger, initial_cash=10_000.0).to_dict()

    duplicate = append_fill_idempotent(ledger, fill)
    after = build_ledger_reconciliation_artifact(ledger, initial_cash=10_000.0).to_dict()

    assert first.appended is True
    assert duplicate.duplicate is True
    assert before == after
    assert before["artifact_hash"] == after["artifact_hash"]
    assert after["fills"]["raw_fill_count"] == 1
    assert after["fills"]["duplicate_fill_count"] == 0


def test_conflicting_fill_row_is_visible_without_changing_effective_replay(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = _fill(fill_id="fill_conflict")
    ledger.append_fill(fill)
    ledger.append_fill(replace(fill, price=101.0))

    artifact = build_ledger_reconciliation_artifact(ledger, initial_cash=10_000.0)
    data = artifact.to_dict()

    assert data["fills"]["raw_fill_count"] == 2
    assert data["fills"]["effective_fill_count"] == 1
    assert data["fills"]["conflict_fill_count"] == 1
    assert data["fills"]["conflict_fill_keys"] == ["fill_id:fill_conflict"]
    assert data["integrity"]["fills"]["passed"] is False
    assert data["integrity"]["passed"] is False
    assert data["cash"]["final_cash"] == pytest.approx(8999.0)
