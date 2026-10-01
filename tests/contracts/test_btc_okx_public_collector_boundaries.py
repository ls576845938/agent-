from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import http.client
import urllib.request
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactWriter,
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
)
from quant_crypto.data.okx_swap_public import (
    OkxSwapPublicCollector,
    OkxSwapPublicEndpointError,
    PUBLIC_ENDPOINTS,
    build_public_url,
    validate_public_endpoint,
)
from quant_crypto.data.immutable_okx_l2_export import (
    ATTESTATION_NAME,
    L2SegmentSource,
    export_immutable_okx_l2,
)
from quant_crypto.data.immutable_okx_10s_microstructure_export import (
    MicrostructureSegmentSource,
    export_immutable_okx_10s_microstructure,
)
import scripts.fetch_btc_okx_microstructure_public_data as micro_capture
import scripts.fetch_btc_okx_l2_microstructure_public_samples as l2_sample_capture
import scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture as aligned_l2_capture
import scripts.fetch_btc_okx_public_ws_l2_raw_capture as ws_l2_capture
import scripts.fetch_btc_okx_swap_public_data as swap_capture
import scripts.run_btc_okx_public_ws_l2_segment_capture as ws_segment_capture
from scripts.bootstrap_btc_runtime_artifact_root import (
    bootstrap_btc_runtime_artifact_root,
)
from scripts.fetch_btc_okx_microstructure_public_data import capture_okx_microstructure_public_data
from scripts.fetch_btc_okx_l2_microstructure_public_samples import capture_okx_l2_microstructure_public_samples
from scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture import capture_okx_timestamp_aligned_l2_public_data
from scripts.fetch_btc_okx_public_ws_l2_raw_capture import capture_okx_public_ws_l2_raw_data
from scripts.fetch_btc_okx_swap_public_data import capture_okx_public_bundle, _fetch_paginated_okx_rows, _okx_request, _row_time_ms
from scripts.run_btc_okx_public_ws_l2_segment_capture import run_btc_okx_public_ws_l2_segment_capture


def test_okx_public_ws_l2_raw_capture_tiebreaks_equal_windows_monotonic_ticks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wall_times = iter(
        [
            "2026-06-20T00:00:00.000000Z",
            "2026-06-20T00:00:00.100000Z",
            "2026-06-20T00:00:00.200000Z",
            "2026-06-20T00:00:00.300000Z",
            "2026-06-20T00:00:00.400000Z",
            "2026-06-20T00:00:00.500000Z",
        ]
    )
    monotonic_times = iter(
        [
            1_000_000_000,
            1_250_000_000,
            1_250_000_000,
            1_350_000_000,
            1_450_000_000,
            1_700_000_000,
        ]
    )

    class FakeWs:
        def __init__(self) -> None:
            self.messages = [
                '{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT-SWAP"}}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"snapshot","data":[{"bids":[["99.9","1","0","1"]],"asks":[["100.1","1","0","1"]],"ts":"1781913600100","seqId":10,"prevSeqId":-1,"checksum":0}]}',
                '{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},"data":[{"tradeId":"tie-1","px":"100.0","sz":"0.1","side":"buy","ts":"1781913600200"}]}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"update","data":[{"bids":[["99.9","1.5","0","1"]],"asks":[["100.1","1.5","0","1"]],"ts":"1781913600250","seqId":11,"prevSeqId":10,"checksum":0}]}',
            ]

        def settimeout(self, timeout: float) -> None:
            assert timeout == 0.1

        def connect(self, url: str) -> None:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"

        def send(self, _payload: str) -> None:
            return None

        def recv(self) -> str:
            return self.messages.pop(0)

        def close(self) -> None:
            return None

    class FakeWsModule:
        WebSocket = FakeWs

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(ws_l2_capture, "_load_websocket_module", lambda: FakeWsModule)
    monkeypatch.setattr(ws_l2_capture, "_utc_z_now_precise", lambda: next(wall_times))
    monkeypatch.setattr(ws_l2_capture.time, "monotonic_ns", lambda: next(monotonic_times))
    monkeypatch.setattr(ws_l2_capture.time, "monotonic", lambda: 0.0)

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        duration_seconds=5,
        max_messages=4,
        channels=["trades", "books"],
        recv_timeout_seconds=0.1,
        captured_at="2026-06-20T00:00:00Z",
    )

    raw_path = bundle / "okx_public_ws_l2_raw_messages.jsonl"
    manifest_path = bundle / "okx_public_ws_l2_raw_capture_manifest.json"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["status"] == "verified_preflight"
    assert [row["raw_monotonic_ns"] for row in rows] == [
        1_250_000_000,
        1_250_000_000,
        1_350_000_000,
        1_450_000_000,
    ]
    assert [row["monotonic_ns"] for row in rows] == [
        1_250_000_000,
        1_250_000_001,
        1_350_000_000,
        1_450_000_000,
    ]
    assert [row["monotonic_tiebreak_ns"] for row in rows] == [0, 1, 0, 0]
    assert manifest["raw_monotonic_ns_preserved"] is True
    assert manifest["monotonic_tiebreak_adjustment_count"] == 1
    assert manifest["monotonic_tiebreak_max_adjustment_ns"] == 1
    assert (
        manifest["monotonic_ordering_policy"]
        == "max(raw_monotonic_ns,previous_monotonic_ns_plus_1)"
    )
    assert all(
        current["monotonic_ns"] > previous["monotonic_ns"]
        for previous, current in zip(rows, rows[1:])
    )

    export = export_immutable_okx_10s_microstructure(
        segments=(
            MicrostructureSegmentSource(
                segment_dir=bundle,
                expected_raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            ),
        ),
        output_dir=tmp_path / "immutable",
        dataset_version="btc-okx-10s-windows-clock-tie-fixture-v1",
        source_head="b" * 40,
        now=datetime(2026, 6, 20, 0, 0, 1, tzinfo=timezone.utc),
    )
    assert export["status"] == "quality_checked"

    rollback_bundle = tmp_path / "rollback-bundle"
    rollback_bundle.mkdir()
    rollback_wall_times = iter(
        f"2026-06-20T00:00:01.{index:06d}Z" for index in range(6)
    )
    rollback_monotonic_times = iter(
        [
            2_000_000_000,
            2_250_000_000,
            2_249_999_999,
            2_350_000_000,
            2_450_000_000,
            2_700_000_000,
        ]
    )
    monkeypatch.setattr(
        ws_l2_capture,
        "_utc_z_now_precise",
        lambda: next(rollback_wall_times),
    )
    monkeypatch.setattr(
        ws_l2_capture.time,
        "monotonic_ns",
        lambda: next(rollback_monotonic_times),
    )
    rollback = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=rollback_bundle,
        execute_network=True,
        duration_seconds=5,
        max_messages=4,
        channels=["trades", "books"],
        recv_timeout_seconds=0.1,
        captured_at="2026-06-20T00:00:01Z",
    )
    assert rollback["status"] == "partial"
    assert (
        "btc_okx_public_ws_l2_monotonic_clock_rollback"
        in rollback["blockers"]
    )


def _bootstrap_hermetic_btc_runtime_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, BTCRuntimeArtifactWriter]:
    source_root = Path.cwd().resolve()

    artifact_root = tmp_path / "external-runtime-artifacts"
    bootstrap = bootstrap_btc_runtime_artifact_root(
        source_repo_root=source_root,
        artifact_root=artifact_root.resolve(),
    )
    monkeypatch.setenv(
        ENVIRONMENT_VARIABLE,
        str(artifact_root.resolve()),
    )

    assert bootstrap["status"] == "created"
    assert Path(bootstrap["artifact_root"]) == artifact_root.resolve()
    assert (artifact_root / OWNER_MARKER_NAME).is_file()
    assert artifact_root.resolve() != source_root
    assert not artifact_root.resolve().is_relative_to(source_root)

    writer = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=source_root,
    )
    real_replay_builder = (
        ws_segment_capture.build_btc_true_scalping_ws_order_book_replay_report
    )
    real_resync_builder = (
        ws_segment_capture.build_btc_true_scalping_ws_reconnect_resync_policy_report
    )

    def build_replay_from_external_fixture(**kwargs: Any) -> dict[str, Any]:
        kwargs["ws_capture_report_path"] = writer.logical_path(
            Path(kwargs["ws_capture_report_path"])
        )
        kwargs["output_root"] = writer.logical_path(
            Path(kwargs["output_root"])
        )
        kwargs["artifact_reader"] = writer
        kwargs["artifact_writer"] = writer
        return real_replay_builder(**kwargs)

    def build_resync_from_external_fixture(**kwargs: Any) -> dict[str, Any]:
        kwargs["replay_report_path"] = writer.logical_path(
            Path(kwargs["replay_report_path"])
        )
        kwargs["output_root"] = writer.logical_path(
            Path(kwargs["output_root"])
        )
        kwargs["artifact_reader"] = writer
        kwargs["artifact_writer"] = writer
        return real_resync_builder(**kwargs)

    monkeypatch.setattr(
        ws_segment_capture,
        "build_btc_true_scalping_ws_order_book_replay_report",
        build_replay_from_external_fixture,
    )
    monkeypatch.setattr(
        ws_segment_capture,
        "build_btc_true_scalping_ws_reconnect_resync_policy_report",
        build_resync_from_external_fixture,
    )
    return source_root, artifact_root, writer


def test_okx_public_collector_default_dry_run_does_not_call_network(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be called in dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    result = OkxSwapPublicCollector().request_by_name("candles", {"instId": "BTC-USDT-SWAP", "bar": "1H"})

    assert result["dry_run"] is True
    assert result["network_called"] is False
    assert "/api/v5/market/history-candles" in result["url"]


def test_okx_public_collector_rejects_private_or_order_endpoints() -> None:
    with pytest.raises(OkxSwapPublicEndpointError):
        validate_public_endpoint("/api/v5/trade/order")
    with pytest.raises(OkxSwapPublicEndpointError):
        validate_public_endpoint("/api/v5/account/balance")


def test_okx_public_url_builder_only_allows_public_params() -> None:
    url = build_public_url(PUBLIC_ENDPOINTS["funding_rate_history"], {"instId": "BTC-USDT-SWAP", "limit": "100"})

    assert url.startswith("https://www.okx.com/api/v5/public/funding-rate-history")
    assert "apikey" not in url.lower()
    with pytest.raises(OkxSwapPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["candles"], {"instId": "BTC-USDT-SWAP", "bar": "1H", "apiKey": "secret"})


def test_okx_public_url_builder_allows_microstructure_public_endpoints() -> None:
    trades = build_public_url(PUBLIC_ENDPOINTS["history_trades"], {"instId": "BTC-USDT-SWAP", "limit": "100"})
    books = build_public_url(PUBLIC_ENDPOINTS["books"], {"instId": "BTC-USDT-SWAP", "sz": "50"})

    assert trades.startswith("https://www.okx.com/api/v5/market/history-trades")
    assert books.startswith("https://www.okx.com/api/v5/market/books")
    with pytest.raises(OkxSwapPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["history_trades"], {"instId": "BTC-USDT-SWAP", "apiKey": "secret"})


def test_okx_public_url_builder_allows_position_tiers_without_private_auth() -> None:
    url = build_public_url(
        PUBLIC_ENDPOINTS["position_tiers"],
        {"instType": "SWAP", "tdMode": "cross", "instFamily": "BTC-USDT"},
    )

    assert url.startswith("https://www.okx.com/api/v5/public/position-tiers")
    assert "account" not in url.lower()
    assert "api" not in url.lower().split("?")[-1]
    with pytest.raises(OkxSwapPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["position_tiers"], {"instType": "SWAP", "tdMode": "cross", "apiKey": "secret"})


def test_okx_public_url_builder_allows_server_time_without_params_or_auth() -> None:
    url = build_public_url(PUBLIC_ENDPOINTS["server_time"], {})

    assert url == "https://www.okx.com/api/v5/public/time"
    with pytest.raises(OkxSwapPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["server_time"], {"apiKey": "secret"})
    with pytest.raises(OkxSwapPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["server_time"], {"instId": "BTC-USDT-SWAP"})


def test_okx_public_bundle_dry_run_plans_microstructure_without_network(tmp_path) -> None:
    result = capture_okx_public_bundle(
        repo_root=tmp_path,
        bundle_id="dry_run_microstructure_fixture",
        execute_network=False,
    )

    planned = {item["endpoint"] for item in result["planned_requests"]}
    assert result["status"] == "dry_run"
    assert result["network_called"] is False
    assert "/api/v5/market/history-trades" in planned
    assert "/api/v5/market/books" in planned


def test_short_funding_history_cannot_truncate_requested_candle_warmup() -> None:
    captured = "2026-07-29T12:15:00Z"
    market_start_ms, market_end_ms = swap_capture._requested_market_window_ms(
        captured_at=captured,
        history_days=220,
    )
    interval_ms = 3_600_000
    candle_rows = [
        [
            str(open_ms),
            "1",
            "2",
            "0.5",
            "1.5",
            "1",
            "1",
            "1",
            "1",
        ]
        for open_ms in range(
            market_start_ms,
            market_end_ms,
            interval_ms,
        )
    ]
    short_funding_rows = [
        {"fundingTime": str(market_end_ms - offset * 8 * interval_ms)}
        for offset in range(273)
    ]

    selected = swap_capture._select_candles(
        candle_rows,
        market_start_ms,
        market_end_ms,
        interval_ms,
    )
    candle_coverage = swap_capture._candle_component_coverage(
        selected,
        interval_ms=interval_ms,
        captured_at=captured,
    )
    funding_coverage = swap_capture._funding_component_coverage(
        short_funding_rows
    )

    assert candle_coverage["row_count"] == 5_280
    assert candle_coverage["confirmed_row_count"] == 5_280
    assert candle_coverage["gap_count"] == 0
    assert candle_coverage["freshness_status"] == "pass"
    assert funding_coverage["row_count"] == 273
    assert funding_coverage["sample_start_utc"] > candle_coverage["sample_start_utc"]


def test_mark_and_index_six_field_candles_use_terminal_confirm_flag() -> None:
    interval_ms = 3_600_000
    sample_start_ms = 100 * interval_ms
    sample_end_ms = 103 * interval_ms
    six_field_rows = [
        [str(sample_start_ms), "1", "2", "0.5", "1.5", "1"],
        [str(sample_start_ms + interval_ms), "1.5", "2.5", "1", "2", "1"],
        [str(sample_start_ms + 2 * interval_ms), "2", "3", "1.5", "2.5", "0"],
    ]

    selected = swap_capture._select_candles(
        six_field_rows,
        sample_start_ms,
        sample_end_ms,
        interval_ms,
    )

    assert [row[0] for row in selected] == [
        str(sample_start_ms),
        str(sample_start_ms + interval_ms),
    ]


def test_btc_swap_index_candles_use_explicit_underlying_index_id() -> None:
    assert swap_capture.VENUE_SYMBOL == "BTC-USDT-SWAP"
    assert swap_capture.INDEX_SYMBOL == "BTC-USDT"
    assert not swap_capture.INDEX_SYMBOL.endswith("-SWAP")


def test_okx_public_request_retries_remote_disconnect(monkeypatch) -> None:
    monkeypatch.setattr(swap_capture.time, "sleep", lambda _seconds: None)

    class FlakyCollector:
        def __init__(self) -> None:
            self.calls = 0

        def request_by_name(self, name: str, params: Mapping[str, Any]) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                raise http.client.RemoteDisconnected("test disconnect")
            return {"payload": {"code": "0", "data": []}, "name": name, "params": dict(params)}

    collector = FlakyCollector()
    result = _okx_request(collector, "candles", {"instId": "BTC-USDT-SWAP"})

    assert collector.calls == 2
    assert result["retry_attempt"] == 2
    assert result["payload"]["code"] == "0"


def test_okx_microstructure_capture_dry_run_is_public_only(tmp_path) -> None:
    result = capture_okx_microstructure_public_data(
        repo_root=tmp_path,
        bundle_dir=tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture",
        execute_network=False,
    )

    planned = {item["endpoint"] for item in result["planned_requests"]}
    assert result["status"] == "dry_run"
    assert result["network_called"] is False
    assert result["public_rest_only"] is True
    assert result["api_key_used"] is False
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
    assert planned == {"/api/v5/market/history-trades", "/api/v5/market/books"}


def test_okx_l2_microstructure_sample_capture_dry_run_is_bounded_public_only(tmp_path: Path) -> None:
    result = capture_okx_l2_microstructure_public_samples(
        repo_root=tmp_path,
        bundle_dir=tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture",
        execute_network=False,
        sample_count=2,
    )

    planned = [(item["sample_index"], item["role"], item["endpoint"]) for item in result["planned_requests"]]
    assert result["status"] == "dry_run"
    assert result["network_called"] is False
    assert result["public_rest_only"] is True
    assert result["api_key_used"] is False
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
    assert planned == [
        (1, "agg_trades", "/api/v5/market/history-trades"),
        (1, "order_book_depth", "/api/v5/market/books"),
        (2, "agg_trades", "/api/v5/market/history-trades"),
        (2, "order_book_depth", "/api/v5/market/books"),
    ]


def test_okx_timestamp_aligned_l2_capture_dry_run_is_public_only(tmp_path: Path) -> None:
    result = capture_okx_timestamp_aligned_l2_public_data(
        repo_root=tmp_path,
        bundle_dir=tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture",
        execute_network=False,
        sample_count=2,
    )

    planned = [(item["sample_index"], item["role"], item["endpoint"]) for item in result["planned_requests"]]
    assert result["status"] == "dry_run"
    assert result["network_called"] is False
    assert result["public_rest_only"] is True
    assert result["api_key_used"] is False
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
    assert planned == [
        (1, "agg_trades_aligned", "/api/v5/market/history-trades"),
        (1, "order_book_depth_aligned", "/api/v5/market/books"),
        (2, "agg_trades_aligned", "/api/v5/market/history-trades"),
        (2, "order_book_depth_aligned", "/api/v5/market/books"),
    ]


def test_okx_public_ws_l2_raw_capture_dry_run_is_public_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        ws_l2_capture,
        "_load_websocket_module",
        lambda: (_ for _ in ()).throw(AssertionError("dry-run must not load the network dependency")),
    )

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture",
        execute_network=False,
    )

    assert result["status"] == "dry_run"
    assert result["network_called"] is False
    assert result["public_ws_only"] is True
    assert result["api_key_used"] is False
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
    assert result["broker_calls_used"] is False
    assert result["planned_subscription"] == {
        "op": "subscribe",
        "args": [
            {"channel": "trades", "instId": "BTC-USDT-SWAP"},
            {"channel": "books", "instId": "BTC-USDT-SWAP"},
        ],
    }


def test_okx_public_ws_l2_runtime_dependency_is_project_installable() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "btc-public-ws = [" in pyproject
    assert '"websocket-client>=1.8,<2"' in pyproject


def test_okx_public_ws_l2_raw_capture_missing_dependency_is_structured_rejection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    report = tmp_path / "capture_report.json"
    monkeypatch.setattr(
        ws_l2_capture,
        "assert_no_okx_credentials_in_env",
        lambda: calls.append("credential_guard"),
    )
    monkeypatch.setattr(
        ws_l2_capture,
        "_load_websocket_module",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'websocket'")),
    )

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        capture_report_path=report,
        execute_network=True,
    )

    assert calls == ["credential_guard"]
    assert result["status"] == "rejected"
    assert result["network_called"] is False
    assert result["websocket_client_initialized"] is False
    assert result["message_count"] == 0
    assert result["data_message_count"] == 0
    assert result["files"] == []
    assert result["errors"] == [
        {
            "role": "websocket_client_dependency",
            "error_type": "ModuleNotFoundError",
            "error": "No module named 'websocket'",
        }
    ]
    assert "btc_okx_websocket_client_dependency_missing" in result["blockers"]
    assert json.loads(report.read_text(encoding="utf-8")) == result
    assert not (bundle / "okx_public_ws_l2_raw_messages.jsonl").exists()
    assert not (bundle / "okx_public_ws_l2_raw_capture_manifest.json").exists()


def test_okx_public_ws_l2_raw_capture_client_init_failure_is_structured_rejection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    class BrokenWsModule:
        class WebSocket:
            def __init__(self) -> None:
                calls.append("client_init")
                raise RuntimeError("fixture client init failed")

    monkeypatch.setattr(
        ws_l2_capture,
        "assert_no_okx_credentials_in_env",
        lambda: calls.append("credential_guard"),
    )
    monkeypatch.setattr(
        ws_l2_capture,
        "_load_websocket_module",
        lambda: calls.append("module_load") or BrokenWsModule,
    )

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        capture_report_path=tmp_path / "capture_report.json",
        execute_network=True,
    )

    assert calls == ["credential_guard", "module_load", "client_init"]
    assert result["status"] == "rejected"
    assert result["network_called"] is False
    assert result["websocket_client_initialized"] is False
    assert result["message_count"] == 0
    assert result["files"] == []
    assert result["errors"] == [
        {
            "role": "websocket_client_initialization",
            "error_type": "RuntimeError",
            "error": "fixture client init failed",
        }
    ]
    assert "btc_okx_public_ws_client_initialization_failed" in result["blockers"]
    assert not (bundle / "okx_public_ws_l2_raw_messages.jsonl").exists()
    assert not (bundle / "okx_public_ws_l2_raw_capture_manifest.json").exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_seconds": True},
        {"duration_seconds": float("nan")},
        {"duration_seconds": float("inf")},
        {"duration_seconds": 0.0},
        {"recv_timeout_seconds": False},
        {"recv_timeout_seconds": float("nan")},
        {"recv_timeout_seconds": -1.0},
        {"max_messages": True},
        {"max_messages": 0},
        {"forced_reconnect_after_messages": True},
        {"forced_reconnect_after_messages": -1},
    ],
)
def test_okx_public_ws_l2_capture_rejects_invalid_input_before_network(
    monkeypatch,
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    monkeypatch.setattr(
        ws_l2_capture,
        "_load_websocket_module",
        lambda: (_ for _ in ()).throw(
            AssertionError("network module must not load")
        ),
    )

    with pytest.raises(ValueError):
        capture_okx_public_ws_l2_raw_data(
            repo_root=tmp_path,
            bundle_dir=tmp_path / "bundle",
            execute_network=True,
            **overrides,
        )


def test_okx_public_ws_l2_segment_capture_dry_run_is_public_only(tmp_path: Path) -> None:
    result = run_btc_okx_public_ws_l2_segment_capture(
        repo_root=tmp_path,
        segment_id="fixture_segment",
        execute_network=False,
        duration_seconds=5,
        max_messages=10,
        generated_at="2026-06-20T00:00:00Z",
    )

    capture_report = (
        tmp_path
        / "artifacts/btc_scalping_readiness/fixture_segment/btc_okx_public_ws_l2_raw_capture_report.json"
    )
    runner_report = (
        tmp_path
        / "artifacts/btc_scalping_readiness/fixture_segment/btc_okx_public_ws_l2_segment_capture_run_report.json"
    )
    capture = json.loads(capture_report.read_text(encoding="utf-8"))

    assert result["status"] == "dry_run_public_ws_l2_segment_capture_planned"
    assert result["capture_network_called"] is False
    assert result["post_capture_reports_built"] is False
    assert result["true_scalping_allowed"] is False
    assert result["paper_or_live_unlock_allowed"] is False
    assert result["guardrails"]["broker_calls_allowed"] is False
    assert result["guardrails"]["private_endpoints_allowed"] is False
    assert result["guardrails"]["order_endpoints_allowed"] is False
    assert capture["status"] == "dry_run"
    assert capture["network_called"] is False
    assert capture["public_ws_only"] is True
    assert capture["private_endpoint_used"] is False
    assert capture["order_endpoint_used"] is False
    assert capture["broker_calls_used"] is False
    assert runner_report.exists()


def test_okx_public_ws_l2_raw_capture_rejects_login_required_channels(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        capture_okx_public_ws_l2_raw_data(
            repo_root=tmp_path,
            bundle_dir=tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture",
            execute_network=False,
            channels=["trades", "books50-l2-tbt"],
        )


def test_okx_microstructure_execute_keeps_planning_dry_run(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    class FakeOkxCollector:
        def __init__(self, *, dry_run: bool, allow_network: bool, **_kwargs: Any) -> None:
            self.dry_run = dry_run
            self.allow_network = allow_network

        def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
            calls.append({"name": name, "dry_run": self.dry_run, "allow_network": self.allow_network})
            endpoint = PUBLIC_ENDPOINTS[name]
            response = {
                "dry_run": self.dry_run,
                "network_called": self.allow_network and not self.dry_run,
                "endpoint": endpoint,
                "params": dict(params or {}),
                "url": f"https://www.okx.com{endpoint}",
            }
            if self.allow_network and not self.dry_run:
                if name == "history_trades":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "tradeId": "1",
                                "px": "100.0",
                                "sz": "0.1",
                                "side": "buy",
                                "ts": "1781960000000",
                            }
                        ],
                    }
                elif name == "books":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "ts": "1781960000100",
                                "bids": [["99.9", "1.0", "0", "1"]],
                                "asks": [["100.1", "1.0", "0", "1"]],
                            }
                        ],
                    }
            return response

    def fake_manifest(**_kwargs: Any) -> dict[str, Any]:
        return {"blockers": []}

    def fake_write_manifest(_manifest: Mapping[str, Any], bundle_dir: Path) -> str:
        path = Path(bundle_dir) / "btc_perpetual_bundle_manifest.json"
        path.write_text("{}", encoding="utf-8")
        return str(path)

    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(micro_capture, "OkxSwapPublicCollector", FakeOkxCollector)
    monkeypatch.setattr(micro_capture, "build_btc_perpetual_data_bundle_manifest", fake_manifest)
    monkeypatch.setattr(micro_capture, "write_manifest", fake_write_manifest)

    result = micro_capture.capture_okx_microstructure_public_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        captured_at="2026-06-20T00:00:00Z",
    )

    assert result["status"] == "verified"
    assert result["network_called"] is True
    assert [(call["name"], call["dry_run"], call["allow_network"]) for call in calls] == [
        ("history_trades", True, False),
        ("books", True, False),
        ("history_trades", False, True),
        ("books", False, True),
    ]
    assert all(item["dry_run"] is True for item in result["planned_requests"])
    assert all(item["network_called"] is False for item in result["planned_requests"])
    assert all("payload" not in item for item in result["planned_requests"])


def test_okx_l2_microstructure_sample_execute_writes_bounded_samples(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    class FakeOkxCollector:
        def __init__(self, *, dry_run: bool, allow_network: bool, **_kwargs: Any) -> None:
            self.dry_run = dry_run
            self.allow_network = allow_network

        def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
            calls.append({"name": name, "dry_run": self.dry_run, "allow_network": self.allow_network})
            endpoint = PUBLIC_ENDPOINTS[name]
            response = {
                "dry_run": self.dry_run,
                "network_called": self.allow_network and not self.dry_run,
                "endpoint": endpoint,
                "params": dict(params or {}),
                "url": f"https://www.okx.com{endpoint}",
                "duration_ms": 12.5,
            }
            if self.allow_network and not self.dry_run:
                if name == "history_trades":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "tradeId": str(len(calls)),
                                "px": "100.0",
                                "sz": "0.1",
                                "side": "buy",
                                "ts": "1781960000000",
                            }
                        ],
                    }
                elif name == "books":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "ts": "1781960000100",
                                "bids": [["99.9", "1.0", "0", "1"]],
                                "asks": [["100.1", "1.0", "0", "1"]],
                            }
                        ],
                    }
            return response

    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(l2_sample_capture, "OkxSwapPublicCollector", FakeOkxCollector)

    result = l2_sample_capture.capture_okx_l2_microstructure_public_samples(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        sample_count=2,
        request_sleep_seconds=0,
        captured_at="2026-06-20T00:00:00Z",
    )

    trade_rows = list(csv.DictReader((bundle / "agg_trades_samples.csv").open("r", encoding="utf-8")))
    book_rows = list(csv.DictReader((bundle / "order_book_depth_samples.csv").open("r", encoding="utf-8")))

    assert result["status"] == "verified"
    assert result["network_called"] is True
    assert result["completed_sample_count"] == 2
    assert result["capture_summary"]["trade_row_count"] == 2
    assert result["capture_summary"]["book_level_row_count"] == 4
    assert result["capture_summary"]["latency_sample_count"] == 4
    assert all(item["dry_run"] is True for item in result["planned_requests"])
    assert all(item["network_called"] is False for item in result["planned_requests"])
    assert {row["sample_index"] for row in trade_rows} == {"1", "2"}
    assert {row["sample_index"] for row in book_rows} == {"1", "2"}
    assert [(call["name"], call["dry_run"], call["allow_network"]) for call in calls] == [
        ("history_trades", True, False),
        ("books", True, False),
        ("history_trades", True, False),
        ("books", True, False),
        ("history_trades", False, True),
        ("books", False, True),
        ("history_trades", False, True),
        ("books", False, True),
    ]


def test_okx_timestamp_aligned_l2_capture_execute_writes_alignment_contract_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeOkxCollector:
        def __init__(self, *, dry_run: bool, allow_network: bool, **_kwargs: Any) -> None:
            self.dry_run = dry_run
            self.allow_network = allow_network

        def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
            calls.append({"name": name, "dry_run": self.dry_run, "allow_network": self.allow_network})
            endpoint = PUBLIC_ENDPOINTS[name]
            response = {
                "dry_run": self.dry_run,
                "network_called": self.allow_network and not self.dry_run,
                "endpoint": endpoint,
                "params": dict(params or {}),
                "url": f"https://www.okx.com{endpoint}",
                "duration_ms": 12.5,
            }
            if self.allow_network and not self.dry_run:
                if name == "history_trades":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "tradeId": str(len(calls)),
                                "px": "100.0",
                                "sz": "0.1",
                                "side": "buy",
                                "ts": "1781960000000",
                            }
                        ],
                    }
                elif name == "books":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "ts": "1781960000100",
                                "bids": [["99.9", "1.0", "0", "1"], ["99.8", "2.0", "0", "2"]],
                                "asks": [["100.1", "1.5", "0", "1"], ["100.2", "2.5", "0", "2"]],
                            }
                        ],
                    }
            return response

    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(aligned_l2_capture, "OkxSwapPublicCollector", FakeOkxCollector)

    result = capture_okx_timestamp_aligned_l2_public_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        sample_count=2,
        request_sleep_seconds=0,
        captured_at="2026-06-20T00:00:00Z",
    )

    trade_rows = list(csv.DictReader((bundle / "agg_trades_aligned.csv").open("r", encoding="utf-8")))
    book_rows = list(csv.DictReader((bundle / "order_book_depth_aligned.csv").open("r", encoding="utf-8")))
    manifest = (bundle / "l2_alignment_manifest.json").read_text(encoding="utf-8")

    assert result["status"] == "verified_preflight"
    assert result["network_called"] is True
    assert result["completed_sample_count"] == 2
    assert result["capture_summary"]["same_capture_sequence_count"] == 2
    assert {row["capture_sequence"] for row in trade_rows} == {"1", "2"}
    assert {row["capture_sequence"] for row in book_rows} == {"1", "2"}
    assert all(row["local_receive_ts"] for row in trade_rows)
    assert all(row["monotonic_ns"] for row in book_rows)
    assert all(row["spread_bps"] for row in book_rows)
    assert '"private_endpoint_used": false' in manifest
    assert '"order_endpoint_used": false' in manifest
    assert [(call["name"], call["dry_run"], call["allow_network"]) for call in calls] == [
        ("history_trades", True, False),
        ("books", True, False),
        ("history_trades", True, False),
        ("books", True, False),
        ("history_trades", False, True),
        ("books", False, True),
        ("history_trades", False, True),
        ("books", False, True),
    ]


def test_okx_timestamp_aligned_l2_capture_appends_existing_history(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeOkxCollector:
        def __init__(self, *, dry_run: bool, allow_network: bool, **_kwargs: Any) -> None:
            self.dry_run = dry_run
            self.allow_network = allow_network

        def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
            endpoint = PUBLIC_ENDPOINTS[name]
            response = {
                "dry_run": self.dry_run,
                "network_called": self.allow_network and not self.dry_run,
                "endpoint": endpoint,
                "params": dict(params or {}),
                "url": f"https://www.okx.com{endpoint}",
                "duration_ms": 12.5,
            }
            if self.allow_network and not self.dry_run:
                if name == "history_trades":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "tradeId": "new-trade",
                                "px": "101.0",
                                "sz": "0.2",
                                "side": "sell",
                                "ts": "1781961000000",
                            }
                        ],
                    }
                elif name == "books":
                    response["payload"] = {
                        "code": "0",
                        "data": [
                            {
                                "ts": "1781961000100",
                                "bids": [["100.9", "1.0", "0", "1"]],
                                "asks": [["101.1", "1.0", "0", "1"]],
                            }
                        ],
                    }
            return response

    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    bundle.mkdir(parents=True)
    _write_text(
        bundle / "agg_trades_aligned.csv",
        "\n".join(
            [
                "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,trade_id,price,size,side,source_record_id",
                "1,2026-06-20T00:00:00Z,1781960000000,2026-06-20T00:00:01Z,1,BTC-USDT-SWAP,BTCUSDT,old-trade,100.0,0.1,buy,old-trade-id",
            ]
        )
        + "\n",
    )
    _write_text(
        bundle / "order_book_depth_aligned.csv",
        "\n".join(
            [
                "capture_sequence,exchange_ts,exchange_ts_ms,local_receive_ts,monotonic_ns,venue_symbol,symbol,side,level,price,size,best_bid,best_ask,spread_bps,bid_depth_notional,ask_depth_notional,liquidation_orders,order_count,source_record_id",
                "1,2026-06-20T00:00:00Z,1781960000100,2026-06-20T00:00:01Z,1,BTC-USDT-SWAP,BTCUSDT,bid,1,99.9,1.0,99.9,100.1,20.0,99.9,100.1,0,1,old-bid",
                "1,2026-06-20T00:00:00Z,1781960000100,2026-06-20T00:00:01Z,1,BTC-USDT-SWAP,BTCUSDT,ask,1,100.1,1.0,99.9,100.1,20.0,99.9,100.1,0,1,old-ask",
            ]
        )
        + "\n",
    )
    monkeypatch.setattr(aligned_l2_capture, "OkxSwapPublicCollector", FakeOkxCollector)

    result = capture_okx_timestamp_aligned_l2_public_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        sample_count=1,
        request_sleep_seconds=0,
        captured_at="2026-06-21T00:00:00Z",
    )

    trade_rows = list(csv.DictReader((bundle / "agg_trades_aligned.csv").open("r", encoding="utf-8")))
    book_rows = list(csv.DictReader((bundle / "order_book_depth_aligned.csv").open("r", encoding="utf-8")))
    manifest = json.loads((bundle / "l2_alignment_manifest.json").read_text(encoding="utf-8"))

    assert result["status"] == "verified_preflight"
    assert result["capture_summary"]["trade_row_count"] == 2
    assert result["capture_summary"]["book_level_row_count"] == 4
    assert {row["capture_sequence"] for row in trade_rows} == {"1", "2"}
    assert {row["capture_sequence"] for row in book_rows} == {"1", "2"}
    assert manifest["append_existing"] is True
    assert manifest["existing_trade_row_count"] == 1
    assert manifest["new_trade_row_count"] == 1
    assert manifest["cumulative_trade_row_count"] == 2


def test_okx_public_ws_l2_raw_capture_execute_writes_public_raw_frames(monkeypatch, tmp_path: Path) -> None:
    sent: list[str] = []

    class FakeWs:
        def __init__(self) -> None:
            self.messages = [
                '{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT-SWAP"}}',
                '{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},"data":[{"tradeId":"1","px":"100.0","sz":"0.1","side":"buy","ts":"1781960000000"}]}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"snapshot","data":[{"bids":[["99.9","1","0","1"]],"asks":[["100.1","1","0","1"]],"ts":"1781960000100","seqId":10,"prevSeqId":9,"checksum":123}]}',
            ]

        def settimeout(self, timeout: float) -> None:
            assert timeout == 0.1

        def connect(self, url: str) -> None:
            assert url == "wss://wsaws.okx.com:8443/ws/v5/public"

        def send(self, payload: str) -> None:
            sent.append(payload)

        def recv(self) -> str:
            if not self.messages:
                raise TimeoutError("done")
            return self.messages.pop(0)

        def close(self) -> None:
            sent.append("close")

    class FakeWsModule:
        WebSocket = FakeWs

    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(ws_l2_capture, "_load_websocket_module", lambda: FakeWsModule)

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        duration_seconds=5,
        max_messages=3,
        recv_timeout_seconds=0.1,
        public_ws_url="wss://wsaws.okx.com:8443/ws/v5/public",
        captured_at="2026-06-20T00:00:00Z",
    )

    raw_lines = (bundle / "okx_public_ws_l2_raw_messages.jsonl").read_text(encoding="utf-8").strip().splitlines()
    manifest = json.loads((bundle / "okx_public_ws_l2_raw_capture_manifest.json").read_text(encoding="utf-8"))

    assert result["status"] == "verified_preflight"
    assert result["network_called"] is True
    assert result["message_count"] == 3
    assert result["data_message_count"] == 2
    assert result["channel_counts"] == {"books": 1, "trades": 1}
    assert len(raw_lines) == 3
    assert manifest["public_ws_only"] is True
    assert manifest["private_endpoint_used"] is False
    assert manifest["order_endpoint_used"] is False
    assert manifest["broker_calls_used"] is False
    assert manifest["public_ws_url"] == "wss://wsaws.okx.com:8443/ws/v5/public"
    assert '"op":"subscribe"' in sent[0]


def test_okx_public_ws_l2_raw_capture_precision_satisfies_immutable_export_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wall_times = iter(
        [
            "2026-07-28T23:08:54.000000Z",
            "2026-07-28T23:08:54.250000Z",
            "2026-07-28T23:08:54.350000Z",
            "2026-07-28T23:08:54.450000Z",
            "2026-07-28T23:08:54.700000Z",
        ]
    )
    monotonic_times = iter(
        [
            1_000_000_000,
            1_250_000_000,
            1_350_000_000,
            1_450_000_000,
            1_700_000_000,
        ]
    )

    class FakeWs:
        def __init__(self) -> None:
            self.messages = [
                '{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT-SWAP"}}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"snapshot","data":[{"bids":[["99.9","1","0","1"]],"asks":[["100.1","1","0","1"]],"ts":"1785280134300","seqId":10,"prevSeqId":-1,"checksum":0}]}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"update","data":[{"bids":[["99.9","1.5","0","1"]],"asks":[["100.1","1.5","0","1"]],"ts":"1785280134400","seqId":11,"prevSeqId":10,"checksum":0}]}',
            ]

        def settimeout(self, timeout: float) -> None:
            assert timeout == 0.1

        def connect(self, url: str) -> None:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"

        def send(self, _payload: str) -> None:
            return None

        def recv(self) -> str:
            return self.messages.pop(0)

        def close(self) -> None:
            return None

    class FakeWsModule:
        WebSocket = FakeWs

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(
        ws_l2_capture,
        "_load_websocket_module",
        lambda: FakeWsModule,
    )
    monkeypatch.setattr(
        ws_l2_capture,
        "_utc_z_now_precise",
        lambda: next(wall_times),
    )
    monkeypatch.setattr(
        ws_l2_capture.time,
        "monotonic_ns",
        lambda: next(monotonic_times),
    )
    monkeypatch.setattr(ws_l2_capture.time, "monotonic", lambda: 0.0)

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        duration_seconds=5,
        max_messages=3,
        channels=["books"],
        recv_timeout_seconds=0.1,
        captured_at="2026-07-28T23:08:53Z",
    )

    raw_path = bundle / "okx_public_ws_l2_raw_messages.jsonl"
    manifest_path = bundle / "okx_public_ws_l2_raw_capture_manifest.json"
    raw_rows = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wall_duration = (
        datetime.fromisoformat(
            manifest["capture_end"].replace("Z", "+00:00")
        )
        - datetime.fromisoformat(
            manifest["capture_start"].replace("Z", "+00:00")
        )
    ).total_seconds()
    monotonic_duration = (
        manifest["capture_ended_monotonic_ns"]
        - manifest["capture_started_monotonic_ns"]
    ) / 1_000_000_000.0

    assert result["status"] == "verified_preflight"
    assert manifest["capture_start"].endswith(".250000Z")
    assert manifest["capture_end"].endswith(".450000Z")
    assert [row["local_receive_ts"] for row in raw_rows] == [
        "2026-07-28T23:08:54.250000Z",
        "2026-07-28T23:08:54.350000Z",
        "2026-07-28T23:08:54.450000Z",
    ]
    assert abs(wall_duration - monotonic_duration) <= 0.1
    assert (
        datetime.fromisoformat(
            raw_rows[0]["local_receive_ts"].replace("Z", "+00:00")
        )
        - datetime.fromisoformat(
            manifest["capture_start"].replace("Z", "+00:00")
        )
    ).total_seconds() <= 0.1
    assert (
        datetime.fromisoformat(
            manifest["capture_end"].replace("Z", "+00:00")
        )
        - datetime.fromisoformat(
            raw_rows[-1]["local_receive_ts"].replace("Z", "+00:00")
        )
    ).total_seconds() <= 0.1

    source = L2SegmentSource(
        segment_dir=bundle,
        expected_raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        expected_manifest_sha256=hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
    )
    output = tmp_path / "immutable"
    report = export_immutable_okx_l2(
        segments=(source,),
        output_dir=output,
        dataset_version="btc-okx-l2-collector-precision-fixture-v1",
        source_head="b" * 40,
        now=datetime(2026, 7, 28, 23, 8, 55, tzinfo=timezone.utc),
        max_clock_lag_ms=2_000,
        freshness_sla_minutes=15,
        max_inter_message_gap_seconds=5,
    )
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )

    assert report["status"] == "quality_checked"
    assert attestation["sequence_validation_status"] == "pass"
    assert attestation["sequence_gap_count"] == 0
    assert attestation["unrecovered_gap_count"] == 0
    assert (
        attestation["checksum_policy"]
        == "nonzero_crc32_validated_zero_accepted_after_okx_deprecation"
    )


def test_okx_public_ws_l2_raw_capture_rejects_unapproved_ws_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="production public-market allowlist"):
        capture_okx_public_ws_l2_raw_data(
            repo_root=tmp_path,
            bundle_dir=tmp_path / "bundle",
            public_ws_url="wss://example.invalid/ws/v5/public",
        )


def test_okx_public_ws_l2_capture_errors_are_fail_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeWs:
        def __init__(self) -> None:
            self.sent = False

        def send(self, _payload: str) -> None:
            return None

        def settimeout(self, timeout: float) -> None:
            assert timeout == 0.1

        def connect(self, _url: str) -> None:
            return None

        def recv(self) -> str:
            if not self.sent:
                self.sent = True
                return (
                    '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},'
                    '"action":"snapshot","data":[{"bids":[["99","1","0","1"]],'
                    '"asks":[["101","1","0","1"]],"ts":"1781960000100",'
                    '"seqId":10,"prevSeqId":9,"checksum":0}]}'
                )
            raise TimeoutError("fixture timeout")

        def close(self) -> None:
            return None

    class FakeWsModule:
        WebSocket = FakeWs

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(
        ws_l2_capture,
        "_load_websocket_module",
        lambda: FakeWsModule,
    )

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        duration_seconds=5.0,
        max_messages=2,
        channels=["books"],
        recv_timeout_seconds=0.1,
    )

    assert result["status"] == "partial"
    assert "btc_okx_public_ws_l2_capture_errors_present" in result["blockers"]
    assert result["manifest"]["error_count"] == 1


def test_okx_public_ws_l2_segment_capture_execute_builds_isolated_reports(monkeypatch, tmp_path: Path) -> None:
    source_root, artifact_root, writer = _bootstrap_hermetic_btc_runtime_fixture(
        monkeypatch,
        tmp_path,
    )
    sent: list[str] = []

    class FakeWs:
        def __init__(self) -> None:
            self.messages = [
                '{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT-SWAP"}}',
                '{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},"data":[{"tradeId":"1","px":"100.0","sz":"0.1","side":"buy","ts":"1781960000000"}]}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"snapshot","data":[{"bids":[["99.9","1","0","1"]],"asks":[["100.1","1","0","1"]],"ts":"1781960000100","seqId":10,"prevSeqId":9,"checksum":123}]}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"update","data":[{"bids":[["99.9","1.2","0","1"]],"asks":[["100.1","0.8","0","1"]],"ts":"1781960000200","seqId":11,"prevSeqId":10,"checksum":124}]}',
            ]

        def send(self, payload: str) -> None:
            sent.append(payload)

        def settimeout(self, timeout: float) -> None:
            assert timeout == 0.1

        def connect(self, url: str) -> None:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"

        def recv(self) -> str:
            if not self.messages:
                raise TimeoutError("done")
            return self.messages.pop(0)

        def close(self) -> None:
            sent.append("close")

    class FakeWsModule:
        WebSocket = FakeWs

    monkeypatch.setattr(ws_l2_capture, "_load_websocket_module", lambda: FakeWsModule)

    result = run_btc_okx_public_ws_l2_segment_capture(
        repo_root=source_root,
        segment_id="fixture_segment_execute",
        bundle_root=tmp_path / "public-ws-bundles",
        capture_root=artifact_root / "btc_scalping_readiness",
        execute_network=True,
        duration_seconds=5,
        max_messages=4,
        recv_timeout_seconds=0.1,
        generated_at="2026-06-20T00:00:00Z",
    )

    output_root = artifact_root / "btc_scalping_readiness/fixture_segment_execute"
    replay_path = output_root / "btc_true_scalping_ws_order_book_replay_report.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    latency_queue = json.loads(
        (output_root / "btc_true_scalping_ws_latency_queue_diagnostics_report.json").read_text(encoding="utf-8")
    )
    coverage = json.loads(
        (
            artifact_root
            / "btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json"
        ).read_text(encoding="utf-8")
    )

    assert result["status"] == "public_ws_l2_segment_capture_verified_research_only"
    assert result["capture_status"] == "verified_preflight"
    assert result["capture_network_called"] is True
    assert result["post_capture_reports_built"] is True
    assert result["true_scalping_allowed"] is False
    assert result["paper_or_live_unlock_allowed"] is False
    assert result["guardrails"]["broker_calls_allowed"] is False
    assert "fixture_segment_execute" in result["selected_bundle_dir"]
    assert replay["replay_sequence_ready"] is True
    assert latency_queue["proxy_diagnostics_ready"] is True
    assert coverage["status"] == "ws_l2_capture_coverage_accumulating_research_only_history_insufficient"
    assert coverage["coverage_totals"]["verified_public_session_count"] == 1
    assert writer.resolve(
        "artifacts/btc_scalping_readiness/fixture_segment_execute/"
        "btc_true_scalping_ws_order_book_replay_report.json",
        require_file=True,
    ) == replay_path.resolve()
    assert not (
        source_root
        / "artifacts/btc_scalping_readiness/fixture_segment_execute"
    ).exists()
    assert sent.count("close") == 1


def test_okx_public_ws_l2_raw_capture_forced_reconnect_records_segments(monkeypatch, tmp_path: Path) -> None:
    sent: list[str] = []
    connections: list["FakeWs"] = []

    class FakeWs:
        def __init__(self, messages: list[str]) -> None:
            self.messages = messages

        def send(self, payload: str) -> None:
            sent.append(payload)

        def settimeout(self, timeout: float) -> None:
            assert timeout == 0.1

        def connect(self, url: str) -> None:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"

        def recv(self) -> str:
            if not self.messages:
                raise TimeoutError("done")
            return self.messages.pop(0)

        def close(self) -> None:
            sent.append("close")

    class FakeWsModule:
        @staticmethod
        def WebSocket() -> FakeWs:
            messages_by_connection = [
                [
                    '{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT-SWAP"}}',
                    '{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},"data":[{"tradeId":"1","px":"100.0","sz":"0.1","side":"buy","ts":"1781960000000"}]}',
                ],
                [
                    '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"snapshot","data":[{"bids":[["99.9","1","0","1"]],"asks":[["100.1","1","0","1"]],"ts":"1781960000100","seqId":10,"prevSeqId":-1,"checksum":123}]}',
                ],
            ]
            ws = FakeWs(messages_by_connection[len(connections)])
            connections.append(ws)
            return ws

    bundle = tmp_path / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(ws_l2_capture, "_load_websocket_module", lambda: FakeWsModule)

    result = capture_okx_public_ws_l2_raw_data(
        repo_root=tmp_path,
        bundle_dir=bundle,
        execute_network=True,
        duration_seconds=5,
        max_messages=3,
        recv_timeout_seconds=0.1,
        forced_reconnect_after_messages=2,
        captured_at="2026-06-20T00:00:00Z",
    )

    raw_rows = [
        json.loads(line)
        for line in (bundle / "okx_public_ws_l2_raw_messages.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    manifest = json.loads((bundle / "okx_public_ws_l2_raw_capture_manifest.json").read_text(encoding="utf-8"))

    assert result["status"] == "verified_preflight"
    assert result["connection_count"] == 2
    assert result["forced_reconnect_count"] == 1
    assert [row["connection_sequence"] for row in raw_rows] == [1, 1, 2]
    assert manifest["connection_count"] == 2
    assert manifest["forced_reconnect_after_messages"] == 2
    assert manifest["forced_reconnect_count"] == 1
    assert manifest["gap_count"] == 1
    assert sent.count("close") == 2
    assert sum(1 for payload in sent if '"op":"subscribe"' in payload) == 2


def test_okx_paginated_rows_walk_backward_with_after_and_dedupe() -> None:
    collector = _FakeOkxCollector(
        {
            "200": [["100", "1"], ["0", "1"], ["100", "duplicate"]],
        }
    )

    rows = _fetch_paginated_okx_rows(
        collector,
        "candles",
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100"},
        timestamp_getter=_row_time_ms,
        target_start_ms=50,
        initial_rows=[["300", "1"], ["200", "1"]],
        sleep_seconds=0,
    )

    assert [row[0] for row in rows] == ["0", "100", "200", "300"]
    assert collector.calls == [
        {
            "name": "candles",
            "params": {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "200"},
        }
    ]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _FakeOkxCollector:
    def __init__(self, pages: Mapping[str, list[list[str]]]) -> None:
        self.pages = dict(pages)
        self.calls: list[dict[str, Any]] = []

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean = dict(params or {})
        self.calls.append({"name": name, "params": clean})
        return {"payload": {"code": "0", "data": self.pages.get(str(clean.get("after", "")), [])}}
