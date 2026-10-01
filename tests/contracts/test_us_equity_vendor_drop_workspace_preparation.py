from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.prepare_us_equity_vendor_drop_workspace import prepare_us_equity_vendor_drop_workspace


SCHEMA = Path("schemas/us_equity_vendor_drop_workspace_preparation_report.schema.json")


def test_prepare_vendor_drop_workspace_creates_empty_source_dir(tmp_path: Path) -> None:
    payload = prepare_us_equity_vendor_drop_workspace(
        repo_root=tmp_path,
        output=Path("out/workspace.json"),
        markdown_output=Path("out/workspace.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    source = tmp_path / payload["source_dir"]
    assert source.is_dir()
    assert payload["status"] == "vendor_drop_workspace_prepared"
    assert payload["vendor_file_count"] == 0
    assert payload["guardrails"]["contains_vendor_data"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_prepare_vendor_drop_workspace_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = prepare_us_equity_vendor_drop_workspace(
        repo_root=tmp_path,
        output=Path("out/workspace.json"),
        markdown_output=Path("out/workspace.md"),
        generated_at="2026-06-27T00:00:00Z",
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
