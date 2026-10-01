from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.backtest.us_etf_26_canonical import build_us_etf_26_canonical_run
from quant_us.data.shared_hf_etf26 import resolve_hf_etf26_dataset


DEFAULT_CONFIG = Path("configs/backtest/us_etf_26_canonical_backtest_v1.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the frozen ETF26 canonical research-only backtest evidence.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--artifact-root", default="")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    config_path = Path(args.config)
    config_abs = config_path if config_path.is_absolute() else root / config_path
    config = json.loads(config_abs.read_text(encoding="utf-8"))
    dataset = resolve_hf_etf26_dataset(
        repo_root=root,
        handoff_event=config["handoff_event"],
        expected_event_id=config["handoff_event_id"],
        manifest_git_spec=config["manifest_git_spec"],
        expected_dataset_id=config["dataset_id"],
        expected_dataset_version=config["dataset_version"],
        expected_aggregate_sha256=config["aggregate_sha256"],
        symbol_file=config["symbol_file"],
    )
    result = build_us_etf_26_canonical_run(
        repo_root=root,
        config_path=config_path,
        resolved_dataset=dataset,
        code_commit=_git(root, "rev-parse", "HEAD"),
        code_tree_hash=_git(root, "rev-parse", "HEAD^{tree}"),
        generated_at=_git(root, "show", "-s", "--format=%cI", "HEAD"),
        artifact_root_override=(root / args.artifact_root).resolve() if args.artifact_root else None,
    )
    print(
        json.dumps(
            {
                "status": result.report["status"],
                "decision": result.report["decision"],
                "run_id": result.run_id,
                "run_dir": result.run_dir.relative_to(root).as_posix(),
                "manifest_sha256": result.manifest_sha256,
                "promotion_credit_allowed": result.report["guardrails"]["promotion_credit_allowed"],
                "paper_or_live_unlock_allowed": result.report["guardrails"]["paper_or_live_unlock_allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
