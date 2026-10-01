#!/usr/bin/env python3
"""Build current-HEAD frozen ETF26 canonical and portfolio evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from typing import Any, Mapping

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.backtest.canonical_portfolio_evidence import (  # noqa: E402
    build_canonical_portfolio_evidence_report,
)
from quant_us.backtest.us_etf_26_canonical import (  # noqa: E402
    build_us_etf_26_canonical_run,
)
from quant_us.data.shared_hf_etf26 import resolve_hf_etf26_dataset  # noqa: E402
from quant_us.portfolio.us_etf_26_candidate_portfolio import (  # noqa: E402
    build_us_etf_26_candidate_portfolio,
)


DEFAULT_CONFIG = Path(
    "configs/backtest/us_v3_canonical_backtest_portfolio_evidence_v1.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build current-HEAD US ETF26 canonical portfolio evidence."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-root", default="")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    config = _read_json(_resolve(root, Path(args.config)))
    output_root = _resolve(
        root,
        Path(args.output_root or str(config["output_root"])),
    )
    _require_within(root, output_root)
    code_commit = _git(root, "rev-parse", "HEAD")
    code_tree_hash = _git(root, "rev-parse", "HEAD^{tree}")
    generated_at = _git(root, "show", "-s", "--format=%cI", "HEAD")

    producer_handoff = _validated_handoff(
        root, str(config["g06_producer_handoff"])
    )
    _validated_handoff(root, str(config["g06_integrated_handoff"]))
    g06 = _read_json(_resolve(root, Path(str(config["g06_report"]))))
    if g06.get("status") != "blocked_external_data":
        raise ValueError("g07_requires_g06_blocked_external_data")

    inputs_dir = output_root / "build_inputs"
    compatibility = {
        **g06,
        "code_commit": producer_handoff["deliverable_commit"],
        "compatibility_adapter": {
            "reason": "legacy canonical builder requires producer code_commit",
            "source_report": str(config["g06_report"]),
            "source_artifact_identity_sha256": g06["artifact_identity_sha256"],
            "source_report_modified": False,
        },
    }
    compatibility_path = inputs_dir / "g06_consumer_compatibility.json"
    _write_json(compatibility_path, compatibility)

    canonical_base = _read_json(
        _resolve(root, Path(str(config["canonical_base_config"])))
    )
    canonical_config = {
        **canonical_base,
        "goal2_intake_report": _relative(compatibility_path, root),
        "artifact_root": _relative(output_root / "canonical", root),
    }
    canonical_config_path = inputs_dir / "canonical_config.json"
    _write_json(canonical_config_path, canonical_config)
    resolved = _resolve_dataset(root, canonical_config)
    canonical = build_us_etf_26_canonical_run(
        repo_root=root,
        config_path=Path(_relative(canonical_config_path, root)),
        resolved_dataset=resolved,
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        generated_at=generated_at,
        artifact_root_override=output_root / "canonical",
    )
    canonical_report_path = canonical.run_dir / "report.json"
    canonical_report_sha = _sha256_file(canonical_report_path)

    portfolio_base = _read_json(
        _resolve(root, Path(str(config["portfolio_base_config"])))
    )
    portfolio_config = {
        **portfolio_base,
        "canonical_latest_pointer": _relative(canonical.latest_pointer, root),
        "goal2_intake_report": _relative(compatibility_path, root),
        "expected_canonical_run_id": canonical.run_id,
        "expected_canonical_code_commit": code_commit,
        "expected_canonical_manifest_sha256": canonical.manifest_sha256,
        "expected_canonical_report_sha256": canonical_report_sha,
        "artifact_root": _relative(output_root / "portfolio", root),
    }
    portfolio_config_path = inputs_dir / "portfolio_config.json"
    _write_json(portfolio_config_path, portfolio_config)
    portfolio = build_us_etf_26_candidate_portfolio(
        repo_root=root,
        config_path=Path(_relative(portfolio_config_path, root)),
        resolved_dataset=resolved,
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        generated_at=generated_at,
        artifact_root_override=output_root / "portfolio",
    )
    portfolio_report_path = portfolio.run_dir / "report.json"
    exposure = _read_jsonl(canonical.run_dir / "exposure_timeline.jsonl")
    fills = _read_jsonl(canonical.run_dir / "fills.jsonl")

    report = build_canonical_portfolio_evidence_report(
        canonical_report=canonical.report,
        portfolio_report=portfolio.report,
        g06_report=g06,
        exposure_sessions=[str(row["session"]) for row in exposure],
        fill_records=fills,
        artifacts={
            "output_root": _relative(output_root, root),
            "canonical_run_id": canonical.run_id,
            "canonical_manifest_sha256": canonical.manifest_sha256,
            "canonical_report_sha256": canonical_report_sha,
            "portfolio_run_id": portfolio.run_id,
            "portfolio_manifest_sha256": portfolio.manifest_sha256,
            "portfolio_report_sha256": _sha256_file(portfolio_report_path),
            "g06_report": str(config["g06_report"]),
            "g06_report_sha256": _sha256_file(
                _resolve(root, Path(str(config["g06_report"])))
            ),
            "full_replay_outputs_persisted_in_git": False,
            "full_replay_outputs_reproducible_by_script": True,
        },
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        generated_at=generated_at,
    )
    schema = _read_json(_resolve(root, Path(str(config["report_schema"]))))
    jsonschema.validate(report, schema, format_checker=jsonschema.FormatChecker())
    report_path = output_root / "report.json"
    _write_json(report_path, report)
    for transient_dir in ("canonical", "portfolio", "build_inputs"):
        _remove_owned_transient(output_root / transient_dir, output_root)
    manifest = _artifact_manifest(
        output_root=output_root,
        root=root,
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        report_identity=str(report["artifact_identity_sha256"]),
    )
    manifest_path = output_root / "manifest.json"
    _write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "canonical_run_id": canonical.run_id,
                "portfolio_run_id": portfolio.run_id,
                "artifact_identity_sha256": report["artifact_identity_sha256"],
                "manifest_sha256": _sha256_file(manifest_path),
                "report": _relative(report_path, root),
                "blockers": report["blockers"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _resolve_dataset(root: Path, config: Mapping[str, Any]):
    return resolve_hf_etf26_dataset(
        repo_root=root,
        handoff_event=str(config["handoff_event"]),
        expected_event_id=str(config["handoff_event_id"]),
        manifest_git_spec=str(config["manifest_git_spec"]),
        expected_dataset_id=str(config["dataset_id"]),
        expected_dataset_version=str(config["dataset_version"]),
        expected_aggregate_sha256=str(config["aggregate_sha256"]),
        symbol_file=str(config["symbol_file"]),
    )


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
        raise ValueError(f"g07_handoff_invalid:{relative_path}")
    validation = json.loads(completed.stdout)
    if validation.get("status") != "valid":
        raise ValueError(f"g07_handoff_invalid:{relative_path}")
    return _read_json(path)


def _artifact_manifest(
    *,
    output_root: Path,
    root: Path,
    code_commit: str,
    code_tree_hash: str,
    report_identity: str,
) -> dict[str, Any]:
    files = []
    for path in sorted(
        item
        for item in output_root.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    ):
        files.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": "us_v3_canonical_backtest_portfolio_evidence_manifest_v1",
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "root": _relative(output_root, root),
        "immutable": True,
        "report_artifact_identity_sha256": report_identity,
        "file_count": len(files),
        "files": files,
    }


def _remove_owned_transient(path: Path, output_root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = output_root.resolve()
    if resolved_path.parent != resolved_root:
        raise ValueError("g07_transient_cleanup_outside_output_root")
    if resolved_path.exists():
        shutil.rmtree(resolved_path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _require_within(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("g07_output_root_outside_repo") from exc


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
