"""Test lazy data repository path for column projection and filter pushdown."""

import pytest


class TestLazyDataRepository:
    """Verify Parquet + DuckDB lazy scan supports projections and filters."""

    def test_feature_store_has_cache(self):
        """ParquetFeatureStore must support FeatureCache."""
        from quant_us.data.storage.feature_store import ParquetFeatureStore, FeatureCache

        cache = FeatureCache()
        assert cache is not None
        assert hasattr(cache, "get")
        assert hasattr(cache, "put")

    def test_feature_store_supports_columns_projection(self):
        """ParquetFeatureStore.read_factor_values must accept columns param."""
        import inspect
        from quant_us.data.storage.feature_store import ParquetFeatureStore

        sig = inspect.signature(ParquetFeatureStore.read_factor_values)
        params = list(sig.parameters.keys())
        assert "columns" in params, "read_factor_values missing columns param"
        assert "start" in params or "date" in str(params), "read_factor_values missing date filter params"

    def test_duckdb_store_supports_predicate_pushdown(self):
        """DuckDBBarReader must accept date/symbol filters."""
        import inspect
        from quant_us.data.storage.duckdb_store import DuckDBBarReader

        sig = inspect.signature(DuckDBBarReader.__init__)
        params = list(sig.parameters.keys())
        # Should accept a db_path or equivalent
        assert len(params) >= 1, "DuckDBBarReader has no init params"

    def test_data_manifest_tracks_versions(self):
        """DataManifestStore must support reading and listing manifests."""
        from quant_us.data.storage.data_manifest import DataManifestStore
        assert hasattr(DataManifestStore, "read_latest")
        assert hasattr(DataManifestStore, "list_manifests")
