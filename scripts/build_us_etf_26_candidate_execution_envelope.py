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

from quant_us.live.us_etf_26_candidate_execution_envelope import build_candidate_execution_envelope


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local-only ETF26 candidate execution and paper envelope evidence.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path, default=Path("configs/execution/us_etf_26_candidate_execution_envelope_v1.json"))
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    artifact_root = None if args.artifact_root is None else (args.artifact_root.resolve() if args.artifact_root.is_absolute() else (root / args.artifact_root).resolve())
    result = build_candidate_execution_envelope(
        repo_root=root,
        config_path=config,
        code_commit=_git(root, "rev-parse", "HEAD"),
        code_tree_hash=_git(root, "rev-parse", "HEAD^{tree}"),
        generated_at=args.generated_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        artifact_root_override=artifact_root,
    )
    print(json.dumps({
        "status": result.report["status"],
        "run_id": result.run_id,
        "run_dir": str(result.run_dir),
        "latest_pointer": str(result.latest_pointer),
        "manifest_sha256": result.manifest_sha256,
        "paper_order_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "real_order_submitted": False,
    }, indent=2))
    return 0


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, check=False, capture_output=True, text=True, encoding="utf-8")
    if completed.returncode != 0:
        raise ValueError(f"goal5_git_command_failed:{' '.join(args)}")
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
