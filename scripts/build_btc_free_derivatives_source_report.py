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

from quant_crypto.data.free_derivatives_sources import build_btc_free_derivatives_source_report


DEFAULT_OUTPUT = Path("artifacts/btc_derivatives_sentiment/latest/btc_free_derivatives_source_report.json")


def build_btc_free_derivatives_source_report_file(
    *,
    output: Path = DEFAULT_OUTPUT,
    execute_network: bool = False,
    generated_at_utc: datetime | None = None,
) -> dict:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    payload = build_btc_free_derivatives_source_report(
        generated_at_utc=generated_at,
        execute_network=execute_network,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute-network", action="store_true")
    args = parser.parse_args()
    payload = build_btc_free_derivatives_source_report_file(output=args.output, execute_network=args.execute_network)
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
