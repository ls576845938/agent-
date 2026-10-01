from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
import pytest

from quant_us.research.us_etf_26_candidate_freeze import build_candidate_strategy_card


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/strategies/us_etf_26_candidate_freeze_v1.json"
SCHEMA_PATH = ROOT / "schemas/us_etf_26_candidate_strategy_card.schema.json"


def test_candidate_card_freezes_one_exploratory_candidate_fail_closed(tmp_path: Path) -> None:
    source_path = _write_source_batch(tmp_path)

    card = build_candidate_strategy_card(
        repo_root=tmp_path,
        config_path=CONFIG_PATH,
        source_report_path=source_path,
        output_root=Path("artifacts/candidate"),
        generated_at="2026-07-13T00:00:00Z",
        code_commit="a" * 40,
    )

    jsonschema.validate(card, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert card["candidate_id"] == "us-etf26-complete-return-qqq-1d-v1"
    assert card["research_window"]["clean_holdout"] is False
    assert card["independent_confirmation_window"]["status"] == "not_started"
    assert card["source_evidence"]["batch_audit"]["matrix_combination_count"] == 182
    assert card["source_evidence"]["batch_audit"]["cost_monotonic_violation_count"] == 0
    assert all(
        value is False
        for key, value in card["guardrails"].items()
        if key != "research_only"
    )
    assert (tmp_path / "artifacts/candidate/us_etf_26_candidate_strategy_card.md").is_file()


def test_candidate_card_rejects_non_monotonic_cost_evidence(tmp_path: Path) -> None:
    source_path = _write_source_batch(tmp_path, inject_cost_violation=True)

    with pytest.raises(ValueError, match="cost monotonic final equity violation"):
        build_candidate_strategy_card(
            repo_root=tmp_path,
            config_path=CONFIG_PATH,
            source_report_path=source_path,
            output_root=Path("artifacts/candidate"),
            code_commit="a" * 40,
        )


def _write_source_batch(tmp_path: Path, *, inject_cost_violation: bool = False) -> Path:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    matrix = []
    costs = []
    walks = []
    for symbol in config["universe"]:
        for timeframe in config["timeframes"]:
            is_selected = symbol == "QQQ" and timeframe == "1D"
            matrix.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "params": config["parameters"],
                    "three_x_portfolio_zero": False,
                    "three_x_total_return_pct": 1000.0 if is_selected else 1.0,
                    "three_x_annual_return_pct": 20.0 if is_selected else 1.0,
                    "three_x_sharpe": 0.7 if is_selected else 0.1,
                    "three_x_max_drawdown_abs_pct": 25.0,
                }
            )
            for cost in (0.0, 5.0, 10.0, 25.0, 50.0):
                final_equity = 100.0 - cost
                if inject_cost_violation and symbol == "AGG" and timeframe == "1min" and cost == 5.0:
                    final_equity = 101.0
                costs.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "cost_bps": cost,
                        "final_equity": final_equity,
                        "cost_drag_pct": cost,
                    }
                )
            walks.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "test_year": 2026,
                    "parameters_frozen": True,
                    "training_selection_used": False,
                }
            )
    output = tmp_path / "artifacts/source"
    output.mkdir(parents=True)
    paths = {
        "json": output / "report.json",
        "markdown": output / "report.md",
        "matrix_csv": output / "matrix.csv",
        "cost_stress_csv": output / "cost.csv",
        "walk_forward_csv": output / "walk.csv",
    }
    paths["markdown"].write_text("本报告不能解锁 paper/live", encoding="utf-8")
    _write_csv(paths["matrix_csv"], matrix)
    _write_csv(paths["cost_stress_csv"], costs)
    _write_csv(paths["walk_forward_csv"], walks)
    report = {
        "schema_version": "us_etf_26_complete_return_multitimeframe_report_v1",
        "status": "complete_research_only",
        "code_commit": "sourcecommit",
        "data": {
            "data_version": config["data"]["data_version"],
            "batch_sha256": config["data"]["aggregate_sha256"],
        },
        "matrix_rows": matrix,
        "cost_stress_rows": costs,
        "walk_forward_rows": walks,
        "walk_forward_contract": {
            "sample_role": "exploratory_selection_sample",
            "selection_sample_reused": True,
            "holdout_reused_for_selection": True,
            "clean_holdout": False,
        },
        "no_lookahead_contract": {
            "status": "pass_for_research_replay",
            "execution_time_rule": "effective signal is shifted one bar",
            "future_adjustment_available_time_replay_complete": False,
        },
        "promotion_blockers": ["source_research_only"],
        "outputs": {key: str(path.relative_to(tmp_path)) for key, path in paths.items()},
    }
    paths["json"].write_text(json.dumps(report), encoding="utf-8")
    return paths["json"]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
