from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_production_bundle_activation_report import (
    build_us_equity_production_bundle_activation_report,
)
from tests.contracts.us_equity_local_csv_test_helpers import (
    copy_fixture_into_external_bundle_root,
    write_gitignore_for_bundle_root,
)


SCHEMA = Path("schemas/us_equity_production_bundle_activation_report.schema.json")


def test_activation_report_blocks_missing_bundle_without_mutating_config(tmp_path: Path) -> None:
    write_gitignore_for_bundle_root(tmp_path)

    payload = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id="missing_bundle",
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_production_bundle_activation_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "activation_blocked"
    assert "candidate_bundle_root_missing" in payload["blockers"]
    assert "manual_license_review_required_before_activation" in payload["blockers"]
    assert payload["guardrails"]["configuration_mutated_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert not (tmp_path / "configs/data/us_equity_provider_sources.yaml").exists()
    assert (tmp_path / "out/activation.json").exists()
    assert (tmp_path / "out/activation.md").exists()


def test_activation_report_complete_bundle_generates_manual_config_candidate_only(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=True,
        bundle_id=bundle_id,
    )

    payload = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id=bundle_id,
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
        generated_at="2026-06-25T00:00:00Z",
        license_reviewed=True,
    )

    assert payload["status"] == "activation_ready_for_manual_config_apply"
    _validate_schema(payload)
    assert payload["blockers"] == []
    assert payload["preflight_summary"]["production_bundle_preflight_pass"] is True
    assert payload["provider_verification_summary"]["promotion_clean"] is True
    assert payload["checks"]["manual_license_review"]["passed"] is True
    assert "selected_bundle_id: production_bundle" in payload["candidate_config_patch"]
    assert "promotion_clean_allowed: true" in payload["candidate_config_patch"]
    assert payload["guardrails"]["configuration_mutated_by_this_report"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert not (tmp_path / "configs/data/us_equity_provider_sources.yaml").exists()
    assert (tmp_path / payload["candidate_config_path"]).exists()


def test_activation_report_requires_manual_license_review_even_when_bundle_is_complete(tmp_path: Path) -> None:
    bundle_id = "production_bundle"
    copy_fixture_into_external_bundle_root(
        tmp_path,
        source_type="production",
        promotion_clean_allowed=True,
        bundle_id=bundle_id,
    )

    payload = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id=bundle_id,
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
        generated_at="2026-06-25T00:00:00Z",
        license_reviewed=False,
    )

    assert payload["status"] == "activation_blocked"
    _validate_schema(payload)
    assert "manual_license_review_required_before_activation" in payload["blockers"]
    assert "promotion_clean_allowed: false" in payload["candidate_config_patch"]
    assert payload["provider_verification_summary"]["promotion_clean"] is False


def test_activation_report_schema_rejects_live_unlock_flag(tmp_path: Path) -> None:
    payload = build_us_equity_production_bundle_activation_report(
        repo_root=tmp_path,
        bundle_id="missing_bundle",
        output=Path("out/activation.json"),
        markdown_output=Path("out/activation.md"),
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
