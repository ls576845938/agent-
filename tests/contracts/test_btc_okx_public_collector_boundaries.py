from __future__ import annotations

import urllib.request
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from quant_crypto.data.okx_swap_public import (
    OkxSwapPublicCollector,
    OkxSwapPublicEndpointError,
    PUBLIC_ENDPOINTS,
    build_public_url,
    validate_public_endpoint,
)
import scripts.fetch_btc_okx_microstructure_public_data as micro_capture
import scripts.fetch_btc_okx_l2_microstructure_public_samples as l2_sample_capture
import scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture as aligned_l2_capture
import scripts.fetch_btc_okx_public_ws_l2_raw_capture as ws_l2_capture
from scripts.fetch_btc_okx_microstructure_public_data import capture_okx_microstructure_public_data
from scripts.fetch_btc_okx_l2_microstructure_public_samples import capture_okx_l2_microstructure_public_samples
from scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture import capture_okx_timestamp_aligned_l2_public_data
from scripts.fetch_btc_okx_public_ws_l2_raw_capture import capture_okx_public_ws_l2_raw_data
from scripts.fetch_btc_okx_swap_public_data import capture_okx_public_bundle, _fetch_paginated_okx_rows, _row_time_ms
from scripts.run_btc_okx_public_ws_l2_segment_capture import run_btc_okx_public_ws_l2_segment_capture


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


def test_okx_public_ws_l2_raw_capture_dry_run_is_public_only(tmp_path: Path) -> None:
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


def test_okx_public_ws_l2_raw_capture_execute_writes_public_raw_frames(monkeypatch, tmp_path: Path) -> None:
    sent: list[str] = []

    class FakeWs:
        def __init__(self) -> None:
            self.messages = [
                '{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT-SWAP"}}',
                '{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},"data":[{"tradeId":"1","px":"100.0","sz":"0.1","side":"buy","ts":"1781960000000"}]}',
                '{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"action":"snapshot","data":[{"bids":[["99.9","1","0","1"]],"asks":[["100.1","1","0","1"]],"ts":"1781960000100","seqId":10,"prevSeqId":9,"checksum":123}]}',
            ]

        def send(self, payload: str) -> None:
            sent.append(payload)

        def recv(self) -> str:
            if not self.messages:
                raise TimeoutError("done")
            return self.messages.pop(0)

        def close(self) -> None:
            sent.append("close")

    class FakeWsModule:
        @staticmethod
        def create_connection(url: str, timeout: float) -> FakeWs:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"
            assert timeout == 0.1
            return FakeWs()

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
    assert '"op":"subscribe"' in sent[0]


def test_okx_public_ws_l2_segment_capture_execute_builds_isolated_reports(monkeypatch, tmp_path: Path) -> None:
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

        def recv(self) -> str:
            if not self.messages:
                raise TimeoutError("done")
            return self.messages.pop(0)

        def close(self) -> None:
            sent.append("close")

    class FakeWsModule:
        @staticmethod
        def create_connection(url: str, timeout: float) -> FakeWs:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"
            assert timeout == 0.1
            return FakeWs()

    monkeypatch.setattr(ws_l2_capture, "_load_websocket_module", lambda: FakeWsModule)

    result = run_btc_okx_public_ws_l2_segment_capture(
        repo_root=tmp_path,
        segment_id="fixture_segment_execute",
        execute_network=True,
        duration_seconds=5,
        max_messages=4,
        recv_timeout_seconds=0.1,
        generated_at="2026-06-20T00:00:00Z",
    )

    output_root = tmp_path / "artifacts/btc_scalping_readiness/fixture_segment_execute"
    replay = json.loads((output_root / "btc_true_scalping_ws_order_book_replay_report.json").read_text(encoding="utf-8"))
    latency_queue = json.loads(
        (output_root / "btc_true_scalping_ws_latency_queue_diagnostics_report.json").read_text(encoding="utf-8")
    )
    coverage = json.loads(
        (
            tmp_path
            / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json"
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
    assert sent.count("close") == 1


def test_okx_public_ws_l2_raw_capture_forced_reconnect_records_segments(monkeypatch, tmp_path: Path) -> None:
    sent: list[str] = []
    connections: list["FakeWs"] = []

    class FakeWs:
        def __init__(self, messages: list[str]) -> None:
            self.messages = messages

        def send(self, payload: str) -> None:
            sent.append(payload)

        def recv(self) -> str:
            if not self.messages:
                raise TimeoutError("done")
            return self.messages.pop(0)

        def close(self) -> None:
            sent.append("close")

    class FakeWsModule:
        @staticmethod
        def create_connection(url: str, timeout: float) -> FakeWs:
            assert url == "wss://ws.okx.com:8443/ws/v5/public"
            assert timeout == 0.1
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


class _FakeOkxCollector:
    def __init__(self, pages: Mapping[str, list[list[str]]]) -> None:
        self.pages = dict(pages)
        self.calls: list[dict[str, Any]] = []

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean = dict(params or {})
        self.calls.append({"name": name, "params": clean})
        return {"payload": {"code": "0", "data": self.pages.get(str(clean.get("after", "")), [])}}
