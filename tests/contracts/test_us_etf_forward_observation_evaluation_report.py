from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_etf_forward_observation_evaluation_report import (
    build_us_etf_forward_observation_evaluation_report,
)


SCHEMA = Path("schemas/us_etf_forward_observation_evaluation_report.schema.json")


def test_us_etf_forward_evaluation_observes_before_30_days(tmp_path: Path) -> None:
    _write_ledger(tmp_path, days=1)
    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_etf_forward_observation_evaluation_v1"
    _validate_schema(payload)
    assert payload["status"] == "forward_observing"
    assert payload["metrics"]["observation_days"] == 1
    assert payload["review_progress"]["observation_days"] == 1
    assert payload["review_progress"]["next_milestone"] == 30
    assert payload["review_progress"]["days_until_minimum"] == 29
    assert payload["review_progress"]["manual_review_required"] is False
    assert payload["review_progress"]["alpha_validation_claim_allowed"] is False
    assert payload["review_progress"]["paper_or_live_unlock_allowed"] is False
    assert payload["metrics"]["target_change_count"] == 1
    assert payload["metrics"]["simulated_fill_count"] == 3
    assert payload["metrics"]["data_gate_pass_count"] == 1
    assert payload["metrics"]["data_gate_blocked_count"] == 0
    assert payload["observation_continuity"]["passed"] is True
    assert payload["observation_continuity"]["unique_observation_days"] == 1
    assert payload["checks"]["observation_continuity"]["passed"] is True
    assert payload["checks"]["ledger_recalculation"]["passed"] is True
    assert payload["checks"]["daily_data_gate"]["passed"] is True
    assert payload["checks"]["target_fill_consistency"]["passed"] is True
    assert payload["guardrails"]["forward_evaluation_is_not_alpha_validation"] is True
    assert payload["guardrails"]["long_term_positive_expectancy_proven"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/eval.json").exists()
    assert (tmp_path / "out/eval.md").exists()


def test_us_etf_forward_evaluation_completes_for_manual_review_at_30_days(tmp_path: Path) -> None:
    _write_ledger(tmp_path, days=30)
    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "forward_complete_for_manual_review"
    _validate_schema(payload)
    assert payload["decision"] == "manual_review_required"
    assert payload["metrics"]["observation_days"] == 30
    assert payload["review_progress"]["completed_milestones"] == [30]
    assert payload["review_progress"]["next_milestone"] == 60
    assert payload["review_progress"]["days_until_minimum"] == 0
    assert payload["review_progress"]["manual_review_required"] is True
    assert payload["review_progress"]["manual_review_only_no_paper_or_live_unlock"] is True
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_us_etf_forward_evaluation_blocks_reconciliation_mismatch(tmp_path: Path) -> None:
    _write_ledger(tmp_path, days=1, corrupt_snapshot=True)
    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "forward_blocked"
    _validate_schema(payload)
    assert "us_etf_forward_evaluation_ledger_recalculation_failed" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_us_etf_forward_evaluation_blocks_data_gate_failure(tmp_path: Path) -> None:
    _write_ledger(tmp_path, days=1, data_gate_status="blocked", data_gate_blockers=["price_data_stale"])
    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "forward_blocked"
    _validate_schema(payload)
    assert payload["metrics"]["data_gate_blocked_count"] == 1
    assert payload["checks"]["daily_data_gate"]["passed"] is False
    assert "us_etf_forward_evaluation_daily_data_gate_failed" in payload["blockers"]
    assert payload["daily_data_gate"]["reports"][0]["blockers"] == ["price_data_stale"]


def test_us_etf_forward_evaluation_blocks_duplicate_target_date(tmp_path: Path) -> None:
    _write_ledger(tmp_path, days=1)
    target_path = tmp_path / "data/forward_observation/us_etf_rotation_v1/target_positions.jsonl"
    duplicate = json.loads(target_path.read_text(encoding="utf-8").splitlines()[0])
    target_path.write_text(target_path.read_text(encoding="utf-8") + json.dumps(duplicate) + "\n", encoding="utf-8")
    state_path = tmp_path / "data/forward_observation/us_etf_rotation_v1/validation_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["target_position_count"] = 2
    state_path.write_text(json.dumps(state), encoding="utf-8")

    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "forward_blocked"
    _validate_schema(payload)
    assert payload["observation_continuity"]["passed"] is False
    assert payload["observation_continuity"]["duplicate_target_dates"] == ["2026-05-01"]
    assert "us_etf_forward_evaluation_observation_continuity_failed" in payload["blockers"]


def test_us_etf_forward_evaluation_schema_rejects_paper_unlock(tmp_path: Path) -> None:
    _write_ledger(tmp_path, days=1)
    payload = build_us_etf_forward_observation_evaluation_report(
        repo_root=tmp_path,
        output=Path("out/eval.json"),
        markdown_output=Path("out/eval.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def _write_ledger(
    tmp_path: Path,
    *,
    days: int,
    corrupt_snapshot: bool = False,
    data_gate_status: str = "pass",
    data_gate_blockers: list[str] | None = None,
) -> None:
    ledger = tmp_path / "data/forward_observation/us_etf_rotation_v1"
    ledger.mkdir(parents=True, exist_ok=True)
    fills = []
    targets = []
    snapshots = []
    equity = 10_000.0
    for index in range(days):
        day = f"2026-05-{index + 1:02d}" if index < 28 else f"2026-06-{index - 27:02d}"
        turnover = 0.9 if index == 0 else 0.0
        slippage = 9.0 if index == 0 else 0.0
        prior = equity
        equity = equity - slippage
        snapshot_equity = equity + (5.0 if corrupt_snapshot and index == 0 else 0.0)
        targets.append(
            {
                "timestamp": day,
                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                "candidate_variant": "min_adv_10m_to_shv",
                "target_position": {
                    "date": day,
                    "target_count": 3,
                    "weights": {"DBMF": 0.2, "SHV": 0.4, "USO": 0.3},
                },
                "rebalance": {
                    "turnover": turnover,
                    "estimated_slippage": slippage,
                    "estimated_financing_daily": 0.0,
                },
                "reason": "fixture_target",
                "simulated_only": True,
            }
        )
        if index == 0:
            for symbol in ["DBMF", "SHV", "USO"]:
                fills.append(
                    {
                        "timestamp": day,
                        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                        "symbol": symbol,
                        "notional": 3000.0,
                        "delta_weight": 0.3,
                        "simulated_only": True,
                    }
                )
        snapshots.append(
            {
                "timestamp": day,
                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                "prior_equity": prior,
                "equity": snapshot_equity,
                "estimated_slippage": slippage,
                "estimated_financing_daily": 0.0,
                "estimated_trade_notional": 9000.0 if index == 0 else 0.0,
                "target_count": 3,
                "reconciliation_status": "clean",
            }
        )
    _write_jsonl(ledger / "target_positions.jsonl", targets)
    _write_jsonl(ledger / "fills.jsonl", fills)
    _write_jsonl(ledger / "portfolio_snapshots.jsonl", snapshots)
    (ledger / "validation_state.json").write_text(
        json.dumps(
            {
                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                "candidate_variant": "min_adv_10m_to_shv",
                "days_completed": days,
                "target_position_count": days,
                "fill_count": len(fills),
                "last_processed_timestamp": snapshots[-1]["timestamp"] if snapshots else None,
                "live_order_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
            }
        ),
        encoding="utf-8",
    )
    roll_path = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"
    roll_path.parent.mkdir(parents=True, exist_ok=True)
    roll_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "guardrails": {
                    "forward_observation_is_not_alpha_validation": True,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                },
                "alpha_validation": {"alpha_validated": False},
                "operational_checks": {"status": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    daily_path = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_run_report.json"
    daily_path.write_text(
        json.dumps(
            {
                "status": "PASS" if data_gate_status == "pass" else "BLOCKED",
                "steps": {
                    "data_gate": {
                        "status": data_gate_status,
                        "checks": [
                            {"check_id": "data_freshness", "status": data_gate_status, "passed": data_gate_status == "pass", "blockers": data_gate_blockers or []}
                        ],
                        "blockers": data_gate_blockers or [],
                    }
                },
                "guardrails": {"live_order_allowed": False, "paper_or_live_unlock_allowed": False},
            }
        ),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
