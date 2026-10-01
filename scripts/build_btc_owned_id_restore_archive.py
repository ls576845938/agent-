"""Build one identity-bound BTC OKX Demo owned-ID restore archive.

This entry point is intentionally private-GET-only.  It does not expose order,
cancel, transfer, withdraw, or live flags; the injected publisher composition
root remains fail-closed unless the existing Windows keyring and read-only
adapter are available.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.btc_owned_id_restore_archive import (
    OwnedIDRestoreArchiveError,
    build_okx_demo_private_read_provider,
    publish_owned_id_restore_archive,
)
from quant_crypto.oms.okx_demo import (
    OkxDemoSafetyError,
    load_windows_keyring_credentials,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one identity-bound BTC OKX Demo owned-ID restore archive"
    )
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--credential-service",
        default="quant-system.okx-demo.trade",
        help="Existing Windows keyring namespace; the secret values are never printed.",
    )
    parser.add_argument("--current-head", default="")
    parser.add_argument("--archive-id", default="")
    parser.add_argument("--base-url", default="https://www.okx.com")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        credentials = load_windows_keyring_credentials(args.credential_service)
        provider = build_okx_demo_private_read_provider(
            credentials=credentials,
            credential_identity=args.credential_service,
            base_url=args.base_url,
        )
        result = publish_owned_id_restore_archive(
            source_archive_root=args.source_archive,
            output_root=args.output_root,
            repo_root=args.repo_root,
            provider=provider,
            credential_identity=args.credential_service,
            expected_current_head=args.current_head or None,
            archive_id=args.archive_id or None,
        )
    except (OwnedIDRestoreArchiveError, OkxDemoSafetyError) as exc:
        print(
            json.dumps(
                {"status": "blocked", "blocker": type(exc).__name__},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
