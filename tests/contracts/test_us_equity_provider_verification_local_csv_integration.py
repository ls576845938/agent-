from __future__ import annotations

from pathlib import Path

from scripts.build_us_equity_provider_verification_report import build_provider_verification_report
from tests.contracts.us_equity_local_csv_test_helpers import (
    copy_fixture_bundle,
    copy_fixture_into_external_bundle_root,
    provider_config,
    provider_config_for_external_bundle,
)


def test_provider_verification_consumes_fixture_bundle_but_fails_promotion(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="fixture")

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, provider_config(bundle_root)),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["selected_provider"] == "local_csv"
    assert report["source_type"] == "fixture"
    assert report["bundle_id"] == "local_csv_fixture_bundle"
    assert report["local_data_available"] is True
    assert report["point_in_time_universe_confirmed"] is True
    assert report["promotion_clean"] is False
    assert report["data_lineage_grade_candidate"] == "L0_fixture"
    assert "fixture_source_not_promotion_ready" in report["blockers"]


def test_provider_verification_sample_bundle_never_promotion_clean(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="sample")

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, provider_config(bundle_root)),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["source_type"] == "sample"
    assert report["promotion_clean"] is False
    assert report["data_lineage_grade_candidate"] == "L2_static_snapshot"
    assert "sample_source_not_promotion_ready" in report["blockers"]


def test_provider_verification_production_bundle_requires_allow_flag(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="production", promotion_clean_allowed=False)

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, provider_config(bundle_root)),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["source_type"] == "production"
    assert report["promotion_clean"] is False
    assert "promotion_clean_not_allowed" in report["blockers"]


def test_provider_verification_complete_production_bundle_can_pass_provider_gate(tmp_path: Path) -> None:
    bundle_id = "local_csv_production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=True,
        bundle_id=bundle_id,
    )

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(
                tmp_path,
                selected_bundle_id=bundle_id,
                promotion_clean_allowed=True,
            ),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["source_type"] == "production"
    assert report["promotion_clean_allowed"] is True
    assert report["production_bundle_preflight_pass"] is True
    assert report["explicit_bundle_selection_confirmed"] is True
    assert report["promotion_clean"] is True
    assert report["data_lineage_grade_candidate"] == "L4_promotion_clean"
    assert report["blockers"] == []


def _write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "provider_sources.yaml"
    local_csv = payload["providers"]["local_csv"]  # type: ignore[index]
    text = (
        "providers:\n"
        "  local_csv:\n"
        "    enabled: true\n"
        f"    root: {local_csv['root']}\n"
        f"    selected_bundle_id: {local_csv.get('selected_bundle_id') or 'null'}\n"
        f"    require_explicit_bundle_selection: {str(local_csv.get('require_explicit_bundle_selection', True)).lower()}\n"
        f"    allow_sample_for_research: {str(local_csv.get('allow_sample_for_research', False)).lower()}\n"
        f"    allow_fixture_for_tests_only: {str(local_csv.get('allow_fixture_for_tests_only', True)).lower()}\n"
        f"    bundle_manifest: {local_csv['bundle_manifest']}\n"
        f"    promotion_clean_allowed: {str(local_csv.get('promotion_clean_allowed', False)).lower()}\n"
        "    files: {}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path
