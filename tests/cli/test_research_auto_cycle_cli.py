from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from quant_us.cli import main


def _run_cli(argv: list[str]) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        main(argv)
    return out.getvalue()


def test_research_auto_cycle_runs_pipeline_evidence_gate_and_registry() -> None:
    pipeline_result = {
        "pipeline_id": "pipe_001",
        "status": "completed",
        "experiment_ids": ["exp_001"],
        "candidate_ids": ["cand_001"],
        "paper_review_ready": ["cand_001"],
    }

    with (
        patch("quant_us.research.automation.pipeline.ResearchAutomationPipeline") as pipeline_cls,
        patch("quant_us.research.evidence_pack.EvidencePackGenerator") as evidence_cls,
        patch("quant_us.research.automation.promotion_gate.ResearchPromotionGate") as gate_cls,
        patch("quant_us.research.evidence_registry.rebuild_evidence_registry") as rebuild,
    ):
        pipeline_cls.return_value.run.return_value = pipeline_result
        evidence_cls.return_value.save.return_value = "data/research/evidence_packs/cand_001/evidence_pack.json"
        gate_cls.return_value.evaluate.return_value = SimpleNamespace(decision="READY_FOR_PAPER_REVIEW")
        rebuild.return_value = {"registry_path": "data/research/evidence_registry.json"}

        output = _run_cli(
            [
                "research",
                "auto-cycle",
                "--strategy-id",
                "etf_rotation",
                "--symbols",
                "SPY,QQQ",
                "--params",
                '{"lookback": 20}',
                "--param-grid",
                '{"lookback": [20, 60]}',
                "--start",
                "2020-01-01",
                "--end",
                "2024-12-31",
                "--data-root",
                "data",
            ]
        )

    pipeline_cls.return_value.run.assert_called_once()
    config = pipeline_cls.return_value.run.call_args.args[0]
    assert config["strategy_id"] == "etf_rotation"
    assert config["symbols"] == ["SPY", "QQQ"]
    assert config["params"] == {"lookback": 20}
    assert config["param_grid"] == {"lookback": [20, 60]}
    evidence_cls.return_value.save.assert_called_once_with("cand_001")
    gate_cls.return_value.evaluate.assert_called_once_with("cand_001")
    rebuild.assert_called_once_with("data", write=True)
    assert "Research Auto-Cycle" in output
    assert "candidate_generation" in output
    assert "experiment_run: COMPLETED" in output
    assert "evidence_materialize: PASS" in output
    assert "promotion_gate: PASS" in output
    assert "evidence_registry_rebuild: PASS" in output
    assert "paper_review_ready: cand_001" in output
    assert "never starts paper trading" in output


def test_research_auto_cycle_invalid_cli_config_fails_closed() -> None:
    with pytest.raises(SystemExit) as raised:
        _run_cli(["research", "auto-cycle", "--symbols", "SPY"])

    assert raised.value.code == 2


def test_research_auto_cycle_failed_pipeline_exits_nonzero() -> None:
    pipeline_result = {
        "pipeline_id": "pipe_bad",
        "status": "failed",
        "experiment_ids": [],
        "candidate_ids": [],
        "paper_review_ready": [],
        "error": "boom",
    }

    out = io.StringIO()
    with (
        redirect_stdout(out),
        patch("quant_us.research.automation.pipeline.ResearchAutomationPipeline") as pipeline_cls,
        patch("quant_us.research.evidence_pack.EvidencePackGenerator"),
        patch("quant_us.research.automation.promotion_gate.ResearchPromotionGate"),
        patch("quant_us.research.evidence_registry.rebuild_evidence_registry") as rebuild,
        pytest.raises(SystemExit) as raised,
    ):
        pipeline_cls.return_value.run.return_value = pipeline_result
        rebuild.return_value = {"registry_path": "data/research/evidence_registry.json"}
        main(
            [
                "research",
                "auto-cycle",
                "--strategy-id",
                "etf_rotation",
                "--symbols",
                "SPY",
            ]
        )

    assert raised.value.code == 1
    output = out.getvalue()
    assert "experiment_run: FAILED" in output
    assert "error: boom" in output
    assert "evidence_registry_rebuild: PASS" in output
