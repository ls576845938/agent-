from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.trend_boundary import build_btc_trend_boundary_report


DEFAULT_SOURCE = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json")
DEFAULT_ROLL_SOURCE = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_roll_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_boundary_report.json")


def build_btc_trend_boundary_report_file(
    *,
    source: Path = DEFAULT_SOURCE,
    roll_source: Path = DEFAULT_ROLL_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    source_report = _read_json(source)
    chain = source_report.get("forecast_target_order_chain")
    if not isinstance(chain, dict) or not chain:
        roll_report = _read_json(roll_source)
        roll_chain = roll_report.get("forecast_target_order_chain")
        if isinstance(roll_chain, dict):
            chain = {
                **roll_chain,
                "chain_source_report": str(roll_source).replace("\\", "/"),
                "daily_source_report": str(source).replace("\\", "/"),
                "daily_source_status": source_report.get("status"),
            }
    payload = build_btc_trend_boundary_report(
        source_report=source_report,
        boundary_chain=chain if isinstance(chain, dict) else {},
        generated_at_utc=generated_at,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--roll-source", type=Path, default=DEFAULT_ROLL_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_btc_trend_boundary_report_file(source=args.source, roll_source=args.roll_source, output=args.output)
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
