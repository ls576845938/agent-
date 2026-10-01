"""Tests for R1 Strategy Research Lab (quant_us.research.lab)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.lab.batch_runner import BatchBacktestRunner
from quant_us.research.lab.manifest import (
    ExperimentManager,
    ResearchExperimentManifest,
    StrategyCandidate,
)
from quant_us.research.lab.scorecard import ResearchScorecard, ResearchScorecardBuilder


class ExperimentManagerTest(unittest.TestCase):
    """Tests for experiment lifecycle: create, load, list, promote."""

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.root = self.tmpdir.name
        self.mgr = ExperimentManager(data_root=self.root)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_create_returns_manifest_with_draft_status(self) -> None:
        manifest = self.mgr.create(
            strategy_id="trend_momentum",
            symbols=["SPY", "QQQ"],
            params={"lookback": 20},
        )
        self.assertEqual(manifest.status, "DRAFT")
        self.assertEqual(manifest.strategy_id, "trend_momentum")
        self.assertEqual(manifest.symbols, ["SPY", "QQQ"])
        self.assertEqual(manifest.params, {"lookback": 20})
        self.assertTrue(manifest.experiment_id.startswith("exp_"))

    def test_create_persists_manifest_to_disk(self) -> None:
        manifest = self.mgr.create(
            strategy_id="trend_momentum",
            symbols=["SPY"],
        )
        manifest_path = (
            Path(self.root)
            / "research"
            / "experiments"
            / manifest.experiment_id
            / "manifest.json"
        )
        self.assertTrue(manifest_path.exists())
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["experiment_id"], manifest.experiment_id)
        self.assertEqual(data["strategy_id"], "trend_momentum")

    def test_load_returns_none_for_missing(self) -> None:
        result = self.mgr.load("exp_nonexistent")
        self.assertIsNone(result)

    def test_load_returns_manifest(self) -> None:
        created = self.mgr.create(strategy_id="test", symbols=["AAPL"])
        loaded = self.mgr.load(created.experiment_id)
        assert loaded is not None  # for type narrowing
        self.assertEqual(loaded.experiment_id, created.experiment_id)
        self.assertEqual(loaded.strategy_id, "test")

    def test_list_experiments_returns_all(self) -> None:
        self.mgr.create(strategy_id="a", symbols=["SPY"])
        self.mgr.create(strategy_id="b", symbols=["QQQ"])
        all_exps = self.mgr.list_experiments()
        self.assertEqual(len(all_exps), 2)

    def test_list_experiments_filters_by_status(self) -> None:
        self.mgr.create(strategy_id="a", symbols=["SPY"])
        ongoing = self.mgr.list_experiments(status="DRAFT")
        self.assertEqual(len(ongoing), 1)
        completed = self.mgr.list_experiments(status="COMPLETED")
        self.assertEqual(len(completed), 0)

    def test_list_experiments_sorts_by_created_at_desc(self) -> None:
        m1 = self.mgr.create(strategy_id="a", symbols=["A"])
        m2 = self.mgr.create(strategy_id="b", symbols=["B"])
        results = self.mgr.list_experiments()
        self.assertEqual(results[0].experiment_id, m2.experiment_id)
        self.assertEqual(results[1].experiment_id, m1.experiment_id)

    def test_promote_to_candidate_rejects_non_completed(self) -> None:
        manifest = self.mgr.create(strategy_id="test", symbols=["SPY"])
        with self.assertRaises(ValueError):
            self.mgr.promote_to_candidate(manifest.experiment_id)

    def test_promote_to_candidate_creates_candidate(self) -> None:
        manifest = self.mgr.create(strategy_id="test", symbols=["SPY"])
        # Manually set to COMPLETED so promotion works
        manifest.status = "COMPLETED"
        manifest.metrics = {"sharpe_ratio": 1.5, "total_return_pct": 0.12}
        manifest.run_result_path = "/fake/path.json"
        self.mgr._save_manifest(manifest)

        candidate = self.mgr.promote_to_candidate(manifest.experiment_id)
        self.assertEqual(candidate.strategy_id, "test")
        self.assertEqual(candidate.promotion_status, "RESEARCH_ONLY")
        self.assertEqual(candidate.metrics.get("sharpe_ratio"), 1.5)
        self.assertTrue(candidate.candidate_id.startswith("cand_"))

    def test_promote_updates_experiment_status(self) -> None:
        manifest = self.mgr.create(strategy_id="test", symbols=["SPY"])
        manifest.status = "COMPLETED"
        manifest.metrics = {"sharpe_ratio": 1.0}
        self.mgr._save_manifest(manifest)

        self.mgr.promote_to_candidate(manifest.experiment_id)
        reloaded = self.mgr.load(manifest.experiment_id)
        assert reloaded is not None
        self.assertEqual(reloaded.status, "PROMOTED_TO_CANDIDATE")

    def test_list_candidates_returns_all(self) -> None:
        # Create two COMPLETED experiments and promote both
        for s in ["a", "b"]:
            manifest = self.mgr.create(strategy_id=s, symbols=["SPY"])
            manifest.status = "COMPLETED"
            self.mgr._save_manifest(manifest)
            self.mgr.promote_to_candidate(manifest.experiment_id)

        candidates = self.mgr.list_candidates()
        self.assertEqual(len(candidates), 2)

    def test_settle_ensure_no_live_or_execution_imports(self) -> None:
        """The research.lab package must not import from live or execution."""
        import ast

        lab_init = Path(__file__).parent.parent.parent / "quant_us" / "research" / "lab" / "__init__.py"
        # Check the manifest, scorecard, and batch_runner modules
        for mod in ["manifest.py", "scorecard.py", "batch_runner.py"]:
            mod_path = Path(__file__).parent.parent.parent / "quant_us" / "research" / "lab" / mod
            if mod_path.exists():
                tree = ast.parse(mod_path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("quant_us.live") or alias.name.startswith("quant_us.execution"):
                                self.fail(f"{mod} imports forbidden module: {alias.name}")
                    if isinstance(node, ast.ImportFrom):
                        if node.module and (node.module.startswith("quant_us.live") or node.module.startswith("quant_us.execution")):
                            self.fail(f"{mod} imports forbidden module: {node.module}")


class ResearchScorecardBuilderTest(unittest.TestCase):
    """Tests for scorecard construction and rendering."""

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.root = self.tmpdir.name
        self.builder = ResearchScorecardBuilder(data_root=self.root)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _create_candidate(self, candidate_id: str, metrics: dict) -> Path:
        path = (
            Path(self.root)
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "candidate_id": candidate_id,
            "experiment_id": "exp_xxx",
            "strategy_id": "test",
            "metrics": metrics,
            "promotion_status": "RESEARCH_ONLY",
            "created_at": "2026-01-01T00:00:00",
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def test_build_creates_scorecard_from_candidate(self) -> None:
        self._create_candidate(
            "cand_001",
            {"sharpe_ratio": 2.1, "total_return_pct": 0.25, "max_drawdown_pct": -0.15},
        )
        sc = self.builder.build("cand_001")
        self.assertEqual(sc.candidate_id, "cand_001")
        self.assertAlmostEqual(sc.sharpe, 2.1)
        self.assertAlmostEqual(sc.cagr, 0.25)
        self.assertAlmostEqual(sc.max_drawdown, 0.15)

    def test_build_raises_for_missing_candidate(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.build("cand_nonexistent")

    def test_rank_candidates_returns_sorted(self) -> None:
        self._create_candidate(
            "cand_high",
            {"sharpe_ratio": 2.0, "total_return_pct": 0.20, "max_drawdown_pct": -0.05},
        )
        self._create_candidate(
            "cand_low",
            {"sharpe_ratio": 0.5, "total_return_pct": 0.05, "max_drawdown_pct": -0.20},
        )
        ranked = self.builder.rank_candidates(["cand_high", "cand_low", "cand_missing"])
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0][0], "cand_high")
        self.assertEqual(ranked[1][0], "cand_low")
        self.assertGreater(ranked[0][1], ranked[1][1])

    def test_to_markdown_renders_table(self) -> None:
        sc = ResearchScorecard(
            candidate_id="cand_md",
            cagr=0.15,
            sharpe=1.8,
            sortino=2.1,
            calmar=1.2,
            max_drawdown=0.12,
            win_rate=0.55,
            profit_factor=1.5,
            turnover=0.3,
            trade_count=50,
            avg_holding_period=5.0,
            robustness_score=0.75,
            overfit_risk="LOW",
        )
        md = self.builder.to_markdown(sc)
        self.assertIn("## Research Scorecard: cand_md", md)
        self.assertIn("CAGR", md)
        self.assertIn("15.00%", md)
        self.assertIn("1.80", md)
        self.assertIn("LOW", md)

    def test_scorecard_persisted_to_disk(self) -> None:
        self._create_candidate("cand_disk", {"sharpe_ratio": 1.0})
        self.builder.build("cand_disk")
        scorecard_path = (
            Path(self.root) / "research" / "scorecards" / "cand_disk.json"
        )
        self.assertTrue(scorecard_path.exists())
        data = json.loads(scorecard_path.read_text(encoding="utf-8"))
        self.assertEqual(data["candidate_id"], "cand_disk")


class BatchBacktestRunnerTest(unittest.TestCase):
    """Tests for batch runner logic (no actual data lake)."""

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.root = self.tmpdir.name
        self.mgr = ExperimentManager(data_root=self.root)
        self.runner = BatchBacktestRunner(data_root=self.root)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_run_experiments_empty_list(self) -> None:
        results = self.runner.run_experiments([])
        self.assertEqual(results, [])

    def test_run_experiments_fails_for_missing_ids(self) -> None:
        results = self.runner.run_experiments(["exp_nonexistent"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["experiment_id"], "exp_nonexistent")
        self.assertEqual(results[0]["status"], "FAILED")

    def test_run_parameter_sweep_creates_experiments(self) -> None:
        """run_parameter_sweep creates child experiments but fails at run (no data)."""
        base = self.mgr.create(
            strategy_id="trend_momentum",
            symbols=["SPY"],
            params={"lookback": 20},
            start_date="2020-01-01",
            end_date="2020-02-01",
        )
        results = self.runner.run_parameter_sweep(
            base.experiment_id,
            param_grid={"lookback": [10, 20]},
        )
        # The runs will fail (no data lake), but experiments should be created
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("experiment_id", r)
            self.assertIn("params", r)

    def test_run_multi_symbol_creates_experiments(self) -> None:
        base = self.mgr.create(
            strategy_id="trend_momentum",
            symbols=["SPY", "QQQ"],
            params={},
            start_date="2020-01-01",
            end_date="2020-02-01",
        )
        results = self.runner.run_multi_symbol(
            base.experiment_id,
            symbols=["AAPL", "MSFT"],
        )
        self.assertEqual(len(results), 2)
        symbols_seen = {r["symbol"] for r in results if "symbol" in r}
        self.assertEqual(symbols_seen, {"AAPL", "MSFT"})

    def test_run_parameter_sweep_raises_for_missing_base(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.run_parameter_sweep("exp_nonexistent", {"a": [1, 2]})

    def test_cache_features_raises_for_missing(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.cache_features("exp_nonexistent")


class ResearchExperimentManifestTest(unittest.TestCase):
    """Tests for manifest dataclass defaults and field types."""

    def test_default_status_is_draft(self) -> None:
        m = ResearchExperimentManifest(experiment_id="e1", strategy_id="s1", symbols=[])
        self.assertEqual(m.status, "DRAFT")

    def test_default_cost_model(self) -> None:
        m = ResearchExperimentManifest(experiment_id="e1", strategy_id="s1", symbols=[])
        self.assertEqual(m.cost_model, "default")


class StrategyCandidateTest(unittest.TestCase):
    """Tests for candidate dataclass defaults."""

    def test_default_promotion_status_is_research_only(self) -> None:
        c = StrategyCandidate(candidate_id="c1", experiment_id="e1", strategy_id="s1")
        self.assertEqual(c.promotion_status, "RESEARCH_ONLY")

    def test_scores_default_to_zero(self) -> None:
        c = StrategyCandidate(candidate_id="c1", experiment_id="e1", strategy_id="s1")
        self.assertEqual(c.robustness_score, 0.0)
        self.assertEqual(c.overfit_score, 0.0)
        self.assertEqual(c.alpha_score, 0.0)


if __name__ == "__main__":
    unittest.main()
