from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_etf_forward_observation_replay_readiness_report import (
    build_us_etf_forward_observation_replay_readiness_report,
)


SCHEMA = Path("schemas/us_etf_forward_observation_replay_readiness_report.schema.json")


def test_replay_readiness_passes_with_static_forward_evidence(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    payload = build_us_etf_forward_observation_replay_readiness_report(
        repo_root=tmp_path,
        output=Path("out/replay.json"),
        markdown_output=Path("out/replay.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_etf_forward_observation_replay_readiness_v1"
    _validate_schema(payload)
    assert payload["status"] == "replay_readiness_pass"
    assert payload["replay_scope"]["current_realtime_data_accessed"] is False
    assert payload["replay_scope"]["fixed_random_seed"] == 0
    assert payload["checks"]["latest_target_replay_inputs"]["passed"] is True
    assert payload["checks"]["fills_replay_inputs"]["passed"] is True
    assert payload["checks"]["monitoring_replay_contract"]["passed"] is True
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/replay.md").exists()


def test_replay_readiness_blocks_missing_ledger(tmp_path: Path) -> None:
    _write_fixture(tmp_path, include_ledger=False)

    payload = build_us_etf_forward_observation_replay_readiness_report(
        repo_root=tmp_path,
        output=Path("out/replay.json"),
        markdown_output=Path("out/replay.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "replay_readiness_blocked"
    _validate_schema(payload)
    assert "replay_readiness_ledger_artifacts_present_failed" in payload["blockers"]
    assert "replay_readiness_latest_target_replay_inputs_failed" in payload["blockers"]


def test_replay_readiness_blocks_unsafe_live_flag(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    roll = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"
    payload = json.loads(roll.read_text(encoding="utf-8"))
    payload["guardrails"]["live_order_allowed"] = True
    roll.write_text(json.dumps(payload), encoding="utf-8")

    report = build_us_etf_forward_observation_replay_readiness_report(
        repo_root=tmp_path,
        output=Path("out/replay.json"),
        markdown_output=Path("out/replay.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert report["status"] == "replay_readiness_blocked"
    _validate_schema(report)
    assert "replay_readiness_unsafe_flags_failed" in report["blockers"]
    assert "roll.guardrails.live_order_allowed=true" in report["checks"]["unsafe_flags"]["unsafe_flags"]


def test_replay_readiness_schema_rejects_current_realtime_access(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    payload = build_us_etf_forward_observation_replay_readiness_report(
        repo_root=tmp_path,
        output=Path("out/replay.json"),
        markdown_output=Path("out/replay.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["replay_scope"]["current_realtime_data_accessed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted current_realtime_data_accessed=true")


def _write_fixture(root: Path, *, include_ledger: bool = True) -> None:
    ledger = root / "data/forward_observation/us_etf_rotation_v1"
    if include_ledger:
        _write_jsonl(
            ledger / "target_positions.jsonl",
            [
                {
                    "timestamp": "2026-06-23",
                    "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                    "candidate_variant": "min_adv_10m_to_shv",
                    "current_position": {},
                    "reason": "monthly_rotation_target_from_research_validation_report",
                    "rebalance": {"turnover": 1.0},
                    "target_position": {
                        "date": "2026-06-23",
                        "weights": {"SPY": 1.0},
                        "prices": {"SPY": 100.0},
                        "shares": {"SPY": 100.0},
                        "notionals": {"SPY": 10000.0},
                        "target_count": 1,
                    },
                }
            ],
        )
        _write_jsonl(
            ledger / "fills.jsonl",
            [
                {
                    "timestamp": "2026-06-23",
                    "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                    "candidate_variant": "min_adv_10m_to_shv",
                    "symbol": "SPY",
                    "side": "buy",
                    "quantity": 100.0,
                    "price": 100.0,
                    "notional": 10000.0,
                    "simulated_only": True,
                }
            ],
        )
        _write_jsonl(
            ledger / "portfolio_snapshots.jsonl",
            [
                {
                    "timestamp": "2026-06-23",
                    "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                    "prior_equity": 10000.0,
                    "equity": 9990.0,
                    "estimated_slippage": 10.0,
                    "estimated_financing_daily": 0.0,
                    "reconciliation_status": "clean",
                }
            ],
        )
        _write_json(
            ledger / "validation_state.json",
            {
                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                "candidate_variant": "min_adv_10m_to_shv",
                "live_order_allowed": False,
            },
        )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json",
        {"status": "PASS", "cycle_status": "COMPLETED", "guardrails": {"paper_or_live_unlock_allowed": False, "live_order_allowed": False}},
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {"status": "forward_observing", "guardrails": {"paper_or_live_unlock_allowed": False, "live_order_allowed": False}},
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json",
        {"base_strategy_id": "top1_higher_vol", "selected_variant": {"variant_id": "min_adv_10m_to_shv"}},
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
        {
            "status": "monitoring_rules_defined",
            "replay_requirements": {
                "inputs": ["data_snapshot", "strategy_version", "params", "risk_config", "current_position", "orders_and_fills"],
                "outputs": ["replayed_signal", "replayed_target_position", "replayed_risk_decision", "diff_vs_original_artifact"],
            },
            "guardrails": {"paper_or_live_unlock_allowed": False, "live_order_allowed": False},
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
