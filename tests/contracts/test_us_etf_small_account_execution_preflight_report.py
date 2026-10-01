from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_etf_small_account_execution_preflight_report import (
    build_us_etf_small_account_execution_preflight_report,
)


SCHEMA = Path("schemas/us_etf_small_account_execution_preflight_report.schema.json")


def test_small_account_execution_preflight_builds_fractional_and_whole_share_models(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path)

    payload = build_us_etf_small_account_execution_preflight_report(
        repo_root=tmp_path,
        ledger_root=ledger,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_etf_small_account_execution_preflight_v1"
    _validate_schema(payload)
    assert payload["status"] == "pass_observation_only"
    assert payload["account_equity"] == 10000.0
    assert payload["guardrails"]["simulated_only"] is True
    assert payload["guardrails"]["not_a_broker_order"] is True
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["research_cap_1_5x_not_live_default"] is True
    assert [row["scenario_id"] for row in payload["scenarios"]] == [
        "one_x_cash_only",
        "low_leverage_1_25x_research",
        "research_cap_1_5x",
    ]
    first = payload["scenarios"][0]
    assert first["gross_cap"] == 1.0
    assert first["passes_preflight"] is True
    assert first["fractional_share_allowed_model"]["borrow_notional"] == 0.0
    assert first["fractional_share_allowed_model"]["initial_margin_required"] > 0.0
    assert first["fractional_share_allowed_model"]["maintenance_margin_surplus"] > 0.0
    assert first["fractional_share_allowed_model"]["orders"][0]["quantity"] > 0
    assert first["whole_share_model"]["orders"][0]["quantity"] == int(first["whole_share_model"]["orders"][0]["quantity"])
    assert (tmp_path / "report.md").exists()
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "# US ETF 小账户执行约束审计" in markdown
    assert "本报告只做目标订单和账户约束审计" in markdown
    assert "live_order_allowed=false" in markdown
    assert "## Guardrails" in markdown


def test_small_account_execution_preflight_blocks_missing_ledger(tmp_path: Path) -> None:
    payload = build_us_etf_small_account_execution_preflight_report(
        repo_root=tmp_path,
        ledger_root=Path("missing"),
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "us_etf_small_account_preflight_no_target_positions" in payload["blockers"]
    assert payload["guardrails"]["order_endpoint_allowed"] is False


def test_small_account_execution_preflight_blocks_tiny_trade_amount(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path, weights={"SHV": 0.001, "VOO": 0.999})

    payload = build_us_etf_small_account_execution_preflight_report(
        repo_root=tmp_path,
        ledger_root=ledger,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        min_trade_amount_usd=25.0,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert any(item.startswith("us_etf_small_account_preflight_scenario_failed:") for item in payload["blockers"])
    assert any("below_min_trade_amount:SHV" in item for item in payload["scenarios"][0]["blockers"])


def test_small_account_execution_preflight_blocks_margin_requirement_failure(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path, weights={"VOO": 1.5})

    payload = build_us_etf_small_account_execution_preflight_report(
        repo_root=tmp_path,
        ledger_root=ledger,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        initial_margin_requirement=0.8,
        maintenance_margin_requirement=0.4,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    research_cap = next(item for item in payload["scenarios"] if item["scenario_id"] == "research_cap_1_5x")
    assert research_cap["fractional_share_allowed_model"]["borrow_notional"] > 0.0
    assert research_cap["fractional_share_allowed_model"]["initial_margin_surplus"] < 0.0
    assert "initial_margin_requirement_failed_fractional" in research_cap["blockers"]
    assert "us_etf_small_account_preflight_scenario_failed:research_cap_1_5x" in payload["blockers"]


def test_small_account_execution_preflight_schema_rejects_live_unlock(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path)
    payload = build_us_etf_small_account_execution_preflight_report(
        repo_root=tmp_path,
        ledger_root=ledger,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_ledger(tmp_path: Path, *, weights: dict[str, float] | None = None) -> Path:
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    weights = weights or {"DBMF": 0.25, "SHV": 0.35, "USO": 0.35}
    prices = {"DBMF": 30.57, "SHV": 110.27, "USO": 111.26, "VOO": 550.0}
    target = {
        "timestamp": "2026-06-23",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "candidate_variant": "min_adv_10m_to_shv",
        "target_position": {
            "date": "2026-06-23",
            "gross_exposure": sum(abs(value) for value in weights.values()),
            "net_exposure": sum(weights.values()),
            "weights": weights,
            "prices": {symbol: prices[symbol] for symbol in weights},
        },
    }
    (ledger / "target_positions.jsonl").write_text(json.dumps(target) + "\n", encoding="utf-8")
    return ledger


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
