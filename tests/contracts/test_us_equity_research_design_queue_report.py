from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_research_design_queue_report import (
    build_us_equity_research_design_queue_report,
)


SCHEMA = Path("schemas/us_equity_research_design_queue_report.schema.json")


def test_research_design_queue_prioritizes_design_tasks_without_backtest_unlock(tmp_path: Path) -> None:
    _write_gate(
        tmp_path,
        [
            _row("primary", "us_etf_macro_momentum_rotation", "existing_formal_candidate_waiting_for_production_data"),
            _row("dual", "dual_momentum", "hypothesis_design_only"),
            _row("overlay", "regime_overlay", "hypothesis_design_only"),
        ],
    )

    payload = build_us_equity_research_design_queue_report(
        repo_root=tmp_path,
        research_start_gate=Path("gate.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_design_queue_ready"
    assert payload["design_ready_count"] == 2
    assert payload["waiting_for_production_data_count"] == 1
    assert payload["next_task"]["strategy_id"] == "dual"
    assert payload["production_data_gate"]["production_pit_ready_for_formal_research"] is False
    assert payload["production_data_gate"]["pit_intake_status"] == "production_pit_data_intake_blocked"
    assert "us_equity_research_start_production_pit_intake_not_ready" in payload["production_data_gate"]["blockers"]
    assert all(
        task["production_data_gate"]["production_pit_ready_for_formal_research"] is False
        for task in payload["tasks"]
    )
    assert all(task["standardized_backtest_allowed"] is False for task in payload["tasks"])
    assert all(task["paper_or_live_allowed"] is False for task in payload["tasks"])
    assert payload["guardrails"]["standardized_backtest_allowed_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/queue.md").exists()


def test_research_design_queue_recognizes_completed_design_spec_and_advances(tmp_path: Path) -> None:
    _write_gate(
        tmp_path,
        [
            _row("us_equity_dual_momentum_research_placeholder", "dual_momentum", "hypothesis_design_only"),
            _row("absolute", "absolute_momentum", "hypothesis_design_only"),
            _row("primary", "us_etf_macro_momentum_rotation", "existing_formal_candidate_waiting_for_production_data"),
        ],
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_dual_momentum_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_dual_momentum_design_spec_report.json"
            },
        },
    )

    payload = build_us_equity_research_design_queue_report(
        repo_root=tmp_path,
        research_start_gate=Path("gate.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_design_queue_ready"
    assert payload["design_complete_count"] == 1
    assert payload["design_ready_count"] == 1
    assert payload["next_task"]["strategy_id"] == "absolute"
    completed = next(
        task for task in payload["tasks"] if task["strategy_id"] == "us_equity_dual_momentum_research_placeholder"
    )
    assert completed["status"] == "design_complete_waiting_for_research_start"
    assert completed["design_spec_ready"] is True
    assert completed["next_required_action"] == "wait_for_production_pit_data_and_research_start_gate"
    assert completed["standardized_backtest_allowed"] is False


def test_research_design_queue_recognizes_multiple_completed_specs(tmp_path: Path) -> None:
    _write_gate(
        tmp_path,
        [
            _row("us_equity_dual_momentum_research_placeholder", "dual_momentum", "hypothesis_design_only"),
            _row("us_equity_absolute_momentum_research_placeholder", "absolute_momentum", "hypothesis_design_only"),
            _row("us_equity_etf_topn_rotation_research_placeholder", "topn_etf_rotation", "hypothesis_design_only"),
            _row("us_equity_regime_overlay_research_placeholder", "regime_overlay", "hypothesis_design_only"),
            _row("us_equity_factor_momentum_quality_research_placeholder", "equity_factor", "hypothesis_design_only"),
            _row(
                "us_equity_151_trading_strategies_candidate_research_placeholder",
                "151_trading_strategies_migration",
                "hypothesis_design_only",
            ),
            _row("primary", "us_etf_macro_momentum_rotation", "existing_formal_candidate_waiting_for_production_data"),
        ],
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_dual_momentum_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_dual_momentum_design_spec_report.json"
            },
        },
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_absolute_momentum_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_absolute_momentum_design_spec_report.json"
            },
        },
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_topn_etf_rotation_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_topn_etf_rotation_design_spec_report.json"
            },
        },
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_regime_overlay_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_regime_overlay_design_spec_report.json"
            },
        },
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_factor_momentum_quality_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_factor_momentum_quality_design_spec_report.json"
            },
        },
    )
    _write_json(
        tmp_path
        / "artifacts/us_equity_strategy_registry/latest/us_equity_151_trading_strategies_migration_design_spec_report.json",
        {
            "status": "design_spec_ready",
            "outputs": {
                "json": "artifacts/us_equity_strategy_registry/latest/us_equity_151_trading_strategies_migration_design_spec_report.json"
            },
        },
    )

    payload = build_us_equity_research_design_queue_report(
        repo_root=tmp_path,
        research_start_gate=Path("gate.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_design_queue_waiting_for_data"
    assert payload["design_complete_count"] == 6
    assert payload["design_ready_count"] == 0
    assert payload["waiting_for_production_data_count"] == 1
    assert payload["next_task"]["strategy_id"] == "primary"
    assert payload["next_task"]["production_data_gate"]["pit_acceptance_status"] == "acceptance_blocked"
    completed_ids = {
        task["strategy_id"]
        for task in payload["tasks"]
        if task["status"] == "design_complete_waiting_for_research_start"
    }
    assert completed_ids == {
        "us_equity_dual_momentum_research_placeholder",
        "us_equity_absolute_momentum_research_placeholder",
        "us_equity_etf_topn_rotation_research_placeholder",
        "us_equity_regime_overlay_research_placeholder",
        "us_equity_factor_momentum_quality_research_placeholder",
        "us_equity_151_trading_strategies_candidate_research_placeholder",
    }


def test_research_design_queue_blocks_bad_gate_rows(tmp_path: Path) -> None:
    _write_gate(tmp_path, [_row("bad", "dual_momentum", "blocked", blockers=["strategy_card_missing"])])

    payload = build_us_equity_research_design_queue_report(
        repo_root=tmp_path,
        research_start_gate=Path("gate.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_design_queue_blocked"
    assert payload["blocked_count"] == 1
    assert "us_equity_research_design_queue_task_blocked:bad" in payload["blockers"]


def test_research_design_queue_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_gate(tmp_path, [_row("dual", "dual_momentum", "hypothesis_design_only")])
    payload = build_us_equity_research_design_queue_report(
        repo_root=tmp_path,
        research_start_gate=Path("gate.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _row(strategy_id: str, family: str, status: str, blockers: list[str] | None = None) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "family": family,
        "status": status,
        "strategy_card": f"docs/strategy_cards/{strategy_id}.md",
        "blockers": blockers or [],
    }


def _write_gate(tmp_path: Path, rows: list[dict[str, object]]) -> None:
    _write_json(
        tmp_path / "gate.json",
        {
            "status": "research_design_only",
            "production_data": {
                "pit_intake_status": "production_pit_data_intake_blocked",
                "pit_acceptance_status": "acceptance_blocked",
                "production_pit_ready_for_formal_research": False,
            },
            "blockers": [
                "us_equity_research_start_production_pit_intake_not_ready",
                "us_equity_research_start_pit_bundle_acceptance_not_ready",
            ],
            "strategies": rows,
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
