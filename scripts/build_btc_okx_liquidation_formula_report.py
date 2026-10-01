#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_okx_liquidation_formula import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    build_btc_okx_liquidation_formula_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC OKX liquidation formula/tier evidence from public sources.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at_utc) if args.generated_at_utc else None
    report = build_btc_okx_liquidation_formula_report(
        repo_root=args.repo_root,
        output_root=args.output_root,
        execute_network=args.execute_network,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "liquidation_formula_verified": report["liquidation_formula_verified"],
                "maintenance_margin_tiers_verified": report["maintenance_margin_tiers_verified"],
                "exact_exchange_liquidation_formula_verified": report["exact_exchange_liquidation_formula_verified"],
                "blockers": report["blockers"],
                "output": str(args.output_root / "btc_okx_liquidation_formula_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
