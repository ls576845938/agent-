from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "docs/handoffs/us-v3-current-main-successor-scope-manifest.json"
SCHEMA_PATH = ROOT / "schemas/us_v3_current_main_successor_manifest.schema.json"


def test_successor_manifest_is_complete_and_schema_valid() -> None:
    manifest = _manifest()
    jsonschema.validate(manifest, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    delivered = manifest["deliverables"]
    excluded = manifest["excluded_projection_paths"]
    assert manifest["inspected_projection_path_count"] == len(delivered) + len(excluded) == 40
    assert len({row["path"] for row in delivered + excluded}) == 40
    assert {row["kind"] for row in delivered} == {"config", "source", "schema", "script", "test"}
    assert all(row["test_bindings"] for row in delivered)


def test_successor_deliverables_match_historical_committed_bytes() -> None:
    manifest = _manifest()
    for row in manifest["deliverables"]:
        path = row["path"]
        candidate = ROOT / path
        assert candidate.is_file(), path
        actual_sha = hashlib.sha256(_committed_or_worktree_bytes(path)).hexdigest()
        assert actual_sha == row["successor_sha256"]
        if row["port_action"] == "adapted_fixture_only_current_main_contract":
            assert actual_sha != row["historical_sha256"]
        else:
            assert actual_sha == row["historical_sha256"]


def test_successor_is_us_only_research_only_and_fail_closed() -> None:
    manifest = _manifest()
    allowed_roots = ("configs/", "quant_us/", "schemas/", "scripts/", "tests/")
    forbidden_fragments = ("quant_crypto/", "quant_cn/", "backend/", "frontend/")
    assert all(row["path"].startswith(allowed_roots) for row in manifest["deliverables"])
    assert not any(
        fragment in row["path"]
        for row in manifest["deliverables"]
        for fragment in forbidden_fragments
    )
    assert manifest["decision"] == "research_only"
    assert all(value is False for key, value in manifest["gate_impact"].items() if key.endswith("_ready"))
    assert all(value is False for value in manifest["safety"].values())
    assert manifest["whole_branch_merge_authorized"] is False
    assert manifest["range_cherry_pick_authorized"] is False


def test_historical_branch_audit_tooling_is_explicitly_superseded() -> None:
    excluded = _manifest()["excluded_projection_paths"]
    assert len(excluded) == 5
    assert all(row["port_action"] == "excluded" for row in excluded)
    assert all(
        row["reason"] == "historical_branch_audit_tooling_superseded_by_current_main_successor_manifest"
        for row in excluded
    )


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _committed_or_worktree_bytes(path: str) -> bytes:
    dirty = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", path],
        cwd=ROOT,
        check=False,
    )
    if dirty.returncode != 0:
        return (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
    completed = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode == 0:
        return completed.stdout
    return (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
