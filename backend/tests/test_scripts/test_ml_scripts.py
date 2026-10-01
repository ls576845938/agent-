"""Tests for ML/data scripts: build_features, build_ml_dataset, score_linear_model.

Each script is loaded via importlib so its main() can be tested without
polluting sys.path.  Heavy data / model dependencies are mocked.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Load scripts via importlib (each gets a unique module name)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"

# -- build_features.py --
_spec_bf = importlib.util.spec_from_file_location(
    "build_features_test", str(_SCRIPTS_DIR / "build_features.py")
)
_build_features = importlib.util.module_from_spec(_spec_bf)
_spec_bf.loader.exec_module(_build_features)

# -- build_ml_dataset.py --
_spec_bmd = importlib.util.spec_from_file_location(
    "build_ml_dataset_test", str(_SCRIPTS_DIR / "build_ml_dataset.py")
)
_build_ml_dataset = importlib.util.module_from_spec(_spec_bmd)
_spec_bmd.loader.exec_module(_build_ml_dataset)

# -- score_linear_model.py --
_spec_slm = importlib.util.spec_from_file_location(
    "score_linear_model_test", str(_SCRIPTS_DIR / "score_linear_model.py")
)
_score_linear_model = importlib.util.module_from_spec(_spec_slm)
_spec_slm.loader.exec_module(_score_linear_model)

# ---------------------------------------------------------------------------
# Shared synthetic data helpers
# ---------------------------------------------------------------------------

_BARS_DF = pd.DataFrame(
    {
        "symbol": ["AAPL"],
        "timestamp_utc": pd.to_datetime(["2024-01-02"]),
        "close": [150.0],
        "volume": [1_000_000],
        "open": [149.0],
        "high": [151.0],
        "low": [148.5],
    }
)

_FACTOR_VALUES_DF = pd.DataFrame(
    {
        "date": ["2024-01-02"],
        "symbol": ["AAPL"],
        "factor_name": ["momentum_score"],
        "factor_value": [0.05],
        "version": ["v1"],
        "universe": ["default"],
    }
)


# ===================================================================
# build_features.py
# ===================================================================


class TestBuildFeaturesScript(unittest.TestCase):
    """Tests for scripts/build_features.py"""

    def test_module_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_build_features)
        self.assertTrue(hasattr(_build_features, "main"))
        self.assertTrue(hasattr(_build_features, "parse_utc"))

    def test_help_exits_zero(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _build_features.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_main_function_callable(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_build_features.main))

    def test_main_mocked_feature_pipeline(self):
        """Mock FeaturePipeline and verify it runs with expected args."""
        mock_data_service = MagicMock()
        mock_data_service.read_cleaned_bars.return_value = _BARS_DF

        mock_feature_pipeline = MagicMock()
        mock_feature_result = MagicMock()
        mock_feature_result.status = "completed"
        mock_feature_pipeline.build_bar_factors.return_value = mock_feature_result

        with (
            patch.object(
                _build_features, "DataLakeService", return_value=mock_data_service
            ) as mock_dls_cls,
            patch.object(
                _build_features, "FeaturePipeline", return_value=mock_feature_pipeline
            ) as mock_fp_cls,
            patch("sys.argv", ["prog", "--symbol", "AAPL", "--start", "2024-01-01", "--end", "2024-01-10"]),
        ):
            _build_features.main()

        # Verify DataLakeService was created with a DataLakeConfig
        mock_dls_cls.assert_called_once()
        # Verify read_cleaned_bars was called for AAPL
        mock_data_service.read_cleaned_bars.assert_called_once()
        _call_args, call_kwargs = mock_data_service.read_cleaned_bars.call_args
        self.assertEqual(call_kwargs["symbol"], "AAPL")

        # Verify FeaturePipeline was created
        mock_fp_cls.assert_called_once()
        # Verify build_bar_factors was called with correct params
        mock_feature_pipeline.build_bar_factors.assert_called_once()
        __, bf_kwargs = mock_feature_pipeline.build_bar_factors.call_args
        self.assertEqual(bf_kwargs["universe"], "default")
        self.assertEqual(bf_kwargs["version"], "v1")


# ===================================================================
# build_ml_dataset.py
# ===================================================================


class TestBuildMLDatasetScript(unittest.TestCase):
    """Tests for scripts/build_ml_dataset.py"""

    def test_module_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_build_ml_dataset)
        self.assertTrue(hasattr(_build_ml_dataset, "main"))
        self.assertTrue(hasattr(_build_ml_dataset, "parse_utc"))
        self.assertTrue(hasattr(_build_ml_dataset, "parse_date"))

    def test_help_exits_zero(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _build_ml_dataset.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_main_function_callable(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_build_ml_dataset.main))

    def test_main_mocked_dataset_builder(self):
        """Mock data source and dataset builder, verify dataset building runs."""
        mock_data_service = MagicMock()
        mock_data_service.read_cleaned_bars.return_value = _BARS_DF

        mock_feature_store = MagicMock()
        mock_feature_store.read_factor_values.return_value = _FACTOR_VALUES_DF

        mock_builder = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.rows_written = 50
        mock_builder.build_from_bars_and_factors.return_value = mock_result

        with (
            patch.object(
                _build_ml_dataset, "DataLakeService", return_value=mock_data_service
            ) as mock_dls_cls,
            patch.object(
                _build_ml_dataset,
                "ParquetFeatureStore",
                return_value=mock_feature_store,
            ) as mock_pfs_cls,
            patch.object(
                _build_ml_dataset,
                "MLFeatureDatasetBuilder",
                return_value=mock_builder,
            ) as mock_mldb_cls,
            patch(
                "sys.argv",
                [
                    "prog",
                    "--symbols",
                    "AAPL,MSFT",
                    "--start",
                    "2024-01-01",
                    "--end",
                    "2024-01-10",
                ],
            ),
        ):
            _build_ml_dataset.main()

        # Verify DataLakeService was created
        mock_dls_cls.assert_called_once()
        # Verify read_cleaned_bars was called twice (once per symbol)
        self.assertEqual(mock_data_service.read_cleaned_bars.call_count, 2)

        # Verify ParquetFeatureStore was created
        mock_pfs_cls.assert_called_once()

        # Verify MLFeatureDatasetBuilder was created and called
        mock_mldb_cls.assert_called_once()
        mock_builder.build_from_bars_and_factors.assert_called_once()


# ===================================================================
# score_linear_model.py
# ===================================================================


class TestScoreLinearModelScript(unittest.TestCase):
    """Tests for scripts/score_linear_model.py"""

    def test_module_imports(self):
        """Module loads without error."""
        self.assertIsNotNone(_score_linear_model)
        self.assertTrue(hasattr(_score_linear_model, "main"))
        self.assertTrue(hasattr(_score_linear_model, "load_json_arg"))

    def test_help_exits_zero(self):
        """--help exits 0."""
        with patch("sys.argv", ["prog", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                _score_linear_model.main()
            self.assertEqual(ctx.exception.code, 0)

    def test_main_function_callable(self):
        """main() exists and is callable."""
        self.assertTrue(callable(_score_linear_model.main))

    def test_main_mocked_scoring(self):
        """Mock model loader and verify scoring runs."""
        mock_score_builder = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_score_builder.score_dataset.return_value = mock_result

        with (
            patch.object(
                _score_linear_model,
                "LinearModelScoreBuilder",
                return_value=mock_score_builder,
            ) as mock_lmsb_cls,
            patch.object(_score_linear_model, "ExperimentRegistry"),
            patch(
                "sys.argv",
                [
                    "prog",
                    "--dataset-path",
                    "/tmp/test_dataset.parquet",
                    "--model-id",
                    "test_model_v1",
                    "--feature-names",
                    "momentum_score,realized_vol_20",
                ],
            ),
        ):
            _score_linear_model.main()

        # Verify LinearModelScoreBuilder was created
        mock_lmsb_cls.assert_called_once()

        # Verify score_dataset was called with correct dataset_path
        mock_score_builder.score_dataset.assert_called_once()
        _call_args, call_kwargs = mock_score_builder.score_dataset.call_args
        self.assertEqual(str(_call_args[0]), "/tmp/test_dataset.parquet")


if __name__ == "__main__":
    unittest.main()
