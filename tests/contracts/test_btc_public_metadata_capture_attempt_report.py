from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import jsonschema
import pytest

from scripts.build_btc_public_metadata_capture_attempt_report import (
    build_btc_public_metadata_capture_attempt_report,
)


SCHEMA = Path("schemas/btc_public_metadata_capture_attempt_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json")


def test_btc_public_metadata_capture_attempt_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_public_metadata_capture_attempt_dry_run_is_fail_closed() -> None:
    payload = build_btc_public_metadata_capture_attempt_report(
        execute_network=False,
        generated_at="2026-05-22T00:00:00Z",
    )

    assert payload["status"] == "capture_incomplete"
    assert payload["network_called"] is False
    assert payload["allowed_endpoints"]["exchange_info"] == "GET /fapi/v1/exchangeInfo"
    assert payload["allowed_endpoints"]["funding_info"] == "GET /fapi/v1/fundingInfo"
    assert payload["safety"]["api_key_required"] is False
    assert payload["safety"]["private_endpoints_allowed"] is False
    assert payload["safety"]["order_endpoints_allowed"] is False
    assert payload["safety"]["writes_bundle_files"] is False
    assert payload["raw_capture_artifacts"]["enabled"] is False
    assert payload["raw_capture_artifacts"]["writes_performed"] is False
    assert payload["endpoint_results"]["exchange_info"]["capture_status"] == "not_executed"
    assert payload["endpoint_results"]["funding_info"]["capture_status"] == "not_executed"
    assert "btc_public_metadata_capture_not_executed" in payload["blockers"]


def test_btc_public_metadata_capture_attempt_schema_rejects_non_utc_generated_at() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["generated_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_public_metadata_capture_attempt_records_http_451() -> None:
    def fake_request(name: str, _params: object) -> object:
        raise HTTPError(
            url=f"https://fapi.binance.com/{name}",
            code=451,
            msg="restricted location",
            hdrs={},
            fp=_Body(b'{"msg":"restricted location"}'),
        )

    payload = build_btc_public_metadata_capture_attempt_report(
        execute_network=True,
        generated_at="2026-05-22T00:00:00Z",
        request_fn=fake_request,
    )

    assert payload["status"] == "capture_incomplete"
    assert payload["network_called"] is True
    assert payload["endpoint_results"]["exchange_info"]["http_status"] == 451
    assert payload["endpoint_results"]["funding_info"]["http_status"] == 451
    assert "btc_binance_public_rest_http_451_geoblocked" in payload["blockers"]
    assert "btc_public_metadata_exchange_info_capture_failed" in payload["blockers"]
    assert "btc_public_metadata_funding_info_capture_failed" in payload["blockers"]
    assert payload["next_required_action"] == "manual_capture_from_allowed_network"
    assert payload["raw_capture_artifacts"]["writes_performed"] is False


def test_btc_public_metadata_capture_attempt_complete_when_both_payloads_exist() -> None:
    def fake_request(name: str, _params: object) -> dict[str, object]:
        payload = [] if name == "funding_info" else {"symbols": [{"symbol": "BTCUSDT"}]}
        return {
            "network_called": True,
            "url": f"https://fapi.binance.com/{name}",
            "payload": payload,
        }

    payload = build_btc_public_metadata_capture_attempt_report(
        execute_network=True,
        generated_at="2026-05-22T00:00:00Z",
        request_fn=fake_request,
    )

    assert payload["status"] == "capture_complete"
    assert payload["next_required_action"] == "wrap_and_validate_metadata"
    assert payload["blockers"] == []
    assert payload["raw_capture_artifacts"]["enabled"] is False


def test_btc_public_metadata_capture_attempt_can_stage_raw_import_inputs(tmp_path: Path) -> None:
    def fake_request(name: str, _params: object) -> dict[str, object]:
        payload = [] if name == "funding_info" else {"symbols": [{"symbol": "BTCUSDT"}]}
        return {
            "network_called": True,
            "url": f"https://fapi.binance.com/{name}",
            "payload": payload,
        }

    payload = build_btc_public_metadata_capture_attempt_report(
        execute_network=True,
        generated_at="2026-05-22T00:00:00Z",
        request_fn=fake_request,
        raw_capture_root=tmp_path / "raw_capture",
    )
    artifacts = payload["raw_capture_artifacts"]

    assert payload["status"] == "capture_complete"
    assert payload["next_required_action"] == "run_manual_metadata_import"
    assert payload["blockers"] == []
    assert artifacts["enabled"] is True
    assert artifacts["writes_performed"] is True
    assert Path(artifacts["exchange_info_raw"]).exists()
    assert Path(artifacts["exchange_info_http_status"]).read_text(encoding="utf-8").strip() == "200"
    assert Path(artifacts["funding_info_raw"]).exists()
    assert Path(artifacts["funding_info_http_status"]).read_text(encoding="utf-8").strip() == "200"
    assert "make dry-run-btc-manual-metadata-import" in artifacts["dry_run_import_command"]
    assert "make apply-btc-manual-metadata-import" in artifacts["apply_import_command"]
    assert payload["safety"]["writes_bundle_files"] is False


class _Body:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        return None
