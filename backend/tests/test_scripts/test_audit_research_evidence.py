from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SPEC = importlib.util.spec_from_file_location(
    "audit_research_evidence_test",
    str(_SCRIPTS_DIR / "audit_research_evidence.py"),
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
_PLAN_SPEC = importlib.util.spec_from_file_location(
    "plan_research_evidence_migration_test",
    str(_SCRIPTS_DIR / "plan_research_evidence_migration.py"),
)
_PLAN_MODULE = importlib.util.module_from_spec(_PLAN_SPEC)
sys.modules[_PLAN_SPEC.name] = _PLAN_MODULE
_PLAN_SPEC.loader.exec_module(_PLAN_MODULE)


class TestAuditResearchEvidenceScript(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _data_manifest_payload(
        self,
        data_version: str,
        *,
        coverage_pct: float = 100.0,
        quality_score: float = 95.0,
        checksum: str = "a" * 64,
    ) -> dict:
        return {
            "data_version": data_version,
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "asset_class": "equity",
            "timezone": "UTC",
            "adjustment": "raw",
            "adjustment_policy": "raw",
            "corporate_action_adjustment": "raw",
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2024-12-31T00:00:00+00:00",
            "row_count": 252,
            "expected_rows": 252,
            "coverage_pct": coverage_pct,
            "fingerprint": checksum,
            "checksum": checksum,
            "quality_score": quality_score,
            "created_at": "2026-05-09T12:00:00+00:00",
            "fields": ["timestamp", "open", "high", "low", "close", "volume"],
            "issues": [],
            "cleaning": {},
            "quality_summary": {},
            "raw_path": "data/raw/aapl.csv",
            "cleaned_path": "data/clean/aapl.parquet",
            "git_commit": "abc1234",
            "universe_id": "us_equity_core",
            "universe_source": "governed",
            "survivorship_bias_risk": "clean",
        }

    def _write_data_manifest(
        self,
        root: Path,
        data_version: str,
        *,
        filename: str | None = None,
        coverage_pct: float = 100.0,
        quality_score: float = 95.0,
        checksum: str = "a" * 64,
    ) -> dict:
        payload = self._data_manifest_payload(
            data_version,
            coverage_pct=coverage_pct,
            quality_score=quality_score,
            checksum=checksum,
        )
        self._write_json(
            root / "manifests" / f"{filename or data_version}.json",
            payload,
        )
        return payload

    def _write_candidate(
        self,
        root: Path,
        candidate_id: str,
        *,
        data_version: str,
        backtest_manifest_path: str | None = None,
        inline_backtest_manifest: dict | None = None,
    ) -> Path:
        payload = {
            "candidate_id": candidate_id,
            "experiment_id": f"exp_{candidate_id}",
            "strategy_id": "momentum",
            "promotion_status": "RESEARCH_ONLY",
            "data_version": data_version,
            "symbols": ["AAPL"],
            "metrics": {"sharpe": 1.2},
        }
        if backtest_manifest_path is not None:
            payload["backtest_manifest_path"] = backtest_manifest_path
        if inline_backtest_manifest is not None:
            payload["backtest_manifest"] = inline_backtest_manifest
        return self._write_json(
            root / "research" / "candidates" / candidate_id / "candidate.json",
            payload,
        )

    def _write_backtest_manifest(
        self,
        root: Path,
        candidate_id: str,
        *,
        data_version: str,
        embedded_data_manifest: dict | None,
        filename: str = "run_manifest.json",
    ) -> Path:
        payload = {
            "manifest_schema_version": "backtest_run_v2",
            "engine": "event_driven",
            "canonical_for_promotion": True,
            "run_id": f"run_{candidate_id}",
            "data_version": data_version,
            "strategy_version": "momentum@1.0.0",
            "commit_hash": "abc1234",
            "ledger_artifact_hash": "ledgerhash",
            "reconciliation": {"summary": {"passed": True}},
        }
        if embedded_data_manifest is not None:
            payload["data_manifest"] = embedded_data_manifest
        return self._write_json(
            root / "research" / "backtests" / candidate_id / filename,
            payload,
        )

    def test_audit_clean_report_has_no_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_version = "qs-yfinance-AAPL-1d-clean"
            manifest_payload = self._write_data_manifest(root, data_version)
            self._write_candidate(
                root,
                "cand_clean",
                data_version=data_version,
                backtest_manifest_path="research/backtests/cand_clean/run_manifest.json",
            )
            self._write_backtest_manifest(
                root,
                "cand_clean",
                data_version=data_version,
                embedded_data_manifest=manifest_payload,
            )

            report = _MODULE.audit_research_evidence(data_root=str(root))

            self.assertTrue(report["dry_run"])
            self.assertEqual(report["scope"], "report_only")
            self.assertEqual(report["counts"]["blocker_count"], 0)
            self.assertEqual(report["candidates"][0]["blocker_codes"], [])
            self.assertEqual(report["data_manifests"][0]["blocker_codes"], [])
            self.assertEqual(report["migration_plan"]["counts"]["item_count"], 0)
            self.assertEqual(report["migration_plan"]["blocker_categories"], [])

    def test_audit_reports_expected_blockers_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            low_quality_version = "qs-yfinance-AAPL-1d-low"
            low_quality_manifest = self._write_data_manifest(
                root,
                low_quality_version,
                coverage_pct=85.0,
                quality_score=70.0,
                checksum="b" * 64,
            )
            missing_path_candidate = self._write_candidate(
                root,
                "cand_missing_path",
                data_version=low_quality_version,
                backtest_manifest_path=None,
            )
            self._write_backtest_manifest(
                root,
                "cand_missing_path",
                data_version=low_quality_version,
                embedded_data_manifest=low_quality_manifest,
            )

            dup_version = "qs-yfinance-AAPL-1d-dup"
            dup_manifest = self._write_data_manifest(root, dup_version, checksum="c" * 64)
            self._write_data_manifest(root, dup_version, filename=f"{dup_version}_extra", checksum="d" * 64)
            self._write_candidate(
                root,
                "cand_noncanonical",
                data_version=dup_version,
                backtest_manifest_path="research/backtests/cand_noncanonical/alt_run_manifest.json",
            )
            self._write_backtest_manifest(
                root,
                "cand_noncanonical",
                data_version=dup_version,
                embedded_data_manifest=dup_manifest,
                filename="alt_run_manifest.json",
            )

            stale_version = "qs-yfinance-AAPL-1d-stale"
            stale_manifest = self._data_manifest_payload(stale_version, checksum="e" * 64)
            self._write_json(root / "manifests" / f"{stale_version}_alternate.json", stale_manifest)
            self._write_candidate(
                root,
                "cand_stale_binding",
                data_version=stale_version,
                backtest_manifest_path="research/backtests/cand_stale_binding/run_manifest.json",
            )
            stale_embedded = dict(stale_manifest)
            stale_embedded["checksum"] = "f" * 64
            stale_embedded["fingerprint"] = "f" * 64
            self._write_backtest_manifest(
                root,
                "cand_stale_binding",
                data_version=stale_version,
                embedded_data_manifest=stale_embedded,
            )

            no_binding_version = "qs-yfinance-AAPL-1d-nobind"
            self._write_data_manifest(root, no_binding_version, checksum="g" * 64)
            self._write_candidate(
                root,
                "cand_missing_binding",
                data_version=no_binding_version,
                backtest_manifest_path="research/backtests/cand_missing_binding/run_manifest.json",
            )
            self._write_backtest_manifest(
                root,
                "cand_missing_binding",
                data_version=no_binding_version,
                embedded_data_manifest=None,
            )

            self._write_candidate(
                root,
                "cand_inline_only",
                data_version="qs-yfinance-AAPL-1d-inline",
                backtest_manifest_path=None,
                inline_backtest_manifest={"engine": "event_driven"},
            )

            before = json.loads(missing_path_candidate.read_text(encoding="utf-8"))
            report = _MODULE.audit_research_evidence(data_root=str(root))
            after = json.loads(missing_path_candidate.read_text(encoding="utf-8"))

            blocker_codes = {item["code"] for item in report["blockers"]}
            self.assertTrue(report["dry_run"])
            self.assertEqual(before, after)
            self.assertIn("missing_backtest_manifest_path", blocker_codes)
            self.assertIn("non_canonical_backtest_manifest_path", blocker_codes)
            self.assertIn("duplicate_data_version_manifests", blocker_codes)
            self.assertIn("stale_data_manifest", blocker_codes)
            self.assertIn("missing_embedded_data_manifest_binding", blocker_codes)
            self.assertIn("inline_only_backtest_manifest", blocker_codes)
            self.assertIn("low_quality_data_manifest", blocker_codes)

            migration_categories = {
                item["blocker_code"]: item for item in report["migration_plan"]["blocker_categories"]
            }
            missing_path_items = migration_categories["missing_backtest_manifest_path"]["items"]
            missing_path_by_candidate = {
                item["candidate_id"]: item for item in missing_path_items
            }
            self.assertEqual(
                set(missing_path_by_candidate),
                {"cand_missing_path", "cand_inline_only"},
            )
            self.assertTrue(
                missing_path_by_candidate["cand_missing_path"][
                    "existing_migration_script_compatible"
                ]
            )
            self.assertFalse(
                missing_path_by_candidate["cand_inline_only"][
                    "existing_migration_script_compatible"
                ]
            )
            self.assertIn(
                "migrate_backtest_manifest_path.py",
                missing_path_by_candidate["cand_missing_path"]["recommended_action"],
            )

            duplicate_items = migration_categories["duplicate_data_version_manifests"]["items"]
            duplicate_candidate_ids = {item["candidate_id"] for item in duplicate_items}
            self.assertEqual(duplicate_candidate_ids, {"cand_noncanonical"})
            self.assertFalse(duplicate_items[0]["existing_migration_script_compatible"])

            stale_manifest_items = migration_categories["stale_data_manifest"]["items"]
            self.assertEqual(stale_manifest_items[0]["candidate_id"], "cand_stale_binding")
            self.assertIn(
                "Restore the canonical manifest",
                stale_manifest_items[0]["recommended_action"],
            )

    def test_main_strict_exits_non_zero_when_blockers_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_candidate(
                root,
                "cand_strict",
                data_version="qs-yfinance-AAPL-1d-strict",
                backtest_manifest_path=None,
            )

            stdout = io.StringIO()
            with (
                patch("sys.argv", ["prog", "--data-root", str(root), "--strict"]),
                patch("sys.stdout", stdout),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    raise SystemExit(_MODULE.main())

            report = json.loads(stdout.getvalue())
            self.assertEqual(ctx.exception.code, 1)
            self.assertTrue(report["strict"])
            self.assertGreater(report["counts"]["blocker_count"], 0)

    def test_plan_script_outputs_read_only_json_and_strict_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_version = "qs-yfinance-AAPL-1d-plan"
            manifest_payload = self._write_data_manifest(root, data_version)
            candidate_path = self._write_candidate(
                root,
                "cand_plan",
                data_version=data_version,
                backtest_manifest_path=None,
            )
            self._write_backtest_manifest(
                root,
                "cand_plan",
                data_version=data_version,
                embedded_data_manifest=manifest_payload,
            )
            before = json.loads(candidate_path.read_text(encoding="utf-8"))

            stdout = io.StringIO()
            with (
                patch("sys.argv", ["prog", "--data-root", str(root), "--strict"]),
                patch("sys.stdout", stdout),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    raise SystemExit(_PLAN_MODULE.main())

            plan = json.loads(stdout.getvalue())
            after = json.loads(candidate_path.read_text(encoding="utf-8"))

            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual(plan["scope"], "report_only")
            self.assertTrue(plan["dry_run"])
            self.assertTrue(plan["strict"])
            self.assertEqual(before, after)
            self.assertEqual(plan["counts"]["existing_migration_script_compatible_count"], 1)
            category = {
                item["blocker_code"]: item for item in plan["blocker_categories"]
            }["missing_backtest_manifest_path"]
            self.assertEqual(category["items"][0]["candidate_id"], "cand_plan")
            self.assertTrue(category["items"][0]["existing_migration_script_compatible"])


if __name__ == "__main__":
    unittest.main()
