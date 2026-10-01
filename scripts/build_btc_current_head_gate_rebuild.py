from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.btc_current_head_gate_rebuild import (  # noqa: E402
    rebuild_btc_current_head_gate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline, fail-closed reconstruction of the current-HEAD BTC gate, "
            "dashboard and domain read model."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--run-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    head = _git_head(root)
    report = rebuild_btc_current_head_gate(
        repo_root=root,
        current_head=head,
        run_id=args.run_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "source_head": report["source_head"],
                "run_id": report["run_id"],
                "data_version": report["data_version"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
                "snapshot_publication": report["snapshot_publication"],
                "quality_checked": report["quality_checked"],
                "research_ready": report["research_ready"],
                "backtest_ready": report["backtest_ready"],
                "promotion_evidence_ready": report[
                    "promotion_evidence_ready"
                ],
                "safety": report["safety"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    head = result.stdout.strip()
    if result.returncode != 0 or len(head) != 40:
        raise RuntimeError("btc_current_head_gate_git_head_unavailable")
    return head


if __name__ == "__main__":
    raise SystemExit(main())
