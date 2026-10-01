from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    SharedDataError,
    load_manifest_from_git,
    publish_dataset,
    resolve_manifest_file,
    resolve_manifest_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO_ROOT / "schemas" / "shared_dataset_manifest.schema.json").read_text(encoding="utf-8"))


def _publish(tmp_path: Path, **overrides: object) -> dict[str, object]:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    if not (source / "SPY.parquet").exists():
        (source / "SPY.parquet").write_bytes(b"fixture-parquet")
    if not (source / "metadata.json").exists():
        (source / "metadata.json").write_text('{"finalized": true}\n', encoding="utf-8")
    options: dict[str, object] = {
        "source": source,
        "shared_root": tmp_path / "shared",
        "dataset_id": "us-etf-minute",
        "dataset_version": "fixture-v1",
        "readiness_class": "research_ready",
        "quality_status": "pass_with_research_only_warnings",
        "producer_role": "data_steward",
        "producer_commit": "a" * 40,
        "schema_name": "hf_etf_clean_1min_v1",
        "known_gaps": ["pit_adjustment_not_proven"],
        "manifest_output": tmp_path / "repo-manifest.json",
    }
    options.update(overrides)
    return publish_dataset(**options)  # type: ignore[arg-type]


def test_publish_is_atomic_immutable_and_resolvable(tmp_path: Path) -> None:
    result = _publish(tmp_path)
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    Draft202012Validator(SCHEMA).validate(manifest)
    assert result["status"] == "published"
    assert manifest["readiness_class"] == "research_ready"
    assert manifest["guardrails"]["promotion_unlock_allowed"] is False

    target = resolve_manifest_file(
        tmp_path / "repo-manifest.json",
        shared_root=tmp_path / "shared",
        verify_files=True,
    )
    assert (target / "SPY.parquet").read_bytes() == b"fixture-parquet"
    assert json.loads((target / MANIFEST_NAME).read_text(encoding="utf-8")) == manifest

    repeated = _publish(tmp_path)
    assert repeated["status"] == "already_published"

    (tmp_path / "source" / "SPY.parquet").write_bytes(b"different")
    with pytest.raises(SharedDataError, match="dataset_version_immutable_conflict"):
        _publish(tmp_path)


def test_shared_data_rejects_wrong_role_mutable_database_and_false_readiness(tmp_path: Path) -> None:
    with pytest.raises(SharedDataError, match="publish_role_forbidden"):
        _publish(tmp_path, producer_role="super_developer")

    source = tmp_path / "db-source"
    source.mkdir()
    (source / "market.sqlite").write_bytes(b"not-a-database")
    with pytest.raises(SharedDataError, match="shared_mutable_database_not_allowed"):
        publish_dataset(
            source=source,
            shared_root=tmp_path / "shared-db",
            dataset_id="db-data",
            dataset_version="v1",
            readiness_class="quality_checked",
            quality_status="pass",
            producer_role="data_steward",
            producer_commit="a" * 40,
            schema_name="db_v1",
        )

    with pytest.raises(SharedDataError, match="advanced_readiness_requires_clean_quality"):
        _publish(tmp_path, readiness_class="promotion_evidence_ready")


def test_resolver_fails_closed_on_missing_or_changed_physical_file(tmp_path: Path) -> None:
    result = _publish(tmp_path)
    target = Path(str(result["path"]))
    (target / "SPY.parquet").write_bytes(b"tampered")
    with pytest.raises(SharedDataError, match="file_(size|hash)_mismatch"):
        resolve_manifest_file(
            tmp_path / "repo-manifest.json",
            shared_root=tmp_path / "shared",
            verify_files=True,
        )


def test_consumer_can_resolve_committed_manifest_from_another_branch(tmp_path: Path) -> None:
    result = _publish(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    manifest_path = repo / ".agent" / "data_manifests" / "fixture" / "v1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(result["manifest"], indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", manifest_path.relative_to(repo).as_posix()], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "manifest"], cwd=repo, check=True, capture_output=True)

    payload = load_manifest_from_git(repo, "main:.agent/data_manifests/fixture/v1.json")
    target = resolve_manifest_payload(payload, shared_root=tmp_path / "shared", verify_files=True)
    assert target == Path(str(result["path"]))

    with pytest.raises(SharedDataError, match="git_path_forbidden"):
        load_manifest_from_git(repo, "main:README.md")
