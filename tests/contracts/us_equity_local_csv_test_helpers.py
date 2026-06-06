from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.build_us_equity_local_csv_bundle_manifest import (
    build_local_csv_bundle_manifest,
    write_local_csv_bundle_manifest,
)


FIXTURE_ROOT = Path("tests/fixtures/us_equity_lineage/local_csv_valid_fixture")


def copy_fixture_bundle(tmp_path: Path, *, source_type: str = "fixture", promotion_clean_allowed: bool = False) -> Path:
    bundle_root = tmp_path / "bundle"
    shutil.copytree(FIXTURE_ROOT, bundle_root)
    manifest = build_local_csv_bundle_manifest(
        bundle_root=bundle_root,
        bundle_id=f"local_csv_{source_type}_bundle",
        source_provider="local_csv",
        source_type=source_type,
        created_at="2026-05-19T00:00:00Z",
        as_of_date="2021-01-03",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        universe_name="us_core",
        price_data_reference="fixture_prices",
        license_note="Synthetic contract fixture for tests only.",
        promotion_clean_allowed=promotion_clean_allowed,
    )
    write_local_csv_bundle_manifest(manifest, bundle_root / "provider_bundle_manifest.json")
    return bundle_root


def provider_config(
    bundle_root: Path,
    *,
    promotion_clean_allowed: bool = False,
    selected_bundle_id: str | None = "",
    require_explicit_bundle_selection: bool = True,
) -> dict[str, object]:
    manifest = load_manifest(bundle_root)
    selected = selected_bundle_id if selected_bundle_id != "" else str(manifest.get("bundle_id") or bundle_root.name)
    return {
        "providers": {
            "local_csv": {
                "enabled": True,
                "root": str(bundle_root),
                "selected_bundle_id": selected,
                "require_explicit_bundle_selection": require_explicit_bundle_selection,
                "allow_sample_for_research": False,
                "allow_fixture_for_tests_only": True,
                "bundle_manifest": str(bundle_root / "provider_bundle_manifest.json"),
                "promotion_clean_allowed": promotion_clean_allowed,
                "files": {},
            }
        }
    }


def write_gitignore_for_bundle_root(repo_root: Path) -> None:
    (repo_root / ".gitignore").write_text(
        "/data/external/us_equity_lineage/bundles/*\n",
        encoding="utf-8",
    )


def copy_fixture_into_external_bundle_root(
    tmp_path: Path,
    *,
    source_type: str = "production",
    promotion_clean_allowed: bool = True,
    bundle_id: str | None = None,
) -> tuple[Path, Path]:
    bundle_id = bundle_id or f"local_csv_{source_type}_bundle"
    bundle_root = tmp_path / "data/external/us_equity_lineage/bundles" / bundle_id
    shutil.copytree(FIXTURE_ROOT, bundle_root)
    manifest = build_local_csv_bundle_manifest(
        bundle_root=bundle_root,
        bundle_id=bundle_id,
        source_provider="local_csv",
        source_type=source_type,
        created_at="2026-05-19T00:00:00Z",
        as_of_date="2021-01-03",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        universe_name="us_core",
        price_data_reference="fixture_prices",
        license_note="Synthetic contract fixture for preflight tests only.",
        promotion_clean_allowed=promotion_clean_allowed,
    )
    write_local_csv_bundle_manifest(manifest, bundle_root / "provider_bundle_manifest.json")
    write_gitignore_for_bundle_root(tmp_path)
    return bundle_root, tmp_path / "data/external/us_equity_lineage/bundles"


def provider_config_for_external_bundle(
    tmp_path: Path,
    *,
    selected_bundle_id: str | None,
    promotion_clean_allowed: bool = True,
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "providers": {
            "local_csv": {
                "enabled": enabled,
                "root": str(tmp_path / "data/external/us_equity_lineage"),
                "selected_bundle_id": selected_bundle_id,
                "require_explicit_bundle_selection": True,
                "allow_sample_for_research": False,
                "allow_fixture_for_tests_only": True,
                "bundle_manifest": None,
                "promotion_clean_allowed": promotion_clean_allowed,
                "files": {},
            }
        }
    }


def load_manifest(bundle_root: Path) -> dict[str, object]:
    return json.loads((bundle_root / "provider_bundle_manifest.json").read_text(encoding="utf-8"))


def write_manifest(bundle_root: Path, manifest: dict[str, object]) -> None:
    (bundle_root / "provider_bundle_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
