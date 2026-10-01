#!/usr/bin/env python3
"""Offline CLI for the current-main authoritative BTC data pointer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.btc_current_head_authoritative_data_pointer import (  # noqa: E402
    PublicationError,
    publish_current_head_authoritative_data_pointer,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (  # noqa: E402
    BTCRuntimeArtifactStoreError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve exact committed immutable 10s feed manifests, bind a "
            "verified ESS artifact and optional real depth-fill mapping, then "
            "publish the external current-main pointer last."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--shared-root", type=Path)
    parser.add_argument(
        "--manifest-git-spec",
        action="append",
        default=[],
        help="Repeatable exact committed immutable feed manifest Git spec.",
    )
    parser.add_argument("--ess-artifact-git-spec")
    parser.add_argument("--depth-fill-mapping-git-spec")
    parser.add_argument("--run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = publish_current_head_authoritative_data_pointer(
            repo_root=args.repo_root,
            expected_head=args.expected_head,
            shared_root=args.shared_root,
            run_id=args.run_id,
            manifest_git_specs=args.manifest_git_spec or None,
            ess_artifact_git_spec=args.ess_artifact_git_spec,
            depth_fill_mapping_git_spec=args.depth_fill_mapping_git_spec,
        )
    except (PublicationError, BTCRuntimeArtifactStoreError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_fail_closed",
                    "error": str(exc),
                    "promotion": False,
                    "paper": False,
                    "live": False,
                    "private": False,
                    "order": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
