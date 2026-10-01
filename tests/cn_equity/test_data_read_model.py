from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from quant_cn.application.data_read_model import consume_cn_dataready
from quant_cn.data.read_model import (
    CN_DATAREADY_DATA_SCHEMA,
    CN_DATAREADY_EVIDENCE_FILE,
    CN_DATAREADY_EVIDENCE_SCHEMA,
)
from quant_cn.operations.blockers import (
    CN_DATAREADY_ADJUSTMENT_VISIBILITY_MISSING,
    CN_DATAREADY_COMMON_DATE_STALE,
    CN_DATAREADY_CORPORATE_ACTION_VISIBILITY_MISSING,
    CN_DATAREADY_COVERAGE_INCOMPLETE,
    CN_DATAREADY_HANDOFF_INVALID,
    CN_DATAREADY_LICENSE_UNVERIFIED,
    CN_DATAREADY_MANIFEST_BLOCKED,
    CN_DATAREADY_MANIFEST_MISSING,
    CN_DATAREADY_MANIFEST_RESOLVE_FAILED,
    CN_DATAREADY_PILOT_ONLY,
    CN_DATAREADY_PIT_INCOMPLETE,
    CN_DATAREADY_RISK_WARNING_HISTORY_MISSING,
)
from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    aggregate_inventory_hash,
    build_manifest,
)


UTC = timezone.utc
NOW = datetime(2025, 1, 10, 12, tzinfo=UTC)
HEAD = "a" * 40
PRODUCER = "b" * 40
REPO_ROOT = Path(__file__).resolve().parents[2]


def _clean_evidence(
    *,
    dataset_id: str = "cn-equity-dataready",
    dataset_version: str = "cn-dataready-v1",
) -> dict[str, Any]:
    visible_history = {"covered": True, "available_time": True}
    return {
        "schema_version": CN_DATAREADY_EVIDENCE_SCHEMA,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "common_date": "2025-01-10",
        "coverage": {
            "security_count": 4800,
            "expected_security_count": 5000,
            "ratio": 0.96,
            "pilot": False,
        },
        "pit": {
            "event_time": True,
            "available_time": True,
            "ingested_at": True,
            "processed_at": True,
        },
        "quality": {
            "status": "pass",
            "missing_count": 0,
            "duplicate_count": 0,
            "out_of_order_count": 0,
            "blocking_issues": [],
        },
        "license": {
            "verified": True,
            "research_backtest_allowed": True,
        },
        "market_state": {
            "listing": visible_history,
            "delisting": visible_history,
            "risk_warning": visible_history,
            "suspension": visible_history,
        },
        "corporate_actions": {
            "covered": True,
            "available_time": True,
        },
        "adjustments": {
            "raw_price_preserved": True,
            "factor_versioned": True,
            "available_time": True,
        },
    }


def _build_fixture(
    tmp_path: Path,
    *,
    evidence: dict[str, Any] | None = None,
    quality_status: str = "pass",
    blockers: tuple[str, ...] = (),
    known_gaps: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    payload = evidence or _clean_evidence()
    dataset_id = str(payload["dataset_id"])
    dataset_version = str(payload["dataset_version"])
    shared_root = tmp_path / "shared-data"
    version_root = shared_root / "datasets" / dataset_id / dataset_version
    version_root.mkdir(parents=True)
    evidence_path = version_root / CN_DATAREADY_EVIDENCE_FILE
    evidence_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_bytes = evidence_path.read_bytes()
    files = [
        {
            "path": CN_DATAREADY_EVIDENCE_FILE,
            "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
            "bytes": len(evidence_bytes),
        }
    ]
    manifest = build_manifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        readiness_class="research_ready",
        quality_status=quality_status,
        files=files,
        aggregate_sha256=aggregate_inventory_hash(files),
        total_bytes=len(evidence_bytes),
        producer_commit=PRODUCER,
        blockers=blockers,
        known_gaps=known_gaps,
        schema_name=CN_DATAREADY_DATA_SCHEMA,
        coverage_start="2024-01-01",
        coverage_end="2025-01-10",
        published_at="2025-01-10T11:00:00Z",
    )
    encoded_manifest = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    (version_root / MANIFEST_NAME).write_text(
        encoded_manifest,
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(encoded_manifest, encoding="utf-8")
    return manifest_path, shared_root


def _consume(manifest_path: Path | None, shared_root: Path, **overrides):
    values = {
        "manifest_path": manifest_path,
        "shared_root": shared_root,
        "handoff_event_id": "published-cn-dataready-current-main-v1",
        "handoff_validated": True,
        "evaluated_at": NOW,
        "current_head": HEAD,
        "manifest_reference": (
            ".agent/data_manifests/cn-equity-dataready/cn-dataready-v1.json"
        ),
    }
    values.update(overrides)
    return consume_cn_dataready(**values)


def _codes(result) -> set[str]:
    return {item.code for item in result.model.blockers}


def _snapshot_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_missing_or_unvalidated_handoff_and_manifest_fail_closed(tmp_path: Path) -> None:
    invalid = _consume(
        tmp_path / "missing.json",
        tmp_path / "shared",
        handoff_validated=False,
    )
    assert _codes(invalid) == {CN_DATAREADY_HANDOFF_INVALID}
    assert invalid.shared_snapshot is None
    missing = _consume(None, tmp_path / "shared")
    assert _codes(missing) == {CN_DATAREADY_MANIFEST_MISSING}
    assert missing.model.decision == "blocked"
    assert all(value is False for value in missing.model.safety_flags.values())


def test_resolver_consumes_clean_immutable_version_without_writes(
    tmp_path: Path,
) -> None:
    manifest_path, shared_root = _build_fixture(tmp_path)
    before_manifest = manifest_path.read_bytes()
    before_tree = _snapshot_tree(shared_root)
    result = _consume(manifest_path, shared_root)
    assert result.model.status == "pass"
    assert result.model.decision == "research_only"
    assert result.model.coverage_ratio == 0.96
    assert result.consumer_read_only is True
    assert result.shared_snapshot.status == "pass"
    assert result.shared_snapshot.decision == "research_only"
    assert manifest_path.read_bytes() == before_manifest
    assert _snapshot_tree(shared_root) == before_tree


def test_two_security_pilot_is_not_dataready(tmp_path: Path) -> None:
    evidence = _clean_evidence()
    evidence["coverage"] = {
        "security_count": 2,
        "expected_security_count": 5000,
        "ratio": 0.0004,
        "pilot": True,
    }
    manifest_path, shared_root = _build_fixture(tmp_path, evidence=evidence)
    result = _consume(manifest_path, shared_root)
    assert result.model.status == "blocked"
    assert CN_DATAREADY_PILOT_ONLY in _codes(result)
    assert CN_DATAREADY_COVERAGE_INCOMPLETE in _codes(result)
    assert result.shared_snapshot.status == "blocked"


def test_hash_mismatch_is_blocked_by_official_resolver(tmp_path: Path) -> None:
    manifest_path, shared_root = _build_fixture(tmp_path)
    evidence_path = next(shared_root.rglob(CN_DATAREADY_EVIDENCE_FILE))
    evidence_path.write_text("{}\n", encoding="utf-8")
    result = _consume(manifest_path, shared_root)
    assert _codes(result) == {CN_DATAREADY_MANIFEST_RESOLVE_FAILED}
    assert "shared_data_file_size_mismatch" in result.model.blockers[0].detail


def test_pit_license_market_state_actions_and_adjustments_fail_closed(
    tmp_path: Path,
) -> None:
    evidence = _clean_evidence()
    evidence["common_date"] = "2024-12-01"
    evidence["pit"]["available_time"] = False
    evidence["license"]["verified"] = False
    evidence["market_state"]["risk_warning"] = {
        "covered": False,
        "available_time": False,
    }
    evidence["corporate_actions"]["available_time"] = False
    evidence["adjustments"]["factor_versioned"] = False
    manifest_path, shared_root = _build_fixture(tmp_path, evidence=evidence)
    result = _consume(manifest_path, shared_root)
    assert {
        CN_DATAREADY_COMMON_DATE_STALE,
        CN_DATAREADY_PIT_INCOMPLETE,
        CN_DATAREADY_LICENSE_UNVERIFIED,
        CN_DATAREADY_RISK_WARNING_HISTORY_MISSING,
        CN_DATAREADY_CORPORATE_ACTION_VISIBILITY_MISSING,
        CN_DATAREADY_ADJUSTMENT_VISIBILITY_MISSING,
    } <= _codes(result)
    assert result.model.decision == "blocked"


def test_manifest_blockers_are_preserved_without_upgrading_readiness(
    tmp_path: Path,
) -> None:
    manifest_path, shared_root = _build_fixture(
        tmp_path,
        quality_status="blocked",
        blockers=("cn_license_scope_unverified",),
    )
    result = _consume(manifest_path, shared_root)
    assert CN_DATAREADY_MANIFEST_BLOCKED in _codes(result)
    assert result.model.status == "blocked"
    assert result.model.decision == "blocked"
    assert all(value is False for value in result.model.safety_flags.values())


def test_consumer_has_no_network_or_write_api_surface() -> None:
    path = REPO_ROOT / "quant_cn" / "application" / "data_read_model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    called_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.append(node.func.attr)
    assert not {
        "aiohttp",
        "httpx",
        "requests",
        "socket",
        "urllib",
    } & {module.split(".", 1)[0] for module in imported}
    assert not {
        "publish_dataset",
        "write_bytes",
        "write_text",
        "open",
        "unlink",
    } & set(called_names)
