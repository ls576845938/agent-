"""Comprehensive tests for quant_us.research.experiments.

Covers ExperimentSpec, ArtifactRef, ExperimentRecord, ExperimentRegistry
(create_record, register, load_records, compare), ModelArtifact, and
_to_jsonable serialisation.

Uses synthetic data and TemporaryDirectory for all file I/O -- no network,
no real backtest engine.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from datetime import date, datetime, timezone
from tempfile import TemporaryDirectory
from typing import Any

from quant_us.research.experiments import (
    ArtifactRef,
    ExperimentRecord,
    ExperimentRegistry,
    ExperimentSpec,
    ModelArtifact,
    _to_jsonable,
)


def _spec(**overrides: Any) -> ExperimentSpec:
    """Factory that returns a minimal ExperimentSpec with caller overrides."""
    defaults: dict[str, Any] = {
        "experiment_name": "test_experiment",
        "run_type": "backtest",
        "symbols": ["AAPL"],
        "start": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "end": datetime(2024, 6, 30, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return ExperimentSpec(**defaults)


class TestExperimentSpec(unittest.TestCase):
    """ExperimentSpec dataclass construction and defaults."""

    def test_construction_all_fields(self) -> None:
        """All fields passed explicitly are stored correctly."""
        spec = _spec(
            experiment_name="momentum_v3",
            run_type="walk_forward",
            symbols=["AAPL", "MSFT"],
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 12, 31, tzinfo=timezone.utc),
            strategy_id="mom",
            strategy_version="v3.1",
            data_vendor="polygon",
            asset_class="equity",
            bar_size="1h",
            feature_version="fv2",
            data_version="dv3",
            dataset_run_id="ds_run_abc",
            model_id="lgbm_1",
            promotion_decision="promote",
            promotion_stage="prod",
            promotion_manifest_id="pm_xyz",
            parameters={"lookback": 20, "threshold": 0.5},
            tags=["unit", "regression"],
            notes="A note about this experiment.",
        )
        self.assertEqual(spec.experiment_name, "momentum_v3")
        self.assertEqual(spec.run_type, "walk_forward")
        self.assertEqual(spec.symbols, ["AAPL", "MSFT"])
        self.assertEqual(spec.strategy_id, "mom")
        self.assertEqual(spec.strategy_version, "v3.1")
        self.assertEqual(spec.data_vendor, "polygon")
        self.assertEqual(spec.asset_class, "equity")
        self.assertEqual(spec.bar_size, "1h")
        self.assertEqual(spec.feature_version, "fv2")
        self.assertEqual(spec.data_version, "dv3")
        self.assertEqual(spec.dataset_run_id, "ds_run_abc")
        self.assertEqual(spec.model_id, "lgbm_1")
        self.assertEqual(spec.promotion_decision, "promote")
        self.assertEqual(spec.promotion_stage, "prod")
        self.assertEqual(spec.promotion_manifest_id, "pm_xyz")
        self.assertEqual(spec.parameters, {"lookback": 20, "threshold": 0.5})
        self.assertEqual(spec.tags, ["unit", "regression"])
        self.assertEqual(spec.notes, "A note about this experiment.")

    def test_defaults(self) -> None:
        """Optional fields get the correct defaults."""
        spec = _spec()
        self.assertEqual(spec.strategy_id, "")
        self.assertEqual(spec.strategy_version, "")
        self.assertEqual(spec.data_vendor, "yfinance")
        self.assertEqual(spec.asset_class, "equity")
        self.assertEqual(spec.bar_size, "1d")
        self.assertEqual(spec.feature_version, "")
        self.assertEqual(spec.data_version, "")
        self.assertEqual(spec.dataset_run_id, "")
        self.assertEqual(spec.model_id, "")
        self.assertEqual(spec.promotion_decision, "")
        self.assertEqual(spec.promotion_stage, "")
        self.assertEqual(spec.promotion_manifest_id, "")
        self.assertEqual(spec.parameters, {})
        self.assertEqual(spec.tags, [])
        self.assertEqual(spec.notes, "")

    def test_frozen(self) -> None:
        """Modifying a field after construction raises FrozenInstanceError."""
        spec = _spec()
        with self.assertRaises(Exception):
            spec.experiment_name = "changed"  # type: ignore[misc]


class TestArtifactRef(unittest.TestCase):
    """ArtifactRef dataclass construction."""

    def test_basic_construction(self) -> None:
        """Minimal fields stored correctly."""
        ref = ArtifactRef("summary", "/path/to/summary.json", "json")
        self.assertEqual(ref.name, "summary")
        self.assertEqual(ref.path, "/path/to/summary.json")
        self.assertEqual(ref.artifact_type, "json")
        self.assertEqual(ref.metadata, {})

    def test_with_metadata(self) -> None:
        """Metadata dict is stored as provided."""
        ref = ArtifactRef(
            "params",
            "/tmp/params.yaml",
            "yaml",
            metadata={"rows": 500, "columns": ["a", "b"]},
        )
        self.assertEqual(ref.metadata, {"rows": 500, "columns": ["a", "b"]})

    def test_frozen(self) -> None:
        """Modifying an ArtifactRef field raises FrozenInstanceError."""
        ref = ArtifactRef("a", "/p", "t")
        with self.assertRaises(Exception):
            ref.name = "changed"  # type: ignore[misc]


class TestExperimentRecord(unittest.TestCase):
    """ExperimentRecord dataclass (created via ExperimentRegistry.create_record)."""

    def test_create_record_populates_fields(self) -> None:
        """create_record returns ExperimentRecord with generated id and timestamps."""
        registry = ExperimentRegistry("/tmp/_unused_test_create")
        spec = _spec()
        now_before = datetime.now(tz=timezone.utc)
        record = registry.create_record(
            run_id="run_001",
            spec=spec,
            metrics={"sharpe_ratio": 1.2, "total_return_pct": 3.5},
            artifacts=[ArtifactRef("summary", "/tmp/s.json", "json")],
        )
        now_after = datetime.now(tz=timezone.utc)

        self.assertIsInstance(record, ExperimentRecord)
        self.assertIsInstance(record.experiment_id, str)
        self.assertTrue(record.experiment_id.startswith("exp_"))
        self.assertEqual(record.run_id, "run_001")
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.spec, spec)
        self.assertEqual(record.metrics, {"sharpe_ratio": 1.2, "total_return_pct": 3.5})
        self.assertEqual(len(record.artifacts), 1)
        self.assertEqual(record.artifacts[0].name, "summary")
        self.assertIsNotNone(record.created_at)
        self.assertIsNotNone(record.completed_at)
        self.assertIsNone(record.error)
        # timestamps should be around now
        self.assertGreaterEqual(record.created_at, now_before)
        self.assertLessEqual(record.created_at, now_after)

    def test_create_record_with_error_status(self) -> None:
        """Failed status sets completed_at and error field."""
        registry = ExperimentRegistry("/tmp/_unused_test_error")
        record = registry.create_record(
            run_id="run_fail",
            spec=_spec(),
            metrics={},
            artifacts=[],
            status="failed",
            error="something went wrong",
        )
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.error, "something went wrong")
        self.assertIsNotNone(record.completed_at)

    def test_create_record_pending_status_no_completed_at(self) -> None:
        """Pending status leaves completed_at as None."""
        registry = ExperimentRegistry("/tmp/_unused_test_pending")
        record = registry.create_record(
            run_id="run_pending",
            spec=_spec(),
            metrics={},
            artifacts=[],
            status="running",
        )
        self.assertEqual(record.status, "running")
        self.assertIsNone(record.completed_at)
        self.assertIsNone(record.error)


class TestExperimentRegistry(unittest.TestCase):
    """ExperimentRegistry write / read / compare integration."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.root = self.tmpdir.name
        self.registry = ExperimentRegistry(self.root)

    def tearDown(self):
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # register & load_records
    # ------------------------------------------------------------------

    def test_register_returns_existing_path(self) -> None:
        """register writes a manifest file and returns its path."""
        spec = _spec()
        record = self.registry.create_record(
            run_id="run_register",
            spec=spec,
            metrics={"sharpe_ratio": 1.0},
            artifacts=[ArtifactRef("log", "/tmp/log.txt", "txt")],
        )
        manifest_path = self.registry.register(record)

        self.assertTrue(manifest_path.exists())
        self.assertEqual(manifest_path.suffix, ".json")
        self.assertIn("run_id=run_register", str(manifest_path))

    def test_register_writes_valid_json(self) -> None:
        """The written manifest is valid JSON and contains expected keys."""
        spec = _spec(experiment_name="json_test")
        record = self.registry.create_record(
            run_id="run_json",
            spec=spec,
            metrics={"sharpe_ratio": 0.9},
            artifacts=[ArtifactRef("chart", "/tmp/chart.png", "png")],
        )
        path = self.registry.register(record)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertIn("experiment_id", payload)
        self.assertIn("run_id", payload)
        self.assertIn("status", payload)
        self.assertIn("spec", payload)
        self.assertIn("metrics", payload)
        self.assertIn("artifacts", payload)
        self.assertIn("created_at", payload)
        self.assertEqual(payload["run_id"], "run_json")
        self.assertEqual(payload["metrics"]["sharpe_ratio"], 0.9)

    def test_register_appends_to_index_jsonl(self) -> None:
        """Each register call appends a line to index.jsonl."""
        for i in range(3):
            record = self.registry.create_record(
                run_id=f"run_{i}",
                spec=_spec(experiment_name="index_test"),
                metrics={"metric_a": float(i)},
                artifacts=[],
            )
            self.registry.register(record)

        lines = self.registry.index_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        for i, line in enumerate(lines):
            payload = json.loads(line)
            self.assertEqual(payload["run_id"], f"run_{i}")
            self.assertEqual(payload["metrics"]["metric_a"], float(i))

    def test_load_records_empty(self) -> None:
        """No index file yields empty list."""
        self.assertEqual(self.registry.load_records(), [])

    def test_load_records_all(self) -> None:
        """load_records returns all records when no filter."""
        for i in range(2):
            record = self.registry.create_record(
                run_id=f"r{i}",
                spec=_spec(),
                metrics={},
                artifacts=[],
            )
            self.registry.register(record)
        records = self.registry.load_records()
        self.assertEqual(len(records), 2)

    def test_load_records_filter_by_name(self) -> None:
        """load_records filters by experiment_name when provided."""
        # Register two experiments with different names
        spec_a = _spec(experiment_name="exp_a")
        spec_b = _spec(experiment_name="exp_b")

        rec_a = self.registry.create_record("r_a", spec_a, {"m": 1.0}, [])
        rec_b = self.registry.create_record("r_b", spec_b, {"m": 2.0}, [])

        self.registry.register(rec_a)
        self.registry.register(rec_b)

        filtered = self.registry.load_records("exp_a")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["run_id"], "r_a")

    def test_register_record_fields_in_manifest(self) -> None:
        """Registered manifest has run_id, artifacts, metrics visible in dict."""
        ref = ArtifactRef("summary", "/tmp/s.json", "json", metadata={"k": "v"})
        spec = _spec(parameters={"p1": 10})
        record = self.registry.create_record(
            run_id="field_check",
            spec=spec,
            metrics={"sharpe_ratio": 1.5, "total_return_pct": 4.2},
            artifacts=[ref],
        )
        path = self.registry.register(record)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "field_check")
        self.assertEqual(payload["metrics"]["sharpe_ratio"], 1.5)
        self.assertEqual(payload["metrics"]["total_return_pct"], 4.2)
        self.assertEqual(len(payload["artifacts"]), 1)
        self.assertEqual(payload["artifacts"][0]["name"], "summary")
        self.assertEqual(payload["artifacts"][0]["metadata"]["k"], "v")
        self.assertEqual(payload["spec"]["parameters"]["p1"], 10)

    # ------------------------------------------------------------------
    # compare
    # ------------------------------------------------------------------

    def test_compare_sorts_descending_by_default(self) -> None:
        """Compare returns results sorted by metric descending."""
        spec = _spec(experiment_name="cmp")
        low = self.registry.create_record("r_low", spec, {"sharpe_ratio": 0.5, "total_return_pct": 1.0, "max_drawdown_pct": -2.0}, [])
        high = self.registry.create_record("r_high", spec, {"sharpe_ratio": 1.2, "total_return_pct": 3.0, "max_drawdown_pct": -1.0}, [])
        self.registry.register(low)
        self.registry.register(high)

        rows = self.registry.compare(metric="sharpe_ratio", experiment_name="cmp")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["run_id"], "r_high")
        self.assertEqual(rows[0]["sharpe_ratio"], 1.2)
        self.assertEqual(rows[1]["run_id"], "r_low")
        self.assertEqual(rows[1]["sharpe_ratio"], 0.5)

    def test_compare_ascending(self) -> None:
        """descending=False sorts ascending."""
        spec = _spec(experiment_name="asc")
        low = self.registry.create_record("r_low", spec, {"sharpe_ratio": 0.5, "total_return_pct": 1.0, "max_drawdown_pct": -2.0}, [])
        high = self.registry.create_record("r_high", spec, {"sharpe_ratio": 1.2, "total_return_pct": 3.0, "max_drawdown_pct": -1.0}, [])
        self.registry.register(low)
        self.registry.register(high)

        rows = self.registry.compare(metric="sharpe_ratio", experiment_name="asc", descending=False)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["run_id"], "r_low")
        self.assertEqual(rows[0]["sharpe_ratio"], 0.5)

    def test_compare_skips_missing_metric(self) -> None:
        """Records lacking the sort metric are skipped."""
        spec = _spec(experiment_name="skip_missing")
        has_metric = self.registry.create_record("r_has", spec, {"sharpe_ratio": 1.0}, [])
        no_metric = self.registry.create_record("r_no", spec, {"other": 99.0}, [])
        self.registry.register(has_metric)
        self.registry.register(no_metric)

        rows = self.registry.compare(metric="sharpe_ratio", experiment_name="skip_missing")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "r_has")

    def test_compare_returns_useful_fields(self) -> None:
        """Compare results contain metadata fields needed for reporting."""
        spec = _spec(
            experiment_name="rich_cmp",
            strategy_id="strat_1",
            strategy_version="v1",
            data_version="dv1",
        )
        rec = self.registry.create_record(
            "r1", spec, {"sharpe_ratio": 1.0, "total_return_pct": 5.0, "max_drawdown_pct": -1.5}, []
        )
        self.registry.register(rec)
        rows = self.registry.compare(metric="sharpe_ratio", experiment_name="rich_cmp")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["experiment_name"], "rich_cmp")
        self.assertEqual(rows[0]["strategy_id"], "strat_1")
        self.assertEqual(rows[0]["strategy_version"], "v1")
        self.assertEqual(rows[0]["data_version"], "dv1")
        self.assertEqual(rows[0]["total_return_pct"], 5.0)
        self.assertEqual(rows[0]["max_drawdown_pct"], -1.5)

    def test_compare_empty_registry(self) -> None:
        """Compare on an empty registry returns an empty list."""
        rows = self.registry.compare(metric="sharpe_ratio")
        self.assertEqual(rows, [])

    def test_compare_no_match_for_experiment_name(self) -> None:
        """Experiment name with no matches returns empty list."""
        spec = _spec(experiment_name="exists")
        rec = self.registry.create_record("r1", spec, {"sharpe_ratio": 1.0}, [])
        self.registry.register(rec)
        rows = self.registry.compare(metric="sharpe_ratio", experiment_name="nonexistent")
        self.assertEqual(rows, [])

    # ------------------------------------------------------------------
    # Determinism
    # ------------------------------------------------------------------

    def test_identical_specs_produce_identical_comparison_fields(self) -> None:
        """Two records with same metadata fields compare identically (run_ids differ)."""
        spec = _spec(
            experiment_name="det",
            strategy_id="s",
            strategy_version="v1",
            data_version="dv1",
            parameters={"a": 1},
        )
        metrics = {"sharpe_ratio": 1.0, "total_return_pct": 5.0, "max_drawdown_pct": -1.0}
        r1 = self.registry.create_record("id_a", spec, metrics, [])
        r2 = self.registry.create_record("id_b", spec, metrics, [])
        self.registry.register(r1)
        self.registry.register(r2)

        rows = self.registry.compare(metric="sharpe_ratio", experiment_name="det")

        # Same values for all metadata fields (run_id differs)
        for row in rows:
            self.assertEqual(row["strategy_id"], "s")
            self.assertEqual(row["strategy_version"], "v1")
            self.assertEqual(row["data_version"], "dv1")
            self.assertEqual(row["sharpe_ratio"], 1.0)
            self.assertEqual(row["total_return_pct"], 5.0)
            self.assertEqual(row["max_drawdown_pct"], -1.0)


class TestModelArtifact(unittest.TestCase):
    """ModelArtifact construction and registration."""

    def test_construction(self) -> None:
        """Minimal ModelArtifact stores fields correctly."""
        artifact = ModelArtifact(
            model_id="m1",
            model_type="linear",
            path="/tmp/model.pkl",
            feature_names=["f1", "f2"],
            feature_version="v1",
            dataset_run_id="ds_1",
        )
        self.assertEqual(artifact.model_id, "m1")
        self.assertEqual(artifact.model_type, "linear")
        self.assertEqual(artifact.path, "/tmp/model.pkl")
        self.assertEqual(artifact.feature_names, ["f1", "f2"])
        self.assertEqual(artifact.feature_version, "v1")
        self.assertEqual(artifact.dataset_run_id, "ds_1")
        self.assertEqual(artifact.metrics, {})
        self.assertIsNotNone(artifact.created_at)
        self.assertEqual(artifact.metadata, {})

    def test_register_model_writes_manifest(self) -> None:
        """ExperimentRegistry.register_model writes a valid model manifest."""
        with TemporaryDirectory() as tmp:
            registry = ExperimentRegistry(tmp)
            artifact = ModelArtifact(
                model_id="lgbm_test",
                model_type="lightgbm",
                path="/models/lgbm_1.txt",
                feature_names=["mom", "vol"],
                feature_version="fv2",
                dataset_run_id="ds_abc",
                metrics={"ic": 0.03, "mse": 0.01},
                metadata={"training_rows": 10000},
            )
            manifest_path = registry.register_model(artifact)
            self.assertTrue(manifest_path.exists())

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["model_id"], "lgbm_test")
            self.assertEqual(payload["model_type"], "lightgbm")
            self.assertEqual(payload["feature_names"], ["mom", "vol"])
            self.assertEqual(payload["metrics"]["ic"], 0.03)
            self.assertEqual(payload["metadata"]["training_rows"], 10000)


class TestToJsonable(unittest.TestCase):
    """_to_jsonable serialisation helper."""

    def test_datetime_to_isoformat(self) -> None:
        """datetime becomes ISO-format string."""
        dt = datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        result = _to_jsonable(dt)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "2024-06-15T14:30:00+00:00")

    def test_date_to_isoformat(self) -> None:
        """date becomes ISO-format string."""
        d = date(2024, 6, 15)
        result = _to_jsonable(d)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "2024-06-15")

    def test_nested_dataclass(self) -> None:
        """Dataclass is converted to dict recursively."""
        ref = ArtifactRef("file", "/p", "csv", metadata={"size": 100})
        result = _to_jsonable(ref)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "file")
        self.assertEqual(result["path"], "/p")
        self.assertEqual(result["artifact_type"], "csv")
        self.assertEqual(result["metadata"]["size"], 100)

    def test_dict_with_mixed_types(self) -> None:
        """Nested dict with datetime values is serializable."""
        data = {
            "name": "test",
            "created": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "nested": {"value": 42, "flag": True},
        }
        result = _to_jsonable(data)
        self.assertIsInstance(result["created"], str)
        self.assertEqual(result["nested"]["value"], 42)

    def test_list_with_dates(self) -> None:
        """List of datetimes is converted to list of strings."""
        dates = [datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 6, 1, tzinfo=timezone.utc)]
        result = _to_jsonable(dates)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], str)

    def test_set_is_converted_to_list(self) -> None:
        """Set values become lists."""
        result = _to_jsonable({1, 2, 3})
        self.assertIsInstance(result, list)
        self.assertEqual(sorted(result), [1, 2, 3])

    def test_tuple_is_converted_to_list(self) -> None:
        """Tuple values become lists."""
        result = _to_jsonable((10, 20))
        self.assertIsInstance(result, list)
        self.assertEqual(result, [10, 20])

    def test_primitive_values_passthrough(self) -> None:
        """int, float, str, bool, None pass through unchanged."""
        for val in [42, 3.14, "hello", True, None]:
            self.assertEqual(_to_jsonable(val), val)

    def test_asdict_of_experiment_record_is_json_serializable(self) -> None:
        """asdict(ExperimentRecord) produces a JSON-serializable dict."""
        spec = _spec(
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 6, 30, tzinfo=timezone.utc),
        )
        registry = ExperimentRegistry("/tmp/_unused_serialize_test")
        record = registry.create_record(
            run_id="ser_test",
            spec=spec,
            metrics={"sharpe_ratio": 1.2},
            artifacts=[
                ArtifactRef("summary", "/tmp/s.json", "json", metadata={"rows": 100}),
            ],
        )
        d = _to_jsonable(asdict(record))
        # Should not raise
        serialized = json.dumps(d, indent=2)
        self.assertIsInstance(serialized, str)
        # Round-trip
        loaded = json.loads(serialized)
        self.assertEqual(loaded["run_id"], "ser_test")
        self.assertEqual(loaded["metrics"]["sharpe_ratio"], 1.2)
        self.assertEqual(loaded["spec"]["experiment_name"], "test_experiment")
        self.assertIsInstance(loaded["spec"]["start"], str)
        self.assertIsInstance(loaded["spec"]["end"], str)
        self.assertEqual(loaded["artifacts"][0]["name"], "summary")


if __name__ == "__main__":
    unittest.main()
