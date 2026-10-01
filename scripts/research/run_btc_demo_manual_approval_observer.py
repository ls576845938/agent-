from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_demo_manual_approval_observer import (
    append_manual_approval_fact,
    build_btc_demo_manual_approval_observer,
    write_btc_demo_manual_approval_observer_evidence,
)
from quant_crypto.research.btc_demo_observation_accumulator import safety_flags


DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "btc_demo_manual_approval_observer"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an independently approved BTC fact or emit an awaiting "
            "receipt. This observer cannot approve or start a runtime."
        )
    )
    parser.add_argument("--approval-fact", type=Path)
    parser.add_argument("--approval-ledger", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--source-head")
    parser.add_argument("--generated-at-utc")
    args = parser.parse_args()

    generated = (
        _parse_datetime(args.generated_at_utc)
        if args.generated_at_utc
        else datetime.now(timezone.utc)
    )
    source_head = args.source_head or _git_head()
    run_id = args.run_id or (
        "btc-g10-manual-approval-"
        + generated.strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    try:
        approval_fact = (
            _read_json(args.approval_fact)
            if args.approval_fact is not None
            else None
        )
        report = build_btc_demo_manual_approval_observer(
            approval_fact=approval_fact,
            source_head=source_head,
            run_id=run_id,
            generated_at_utc=generated,
        )
        append_result: dict[str, Any] | None = None
        if approval_fact is not None and report["manual_approval_recorded"]:
            ledger_path = (
                args.approval_ledger
                or args.output_root / "approved_facts.jsonl"
            )
            append_result = append_manual_approval_fact(
                ledger_path=ledger_path,
                approval_fact=approval_fact,
                expected_source_head=source_head,
                generated_at_utc=generated,
            )
        artifact = write_btc_demo_manual_approval_observer_evidence(
            report=report,
            output_root=args.output_root,
            run_id=run_id,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_fail_closed",
                    "decision": "manual_approval_observer_error_no_runtime",
                    "error_code": type(exc).__name__,
                    "blockers": [str(exc)],
                    "safety": safety_flags(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "run_id": run_id,
                "source_head": source_head,
                "manual_approval_recorded": report[
                    "manual_approval_recorded"
                ],
                "append_result": append_result,
                "blockers": report["blockers"],
                "artifact": artifact,
                "safety": report["safety"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path.name}")
    return payload


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("generated_at_timezone_required")
    return parsed.astimezone(timezone.utc)


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
