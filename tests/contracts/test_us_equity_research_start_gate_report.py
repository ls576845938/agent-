from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_research_start_gate_report import (
    build_us_equity_research_start_gate_report,
)


SCHEMA = Path("schemas/us_equity_research_start_gate_report.schema.json")


def test_research_start_gate_allows_design_only_when_pit_data_is_blocked(tmp_path: Path) -> None:
    _write_registry(tmp_path)
    _write_json(tmp_path / "pit.json", {"status": "production_pit_data_intake_blocked"})
    _write_json(tmp_path / "acceptance.json", {"status": "acceptance_blocked"})

    payload = build_us_equity_research_start_gate_report(
        repo_root=tmp_path,
        registry_report=Path("registry.json"),
        pit_intake_status=Path("pit.json"),
        pit_acceptance=Path("acceptance.json"),
        output=Path("out/gate.json"),
        markdown_output=Path("out/gate.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_design_only"
    assert payload["formal_research_allowed_count"] == 0
    assert payload["hypothesis_design_only_count"] == 1
    assert payload["production_data"]["production_pit_ready_for_formal_research"] is False
    assert payload["production_data"]["pit_intake_status"] == "production_pit_data_intake_blocked"
    assert payload["production_data"]["pit_acceptance_status"] == "acceptance_blocked"
    assert "us_equity_research_start_production_pit_intake_not_ready" in payload["blockers"]
    row = payload["strategies"][0]
    assert row["production_data_gate"] == payload["production_data"]
    assert row["hypothesis_design_allowed"] is True
    assert row["formal_research_allowed"] is False
    assert row["standardized_backtest_allowed"] is False
    assert row["paper_or_live_allowed"] is False
    assert payload["guardrails"]["standardized_backtest_started_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/gate.md").exists()


def test_research_start_gate_blocks_missing_strategy_card(tmp_path: Path) -> None:
    _write_registry(tmp_path, card_exists=False)
    _write_json(tmp_path / "pit.json", {"status": "production_pit_data_intake_ready"})
    _write_json(tmp_path / "acceptance.json", {"status": "acceptance_ready_for_manual_config_apply"})

    payload = build_us_equity_research_start_gate_report(
        repo_root=tmp_path,
        registry_report=Path("registry.json"),
        pit_intake_status=Path("pit.json"),
        pit_acceptance=Path("acceptance.json"),
        output=Path("out/gate.json"),
        markdown_output=Path("out/gate.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_start_blocked"
    assert payload["strategies"][0]["status"] == "blocked"
    assert "strategy_card_missing" in payload["blockers"]


def test_research_start_gate_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_registry(tmp_path)
    _write_json(tmp_path / "pit.json", {"status": "production_pit_data_intake_blocked"})
    _write_json(tmp_path / "acceptance.json", {"status": "acceptance_blocked"})
    payload = build_us_equity_research_start_gate_report(
        repo_root=tmp_path,
        registry_report=Path("registry.json"),
        pit_intake_status=Path("pit.json"),
        pit_acceptance=Path("acceptance.json"),
        output=Path("out/gate.json"),
        markdown_output=Path("out/gate.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_registry(tmp_path: Path, *, card_exists: bool = True) -> None:
    if card_exists:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs/card.md").write_text("# Card", encoding="utf-8")
    _write_json(
        tmp_path / "registry.json",
        {
            "status": "pass",
            "strategy_rows": [
                {
                    "strategy_id": "hypothesis",
                    "family": "dual_momentum",
                    "status": "hypothesis_registered_only",
                    "current_stage": "strategy_hypothesis_registration",
                    "strategy_card": "docs/card.md",
                    "strategy_card_exists": card_exists,
                    "source_report_contract_passed": True,
                }
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
