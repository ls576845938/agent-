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
