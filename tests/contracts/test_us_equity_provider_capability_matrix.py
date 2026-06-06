from __future__ import annotations

import json
from pathlib import Path

from scripts.build_us_equity_provider_capability_matrix import (
    build_provider_capability_matrix,
    write_provider_capability_matrix,
)


def test_provider_capability_matrix_schema_exists() -> None:
    assert Path("schemas/us_equity_provider_capability_matrix.schema.json").exists()


def test_capability_matrix_lists_required_providers_and_keeps_verification_separate(tmp_path: Path) -> None:
    _write_yfinance_manifest(tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json")

    payload = build_provider_capability_matrix(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    providers = {row["provider_id"]: row for row in payload["providers"]}
    assert set(providers) == {"yfinance", "crsp", "sharadar", "polygon", "norgate", "local_csv"}
    assert providers["yfinance"]["configured"] is True
    assert providers["yfinance"]["local_data_available"] is True
    assert providers["yfinance"]["verified_for_promotion"] is False
    assert providers["yfinance"]["promotion_clean_capable"] is False
    assert providers["crsp"]["configured"] is False
    assert providers["crsp"]["local_data_available"] is False
    assert payload["selected_provider_profile"] is None
    assert payload["promotion_clean_provider_available"] is False
    assert "promotion_clean_provider_not_verified" in payload["blockers"]


def test_configured_false_provider_has_no_local_data_available(tmp_path: Path) -> None:
    payload = build_provider_capability_matrix(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    providers = {row["provider_id"]: row for row in payload["providers"]}
    assert providers["local_csv"]["configured"] is False
    assert providers["local_csv"]["local_data_available"] is False
    assert "local_csv_provider_disabled" in providers["local_csv"]["blockers"]


def test_provider_capability_matrix_writer_persists_artifact(tmp_path: Path) -> None:
    payload = build_provider_capability_matrix(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    output = write_provider_capability_matrix(
        payload,
        tmp_path / "artifacts/us_equity_data_lineage/latest/provider_capability_matrix.json",
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "us_equity_provider_capability_matrix_v1"


def _write_yfinance_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "data_version": path.stem,
                "source": "yfinance",
                "symbol": "AAPL",
                "interval": "1d",
                "asset_class": "equity",
            }
        ),
        encoding="utf-8",
    )
