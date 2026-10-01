#!/usr/bin/env python3
"""Build bounded, fixture-only US paper OMS reconciliation evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping
import uuid

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.live.paper_oms_reconciliation import (  # noqa: E402
    build_fixture_evidence,
)


DEFAULT_CONFIG = Path(
    "configs/execution/us_v3_paper_oms_reconciliation_v1.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build fixture-only US paper OMS reconciliation evidence."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-root", default="")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    config_path = _resolve(root, Path(args.config))
    _require_within(root, config_path)
    config = _read_json(config_path)
    output_root = _resolve(
        root,
        Path(args.output_root or str(config["output_root"])),
    )
    _require_within(root, output_root)
    _validate_safe_config(config)
    producer = _validated_handoff(
        root,
        str(config["g07_producer_handoff"]),
    )
    integrated = _validated_handoff(
        root,
        str(config["g07_integrated_handoff"]),
    )
    if integrated.get("transition_for") != producer.get("event_id"):
        raise ValueError("g07_integrated_handoff_transition_mismatch")

    code_commit = _git(root, "rev-parse", "HEAD")
    code_tree_hash = _git(root, "rev-parse", "HEAD^{tree}")
    generated_at = _git(root, "show", "-s", "--format=%cI", "HEAD")
    config_relative = config_path.relative_to(root).as_posix()
    config_sha256 = hashlib.sha256(
        _git_bytes(root, "show", f"HEAD:{config_relative}")
    ).hexdigest()
    with tempfile.TemporaryDirectory(
        prefix="us-v3-paper-oms-reconciliation-01-"
    ) as temporary:
        report = build_fixture_evidence(
            work_root=Path(temporary),
            generated_at=generated_at,
            code_commit=code_commit,
            code_tree_hash=code_tree_hash,
            config_sha256=config_sha256,
            initial_cash=float(config["initial_cash"]),
            commission_bps=float(config["commission_bps"]),
        )

    schema = _read_json(_resolve(root, Path(str(config["report_schema"]))))
    jsonschema.validate(
        report,
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    report_path = output_root / "report.json"
    _write_json(report_path, report)
    manifest = {
        "schema_version": "us_v3_paper_oms_reconciliation_manifest_v1",
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "config_path": config_relative,
        "config_sha256": config_sha256,
        "root": output_root.relative_to(root).as_posix(),
        "immutable": True,
        "fixture_only": True,
        "paper_started": False,
        "report_artifact_identity_sha256": report[
            "artifact_identity_sha256"
        ],
        "upstream_handoffs": [
            producer["event_id"],
            integrated["event_id"],
        ],
        "files": [
            {
                "path": "report.json",
                "sha256": _sha256_file(report_path),
                "bytes": report_path.stat().st_size,
            }
        ],
    }
    manifest_path = output_root / "manifest.json"
    _write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "artifact_identity_sha256": report[
                    "artifact_identity_sha256"
                ],
                "report_sha256": _sha256_file(report_path),
                "manifest_sha256": _sha256_file(manifest_path),
                "report": report_path.relative_to(root).as_posix(),
                "guardrails": report["guardrails"],
                "blockers": report["blockers"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _validate_safe_config(config: Mapping[str, Any]) -> None:
    required_false = (
        "network_allowed",
        "paper_start_allowed",
        "paper_queue_write_allowed",
        "broker_endpoint_allowed",
        "private_endpoint_allowed",
        "order_endpoint_allowed",
    )
    blockers = [
        f"unsafe_config_flag:{field}"
        for field in required_false
        if config.get(field) is not False
    ]
    if config.get("runtime_mode") != "fixture_only":
        blockers.append("runtime_mode_not_fixture_only")
    if config.get("fake_adapter_required") is not True:
        blockers.append("fake_adapter_not_required")
    if blockers:
        raise ValueError(",".join(blockers))


def _validated_handoff(root: Path, relative_path: str) -> dict[str, Any]:
    path = _resolve(root, Path(relative_path))
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools/agent_governance/handoff.py"),
            "--repo-root",
            str(root),
            "validate",
            "--input",
            str(path),
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ValueError(
            f"upstream_handoff_invalid:{relative_path}:"
            f"{completed.stdout.strip()}:{completed.stderr.strip()}"
        )
    result = json.loads(completed.stdout)
    if result.get("status") != "valid":
        raise ValueError(f"upstream_handoff_not_valid:{relative_path}")
    return _read_json(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"json_object_required:{path}")
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    dict(payload),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _require_within(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path_outside_repo:{path}") from exc


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
