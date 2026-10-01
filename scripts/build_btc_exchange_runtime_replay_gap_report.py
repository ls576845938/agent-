from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_exchange_runtime_replay_gap import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAPER_RUNTIME_DRILL_PATH,
    DEFAULT_PAPER_RUNTIME_FIXTURE_DRILL_PATH,
    DEFAULT_PAPER_RUNTIME_RECONCILIATION_PATH,
    DEFAULT_PAPER_RUNTIME_REPLAY_PATH,
    DEFAULT_PUBLIC_RUNTIME_DRY_PROBE_PATH,
    DEFAULT_PUBLIC_WS_COVERAGE_PATH,
    DEFAULT_RUNTIME_CONTRACT_PATH,
    build_btc_exchange_runtime_replay_gap_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC exchange runtime replay gap report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--runtime-contract", type=Path, default=DEFAULT_RUNTIME_CONTRACT_PATH)
    parser.add_argument("--public-runtime-dry-probe", type=Path, default=DEFAULT_PUBLIC_RUNTIME_DRY_PROBE_PATH)
    parser.add_argument("--public-ws-coverage", type=Path, default=DEFAULT_PUBLIC_WS_COVERAGE_PATH)
    parser.add_argument("--paper-runtime-replay", type=Path, default=DEFAULT_PAPER_RUNTIME_REPLAY_PATH)
    parser.add_argument("--paper-runtime-drill", type=Path, default=DEFAULT_PAPER_RUNTIME_DRILL_PATH)
    parser.add_argument("--paper-runtime-fixture-drill", type=Path, default=DEFAULT_PAPER_RUNTIME_FIXTURE_DRILL_PATH)
    parser.add_argument("--paper-runtime-reconciliation", type=Path, default=DEFAULT_PAPER_RUNTIME_RECONCILIATION_PATH)
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_exchange_runtime_replay_gap_report(
        output_dir=args.output_dir,
        runtime_contract_path=args.runtime_contract,
        public_runtime_dry_probe_path=args.public_runtime_dry_probe,
        public_ws_coverage_path=args.public_ws_coverage,
        paper_runtime_replay_path=args.paper_runtime_replay,
        paper_runtime_drill_path=args.paper_runtime_drill,
        paper_runtime_fixture_drill_path=args.paper_runtime_fixture_drill,
        paper_runtime_reconciliation_path=args.paper_runtime_reconciliation,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "blocker_count": report["summary"]["blocker_count"],
                "runtime_contract_is_simulated_probe": report["summary"]["runtime_contract_is_simulated_probe"],
                "runtime_contract_effective_layer": report["summary"]["runtime_contract_effective_layer"],
                "public_runtime_dry_probe_passed": report["summary"]["public_runtime_dry_probe_passed"],
                "public_ws_coverage_contract_satisfied": report["summary"]["public_ws_coverage_contract_satisfied"],
                "execution_latency_model_ready": report["summary"]["execution_latency_model_ready"],
                "queue_model_ready": report["summary"]["queue_model_ready"],
                "paper_runtime_replay_ready": report["summary"]["paper_runtime_replay_ready"],
                "fixture_capability_status": report["summary"]["fixture_capability_status"],
                "historical_drill_status": report["summary"]["historical_drill_status"],
                "current_observe_only_gate_evidence_status": report["summary"][
                    "current_observe_only_gate_evidence_status"
                ],
                "fixture_or_drill_cannot_satisfy_paper_gate": report["summary"][
                    "fixture_or_drill_cannot_satisfy_paper_gate"
                ],
                "paper_runtime_drill_simulated_fill_count": report["summary"]["paper_runtime_drill_simulated_fill_count"],
                "paper_runtime_drill_event_ledger_row_count": report["summary"]["paper_runtime_drill_event_ledger_row_count"],
                "paper_runtime_drill_gate_evidence": report["summary"]["paper_runtime_drill_gate_evidence"],
                "paper_runtime_reconciliation_passed": report["summary"]["paper_runtime_reconciliation_passed"],
                "paper_runtime_reconciliation_violation_count": report["summary"]["paper_runtime_reconciliation_violation_count"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
