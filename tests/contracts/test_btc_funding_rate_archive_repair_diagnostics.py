from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.repair_btc_funding_rate_coverage import _write_archive_repair_report


SCHEMA = Path("schemas/btc_funding_rate_archive_repair_report.schema.json")


def test_archive_repair_report_classifies_404_without_fabricating_rows(tmp_path: Path) -> None:
    audit = {
        "generated_at": "2026-05-19T00:00:00Z",
        "bundle_id": "btc_usdm_binance_btcusdt_20240101_20260512_v1",
        "repair_mode": "binance_vision_public_archive",
        "records_added": 0,
        "repair_success": False,
        "attempted_sources": [
            {
                "mode": "daily",
                "url": "https://data.binance.vision/data/futures/um/daily/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-05-01.zip",
                "status_code": 404,
                "role": "funding_rate",
                "date_or_month": "2026-05-01",
                "rows": 0,
                "error_type": "not_found",
            }
        ],
        "blockers": ["btc_funding_rate_no_archive_rows_added"],
    }

    output = Path(_write_archive_repair_report(audit, tmp_path))
    payload = json.loads(output.read_text(encoding="utf-8"))

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert payload["rows_added"] == 0
    assert payload["repair_success"] is False
    assert payload["attempted_sources"][0]["error_type"] == "not_found"


def test_archive_repair_report_preserves_http_451_as_network_boundary(tmp_path: Path) -> None:
    audit = {
        "generated_at": "2026-05-19T00:00:00Z",
        "bundle_id": "btc_usdm_binance_btcusdt_20240101_20260512_v1",
        "repair_mode": "binance_vision_public_archive",
        "records_added": 0,
        "repair_success": False,
        "attempted_sources": [
            {
                "mode": "monthly",
                "url": "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-05.zip",
                "status_code": 451,
                "role": "funding_rate",
                "date_or_month": "2026-05",
                "rows": 0,
                "error_type": "http_451",
            }
        ],
        "blockers": ["btc_funding_rate_archive_repair_errors"],
    }

    output = Path(_write_archive_repair_report(audit, tmp_path))
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["attempted_sources"][0]["status_code"] == 451
    assert payload["attempted_sources"][0]["error_type"] == "http_451"
