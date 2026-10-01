from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from quant_crypto.backtest.funding_ledger import FundingFill, FundingRateEvent, calculate_funding_payments
from scripts.build_btc_funding_ledger_report import build_btc_funding_ledger_report


SCHEMA = Path("schemas/btc_funding_ledger_report.schema.json")
REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")


def test_btc_funding_ledger_report_schema_valid(tmp_path: Path) -> None:
    inputs = _external_runtime_inputs(tmp_path)
    payload = build_btc_funding_ledger_report(
        repo_root=tmp_path,
        provider_report_path=inputs["provider"],
        source_run_dir=inputs["run"],
        generated_at="2026-05-19T00:00:00Z",
    )
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


def test_default_funding_report_writes_funding_adjusted_net_ledger_but_not_promotion_evidence(
    tmp_path: Path,
) -> None:
    inputs = _external_runtime_inputs(tmp_path)
    payload = build_btc_funding_ledger_report(
        repo_root=tmp_path,
        provider_report_path=inputs["provider"],
        source_run_dir=inputs["run"],
        generated_at="2026-05-19T00:00:00Z",
    )

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


def _external_runtime_inputs(root: Path) -> dict[str, Path]:
    provider = root / "external" / "provider_report.json"
    provider.parent.mkdir(parents=True)
    provider.write_text(
        json.dumps(
            {
                "source_type": "production",
                "funding_rate_verified": True,
                "funding_info_verified": True,
                "funding_interval_hours": 8,
                "funding_interval_inference_confidence": "high",
                "funding_interval_source": "immutable_external_bundle",
            }
        ),
        encoding="utf-8",
    )
    config = root / "configs" / "data" / "btc_perpetual_sources.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "selected_provider: okx_swap\n"
        "providers:\n"
        "  okx_swap:\n"
        "    enabled: true\n"
        "    root: external/okx_swap\n"
        "    selected_bundle_id: funding-fixture-v1\n",
        encoding="utf-8",
    )
    bundle = (
        root
        / "external"
        / "okx_swap"
        / "bundles"
        / "funding-fixture-v1"
    )
    bundle.mkdir(parents=True)
    (bundle / "funding_rate.csv").write_text(
        "fundingTime,fundingRate,markPrice,source_record_id\n"
        "2026-01-01T08:00:00Z,0.0001,100000,bill-1\n"
        "2026-01-01T16:00:00Z,0.0001,100000,bill-2\n",
        encoding="utf-8",
    )
    (bundle / "funding_info.json").write_text(
        json.dumps({"instrument_id": "BTC-USDT-SWAP", "interval_hours": 8}),
        encoding="utf-8",
    )
    run = root / "external" / "run"
    run.mkdir(parents=True)
    (run / "trade_ledger.csv").write_text(
        "trade_id,side,size,entry_price,exit_price,entry_time,exit_time,net_pnl\n"
        "trade-1,long,0.001,100000,101000,2026-01-01T07:00:00Z,2026-01-01T09:00:00Z,1.0\n",
        encoding="utf-8",
    )
    return {"provider": provider, "run": run}
