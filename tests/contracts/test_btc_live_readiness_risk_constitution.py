from __future__ import annotations

import json
from pathlib import Path

from scripts.build_btc_live_readiness_risk_constitution import (
    DEFAULT_INCIDENT_REPLAY_DRILL_CONTRACT,
    DEFAULT_PAPER_OMS_SESSION_CONTRACT,
    DEFAULT_PAPER_VALIDATION_REPLAY,
    build_btc_live_readiness_risk_constitution,
)


def test_live_readiness_blocks_current_one_day_forward_observation(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=1)

    payload = build_btc_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        **reports,
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "live_readiness_blocked"
    assert payload["decision"] == "do_not_start_live_trading"
    assert payload["forward_observation"]["observation_days"] == 1
    assert "btc_live_readiness_forward_observation_less_than_30_days" in payload["blockers"]
    assert "btc_live_readiness_missing_paper_oms_session_contract" in payload["blockers"]
    assert "btc_live_readiness_missing_incident_replay_drill_contract" in payload["blockers"]
    assert "btc_live_readiness_missing_paper_validation_replay" in payload["blockers"]
    assert "btc_live_readiness_kill_switch_not_proven" in payload["blockers"]
    assert "btc_live_readiness_order_reconciliation_not_proven" in payload["blockers"]
    assert "btc_live_readiness_replay_not_proven" in payload["blockers"]
    assert payload["gate_checks"]["five_minute_hft_frozen"] is True
    assert payload["gate_checks"]["strategy_gate_validated"] is True
    assert payload["gate_checks"]["four_hour_research_gate_validated"] is True
    assert payload["gate_checks"]["kill_switch_drill_complete"] is False
    assert payload["gate_checks"]["reconciliation_proven"] is False
    assert payload["gate_checks"]["replay_proven"] is False
    assert payload["live_order_allowed"] is False
    assert payload["real_order_submitted"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert (tmp_path / "live.md").exists()


def test_live_readiness_blocks_unsafe_flags_even_when_observation_complete(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=30, forward_status="raw_forward_complete_for_manual_review")
    daily = Path(reports["daily_run"])
    payload = json.loads(daily.read_text(encoding="utf-8"))
    payload["status"] = "PASS"
    payload["steps"]["data_refresh"]["status"] = "verified"
    daily.write_text(json.dumps(payload), encoding="utf-8")
    unsafe = Path(reports["strategy_gate"])
    strategy = json.loads(unsafe.read_text(encoding="utf-8"))
    strategy["guardrails"]["live_order_allowed"] = True
    unsafe.write_text(json.dumps(strategy), encoding="utf-8")

    payload = build_btc_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        max_principal_usd=100.0,
        manual_reviewer="manual-review",
        **reports,
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "live_readiness_blocked"
    assert payload["gate_checks"]["no_unsafe_live_flags"] is False
    assert any("live_order_allowed=true" in item for item in payload["unsafe_flags"])
    assert any(item.startswith("btc_live_readiness_unsafe_flag:") for item in payload["blockers"])
    assert payload["live_order_allowed"] is False


def test_live_readiness_reads_operational_evidence_without_unlocking_live(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=30, forward_status="raw_forward_complete_for_manual_review")
    _mark_daily_pass(Path(reports["daily_run"]))
    _write_operational_evidence(tmp_path)

    payload = build_btc_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        max_principal_usd=100.0,
        manual_reviewer="manual-review",
        **reports,
        generated_at="2026-06-29T00:00:00Z",
    )

    assert payload["status"] == "live_readiness_blocked"
    assert payload["gate_checks"]["kill_switch_drill_complete"] is True
    assert payload["gate_checks"]["reconciliation_proven"] is True
    assert payload["gate_checks"]["replay_proven"] is True
    assert payload["operational_evidence"]["kill_switch_drill"]["complete"] is True
    assert payload["operational_evidence"]["reconciliation"]["complete"] is True
    assert payload["operational_evidence"]["replay"]["complete"] is True
    assert "btc_live_readiness_kill_switch_not_proven" not in payload["blockers"]
    assert "btc_live_readiness_order_reconciliation_not_proven" not in payload["blockers"]
    assert "btc_live_readiness_replay_not_proven" not in payload["blockers"]
    assert "btc_live_readiness_exchange_credentials_not_configured" in payload["blockers"]
    assert "btc_live_readiness_shadow_live_not_completed" in payload["blockers"]
    assert payload["live_order_allowed"] is False
    assert payload["guardrails"]["private_endpoint_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False


def test_live_readiness_reads_latest_daily_artifact_not_stale_blocked_content(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=4)
    daily = Path(reports["daily_run"])
    daily.write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "generated_at": "2026-06-24T00:30:00Z",
                "steps": {"data_refresh": {"status": "rejected"}},
                "blockers": ["old_capture_failed"],
            }
        ),
        encoding="utf-8",
    )
    daily.write_text(
        json.dumps(
            {
                "status": "PASS",
                "generated_at": "2026-06-28T00:32:47Z",
                "steps": {"data_refresh": {"status": "verified"}},
                "blockers": [],
                "guardrails": {
                    "public_rest_only": True,
                    "simulated_only": True,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = build_btc_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        **reports,
        generated_at="2026-06-28T01:00:00Z",
    )

    assert payload["daily_run"]["status"] == "PASS"
    assert payload["daily_run"]["data_refresh_status"] == "verified"
    assert "btc_live_readiness_daily_forward_pipeline_not_pass" not in payload["blockers"]
    assert "btc_live_readiness_daily_data_refresh_not_verified" not in payload["blockers"]
    assert payload["source_report_details"]["daily_run"]["generated_at"] == "2026-06-28T00:32:47Z"
    assert payload["source_report_details"]["daily_run"]["status"] == "PASS"
    assert payload["gate_checks"]["daily_pipeline_pass"] is True
    assert payload["status"] == "live_readiness_blocked"
    assert "btc_live_readiness_forward_observation_less_than_30_days" in payload["blockers"]
    assert payload["live_order_allowed"] is False
    assert payload["real_order_submitted"] is False


def _mark_daily_pass(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "PASS"
    payload["steps"]["data_refresh"]["status"] = "verified"
    payload["blockers"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_operational_evidence(tmp_path: Path) -> None:
    paper_oms = tmp_path / DEFAULT_PAPER_OMS_SESSION_CONTRACT
    incident_drill = tmp_path / DEFAULT_INCIDENT_REPLAY_DRILL_CONTRACT
    replay = tmp_path / DEFAULT_PAPER_VALIDATION_REPLAY
    paper_oms.parent.mkdir(parents=True, exist_ok=True)
    incident_drill.parent.mkdir(parents=True, exist_ok=True)
    replay.parent.mkdir(parents=True, exist_ok=True)
    paper_oms.write_text(
        json.dumps(
            {
                "artifact_hash": "a" * 64,
                "status": "complete",
                "decision": "paper_oms_session_reconciled",
                "blockers": [],
                "missing_fill_client_order_ids": [],
                "unknown_fill_client_order_ids": [],
                "ledger_hash": "b" * 64,
                "order_count": 1,
                "fill_count": 1,
                "allows_live_orders": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "real_order_submitted": False,
            }
        ),
        encoding="utf-8",
    )
    incident_drill.write_text(
        json.dumps(
            {
                "artifact_hash": "c" * 64,
                "status": "complete",
                "decision": "incident_replay_drill_complete",
                "blockers": [],
                "required_scenarios": ["data_outage", "funding_gap", "ledger_mismatch", "order_reject"],
                "allows_live_orders": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "real_order_submitted": False,
            }
        ),
        encoding="utf-8",
    )
    replay.write_text(
        json.dumps(
            {
                "artifact_hash": "d" * 64,
                "status": "replay_pass",
                "decision": "replay_pass",
                "blockers": [],
                "metadata": {"current_realtime_data_accessed": False},
            }
        ),
        encoding="utf-8",
    )


def _write_reports(tmp_path: Path, *, observation_days: int, forward_status: str = "raw_forward_observing") -> dict[str, Path]:
    forward_evaluation = tmp_path / "forward_eval.json"
    daily_run = tmp_path / "daily.json"
    strategy_gate = tmp_path / "strategy.json"
    four_hour_gate = tmp_path / "4h.json"
    intraday = tmp_path / "intraday.json"
    freeze = tmp_path / "freeze.json"
    forward_state = tmp_path / "state.json"
    forward_evaluation.write_text(
        json.dumps(
            {
                "status": forward_status,
                "minimum_complete_days": 30,
                "metrics": {"observation_days": observation_days},
                "guardrails": {"live_order_allowed": False, "private_endpoint_used": False, "order_endpoint_used": False},
            }
        ),
        encoding="utf-8",
    )
    daily_run.write_text(
        json.dumps({"status": "BLOCKED", "steps": {"data_refresh": {"status": "rejected"}}, "blockers": ["capture_failed"]}),
        encoding="utf-8",
    )
    strategy_gate.write_text(
        json.dumps({"status": "strategy_backtest_validated", "guardrails": {"live_order_allowed": False, "private_endpoint_used": False, "order_endpoint_used": False}}),
        encoding="utf-8",
    )
    four_hour_gate.write_text(
        json.dumps({"status": "research_validation_passed_manual_review_required", "guardrails": {"live_order_allowed": False, "private_endpoint_used": False, "order_endpoint_used": False}}),
        encoding="utf-8",
    )
    intraday.write_text(
        json.dumps({"status": "research_only_intraday_trend_v1_complete", "guardrails": {"live_order_allowed": False, "private_endpoint_used": False, "order_endpoint_used": False}}),
        encoding="utf-8",
    )
    freeze.write_text(
        json.dumps({"status": "frozen_rejected_as_high_frequency", "guardrails": {"parameter_tuning_allowed": False}}),
        encoding="utf-8",
    )
    forward_state.write_text(json.dumps({"days_completed": observation_days, "live_order_allowed": False}), encoding="utf-8")
    return {
        "forward_evaluation": forward_evaluation,
        "daily_run": daily_run,
        "strategy_gate": strategy_gate,
        "four_hour_gate": four_hour_gate,
        "intraday_report": intraday,
        "five_minute_freeze": freeze,
        "forward_state": forward_state,
    }
