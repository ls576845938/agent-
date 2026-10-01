#!/usr/bin/env python3
"""Initialize the local, ignored US equity manual decision record file.

This copies only the safe blank template. It does not approve paper/live and it
must not be committed after the operator fills reviewer-specific fields.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.live.manual_decision_record import (  # noqa: E402
    DEFAULT_RECORD,
    DEFAULT_TEMPLATE,
    evaluate_manual_decision_local_init,
)


SCHEMA_VERSION = "us_equity_manual_decision_record_local_init_v1"
DEFAULT_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_local_init_report.json")


def init_us_equity_manual_decision_record_local(
    *,
    repo_root: Path | None = None,
    template: Path = DEFAULT_TEMPLATE,
    local_record: Path = DEFAULT_RECORD,
    report: Path = DEFAULT_REPORT,
    force: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    template_path = _resolve(root, template)
    local_path = _resolve(root, local_record)
    report_path = _resolve(root, report)
    generated = generated_at or _utc_z_now()
    template_payload = _read_json(template_path)
    evaluation = evaluate_manual_decision_local_init(
        template=template_payload,
        template_exists=template_path.exists(),
        local_record_exists=local_path.exists(),
        force=force,
    )

    if not evaluation.blockers:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_path, local_path)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": evaluation.status,
        "allowed_statuses": ["manual_decision_local_init_blocked", "manual_decision_local_initialized"],
        "template": _relpath(template_path, root),
        "local_record": _relpath(local_path, root),
        "local_record_exists_after": local_path.exists(),
        "actions": evaluation.actions,
        "blockers": evaluation.blockers,
        "operator_next_actions": evaluation.operator_next_actions,
        "guardrails": evaluation.guardrails,
    }
    _write_json(report_path, payload)
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "unreadable", "read_error": type(exc).__name__}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--local-record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = init_us_equity_manual_decision_record_local(
        repo_root=args.repo_root,
        template=args.template,
        local_record=args.local_record,
        report=args.report,
        force=args.force,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
