"""Tests for CLI portfolio research commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest


class TestCliPortfolioResearchCommands:
    """Verify CLI commands parse correctly."""

    def _make_parser(self) -> Any:
        """Get the research parser."""
        from quant_us.cli import _add_research_parser

        parent = argparse.ArgumentParser(add_help=False)
        parent.add_argument("--data-root", default="data")
        parent.add_argument("--symbols", default="SPY,QQQ")

        parser = argparse.ArgumentParser(prog="quant-us")
        subparsers = parser.add_subparsers()
        _add_research_parser(subparsers)
        return parser

    def test_portfolio_build_command_parses(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "portfolio-build",
            "--strategy-manifests", "sm_1,sm_2",
            "--weights", "strat_1:0.6,strat_2:0.4",
        ])
        assert args.research_command == "portfolio-build"
        assert args.func is not None
        assert args.strategy_manifests == "sm_1,sm_2"
        assert args.weights == "strat_1:0.6,strat_2:0.4"

    def test_portfolio_build_command_default_weights(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "portfolio-build",
            "--strategy-manifests", "sm_1",
        ])
        assert args.weights == ""

    def test_portfolio_analyze_command_parses(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "portfolio-analyze",
            "--portfolio-id", "portfolio_1",
        ])
        assert args.research_command == "portfolio-analyze"
        assert args.portfolio_id == "portfolio_1"

    def test_portfolio_stress_command_parses(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "portfolio-stress",
            "--portfolio-id", "portfolio_1",
        ])
        assert args.research_command == "portfolio-stress"
        assert args.portfolio_id == "portfolio_1"

    def test_evidence_registry_rebuild_command_parses(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "evidence-registry-rebuild",
            "--data-root", "tmp-data",
        ])
        assert args.research_command == "evidence-registry-rebuild"
        assert args.data_root == "tmp-data"
        assert args.func is not None

    def test_research_feature_build_accepts_timeframe_args(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "feature", "build",
            "--feature-id", "momentum_20d",
            "--symbols", "AAPL,MSFT",
            "--bar-size", "15m",
            "--timeframe", "15m",
        ])
        assert args.feature_command == "build"
        assert args.bar_size == "15m"
        assert args.timeframe == "15m"

    def test_paper_review_create_accepts_evidence_pack_id(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "paper-review-create",
            "--evidence-pack-id", "cand_001",
        ])
        assert args.research_command == "paper-review-create"
        assert args.evidence_pack_id == "cand_001"
        assert args.portfolio_sim_id is None

    def test_paper_review_create_accepts_candidate_id(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "paper-review-create",
            "--candidate-id", "cand_001",
        ])
        assert args.research_command == "paper-review-create"
        assert args.candidate_id == "cand_001"
        assert args.strategy_manifest_id is None

    def test_paper_review_create_accepts_strategy_manifest_id(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args([
            "research", "paper-review-create",
            "--strategy-manifest-id", "sm_001",
            "--prepared-evidence-pack-id", "pending_review_sm_001",
        ])
        assert args.research_command == "paper-review-create"
        assert args.strategy_manifest_id == "sm_001"
        assert args.prepared_evidence_pack_id == "pending_review_sm_001"

    def test_portfolio_build_requires_manifests(self) -> None:
        parser = self._make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["research", "portfolio-build"])

    def test_portfolio_analyze_requires_portfolio_id(self) -> None:
        parser = self._make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["research", "portfolio-analyze"])

    def test_portfolio_stress_requires_portfolio_id(self) -> None:
        parser = self._make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["research", "portfolio-stress"])

    def test_factor_compute_accepts_timeframe_args(self) -> None:
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "factor",
            "--symbols", "AAPL,MSFT",
            "compute",
            "--factor", "momentum_20d",
            "--bar-size", "5m",
            "--timeframe", "5m",
        ])
        assert args.factor_command == "compute"
        assert args.bar_size == "5m"
        assert args.timeframe == "5m"
