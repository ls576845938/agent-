from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.shared_hf_etf26 import resolve_hf_etf26_dataset
from quant_us.portfolio.us_etf_26_candidate_portfolio import (
    build_us_etf_26_candidate_portfolio,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build candidate-specific ETF26 portfolio and blocked promotion evidence."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/portfolio/us_etf_26_candidate_portfolio_v1.json"),
    )
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--generated-at")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    generated_at = args.generated_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    code_commit = _git(root, "rev-parse", "HEAD")
    code_tree_hash = _git(root, "rev-parse", "HEAD^{tree}")
    resolved = resolve_hf_etf26_dataset(
        repo_root=root,
        handoff_event=str(config["handoff_event"]),
        expected_event_id=str(config["handoff_event_id"]),
        manifest_git_spec=str(config["manifest_git_spec"]),
        expected_dataset_id=str(config["dataset_id"]),
        expected_dataset_version=str(config["dataset_version"]),
        expected_aggregate_sha256=str(config["aggregate_sha256"]),
        symbol_file=str(config["symbol_file"]),
    )
    artifact_root = None
    if args.artifact_root is not None:
        artifact_root = (
            args.artifact_root.resolve()
            if args.artifact_root.is_absolute()
            else (root / args.artifact_root).resolve()
        )
    result = build_us_etf_26_candidate_portfolio(
        repo_root=root,
        config_path=config_path,
        resolved_dataset=resolved,
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        generated_at=generated_at,
        artifact_root_override=artifact_root,
    )
    print(
        json.dumps(
            {
                "status": result.report["status"],
                "decision": result.report["decision"],
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "latest_pointer": str(result.latest_pointer),
                "manifest_sha256": result.manifest_sha256,
                "promotion_credit_allowed": False,
                "paper_or_live_unlock_allowed": False,
            },
            indent=2,
        )
    )
    return 0


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ValueError(f"goal4_git_command_failed:{' '.join(args)}")
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
