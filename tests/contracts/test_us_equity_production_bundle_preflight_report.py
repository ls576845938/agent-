from __future__ import annotations

from pathlib import Path

from scripts.build_us_equity_production_bundle_preflight_report import (
    build_production_bundle_preflight_report,
)
from tests.contracts.us_equity_local_csv_test_helpers import (
    copy_fixture_into_external_bundle_root,
    load_manifest,
    provider_config_for_external_bundle,
    write_gitignore_for_bundle_root,
    write_manifest,
)


def test_no_bundle_fails(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)

    report = build_production_bundle_preflight_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, provider_config_for_external_bundle(tmp_path, selected_bundle_id=None)),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["production_bundles_found"] == 0
    assert report["production_bundle_preflight_pass"] is False
    assert "production_bundle_missing" in report["blockers"]


def test_fixture_only_fails(tmp_path: Path) -> None:
    bundle_id = "fixture_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="fixture", bundle_id=bundle_id)

    report = build_production_bundle_preflight_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, provider_config_for_external_bundle(tmp_path, selected_bundle_id=bundle_id)),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["fixture_bundles_found"] == 1
    assert report["production_bundle_preflight_pass"] is False
    assert "production_bundle_missing" in report["blockers"]
    assert "selected_bundle_not_production" in report["blockers"]


def test_sample_only_fails(tmp_path: Path) -> None:
    bundle_id = "sample_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="sample", bundle_id=bundle_id)

    report = build_production_bundle_preflight_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, provider_config_for_external_bundle(tmp_path, selected_bundle_id=bundle_id)),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["sample_bundles_found"] == 1
    assert report["production_bundle_preflight_pass"] is False
    assert "production_bundle_missing" in report["blockers"]
    assert "selected_bundle_not_production" in report["blockers"]


def test_production_without_promotion_clean_allowed_fails(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=False,
        bundle_id=bundle_id,
    )

    report = build_production_bundle_preflight_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(tmp_path, selected_bundle_id=bundle_id, promotion_clean_allowed=True),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["production_bundles_found"] == 1
    assert report["promotion_clean_allowed"] is False
    assert report["production_bundle_preflight_pass"] is False
    assert "bundle_promotion_clean_not_allowed" in report["blockers"]


def test_production_missing_file_fails(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    bundle_root, _ = copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)
    (bundle_root / "corporate_actions.csv").unlink()

    report = _preflight_for_selected(tmp_path, bundle_id)

    assert report["required_files_present"] is False
    assert report["production_bundle_preflight_pass"] is False
    assert "production_bundle_corporate_actions_file_missing" in report["blockers"]


def test_production_missing_sha256_fails(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    bundle_root, _ = copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)
    manifest = load_manifest(bundle_root)
    manifest["files"]["corporate_actions"]["sha256"] = ""
    write_manifest(bundle_root, manifest)

    report = _preflight_for_selected(tmp_path, bundle_id)

    assert report["manifest_sha256_present"] is False
    assert "production_bundle_corporate_actions_sha256_missing" in report["blockers"]


def test_production_missing_record_count_fails(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    bundle_root, _ = copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)
    manifest = load_manifest(bundle_root)
    manifest["files"]["corporate_actions"].pop("record_count")
    write_manifest(bundle_root, manifest)

    report = _preflight_for_selected(tmp_path, bundle_id)

    assert report["manifest_record_counts_present"] is False
    assert "production_bundle_corporate_actions_record_count_missing" in report["blockers"]


def test_production_missing_license_note_fails(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    bundle_root, _ = copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)
    manifest = load_manifest(bundle_root)
    manifest["license_note"] = ""
    write_manifest(bundle_root, manifest)

    report = _preflight_for_selected(tmp_path, bundle_id)

    assert report["license_note_present"] is False
    assert "production_bundle_license_note_missing" in report["blockers"]


def test_complete_production_bundle_may_preflight_pass_but_is_not_promotion_clean_evidence(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)

    report = _preflight_for_selected(tmp_path, bundle_id)

    assert report["production_bundle_preflight_pass"] is True
    assert report["required_files_present"] is True
    assert "promotion_clean" not in report


def _preflight_for_selected(tmp_path: Path, bundle_id: str) -> dict[str, object]:
    return build_production_bundle_preflight_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(tmp_path, selected_bundle_id=bundle_id, promotion_clean_allowed=True),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )


def _write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "provider_sources.yaml"
    local_csv = payload["providers"]["local_csv"]  # type: ignore[index]
    selected = local_csv.get("selected_bundle_id") or "null"
    text = (
        "providers:\n"
        "  local_csv:\n"
        f"    enabled: {str(local_csv.get('enabled', True)).lower()}\n"
        f"    root: {local_csv['root']}\n"
        f"    selected_bundle_id: {selected}\n"
        "    require_explicit_bundle_selection: true\n"
        "    allow_sample_for_research: false\n"
        "    allow_fixture_for_tests_only: true\n"
        "    bundle_manifest: null\n"
        f"    promotion_clean_allowed: {str(local_csv.get('promotion_clean_allowed', False)).lower()}\n"
        "    files: {}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path
