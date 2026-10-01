from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.apply_us_equity_production_bundle_activation import (
    apply_us_equity_production_bundle_activation,
)
from scripts.build_us_equity_production_bundle_activation_report import (
    build_us_equity_production_bundle_activation_report,
)
from tests.contracts.us_equity_local_csv_test_helpers import (
    copy_fixture_into_external_bundle_root,
    write_gitignore_for_bundle_root,
)


SCHEMA = Path("schemas/us_equity_production_bundle_activation_apply_report.schema.json")


def test_activation_apply_blocks_when_activation_report_is_not_ready(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)
    target = tmp_path / "configs/data/us_equity_provider_sources.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("providers:\n  local_csv:\n    enabled: false\n", encoding="utf-8")
    activation = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id="missing_bundle",
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
        generated_at="2026-06-25T00:00:00Z",
        license_reviewed=True,
    )

    payload = apply_us_equity_production_bundle_activation(
        repo_root=tmp_path,
        activation_report=Path(activation["outputs"]["json"]),
        target_config=Path("configs/data/us_equity_provider_sources.yaml"),
        output=Path("out/apply.json"),
        markdown_output=Path("out/apply.md"),
        generated_at="2026-06-25T00:01:00Z",
        confirm_apply=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "activation_apply_blocked"
    assert payload["configuration_mutated"] is False
    assert "activation_report_not_ready" in payload["blockers"]
    assert "enabled: false" in target.read_text(encoding="utf-8")


def test_activation_apply_requires_explicit_confirm_even_when_ready(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=True,
        bundle_id=bundle_id,
    )
    activation = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id=bundle_id,
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
        generated_at="2026-06-25T00:00:00Z",
        license_reviewed=True,
    )

    payload = apply_us_equity_production_bundle_activation(
        repo_root=tmp_path,
        activation_report=Path(activation["outputs"]["json"]),
        target_config=Path("configs/data/us_equity_provider_sources.yaml"),
        output=Path("out/apply.json"),
        markdown_output=Path("out/apply.md"),
        generated_at="2026-06-25T00:01:00Z",
        confirm_apply=False,
    )

    _validate_schema(payload)
    assert payload["status"] == "activation_apply_blocked"
    assert payload["configuration_mutated"] is False
    assert "manual_confirm_apply_missing" in payload["blockers"]
    assert payload["pre_apply_audit"]["activation_report_ready"] is True
    assert payload["pre_apply_audit"]["manual_confirm_apply_present"] is False
    assert payload["pre_apply_audit"]["candidate_config_exists"] is True
    assert payload["pre_apply_audit"]["candidate_config_inside_allowed_dir"] is True
    assert payload["pre_apply_audit"]["target_config_would_change"] is True
    assert payload["pre_apply_audit"]["backup_will_be_written_on_apply"] is False
    assert payload["pre_apply_audit"]["paper_or_live_unlock_allowed"] is False
    assert not (tmp_path / "configs/data/us_equity_provider_sources.yaml").exists()


def test_activation_apply_writes_config_only_when_ready_and_confirmed(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=True,
        bundle_id=bundle_id,
    )
    target = tmp_path / "configs/data/us_equity_provider_sources.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("providers:\n  local_csv:\n    enabled: false\n", encoding="utf-8")
    activation = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id=bundle_id,
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
        generated_at="2026-06-25T00:00:00Z",
        license_reviewed=True,
    )
    assert activation["status"] == "activation_ready_for_manual_config_apply"

    payload = apply_us_equity_production_bundle_activation(
        repo_root=tmp_path,
        activation_report=Path(activation["outputs"]["json"]),
        target_config=Path("configs/data/us_equity_provider_sources.yaml"),
        output=Path("out/apply.json"),
        markdown_output=Path("out/apply.md"),
        generated_at="2026-06-25T00:01:00Z",
        confirm_apply=True,
    )

    _validate_schema(payload)
    assert payload["status"] == "activation_applied"
    assert payload["configuration_mutated"] is True
    assert payload["pre_apply_audit"]["activation_report_ready"] is True
    assert payload["pre_apply_audit"]["manual_confirm_apply_present"] is True
    assert payload["pre_apply_audit"]["target_config_exists_before"] is True
    assert payload["pre_apply_audit"]["target_config_would_change"] is True
    assert payload["pre_apply_audit"]["backup_required_before_overwrite"] is True
    assert payload["pre_apply_audit"]["backup_will_be_written_on_apply"] is True
    assert payload["pre_apply_audit"]["unsafe_activation_guardrail_keys"] == []
    assert payload["guardrails"]["live_order_allowed"] is False
    text = target.read_text(encoding="utf-8")
    assert "enabled: true" in text
    assert f"selected_bundle_id: {bundle_id}" in text
    assert "promotion_clean_allowed: true" in text
    assert payload["backup_config_path"]
    assert (tmp_path / payload["backup_config_path"]).exists()


def test_activation_apply_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = apply_us_equity_production_bundle_activation(
        repo_root=tmp_path,
        activation_report=Path("missing.json"),
        target_config=Path("configs/data/us_equity_provider_sources.yaml"),
        output=Path("out/apply.json"),
        markdown_output=Path("out/apply.md"),
        generated_at="2026-06-25T00:01:00Z",
        confirm_apply=False,
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_activation_apply_schema_rejects_pre_apply_live_unlock(tmp_path: Path) -> None:
    payload = apply_us_equity_production_bundle_activation(
        repo_root=tmp_path,
        activation_report=Path("missing.json"),
        target_config=Path("configs/data/us_equity_provider_sources.yaml"),
        output=Path("out/apply.json"),
        markdown_output=Path("out/apply.md"),
        generated_at="2026-06-25T00:01:00Z",
        confirm_apply=False,
    )
    payload["pre_apply_audit"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted pre_apply_audit.live_order_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
