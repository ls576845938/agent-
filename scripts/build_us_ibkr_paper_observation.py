from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.live.ibkr_paper_observation import (  # noqa: E402
    IbkrPaperObservationError,
    append_daily_observation_receipt,
    build_daily_observation_receipt,
    build_observation_report,
    load_observation_ledger,
    validate_input_envelope,
    write_observation_report_artifact,
)


REQUIRED_MAIN_ANCESTOR = "d3f1e3f7f770bfdf35336257cf1eaecc18f3d6b6"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Append one offline IBKR paper natural-day observation from "
            "content-addressed receipts and write an immutable report."
        )
    )
    parser.add_argument("--strategy-identity", type=Path, required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument("--broker-receipt", type=Path, required=True)
    parser.add_argument("--reconciliation-report", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--observed-at-utc",
        required=True,
        help="Timezone-aware natural observation timestamp; backfill is forbidden.",
    )
    parser.add_argument(
        "--operating-timezone", default="America/New_York"
    )
    parser.add_argument(
        "--required-main-ancestor", default=REQUIRED_MAIN_ANCESTOR
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    observed_at = _parse_utc(args.observed_at_utc)
    inputs = {
        "strategy_identity": _read_json(args.strategy_identity),
        "data_manifest": _read_json(args.data_manifest),
        "runtime_receipt": _read_json(args.runtime_receipt),
        "broker_receipt": _read_json(args.broker_receipt),
        "reconciliation_report": _read_json(args.reconciliation_report),
    }
    for kind, envelope in inputs.items():
        blockers = validate_input_envelope(envelope, expected_kind=kind)
        if blockers:
            raise IbkrPaperObservationError(blockers[0])
        _require_local_commit(str(envelope["source_commit"]))

    runtime = inputs["runtime_receipt"]["payload"]
    _require_authorized_integrated_runtime(runtime)
    current_head = str(runtime["code_head"])
    registered_main_head = _resolve_ref("refs/heads/main")
    if current_head != registered_main_head:
        raise IbkrPaperObservationError(
            "paper_observation_runtime_head_not_registered_main"
        )
    _require_ancestor(args.required_main_ancestor, current_head)
    for envelope in inputs.values():
        _require_ancestor(str(envelope["source_commit"]), current_head)
    existing = load_observation_ledger(args.ledger)
    previous_hash = (
        str(existing[-1]["receipt_sha256"]) if existing else None
    )
    receipt = build_daily_observation_receipt(
        strategy_identity=inputs["strategy_identity"],
        data_manifest=inputs["data_manifest"],
        runtime_receipt=inputs["runtime_receipt"],
        broker_receipt=inputs["broker_receipt"],
        reconciliation_report=inputs["reconciliation_report"],
        observed_at_utc=observed_at,
        previous_receipt_sha256=previous_hash,
        operating_timezone=args.operating_timezone,
        backfilled=False,
    )
    append_result = append_daily_observation_receipt(
        ledger_path=args.ledger,
        receipt=receipt,
    )
    receipts = load_observation_ledger(args.ledger)
    report = build_observation_report(
        receipts=receipts,
        current_head=current_head,
        current_observation_run_id=str(runtime["observation_run_id"]),
        generated_at_utc=datetime.now(timezone.utc),
    )
    artifact = write_observation_report_artifact(
        report=report,
        output_root=args.output_root,
    )
    return {
        "append": append_result,
        "receipt_sha256": str(receipt["receipt_sha256"]),
        "report": report,
        "artifact": artifact,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise IbkrPaperObservationError(
            f"paper_observation_json_object_required:{path}"
        )
    return payload


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise IbkrPaperObservationError(
            "paper_observation_timezone_aware_datetime_required"
        )
    return parsed.astimezone(timezone.utc)


def _require_local_commit(commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise IbkrPaperObservationError(
            "paper_observation_input_commit_not_available_locally"
        )


def _resolve_ref(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise IbkrPaperObservationError(
            "paper_observation_registered_main_unavailable"
        )
    return result.stdout.strip()


def _require_ancestor(ancestor: str, descendant: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise IbkrPaperObservationError(
            "paper_observation_required_main_ancestor_missing"
        )


def _require_authorized_integrated_runtime(runtime: Mapping[str, Any]) -> None:
    receipts = runtime.get("independent_integration_receipts")
    if (
        not isinstance(receipts, list)
        or not all(isinstance(value, str) for value in receipts)
        or len(set(receipts)) < 2
    ):
        raise IbkrPaperObservationError(
            "paper_observation_two_independent_integrations_required"
        )
    if runtime.get("paper_submit_authorized") is not True:
        raise IbkrPaperObservationError(
            "paper_observation_real_paper_submit_authorization_required"
        )
    if (
        runtime.get("runtime_mode") != "ibkr_paper"
        or runtime.get("real_paper_session") is not True
        or runtime.get("fixture") is not False
        or runtime.get("read_only") is not False
        or runtime.get("no_submit") is not False
    ):
        raise IbkrPaperObservationError(
            "paper_observation_real_paper_runtime_required"
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except (IbkrPaperObservationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_fail_closed_no_runtime_write",
                    "error": str(exc),
                    "paper_order_allowed": False,
                    "live_order_allowed": False,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
