#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.ga_factor_mining import (
    DEFAULT_GA_CANDIDATE_EXPRESSIONS,
    DEFAULT_GA_CANDIDATE_REVIEW_MARKDOWN,
    DEFAULT_GA_CANDIDATE_REVIEW_PACKET,
    DEFAULT_GA_FACTOR_MINING_REPORT,
    write_btc_ga_candidate_review_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report-path", type=Path, default=DEFAULT_GA_FACTOR_MINING_REPORT)
    parser.add_argument("--candidate-path", type=Path, default=DEFAULT_GA_CANDIDATE_EXPRESSIONS)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_GA_CANDIDATE_REVIEW_PACKET)
    parser.add_argument("--markdown-path", type=Path, default=DEFAULT_GA_CANDIDATE_REVIEW_MARKDOWN)
    args = parser.parse_args()

    report = write_btc_ga_candidate_review_packet(
        source_report_path=args.source_report_path,
        candidate_path=args.candidate_path,
        output_path=args.output_path,
        markdown_path=args.markdown_path,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "candidate_count": report["review_summary"]["candidate_count"],
                "extended_research_shortlist_count": report["review_summary"][
                    "extended_research_shortlist_count"
                ],
                "reject_count": report["review_summary"]["reject_count"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "output_path": str(args.output_path).replace("\\", "/"),
                "markdown_path": str(args.markdown_path).replace("\\", "/"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
