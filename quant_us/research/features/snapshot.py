"""Feature snapshot manager for R3.

Provides the ``FeatureSnapshot`` data structure and ``FeatureSnapshotManager``
for building, loading, validating, listing, and comparing frozen feature
snapshots.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.factors.definition import FactorDefinition, FactorLibrary
from quant_us.factors.pipeline import FactorPipeline


@dataclass
class FeatureSnapshot:
    """A frozen snapshot of feature values for a set of symbols and date range.

    Attributes:
        snapshot_id: Unique identifier ``{feature_id}_{version}_{config_hash[:8]}``.
        feature_id: The factor ID that was computed.
        feature_version: Version string of the factor definition used.
        symbols: List of symbols included in the snapshot.
        start: Start date (YYYY-MM-DD).
        end: End date (YYYY-MM-DD).
        data_version: Timestamp string for when the snapshot was built.
        config_hash: Hash of the factor definition configuration.
        created_at: ISO-8601 timestamp of creation.
        row_count: Number of rows in the snapshot.
        checksum: Content checksum for integrity verification.
        path: Filesystem path to the snapshot parquet file.
    """

    snapshot_id: str
    feature_id: str
    feature_version: str
    symbols: list[str]
    start: str
    end: str
    data_version: str
    config_hash: str
    created_at: str
    bar_size: str = "1d"
    timeframe: str = "1d"
    row_count: int = 0
    checksum: str = ""
    path: str = ""


class FeatureSnapshotManager:
    """Manages frozen feature snapshots on disk.

    Snapshots are stored as parquet files under ``{data_root}/features/snapshots/``
    alongside a JSON manifest for each.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self._snapshots_dir = self.data_root / "features" / "snapshots"

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        feature_id: str,
        version: str,
        symbols: list[str],
        start: str,
        end: str,
        *,
        bar_size: str = "1d",
        timeframe: str | None = None,
    ) -> FeatureSnapshot:
        """Compute factor values and freeze them into a snapshot.

        Returns a ``FeatureSnapshot`` with path, checksum, and row count populated.
        """
        lib = FactorLibrary()
        factor = lib.get(feature_id)
        config_hash = self._compute_config_hash(factor)
        effective_timeframe = timeframe or bar_size
        snapshot_id = f"{feature_id}_{version}_{effective_timeframe}_{config_hash[:8]}"
        snapshot_dir = self._snapshots_dir / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        pipe = FactorPipeline(data_root=str(self.data_root))
        df = pipe.compute(
            factor_ids=[feature_id],
            symbols=symbols,
            start=start,
            end=end,
            bar_size=bar_size,
            timeframe=effective_timeframe,
        )

        if df.empty:
            now = datetime.now(timezone.utc).isoformat()
            return FeatureSnapshot(
                snapshot_id=snapshot_id,
                feature_id=feature_id,
                feature_version=version,
                bar_size=bar_size,
                timeframe=effective_timeframe,
                symbols=symbols,
                start=start,
                end=end,
                data_version=now,
                config_hash=config_hash,
                created_at=now,
                row_count=0,
                checksum="",
                path=str(snapshot_dir),
            )

        parquet_path = snapshot_dir / "values.parquet"
        df.to_parquet(parquet_path, index=False)

        checksum = self._compute_file_checksum(parquet_path)
        now = datetime.now(timezone.utc).isoformat()

        snapshot = FeatureSnapshot(
            snapshot_id=snapshot_id,
            feature_id=feature_id,
            feature_version=version,
            bar_size=bar_size,
            timeframe=effective_timeframe,
            symbols=symbols,
            start=start,
            end=end,
            data_version=now,
            config_hash=config_hash,
            created_at=now,
            row_count=len(df),
            checksum=checksum,
            path=str(parquet_path),
        )

        self._write_manifest(snapshot, snapshot_dir)
        return snapshot

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, snapshot_id: str) -> pd.DataFrame:
        """Load a snapshot's feature values from disk.

        Raises FileNotFoundError if the snapshot does not exist.
        """
        snapshot_dir = self._snapshots_dir / snapshot_id
        parquet_path = snapshot_dir / "values.parquet"
        if not parquet_path.exists():
            raise FileNotFoundError(
                f"Snapshot '{snapshot_id}' not found at {parquet_path}"
            )
        return pd.read_parquet(parquet_path)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate(self, snapshot_id: str) -> tuple[bool, str]:
        """Verify snapshot integrity by comparing checksums.

        Returns ``(pass, reason)``.
        """
        snapshot_dir = self._snapshots_dir / snapshot_id
        parquet_path = snapshot_dir / "values.parquet"
        manifest_path = snapshot_dir / "manifest.json"

        if not parquet_path.exists():
            return False, f"Snapshot '{snapshot_id}' has no data file"
        if not manifest_path.exists():
            return False, f"Snapshot '{snapshot_id}' has no manifest"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored_checksum = manifest.get("checksum", "")

        if not stored_checksum:
            return False, "No checksum stored in manifest"

        actual = self._compute_file_checksum(parquet_path)
        if actual != stored_checksum:
            return (
                False,
                f"Checksum mismatch: stored={stored_checksum}, actual={actual}",
            )
        return True, "Checksum verified OK"

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_snapshots(self) -> list[FeatureSnapshot]:
        """Return all snapshot manifests found on disk."""
        if not self._snapshots_dir.exists():
            return []
        snapshots: list[FeatureSnapshot] = []
        for d in sorted(self._snapshots_dir.iterdir()):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                snapshots.append(FeatureSnapshot(**data))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
        return snapshots

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------

    def compare(self, id1: str, id2: str) -> dict[str, Any]:
        """Generate a diff report between two snapshots.

        Returns a dict with shared stats and differences in row count,
        symbol overlap, date range overlap, and content divergence.
        """
        try:
            df1 = self.load(id1)
            df2 = self.load(id2)
        except FileNotFoundError as exc:
            return {"error": str(exc)}

        report: dict[str, Any] = {}
        report["snapshot_1"] = id1
        report["snapshot_2"] = id2
        report["rows_1"] = len(df1)
        report["rows_2"] = len(df2)
        report["diff_rows"] = len(df1) - len(df2)

        intersection = set(df1["symbol"]).intersection(set(df2["symbol"]))
        report["symbol_overlap"] = len(intersection)

        if "date" in df1.columns and "date" in df2.columns:
            report["date_range_1"] = (
                df1["date"].min(),
                df1["date"].max(),
            )
            report["date_range_2"] = (
                df2["date"].min(),
                df2["date"].max(),
            )
            overlap_start = max(df1["date"].min(), df2["date"].min())
            overlap_end = min(df1["date"].max(), df2["date"].max())
            report["date_overlap_days"] = (
                (pd.to_datetime(overlap_end) - pd.to_datetime(overlap_start)).days + 1
                if overlap_start <= overlap_end
                else 0
            )

        common = ["symbol", "date"]
        if "timestamp_utc" in df1.columns and "timestamp_utc" in df2.columns:
            common = ["symbol", "timestamp_utc"]
        value_cols_1 = [c for c in df1.columns if c not in common]
        value_cols_2 = [c for c in df2.columns if c not in common]
        shared_value_cols = set(value_cols_1).intersection(value_cols_2)
        report["shared_value_columns"] = list(shared_value_cols)

        if shared_value_cols and intersection and report.get("date_overlap_days", 0) > 0:
            merged = df1.merge(
                df2,
                on=common,
                how="inner",
                suffixes=("_1", "_2"),
            )
            if len(merged) > 0:
                diffs = 0
                for col in shared_value_cols:
                    c1 = f"{col}_1"
                    c2 = f"{col}_2"
                    if c1 in merged.columns and c2 in merged.columns:
                        diffs += int((merged[c1].fillna(0) != merged[c2].fillna(0)).sum())
                report["overlapping_values_different"] = diffs
            else:
                report["overlapping_values_different"] = 0
        else:
            report["overlapping_values_different"] = None

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_config_hash(factor: FactorDefinition) -> str:
        """Deterministic hash of factor definition configuration."""
        payload = {
            "factor_id": factor.factor_id,
            "lookback": factor.lookback,
            "neutralization": factor.neutralization,
            "winsorize_pct": factor.winsorize_pct,
            "zscore": factor.zscore,
            "rank_method": factor.rank_method,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _compute_file_checksum(path: Path) -> str:
        """SHA-256 of the full file contents (first 16 hex chars)."""
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()[:16]

    def _write_manifest(self, snapshot: FeatureSnapshot, snapshot_dir: Path) -> None:
        """Write snapshot metadata as JSON."""
        manifest = {
            "snapshot_id": snapshot.snapshot_id,
            "feature_id": snapshot.feature_id,
            "feature_version": snapshot.feature_version,
            "bar_size": snapshot.bar_size,
            "timeframe": snapshot.timeframe,
            "symbols": snapshot.symbols,
            "start": snapshot.start,
            "end": snapshot.end,
            "data_version": snapshot.data_version,
            "config_hash": snapshot.config_hash,
            "created_at": snapshot.created_at,
            "row_count": snapshot.row_count,
            "checksum": snapshot.checksum,
            "path": snapshot.path,
        }
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
