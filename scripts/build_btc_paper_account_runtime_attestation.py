from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_paper_account_runtime_attestation import (  # noqa: E402
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_DIR,
    build_btc_paper_account_runtime_attestation_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC paper account runtime manual attestation report.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at-utc", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated = _parse_utc(args.generated_at_utc) if args.generated_at_utc else None
    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=args.repo_root,
        input_path=args.input,
        output_dir=args.output_dir,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "account_mode_verified": report["account_mode_verified"],
                "position_mode_verified": report["position_mode_verified"],
                "margin_mode_verified": report["margin_mode_verified"],
                "rate_limit_budget_verified": report["rate_limit_budget_verified"],
                "credential_permissions_verified": report["credential_permissions_verified"],
                "credential_separation_verified": report["credential_separation_verified"],
                "manual_approval_recorded": report["manual_approval_recorded"],
                "attestation_current": report["attestation_current"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "verified_research_only" else 1


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
