from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.data.dataready_consumer import (  # noqa: E402
    KLINE_MANIFEST_DATA_SCHEMA,
    L2_DATASET_ID,
    L2_MANIFEST_DATA_SCHEMA,
    SNAPSHOT_DATASET_ID,
    consume_btc_dataready,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (  # noqa: E402
    BTCRuntimeArtifactWriter,
)
from tools.agent_governance.shared_data import (  # noqa: E402
    SCHEMA_VERSION as SHARED_DATA_MANIFEST_SCHEMA_VERSION,
    default_shared_data_root,
)


DEFAULT_RUNTIME_POINTER = ".agent/runtime_manifests/btc-market-data-v1.json"
DEFAULT_OUTPUT = (
    "artifacts/btc_dataready_consumption/latest/"
    "btc_dataready_consumption_report.json"
)
MANIFEST_ROOT = ".agent/data_manifests"
MANIFEST_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EXPECTED_DATA_SCHEMAS = {
    SNAPSHOT_DATASET_ID: KLINE_MANIFEST_DATA_SCHEMA,
    L2_DATASET_ID: L2_MANIFEST_DATA_SCHEMA,
}
L2_BLOCKED_MANIFEST_DATA_SCHEMA = "btc_okx_l2_blocked_attestation_v1"


def build_report(
    *,
    repo_root: Path,
    shared_root: Path,
    now: datetime,
    snapshot_manifest_path: str = "",
    snapshot_dataset_version: str = "",
    l2_manifest_path: str = "",
    l2_dataset_version: str = "",
) -> dict[str, Any]:
    current_head = _git_text(repo_root, "rev-parse", "HEAD")
    runtime_pointer = _load_committed_json(repo_root, current_head, DEFAULT_RUNTIME_POINTER)
    snapshot_manifest, snapshot_source, snapshot_discovery_blocker = _discover_manifest(
        repo_root,
        current_head,
        SNAPSHOT_DATASET_ID,
        manifest_path=snapshot_manifest_path,
        dataset_version=snapshot_dataset_version,
    )
    l2_manifest, l2_source, l2_discovery_blocker = _discover_manifest(
        repo_root,
        current_head,
        L2_DATASET_ID,
        manifest_path=l2_manifest_path,
        dataset_version=l2_dataset_version,
    )
    report = consume_btc_dataready(
        runtime_pointer=runtime_pointer,
        snapshot_manifest=snapshot_manifest,
        l2_manifest=l2_manifest,
        shared_root=shared_root,
        current_head=current_head,
        now=now,
        commit_exists=lambda commit: _git_commit_exists(repo_root, commit),
        snapshot_manifest_source=snapshot_source,
        l2_manifest_source=l2_source,
    )
    discovery_blockers = [
        item
        for item in (snapshot_discovery_blocker, l2_discovery_blocker)
        if item
    ]
    if discovery_blockers:
        report["blockers"] = list(dict.fromkeys([*report["blockers"], *discovery_blockers]))
        report["status"] = "blocked"
        report["decision"] = "block_dataready_consumption_fail_closed"
        report["readiness"] = {
            "quality_checked": False,
            "research_ready": False,
            "backtest_ready": False,
            "promotion_evidence_ready": False,
        }
    return report


def _discover_manifest(
    repo_root: Path,
    ref: str,
    dataset_id: str,
    *,
    manifest_path: str = "",
    dataset_version: str = "",
) -> tuple[dict[str, Any] | None, str, str]:
    if manifest_path and not _is_allowed_manifest_path(manifest_path):
        return None, "", f"committed_manifest_path_invalid:{dataset_id}"
    if dataset_version and not MANIFEST_IDENTIFIER_PATTERN.fullmatch(dataset_version):
        return None, "", f"committed_manifest_version_invalid:{dataset_id}"
    if manifest_path:
        payload = _load_committed_json(repo_root, ref, manifest_path)
        if payload is None:
            return None, "", f"committed_manifest_path_not_found:{dataset_id}"
        identity_blocker = _manifest_identity_blocker(
            payload,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )
        if identity_blocker:
            return None, "", identity_blocker
        return payload, f"{ref}:{manifest_path}", ""

    paths = [
        path
        for path in _git_text(
            repo_root,
            "ls-tree",
            "-r",
            "--name-only",
            ref,
            "--",
            ".agent/data_manifests",
        ).splitlines()
        if _is_allowed_manifest_path(path)
    ]
    matches: list[tuple[str, dict[str, Any]]] = []
    for path in paths:
        payload = _load_committed_json(repo_root, ref, path)
        if not payload:
            continue
        if payload.get("schema_version") != SHARED_DATA_MANIFEST_SCHEMA_VERSION:
            continue
        if payload.get("dataset_id") != dataset_id:
            continue
        actual_version = payload.get("dataset_version")
        if (
            dataset_version
            and isinstance(actual_version, str)
            and MANIFEST_IDENTIFIER_PATTERN.fullmatch(actual_version)
            and actual_version != dataset_version
        ):
            continue
        identity_blocker = _manifest_identity_blocker(
            payload,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )
        if identity_blocker:
            return None, "", identity_blocker
        matches.append((path, payload))
    if len(matches) > 1:
        return None, "", f"committed_manifest_selection_required:{dataset_id}"
    if not matches:
        blocker = (
            f"committed_manifest_version_not_found:{dataset_id}:{dataset_version}"
            if dataset_version
            else ""
        )
        return None, "", blocker
    path, payload = matches[0]
    return payload, f"{ref}:{path}", ""


def _is_allowed_manifest_path(path: str) -> bool:
    if not path or "\\" in path or path.startswith("/"):
        return False
    pure = PurePosixPath(path)
    return (
        not pure.is_absolute()
        and ".." not in pure.parts
        and pure.as_posix() == path
        and path.startswith(f"{MANIFEST_ROOT}/")
        and pure.suffix.lower() == ".json"
    )


def _manifest_identity_blocker(
    payload: dict[str, Any],
    *,
    dataset_id: str,
    dataset_version: str,
) -> str:
    if payload.get("schema_version") != SHARED_DATA_MANIFEST_SCHEMA_VERSION:
        return f"committed_manifest_schema_invalid:{dataset_id}"
    if payload.get("dataset_id") != dataset_id:
        return f"committed_manifest_dataset_mismatch:{dataset_id}"
    actual_version = payload.get("dataset_version")
    if not isinstance(actual_version, str) or not MANIFEST_IDENTIFIER_PATTERN.fullmatch(actual_version):
        return f"committed_manifest_schema_invalid:{dataset_id}"
    if dataset_version and actual_version != dataset_version:
        return f"committed_manifest_version_mismatch:{dataset_id}"
    if payload.get("producer_role") != "data_steward":
        return f"committed_manifest_schema_invalid:{dataset_id}"
    if not _manifest_data_contract_allowed(payload, dataset_id=dataset_id):
        return f"committed_manifest_schema_invalid:{dataset_id}"
    if payload.get("storage_relative_path") != f"datasets/{dataset_id}/{actual_version}":
        return f"committed_manifest_schema_invalid:{dataset_id}"
    return ""


def _manifest_data_contract_allowed(
    payload: dict[str, Any],
    *,
    dataset_id: str,
) -> bool:
    if payload.get("data_schema") == EXPECTED_DATA_SCHEMAS.get(dataset_id):
        return True
    blockers = payload.get("blockers")
    return (
        dataset_id == L2_DATASET_ID
        and payload.get("data_schema") == L2_BLOCKED_MANIFEST_DATA_SCHEMA
        and payload.get("quality_status") == "blocked"
        and isinstance(blockers, list)
        and bool(blockers)
        and all(isinstance(item, str) and bool(item) for item in blockers)
    )


def _load_committed_json(repo_root: Path, ref: str, path: str) -> dict[str, Any] | None:
    try:
        raw = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _git_commit_exists(repo_root: Path, commit: str) -> bool:
    if len(commit) != 40:
        return False
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
    )
    return result.returncode == 0


def _git_text(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def write_report(
    *,
    repo_root: Path,
    logical_output: str | Path,
    report: dict[str, Any],
    artifact_writer: BTCRuntimeArtifactWriter | None = None,
) -> Path:
    writer = artifact_writer or BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=repo_root
    )
    with writer.exclusive() as session:
        return session.write_json_atomic(logical_output, report)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed BTC immutable DataReady consumption report."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--shared-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument("--now", default="")
    parser.add_argument("--snapshot-manifest-path", default="")
    parser.add_argument("--snapshot-dataset-version", default="")
    parser.add_argument("--l2-manifest-path", default="")
    parser.add_argument("--l2-dataset-version", default="")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    shared_root = (
        args.shared_root.resolve()
        if args.shared_root
        else default_shared_data_root(repo_root).resolve()
    )
    now = _parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    report = build_report(
        repo_root=repo_root,
        shared_root=shared_root,
        now=now,
        snapshot_manifest_path=args.snapshot_manifest_path,
        snapshot_dataset_version=args.snapshot_dataset_version,
        l2_manifest_path=args.l2_manifest_path,
        l2_dataset_version=args.l2_dataset_version,
    )
    write_report(
        repo_root=repo_root,
        logical_output=args.output,
        report=report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "quality_checked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
