from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_cost_model_report import build_btc_cost_model_report
from scripts.import_btc_fee_tier_overlay import import_btc_fee_tier_overlay, write_fee_tier_overlay_import_report


SCHEMA = Path("schemas/btc_cost_model_contract.schema.json")
REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
FEE_SOURCE_URL = "https://www.okx.com/en-us/fees"


def _valid_fee_tier_overlay() -> dict[str, object]:
    return {
        "schema_version": "btc_fee_tier_overlay_v1",
        "symbol": "BTCUSDT",
        "market_type": "usds_m_perpetual",
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 5.0,
        "source": "manual_public_okx_swap_fee_schedule",
        "source_url_or_doc": FEE_SOURCE_URL,
        "captured_at": "2026-05-22T00:00:00Z",
        "api_key_used": False,
        "private_endpoint_used": False,
        "auth_headers_used": False,
    }


def test_btc_cost_model_report_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_cost_model_fails_only_on_missing_fee_tier_when_provider_evidence_is_verified(tmp_path: Path) -> None:
    payload = build_btc_cost_model_report(
        fee_tier_overlay_path=tmp_path / "missing_fee_tier_overlay.json",
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["status"] == "fail"
    assert payload["funding_model"]["funding_rate_available"] is True
    assert payload["funding_model"]["funding_info_available"] is True
    assert payload["funding_model"]["funding_interval_hours"] == 8.0
    assert payload["funding_model"]["funding_interval_source"] == "funding_info_endpoint"
    assert payload["funding_model"]["funding_interval_inference_confidence"] == "high"
    assert payload["funding_model"]["funding_payment_in_ledger"] is True
    assert payload["fee_model"]["fee_in_ledger"] is True
    assert payload["fee_model"]["fee_tier_verified"] is False
    assert payload["fee_model"]["maker_fee_bps"] is None
    assert payload["fee_model"]["taker_fee_bps"] == 4.0
    assert "btc_maker_taker_fee_tier_missing" in payload["fee_model"]["fee_blockers"]
    assert "btc_maker_taker_fee_tier_missing" in payload["blockers"]
    assert payload["slippage_model"]["slippage_bps"] == 4.0
    assert payload["slippage_model"]["slippage_in_ledger"] is True
    assert payload["mark_price_model"]["mark_price_available"] is True
    assert payload["mark_price_model"]["premium_index_available"] is True
    assert payload["exchange_rules"]["exchange_info_available"] is True
    assert "btc_funding_info_not_verified_for_promotion_evidence" not in payload["blockers"]
    assert "btc_exchange_info_missing" not in payload["blockers"]


def test_liquidation_snapshot_not_complete_liquidation_evidence() -> None:
    payload = build_btc_cost_model_report(generated_at="2026-05-19T00:00:00Z")

    assert payload["liquidation_data"]["liquidation_snapshot_available"] is False
    assert payload["liquidation_data"]["complete_liquidation_history_available"] is False
    assert payload["candidate_pass_allowed"] is False


def test_verified_fee_tier_overlay_clears_fee_tier_blocker_only(tmp_path: Path) -> None:
    overlay, report, import_result = _write_imported_fee_tier_overlay(tmp_path)

    payload = build_btc_cost_model_report(
        fee_tier_overlay_path=overlay,
        fee_tier_import_report_path=report,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["status"] == "pass"
    assert payload["fee_model"]["fee_tier_verified"] is True
    assert payload["fee_model"]["fee_tier_import_report_verified"] is True
    assert payload["fee_model"]["fee_tier_overlay_sha256"] == import_result["overlay_payload_sha256"]
    assert payload["fee_model"]["maker_fee_bps"] == 2.0
    assert payload["fee_model"]["taker_fee_bps"] == 5.0
    assert payload["fee_model"]["fee_source"] == "manual_public_okx_swap_fee_schedule"
    assert payload["fee_model"]["fee_tier_source_url_or_doc"] == FEE_SOURCE_URL
    assert payload["fee_model"]["fee_blockers"] == []
    assert "btc_maker_taker_fee_tier_missing" not in payload["blockers"]
    assert payload["blockers"] == []
    assert payload["candidate_pass_allowed"] is False


def test_diagnostic_open_interest_gap_does_not_fail_cost_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts/btc_candidate_validation/pass_cost"
    _write_cost_source_run(run_dir)
    _write_cost_evidence_without_open_interest(tmp_path)
    overlay, report, _ = _write_imported_fee_tier_overlay(tmp_path)

    payload = build_btc_cost_model_report(
        repo_root=tmp_path,
        source_run_dir=run_dir,
        fee_tier_overlay_path=overlay,
        fee_tier_import_report_path=report,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["status"] == "pass"
    assert payload["blockers"] == []
    assert "btc_open_interest_history_not_verified_diagnostic_partial" in payload["diagnostic_warnings"]


def test_fee_tier_overlay_requires_matching_write_import_report(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"
    overlay.write_text(json.dumps(_valid_fee_tier_overlay()), encoding="utf-8")

    payload = build_btc_cost_model_report(
        fee_tier_overlay_path=overlay,
        fee_tier_import_report_path=tmp_path / "missing_import_report.json",
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["fee_model"]["fee_tier_verified"] is False
    assert payload["fee_model"]["fee_tier_import_report_verified"] is False
    assert "btc_fee_tier_overlay_import_report_missing" in payload["fee_model"]["fee_blockers"]
    assert "btc_fee_tier_overlay_import_report_missing" in payload["blockers"]


def test_fee_tier_overlay_rejects_import_report_hash_mismatch(tmp_path: Path) -> None:
    overlay, report, _ = _write_imported_fee_tier_overlay(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["overlay_payload_sha256"] = "0" * 64
    report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    cost_report = build_btc_cost_model_report(
        fee_tier_overlay_path=overlay,
        fee_tier_import_report_path=report,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert cost_report["fee_model"]["fee_tier_verified"] is False
    assert "btc_fee_tier_overlay_import_report_hash_mismatch" in cost_report["fee_model"]["fee_blockers"]


def test_fee_tier_overlay_requires_source_url_or_doc(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"
    payload = _valid_fee_tier_overlay()
    payload.pop("source_url_or_doc")
    overlay.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_cost_model_report(
        fee_tier_overlay_path=overlay,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["fee_model"]["fee_tier_verified"] is False
    assert report["fee_model"]["maker_fee_bps"] is None
    assert report["fee_model"]["fee_tier_source_url_or_doc"] is None
    assert "btc_fee_tier_overlay_schema_invalid" in report["fee_model"]["fee_blockers"]
    assert "btc_fee_tier_source_url_or_doc_missing" in report["fee_model"]["fee_blockers"]
    assert "btc_fee_tier_source_url_or_doc_missing" in report["blockers"]


def test_fee_tier_overlay_requires_zulu_utc_capture_time(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"
    payload = _valid_fee_tier_overlay()
    payload["captured_at"] = "2026-05-22T00:00:00+00:00"
    overlay.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_cost_model_report(
        fee_tier_overlay_path=overlay,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["fee_model"]["fee_tier_verified"] is False
    assert "btc_fee_tier_overlay_schema_invalid" in report["fee_model"]["fee_blockers"]
    assert "btc_fee_tier_captured_at_not_utc" in report["fee_model"]["fee_blockers"]
    assert "btc_fee_tier_captured_at_not_utc" in report["blockers"]


def _write_imported_fee_tier_overlay(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    overlay = tmp_path / "btc_fee_tier_overlay.json"
    report = tmp_path / "btc_fee_tier_overlay_import_report.json"
    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="5.0",
        source="manual_public_okx_swap_fee_schedule",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-22T00:00:00Z",
        overlay_output=overlay,
        dry_run=False,
        generated_at="2026-05-23T00:00:00Z",
    )
    write_fee_tier_overlay_import_report(result, report)
    return overlay, report, result


def _write_cost_source_run(run_dir: Path) -> None:
    _write_json(
        run_dir / "canonical_backtest_report.json",
        {"metrics": {"fill_count": 12}},
    )
    _write_json(
        run_dir / "manifests/run_btc_compression_expansion_breakout_v1_base.json",
        {
            "config": {"commission_rate": 0.0004, "slippage_bps": 4.0},
            "cost_model": {
                "commission_rate": 0.0004,
                "realized_commission": 10.0,
                "realized_slippage_cost": 2.0,
                "slippage_bps": 4.0,
            },
        },
    )


def _write_cost_evidence_without_open_interest(root: Path) -> None:
    for schema_name in ("btc_fee_tier_overlay.schema.json", "btc_fee_tier_overlay_import_report.schema.json"):
        _write_json(root / "schemas" / schema_name, json.loads((Path("schemas") / schema_name).read_text(encoding="utf-8")))
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "funding_rate_verified": True,
            "funding_info_verified": True,
            "funding_interval_inference_confidence": "high",
            "mark_price_klines_verified": True,
            "premium_index_klines_verified": True,
            "exchange_info_verified": True,
            "open_interest_verified": False,
            "diagnostic_warnings": ["btc_open_interest_history_not_verified_diagnostic_partial"],
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json",
        {"funding_payment_in_ledger": True, "funding_interval_hours": 8.0, "funding_interval_source": "endpoint", "blockers": []},
    )
    _write_json(
        root / "configs/data/btc_perpetual_sources.yaml",
        {
            "providers": {
                "binance_usdm": {
                    "root": "data/external/btc_perpetual/binance_usdm/",
                    "selected_bundle_id": "prod1",
                }
            }
        },
    )
    _write_json(
        root / "data/external/btc_perpetual/binance_usdm/bundles/prod1/exchange_info.json",
        {
            "source_method": "manual_offline_capture",
            "source_url_or_doc": "offline capture from /fapi/v1/exchangeInfo",
            "captured_at": "2026-01-01T00:00:00Z",
            "symbol": "BTCUSDT",
            "raw_symbol_info": {
                "symbol": "BTCUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "pricePrecision": 2,
                "quantityPrecision": 3,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "100"},
                ],
            },
            "api_key_used": False,
            "private_endpoint_used": False,
            "auth_headers_present": False,
            "operator_note": "manual public exchangeInfo capture",
            "blockers": [],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
