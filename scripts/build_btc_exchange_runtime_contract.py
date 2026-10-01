from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.exchange.runtime import (
    BTCExchangeRuntimeSnapshot,
    BTCExchangeRuntimeStatus,
    BTCGapfillState,
    BTCRestStatus,
    BTCStreamStatus,
)


DEFAULT_OUTPUT = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_contract.json")


def build_btc_exchange_runtime_contract_file(
    *,
    output: Path = DEFAULT_OUTPUT,
    generated_at_utc: datetime | None = None,
) -> dict:
    observed_at = generated_at_utc or datetime.now(timezone.utc)
    snapshot = BTCExchangeRuntimeSnapshot(
        venue="simulated_exchange_contract",
        instrument_id="BTCUSDT",
        observed_at_utc=observed_at,
        exchange_status=BTCExchangeRuntimeStatus.OK,
        public_ws_status=BTCStreamStatus.CONNECTED,
        private_ws_status=BTCStreamStatus.CONNECTED,
        rest_status=BTCRestStatus.OK,
        server_time_offset_ms=0,
        rate_limit_budget_remaining=100,
        order_rate_budget_remaining=50,
        last_market_data_time_utc=observed_at - timedelta(seconds=5),
        last_private_event_time_utc=observed_at - timedelta(seconds=5),
        last_reconciliation_time_utc=observed_at - timedelta(seconds=5),
        unreconciled_order_count=0,
        unreconciled_fill_count=0,
        metadata_version="simulated_exchange_contract_v1",
        cancel_only=False,
        private_endpoints_enabled=False,
        order_endpoints_enabled=False,
        public_ws_gapfill=BTCGapfillState(
            stream="public_market_data",
            gap_detected=True,
            recovered=True,
            recovery_method="simulated_rest_gapfill",
            events_backfilled=12,
            bars_rebuilt=3,
            trading_blocked=True,
        ),
        private_ws_gapfill=BTCGapfillState(
            stream="private_order_fill_stream",
            gap_detected=True,
            recovered=True,
            recovery_method="simulated_open_orders_and_fills_reconciliation",
            orders_reconciled=2,
            fills_reconciled=2,
            trading_blocked=True,
        ),
        mode="paper",
        notes={
            "evidence_type": "simulated_contract_probe",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
            "scope": "contract artifact only; not a live exchange adapter authorization",
        },
    )
    payload = snapshot.to_artifact()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_btc_exchange_runtime_contract_file(output=args.output)
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
