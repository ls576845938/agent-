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

from quant_crypto.research.btc_demo_observation_accumulator import (
    append_hourly_observation_receipt,
    build_awaiting_authorized_runtime_receipt,
    build_observation_window_report,
    load_observation_receipt_ledger,
    safety_flags,
    stable_payload_hash,
    write_observation_window_artifact,
)


DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "btc_demo_observation_accumulator"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the authoritative BTC OKX Demo 25-hour observation accumulator "
            "without starting any runtime."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("awaiting", "append-recorded-receipt"),
        default="awaiting",
    )
    parser.add_argument("--receipt-input", type=Path)
    parser.add_argument("--ledger-path", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--source-head")
    parser.add_argument(
        "--strategy-version",
        default="btc_strategy_version_unavailable",
    )
    parser.add_argument(
        "--data-version",
        default="btc_immutable_data_version_unavailable",
    )
    parser.add_argument(
        "--runtime-version",
        default="btc_demo_runtime_version_unavailable",
    )
    parser.add_argument("--generated-at-utc")
    args = parser.parse_args()

    generated = (
        _parse_datetime(args.generated_at_utc)
        if args.generated_at_utc
        else datetime.now(timezone.utc)
    )
    source_head = args.source_head or _git_head()
    run_id = args.run_id or (
        "btc-g10-observation-"
        + generated.strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    ledger_path = (
        args.ledger_path
        or args.output_root / "hourly_observation_receipts.jsonl"
    )
    try:
        append_result: dict[str, Any] | None = None
        if args.mode == "append-recorded-receipt":
            if args.receipt_input is None:
                raise ValueError(
                    "receipt_input_required_for_append_recorded_receipt"
                )
            receipt = _read_json(args.receipt_input)
            append_result = append_hourly_observation_receipt(
                ledger_path=ledger_path,
                receipt=receipt,
            )
        receipts = load_observation_receipt_ledger(ledger_path)
        report = build_observation_window_report(
            receipts=receipts,
            current_head=source_head,
            current_strategy_version=args.strategy_version,
            current_data_version=args.data_version,
            current_runtime_version=args.runtime_version,
            run_id=run_id,
            generated_at_utc=generated,
        )
        if args.mode == "awaiting":
            authorization_receipt = build_awaiting_authorized_runtime_receipt(
                source_head=source_head,
                strategy_version=args.strategy_version,
                data_version=args.data_version,
                runtime_version=args.runtime_version,
                generated_at_utc=generated,
                run_id=run_id,
            )
            report = {
                **report,
                "runtime_authorization_receipt": authorization_receipt,
            }
            report["artifact_hash"] = stable_payload_hash(
                report,
                exclude={"artifact_hash"},
            )
        artifact = write_observation_window_artifact(
            report=report,
            output_root=args.output_root,
            run_id=run_id,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_fail_closed",
                    "decision": "observation_accumulator_error_no_runtime",
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
                "observation_hours": report["observation_hours"],
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
