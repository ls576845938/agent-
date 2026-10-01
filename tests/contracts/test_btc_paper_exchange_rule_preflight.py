from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_paper_exchange_rule_preflight import build_btc_paper_exchange_rule_preflight


def test_preflight_detects_unrounded_okx_contract_quantity(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        current_rows=[_flat_row()],
        drill_rows=[_order_row(quantity_btc="-0.157969398168", target_exposure="-1.0")],
        kill_switch_engaged=False,
        manual_approval_recorded=True,
        current_replay_status="complete_research_only",
    )

    report = _build(tmp_path, paths)

    assert report["summary"]["current_order_count"] == 0
    assert report["summary"]["current_flat_no_order_healthy"] is True
    assert report["summary"]["current_order_sample_available"] is False
    assert report["summary"]["current_order_sample_status"] == "current_flat_heartbeat_waiting_for_order_sample"
    assert (
        report["summary"]["current_order_sample_pending_reason"]
        == "current_observe_only_signal_flat_waiting_for_exchange_filter_sample"
    )
    assert "btc_paper_exchange_rule_no_current_theoretical_orders_to_validate" in report["blockers"]
    assert report["summary"]["drill_order_count"] == 1
    assert report["summary"]["quantity_lot_violation_count"] == 1
    order_row = next(row for row in report["rows"] if row["theoretical_order_created"])
    assert order_row["preflight_status"] == "fail_exchange_preflight"
    assert "quantity_lot_aligned" in order_row["blockers"]
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_rounded_order_can_pass_filters_but_runtime_evidence_still_blocks(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        current_rows=[_order_row(quantity_btc="-0.15", target_exposure="-1.0")],
        drill_rows=[],
        kill_switch_engaged=False,
        manual_approval_recorded=True,
        current_replay_status="complete_research_only",
    )

    report = _build(tmp_path, paths)

    order_row = next(row for row in report["rows"] if row["theoretical_order_created"])
    assert order_row["preflight_status"] == "pass_exchange_filters"
    assert report["summary"]["current_order_sample_available"] is True
    assert report["summary"]["current_order_sample_status"] == "current_order_sample_present"
    assert report["summary"]["current_flat_no_order_healthy"] is False
    assert report["summary"]["order_filter_violation_count"] == 0
    assert "btc_paper_exchange_rule_account_mode_not_verified" in report["blockers"]
    assert "btc_paper_exchange_rule_margin_mode_not_verified" in report["blockers"]
    assert report["status"] == "incomplete_research_only"
    assert report["guardrails"]["order_endpoint_used"] is False


def test_verified_public_server_time_removes_server_time_offset_blocker_only(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        current_rows=[_order_row(quantity_btc="-0.15", target_exposure="-1.0")],
        drill_rows=[],
        kill_switch_engaged=False,
        manual_approval_recorded=True,
        current_replay_status="complete_research_only",
        server_time_verified=True,
    )

    report = _build(tmp_path, paths)

    assert report["server_time_preflight"]["server_time_offset_verified"] is True
    assert "btc_paper_exchange_rule_server_time_offset_not_verified" not in report["blockers"]
    assert "btc_paper_exchange_rule_account_mode_not_verified" in report["blockers"]
    assert "btc_paper_exchange_rule_margin_mode_not_verified" in report["blockers"]
    assert report["account_runtime_evidence"]["server_time_offset_verified"] is True
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_verified_account_runtime_attestation_removes_account_runtime_blockers_only(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        current_rows=[_order_row(quantity_btc="-0.15", target_exposure="-1.0")],
        drill_rows=[],
        kill_switch_engaged=False,
        manual_approval_recorded=True,
        current_replay_status="complete_research_only",
        account_runtime_verified=True,
    )

    report = _build(tmp_path, paths)

    assert report["account_runtime_attestation"]["account_mode_verified"] is True
    assert report["account_runtime_evidence"]["account_mode_verified"] is True
    assert report["account_runtime_evidence"]["position_mode_verified"] is True
    assert report["account_runtime_evidence"]["margin_mode_verified"] is True
    assert report["account_runtime_evidence"]["rate_limit_budget_verified"] is True
    assert report["account_runtime_evidence"]["credential_permissions_verified"] is True
    assert report["account_runtime_evidence"]["manual_approval_recorded"] is True
    assert "btc_paper_exchange_rule_account_mode_not_verified" not in report["blockers"]
    assert "btc_paper_exchange_rule_position_mode_not_verified" not in report["blockers"]
    assert "btc_paper_exchange_rule_margin_mode_not_verified" not in report["blockers"]
    assert "btc_paper_exchange_rule_rate_limit_budget_not_verified" not in report["blockers"]
    assert "btc_paper_exchange_rule_server_time_offset_not_verified" in report["blockers"]
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_account_runtime_attestation_true_private_or_order_flags_block_preflight(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        current_rows=[_order_row(quantity_btc="-0.15", target_exposure="-1.0")],
        drill_rows=[],
        kill_switch_engaged=False,
        manual_approval_recorded=True,
        current_replay_status="complete_research_only",
        account_runtime_verified=True,
    )
    account = json.loads(paths["account_runtime"].read_text(encoding="utf-8"))
    account["private_endpoint_used"] = True
    account["order_endpoint_used"] = True
    paths["account_runtime"].write_text(json.dumps(account), encoding="utf-8")

    report = _build(tmp_path, paths)

    assert "btc_paper_exchange_rule_account_runtime_private_endpoint_used" in report["blockers"]
    assert "btc_paper_exchange_rule_account_runtime_order_endpoint_used" in report["blockers"]
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_current_kill_switch_blocks_position_increase_even_if_exchange_filters_pass(tmp_path: Path) -> None:
    paths = _write_sources(
        tmp_path,
        current_rows=[_order_row(quantity_btc="-0.15", target_exposure="-1.0")],
        drill_rows=[],
        kill_switch_engaged=True,
        manual_approval_recorded=False,
        current_replay_status="complete_research_only",
    )

    report = _build(tmp_path, paths)

    order_row = next(row for row in report["rows"] if row["theoretical_order_created"])
    assert "current_kill_switch_cancel_only_blocks_position_increase" in order_row["blockers"]
    assert order_row["preflight_status"] == "blocked_by_kill_switch_cancel_only"
    assert report["summary"]["order_filter_violation_count"] == 0
    assert report["summary"]["kill_switch_reject_count"] == 1
    assert "btc_paper_exchange_rule_kill_switch_currently_engaged" in report["blockers"]
    assert report["gate"]["position_increase_allowed"] is False


def _build(tmp_path: Path, paths: dict[str, Path]) -> dict[str, object]:
    return build_btc_paper_exchange_rule_preflight(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        exchange_info_path=paths["exchange_info"],
        current_rows_path=paths["current_rows"],
        drill_rows_path=paths["drill_rows"],
        current_replay_report_path=paths["current_replay"],
        drill_report_path=paths["drill_report"],
        kill_switch_report_path=paths["kill_switch"],
        server_time_preflight_report_path=paths["server_time"],
        account_runtime_attestation_report_path=paths["account_runtime"],
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def _write_sources(
    tmp_path: Path,
    *,
    current_rows: list[dict[str, object]],
    drill_rows: list[dict[str, object]],
    kill_switch_engaged: bool,
    manual_approval_recorded: bool,
    current_replay_status: str,
    server_time_verified: bool = False,
    account_runtime_verified: bool = False,
) -> dict[str, Path]:
    paths = {
        "exchange_info": tmp_path / "exchange_info.json",
        "current_rows": tmp_path / "current_rows.csv",
        "drill_rows": tmp_path / "drill_rows.csv",
        "current_replay": tmp_path / "current_replay.json",
        "drill_report": tmp_path / "drill_report.json",
        "kill_switch": tmp_path / "kill_switch.json",
        "server_time": tmp_path / "server_time.json",
        "account_runtime": tmp_path / "account_runtime.json",
    }
    paths["exchange_info"].write_text(json.dumps(_exchange_info()), encoding="utf-8")
    _write_csv(paths["current_rows"], current_rows)
    _write_csv(paths["drill_rows"], drill_rows)
    current_theoretical_order_count = sum(1 for row in current_rows if str(row.get("theoretical_order_created")) == "True")
    current_flat_heartbeat_healthy = bool(current_rows) and current_theoretical_order_count == 0
    paths["current_replay"].write_text(
        json.dumps(
            {
                "status": current_replay_status,
                "summary": {
                    "theoretical_order_count": current_theoretical_order_count,
                    "simulated_fill_count": current_theoretical_order_count,
                    "current_flat_heartbeat_healthy": current_flat_heartbeat_healthy,
                    "trade_execution_evidence_available": current_theoretical_order_count > 0,
                    "trade_execution_evidence_pending_reason": (
                        "waiting_for_current_gate_eligible_non_flat_fill"
                        if current_flat_heartbeat_healthy
                        else None
                    ),
                    "paper_runtime_health_status": (
                        "current_flat_heartbeat_healthy_waiting_for_trade_sample"
                        if current_flat_heartbeat_healthy
                        else "trade_execution_sample_present"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    paths["drill_report"].write_text(
        json.dumps({"status": "complete_research_only", "summary": {"paper_runtime_gate_evidence": False}}),
        encoding="utf-8",
    )
    paths["kill_switch"].write_text(
        json.dumps(
            {
                "status": "fail_closed_research_only" if kill_switch_engaged else "complete_research_only",
                "policy_state": {
                    "kill_switch_engaged": kill_switch_engaged,
                    "cancel_only_mode": kill_switch_engaged,
                    "manual_approval_recorded": manual_approval_recorded,
                    "paper_order_intake_allowed": False,
                    "position_increase_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    paths["server_time"].write_text(json.dumps(_server_time_report(verified=server_time_verified)), encoding="utf-8")
    paths["account_runtime"].write_text(
        json.dumps(_account_runtime_report(verified=account_runtime_verified)),
        encoding="utf-8",
    )
    return paths


def _server_time_report(*, verified: bool) -> dict[str, object]:
    return {
        "status": "verified_research_only" if verified else "dry_run",
        "decision": (
            "okx_server_time_offset_verified_research_only_no_paper_no_live"
            if verified
            else "okx_server_time_offset_incomplete_fail_closed_no_paper_no_live"
        ),
        "public_rest_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "server_time_offset_verified": verified,
        "server_time_metrics": {"offset_ms": 10.0, "abs_offset_ms": 10.0, "round_trip_ms": 80.0},
        "validation": {"max_abs_offset_ms": 2000.0, "max_round_trip_ms": 5000.0},
        "blockers": [] if verified else ["btc_okx_server_time_network_capture_not_executed"],
    }


def _account_runtime_report(*, verified: bool) -> dict[str, object]:
    return {
        "status": "verified_research_only" if verified else "blocked_fail_closed_research_only",
        "decision": (
            "btc_paper_account_runtime_attestation_verified_manual_review_only_no_auto_paper_no_live"
            if verified
            else "btc_paper_account_runtime_attestation_missing_or_incomplete_fail_closed_no_paper_no_live"
        ),
        "account_mode_verified": verified,
        "position_mode_verified": verified,
        "margin_mode_verified": verified,
        "rate_limit_budget_verified": verified,
        "credential_permissions_verified": verified,
        "manual_approval_recorded": verified,
        "attestation_current": verified,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "blockers": []
        if verified
        else [
            "btc_paper_account_runtime_account_mode_not_verified",
            "btc_paper_account_runtime_position_mode_not_verified",
            "btc_paper_account_runtime_margin_mode_not_verified",
            "btc_paper_account_runtime_rate_limit_budget_not_verified",
            "btc_paper_account_runtime_credential_permissions_not_verified",
            "btc_paper_account_runtime_manual_approval_not_recorded",
        ],
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(_order_row().keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _flat_row() -> dict[str, object]:
    row = _order_row(quantity_btc="", target_exposure="0.0")
    row.update(
        {
            "side": "flat",
            "order_intent": "none_flat",
            "theoretical_order_created": "False",
            "simulated_fill_created": "False",
            "notional_usdt": "",
            "execution_price": "",
            "mark_price": "",
            "index_price": "",
            "fee_amount_usdt": "0.0",
            "funding_rate": "",
            "liquidation_buffer_bps": "",
        }
    )
    return row


def _order_row(*, quantity_btc: str = "-0.15", target_exposure: str = "-1.0") -> dict[str, object]:
    return {
        "strategy_line": "long_short_donchian_top5",
        "candidate_id": "candidate",
        "decision_time": "2026-06-07T23:59:59.999000+00:00",
        "side": "short",
        "target_exposure": target_exposure,
        "order_intent": "market_rebalance",
        "theoretical_order_created": "True",
        "simulated_fill_created": "True",
        "fill_time": "2026-06-08T00:00:00+00:00",
        "execution_price": "63303.4",
        "mark_price": "63303.4",
        "index_price": "63332.8",
        "notional_usdt": "9495.51",
        "quantity_btc": quantity_btc,
        "fee_amount_usdt": "5.0",
        "funding_rate": "0.00001",
        "funding_amount_usdt": "0.1",
        "risk_approved": "True",
        "risk_action": "approve",
        "risk_blockers": "[]",
        "liquidation_price": "126290.2",
        "liquidation_buffer_bps": "9000",
        "diagnostic_drill_only": "False",
        "paper_runtime_gate_eligible": "False",
        "ignored_current_execution_evidence_blockers": "[]",
        "source_line": "long_short_top5",
        "source_decision_time": "2026-06-07T23:59:59.999000+00:00",
        "source_rank": "1",
        "source_model_boundary_flag": "False",
        "source_execution_replay_required_before_paper": "False",
        "paper_queue_write_allowed": "False",
        "live_unlock_allowed": "False",
    }


def _exchange_info() -> dict[str, object]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "api_key_used": False,
        "min_notional_estimate": 5.0,
        "raw_symbol_info": {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "state": "live",
            "ctType": "linear",
            "ctVal": "0.01",
            "settleCcy": "USDT",
            "tickSz": "0.1",
            "lotSz": "0.01",
            "minSz": "0.01",
            "maxMktSz": "35000",
            "lever": "100",
        },
    }
