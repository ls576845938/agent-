from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_etf_walk_forward_parameter_stability_gate import (
    build_us_etf_walk_forward_parameter_stability_gate,
)


SCHEMA_PATH = Path("schemas/us_etf_walk_forward_parameter_stability_gate_report.schema.json")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def test_walk_forward_parameter_stability_gate_accepts_research_only_stable_grid(tmp_path: Path) -> None:
    source = tmp_path / "wf.json"
    _write_source(source, fold_count=11, candidate_count=36, alive_rate=1.0, stable=True)

    payload = build_us_etf_walk_forward_parameter_stability_gate(
        repo_root=tmp_path,
        input_report=source,
        output=tmp_path / "gate.json",
        markdown_output=tmp_path / "gate.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "research_only_manual_review_required"
    assert payload["fold_count"] == 11
    assert payload["candidate_count"] == 36
    assert payload["alive_rate"] == 1.0
    assert payload["guardrails"]["not_strategy_validation_pass"] is True
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "gate.md").exists()


def test_walk_forward_parameter_stability_gate_blocks_tiny_parameter_grid(tmp_path: Path) -> None:
    source = tmp_path / "wf.json"
    _write_source(source, fold_count=3, candidate_count=4, alive_rate=0.25, stable=False)

    payload = build_us_etf_walk_forward_parameter_stability_gate(
        repo_root=tmp_path,
        input_report=source,
        output=tmp_path / "gate.json",
        markdown_output=tmp_path / "gate.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "blocked"
    assert "us_etf_wf_stability_fold_count_lt_5" in payload["blockers"]
    assert "us_etf_wf_stability_parameter_grid_too_small" in payload["blockers"]
    assert "us_etf_wf_stability_alive_rate_lt_50pct" in payload["blockers"]


def _write_source(path: Path, *, fold_count: int, candidate_count: int, alive_rate: float, stable: bool) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "research_only",
                "paper_ready": False,
                "live_ready": False,
                "walk_forward": {
                    "fold_count": fold_count,
                    "aggregate_oos_metrics": {
                        "cagr": 0.08,
                        "sharpe": 0.75,
                        "max_drawdown": -0.18,
                    },
                },
                "stability": {
                    "candidate_count": candidate_count,
                    "alive_count": int(candidate_count * alive_rate),
                    "alive_rate": alive_rate,
                    "stable_enough_for_next_research_stage": stable,
                    "min": {"sharpe": 0.6},
                    "median": {"sharpe": 0.7},
                    "max": {"sharpe": 0.8},
                },
            }
        ),
        encoding="utf-8",
    )
