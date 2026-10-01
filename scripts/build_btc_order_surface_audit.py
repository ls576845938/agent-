#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.order_surface_audit import audit_btc_direct_order_call_surface  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("artifacts/btc_security/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_order_surface_audit_report.json"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_order_surface_audit_safety_status.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC quant_crypto order surface audit report.")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def build_btc_order_surface_audit_report(
    *,
    repo_root: Path = ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source_files = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "quant_crypto").rglob("*.py"))
    }
    report = audit_btc_direct_order_call_surface(
        source_files,
        generated_at_utc=generated,
        aggregation_batch_id=aggregation_batch_id,
    )
    report["code_commit"] = _git(["rev-parse", "--short", "HEAD"], cwd=root)
    report["scope"] = "btc_quant_crypto_order_surface_audit_no_private_no_order_no_broker"
    report["gate"] = _gate()
    report["guardrails"] = _guardrails()
    report["outputs"] = {
        "json": _portable_path(output / DEFAULT_REPORT_PATH.name),
        "paper_live_safety_status": _portable_path(output / DEFAULT_SAFETY_PATH.name),
    }
    _write_json(output / DEFAULT_REPORT_PATH.name, report)
    _write_json(output / DEFAULT_SAFETY_PATH.name, _safety_status(report))
    return report


def main() -> int:
    args = parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_order_surface_audit_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        generated_at_utc=generated,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "finding_count": len(report.get("findings", [])),
                "non_blocking_match_count": report.get("non_blocking_match_count"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path) -> str:
    return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_order_surface_audit_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
