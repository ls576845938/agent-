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
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_SPEC = importlib.util.spec_from_file_location(
    "migrate_backtest_manifest_path_test",
    str(_SCRIPTS_DIR / "migrate_backtest_manifest_path.py"),
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_PLAN_SPEC = importlib.util.spec_from_file_location(
    "plan_research_evidence_migration_compat_test",
    str(_SCRIPTS_DIR / "plan_research_evidence_migration.py"),
)
_PLAN_MODULE = importlib.util.module_from_spec(_PLAN_SPEC)
_PLAN_SPEC.loader.exec_module(_PLAN_MODULE)


class TestMigrateBacktestManifestPathScript(unittest.TestCase):
    def _write_candidate(
        self,
        root: Path,
        candidate_id: str,
        *,
        backtest_manifest_path: str | None = None,
        inline_manifest: dict | None = None,
        raw_candidate_id: str | None = None,
    ) -> Path:
        candidate_dir = root / "research" / "candidates" / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate = {
            "candidate_id": raw_candidate_id or candidate_id,
            "strategy_id": "momentum",
            "metrics": {"sharpe": 1.2},
        }
        if backtest_manifest_path is not None:
            candidate["backtest_manifest_path"] = backtest_manifest_path
        if inline_manifest is not None:
            candidate["backtest_manifest"] = inline_manifest
        path = candidate_dir / "candidate.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        return path

    def _write_manifest(self, root: Path, candidate_id: str) -> Path:
        manifest_dir = root / "research" / "backtests" / candidate_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        path = manifest_dir / "run_manifest.json"
        path.write_text(
            json.dumps({"engine": "event_driven", "canonical_for_promotion": True}),
            encoding="utf-8",
        )
        return path

    def test_dry_run_reports_migration_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_candidate(root, "cand_ok")
            self._write_manifest(root, "cand_ok")

            report = _MODULE.audit_candidates(data_root=str(root), apply=False)

            self.assertEqual(report["counts"]["can_migrate"], 1)
            self.assertEqual(report["results"][0].candidate_id, "cand_ok")
            saved = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertNotIn("backtest_manifest_path", saved)

    def test_apply_writes_relative_backtest_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_candidate(root, "cand_apply")
            self._write_manifest(root, "cand_apply")

            report = _MODULE.audit_candidates(data_root=str(root), apply=True)

            self.assertEqual(report["counts"]["migrated"], 1)
            saved = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["backtest_manifest_path"],
                "research/backtests/cand_apply/run_manifest.json",
            )

    def test_inline_manifest_only_is_audited_and_not_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_candidate(
                root,
                "cand_inline",
                inline_manifest={"engine": "event_driven", "canonical_for_promotion": True},
            )

            report = _MODULE.audit_candidates(data_root=str(root), apply=True)

            self.assertEqual(report["counts"]["inline_manifest_only"], 1)
            saved = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertNotIn("backtest_manifest_path", saved)

    def test_existing_path_is_left_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_candidate(
                root,
                "cand_existing",
                backtest_manifest_path="research/backtests/cand_existing/run_manifest.json",
            )
            self._write_manifest(root, "cand_existing")

            report = _MODULE.audit_candidates(data_root=str(root), apply=True)

            self.assertEqual(report["counts"]["already_present"], 1)
            saved = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["backtest_manifest_path"],
                "research/backtests/cand_existing/run_manifest.json",
            )

    def test_main_prints_dry_run_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_candidate(root, "cand_cli")
            self._write_manifest(root, "cand_cli")

            stdout = io.StringIO()
            with (
                patch("sys.argv", ["prog", "--data-root", str(root)]),
                patch("sys.stdout", stdout),
            ):
                _MODULE.main()

            text = stdout.getvalue()
            self.assertIn("Legacy backtest_manifest_path migration [DRY-RUN]", text)
            self.assertIn("[can_migrate] cand_cli", text)
            self.assertIn("Summary:", text)

    def test_candidate_id_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_candidate(root, "cand_dir", raw_candidate_id="cand_payload")
            self._write_manifest(root, "cand_dir")

            report = _MODULE.audit_candidates(data_root=str(root), apply=True)

            self.assertEqual(report["counts"]["candidate_id_mismatch"], 1)

    def test_can_migrate_status_matches_read_only_planner_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_candidate(root, "cand_plan_match")
            self._write_manifest(root, "cand_plan_match")

            migration_audit = _MODULE.audit_candidates(data_root=str(root), apply=False)
            plan_stdout = io.StringIO()
            with (
                patch("sys.argv", ["prog", "--data-root", str(root)]),
                patch("sys.stdout", plan_stdout),
            ):
                _PLAN_MODULE.main()

            plan = json.loads(plan_stdout.getvalue())
            plan_items = {
                item["blocker_code"]: item for item in plan["blocker_categories"]
            }["missing_backtest_manifest_path"]["items"]

            self.assertEqual(migration_audit["results"][0].status, "can_migrate")
            self.assertEqual(plan_items[0]["candidate_id"], "cand_plan_match")
            self.assertTrue(plan_items[0]["existing_migration_script_compatible"])


if __name__ == "__main__":
    unittest.main()
