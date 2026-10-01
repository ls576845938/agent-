from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.research.btc_okx_liquidation_formula import (
    SCHEMA_VERSION,
    build_btc_okx_liquidation_formula_report,
)


def test_okx_liquidation_formula_report_dry_run_is_fail_closed(tmp_path: Path) -> None:
    report = build_btc_okx_liquidation_formula_report(
        repo_root=tmp_path,
        output_root=tmp_path / "out",
        execute_network=False,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        collector_factory=_FakeOkxCollector,
    )

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["status"] == "dry_run"
    assert report["public_rest_only"] is True
    assert report["api_key_used"] is False
    assert report["private_endpoint_used"] is False
    assert report["order_endpoint_used"] is False
    assert report["exact_exchange_liquidation_formula_verified"] is False
    assert "btc_okx_position_tiers_network_capture_not_executed" in report["blockers"]
    assert (tmp_path / "out" / "btc_okx_liquidation_formula_report.json").exists()
    assert (tmp_path / "out" / "btc_okx_liquidation_formula_summary_cn.md").exists()


def test_okx_liquidation_formula_report_verifies_public_tiers_and_formula(tmp_path: Path) -> None:
    report = build_btc_okx_liquidation_formula_report(
        repo_root=tmp_path,
        output_root=tmp_path / "out",
        execute_network=True,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        collector_factory=_FakeOkxCollector,
    )

    validation = report["tier_validation"]
    assert report["status"] == "verified_research_only"
    assert report["liquidation_formula_verified"] is True
    assert report["maintenance_margin_tiers_verified"] is True
    assert report["exact_exchange_liquidation_formula_verified"] is True
    assert validation["td_modes_verified"] == ["cross", "isolated"]
    assert validation["tier_count"] == 4
    assert report["blockers"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert len(report["raw_response_files"]) == 2
    raw_paths = [tmp_path / row["path"] for row in report["raw_response_files"]]
    assert all(path.exists() for path in raw_paths)


def test_okx_liquidation_formula_report_rejects_missing_mode(tmp_path: Path) -> None:
    report = build_btc_okx_liquidation_formula_report(
        repo_root=tmp_path,
        output_root=tmp_path / "out",
        execute_network=True,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        collector_factory=_MissingModeCollector,
    )

    assert report["exact_exchange_liquidation_formula_verified"] is False
    assert report["maintenance_margin_tiers_verified"] is False
    assert "btc_okx_position_tiers_isolated_missing" in report["blockers"]
    assert "btc_okx_exact_liquidation_formula_evidence_incomplete" in report["blockers"]


class _FakeOkxCollector:
    def __init__(self, *, dry_run: bool, allow_network: bool, **_kwargs: Any) -> None:
        self.dry_run = dry_run
        self.allow_network = allow_network

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean = dict(params or {})
        endpoint = "/api/v5/public/position-tiers"
        response: dict[str, Any] = {
            "dry_run": self.dry_run,
            "network_called": self.allow_network and not self.dry_run,
            "endpoint": endpoint,
            "params": clean,
            "url": f"https://www.okx.com{endpoint}",
        }
        if self.allow_network and not self.dry_run:
            response["payload"] = _tier_payload(clean.get("tdMode", "cross"))
        return response


class _MissingModeCollector(_FakeOkxCollector):
    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        response = super().request_by_name(name, params)
        clean = dict(params or {})
        if self.allow_network and not self.dry_run and clean.get("tdMode") == "isolated":
            response["payload"] = {"code": "0", "msg": "", "data": []}
        return response


def _tier_payload(td_mode: str) -> dict[str, Any]:
    return {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instFamily": "BTC-USDT",
                "instId": "",
                "tier": "1",
                "minSz": "0",
                "maxSz": "1000",
                "mmr": "0.004",
                "imr": "0.01",
                "maxLever": "100",
                "tdMode": td_mode,
            },
            {
                "instFamily": "BTC-USDT",
                "instId": "",
                "tier": "2",
                "minSz": "1000.01",
                "maxSz": "5000",
                "mmr": "0.005",
                "imr": "0.015",
                "maxLever": "66.66",
                "tdMode": td_mode,
            },
        ],
    }
