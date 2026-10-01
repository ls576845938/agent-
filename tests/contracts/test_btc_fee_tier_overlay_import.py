from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_cost_model_report import build_btc_cost_model_report
from scripts.import_btc_fee_tier_overlay import (
    import_btc_fee_tier_overlay,
    write_fee_tier_overlay_import_report,
)


REPORT_SCHEMA = Path("schemas/btc_fee_tier_overlay_import_report.schema.json")
OVERLAY_SCHEMA = Path("schemas/btc_fee_tier_overlay.schema.json")
FEE_SOURCE_URL = "https://www.binance.com/en/fee/futureFee"


def test_fee_tier_overlay_import_dry_run_verifies_without_writing(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"

    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="manual_public_binance_usdm_fee_schedule",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-22T00:00:00Z",
        overlay_output=overlay,
        dry_run=True,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert result["status"] == "verified"
    assert result["writes_performed"] is False
    assert result["fee_tier_verified"] is True
    assert isinstance(result["overlay_payload_sha256"], str)
    assert len(result["overlay_payload_sha256"]) == 64
    assert result["overlay_output"] == str(overlay)
    assert result["blockers"] == []
    assert not overlay.exists()
    _assert_report_schema_valid(result)


def test_fee_tier_overlay_import_apply_writes_schema_valid_overlay_and_cost_model_consumes_it(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"
    report = tmp_path / "btc_fee_tier_overlay_import_report.json"

    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="manual_public_binance_usdm_fee_schedule",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-22T00:00:00Z",
        overlay_output=overlay,
        dry_run=False,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert result["status"] == "verified"
    assert result["writes_performed"] is True
    _assert_report_schema_valid(result)
    write_fee_tier_overlay_import_report(result, report)
    overlay_payload = json.loads(overlay.read_text(encoding="utf-8"))
    jsonschema.validate(overlay_payload, json.loads(OVERLAY_SCHEMA.read_text(encoding="utf-8")))

    cost_report = build_btc_cost_model_report(
        fee_tier_overlay_path=overlay,
        fee_tier_import_report_path=report,
        generated_at="2026-05-23T00:00:00Z",
    )
    assert cost_report["fee_model"]["fee_tier_verified"] is True
    assert cost_report["fee_model"]["fee_tier_import_report_verified"] is True
    assert cost_report["fee_model"]["fee_tier_overlay_sha256"] == result["overlay_payload_sha256"]
    assert cost_report["fee_model"]["maker_fee_bps"] == 2.0
    assert cost_report["fee_model"]["taker_fee_bps"] == 4.0
    assert cost_report["fee_model"]["fee_tier_source_url_or_doc"] == FEE_SOURCE_URL
    assert "btc_maker_taker_fee_tier_missing" not in cost_report["blockers"]
    assert "btc_exchange_info_missing" not in cost_report["blockers"]


def test_fee_tier_overlay_import_report_writer(tmp_path: Path) -> None:
    report = tmp_path / "btc_fee_tier_overlay_import_report.json"
    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="manual_public_binance_usdm_fee_schedule",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-22T00:00:00Z",
        overlay_output=tmp_path / "btc_fee_tier_overlay.json",
        dry_run=True,
        generated_at="2026-05-23T00:00:00Z",
    )

    write_fee_tier_overlay_import_report(result, report)

    assert report.exists()
    _assert_report_schema_valid(json.loads(report.read_text(encoding="utf-8")))


def test_fee_tier_overlay_import_rejects_missing_source_url_without_writing(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"

    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="manual_public_binance_usdm_fee_schedule",
        source_url_or_doc="   ",
        captured_at="2026-05-22T00:00:00Z",
        overlay_output=overlay,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_fee_tier_source_url_or_doc_missing" in result["blockers"]
    assert "btc_fee_tier_overlay_schema_invalid" in result["blockers"]
    assert result["overlay_payload_sha256"] is not None
    assert not overlay.exists()
    _assert_report_schema_valid(result)


def test_fee_tier_overlay_import_rejects_noncanonical_source_without_writing(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"

    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="operator_note_from_fee_page",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-22T00:00:00Z",
        overlay_output=overlay,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_fee_tier_source_not_canonical" in result["blockers"]
    assert "btc_fee_tier_overlay_schema_invalid" in result["blockers"]
    assert not overlay.exists()
    _assert_report_schema_valid(result)


def test_fee_tier_overlay_import_rejects_non_zulu_utc_capture_time(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"

    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="manual_public_binance_usdm_fee_schedule",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-22T00:00:00+00:00",
        overlay_output=overlay,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_fee_tier_captured_at_not_utc" in result["blockers"]
    assert "btc_fee_tier_overlay_schema_invalid" in result["blockers"]
    assert not overlay.exists()
    _assert_report_schema_valid(result)


def test_fee_tier_overlay_import_rejects_future_capture_time(tmp_path: Path) -> None:
    overlay = tmp_path / "btc_fee_tier_overlay.json"

    result = import_btc_fee_tier_overlay(
        maker_fee_bps="2.0",
        taker_fee_bps="4.0",
        source="manual_public_binance_usdm_fee_schedule",
        source_url_or_doc=FEE_SOURCE_URL,
        captured_at="2026-05-24T00:00:00Z",
        overlay_output=overlay,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_fee_tier_captured_at_in_future" in result["blockers"]
    assert not overlay.exists()
    _assert_report_schema_valid(result)


def test_fee_tier_overlay_import_make_targets_are_parameterized_and_fail_closed() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "BTC_FEE_TIER_IMPORT_REPORT ?= artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json" in makefile
    assert "BTC_FEE_TIER_DRY_RUN_REPORT ?= artifacts/btc_cost_model/latest/btc_fee_tier_overlay_dry_run_report.json" in makefile
    assert "BTC_FEE_TIER_OVERLAY ?= artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json" in makefile
    assert "BTC_FEE_TIER_CAPTURED_AT ?=" in makefile
    assert "BTC_FEE_TIER_MAKER_BPS ?=" in makefile
    assert "BTC_FEE_TIER_TAKER_BPS ?=" in makefile
    assert "dry-run-btc-fee-tier-overlay-import" in makefile
    assert "apply-btc-fee-tier-overlay-import" in makefile
    assert 'test -n "$(BTC_FEE_TIER_MAKER_BPS)"' in makefile
    assert 'test -n "$(BTC_FEE_TIER_TAKER_BPS)"' in makefile
    assert 'test -n "$(BTC_FEE_TIER_CAPTURED_AT)"' in makefile
    assert '--maker-fee-bps "$(BTC_FEE_TIER_MAKER_BPS)"' in makefile
    assert '--taker-fee-bps "$(BTC_FEE_TIER_TAKER_BPS)"' in makefile
    assert '--source-url-or-doc "$(BTC_FEE_TIER_SOURCE_URL_OR_DOC)"' in makefile
    assert '--overlay-output "$(BTC_FEE_TIER_OVERLAY)"' in makefile
    assert '--report-output "$(BTC_FEE_TIER_DRY_RUN_REPORT)"' in _target_body(
        makefile, "dry-run-btc-fee-tier-overlay-import"
    )
    assert '--report-output "$(BTC_FEE_TIER_IMPORT_REPORT)"' in _target_body(
        makefile, "apply-btc-fee-tier-overlay-import"
    )
    assert "--dry-run" in _target_body(makefile, "dry-run-btc-fee-tier-overlay-import")
    assert "--dry-run" not in _target_body(makefile, "apply-btc-fee-tier-overlay-import")
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" in _target_body(
        makefile, "apply-btc-fee-tier-overlay-import"
    )
    assert "$(MAKE) validate-btc-evidence" in _target_body(makefile, "apply-btc-fee-tier-overlay-import")
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" not in _target_body(
        makefile, "dry-run-btc-fee-tier-overlay-import"
    )


def _assert_report_schema_valid(payload: dict[str, object]) -> None:
    jsonschema.validate(payload, json.loads(REPORT_SCHEMA.read_text(encoding="utf-8")))


def _target_body(makefile: str, target: str) -> str:
    marker = f"\n{target}:"
    start = makefile.index(marker)
    rest = makefile[start + 1 :]
    next_target = rest.find("\n\n")
    return rest if next_target == -1 else rest[:next_target]
