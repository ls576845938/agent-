"""Tests for ResearchAutomationPipeline.

Covers: full pipeline run, ranking, and manual-only PAPER_ELIGIBLE promotion.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from quant_us.research.automation.pipeline import ResearchAutomationPipeline
from quant_us.research.automation.report_gen import generate_v2
from quant_us.research.evidence_registry import (
    inspect_candidate_evidence,
    inspect_evidence_registry,
    rebuild_evidence_registry,
)
from quant_us.research.lab.manifest import ExperimentManager


def _fake_manager_run(self, experiment_id: str) -> dict:
    """Mock ExperimentManager.run() to write fake results instead of real backtests.

    This avoids the need for real backtest infrastructure in unit tests.
    """
    import json
    from datetime import datetime

    manifest = self.load(experiment_id)
    if manifest is None:
        raise ValueError(f"Experiment {experiment_id} not found")

    fake_metrics = {
        "sharpe_ratio": 1.5,
        "cagr": 0.12,
        "max_drawdown_pct": 0.10,
        "total_return_pct": 0.15,
        "win_rate": 0.55,
        "trade_count": 50,
        "cost_sensitivity": 0.1,
        "walk_forward_pass_rate": 0.8,
        "oos_degradation": 0.1,
        "turnover": 0.2,
        "param_count": 4,
    }

    exp_dir = Path(self.data_root) / "research" / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    result_path = exp_dir / "run_result.json"
    result_path.write_text(json.dumps(fake_metrics, default=str), encoding="utf-8")

    manifest.status = "COMPLETED"
    manifest.run_result_path = str(result_path)
    manifest.metrics = fake_metrics
    self._save_manifest(manifest)
    return fake_metrics


class TestResearchAutomationPipeline(unittest.TestCase):
    """Pipeline orchestration tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.pipeline = ResearchAutomationPipeline(data_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_unified_backtest_fixture(
        self,
        *,
        candidate_id: str,
        experiment_id: str,
        reconciliation_passed: bool = False,
    ) -> None:
        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)

        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)

        experiment_dir = (
            Path(self.tmp.name) / "research" / "experiments" / experiment_id
        )
        experiment_dir.mkdir(parents=True, exist_ok=True)

        snapshot_failed = {
            "timestamp_utc": "2026-05-09T12:01:00+00:00",
            "ledger_cash": 99_000.0,
            "ledger_equity": 99_500.0,
            "snapshot_cash": 99_020.0,
            "snapshot_equity": 99_450.0,
            "diff": {"cash": -20.0, "equity": 50.0},
            "max_abs_diff": 50.0,
            "max_pct_diff": 0.05,
            "passed": False,
        }
        snapshot_passed = {
            "timestamp_utc": "2026-05-09T12:02:00+00:00",
            "ledger_cash": 99_500.0,
            "ledger_equity": 100_000.0,
            "snapshot_cash": 99_500.0,
            "snapshot_equity": 100_000.0,
            "diff": {"cash": 0.0, "equity": 0.0},
            "max_abs_diff": 0.0,
            "max_pct_diff": 0.0,
            "passed": True,
        }
        reconciliation_summary = {
            "snapshot_count": 2,
            "tolerance_pct": 0.01,
            "absolute_tolerance": 1e-6,
            "max_abs_diff": 50.0 if not reconciliation_passed else 0.0,
            "max_pct_diff": 0.05 if not reconciliation_passed else 0.0,
            "passed": reconciliation_passed,
            "message": "snapshot mismatch" if not reconciliation_passed else "clean",
        }
        corporate_actions_digest = {
            "total_dividends": 10.0,
            "total_borrow_fees": 0.0,
            "total_corporate_adjustments": 10.0,
            "adjustment_count": 1,
            "split_event_count": 0,
        }

        candidate_data = {
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "strategy_id": "momentum",
            "promotion_status": "RESEARCH_ONLY",
            "backtest_manifest_path": f"research/backtests/{candidate_id}/run_manifest.json",
            "metrics": {},
        }
        (candidate_dir / "candidate.json").write_text(
            json.dumps(candidate_data),
            encoding="utf-8",
        )

        (experiment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "experiment_id": experiment_id,
                    "strategy_id": "momentum",
                    "status": "COMPLETED",
                    "created_at": "2026-05-09T12:00:00+00:00",
                    "data_version": "qs-yfinance-AAPL-1d-report",
                }
            ),
            encoding="utf-8",
        )

        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "manifest_schema_version": "backtest_run_v2",
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "run_id": f"run_{candidate_id}",
                    "data_version": "qs-yfinance-AAPL-1d-report",
                    "strategy_version": "momentum@1.0.0",
                    "commit_hash": "abc1234",
                    "reconciliation": reconciliation_summary,
                    "corporate_actions": corporate_actions_digest,
                    "evidence": {
                        "reconciliation": {
                            "summary": reconciliation_summary,
                            "snapshots": [snapshot_failed, snapshot_passed],
                            "adjustment_cross_check": {
                                "timestamp_utc": "2026-05-09T12:03:00+00:00",
                                "replay_final_equity": 99_500.0,
                                "reconstructed_final_equity": 99_500.0,
                                "equity_diff": 0.0,
                                "passed": reconciliation_passed,
                            },
                        },
                        "corporate_actions": {
                            "summary": corporate_actions_digest,
                            "digest": corporate_actions_digest,
                            "adjustments": [
                                {
                                    "timestamp_utc": "2026-05-09T12:00:30+00:00",
                                    "symbol": "AAPL",
                                    "adjustment_type": "dividend",
                                    "amount": 10.0,
                                    "quantity_multiplier": 1.0,
                                    "avg_price_multiplier": 1.0,
                                    "description": "quarterly dividend",
                                    "has_position_impact": False,
                                }
                            ],
                        },
                        "equity": {
                            "consistent": reconciliation_passed,
                            "consistent_at_final_snapshot": reconciliation_passed,
                            "consistency_msg": "clean" if reconciliation_passed else "snapshot mismatch",
                        },
                        "orders": {
                            "count": 1,
                            "status_counts": {"filled": 1},
                            "oms_order_count": 1,
                            "all_orders_created_by_oms": True,
                            "all_orders_have_risk_check_id": True,
                        },
                        "fills": {
                            "count": 1,
                            "filled_order_count": 1,
                            "all_fills_match_orders": True,
                        },
                        "completeness": {
                            "missing_required_fields": [],
                            "ledger_evidence_complete": reconciliation_passed,
                            "data_manifest_bound": False,
                            "promotion_evidence_complete": reconciliation_passed,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_strategy_manifest_and_approved_review(
        self,
        *,
        candidate_id: str,
        manifest_id: str,
        review_id: str,
    ) -> None:
        manifest_dir = Path(self.tmp.name) / "research" / "manifests" / manifest_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": manifest_id,
                    "source_candidate_id": candidate_id,
                    "source_experiment_id": "exp_ready_review",
                    "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                    "created_at": "2026-05-09T12:10:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        review_dir = Path(self.tmp.name) / "research" / "paper_reviews" / review_id
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "review.json").write_text(
            json.dumps(
                {
                    "paper_review_id": review_id,
                    "strategy_manifest_id": manifest_id,
                    "status": "APPROVED_FOR_PAPER_ONLY",
                    "reviewer": "risk_committee",
                    "created_at": "2026-05-09T12:20:00+00:00",
                }
            ),
            encoding="utf-8",
        )

    def test_pipeline_initialization(self) -> None:
        self.assertIsNotNone(self.pipeline)

    def test_run_with_minimal_config(self) -> None:
        """Pipeline run with minimal config should not crash."""
        config = {
            "experiment_name": "test_pipeline",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "data_version": "v1",
            "feature_version": "v1",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        if result["status"] == "failed":
            self.fail(f"Pipeline failed with error: {result.get('error')}")
        self.assertEqual(result["status"], "completed")
        self.assertGreater(len(result["experiment_ids"]), 0)

    def test_pipeline_creates_experiments(self) -> None:
        config = {
            "experiment_name": "test_exp",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        for eid in result["experiment_ids"]:
            mgr = ExperimentManager(data_root=self.tmp.name)
            manifest = mgr.load(eid)
            self.assertIsNotNone(manifest)

    def test_pipeline_with_param_grid(self) -> None:
        config = {
            "experiment_name": "grid_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "param_grid": {"lookback": [10, 20], "entry_z": [1.5, 2.0]},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        if result["status"] == "failed":
            self.fail(f"Pipeline failed with error: {result.get('error')}")
        # At least the base experiment + walk-forward + cost stress + regime split
        self.assertGreater(len(result["experiment_ids"]), 5)

    def test_step_evaluate_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.pipeline.step_evaluate("exp_nonexistent")

    def test_step_rank_returns_list(self) -> None:
        config = {
            "experiment_name": "rank_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            self.pipeline.run(config)
        ranked = self.pipeline.step_rank()
        self.assertIsInstance(ranked, list)

    def test_step_promote_requires_explicit_manual_approval_after_gate(self) -> None:
        """READY_FOR_PAPER_REVIEW alone cannot write PAPER_ELIGIBLE."""
        cand_id = "cand_manual_test"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": cand_id,
                    "experiment_id": "exp_ready_manual",
                    "strategy_id": "momentum",
                    "promotion_status": "RESEARCH_ONLY",
                    "metrics": {"sharpe_ratio": 1.5},
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(
                self.pipeline,
                "_evaluate_promotion_gate",
                return_value={"decision": "READY_FOR_PAPER_REVIEW", "reasons": []},
            ),
            patch.object(self.pipeline, "_has_approved_paper_review", return_value=False),
        ):
            with self.assertRaisesRegex(ValueError, "manual_approval=True"):
                self.pipeline.step_promote(cand_id)

            candidate = self.pipeline.step_promote(cand_id, manual_approval=True)
        self.assertEqual(candidate.promotion_status, "PAPER_ELIGIBLE")

    def test_step_promote_accepts_approved_paper_review(self) -> None:
        """An approved paper review can satisfy the human approval requirement."""
        cand_id = "cand_review_path"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": cand_id,
                    "experiment_id": "exp_ready_review",
                    "strategy_id": "momentum",
                    "promotion_status": "RESEARCH_ONLY",
                    "metrics": {"sharpe_ratio": 1.5},
                }
            ),
            encoding="utf-8",
        )
        self._write_strategy_manifest_and_approved_review(
            candidate_id=cand_id,
            manifest_id="sman_ready_review",
            review_id="prev_ready_review",
        )

        with patch.object(
            self.pipeline,
            "_evaluate_promotion_gate",
            return_value={"decision": "READY_FOR_PAPER_REVIEW", "reasons": []},
        ):
            candidate = self.pipeline.step_promote(cand_id)
        self.assertEqual(candidate.promotion_status, "PAPER_ELIGIBLE")

    def test_step_promote_rejects_manual_approval_when_gate_not_ready(self) -> None:
        """Explicit manual approval cannot bypass the canonical promotion gate."""
        cand_id = "cand_gate_blocked"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": cand_id,
                    "experiment_id": "exp_gate_blocked",
                    "strategy_id": "momentum",
                    "promotion_status": "RESEARCH_ONLY",
                    "metrics": {"sharpe_ratio": 1.5},
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "READY_FOR_PAPER_REVIEW"):
            self.pipeline.step_promote(cand_id, manual_approval=True)

    def test_cannot_promote_unknown_candidate(self) -> None:
        with self.assertRaises(ValueError):
            self.pipeline.step_promote("cand_nonexistent")

    def test_cannot_promote_past_paper_eligible(self) -> None:
        """Cannot promote a candidate that is already PAPER_ELIGIBLE."""
        import json
        cand_id = "cand_already_promoted"
        cand_dir = Path(self.tmp.name) / "research" / "candidates" / cand_id
        cand_dir.mkdir(parents=True, exist_ok=True)
        candidate_data = {
            "candidate_id": cand_id,
            "experiment_id": "exp_001",
            "strategy_id": "momentum",
            "promotion_status": "PAPER_ELIGIBLE",
            "metrics": {"sharpe_ratio": 1.5},
        }
        (cand_dir / "candidate.json").write_text(
            json.dumps(candidate_data), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            self.pipeline.step_promote(cand_id)

    def test_pipeline_result_has_all_keys(self) -> None:
        config = {
            "experiment_name": "keys_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        expected_keys = [
            "pipeline_id", "experiment_ids", "candidate_ids",
            "ranked_candidates", "overfit_reports", "promotion_gate_results",
            "required_stages", "paper_review_ready", "dossier_paths",
            "report_paths", "promoted", "status",
        ]
        for key in expected_keys:
            self.assertIn(key, result)

    def test_pipeline_does_not_auto_mark_paper_eligible(self) -> None:
        """Automation may evaluate paper review readiness but must not set PAPER_ELIGIBLE."""
        config = {
            "experiment_name": "manual_gate_test",
            "strategy_id": "momentum",
            "symbols": ["AAPL"],
            "params": {"lookback": 20},
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
        }
        with patch.object(ExperimentManager, "run", _fake_manager_run):
            result = self.pipeline.run(config)
        self.assertEqual(result["status"], "completed")
        for cid in result["candidate_ids"]:
            cand_path = Path(self.tmp.name) / "research" / "candidates" / cid / "candidate.json"
            data = json.loads(cand_path.read_text(encoding="utf-8"))
            self.assertNotEqual(data["promotion_status"], "PAPER_ELIGIBLE")
            self.assertNotEqual(data["promotion_status"], "LIVE")
        self.assertEqual(result["paper_review_ready"], [])

    def test_evidence_registry_builds_candidate_chain(self) -> None:
        candidate_id = "cand_chain"
        experiment_id = "exp_chain"
        data_version = "qs-yfinance-AAPL-1d-chain"

        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": experiment_id,
                    "strategy_id": "momentum",
                    "data_version": data_version,
                    "promotion_status": "RESEARCH_ONLY",
                    "backtest_manifest_path": "research/backtests/cand_chain/run_manifest.json",
                    "created_at": "2026-05-09T12:00:00+00:00",
                    "metrics": {"sharpe_ratio": 1.2},
                }
            ),
            encoding="utf-8",
        )

        manifest_dir = Path(self.tmp.name) / "research" / "manifests" / "sman_chain"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": "sman_chain",
                    "source_candidate_id": candidate_id,
                    "source_experiment_id": experiment_id,
                    "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                    "created_at": "2026-05-09T12:10:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        paper_review_dir = Path(self.tmp.name) / "research" / "paper_reviews" / "prev_chain"
        paper_review_dir.mkdir(parents=True, exist_ok=True)
        (paper_review_dir / "review.json").write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_chain",
                    "strategy_manifest_id": "sman_chain",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": "2026-05-09T12:20:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)
        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "run_chain",
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "data_version": data_version,
                    "created_at": "2026-05-09T12:05:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        manifests_dir = Path(self.tmp.name) / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        (manifests_dir / f"{data_version}.json").write_text(
            json.dumps(
                {
                    "data_version": data_version,
                    "source": "yfinance",
                    "symbol": "AAPL",
                    "interval": "1d",
                    "quality_score": 95.0,
                    "created_at": "2026-05-09T11:55:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        pipeline_dir = Path(self.tmp.name) / "research" / "pipeline_results"
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        (pipeline_dir / "pipe_chain.json").write_text(
            json.dumps(
                {
                    "pipeline_id": "pipe_chain",
                    "created_at": "2026-05-09T12:15:00+00:00",
                    "status": "completed",
                    "paper_review_ready": [candidate_id],
                    "promotion_gate_results": {
                        candidate_id: {"decision": "READY_FOR_PAPER_REVIEW", "reasons": []}
                    },
                }
            ),
            encoding="utf-8",
        )

        reports_dir = Path(self.tmp.name) / "daily_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "daily_report_2026-05-09.json").write_text(
            json.dumps(
                {
                    "report_date": "2026-05-09",
                    "generated_at": "2026-05-09T20:00:00+00:00",
                    "reconciliation_status": "clean",
                    "orders_submitted": 3,
                    "kill_switch_triggered": False,
                }
            ),
            encoding="utf-8",
        )

        registry = rebuild_evidence_registry(self.tmp.name)
        chain = inspect_candidate_evidence(candidate_id, self.tmp.name)

        self.assertEqual(registry["counts"]["candidate_count"], 1)
        self.assertEqual(chain.status, "complete")
        self.assertEqual(chain.data_manifest.status, "present")
        self.assertEqual(chain.backtest_manifest.status, "present")
        self.assertEqual(chain.promotion_result.status, "present")
        self.assertEqual(chain.strategy_manifest.status, "present")
        self.assertEqual(chain.paper_review.status, "present")
        self.assertEqual(chain.daily_report.status, "present")
        self.assertEqual(chain.backtest_manifest.content_type, "application/json")
        self.assertTrue(chain.backtest_manifest.sha256)
        self.assertGreater(chain.backtest_manifest.size_bytes, 0)
        self.assertGreater(chain.backtest_manifest.mtime_ns, 0)
        self.assertEqual(chain.paper_review.content_type, "application/json")
        self.assertTrue(chain.paper_review.sha256)
        self.assertGreater(chain.paper_review.size_bytes, 0)
        self.assertGreater(chain.paper_review.mtime_ns, 0)

    def test_evidence_registry_marks_recoverable_backtest_link_stale(self) -> None:
        candidate_id = "cand_stale"

        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "candidate.json").write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": "exp_stale",
                    "strategy_id": "momentum",
                    "data_version": "qs-yfinance-AAPL-1d-stale",
                    "promotion_status": "RESEARCH_ONLY",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        backtest_dir = Path(self.tmp.name) / "research" / "backtests" / candidate_id
        backtest_dir.mkdir(parents=True, exist_ok=True)
        (backtest_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "run_stale",
                    "engine": "event_driven",
                    "canonical_for_promotion": True,
                    "data_version": "qs-yfinance-AAPL-1d-stale",
                    "created_at": "2026-05-09T12:05:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        chain = inspect_candidate_evidence(candidate_id, self.tmp.name, use_saved=False)
        registry = inspect_evidence_registry(self.tmp.name, use_saved=False)

        self.assertEqual(registry["chains"][candidate_id]["backtest_manifest"]["status"], "stale")
        self.assertEqual(chain.backtest_manifest.status, "stale")
        self.assertIn("backtest_manifest_link_missing_but_recoverable", chain.notes)

    def test_candidate_evidence_rebuilds_when_saved_registry_content_changed(self) -> None:
        candidate_id = "cand_changed"
        candidate_dir = Path(self.tmp.name) / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_dir / "candidate.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": "exp_before",
                    "strategy_id": "momentum",
                    "data_version": "qs-yfinance-AAPL-1d-changed",
                    "promotion_status": "RESEARCH_ONLY",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        rebuild_evidence_registry(self.tmp.name)

        candidate_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "experiment_id": "exp_after",
                    "strategy_id": "momentum",
                    "data_version": "qs-yfinance-AAPL-1d-changed",
                    "promotion_status": "RESEARCH_ONLY",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        registry = inspect_evidence_registry(
            self.tmp.name,
            use_saved=True,
            rebuild_if_missing=False,
        )
        chain = inspect_candidate_evidence(
            candidate_id,
            self.tmp.name,
            use_saved=True,
            rebuild_if_missing=False,
        )

        self.assertEqual(registry["registry_status"], "changed")
        self.assertTrue(any(note.startswith("content_changed:") for note in registry["registry_notes"]))
        self.assertEqual(chain.experiment_id, "exp_after")

    def test_promotion_gate_surfaces_reconciliation_and_corporate_actions(self) -> None:
        candidate_id = "cand_report_gate"
        experiment_id = "exp_report_gate"
        self._write_unified_backtest_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            reconciliation_passed=False,
        )

        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        gate = ResearchPromotionGate(data_root=self.tmp.name)
        result = gate.evaluate(candidate_id)

        self.assertIn("reconciliation", result.evidence)
        self.assertFalse(result.evidence["reconciliation"]["summary"]["passed"])
        self.assertEqual(result.evidence["reconciliation"]["summary"]["max_abs_diff"], 50.0)
        self.assertEqual(result.evidence["reconciliation"]["summary"]["max_pct_diff"], 0.05)
        self.assertEqual(result.evidence["reconciliation_passed"], False)
        self.assertEqual(result.evidence["reconciliation_failed_snapshot_count"], 1)
        self.assertIn("count=1", result.evidence["reconciliation_failed_snapshot_summary"])
        self.assertIn("max_abs_diff=50.0000", result.evidence["reconciliation_failed_snapshot_summary"])
        self.assertIn("corporate_actions", result.evidence)
        self.assertEqual(result.evidence["corporate_actions"]["digest"]["adjustment_count"], 1)
        self.assertEqual(result.evidence["corporate_actions_digest"]["total_dividends"], 10.0)

    def test_promotion_gate_does_not_treat_string_false_reconciliation_as_passed(self) -> None:
        candidate_id = "cand_report_string_false"
        experiment_id = "exp_report_string_false"
        self._write_unified_backtest_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            reconciliation_passed=False,
        )
        manifest_path = (
            Path(self.tmp.name)
            / "research"
            / "backtests"
            / candidate_id
            / "run_manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["evidence"]["reconciliation"]["summary"]["passed"] = "False"
        manifest["evidence"]["reconciliation"]["snapshots"][0]["passed"] = "False"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        result = ResearchPromotionGate(data_root=self.tmp.name).evaluate(candidate_id)

        self.assertFalse(result.evidence["reconciliation_passed"])
        self.assertEqual(result.evidence["reconciliation_failed_snapshot_count"], 1)
        self.assertIn(
            "reconciliation_failed: backtest reconciliation summary.passed is false",
            result.reasons,
        )

    def test_generate_v2_includes_unified_backtest_evidence(self) -> None:
        candidate_id = "cand_report_text"
        experiment_id = "exp_report_text"
        self._write_unified_backtest_fixture(
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            reconciliation_passed=False,
        )

        report = generate_v2(experiment_id, data_root=self.tmp.name)

        self.assertIn("## Unified Backtest Evidence", report)
        self.assertIn("Reconciliation Passed: False", report)
        self.assertIn("Max Abs Diff: 50.0000", report)
        self.assertIn("Max Pct Diff: 0.0500", report)
        self.assertIn("Failed Snapshot Summary:", report)
        self.assertIn("Corporate Actions Digest:", report)
        self.assertIn("adjustment_count=1", report)
        self.assertIn("total_dividends=10.0000", report)
        self.assertNotIn("Reconciliation Passed: True", report)
