"""Deep validation path tests for ResearchPromotionGateService.

Exercises evaluate() with skip_deep_checks=False to verify cost_stress,
walk_forward gates, next_stage transitions, and error handling.

Uses fixture data (no network calls). Mocks only where real data cannot
produce the required condition (e.g., walk-forward with < 50 bars).
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from backend.app.domain.models import BacktestArtifacts
from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.research_gate import ResearchPromotionGateService


def _mock_artifacts(
    total_return_pct: float = 10.0,
    sharpe_ratio: float = 1.5,
    max_drawdown_pct: float = -8.0,
    trade_count: int = 50,
    profit_factor: float = 1.5,
) -> BacktestArtifacts:
    """Build a BacktestArtifacts with sufficient metrics to pass basic gates."""
    return BacktestArtifacts(
        mode="single",
        summary={
            "total_return_pct": total_return_pct,
            "annual_return_pct": 15.0,
            "annual_volatility_pct": 10.0,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": 2.0,
            "max_drawdown_pct": max_drawdown_pct,
            "calmar_ratio": 1.5,
            "win_rate_pct": 55.0,
            "profit_factor": profit_factor,
            "trade_count": trade_count,
        },
        chart={
            "candles": [],
            "markers": [],
            "equity": [],
            "drawdown": [],
            "exposure": [],
            "net_units": [],
            "turnover": [],
            "leverage": [],
        },
        strategy_details=[],
        latest_weights=[],
        diagnostics={
            "execution": {
                "cost_drag_pct": 0.5,
                "annual_turnover_pct": 200.0,
                "orders": trade_count,
            },
            "exposure": {
                "max_gross_exposure_pct": 150.0,
            },
        },
    )


class ResearchPromotionGateDeepTests(unittest.TestCase):
    """Exercise the skip_deep_checks=False path with fixture data and targeted mocks."""

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.service = ResearchPromotionGateService(
            research_service=ResearchBacktestService(),
            manifest_root=Path(self.tmpdir.name) / "manifests",
            experiment_root=Path(self.tmpdir.name) / "experiments",
        )
        # Use a data range that generates enough bars for both cost stress and walk-forward
        self.base_request: dict = {
            "mode": "single",
            "source": "fixture",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1),
            "end": datetime(2024, 2, 15),
            "strategy_id": "trend_macd",
            "strategy_params": {},
            "skip_deep_checks": False,
        }

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # Structural: verify deep-check gates appear
    # ------------------------------------------------------------------

    def test_deep_checks_gates_present(self) -> None:
        """evaluate(skip_deep_checks=False) includes cost_stress and walk_forward gates."""
        result = self.service.evaluate(dict(self.base_request))
        gate_names = [g["name"] for g in result["gates"]]
        self.assertIn("cost_stress", gate_names,
                      "cost_stress gate must be present when deep checks are enabled")
        self.assertIn("walk_forward", gate_names,
                      "walk_forward gate must be present when deep checks are enabled")

    def test_deep_checks_in_manifest_deep_checks_dict(self) -> None:
        """Manifest's deep_checks dict contains cost_stress and walk_forward results."""
        request = {**self.base_request, "persist_manifest": True}
        result = self.service.evaluate(request)
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertIn("cost_stress", manifest["deep_checks"],
                      "cost_stress keys in manifest['deep_checks']")
        self.assertIn("walk_forward", manifest["deep_checks"],
                      "walk_forward keys in manifest['deep_checks']")

    def test_deep_checks_are_omitted_when_skip_true(self) -> None:
        """skip_deep_checks=True does not include deep-check gates."""
        skip_request = {**self.base_request, "skip_deep_checks": True}
        result = self.service.evaluate(skip_request)
        gate_names = {g["name"] for g in result["gates"]}
        self.assertNotIn("cost_stress", gate_names,
                         "cost_stress gate omitted when skip_deep_checks=True")
        self.assertNotIn("walk_forward", gate_names,
                         "walk_forward gate omitted when skip_deep_checks=True")

    def test_deep_checks_gate_counts_increase(self) -> None:
        """Number of gates with deep checks > number without."""
        deep_request = {**self.base_request, "skip_deep_checks": False}
        skip_request = {**self.base_request, "skip_deep_checks": True}
        deep_result = self.service.evaluate(deep_request)
        skip_result = self.service.evaluate(skip_request)
        self.assertGreater(len(deep_result["gates"]), len(skip_result["gates"]),
                           "deep checks add 2 additional gates (cost_stress + walk_forward)")

    def test_cost_stress_gate_has_expected_structure(self) -> None:
        """Each cost_stress gate entry has required fields."""
        result = self.service.evaluate(dict(self.base_request))
        cost_gate = next(g for g in result["gates"] if g["name"] == "cost_stress")
        for key in ("name", "status", "message", "metrics", "threshold"):
            self.assertIn(key, cost_gate, f"cost_stress gate missing '{key}'")
        self.assertIn("survival_rate_pct", cost_gate["metrics"],
                      "cost_stress metrics must include survival_rate_pct")

    def test_walk_forward_gate_has_expected_structure(self) -> None:
        """Each walk_forward gate entry has required fields."""
        result = self.service.evaluate(dict(self.base_request))
        wf_gate = next(g for g in result["gates"] if g["name"] == "walk_forward")
        for key in ("name", "status", "message", "metrics", "threshold"):
            self.assertIn(key, wf_gate, f"walk_forward gate missing '{key}'")

    # ------------------------------------------------------------------
    # Decision and next_stage transitions (via mocking for determinism)
    # ------------------------------------------------------------------

    def test_next_stage_is_blocked_when_walk_forward_fails(self) -> None:
        """All deep checks present, walk-forward gate=fail => decision=fail => next_stage=blocked."""
        with (
            patch.object(ResearchBacktestService, "run_cost_stress",
                         return_value={"survival_rate_pct": 100.0, "status": "completed"}),
            patch.object(ResearchBacktestService, "run_walk_forward",
                         return_value={"stability": {"pass_rate_pct": 0.0, "window_count": 0}}),
            patch.object(ResearchBacktestService, "run_single",
                         return_value=_mock_artifacts()),
        ):
            result = self.service.evaluate(dict(self.base_request))
            gate_map = {g["name"]: g["status"] for g in result["gates"]}
            self.assertEqual(gate_map["cost_stress"], "pass")
            self.assertEqual(gate_map["walk_forward"], "fail")
            self.assertEqual(result["decision"], "fail",
                             "walk-forward fail should produce overall 'fail' decision")
            self.assertEqual(result["next_stage"], "blocked",
                             "fail decision maps to next_stage=blocked")

    def test_next_stage_is_research_iteration_when_warn_only(self) -> None:
        """All deep checks pass, cost_stress warns only => decision=warn => next_stage=research_iteration."""
        with (
            patch.object(ResearchBacktestService, "run_cost_stress",
                         return_value={"survival_rate_pct": 99.0, "status": "completed"}),
            patch.object(ResearchBacktestService, "run_walk_forward",
                         return_value={"stability": {"pass_rate_pct": 100.0, "window_count": 2}}),
            patch.object(ResearchBacktestService, "run_single",
                         return_value=_mock_artifacts()),
        ):
            result = self.service.evaluate(dict(self.base_request))
            gate_map = {g["name"]: g["status"] for g in result["gates"]}
            self.assertEqual(gate_map["cost_stress"], "warn")
            self.assertEqual(gate_map["walk_forward"], "pass")
            self.assertEqual(result["decision"], "warn")
            self.assertEqual(result["next_stage"], "research_iteration")

    def test_next_stage_is_paper_candidate_when_all_deep_pass(self) -> None:
        """All gates pass and deep not skipped => next_stage=paper_candidate."""
        with (
            patch.object(ResearchBacktestService, "run_cost_stress",
                         return_value={"survival_rate_pct": 100.0, "status": "completed"}),
            patch.object(ResearchBacktestService, "run_walk_forward",
                         return_value={"stability": {"pass_rate_pct": 100.0, "window_count": 2}}),
            patch.object(ResearchBacktestService, "run_single",
                         return_value=_mock_artifacts()),
        ):
            result = self.service.evaluate(dict(self.base_request))
            gate_map = {g["name"]: g["status"] for g in result["gates"]}
            self.assertEqual(gate_map["cost_stress"], "pass")
            self.assertEqual(gate_map["walk_forward"], "pass")
            self.assertEqual(result["decision"], "pass")
            self.assertEqual(result["next_stage"], "paper_candidate")

    def test_next_stage_blocked_when_basic_gate_fails_independent_of_deep(self) -> None:
        """A failing basic gate (data_quality) produces 'blocked' regardless of deep check outcome."""
        with (
            patch.object(ResearchBacktestService, "run_cost_stress",
                         return_value={"survival_rate_pct": 100.0, "status": "completed"}),
            patch.object(ResearchBacktestService, "run_walk_forward",
                         return_value={"stability": {"pass_rate_pct": 100.0, "window_count": 2}}),
            patch.object(ResearchBacktestService, "run_single",
                         return_value=_mock_artifacts(sharpe_ratio=-0.5, total_return_pct=-3.0)),
        ):
            result = self.service.evaluate(dict(self.base_request))
            self.assertEqual(result["decision"], "fail")
            self.assertEqual(result["next_stage"], "blocked",
                             "basic gate fail + deep pass should still be blocked")

    # ------------------------------------------------------------------
    # Decision logic: deep gates are part of overall decision
    # ------------------------------------------------------------------

    def test_deep_gates_contribute_to_overall_decision(self) -> None:
        """When deep gates are present, their statuses affect decision."""
        with (
            patch.object(ResearchBacktestService, "run_cost_stress",
                         return_value={"survival_rate_pct": 50.0, "status": "completed"}),
            patch.object(ResearchBacktestService, "run_walk_forward",
                         return_value={"stability": {"pass_rate_pct": 100.0, "window_count": 2}}),
            patch.object(ResearchBacktestService, "run_single",
                         return_value=_mock_artifacts()),
        ):
            result = self.service.evaluate(dict(self.base_request))
            gate_map = {g["name"]: g["status"] for g in result["gates"]}
            self.assertEqual(gate_map["cost_stress"], "fail")
            self.assertEqual(result["decision"], "fail",
                             "cost_stress fail should produce overall 'fail' decision")

    def test_deep_gates_listed_in_gates_list(self) -> None:
        """cost_stress and walk_forward gates appear in the gates list alongside basic gates."""
        result = self.service.evaluate(dict(self.base_request))
        gate_names = {g["name"] for g in result["gates"]}
        # Basic gates expected: data_quality, backtest_survival, execution_cost, portfolio_risk
        for basic in ("data_quality", "backtest_survival", "execution_cost", "portfolio_risk"):
            self.assertIn(basic, gate_names, f"basic gate '{basic}' must be present")
        # Deep gates are additional
        self.assertIn("cost_stress", gate_names)
        self.assertIn("walk_forward", gate_names)
        # Total gate count should be 4 basic + 2 deep = 6
        self.assertGreaterEqual(len(result["gates"]), 6)

    # ------------------------------------------------------------------
    # Error handling: insufficient data for walk-forward
    # ------------------------------------------------------------------

    def test_insufficient_data_walk_forward_error_handled(self) -> None:
        """Walk-forward returning error/insufficient-data status does not crash evaluate()."""
        wf_error_result = {
            "status": "error",
            "strategies": "trend_macd",
            "strategys_params": {},
            "windows": [],
            "regimes": [],
            "stability": {},
            "recommendations": ["Not enough bars for walk-forward validation, need at least 50."],
        }
        with patch.object(ResearchBacktestService, "run_walk_forward",
                          return_value=wf_error_result):
            # Should not raise KeyError or any other exception
            result = self.service.evaluate(dict(self.base_request))
            gate_names = {g["name"] for g in result["gates"]}
            self.assertIn("walk_forward", gate_names)
            wf_gate = next(g for g in result["gates"] if g["name"] == "walk_forward")
            # With empty stability, pass_rate defaults to 0 => fail
            self.assertIn(wf_gate["status"], ("fail", "warn"),
                          "insufficient-data walk-forward gate should show fail or warn")

    def test_insufficient_data_does_not_crash_manifest(self) -> None:
        """Manifest generation works even with walk-forward error result."""
        wf_error_result = {
            "status": "error",
            "stability": {"pass_rate_pct": 0.0},
            "windows": [],
            "regimes": [],
            "recommendations": ["Not enough bars."],
        }
        with patch.object(ResearchBacktestService, "run_walk_forward",
                          return_value=wf_error_result):
            request = {**self.base_request, "persist_manifest": True}
            result = self.service.evaluate(request)
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertIn("deep_checks", manifest)
            self.assertIn("walk_forward", manifest["deep_checks"])
            self.assertIn("cost_stress", manifest["deep_checks"])

    # ------------------------------------------------------------------
    # Portfolio mode deep checks
    # ------------------------------------------------------------------

    def test_portfolio_mode_deep_checks_use_portfolio_path(self) -> None:
        """Portfolio mode with skip_deep_checks=False uses _portfolio_deep_checks path."""
        with (
            patch.object(ResearchBacktestService, "optimize_portfolio",
                         return_value={
                             "status": "completed",
                             "risk_budget": {"max_pair_abs_correlation": 0.5, "active_gross_pct": 95.0},
                             "improvement": {"sharpe_delta": 0.1},
                         }),
            patch.object(ResearchBacktestService, "run_portfolio",
                         return_value=_mock_artifacts()),
        ):
            result = self.service.evaluate({
                "mode": "portfolio",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": datetime(2024, 1, 1),
                "end": datetime(2024, 2, 15),
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.6},
                    {"strategy_id": "reversion_rsi", "weight": 0.4},
                ],
                "skip_deep_checks": False,
            })
            gate_names = {g["name"] for g in result["gates"]}
            self.assertIn("portfolio_allocation", gate_names)

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    def test_deep_checks_complete_within_timeout(self) -> None:
        """Full evaluate() with deep checks completes within 60 seconds."""
        start = time.monotonic()
        self.service.evaluate(dict(self.base_request))
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 60.0,
                        f"Deep checks took {elapsed:.1f}s, exceeded 60s timeout")

    # ------------------------------------------------------------------
    # Edge: skip_deep_checks=False but mode="single" with a strategy
    # that has minimal trading activity
    # ------------------------------------------------------------------

    def test_deep_checks_accept_minimal_strategy_params(self) -> None:
        """Various strategy_params dicts do not crash deep checks."""
        for params in ({}, {"fast_window": 12, "slow_window": 48}, {"channel_window": 20}):
            request = {**self.base_request, "strategy_params": params}
            result = self.service.evaluate(request)
            self.assertIn(result["status"], ("completed",))
            gate_names = {g["name"] for g in result["gates"]}
            self.assertIn("cost_stress", gate_names)
            self.assertIn("walk_forward", gate_names)


if __name__ == "__main__":
    unittest.main()
