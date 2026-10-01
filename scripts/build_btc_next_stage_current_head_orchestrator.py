#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.btc_next_stage_current_head_orchestrator import (  # noqa: E402
    BTCNextStageOrchestratorError,
    run_btc_next_stage_current_head_orchestrator,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build current-HEAD BTC next-stage evidence on a fresh external root."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--data-integrated-handoff", type=Path, required=True)
    parser.add_argument(
        "--engineering-integrated-handoff", type=Path, required=True
    )
    parser.add_argument(
        "--real-l2-attestation-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--real-l2-attestation-shared-root", type=Path, required=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_btc_next_stage_current_head_orchestrator(
            repo_root=args.repo_root,
            expected_head=args.expected_head,
            run_id=args.run_id,
            data_manifest=args.data_manifest,
            data_integrated_handoff=args.data_integrated_handoff,
            engineering_integrated_handoff=args.engineering_integrated_handoff,
            real_l2_attestation_manifest=args.real_l2_attestation_manifest,
            real_l2_attestation_shared_root=(
                args.real_l2_attestation_shared_root
            ),
        )
    except BTCNextStageOrchestratorError as exc:
        report = {
            "status": "blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "error": str(exc).split(":", 1)[0],
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
        }
        exit_code = 2
    else:
        exit_code = 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
