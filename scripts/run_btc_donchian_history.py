from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.donchian_historical_replay import (  # noqa: E402
    DonchianHistoricalReplay,
    build_market_policy_replay_plan,
    load_historical_input,
)
from quant_crypto.application.donchian_history_spec import HistorySpec, legacy_spec


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or inspect the frozen BTC Donchian historical replay."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "resume", "status", "check-data"):
        command = subparsers.add_parser(name)
        if name != "check-data":
            command.add_argument("--output-root", type=Path, required=True)
            command.add_argument("--run-id", required=True)
        if name != "status":
            command.add_argument("--max-events", type=int)
            command.add_argument("--shared-root", type=Path)
            command.add_argument("--spec-git", help="Exact 40-character commit:path to frozen specification; omitted selects the legacy week.")
            command.add_argument(
                "--market-policy-protocol-git",
                help="Exact committed docs/research protocol used by a bounded entry-only replay.",
            )
            command.add_argument(
                "--market-policy-evidence-git",
                help="Exact committed .agent/market_state_evidence diagnostic authority.",
            )
            command.add_argument(
                "--market-policy-arm",
                choices=("baseline", "conditioned"),
                help="Frozen A/B arm; requires protocol and evidence refs.",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check-data":
        spec = HistorySpec.from_git(REPO_ROOT, args.spec_git) if args.spec_git else legacy_spec()
        source = load_historical_input(REPO_ROOT, shared_root=args.shared_root, spec=spec)
        result = {"status": "quality_checked", "spec_digest": spec.digest,
                  "window": spec.payload["window"], "warmup_rows": spec.warmup_rows,
                  "evaluation_rows": len(source.signal_rows), "funding_settlements": len(source.funding_events),
                  "evaluation_not_run": True, "permissions_granted": False}
        policy_parts = (
            args.market_policy_protocol_git,
            args.market_policy_evidence_git,
            args.market_policy_arm,
        )
        if any(value is not None for value in policy_parts):
            if not all(value for value in policy_parts):
                raise ValueError("market_policy_replay_binding_incomplete")
            source_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
            ).strip()
            plan = build_market_policy_replay_plan(
                repo_root=REPO_ROOT,
                spec=spec,
                source_head=source_head,
                protocol_git_spec=args.market_policy_protocol_git,
                evidence_git_spec=args.market_policy_evidence_git,
                arm=args.market_policy_arm,
            )
            result["market_entry_policy"] = {
                "arm": plan.arm,
                "attachment_hash": plan.attachment["attachment_hash"],
                "analysis_start_utc": plan.analysis_start.isoformat(),
                "analysis_end_exclusive_utc": plan.analysis_end.isoformat(),
                "expected_analysis_bars": plan.expected_analysis_bars,
                "policy_trial_not_started": True,
            }
    elif args.command == "status":
        result = DonchianHistoricalReplay.status(
            output_root=args.output_root, run_id=args.run_id
        )
    else:
        dirty = subprocess.check_output([
            "git", "status", "--porcelain", "--untracked-files=all", "--",
            "quant_crypto", "quant_shared", "integrations/qlib_adapter",
            "scripts/run_btc_donchian_history.py",
        ], cwd=REPO_ROOT, text=True)
        if dirty.strip():
            raise ValueError("historical_source_must_be_committed_before_run")
        if args.command == "resume" and DonchianHistoricalReplay.status(output_root=args.output_root, run_id=args.run_id)["status"] == "not_started":
            raise ValueError("historical_resume_requires_existing_run")
        runner = DonchianHistoricalReplay(
            repo_root=REPO_ROOT,
            output_root=args.output_root,
            run_id=args.run_id,
            shared_root=args.shared_root,
            spec_git=args.spec_git,
            market_policy_protocol_git=args.market_policy_protocol_git,
            market_policy_evidence_git=args.market_policy_evidence_git,
            market_policy_arm=args.market_policy_arm,
        )
        result = runner.run(max_events=args.max_events)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
