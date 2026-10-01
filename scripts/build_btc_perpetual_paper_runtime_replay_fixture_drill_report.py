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
    DEFAULT_OUTPUT_DIR,
    build_btc_perpetual_paper_runtime_replay_fixture_drill_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC deterministic fixture paper runtime replay drill report.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_perpetual_paper_runtime_replay_fixture_drill_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "fixture_scenario_count": report["summary"]["fixture_scenario_count"],
                "theoretical_order_count": report["summary"]["theoretical_order_count"],
                "simulated_fill_count": report["summary"]["simulated_fill_count"],
                "funding_cashflow_event_count": report["summary"]["funding_cashflow_event_count"],
                "order_ledger_row_count": report["summary"]["order_ledger_row_count"],
                "fill_ledger_row_count": report["summary"]["fill_ledger_row_count"],
                "oms_session_reconciliation_status": report["summary"]["oms_session_reconciliation_status"],
                "oms_session_unreconciled_count": report["summary"]["oms_session_unreconciled_count"],
                "mark_index_price_visible": report["summary"]["mark_index_price_visible"],
                "liquidation_buffer_visible_in_replay": report["summary"]["liquidation_buffer_visible_in_replay"],
                "paper_runtime_gate_evidence": report["summary"]["paper_runtime_gate_evidence"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "warnings": report["warnings"],
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
