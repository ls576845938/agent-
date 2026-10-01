#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.regime_conditional_5m_alpha_search import (
    DEFAULT_EXPERIMENT_ID,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SEED,
    run_btc_regime_conditional_5m_alpha_search,
    run_btc_regime_conditional_neighborhood_correction,
)


def _timestamp(value: str) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run offline research-only BTC 5m regime-conditional Pareto genetic "
            "alpha search with fixed sizing and risk policies."
        )
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--population-size", type=int, default=48)
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--fold-count", type=int, default=4)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--search-round-count", type=int, default=1)
    parser.add_argument("--prior-search-unique-evaluations", type=int, default=0)
    parser.add_argument(
        "--frozen-unseen-holdout-start",
        default="",
        help=(
            "UTC start of the immutable unseen tail. Requires exactly one candidate, "
            "the prior cutoff and --no-prior-shared-tail-exposure."
        ),
    )
    parser.add_argument(
        "--prior-research-cutoff",
        default="",
        help="UTC final selection bar, exactly five minutes before the unseen tail.",
    )
    parser.add_argument(
        "--prior-shared-tail-exposure",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID)
    parser.add_argument("--generated-at", default="")
    parser.add_argument(
        "--resume-selection-report",
        type=Path,
        default=None,
        help=(
            "Selection-only correction mode: immutable source report whose locked "
            "candidate still lacks completed parameter-neighborhood evidence."
        ),
    )
    parser.add_argument(
        "--resume-candidate-lock",
        type=Path,
        default=None,
        help="Selection-only correction mode: matching preserved-unseen candidate lock.",
    )
    args = parser.parse_args()

    correction_mode = (
        args.resume_selection_report is not None
        or args.resume_candidate_lock is not None
    )
    if correction_mode:
        if args.resume_selection_report is None or args.resume_candidate_lock is None:
            parser.error(
                "--resume-selection-report and --resume-candidate-lock must be paired"
            )
        report = run_btc_regime_conditional_neighborhood_correction(
            source_report_path=args.resume_selection_report,
            source_lock_path=args.resume_candidate_lock,
            output_root=args.output_root,
            repo_root=ROOT,
            generated_at_utc=_timestamp(args.generated_at),
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "decision": report["decision"],
                    "artifact_hash": report["artifact_hash"],
                    "code_commit": report["code_commit"],
                    "output_root": args.output_root.as_posix(),
                    "correction_unique_evaluations": report[
                        "correction_unique_evaluations"
                    ],
                    "holdout_exposure_after_run": report[
                        "holdout_exposure_after_run"
                    ],
                    "holdout_strategy_metrics_read": False,
                    "public_network_called": False,
                    "promotion": False,
                    "paper": False,
                    "live": False,
                    "private": False,
                    "order": False,
                    "real_order": False,
                    "transfer": False,
                    "withdraw": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    report = run_btc_regime_conditional_5m_alpha_search(
        repo_root=ROOT,
        output_root=args.output_root,
        seed=args.seed,
        population_size=args.population_size,
        generations=args.generations,
        fold_count=args.fold_count,
        holdout_fraction=args.holdout_fraction,
        max_candidates=args.max_candidates,
        prior_shared_tail_exposure=args.prior_shared_tail_exposure,
        search_round_count=args.search_round_count,
        prior_search_unique_evaluations=args.prior_search_unique_evaluations,
        frozen_unseen_holdout_start_utc=_timestamp(args.frozen_unseen_holdout_start),
        prior_research_cutoff_utc=_timestamp(args.prior_research_cutoff),
        experiment_id=args.experiment_id,
        generated_at_utc=_timestamp(args.generated_at),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "retained_research_candidate_count": report[
                    "retained_research_candidate_count"
                ],
                "artifact_hash": report["artifact_hash"],
                "code_commit": report["code_commit"],
                "output_root": args.output_root.as_posix(),
                "holdout_exposure_after_run": report["validation_design"][
                    "holdout_exposure_after_run"
                ],
                "public_network_called": False,
                "promotion": False,
                "paper": False,
                "live": False,
                "private": False,
                "order": False,
                "real_order": False,
                "transfer": False,
                "withdraw": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
