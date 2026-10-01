"""Canonical PnL replay adapter for the US equity paper ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from quant_us.backtest.corporate_actions_ledger import LedgerAdjustment, LedgerAdjustmentLog
from quant_us.backtest.ledger_pnl import build_ledger_reconciliation_artifact_from_records
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, PortfolioSnapshot


def build_paper_ledger_pnl_replay(
    *,
    fill_rows: list[Mapping[str, Any]],
    position_rows: list[Mapping[str, Any]],
    cash_rows: list[Mapping[str, Any]],
    snapshot_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not fill_rows and not position_rows and not cash_rows and not snapshot_rows:
        return _empty_replay("not_started", [])

    blockers: list[str] = []
    fills: list[Fill] = []
    for index, row in enumerate(fill_rows):
        try:
            fills.append(_paper_fill(row, index))
        except (TypeError, ValueError, KeyError) as exc:
            blockers.append(f"paper_ledger_pnl_fill_invalid:{index}:{type(exc).__name__}")

    prices_by_time: dict[datetime, dict[str, float]] = {}
    for index, row in enumerate(position_rows):
        try:
            timestamp = _timestamp(row.get("timestamp"))
        except ValueError as exc:
            blockers.append(f"paper_ledger_pnl_position_timestamp_invalid:{index}:{type(exc).__name__}")
            continue
        prices_by_time[timestamp] = {
            str(symbol).upper(): _float(_mapping(position).get("price"))
            for symbol, position in _mapping(row.get("positions")).items()
        }

    cash_by_time = {str(row.get("timestamp", "")): row for row in cash_rows if row.get("timestamp")}
    snapshots: list[PortfolioSnapshot] = []
    for index, row in enumerate(snapshot_rows):
        timestamp_text = str(row.get("timestamp", ""))
        cash_row = cash_by_time.get(timestamp_text, {})
        if "ending_cash" not in cash_row:
            blockers.append(f"paper_ledger_pnl_ending_cash_missing:{timestamp_text or index}")
            continue
        try:
            snapshots.append(
                PortfolioSnapshot(
                    timestamp_utc=_timestamp(timestamp_text),
                    equity=_float(row.get("equity")),
                    cash=_float(cash_row.get("ending_cash")),
                    gross_exposure=_float(row.get("gross_exposure")),
                    net_exposure=_float(row.get("net_exposure")),
                )
            )
        except (TypeError, ValueError) as exc:
            blockers.append(f"paper_ledger_pnl_snapshot_invalid:{timestamp_text or index}:{type(exc).__name__}")

    if not cash_rows:
        blockers.append("paper_ledger_pnl_cash_ledger_missing")
        initial_cash = 0.0
    else:
        first_cash = cash_rows[0]
        if "prior_cash" not in first_cash:
            blockers.append("paper_ledger_pnl_initial_cash_missing")
        initial_cash = _float(first_cash.get("prior_cash", first_cash.get("prior_equity", 0.0)))

    adjustments = LedgerAdjustmentLog()
    for row in cash_rows:
        financing = _float(row.get("estimated_financing_daily", 0.0))
        if financing <= 0:
            continue
        adjustments.adjustments.append(
            LedgerAdjustment(
                timestamp_utc=_timestamp(row.get("timestamp")),
                symbol="CASH",
                adjustment_type="borrow_fee",
                amount=-financing,
                description="paper simulation financing cost",
            )
        )

    artifact = build_ledger_reconciliation_artifact_from_records(
        order_records=[],
        fills=fills,
        initial_cash=initial_cash,
        market_prices_by_time=prices_by_time,
        snapshots=snapshots,
        adjustments=adjustments if adjustments.adjustments else None,
        tolerance_pct=0.0001,
        absolute_tolerance=0.01,
    ).to_dict()
    reconciliation = _mapping(artifact.get("reconciliation"))
    reconciliation_summary = _mapping(reconciliation.get("summary"))
    integrity = _mapping(artifact.get("integrity"))
    if reconciliation_summary.get("passed") is not True:
        blockers.append("paper_ledger_pnl_snapshot_reconciliation_failed")
    if integrity.get("passed") is not True:
        blockers.append("paper_ledger_pnl_fill_integrity_failed")

    canonical_positions = _mapping(artifact.get("positions"))
    expected_positions = _mapping(position_rows[-1].get("positions")) if position_rows else {}
    position_diffs: dict[str, float] = {}
    for symbol in sorted(set(canonical_positions) | set(expected_positions)):
        actual_qty = _float(_mapping(canonical_positions.get(symbol)).get("quantity", 0.0))
        expected_qty = _float(_mapping(expected_positions.get(symbol)).get("quantity", 0.0))
        position_diffs[str(symbol)] = round(actual_qty - expected_qty, 10)
    if any(abs(value) > 1e-8 for value in position_diffs.values()):
        blockers.append("paper_ledger_pnl_position_quantity_mismatch")

    final_cash = _float(_mapping(artifact.get("cash")).get("final_cash", 0.0))
    expected_final_cash = _float(cash_rows[-1].get("ending_cash", 0.0)) if cash_rows else 0.0
    cash_diff = round(final_cash - expected_final_cash, 8)
    if abs(cash_diff) > 0.01:
        blockers.append("paper_ledger_pnl_cash_balance_mismatch")

    reconciliation_rows = [
        row for row in reconciliation.get("snapshots", []) if isinstance(row, Mapping)
    ]
    equity_curve = [
        {
            "timestamp": str(row.get("timestamp_utc", "")),
            "cash": _float(row.get("ledger_cash", 0.0)),
            "equity": _float(row.get("ledger_equity", 0.0)),
        }
        for row in reconciliation_rows
    ]
    pnl = _mapping(artifact.get("pnl"))
    return {
        "status": "passed" if not blockers else "blocked",
        "canonical_replay_module": "quant_us.backtest.ledger_pnl",
        "source": "fills_positions_cash_ledger",
        "initial_cash": round(initial_cash, 6),
        "raw_fill_count": len(fill_rows),
        "effective_fill_count": int(_mapping(artifact.get("fills")).get("effective_fill_count", 0) or 0),
        "snapshot_count": len(snapshot_rows),
        "latest_equity": _float(pnl.get("final_equity", initial_cash)),
        "net_pnl": _float(pnl.get("net_pnl", 0.0)),
        "final_cash": final_cash,
        "expected_final_cash": expected_final_cash,
        "cash_diff": cash_diff,
        "position_quantity_diffs": position_diffs,
        "equity_curve": equity_curve,
        "artifact_hash": str(artifact.get("artifact_hash", "")),
        "reconciliation": reconciliation,
        "integrity": integrity,
        "blockers": _dedupe(blockers),
    }


def _paper_fill(row: Mapping[str, Any], index: int) -> Fill:
    symbol = str(row["symbol"]).upper()
    side = OrderSide(str(row["side"]).lower())
    quantity = _float(row["quantity"])
    price = _float(row["price"])
    if not symbol or quantity <= 0 or price <= 0:
        raise ValueError("paper fill symbol, quantity and price must be positive")
    timestamp = _timestamp(row.get("filled_at") or row.get("timestamp"))
    order_id = str(row.get("order_id") or f"paper-{timestamp.date().isoformat()}-{symbol}-{index}")
    fill_id = str(row.get("fill_id") or f"{order_id}-fill")
    return Fill(
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        commission=_float(row.get("commission", 0.0)),
        filled_at=timestamp,
        broker="paper_simulation",
        broker_order_id="",
        fill_id=fill_id,
    )


def _timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp missing")
    if "T" not in text:
        text = f"{text}T00:00:00+00:00"
    else:
        text = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _empty_replay(status: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "canonical_replay_module": "quant_us.backtest.ledger_pnl",
        "source": "fills_positions_cash_ledger",
        "initial_cash": 0.0,
        "raw_fill_count": 0,
        "effective_fill_count": 0,
        "snapshot_count": 0,
        "latest_equity": 0.0,
        "net_pnl": 0.0,
        "final_cash": 0.0,
        "expected_final_cash": 0.0,
        "cash_diff": 0.0,
        "position_quantity_diffs": {},
        "equity_curve": [],
        "artifact_hash": "",
        "reconciliation": {},
        "integrity": {},
        "blockers": blockers,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(value: Any) -> float:
    return float(value or 0.0)


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
