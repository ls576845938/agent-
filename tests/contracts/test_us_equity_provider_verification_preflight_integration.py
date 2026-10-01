from __future__ import annotations

from pathlib import Path

from scripts.build_us_equity_provider_verification_report import build_provider_verification_report
from tests.contracts.us_equity_local_csv_test_helpers import (
    copy_fixture_into_external_bundle_root,
    provider_config_for_external_bundle,
)


def test_provider_verification_inherits_preflight_failure_when_bundle_missing(tmp_path: Path) -> None:
    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(tmp_path, selected_bundle_id=None, promotion_clean_allowed=True),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["selected_provider"] == "local_csv"
    assert report["production_bundle_preflight_pass"] is False
    assert report["promotion_clean"] is False
    assert "production_bundle_preflight_failed" in report["blockers"]


def test_provider_verification_requires_explicit_bundle_selection(tmp_path: Path) -> None:
    copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id="production_bundle")

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(tmp_path, selected_bundle_id=None, promotion_clean_allowed=True),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["explicit_bundle_selection_confirmed"] is False
    assert report["production_bundle_preflight_pass"] is False
    assert report["promotion_clean"] is False
    assert "explicit_bundle_selection_missing" in report["blockers"]


def test_provider_verification_requires_manifest_and_config_promotion_allow(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=False,
        bundle_id=bundle_id,
    )

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(tmp_path, selected_bundle_id=bundle_id, promotion_clean_allowed=True),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["promotion_clean_allowed_by_manifest"] is False
    assert report["production_bundle_preflight_pass"] is False
    assert report["promotion_clean"] is False
    assert "bundle_promotion_clean_not_allowed" in report["blockers"]


def test_preflight_pass_still_requires_provider_verification(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    bundle_root, _ = copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=True,
        bundle_id=bundle_id,
    )
    text = (bundle_root / "corporate_actions.csv").read_text(encoding="utf-8").replace("split", "bad_event", 1)
    (bundle_root / "corporate_actions.csv").write_text(text, encoding="utf-8")

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(tmp_path, selected_bundle_id=bundle_id, promotion_clean_allowed=True),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["production_bundle_preflight_pass"] is True
    assert report["promotion_clean"] is False
    assert "local_csv_corporate_actions_sha256_mismatch" in report["blockers"]
    assert "local_csv_corporate_actions_event_type_invalid" in report["blockers"]


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
