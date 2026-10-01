from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactWriter,
)
from quant_crypto.application.btc_strategy_history import (
    SOURCE_REPORT_RELATIVE_PATH,
    publish_btc_strategy_history_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish a content-addressed BTC Top5 research report snapshot "
            "to QS_BTC_RUNTIME_ARTIFACT_ROOT."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository containing the report, tracked data lineage, and Git HEAD.",
    )
    parser.add_argument(
        "--source-commit",
        required=True,
        help=(
            "Report code_commit; the publisher resolves it and rejects relabeling "
            "that does not match the report provenance."
        ),
    )
    parser.add_argument(
        "--producer-commit",
        required=True,
        help=(
            "Expected producer Git HEAD; the publisher resolves it and rejects "
            "stale or unrelated caller labels."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    source_path = repo_root / SOURCE_REPORT_RELATIVE_PATH
    writer = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=repo_root,
    )
    receipt = publish_btc_strategy_history_snapshot(
        writer,
        source_path=source_path,
        source_commit=str(args.source_commit),
        producer_commit=str(args.producer_commit),
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
