from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from quant_crypto.backtest.funding_ledger import FundingFill, FundingRateEvent, calculate_funding_payments
from scripts.build_btc_funding_ledger_report import build_btc_funding_ledger_report


SCHEMA = Path("schemas/btc_funding_ledger_report.schema.json")
REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")


def test_btc_funding_ledger_report_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_long_pays_and_short_receives_when_funding_positive() -> None:
    funding_time = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    rates = [FundingRateEvent(funding_time=funding_time, funding_rate=0.0001, mark_price=100_000)]

    long_payment = calculate_funding_payments(
        funding_rates=rates,
        fills=[FundingFill(filled_at=datetime(2026, 1, 1, 7, tzinfo=timezone.utc), side="buy", quantity=1, price=99_000)],
    )[0]
    short_payment = calculate_funding_payments(
        funding_rates=rates,
        fills=[FundingFill(filled_at=datetime(2026, 1, 1, 7, tzinfo=timezone.utc), side="sell", quantity=1, price=99_000)],
    )[0]

    assert long_payment.funding_payment == -10.0
    assert short_payment.funding_payment == 10.0


def test_no_position_at_funding_time_has_zero_payment() -> None:
    funding_time = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    payment = calculate_funding_payments(
        funding_rates=[FundingRateEvent(funding_time=funding_time, funding_rate=0.0001, mark_price=100_000)],
        fills=[FundingFill(filled_at=datetime(2026, 1, 1, 9, tzinfo=timezone.utc), side="buy", quantity=1, price=99_000)],
    )[0]

    assert payment.position_qty == 0.0
    assert payment.funding_payment == 0.0


def test_default_funding_report_writes_funding_adjusted_net_ledger_but_not_promotion_evidence() -> None:
    payload = build_btc_funding_ledger_report(generated_at="2026-05-19T00:00:00Z")

    assert payload["funding_rate_available"] is True
    assert payload["funding_payment_in_ledger"] is True
    assert payload["funding_merged_into_net_ledger"] is True
    assert payload["funding_adjusted_trade_count"] > 0
    assert round(payload["funding_adjusted_net_pnl_total"], 9) == round(
        payload["trade_ledger_net_pnl_total"] + payload["funding_pnl_total"],
        9,
    )
    assert payload["expected_funding_adjusted_net_pnl_total"] == round(
        payload["trade_ledger_net_pnl_total"] + payload["funding_pnl_total"],
        12,
    )
    assert payload["funding_adjusted_net_pnl_reconciliation_delta"] == 0.0
    assert payload["funding_adjusted_net_pnl_reconciled"] is True
    assert payload["promotion_evidence"] is False
    assert payload["blockers"] == []


def test_default_funding_report_generated_at_defaults_to_utc_z() -> None:
    payload = build_btc_funding_ledger_report()

    assert payload["generated_at"].endswith("Z")
    assert "+00:00" not in payload["generated_at"]
