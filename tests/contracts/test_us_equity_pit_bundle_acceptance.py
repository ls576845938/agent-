from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema

from scripts.run_us_equity_pit_bundle_acceptance import run_us_equity_pit_bundle_acceptance
from tests.contracts.us_equity_local_csv_test_helpers import FIXTURE_ROOT, write_gitignore_for_bundle_root


SCHEMA = Path("schemas/us_equity_pit_bundle_acceptance_run_report.schema.json")


def test_pit_bundle_acceptance_blocks_missing_source_dir(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)

    payload = run_us_equity_pit_bundle_acceptance(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        bundle_id="prod_bundle",
        license_note="Licensed provider drop reviewed for tests.",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        as_of_date="2021-01-03",
        universe_name="us_core",
        price_data_reference="fixture_prices",
        license_reviewed=True,
        output=Path("out/acceptance.json"),
        markdown_output=Path("out/acceptance.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_pit_bundle_acceptance_run_v1"
    _validate_schema(payload)
    assert payload["status"] == "acceptance_blocked"
    assert payload["current_blocking_step"] == "incoming_drop_readiness"
    assert "source_dir_missing" in payload["blockers"]
    steps = {item["step_id"]: item for item in payload["steps"]}
    assert steps["local_csv_production_bundle_import"]["status"] == "SKIPPED"
    assert steps["local_csv_production_bundle_import"]["skipped_due_to_step_id"] == "incoming_drop_readiness"
    assert steps["production_bundle_activation"]["status"] == "SKIPPED"
    assert steps["production_bundle_activation"]["skipped_due_to_step_id"] == "local_csv_production_bundle_import"
    assert payload["guardrails"]["configuration_mutated_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert not (tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle").exists()


def test_pit_bundle_acceptance_reaches_manual_config_apply_without_unlocking_live(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)

    payload = run_us_equity_pit_bundle_acceptance(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        license_note="Licensed provider drop reviewed for tests.",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        as_of_date="2021-01-03",
        universe_name="us_core",
        price_data_reference="fixture_prices",
        license_reviewed=True,
        output=Path("out/acceptance.json"),
        markdown_output=Path("out/acceptance.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    assert payload["status"] == "acceptance_ready_for_manual_config_apply"
    _validate_schema(payload)
    assert payload["current_blocking_step"] == "none"
    assert payload["blockers"] == []
    assert payload["activation_candidate_config_path"].endswith("us_equity_provider_sources.prod_bundle.candidate.yaml")
    assert all(step["passed"] is True for step in payload["steps"])
    assert payload["guardrails"]["configuration_mutated_by_this_report"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "data/external/us_equity_lineage/bundles/prod_bundle/provider_bundle_manifest.json").exists()
    assert not (tmp_path / "configs/data/us_equity_provider_sources.yaml").exists()


def test_pit_bundle_acceptance_requires_license_review_for_activation(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)

    payload = run_us_equity_pit_bundle_acceptance(
        repo_root=tmp_path,
        source_dir=source,
        bundle_id="prod_bundle",
        license_note="Licensed provider drop reviewed for tests.",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        as_of_date="2021-01-03",
        universe_name="us_core",
        price_data_reference="fixture_prices",
        license_reviewed=False,
        output=Path("out/acceptance.json"),
        markdown_output=Path("out/acceptance.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    assert payload["status"] == "acceptance_blocked"
    _validate_schema(payload)
    assert payload["current_blocking_step"] == "production_bundle_activation"
    assert "manual_license_review_required_before_activation" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_pit_bundle_acceptance_does_not_call_downstream_steps_when_readiness_blocks(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    calls: list[str] = []

    def manual_package_fn(**_: object) -> dict[str, object]:
        calls.append("manual")
        return {"status": "manual_vendor_drop_package_ready", "blockers": []}

    def readiness_fn(**_: object) -> dict[str, object]:
        calls.append("readiness")
        return {"status": "incoming_drop_blocked", "blockers": ["source_dir_missing"]}

    def import_fn(**_: object) -> dict[str, object]:
        calls.append("import")
        raise AssertionError("import must not run after readiness blocks")

    def activation_fn(**_: object) -> dict[str, object]:
        calls.append("activation")
        raise AssertionError("activation must not run after readiness blocks")

    payload = run_us_equity_pit_bundle_acceptance(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        bundle_id="prod_bundle",
        output=Path("out/acceptance.json"),
        markdown_output=Path("out/acceptance.md"),
        manual_package_fn=manual_package_fn,
        incoming_readiness_fn=readiness_fn,
        import_fn=import_fn,
        activation_fn=activation_fn,
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert calls == ["manual", "readiness"]
    assert payload["status"] == "acceptance_blocked"
    assert payload["current_blocking_step"] == "incoming_drop_readiness"
    steps = {item["step_id"]: item for item in payload["steps"]}
    assert steps["local_csv_production_bundle_import"]["status"] == "SKIPPED"
    assert steps["production_bundle_activation"]["status"] == "SKIPPED"
    assert payload["guardrails"]["live_order_allowed"] is False


def test_pit_bundle_acceptance_schema_rejects_live_flag(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    payload = run_us_equity_pit_bundle_acceptance(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        bundle_id="prod_bundle",
        license_note="Licensed provider drop reviewed for tests.",
        sample_start="2020-01-01",
        sample_end="2021-01-03",
        as_of_date="2021-01-03",
        universe_name="us_core",
        price_data_reference="fixture_prices",
        license_reviewed=True,
        output=Path("out/acceptance.json"),
        markdown_output=Path("out/acceptance.md"),
        generated_at="2026-06-26T00:00:00Z",
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


def _copy_fixture_csvs(target: Path) -> None:
    target.mkdir(parents=True)
    for path in FIXTURE_ROOT.glob("*.csv"):
        shutil.copy2(path, target / path.name)
