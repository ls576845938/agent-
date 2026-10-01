#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_depth_slippage import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    build_btc_depth_slippage_fill_mapping_report,
)
from tools.agent_governance.shared_data import default_shared_data_root  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC strategy-fill to OKX depth mapping evidence.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--shared-root", type=Path)
    parser.add_argument(
        "--l2-manifest-git-spec",
        action="append",
        required=True,
        help="Repeatable exact committed immutable ordered-L2 manifest Git spec.",
    )
    parser.add_argument(
        "--natural-fill-ledger-manifest-git-spec",
        required=True,
        help="Exact committed immutable natural non-diagnostic fill-ledger manifest Git spec.",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at_utc) if args.generated_at_utc else None
    report = build_btc_depth_slippage_fill_mapping_report(
        repo_root=args.repo_root,
        output_root=args.output_root,
        immutable_l2_manifest_git_specs=args.l2_manifest_git_spec,
        natural_fill_ledger_manifest_git_spec=args.natural_fill_ledger_manifest_git_spec,
        shared_root=args.shared_root or default_shared_data_root(args.repo_root.resolve()),
        run_id=args.run_id,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "strategy_fill_mapping_verified": report["strategy_fill_mapping_verified"],
                "fill_mapping_state": report["fill_mapping_state"],
                "summary": report["summary"],
                "blockers": report["blockers"],
                "output": str(args.output_root / "btc_depth_slippage_fill_mapping_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
