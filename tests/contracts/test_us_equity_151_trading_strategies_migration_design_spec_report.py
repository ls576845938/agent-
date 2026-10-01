from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_151_trading_strategies_migration_design_spec_report import (
    build_us_equity_151_trading_strategies_migration_design_spec_report,
)


SCHEMA = Path("schemas/us_equity_151_trading_strategies_migration_design_spec_report.schema.json")


def test_151_trading_strategies_migration_design_spec_is_design_only(tmp_path: Path) -> None:
    payload = build_us_equity_151_trading_strategies_migration_design_spec_report(
        repo_root=tmp_path,
        output=Path("out/spec.json"),
        markdown_output=Path("out/spec.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "design_spec_ready"
    assert payload["registry_strategy_id"] == "us_equity_151_trading_strategies_candidate_research_placeholder"
    assert payload["family"] == "151_trading_strategies_migration"
    assert payload["guardrails"]["standardized_backtest_allowed_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert "screening_buckets" in payload["parameter_space_before_backtest"]
    assert "source_strategy_mapping" in payload["required_design_outputs"]
    assert "implementation_exclusions" in payload["required_design_outputs"]
    assert "source_strategy_mapping" in payload["signal_design"]
    assert "implementation_exclusions" in payload["signal_design"]
    assert set(payload["validation_plan"]["benchmarks"]) >= {"SPY", "QQQ", "IWM", "SHV"}
    assert "duplicate_strategy_detection" in payload["validation_plan"]["attribution_required"]
    assert (tmp_path / "out/spec.md").exists()


def test_151_trading_strategies_migration_design_spec_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_151_trading_strategies_migration_design_spec_report(
        repo_root=tmp_path,
        output=Path("out/spec.json"),
        markdown_output=Path("out/spec.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
