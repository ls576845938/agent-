#!/usr/bin/env python3
"""Initialize the local, ignored broker credential review file.

This writes only the safe review template to the local operator file. It must
not contain API keys, account numbers, tokens, or broker secrets.
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

from scripts.build_us_equity_broker_credentials_review_report import (  # noqa: E402
    DEFAULT_REVIEW_INPUT,
    DEFAULT_TEMPLATE,
)


DEFAULT_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_local_review_init_report.json")
SCHEMA_VERSION = "us_equity_broker_credentials_local_review_init_v1"
SECRET_LIKE_VALUE_KEYS = {
    "api_key",
    "access_key",
    "secret",
    "token",
    "passphrase",
    "password",
    "private_key",
    "account_number",
}


def init_us_equity_broker_credentials_local_review(
    *,
    repo_root: Path | None = None,
    template: Path = DEFAULT_TEMPLATE,
    local_review: Path = DEFAULT_REVIEW_INPUT,
    report: Path = DEFAULT_REPORT,
    force: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    template_path = _resolve(root, template)
    local_path = _resolve(root, local_review)
    report_path = _resolve(root, report)
    generated = generated_at or _utc_z_now()
    blockers: list[str] = []
    actions: list[str] = []

    template_payload = _read_json(template_path)
    if not template_path.exists():
        blockers.append("broker_credentials_template_missing")
    if template_payload.get("schema_version") != "us_equity_broker_credentials_review_input_v1":
        blockers.append("broker_credentials_template_schema_invalid")
    if _secret_like_values(template_payload):
        blockers.append("broker_credentials_template_contains_secret_like_value")
    if local_path.exists() and not force:
        blockers.append("broker_credentials_local_review_already_exists")

    if not blockers:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_path, local_path)
        actions.append("local_review_template_copied")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": "local_review_initialized" if not blockers else "local_review_init_blocked",
        "allowed_statuses": ["local_review_init_blocked", "local_review_initialized"],
        "template": _relpath(template_path, root),
        "local_review": _relpath(local_path, root),
        "local_review_exists_after": local_path.exists(),
        "actions": actions,
        "blockers": _dedupe(blockers),
        "operator_next_actions": [
            "Open configs/execution/us_equity_broker_credentials_review.local.json locally.",
            "Fill reviewer, reviewed_at, broker_name, account_id_hash as sha256:<64 hex chars>, and manual_approval_ticket.",
            "Do not write API keys, account numbers, tokens, passwords, or funding details.",
            "Keep read_only_or_live_disabled=true and order_permission_enabled=false.",
            "Run: python scripts/build_us_equity_broker_credentials_review_report.py",
        ],
        "guardrails": {
            "local_template_init_only": True,
            "contains_secret_values": False,
            "secret_values_must_not_be_written": True,
            "local_review_should_not_be_committed": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
            "real_order_submitted": False,
        },
    }
    _write_json(report_path, payload)
    return payload


def _secret_like_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in SECRET_LIKE_VALUE_KEYS) and isinstance(child, str) and child.strip():
                found.append(str(key))
            found.extend(_secret_like_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_secret_like_values(child))
    return _dedupe(found)


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


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--local-review", type=Path, default=DEFAULT_REVIEW_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = init_us_equity_broker_credentials_local_review(
        repo_root=args.repo_root,
        template=args.template,
        local_review=args.local_review,
        report=args.report,
        force=args.force,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
