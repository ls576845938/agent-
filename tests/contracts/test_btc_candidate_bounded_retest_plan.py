from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_candidate_bounded_retest_plan import build_btc_candidate_bounded_retest_plan


SCHEMA = Path("schemas/btc_candidate_bounded_retest_plan.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json")


def test_btc_candidate_bounded_retest_plan_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_candidate_bounded_retest_plan_is_ready_for_bounded_retest() -> None:
    payload = build_btc_candidate_bounded_retest_plan(generated_at="2026-05-23T00:00:00Z")

    assert payload["status"] == "ready_for_bounded_retest"
    assert payload["retest_allowed"] is True
    assert payload["bounded_parameter_search_allowed"] is True
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["candidate"]["strategy_id"] == "btc_perp_dual_trend_v4_eventpf_wf"
    assert payload["metric_repair_context"]["failed_metrics"] == [
        "event_profit_factor",
        "walk_forward_pass_rate",
    ]
    assert payload["acceptance_criteria"]["event_profit_factor_min"] == pytest.approx(1.15)
    assert payload["acceptance_criteria"]["walk_forward_pass_rate_min"] == pytest.approx(0.8)
    assert payload["test_scope"]["focus_failed_folds"] == [3, 4]
    assert payload["test_scope"]["folds_required_for_rerun"] == [1, 2, 3, 4]
    assert "exit_hysteresis_only" in payload["test_scope"]["allowed_rule_changes"]
    assert "long_only" in payload["test_scope"]["allowed_rule_changes"]
    assert "broad_short_reintroduction" in payload["test_scope"]["disallowed_rule_changes"]
    assert "ordinary_profit_factor_primary_objective" in payload["test_scope"]["disallowed_rule_changes"]
    assert payload["guardrails"]["report_only"] is True
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["ordinary_profit_factor_diagnostic_only"] is True
    execution = payload["execution_plan"]
    assert execution["status"] == "ready"
    assert execution["readiness_check_command"] == "make check-btc-candidate-bounded-retest-readiness"
    assert execution["retest_command"] == execution["retest_command_template"]
    assert execution["retest_command_template"].startswith(
        "python3 scripts/research/run_btc_eventpf_wf_stabilization.py"
    )
    assert execution["post_retest_validation_command"] == "make validate-btc-evidence"
    assert execution["runner"]["path"] == "scripts/research/run_btc_eventpf_wf_stabilization.py"
    assert execution["runner"]["exists"] is True
    assert execution["runner"]["supports_run_id_arg"] is True
    assert execution["runner"]["supports_output_root_arg"] is True
    assert execution["runner"]["broker_calls_allowed"] is False
    assert execution["runner"]["paper_or_live_unlock_allowed"] is False
    manifest = execution["manifest_contract"]
    assert manifest["params_field"] == "strategy_params"
    assert manifest["existing_event_manifest_contract_ok"] is True
    assert all(manifest["existing_event_manifest_fields_present"].values())
    assert (
        "artifacts/btc_canonical/BTC_CANDIDATE_RETEST_YYYYMMDDTHHMMSSZ/"
        "manifests/run_btc_perp_dual_trend_v4_eventpf_wf_base.json"
    ) in execution["required_output_artifacts"]
    checks = {item["name"]: item for item in execution["preflight_checks"]}
    assert checks["perpetual_data_cost_evidence_complete"]["status"] == "complete"
    assert checks["bounded_retest_runner_contract"]["status"] == "complete"
    assert checks["event_backtest_manifest_contract"]["status"] == "complete"
    assert payload["blockers"] == []


def test_btc_candidate_bounded_retest_plan_can_be_ready_after_data_cost(tmp_path: Path) -> None:
    _write_metric_repair(
        tmp_path,
        status="needs_metric_repair",
        failed_metrics=["event_profit_factor", "walk_forward_pass_rate"],
        data_cost_blockers=[],
    )
    payload = build_btc_candidate_bounded_retest_plan(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "ready_for_bounded_retest"
    assert payload["retest_allowed"] is True
    assert payload["bounded_parameter_search_allowed"] is True
    assert payload["guardrails"]["strategy_retest_allowed"] is True
    assert payload["execution_plan"]["status"] == "blocked"
    assert payload["execution_plan"]["retest_command"] == ""
    assert payload["promotion_allowed"] is False
    assert payload["blockers"] == []


def test_btc_candidate_bounded_retest_plan_emits_command_when_runner_and_manifest_are_ready(tmp_path: Path) -> None:
    _write_metric_repair(
        tmp_path,
        status="needs_metric_repair",
        failed_metrics=["event_profit_factor", "walk_forward_pass_rate"],
        data_cost_blockers=[],
    )
    _write_retest_runner_contract(tmp_path)
    _write_existing_event_manifest_contract(tmp_path)

    payload = build_btc_candidate_bounded_retest_plan(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "ready_for_bounded_retest"
    assert payload["execution_plan"]["status"] == "ready"
    assert payload["execution_plan"]["retest_command"] == payload["execution_plan"]["retest_command_template"]
    checks = {item["name"]: item for item in payload["execution_plan"]["preflight_checks"]}
    assert {item["status"] for item in checks.values()} == {"complete"}


def test_btc_candidate_bounded_retest_plan_is_not_required_after_metric_pass(tmp_path: Path) -> None:
    _write_metric_repair(
        tmp_path,
        status="candidate_metric_gate_passed",
        failed_metrics=[],
        data_cost_blockers=[],
    )
    payload = build_btc_candidate_bounded_retest_plan(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "not_required_candidate_metric_gate_passed"
    assert payload["retest_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["execution_plan"]["status"] == "not_required"
    assert payload["execution_plan"]["retest_command"] == ""
    assert payload["blockers"] == []


def test_btc_candidate_bounded_retest_schema_rejects_promotion_unlock() -> None:
    payload = build_btc_candidate_bounded_retest_plan(generated_at="2026-05-23T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["promotion_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_candidate_bounded_retest_schema_rejects_paper_live_unlock() -> None:
    payload = build_btc_candidate_bounded_retest_plan(generated_at="2026-05-23T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_candidate_bounded_retest_make_target_is_read_only() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "check-btc-candidate-bounded-retest-readiness" in makefile
    body = _target_body(makefile, "check-btc-candidate-bounded-retest-readiness")
    assert "$(PYTHON) scripts/build_btc_candidate_bounded_retest_plan.py" in body
    assert "$(PYTHON) -m pytest tests/contracts/test_btc_candidate_bounded_retest_plan.py -q" in body
    assert "run_btc_eventpf_wf_stabilization.py" not in body
    assert "run_btc_paper_validation.py" not in body


def _write_metric_repair(
    root: Path,
    *,
    status: str,
    failed_metrics: list[str],
    data_cost_blockers: list[str],
) -> None:
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json",
        {
            "schema_version": "btc_candidate_metric_repair_report_v1",
            "status": status,
            "best_candidate": {
                "strategy_id": "btc_candidate_fixture",
                "source_run_dir": "artifacts/btc_candidate_validation/fixture",
                "status": "candidate_gate_failed" if failed_metrics else "candidate_passed_internal_gate",
                "failed_metrics": failed_metrics,
                "metrics": {
                    "event_profit_factor": 1.1 if failed_metrics else 1.2,
                    "walk_forward_pass_rate": 0.5 if failed_metrics else 1.0,
                    "regime_pass_rate": 1.0,
                    "profit_factor": 1.4,
                    "dsr": 1.0,
                    "pbo": 0.4,
                    "max_drawdown": -4.0,
                    "trade_count": 20,
                    "fill_count": 50,
                },
                "thresholds": {
                    "event_profit_factor": 1.15,
                    "walk_forward_pass_rate": 0.8,
                    "regime_pass_rate": 0.75,
                },
            },
            "gate_thresholds": {
                "event_profit_factor": 1.15,
                "walk_forward_pass_rate": 0.8,
                "regime_pass_rate": 0.75,
                "cost_stress_required": True,
            },
            "failed_metrics": failed_metrics,
            "fold_failure_diagnostics": {
                "failed_folds": [3, 4] if failed_metrics else [],
            },
            "ablation_diagnostics": {
                "adopted_exit_rules": ["exit_hysteresis_only"],
                "adopted_side_rules": ["long_only"],
                "rejected_exit_rules": ["baseline_v3"],
                "rejected_side_rules": ["broad_short_reintroduction"],
            },
            "recommended_repair_actions": [
                {
                    "name": "complete_perpetual_data_cost_evidence",
                    "priority": 1,
                    "status": "complete" if not data_cost_blockers else "blocked",
                    "inputs": data_cost_blockers,
                }
            ],
            "blockers": [
                f"btc_candidate_metric_repair_{metric}_failed" for metric in failed_metrics
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_retest_runner_contract(root: Path) -> None:
    path = root / "scripts/research/run_btc_eventpf_wf_stabilization.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "from quant_us.research.btc_eventpf_wf import run_stabilization_sprint",
                "--run-id",
                "--output-root",
                "--source-run-dir",
            ]
        ),
        encoding="utf-8",
    )


def _write_existing_event_manifest_contract(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_canonical/20260516T080000Z_eventpf_wf/run_manifest.json",
        {
            "schema_version": "btc_eventpf_wf_run_manifest_v1",
            "run_id": "20260516T080000Z_eventpf_wf",
            "artifact_paths": ["run_manifest.json"],
        },
    )
    _write_json(
        root
        / "artifacts/btc_canonical/20260516T080000Z_eventpf_wf/manifests/"
        / "run_btc_perp_dual_trend_v4_eventpf_wf_base.json",
        {
            "data_version": "qs-sqlite-BTCUSDT-1h-fixture",
            "strategy_version": "btc_perp_dual_trend_v4_eventpf_wf:canonical_research_v1",
            "strategy_params": {"fast_ma": 96},
            "cost_model": {"commission_rate": 0.0004},
            "slippage_model": {"bps": 4.0},
            "commit_hash": "fixture",
        },
    )


def _target_body(makefile: str, target: str) -> str:
    marker = f"\n{target}:"
    start = makefile.index(marker)
    rest = makefile[start + 1 :]
    next_target = rest.find("\n\n")
    return rest if next_target == -1 else rest[:next_target]
