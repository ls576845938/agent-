#!/usr/bin/env python3
"""Read-only preflight for the 30-day paper-validation evidence contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.reports.paper_validation import check_paper_validation_preflight


def _parse_symbols(raw: str) -> list[str]:
    return [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only preflight for the paper-validation evidence contract. "
            "This command never starts paper/live trading and never enables submit."
        )
    )
    parser.add_argument("--data-root", default="data", help="Data root directory (default: data)")
    parser.add_argument("--ledger-root", default="", help="Override paper ledger root")
    parser.add_argument("--validation-state", default="", help="Override validation_state.json path")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol override")
    parser.add_argument("--source", default="yfinance", help="Market data vendor (default: yfinance)")
    parser.add_argument("--bar-size", default="1d", help="Bar size (default: 1d)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    args = parser.parse_args()

    preflight = check_paper_validation_preflight(
        args.data_root,
        ledger_root=args.ledger_root or None,
        validation_state_path=args.validation_state or None,
        symbols=_parse_symbols(args.symbols),
        source=args.source,
        bar_size=args.bar_size,
    )

    if args.json:
        print(json.dumps(preflight.to_dict(), indent=2, ensure_ascii=False))
    else:
        print("Paper Validation Preflight")
        print("=" * 60)
        print("  scope:       report only, no execution")
        print("  note:        read-only/no-submit evidence check; no broker writes")
        print(f"  status:      {preflight.status}")
        print(f"  data_root:   {preflight.data_root}")
        print(f"  ledger_root: {preflight.ledger_root}")
        print(f"  state_path:  {preflight.validation_state_path}")
        print(f"  symbols:     {', '.join(preflight.symbols) if preflight.symbols else '(unresolved)'}")
        print(f"  data_spec:   source={preflight.source} bar_size={preflight.bar_size}")
        print("  checks:")
        for check in preflight.checks:
            print(f"    [{check.status}] {check.name}")
            print(f"         {check.detail}")
            if check.artifact_path:
                print(f"         path={check.artifact_path}")
        if preflight.blocking_reasons:
            print(f"  blocking_reasons: {', '.join(preflight.blocking_reasons)}")
        else:
            print("  blocking_reasons: (none)")
        print("=" * 60)

    sys.exit(0 if preflight.status == "PASS" else 1)


if __name__ == "__main__":
    main()
