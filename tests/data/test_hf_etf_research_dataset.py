from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_us.data.hf_etf_research_dataset import HFETFResearchDataset


def test_manifest_dataset_loads_requested_symbols_and_resamples_daily(tmp_path: Path) -> None:
    manifest_path = _write_batch(tmp_path, ["QQQ", "GLD"])
    dataset = HFETFResearchDataset(manifest_path)

    frame = dataset.load_bars(
        symbols=["QQQ", "GLD"],
        start="2024-01-02",
        end="2024-01-02",
        bar_size="1d",
    )

    assert frame["symbol"].tolist() == ["GLD", "QQQ"]
    assert frame["source"].eq("hf_data_library").all()
    assert frame["adjusted_flag"].all()
    assert frame.attrs["research_only"] is True
    assert frame.attrs["promotion_clean_allowed"] is False
    assert frame.attrs["paper_or_live_unlock_allowed"] is False
    assert frame.attrs["blockers"] == ["vendor_adjustment_not_pit_replayed"]


def test_manifest_dataset_rejects_symbol_outside_pinned_batch(tmp_path: Path) -> None:
    dataset = HFETFResearchDataset(_write_batch(tmp_path, ["QQQ"]))

    with pytest.raises(ValueError, match="missing from HF ETF batch manifest"):
        dataset.load_bars(symbols=["TQQQ"], start="2024-01-02", end="2024-01-02")


def test_manifest_dataset_fails_closed_on_missing_file(tmp_path: Path) -> None:
    manifest_path = _write_batch(tmp_path, ["QQQ"])
    parquet_path = next((tmp_path / "data/external").rglob("*.parquet"))
    parquet_path.unlink()

    with pytest.raises(FileNotFoundError, match="HF ETF parquet missing"):
        HFETFResearchDataset(manifest_path)


def test_shared_manifest_resolves_immutable_dataset_root(tmp_path: Path) -> None:
    dataset_root = tmp_path / "shared-version"
    parquet_path = dataset_root / "symbol=QQQ" / "QQQ_clean_1min.parquet"
    parquet_path.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        [
            {"datetime": "2024-01-02 09:30:00", "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 100, "source": "iex"},
            {"datetime": "2024-01-02 15:59:00", "Open": 10.5, "High": 12.0, "Low": 10.0, "Close": 11.5, "Volume": 200, "source": "iex"},
        ]
    )
    frame.to_parquet(parquet_path, index=False)
    manifest_path = tmp_path / "shared.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "shared_dataset_manifest_v1",
                "dataset_version": "hf-shared-test",
                "aggregate_sha256": "a" * 64,
                "blockers": [],
                "known_gaps": ["adjustment_not_pit_replayed"],
                "files": [
                    {
                        "path": "symbol=QQQ/QQQ_clean_1min.parquet",
                        "bytes": parquet_path.stat().st_size,
                        "sha256": "b" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    dataset = HFETFResearchDataset(manifest_path, dataset_root=dataset_root)
    loaded = dataset.load_bars(symbols=["QQQ"], start="2024-01-02", end="2024-01-02")

    assert dataset.data_version == "hf-shared-test"
    assert dataset.symbols == ("QQQ",)
    assert loaded.attrs["blockers"] == ["adjustment_not_pit_replayed"]


def _write_batch(root: Path, symbols: list[str]) -> Path:
    (root / ".git").write_text("gitdir: test", encoding="utf-8")
    entries = []
    for symbol in symbols:
        relative = Path(
            f"data/external/us_equity_intraday/hf_data_library/interval=1m/version=clean/symbol={symbol}/{symbol}_clean_1min.parquet"
        )
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            [
                {"datetime": "2024-01-02 09:30:00", "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 100, "source": "pitrading"},
                {"datetime": "2024-01-02 15:59:00", "Open": 10.5, "High": 12.0, "Low": 10.0, "Close": 11.5, "Volume": 200, "source": "iex"},
            ]
        )
        frame.to_parquet(path, index=False)
        entries.append(
            {
                "ticker": symbol,
                "path": relative.as_posix(),
                "row_count": len(frame),
                "size_bytes": path.stat().st_size,
                "sha256": "test",
                "schema_columns": list(frame.columns),
                "critical_quality_failures": [],
            }
        )
    manifest_path = root / "data/manifests/us_equity/hf_data_library/batch.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "hf_data_library_etf_batch_manifest_v1",
                "data_version": "hf-test-batch",
                "batch_sha256": "batch-test",
                "blockers": ["vendor_adjustment_not_pit_replayed"],
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path
