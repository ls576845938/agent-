from __future__ import annotations

from pathlib import Path

from scripts.build_us_equity_provider_verification_report import build_provider_verification_report
from tests.contracts.us_equity_local_csv_test_helpers import (
    copy_fixture_into_external_bundle_root,
    provider_config_for_external_bundle,
)


def test_local_csv_disabled_does_not_enable_production_bundle(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(
                tmp_path,
                selected_bundle_id=bundle_id,
                promotion_clean_allowed=True,
                enabled=False,
            ),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["selected_provider"] == "none"
    assert report["production_bundle_preflight_pass"] is False
    assert report["promotion_clean"] is False


def test_selected_bundle_id_required_no_auto_selection(tmp_path: Path) -> None:
    copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id="production_bundle")

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(
                tmp_path,
                selected_bundle_id=None,
                promotion_clean_allowed=True,
            ),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["selected_provider"] == "local_csv"
    assert report["explicit_bundle_selection_confirmed"] is False
    assert report["production_bundle_preflight_pass"] is False
    assert "explicit_bundle_selection_missing" in report["blockers"]
    assert report["promotion_clean"] is False


def test_config_promotion_clean_allowed_false_blocks_l4(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)

    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(
            tmp_path,
            provider_config_for_external_bundle(
                tmp_path,
                selected_bundle_id=bundle_id,
                promotion_clean_allowed=False,
            ),
        ),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["promotion_clean_allowed_by_config"] is False
    assert report["production_bundle_preflight_pass"] is False
    assert report["promotion_clean"] is False
    assert "config_promotion_clean_not_allowed" in report["blockers"]


def test_sample_bundle_selection_stays_research_only(tmp_path: Path) -> None:
    bundle_id = "sample_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="sample", bundle_id=bundle_id)

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

    assert report["source_type"] == "sample"
    assert report["production_bundle_preflight_pass"] is False
    assert report["promotion_clean"] is False
    assert "sample_source_not_promotion_ready" in report["blockers"]


def test_string_false_config_value_is_not_truthy(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(tmp_path, source_type="production", bundle_id=bundle_id)

    config = provider_config_for_external_bundle(
        tmp_path,
        selected_bundle_id=bundle_id,
        promotion_clean_allowed=True,
    )
    config["providers"]["local_csv"]["promotion_clean_allowed"] = "false"  # type: ignore[index]
    report = build_provider_verification_report(
        repo_root=tmp_path,
        config_path=_write_config(tmp_path, config),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["promotion_clean_allowed_by_config"] is False
    assert report["promotion_clean"] is False
    assert "config_promotion_clean_not_allowed" in report["blockers"]


def _write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "provider_sources.yaml"
    local_csv = payload["providers"]["local_csv"]  # type: ignore[index]
    selected = local_csv.get("selected_bundle_id") or "null"
    enabled = local_csv.get("enabled", True)
    promotion_allowed = local_csv.get("promotion_clean_allowed", False)
    promotion_text = str(promotion_allowed).lower() if isinstance(promotion_allowed, bool) else str(promotion_allowed)
    text = (
        "providers:\n"
        "  local_csv:\n"
        f"    enabled: {str(enabled).lower() if isinstance(enabled, bool) else enabled}\n"
        f"    root: {local_csv['root']}\n"
        f"    selected_bundle_id: {selected}\n"
        "    require_explicit_bundle_selection: true\n"
        "    allow_sample_for_research: false\n"
        "    allow_fixture_for_tests_only: true\n"
        "    bundle_manifest: null\n"
        f"    promotion_clean_allowed: {promotion_text}\n"
        "    files: {}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path
