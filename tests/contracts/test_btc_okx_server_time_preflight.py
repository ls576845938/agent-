from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.research.btc_okx_server_time_preflight import (
    SCHEMA_VERSION,
    build_btc_okx_server_time_preflight_report,
)


def test_okx_server_time_preflight_dry_run_is_fail_closed(tmp_path: Path) -> None:
    report = build_btc_okx_server_time_preflight_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        execute_network=False,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        sample_count=1,
        collector_factory=_FakeOkxCollector,
    )

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["status"] == "dry_run"
    assert report["server_time_offset_verified"] is False
    assert report["public_rest_only"] is True
    assert report["api_key_used"] is False
    assert report["private_endpoint_used"] is False
    assert report["order_endpoint_used"] is False
    assert "btc_okx_server_time_network_capture_not_executed" in report["blockers"]
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_okx_server_time_preflight_verifies_offset_without_private_or_order_endpoint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    values = iter([1_780_000_000_000.0, 1_780_000_000_080.0])
    monkeypatch.setattr("quant_crypto.research.btc_okx_server_time_preflight.time", lambda: next(values) / 1000.0)

    report = build_btc_okx_server_time_preflight_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        execute_network=True,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        sample_count=1,
        collector_factory=_FakeOkxCollector,
    )

    assert report["status"] == "verified_research_only"
    assert report["server_time_offset_verified"] is True
    assert report["server_time_metrics"]["round_trip_ms"] == 80.0
    assert report["server_time_metrics"]["offset_ms"] == 10.0
    assert report["server_time_metrics"]["selection_method"] == "minimum_round_trip_sample"
    assert report["server_time_metrics"]["valid_sample_count"] == 1
    assert report["server_time_metrics"]["abs_offset_p50_ms"] == 10.0
    assert report["server_time_metrics"]["abs_offset_p95_ms"] == 10.0
    assert report["server_time_metrics"]["abs_offset_max_ms"] == 10.0
    assert report["server_time_metrics"]["round_trip_p50_ms"] == 80.0
    assert report["server_time_metrics"]["round_trip_p95_ms"] == 80.0
    assert report["server_time_metrics"]["round_trip_max_ms"] == 80.0
    assert report["blockers"] == []
    assert report["private_endpoint_used"] is False
    assert report["order_endpoint_used"] is False
    assert (tmp_path / "out" / "btc_okx_server_time_preflight_report.json").exists()
    assert (tmp_path / "out" / "btc_okx_server_time_preflight_summary_cn.md").exists()
    assert (tmp_path / "out" / "btc_okx_server_time_preflight_safety_status.json").exists()


def test_okx_server_time_preflight_blocks_large_offset(monkeypatch, tmp_path: Path) -> None:
    values = iter([1_780_000_000_000.0, 1_780_000_000_080.0])
    monkeypatch.setattr("quant_crypto.research.btc_okx_server_time_preflight.time", lambda: next(values) / 1000.0)

    report = build_btc_okx_server_time_preflight_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        execute_network=True,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        max_abs_offset_ms=5.0,
        sample_count=1,
        collector_factory=_FakeOkxCollector,
    )

    assert report["server_time_offset_verified"] is False
    assert "btc_okx_server_time_offset_exceeds_threshold" in report["blockers"]


class _FakeOkxCollector:
    def __init__(self, *, dry_run: bool, allow_network: bool, **_kwargs: Any) -> None:
        self.dry_run = dry_run
        self.allow_network = allow_network

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        endpoint = "/api/v5/public/time"
        result = {
            "dry_run": self.dry_run,
            "network_called": self.allow_network and not self.dry_run,
            "endpoint": endpoint,
            "params": dict(params or {}),
            "url": f"https://www.okx.com{endpoint}",
        }
        if self.allow_network and not self.dry_run:
            result["payload"] = {"code": "0", "msg": "", "data": [{"ts": "1780000000050"}]}
        return result
