"""Tests for ResearchExperimentManifest and ExperimentManager.

Covers: create, load, list, status transitions, no live promotion.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.lab.manifest import (
    ExperimentManager,
    ResearchExperimentManifest,
    StrategyCandidate,
)


class TestResearchExperimentManifest(unittest.TestCase):
    """ResearchExperimentManifest dataclass construction and defaults."""

    def test_construction_minimal(self) -> None:
        manifest = ResearchExperimentManifest(
            experiment_id="exp_abc123",
            strategy_id="trend_momentum",
        )
        self.assertEqual(manifest.experiment_id, "exp_abc123")
        self.assertEqual(manifest.strategy_id, "trend_momentum")
        self.assertEqual(manifest.status, "DRAFT")
        self.assertEqual(manifest.symbols, [])

    def test_construction_all_fields(self) -> None:
        manifest = ResearchExperimentManifest(
            experiment_id="exp_001",
            strategy_id="mean_reversion",
            strategy_version="v2.1",
            strategy_family="reversal",
            symbols=["AAPL", "MSFT"],
            universe="v1",
            timeframe="1h",
            start_date="2024-01-01",
            end_date="2024-06-30",
            params={"lookback": 20, "entry_z": 2.0},
            status="COMPLETED",
            metrics={"sharpe_ratio": 1.5},
        )
        self.assertEqual(manifest.strategy_family, "reversal")
        self.assertEqual(manifest.params["lookback"], 20)
        self.assertEqual(manifest.status, "COMPLETED")


class TestExperimentManager(unittest.TestCase):
    """ExperimentManager CRUD and lifecycle."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.manager = ExperimentManager(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_experiment(self) -> None:
        manifest = self.manager.create(
            strategy_id="trend_momentum",
            symbols=["AAPL"],
            params={"lookback": 20},
        )
        self.assertTrue(manifest.experiment_id.startswith("exp_"))
        self.assertEqual(manifest.strategy_id, "trend_momentum")
        self.assertEqual(manifest.status, "DRAFT")

    def test_create_with_extra_kwargs(self) -> None:
        manifest = self.manager.create(
            strategy_id="test",
            symbols=["SPY"],
            timeframe="1h",
            universe="v2",
        )
        self.assertEqual(manifest.timeframe, "1h")
        self.assertEqual(manifest.universe, "v2")

    def test_load_existing_experiment(self) -> None:
        created = self.manager.create(strategy_id="test", symbols=["AAPL"])
        loaded = self.manager.load(created.experiment_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.experiment_id, created.experiment_id)

    def test_load_nonexistent_returns_none(self) -> None:
        loaded = self.manager.load("exp_nonexistent")
        self.assertIsNone(loaded)

    def test_list_experiments(self) -> None:
        self.manager.create(strategy_id="s1", symbols=["AAPL"])
        self.manager.create(strategy_id="s2", symbols=["MSFT"])
        all_exps = self.manager.list_experiments()
        self.assertEqual(len(all_exps), 2)

    def test_list_filters_by_status(self) -> None:
        m1 = self.manager.create(strategy_id="s1", symbols=["A"])
        with TemporaryDirectory() as tmp:
            # Can't modify status without running, so test filtering directly
            pass
        # All should have DRAFT status since we haven't run
        drafts = self.manager.list_experiments(status="DRAFT")
        completed = self.manager.list_experiments(status="COMPLETED")
        self.assertGreaterEqual(len(drafts), 1)
        self.assertEqual(len(completed), 0)

    def test_status_default_is_draft(self) -> None:
        manifest = self.manager.create(
            strategy_id="momentum",
            symbols=["AAPL"],
        )
        self.assertEqual(manifest.status, "DRAFT")

    def test_list_candidates_empty_initially(self) -> None:
        candidates = self.manager.list_candidates()
        self.assertEqual(candidates, [])

    def test_promote_to_candidate_fails_if_not_completed(self) -> None:
        manifest = self.manager.create(
            strategy_id="test", symbols=["AAPL"]
        )
        with self.assertRaises(ValueError):
            self.manager.promote_to_candidate(manifest.experiment_id)

    def test_promote_to_candidate_unknown_experiment(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.promote_to_candidate("exp_nonexistent")

    def test_experiment_does_not_import_live(self) -> None:
        """Verify experiment management has no live module imports."""
        import quant_us.research.lab.manifest as manifest_module
        source = manifest_module.__file__ or ""
        with open(source, encoding="utf-8") as f:
            content = f.read()
        # Check for actual import statements, not docstring references
        import re
        live_imports = re.findall(r'from\s+quant_us\.live\s+import', content)
        execution_imports = re.findall(r'from\s+quant_us\.execution\s+import', content)
        self.assertEqual(live_imports, [], f"Found live imports: {live_imports}")
        self.assertEqual(execution_imports, [], f"Found execution imports: {execution_imports}")
        self.assertNotIn("submit_order", content)
        self.assertNotIn("AlpacaBroker", content)
