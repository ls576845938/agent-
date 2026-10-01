#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.production_pit_intake import (  # noqa: E402
    build_production_pit_intake_report,
    find_committed_production_pit_events,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_production_pit_intake/latest")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed US-equity production PIT intake report."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    output_root = _resolve(root, Path(args.output_root))
    scan = _run_json(
        [
            sys.executable,
            str(root / "tools/agent_governance/handoff.py"),
            "--repo-root",
            str(root),
            "scan",
        ],
        cwd=root,
    )
    validation_status: dict[str, str] = {}
    for candidate in find_committed_production_pit_events(scan):
        result = _run_json(
            [
                sys.executable,
                str(root / "tools/agent_governance/handoff.py"),
                "--repo-root",
                str(root),
                "validate",
                "--input",
                candidate["path"],
            ],
            cwd=root,
        )
        validation_status[candidate["event_id"]] = str(result.get("status", "invalid"))

    json_path = output_root / "us_equity_production_pit_intake_report.json"
    markdown_path = output_root / "us_equity_production_pit_intake_report.md"
    report = build_production_pit_intake_report(
        scan=scan,
        validation_status_by_event=validation_status,
        code_commit=_git(root, "rev-parse", "HEAD"),
        branch=_git(root, "branch", "--show-current"),
        outputs={
            "json": _relpath(json_path, root),
            "markdown": _relpath(markdown_path, root),
        },
    )
    _write_json(json_path, report)
    _write_text(markdown_path, _markdown(report))
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "code_commit": report["code_commit"],
                "blockers": report["blockers"],
                "guardrails": report["guardrails"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _run_json(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed closed ({completed.returncode}): {' '.join(command)}"
        )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("JSON object required from governance command")
    return payload


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity Production PIT Intake",
        "",
        f"- 状态：`{report['status']}`",
        f"- 决策：`{report['decision']}`",
        f"- HEAD：`{report['code_commit']}`",
        "- Fixture 只能证明 plumbing，不能成为 production PIT 或 promotion-clean 证据。",
        "- HF ETF26 保持 research_ready；QQQ/TQQQ raw minute 保持 raw_evidence。",
        "- 本报告不解锁 Goal 3、promotion、paper、live、private 或 order。",
        "",
        "## Exact blockers",
        "",
        *[f"- `{blocker}`" for blocker in report["blockers"]],
        "",
    ]
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, text: str) -> None:
    _atomic_write(path, text + "\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git command failed closed: {' '.join(args)}")
    return completed.stdout.strip()


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
