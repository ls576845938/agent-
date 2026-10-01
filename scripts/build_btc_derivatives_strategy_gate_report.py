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

from quant_crypto.monitoring.derivatives_strategy_gate import build_btc_derivatives_strategy_gate


DEFAULT_INPUT = Path("artifacts/btc_derivatives_sentiment/latest/btc_derivatives_sentiment_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_derivatives_sentiment/latest/btc_derivatives_strategy_gate_report.json")


def build_btc_derivatives_strategy_gate_report_file(
    *,
    input_path: Path = DEFAULT_INPUT,
    output: Path = DEFAULT_OUTPUT,
    generated_at_utc: datetime | None = None,
) -> dict:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    source = json.loads(input_path.read_text(encoding="utf-8")) if input_path.exists() else {}
    payload = build_btc_derivatives_strategy_gate(
        derivatives_sentiment_report=source,
        generated_at_utc=generated_at,
        source_report_path=input_path,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_btc_derivatives_strategy_gate_report_file(input_path=args.input, output=args.output)
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
