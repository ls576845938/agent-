from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.build_btc_trend_v0_strategy_validation_gate_report import (
    build_btc_trend_v0_strategy_validation_gate_report,
)


def test_strategy_validation_gate_rejects_insufficient_history(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_daily_bundle(bundle, rows=400, close_start=100.0, close_step=1.0)
    formal = tmp_path / "formal.json"
    robustness = tmp_path / "robustness.json"
    paper_gate = tmp_path / "paper_gate.json"
    _write_ready_formal(formal)
    _write_research_robustness(robustness)
    _write_paper_operational_gate(paper_gate)

    payload = build_btc_trend_v0_strategy_validation_gate_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        formal_report=formal,
        robustness_report=robustness,
        paper_gate=paper_gate,
        output=tmp_path / "validation.json",
        markdown_output=tmp_path / "validation.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["gate_type"] == "strategy_backtest_validation_gate"
    assert payload["status"] == "strategy_validation_rejected"
    assert payload["strategy_validation_passed"] is False
    assert "paper_candidate_ready" not in payload
    assert payload["paper_candidate_ready_is_strategy_validation"] is False
    assert "btc_trend_strategy_validation_daily_rows_below_1095" in payload["blockers"]
    assert payload["guardrails"]["this_gate_does_not_unlock_live_trading"] is True
    assert payload["guardrails"]["live_order_allowed"] is False


def test_strategy_validation_gate_stays_separate_from_paper_readiness(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_daily_bundle(bundle, rows=1200, close_start=100.0, close_step=0.0)
    formal = tmp_path / "formal.json"
    robustness = tmp_path / "robustness.json"
    paper_gate = tmp_path / "paper_gate.json"
    _write_ready_formal(formal)
    _write_research_robustness(robustness)
    _write_paper_operational_gate(paper_gate)

    payload = build_btc_trend_v0_strategy_validation_gate_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        formal_report=formal,
        robustness_report=robustness,
        paper_gate=paper_gate,
        output=tmp_path / "validation.json",
        markdown_output=tmp_path / "validation.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "strategy_validation_research_only"
    assert payload["strategy_validation_passed"] is False
    assert payload["paper_runner_observation_allowed"] is True
    assert payload["paper_gate_type"] == "paper_operational_readiness_gate"
    assert payload["guardrails"]["this_gate_does_not_unlock_paper_runner"] is True
    assert payload["checks"]["long_history"] is True
    assert payload["checks"]["cost_stress"] is False


def _write_daily_bundle(path: Path, *, rows: int, close_start: float, close_step: float) -> None:
    path.mkdir(parents=True, exist_ok=True)
    timestamps = pd.date_range("2020-01-01", periods=rows, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [close_start + i * close_step for i in range(rows)],
            "high": [close_start + i * close_step + 1.0 for i in range(rows)],
            "low": [max(1.0, close_start + i * close_step - 1.0) for i in range(rows)],
            "close": [close_start + i * close_step for i in range(rows)],
            "volume_base": [1.0 for _ in range(rows)],
        }
    )
    frame.to_csv(path / "klines_1d.csv", index=False)


def _write_ready_formal(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "research_ready",
                "guardrails": {
                    "broker_calls_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_research_robustness(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "research_only",
                "guardrails": {
                    "broker_calls_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_paper_operational_gate(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "paper_candidate_ready",
                "gate_type": "paper_operational_readiness_gate",
                "guardrails": {
                    "broker_calls_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                },
            }
        ),
        encoding="utf-8",
    )
