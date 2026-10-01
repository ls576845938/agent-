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

from quant_crypto.research.btc_perpetual_paper_runtime_replay import (  # noqa: E402
    DEFAULT_BAR_REPLAY_ROWS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_COST_MODEL_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PERPETUAL_EVIDENCE_REPORT,
    build_btc_perpetual_paper_runtime_replay_drill_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC historical paper runtime replay drill report.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--bar-replay-rows", type=Path, default=DEFAULT_BAR_REPLAY_ROWS)
    parser.add_argument("--cost-model-report", type=Path, default=DEFAULT_COST_MODEL_REPORT)
    parser.add_argument("--perpetual-evidence-report", type=Path, default=DEFAULT_PERPETUAL_EVIDENCE_REPORT)
    parser.add_argument("--sample-per-line", type=int, default=8)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_perpetual_paper_runtime_replay_drill_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        config_path=args.config_path,
        bar_replay_rows_path=args.bar_replay_rows,
        cost_model_report_path=args.cost_model_report,
        perpetual_evidence_report_path=args.perpetual_evidence_report,
        sample_per_line=args.sample_per_line,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "observation_line_counts": report["summary"]["observation_line_counts"],
                "theoretical_order_count": report["summary"]["theoretical_order_count"],
                "simulated_fill_count": report["summary"]["simulated_fill_count"],
                "event_ledger_row_count": report["summary"]["event_ledger_row_count"],
                "order_ledger_row_count": report["summary"]["order_ledger_row_count"],
                "fill_ledger_row_count": report["summary"]["fill_ledger_row_count"],
                "oms_session_reconciliation_status": report["summary"]["oms_session_reconciliation_status"],
                "oms_session_unreconciled_count": report["summary"]["oms_session_unreconciled_count"],
                "event_type_counts": report["summary"]["event_type_counts"],
                "risk_approved_count": report["summary"]["risk_approved_count"],
                "blocker_count": report["summary"]["blocker_count"],
                "paper_runtime_gate_evidence": report["summary"]["paper_runtime_gate_evidence"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "warnings": report["warnings"],
                "blockers": report["blockers"],
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


if __name__ == "__main__":
    raise SystemExit(main())
