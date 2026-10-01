from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import quant_crypto.research.btc_paper_risk_circuit_breaker_drill as drill
from quant_crypto.research.btc_paper_risk_circuit_breaker_drill import (
    RISK_SCENARIOS,
    build_btc_paper_risk_circuit_breaker_drill,
)


def test_risk_circuit_breaker_drill_blocks_all_declared_scenarios(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, rows=[_order_row()])

    report = _build(tmp_path, paths)

    assert report["status"] == "complete_research_only"
    assert report["summary"]["scenario_count"] == len(RISK_SCENARIOS)
    assert report["summary"]["order_sample_count"] == 1
    assert report["summary"]["scenario_order_check_count"] == len(RISK_SCENARIOS)
    assert report["summary"]["expected_block_count"] == len(RISK_SCENARIOS)
    assert report["summary"]["unexpected_allow_count"] == 0
    assert {row["scenario_id"] for row in report["rows"]} == {scenario["scenario_id"] for scenario in RISK_SCENARIOS}
    assert all(row["blocked"] is True for row in report["rows"])
    assert all(row["actual_action"] == "block_position_increase" for row in report["rows"])
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["position_increase_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["broker_access_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["real_order_submitted"] is False


def test_risk_circuit_breaker_drill_fails_if_any_scenario_allows_position_increase(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    paths = _write_inputs(tmp_path, rows=[_order_row()])
    original_evaluate = drill.evaluate_circuit_breaker_scenario

    def fake_evaluate(order_row: Mapping[str, Any], scenario: Mapping[str, Any]) -> dict[str, Any]:
        if scenario["scenario_id"] == "kill_switch_engaged":
            return {
                "actual_action": "allow_position_increase",
                "blocked": False,
                "blocker_code": "missing_block",
                "paper_order_intake_allowed": True,
                "position_increase_allowed": True,
                "live_unlock_allowed": False,
            }
        return original_evaluate(order_row, scenario)

    monkeypatch.setattr(drill, "evaluate_circuit_breaker_scenario", fake_evaluate)

    report = _build(tmp_path, paths)

    assert report["status"] == "incomplete_research_only"
    assert report["summary"]["unexpected_allow_count"] == 1
    assert "btc_paper_risk_circuit_breaker_unexpected_position_increase_allowed" in report["blockers"]
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_risk_circuit_breaker_drill_is_fail_closed_without_theoretical_orders(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, rows=[_flat_row()])

    report = _build(tmp_path, paths)

    assert report["status"] == "incomplete_research_only"
    assert report["summary"]["order_sample_count"] == 0
    assert report["summary"]["scenario_order_check_count"] == 0
    assert "btc_paper_risk_circuit_breaker_no_theoretical_orders_to_drill" in report["blockers"]
    assert report["guardrails"]["paper_queue_write_allowed"] is False
    assert report["guardrails"]["live_order_allowed"] is False


def test_risk_circuit_breaker_drill_marks_historical_drill_as_diagnostic_only(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, rows=[_order_row(source_scope="historical_bar_replay_execution_drill")])

    report = _build(tmp_path, paths)

    assert report["summary"]["current_order_count"] == 0
    assert report["summary"]["diagnostic_drill_order_count"] == 1
    assert report["summary"]["diagnostic_drill_only"] is True
    assert "historical_drill_orders_are_diagnostic_not_current_paper_gate_evidence" in report["warnings"]
    assert report["gate"]["paper_order_intake_allowed"] is False


def _build(tmp_path: Path, paths: dict[str, Path]) -> dict[str, Any]:
    return build_btc_paper_risk_circuit_breaker_drill(
        output_dir=tmp_path / "out",
        preflight_rows_path=paths["rows"],
        preflight_report_path=paths["preflight_report"],
        kill_switch_report_path=paths["kill_switch_report"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def _write_inputs(tmp_path: Path, *, rows: list[dict[str, object]]) -> dict[str, Path]:
    paths = {
        "rows": tmp_path / "preflight_rows.csv",
        "preflight_report": tmp_path / "preflight_report.json",
        "kill_switch_report": tmp_path / "kill_switch_report.json",
    }
    _write_csv(paths["rows"], rows)
    paths["preflight_report"].write_text(
        json.dumps(
            {
                "status": "incomplete_research_only",
                "decision": "btc_paper_exchange_rule_preflight_incomplete_fail_closed_no_paper_no_live",
                "guardrails": {"paper_order_intake_allowed": False, "live_unlock_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    paths["kill_switch_report"].write_text(
        json.dumps(
            {
                "status": "fail_closed_research_only",
                "decision": "btc_paper_live_kill_switch_engaged_fail_closed_no_paper_no_live",
                "policy_state": {"kill_switch_engaged": True, "cancel_only_mode": True},
            }
        ),
        encoding="utf-8",
    )
    return paths


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(_order_row().keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _order_row(*, source_scope: str = "current_observe_only_paper_runtime_replay") -> dict[str, object]:
    return {
        "source_scope": source_scope,
        "strategy_line": "long_short_donchian_top5",
        "candidate_id": "candidate",
        "decision_time": "2026-06-07T23:59:59.999000+00:00",
        "side": "short",
        "target_exposure": "-1.0",
        "theoretical_order_created": "True",
        "simulated_fill_created": "True",
        "preflight_status": "blocked_by_kill_switch_cancel_only",
        "order_intent": "market_rebalance",
        "execution_price": "63303.4",
        "notional_usdt": "9995.60686",
        "quantity_btc": "0.1579",
        "requested_contracts": "15.79",
        "rounded_contracts_down": "15.79",
        "min_notional_usdt": "6.33034",
        "liquidation_buffer_bps": "9954.39",
        "failed_check_count": "1",
        "blocker_count": "1",
        "blockers": '["current_kill_switch_cancel_only_blocks_position_increase"]',
        "paper_queue_write_allowed": "False",
        "live_unlock_allowed": "False",
    }


def _flat_row() -> dict[str, object]:
    row = _order_row()
    row.update(
        {
            "side": "flat",
            "target_exposure": "0.0",
            "theoretical_order_created": "False",
            "simulated_fill_created": "False",
            "preflight_status": "no_order_flat_or_heartbeat",
            "order_intent": "",
        }
    )
    return row
