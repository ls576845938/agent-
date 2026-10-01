from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_production_bundle_scaffold_report import (
    build_us_equity_production_bundle_scaffold_report,
)


SCHEMA = Path("schemas/us_equity_production_bundle_scaffold_report.schema.json")


def test_production_bundle_scaffold_writes_templates_without_unlocking(tmp_path: Path) -> None:
    payload = build_us_equity_production_bundle_scaffold_report(
        repo_root=tmp_path,
        bundle_id="test_bundle",
        output=Path("out/scaffold.json"),
        markdown_output=Path("out/scaffold.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    scaffold_dir = tmp_path / payload["scaffold_dir"]
    assert payload["schema_version"] == "us_equity_production_bundle_scaffold_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "template_ready_not_provider_evidence"
    assert payload["guardrails"]["template_contains_vendor_data"] is False
    assert payload["guardrails"]["template_is_not_provider_evidence"] is True
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/scaffold.json").exists()
    assert (tmp_path / "out/scaffold.md").exists()
    markdown = (tmp_path / "out/scaffold.md").read_text(encoding="utf-8")
    assert "# US Equity 生产数据包接入模板" in markdown
    assert "## 必需表" in markdown
    assert "## 启用步骤" in markdown
    assert (scaffold_dir / "README.md").exists()
    assert (scaffold_dir / "provider_bundle_manifest.template.json").exists()
    assert (scaffold_dir / "us_equity_provider_sources.patch.yaml").exists()
    assert {row["table"] for row in payload["required_tables"]} == set(REQUIRED_LOCAL_CSV_FILES)


def test_production_bundle_scaffold_csv_headers_match_local_csv_provider_contract(tmp_path: Path) -> None:
    payload = build_us_equity_production_bundle_scaffold_report(
        repo_root=tmp_path,
        bundle_id="test_bundle",
        output=Path("out/scaffold.json"),
        markdown_output=Path("out/scaffold.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    for row in payload["required_tables"]:
        path = tmp_path / row["template_path"]
        with path.open("r", encoding="utf-8", newline="") as handle:
            headers = next(csv.reader(handle))
        assert headers == REQUIRED_LOCAL_CSV_FILES[row["table"]]
    _validate_schema(payload)


def test_production_bundle_scaffold_manifest_is_template_not_provider_evidence(tmp_path: Path) -> None:
    payload = build_us_equity_production_bundle_scaffold_report(
        repo_root=tmp_path,
        bundle_id="test_bundle",
        output=Path("out/scaffold.json"),
        markdown_output=Path("out/scaffold.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    manifest = json.loads((tmp_path / payload["manifest_template"]).read_text(encoding="utf-8"))
    assert manifest["source_type"] == "production"
    assert manifest["promotion_clean_allowed"] is False
    assert "template_only_not_provider_evidence" in manifest["blockers"]
    for table, spec in manifest["files"].items():
        assert table in REQUIRED_LOCAL_CSV_FILES
        assert spec["sha256"] == "RUN_MANIFEST_BUILDER_TO_FILL"
        assert spec["record_count"] == 0
    _validate_schema(payload)


def test_production_bundle_scaffold_schema_rejects_vendor_data_claim(tmp_path: Path) -> None:
    payload = build_us_equity_production_bundle_scaffold_report(
        repo_root=tmp_path,
        bundle_id="test_bundle",
        output=Path("out/scaffold.json"),
        markdown_output=Path("out/scaffold.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["template_contains_vendor_data"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted template_contains_vendor_data=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
