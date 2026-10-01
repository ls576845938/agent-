from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_perpetual_paper_runtime_reconciliation import (
    build_btc_perpetual_paper_runtime_reconciliation_report,
)


def test_reconciliation_passes_flat_and_fill_cashflow_chains_without_unlocking(tmp_path: Path) -> None:
    current = tmp_path / "current.csv"
    drill = tmp_path / "drill.csv"
    _write_ledger(
        current,
        [
            _event(
                event_id="flat-1",
                ledger_scope="current_observe_only_paper_runtime_replay",
                event_type="flat_heartbeat",
                event_time="2026-07-01T00:00:00+00:00",
                event_state="held_flat",
                candidate_id="candidate_flat",
                decision_time="2026-07-01T00:00:00+00:00",
                amount_usdt="0",
            )
        ],
    )
    _write_ledger(
        drill,
        [
            _event(event_id="o-1", event_type="order_intent_created", event_state="created", amount_usdt="10000"),
            _event(event_id="r-1", event_type="risk_checked", event_state="approved", amount_usdt="0", risk_approved="True"),
            _event(event_id="f-1", event_type="simulated_fill", event_state="filled", amount_usdt="10000"),
            _event(event_id="fee-1", event_type="fee_cashflow", event_state="settled", amount_usdt="-5"),
            _event(event_id="fund-1", event_type="funding_cashflow", event_state="diagnostic_nearest_visible_funding", amount_usdt="1.2"),
        ],
    )

    report = build_btc_perpetual_paper_runtime_reconciliation_report(
        output_dir=tmp_path / "out",
        current_event_ledger_path=current,
        drill_event_ledger_path=drill,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["summary"]["event_row_count"] == 6
    assert report["summary"]["event_group_count"] == 2
    assert report["summary"]["violation_count"] == 0
    assert report["summary"]["fill_event_count"] == 1
    assert report["summary"]["funding_cashflow_event_count"] == 1
    assert report["summary"]["paper_runtime_reconciliation_passed"] is True
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    safety = json.loads((tmp_path / "out/btc_perpetual_paper_runtime_reconciliation_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["order_endpoint_used"] is False


def test_reconciliation_fails_cashflow_without_fill_and_paper_flag(tmp_path: Path) -> None:
    current = tmp_path / "current.csv"
    drill = tmp_path / "drill.csv"
    _write_ledger(current, [])
    bad = _event(
        event_id="bad-fee",
        event_type="fee_cashflow",
        event_state="settled",
        amount_usdt="5",
        paper_queue_write_allowed="True",
    )
    _write_ledger(drill, [bad])

    report = build_btc_perpetual_paper_runtime_reconciliation_report(
        output_dir=tmp_path / "out",
        current_event_ledger_path=current,
        drill_event_ledger_path=drill,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    codes = {item["violation_code"] for item in report["violations"]}
    assert report["status"] == "incomplete_research_only"
    assert "paper_or_live_flag_true" in codes
    assert "cashflow_without_fill" in codes
    assert "fee_cashflow_positive" in codes
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert (tmp_path / "out/btc_perpetual_paper_runtime_reconciliation_violations.csv").exists()


def _event(
    *,
    event_id: str,
    event_type: str,
    event_state: str,
    amount_usdt: str,
    ledger_scope: str = "historical_bar_replay_execution_drill",
    event_time: str = "2026-06-29T00:00:00+00:00",
    strategy_line: str = "long_short_donchian_top5",
    candidate_id: str = "candidate_a",
    decision_time: str = "2026-06-28T23:59:59.999000+00:00",
    risk_approved: str = "True",
    paper_queue_write_allowed: str = "False",
    live_unlock_allowed: str = "False",
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "ledger_scope": ledger_scope,
        "event_type": event_type,
        "event_time": event_time,
        "event_state": event_state,
        "strategy_line": strategy_line,
        "candidate_id": candidate_id,
        "decision_time": decision_time,
        "side": "long",
        "target_exposure": "1.0",
        "notional_usdt": "10000",
        "quantity_btc": "0.1",
        "execution_price": "100000",
        "mark_price": "100000",
        "index_price": "100010",
        "liquidation_price": "90000",
        "liquidation_buffer_bps": "1000",
        "risk_action": "approve",
        "risk_approved": risk_approved,
        "risk_blockers": "[]",
        "amount_usdt": amount_usdt,
        "diagnostic_drill_only": "True",
        "paper_runtime_gate_eligible": "False",
        "paper_queue_write_allowed": paper_queue_write_allowed,
        "live_unlock_allowed": live_unlock_allowed,
    }


def _write_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "event_id",
        "ledger_scope",
        "event_type",
        "event_time",
        "event_state",
        "strategy_line",
        "candidate_id",
        "decision_time",
        "side",
        "target_exposure",
        "notional_usdt",
        "quantity_btc",
        "execution_price",
        "mark_price",
        "index_price",
        "liquidation_price",
        "liquidation_buffer_bps",
        "risk_action",
        "risk_approved",
        "risk_blockers",
        "amount_usdt",
        "diagnostic_drill_only",
        "paper_runtime_gate_eligible",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
