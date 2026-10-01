from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema

from scripts.import_us_equity_local_csv_production_bundle import (
    import_us_equity_local_csv_production_bundle,
)
from tests.contracts.us_equity_local_csv_test_helpers import (
    FIXTURE_ROOT,
    write_gitignore_for_bundle_root,
)


SCHEMA = Path("schemas/us_equity_local_csv_production_bundle_import_report.schema.json")


def test_import_blocks_missing_source_without_writing_bundle(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)

    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_bundle_import_blocked"
    assert "source_dir_missing" in payload["blockers"]
    assert not (tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle").exists()


def test_import_blocks_missing_required_csv(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    shutil.copytree(FIXTURE_ROOT, source)
    (source / "corporate_actions.csv").unlink()

    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_bundle_import_blocked"
    assert "source_corporate_actions_file_missing" in payload["blockers"]
    assert not (tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle").exists()


def test_import_blocks_duplicate_source_record_id_without_writing_bundle(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    shutil.copytree(FIXTURE_ROOT, source)
    path = source / "corporate_actions.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("fixture-action-1", "fixture-membership-1"), encoding="utf-8")

    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_bundle_import_blocked"
    assert "source_record_id_duplicate" in payload["blockers"]
    assert not (tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle").exists()


def test_import_blocks_invalid_macro_available_time_without_writing_bundle(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    shutil.copytree(FIXTURE_ROOT, source)
    path = source / "macro_release_calendar.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("2020-02-03T13:00:00Z", "2020-02-03 13:00:00"), encoding="utf-8")

    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_bundle_import_blocked"
    assert "source_macro_release_calendar_available_time_utc_invalid" in payload["blockers"]
    assert not (tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle").exists()


def test_import_writes_gitignored_bundle_and_manifest_for_complete_drop(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    shutil.copytree(FIXTURE_ROOT, source)

    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        as_of_date="2021-01-03",
        universe_name="us_core",
        price_data_reference="licensed_provider_prices_v1",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_bundle_imported"
    assert payload["blockers"] == []
    assert payload["manifest_blockers"] == []
    assert len(payload["copied_files"]) == 6
    bundle = tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle"
    manifest = json.loads((bundle / "provider_bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_type"] == "production"
    assert manifest["promotion_clean_allowed"] is True
    assert manifest["license_note"] == "Licensed provider drop reviewed for tests."
    assert payload["guardrails"]["live_order_allowed"] is False


def test_import_blocks_existing_target_bundle(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    shutil.copytree(FIXTURE_ROOT, source)
    target = tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle"
    target.mkdir(parents=True)

    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_bundle_import_blocked"
    assert "target_bundle_already_exists" in payload["blockers"]


def test_import_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = import_us_equity_local_csv_production_bundle(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        bundle_id="prod_bundle",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        license_note="Licensed provider drop reviewed for tests.",
        promotion_clean_allowed=True,
        output=Path("out/import.json"),
        markdown_output=Path("out/import.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
