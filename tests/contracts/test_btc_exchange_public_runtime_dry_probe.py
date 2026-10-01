from __future__ import annotations

import json
import time as pytime
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.research.btc_exchange_public_runtime_dry_probe import (
    build_btc_exchange_public_runtime_dry_probe,
)


TS = datetime(2026, 7, 6, tzinfo=timezone.utc)


def test_public_runtime_dry_probe_verifies_public_rest_and_ws_without_order_endpoints(tmp_path: Path) -> None:
    coverage = _write_json(tmp_path / "coverage.json", _coverage_report())

    report = build_btc_exchange_public_runtime_dry_probe(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        public_ws_coverage_path=coverage,
        execute_network=True,
        generated_at_utc=TS,
        collector_factory=FakeOkxPublicCollector,
    )

    assert report["schema_version"] == "btc_exchange_public_runtime_dry_probe_v2"
    assert report["status"] == "verified_research_only"
    assert report["runtime_layer"]["status"] == "passed"
    assert report["runtime_layer"]["server_time_verified"] is True
    assert report["runtime_layer"]["symbol_rules_visible"] is True
    assert report["runtime_layer"]["normalized_market_metadata_visible"] is True
    assert report["runtime_layer"]["tick_size_visible"] is True
    assert report["runtime_layer"]["lot_size_visible"] is True
    assert report["runtime_layer"]["min_size_visible"] is True
    assert report["runtime_layer"]["contract_value_visible"] is True
    assert report["normalized_market_metadata_contract"]["contract_valid"] is True
    assert report["normalized_market_metadata_contract"]["instrument_id"] == "BTC-USDT-SWAP"
    assert report["normalized_market_metadata_contract"]["tick_size"] == 0.1
    assert report["normalized_market_metadata_contract"]["lot_size"] == 0.01
    assert report["normalized_market_metadata_contract"]["min_order_size"] == 0.01
    assert report["third_party_reference_adaptation"]["ccxt"]["license"] == "MIT"
    assert report["third_party_reference_adaptation"]["hummingbot"]["license"] == "Apache-2.0"
    assert report["third_party_reference_adaptation"]["ccxt"]["copy_allowed_after_provenance_review"] is True
    assert report["third_party_reference_adaptation"]["hummingbot"]["copy_allowed_after_provenance_review"] is True
    assert report["third_party_reference_adaptation"]["ccxt"]["source_code_copied"] is False
    assert report["third_party_reference_adaptation"]["hummingbot"]["source_code_copied"] is False
    assert report["third_party_reference_adaptation"]["ccxt"]["copied_source_paths"] == []
    assert report["third_party_reference_adaptation"]["hummingbot"]["copied_source_paths"] == []
    assert "instId" in report["third_party_reference_adaptation"]["ccxt"]["adapted_public_fields"]
    assert "public_rest_only" in report["third_party_reference_adaptation"]["hummingbot"]["adapted_public_fields"]
    assert "do_not_copy_large_exchange_parser" in report["third_party_reference_adaptation"]["ccxt"]["source_copy_decision"]
    assert report["third_party_reference_adaptation"]["private_or_order_endpoint_imported"] is False
    assert report["runtime_layer"]["mark_price_available"] is True
    assert report["runtime_layer"]["index_price_available"] is True
    assert report["runtime_layer"]["funding_available"] is True
    assert report["runtime_layer"]["public_depth_available"] is True
    assert report["runtime_layer"]["open_interest_available"] is True
    assert report["runtime_layer"]["public_ws_replay_verified"] is True
    assert report["runtime_layer"]["paper_gate_eligible"] is False
    assert report["private_endpoint_used"] is False
    assert report["order_endpoint_used"] is False
    assert report["real_order_submitted"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False

    safety = json.loads((tmp_path / "out" / "btc_exchange_public_runtime_dry_probe_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False


def test_public_runtime_dry_probe_fails_closed_when_network_not_executed(tmp_path: Path) -> None:
    coverage = _write_json(tmp_path / "coverage.json", _coverage_report())

    report = build_btc_exchange_public_runtime_dry_probe(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        public_ws_coverage_path=coverage,
        execute_network=False,
        generated_at_utc=TS,
        collector_factory=FakeOkxPublicCollector,
    )

    assert report["status"] == "incomplete_research_only"
    assert "btc_public_runtime_dry_probe_capture_error:public_runtime_dry_probe:network_not_executed" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


class FakeOkxPublicCollector:
    def __init__(self, *, dry_run: bool = True, allow_network: bool = False, **_: Any) -> None:
        self.dry_run = dry_run
        self.allow_network = allow_network

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        endpoint = f"/fake/{name}"
        url = "https://www.okx.com" + endpoint
        if self.dry_run or not self.allow_network:
            return {
                "dry_run": True,
                "network_called": False,
                "endpoint": endpoint,
                "params": dict(params or {}),
                "url": url,
            }
        payload = {"code": "0", "msg": "", "data": [{"ok": True}]}
        if name == "server_time":
            payload = {"code": "0", "msg": "", "data": [{"ts": str(int(pytime.time() * 1000))}]}
        if name == "instruments":
            payload = {
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "instType": "SWAP",
                        "baseCcy": "BTC",
                        "quoteCcy": "USDT",
                        "settleCcy": "USDT",
                        "ctType": "linear",
                        "ctVal": "0.01",
                        "ctValCcy": "BTC",
                        "ctMult": "1",
                        "tickSz": "0.1",
                        "lotSz": "0.01",
                        "minSz": "0.01",
                        "maxLmtSz": "1000000",
                        "maxMktSz": "100000",
                        "state": "live",
                    }
                ],
            }
        return {
            "dry_run": False,
            "network_called": True,
            "endpoint": endpoint,
            "params": dict(params or {}),
            "url": url,
            "duration_ms": 12.0,
            "payload": payload,
        }


def _coverage_report() -> dict[str, Any]:
    return {
        "status": "complete_research_only",
        "coverage_contract_satisfied": False,
        "coverage_totals": {"verified_public_session_count": 2},
        "validation": {
            "all_verified_sessions_have_replay_sequence_ready": True,
            "resync_policy_exercised": True,
            "required_channels_observed": True,
            "minimum_event_ledger_history_days_satisfied": False,
            "minimum_calendar_span_days_satisfied": False,
        },
        "guardrails": {
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
