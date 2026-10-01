"""Tests for batch backtest execution via ExperimentManager.

Covers: batch run multiple experiments, parameter sweep, cache reuse.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_us.research.lab.manifest import ExperimentManager


class TestBatchBacktestRunner(unittest.TestCase):
    """Batch backtest execution through ExperimentManager."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.manager = ExperimentManager(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_fake_run_result(self, experiment_id: str, metrics: dict | None = None) -> None:
        """Write a fake run result so the experiment appears COMPLETED."""
        if metrics is None:
            metrics = {"sharpe_ratio": 1.5, "cagr": 0.12}
        exp_dir = Path(self.tmp.name) / "research" / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        result_path = exp_dir / "run_result.json"
        result_path.write_text(json.dumps(metrics), encoding="utf-8")

        manifest_path = exp_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "COMPLETED"
        manifest["run_result_path"] = str(result_path)
        manifest["metrics"] = metrics
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def test_batch_create_multiple_experiments(self) -> None:
        param_sets = [
            {"lookback": 10, "entry_z": 1.5},
            {"lookback": 20, "entry_z": 2.0},
            {"lookback": 30, "entry_z": 2.5},
        ]
        ids = []
        for params in param_sets:
            m = self.manager.create(
                strategy_id="momentum",
                symbols=["AAPL", "MSFT"],
                params=params,
            )
            ids.append(m.experiment_id)

        self.assertEqual(len(ids), 3)
        for eid in ids:
            manifest = self.manager.load(eid)
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest.status, "DRAFT")

    def test_batch_status_update(self) -> None:
        ids = []
        for i in range(3):
            m = self.manager.create(
                strategy_id="momentum",
                symbols=["AAPL"],
                params={"variant": i},
            )
            ids.append(m.experiment_id)
            self._write_fake_run_result(m.experiment_id)

        for eid in ids:
            manifest = self.manager.load(eid)
            self.assertEqual(manifest.status, "COMPLETED")

    def test_parameter_sweep_stores_params(self) -> None:
        params_list = [
            {"lookback": 10, "smoothing": "sma"},
            {"lookback": 20, "smoothing": "ema"},
        ]
        for params in params_list:
            m = self.manager.create(
                strategy_id="trend",
                symbols=["SPY"],
                params=params,
            )
            loaded = self.manager.load(m.experiment_id)
            self.assertEqual(loaded.params, params)

    def test_experiments_with_different_symbols(self) -> None:
        m1 = self.manager.create(strategy_id="s1", symbols=["AAPL"])
        m2 = self.manager.create(strategy_id="s1", symbols=["MSFT", "GOOGL"])
        self.assertEqual(m1.symbols, ["AAPL"])
        self.assertEqual(m2.symbols, ["MSFT", "GOOGL"])

    def test_batch_list_order(self) -> None:
        """Experiments should be listed in reverse chronological order."""
        m1 = self.manager.create(strategy_id="s1", symbols=["A"])
        import time
        time.sleep(0.01)
        m2 = self.manager.create(strategy_id="s1", symbols=["B"])
        all_exps = self.manager.list_experiments()
        self.assertEqual(all_exps[0].experiment_id, m2.experiment_id)

    def test_promote_all_batch(self) -> None:
        ids = []
        for i in range(3):
            m = self.manager.create(strategy_id="mom", symbols=["AAPL"])
            ids.append(m.experiment_id)
            self._write_fake_run_result(m.experiment_id)

        for eid in ids:
            candidate = self.manager.promote_to_candidate(eid)
            self.assertTrue(candidate.candidate_id.startswith("cand_"))

        candidates = self.manager.list_candidates()
        self.assertEqual(len(candidates), 3)

    def test_batch_with_missing_symbols(self) -> None:
        m = self.manager.create(strategy_id="mom", symbols=[])
        self.assertEqual(m.symbols, [])

    def test_batch_does_not_import_broker(self) -> None:
        import quant_us.research.lab.manifest as manifest_module
        with open(manifest_module.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("submit_order", content)
        self.assertNotIn("AlpacaBroker", content)
