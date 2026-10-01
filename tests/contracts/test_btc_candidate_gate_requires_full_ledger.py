from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_candidate_gate_audit import build_btc_candidate_gate_audit


SCHEMA = Path("schemas/btc_candidate_gate_audit_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")


def test_btc_candidate_gate_audit_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_candidate_gate_requires_full_perp_ledger_components() -> None:
    payload = build_btc_candidate_gate_audit(generated_at="2026-05-19T00:00:00Z")
    required = payload["candidate_gate_required_artifacts"]

    assert required["canonical_backtest_report"] is True
    assert required["fills"] is True
    assert required["ledger_pnl"] is True
    assert required["fee_pnl"] is True
    assert required["slippage_pnl"] is True
    assert required["funding_pnl"] is True
    assert required["tail_dependency_report"] is True
    assert payload["candidate_passed_internal_gate"] == 0
    assert payload["paper_review_pending_allowed"] is False
    assert payload["candidate_repair_plan"]["next_required_action"] == "repair_btc_candidate_metric_gate"
    stages = {item["name"]: item for item in payload["candidate_repair_plan"]["stages"]}
    assert stages["perpetual_data_cost_evidence"]["status"] == "complete"
    assert stages["internal_metric_gate"]["status"] == "blocked"
    assert "event_profit_factor" in stages["internal_metric_gate"]["blockers"]
    assert "walk_forward_pass_rate" in stages["internal_metric_gate"]["blockers"]
    assert "regime_pass_rate" in stages["internal_metric_gate"]["blockers"]
    assert payload["best_available_candidate"]["strategy_id"]
    assert payload["best_available_candidate"]["passed_metric_count"] >= 0
    assert "btc_candidate_gate_perpetual_evidence_not_ready" not in payload["blockers"]
    assert "btc_candidate_gate_event_pf_failed" in payload["blockers"]


def test_btc_candidate_gate_blocks_pf_signal_and_target_active_shortcuts() -> None:
    payload = build_btc_candidate_gate_audit(generated_at="2026-05-19T00:00:00Z")
    checks = payload["candidate_gate_metric_checks"]

    assert checks["ordinary_pf_diagnostic_only"] is True
    assert checks["signal_equity_diagnostic_only"] is True
    assert checks["target_active_return_diagnostic_only"] is True
    assert checks["event_pf_pass"] is False
    assert checks["walk_forward_pass"] is False
    assert checks["regime_pass"] is False
    assert payload["candidate_gate_thresholds"]["event_profit_factor"] == 1.15
    assert payload["candidate_gate_thresholds"]["walk_forward_pass_rate"] == 0.8
    assert payload["candidate_gate_thresholds"]["regime_pass_rate"] == 0.75
    assert payload["metric_failures"] == [
        "event_profit_factor",
        "walk_forward_pass_rate",
        "regime_pass_rate",
    ]


def test_btc_candidate_gate_can_represent_future_passing_candidate_without_unlocking_live(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/pass_candidate"
    _write_passing_candidate_run(run_dir)
    _write_passing_perpetual_evidence(tmp_path)

    payload = build_btc_candidate_gate_audit(
        repo_root=tmp_path,
        source_run_dir=run_dir,
        generated_at="2026-05-19T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "pass"
    assert payload["candidate_passed_internal_gate"] == 1
    assert payload["paper_review_pending_allowed"] is True
    assert payload["paper_queue_status"] == "pending_review"
    assert payload["live_status"] == "frozen"
    assert payload["metric_failures"] == []
    assert payload["candidate_repair_plan"]["next_required_action"] == "none"
    stages = {item["name"]: item for item in payload["candidate_repair_plan"]["stages"]}
    assert stages["perpetual_data_cost_evidence"]["status"] == "complete"
    assert stages["internal_metric_gate"]["status"] == "complete"
    assert stages["paper_review_queue"]["status"] == "ready"
    assert payload["best_available_candidate"]["strategy_id"] == "btc_future_candidate_v1"
    assert payload["blockers"] == []


def test_btc_candidate_gate_ignores_diagnostic_only_market_microstructure_gaps(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/pass_candidate"
    _write_passing_candidate_run(run_dir)
    _write_passing_perpetual_evidence(tmp_path)
    diagnostic_code = "btc_open_interest_history_not_verified_diagnostic_partial"
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {"perpetual_evidence_ready": True, "blockers": [diagnostic_code], "diagnostic_warnings": [diagnostic_code]},
    )
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {"status": "pass", "blockers": [diagnostic_code], "diagnostic_warnings": [diagnostic_code]},
    )

    payload = build_btc_candidate_gate_audit(
        repo_root=tmp_path,
        source_run_dir=run_dir,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["status"] == "pass"
    assert payload["blockers"] == []
    assert diagnostic_code in payload["diagnostic_warnings"]


def test_btc_candidate_gate_schema_rejects_pass_without_required_artifact_checks(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/pass_candidate"
    _write_passing_candidate_run(run_dir)
    _write_passing_perpetual_evidence(tmp_path)
    payload = build_btc_candidate_gate_audit(
        repo_root=tmp_path,
        source_run_dir=run_dir,
        generated_at="2026-05-19T00:00:00Z",
    )
    payload["candidate_gate_required_artifacts"]["funding_pnl"] = False
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_passing_candidate_run(run_dir: Path) -> None:
    _write_json(
        run_dir / "canonical_backtest_report.json",
        {
            "strategy_id": "btc_future_candidate_v1",
            "metrics": {"fill_count": 12},
            "no_lookahead_status": {"status": "pass"},
            "gate_decision": {
                "checks": {
                    "event_profit_factor": True,
                    "walk_forward_pass_rate": True,
                    "regime_pass_rate": True,
                    "cost_stress_base": True,
                    "cost_stress_harsh": True,
                    "signal_equity_diagnostic_only": True,
                }
            },
        },
    )
    _write_json(
        run_dir / "manifests/run_btc_compression_expansion_breakout_v1_base.json",
        {
            "evidence": {
                "ledger_artifact": {
                    "pnl": {"source": "ledger_fills", "net_pnl": 100.0},
                    "fills": {"effective_fill_count": 12},
                    "fees": {"total_fees": 5.0},
                }
            },
            "cost_model": {"realized_commission": 5.0, "realized_slippage_cost": 1.0},
        },
    )
    for name in ("cost_stress_report.json", "walk_forward_report.json", "regime_report.json", "pbo_dsr_report.json"):
        _write_json(run_dir / name, {"status": "pass"})
    _write_json(run_dir / "promotion_decision.json", {"candidate_passed_internal_gate_count": 1})


def _write_passing_perpetual_evidence(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_data_status_report.json",
        {"instrument": {"market_type": "usds_m_perpetual", "contract_type": "PERPETUAL"}, "blockers": []},
    )
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {"perpetual_evidence_ready": True, "blockers": []},
    )
    _write_json(root / "artifacts/btc_cost_model/latest/btc_cost_model_report.json", {"status": "pass", "blockers": []})
    _write_json(
        root / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json",
        {"funding_payment_in_ledger": True, "blockers": []},
    )
    _write_json(root / "artifacts/btc_tail_dependency/latest/tail_dependency_report.json", {"tail_dependency_pass": True, "blockers": []})


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
