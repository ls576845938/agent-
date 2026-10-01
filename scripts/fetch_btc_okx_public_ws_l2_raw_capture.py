#!/usr/bin/env python3
"""Capture OKX public WebSocket trades/books raw frames for BTC L2 research."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import math

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.okx_l2_capture_contract import (
        OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
        OKX_L2_INSTRUMENT_ID,
        OKX_L2_PUBLIC_WS_URL,
        OKX_L2_PUBLIC_WS_URLS,
        OKX_L2_RAW_MANIFEST_FILE,
        OKX_L2_RAW_MESSAGES_FILE,
        OKX_L2_SYMBOL,
    )
    from quant_crypto.data.okx_swap_public import assert_no_okx_credentials_in_env
    from scripts.fetch_btc_okx_swap_public_data import _file_facts, _relpath, _utc_z_now, _write_json_atomic
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.okx_l2_capture_contract import (
        OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
        OKX_L2_INSTRUMENT_ID,
        OKX_L2_PUBLIC_WS_URL,
        OKX_L2_PUBLIC_WS_URLS,
        OKX_L2_RAW_MANIFEST_FILE,
        OKX_L2_RAW_MESSAGES_FILE,
        OKX_L2_SYMBOL,
    )
    from quant_crypto.data.okx_swap_public import assert_no_okx_credentials_in_env
    from scripts.fetch_btc_okx_swap_public_data import _file_facts, _relpath, _utc_z_now, _write_json_atomic


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_okx_public_ws_l2_raw_capture_report.json")
PUBLIC_WS_URL = OKX_L2_PUBLIC_WS_URL
VENUE_SYMBOL = OKX_L2_INSTRUMENT_ID
SYMBOL = OKX_L2_SYMBOL
RAW_WS_MESSAGES_FILE = OKX_L2_RAW_MESSAGES_FILE
RAW_WS_MANIFEST_FILE = OKX_L2_RAW_MANIFEST_FILE
REPORT_SCHEMA_VERSION = "btc_okx_public_ws_l2_raw_capture_report_v1"
ALLOWED_PUBLIC_WS_CHANNELS = {"trades", "books", "books5", "bbo-tbt"}
DISALLOWED_PUBLIC_WS_CHANNELS = {"books-l2-tbt", "books50-l2-tbt", "orders", "account", "positions"}


def _utc_z_now_precise() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def capture_okx_public_ws_l2_raw_data(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG,
    bundle_dir: Path | None = None,
    capture_report_path: Path = DEFAULT_CAPTURE_REPORT,
    execute_network: bool = False,
    duration_seconds: float = 10.0,
    max_messages: int = 2_000,
    channels: list[str] | None = None,
    recv_timeout_seconds: float = 5.0,
    forced_reconnect_after_messages: int = 0,
    public_ws_url: str = PUBLIC_WS_URL,
    captured_at: str | None = None,
) -> dict[str, Any]:
    effective_duration = _positive_finite_number(
        duration_seconds,
        "duration_seconds",
    )
    effective_timeout = _positive_finite_number(
        recv_timeout_seconds,
        "recv_timeout_seconds",
    )
    effective_max_messages = _positive_integer(
        max_messages,
        "max_messages",
    )
    effective_forced_reconnect_after_messages = _nonnegative_integer(
        forced_reconnect_after_messages,
        "forced_reconnect_after_messages",
    )
    effective_public_ws_url = _validate_public_ws_url(public_ws_url)
    root = repo_root.resolve()
    captured = captured_at or _utc_z_now()
    selected_bundle = _resolve(root, bundle_dir) if bundle_dir else selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    report_path = _resolve(root, capture_report_path)
    effective_channels = _validate_channels(channels or ["trades", "books"])
    blockers: list[str] = []
    if selected_bundle is None:
        blockers.append("btc_okx_selected_bundle_missing")
        selected_bundle = root / "data/external/btc_perpetual/okx_swap/bundles/missing"
    subscription = {
        "op": "subscribe",
        "args": [{"channel": channel, "instId": VENUE_SYMBOL} for channel in effective_channels],
    }
    base_payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": captured,
        "selected_bundle_dir": _relpath(selected_bundle, root),
        "public_ws_url": effective_public_ws_url,
        "source_endpoint_category": "okx_public_market_data_websocket",
        "collector_commit": _git_head(root),
        "venue_symbol": VENUE_SYMBOL,
        "symbol": SYMBOL,
        "channels": effective_channels,
        "duration_seconds": effective_duration,
        "max_messages": effective_max_messages,
        "forced_reconnect_after_messages": effective_forced_reconnect_after_messages,
        "network_called": False,
        "websocket_client_initialized": False,
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_calls_used": False,
        "planned_subscription": subscription,
    }
    if not execute_network:
        payload = {
            **base_payload,
            "status": "dry_run",
            "completed": False,
            "message_count": 0,
            "data_message_count": 0,
            "channel_counts": {},
            "files": [],
            "errors": [],
            "blockers": blockers,
        }
        _write_json_atomic(payload, report_path)
        return payload

    if not selected_bundle.exists():
        blockers.append("btc_okx_selected_bundle_dir_missing")
    if blockers:
        payload = {
            **base_payload,
            "status": "rejected",
            "network_called": False,
            "completed": False,
            "message_count": 0,
            "data_message_count": 0,
            "channel_counts": {},
            "files": [],
            "errors": [],
            "blockers": blockers,
        }
        _write_json_atomic(payload, report_path)
        return payload

    assert_no_okx_credentials_in_env()
    try:
        ws_module = _load_websocket_module()
    except Exception as exc:  # noqa: BLE001 - dependency failure becomes fail-closed evidence.
        dependency_blockers = ["btc_okx_websocket_client_dependency_unavailable"]
        if isinstance(exc, ModuleNotFoundError):
            dependency_blockers.append("btc_okx_websocket_client_dependency_missing")
        return _write_pre_network_rejection(
            base_payload=base_payload,
            report_path=report_path,
            blockers=blockers + dependency_blockers,
            error_role="websocket_client_dependency",
            error=exc,
        )
    runtime_identity = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "websocket_client_module": str(
            getattr(ws_module, "__name__", "websocket")
        ),
        "websocket_client_version": str(
            getattr(ws_module, "__version__", "unknown")
        ),
    }
    base_payload["runtime_identity"] = runtime_identity
    try:
        connection = _initialize_websocket_client(ws_module, effective_timeout)
    except Exception as exc:  # noqa: BLE001 - client init failure becomes fail-closed evidence.
        return _write_pre_network_rejection(
            base_payload=base_payload,
            report_path=report_path,
            blockers=blockers + ["btc_okx_public_ws_client_initialization_failed"],
            error_role="websocket_client_initialization",
            error=exc,
        )
    raw_path = selected_bundle / RAW_WS_MESSAGES_FILE
    manifest_path = selected_bundle / RAW_WS_MANIFEST_FILE
    capture_started_at = _utc_z_now_precise()
    capture_started_monotonic_ns = time.monotonic_ns()
    deadline = time.monotonic() + effective_duration
    errors: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    channel_counts: dict[str, int] = {}
    data_message_count = 0
    completed = False
    network_called = False
    connection_connected = False
    connection_count = 0
    forced_reconnect_count = 0
    last_raw_receive_monotonic_ns: int | None = None
    last_receive_monotonic_ns: int | None = None
    monotonic_tiebreak_adjustment_count = 0
    monotonic_tiebreak_max_adjustment_ns = 0
    try:
        message_index = 0
        while time.monotonic() < deadline and message_index < effective_max_messages:
            if connection is None:
                try:
                    connection = _initialize_websocket_client(ws_module, effective_timeout)
                    connection_connected = False
                except Exception as exc:  # noqa: BLE001 - reconnect init evidence.
                    errors.append(
                        {
                            "role": "websocket_client_initialization",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    blockers.append("btc_okx_public_ws_client_initialization_failed")
                    break
            if not connection_connected:
                network_called = True
                connection.connect(effective_public_ws_url)
                connection_connected = True
                connection_count += 1
                connection.send(json.dumps(subscription, separators=(",", ":")))
                last_ping_monotonic = time.monotonic()
            if time.monotonic() - last_ping_monotonic >= 20.0:
                connection.send("ping")
                last_ping_monotonic = time.monotonic()
            try:
                raw = connection.recv()
            except Exception as exc:  # noqa: BLE001 - timeout or connection evidence.
                errors.append(_error_record("recv", exc))
                break
            raw_receive_monotonic_ns = time.monotonic_ns()
            if (
                last_raw_receive_monotonic_ns is not None
                and raw_receive_monotonic_ns < last_raw_receive_monotonic_ns
            ):
                blockers.append("btc_okx_public_ws_l2_monotonic_clock_rollback")
            receive_monotonic_ns = (
                raw_receive_monotonic_ns
                if last_receive_monotonic_ns is None
                else max(
                    raw_receive_monotonic_ns,
                    last_receive_monotonic_ns + 1,
                )
            )
            monotonic_tiebreak_ns = (
                receive_monotonic_ns - raw_receive_monotonic_ns
            )
            if monotonic_tiebreak_ns > 0:
                monotonic_tiebreak_adjustment_count += 1
                monotonic_tiebreak_max_adjustment_ns = max(
                    monotonic_tiebreak_max_adjustment_ns,
                    monotonic_tiebreak_ns,
                )
            last_raw_receive_monotonic_ns = raw_receive_monotonic_ns
            last_receive_monotonic_ns = receive_monotonic_ns
            local_receive_ts = _utc_z_now_precise()
            message_index += 1
            parsed = _parse_ws_message(raw)
            channel = str(_mapping(parsed.get("arg")).get("channel", "event") or "event")
            if isinstance(parsed.get("data"), list):
                data_message_count += 1
                channel_counts[channel] = channel_counts.get(channel, 0) + 1
            rows.append(
                {
                    "capture_sequence": message_index,
                    "connection_sequence": connection_count,
                    "local_receive_ts": local_receive_ts,
                    "monotonic_ns": receive_monotonic_ns,
                    "raw_monotonic_ns": raw_receive_monotonic_ns,
                    "monotonic_tiebreak_ns": monotonic_tiebreak_ns,
                    "channel": channel,
                    "instId": str(_mapping(parsed.get("arg")).get("instId", VENUE_SYMBOL) or VENUE_SYMBOL),
                    "event": parsed.get("event"),
                    "action": parsed.get("action"),
                    "raw": raw,
                }
            )
            if (
                effective_forced_reconnect_after_messages > 0
                and message_index % effective_forced_reconnect_after_messages == 0
                and message_index < effective_max_messages
                and time.monotonic() < deadline
            ):
                forced_reconnect_count += 1
                try:
                    connection.close()
                except Exception as exc:  # noqa: BLE001 - close evidence only.
                    errors.append({"role": "forced_reconnect_close", "error": repr(exc)})
                connection = None
                connection_connected = False
        completed = time.monotonic() >= deadline or message_index >= effective_max_messages
    except Exception as exc:  # noqa: BLE001 - persisted as evidence.
        errors.append(_error_record("connection", exc))
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception as exc:  # noqa: BLE001 - close evidence only.
                errors.append({"role": "close", "error": repr(exc)})
    capture_ended_monotonic_ns = time.monotonic_ns()
    capture_ended_at = _utc_z_now_precise()
    if rows:
        capture_started_at = str(rows[0]["local_receive_ts"])
        capture_started_monotonic_ns = int(rows[0]["monotonic_ns"])
        capture_ended_at = str(rows[-1]["local_receive_ts"])
        capture_ended_monotonic_ns = int(rows[-1]["monotonic_ns"])
    if not rows:
        blockers.append("btc_okx_public_ws_l2_no_messages_captured")
    if data_message_count <= 0:
        blockers.append("btc_okx_public_ws_l2_no_data_messages_captured")
    for channel in effective_channels:
        if channel_counts.get(channel, 0) <= 0:
            blockers.append(f"btc_okx_public_ws_l2_channel_{channel}_missing_data")
    if errors and not rows:
        blockers.append("btc_okx_public_ws_l2_capture_failed")
    if errors:
        blockers.append("btc_okx_public_ws_l2_capture_errors_present")

    _write_jsonl_atomic(raw_path, rows)
    manifest = _manifest(
        capture_started_at=capture_started_at,
        capture_ended_at=capture_ended_at,
        capture_started_monotonic_ns=capture_started_monotonic_ns,
        capture_ended_monotonic_ns=capture_ended_monotonic_ns,
        channels=effective_channels,
        message_count=len(rows),
        data_message_count=data_message_count,
        channel_counts=channel_counts,
        errors=errors,
        connection_count=connection_count,
        forced_reconnect_after_messages=effective_forced_reconnect_after_messages,
        forced_reconnect_count=forced_reconnect_count,
        public_ws_url=effective_public_ws_url,
        collector_commit=str(base_payload["collector_commit"]),
        runtime_identity=runtime_identity,
        monotonic_tiebreak_adjustment_count=(
            monotonic_tiebreak_adjustment_count
        ),
        monotonic_tiebreak_max_adjustment_ns=(
            monotonic_tiebreak_max_adjustment_ns
        ),
    )
    _write_json_atomic(manifest, manifest_path)
    files = [_file_facts(raw_path, root), _file_facts(manifest_path, root)]
    payload = {
        **base_payload,
        "status": "verified_preflight" if not blockers else "partial",
        "network_called": network_called,
        "websocket_client_initialized": True,
        "completed": completed,
        "message_count": len(rows),
        "data_message_count": data_message_count,
        "channel_counts": channel_counts,
        "connection_count": connection_count,
        "forced_reconnect_count": forced_reconnect_count,
        "files": files,
        "manifest": manifest,
        "errors": errors,
        "blockers": _dedupe(blockers),
    }
    _write_json_atomic(payload, report_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bundle-dir", default="")
    parser.add_argument("--capture-report", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--max-messages", type=int, default=2_000)
    parser.add_argument("--channels", default="trades,books")
    parser.add_argument("--recv-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--forced-reconnect-after-messages", type=int, default=0)
    parser.add_argument("--public-ws-url", default=PUBLIC_WS_URL)
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()
    payload = capture_okx_public_ws_l2_raw_data(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        bundle_dir=Path(args.bundle_dir) if args.bundle_dir else None,
        capture_report_path=Path(args.capture_report),
        execute_network=bool(args.execute_network),
        duration_seconds=args.duration_seconds,
        max_messages=args.max_messages,
        channels=_split_channels(args.channels),
        recv_timeout_seconds=args.recv_timeout_seconds,
        forced_reconnect_after_messages=args.forced_reconnect_after_messages,
        public_ws_url=args.public_ws_url,
        captured_at=args.captured_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {"verified_preflight", "partial", "dry_run"}:
        raise SystemExit(2)


def _validate_channels(channels: list[str]) -> list[str]:
    out: list[str] = []
    for channel in channels:
        clean = channel.strip()
        if not clean:
            continue
        if clean in DISALLOWED_PUBLIC_WS_CHANNELS:
            raise ValueError(f"OKX WS channel requires private/login/VIP or is not market data: {clean}")
        if clean not in ALLOWED_PUBLIC_WS_CHANNELS:
            raise ValueError(f"OKX WS channel is not in the public market-data allowlist: {clean}")
        if clean not in out:
            out.append(clean)
    if not out:
        raise ValueError("At least one public WS channel is required")
    return out


def _validate_public_ws_url(value: str) -> str:
    clean = str(value).strip()
    if clean not in OKX_L2_PUBLIC_WS_URLS:
        raise ValueError(
            "OKX public WS URL is not in the production public-market allowlist"
        )
    return clean


def _positive_finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}_must_be_positive_finite_number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field}_must_be_positive_finite_number")
    return number


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field}_must_be_positive_integer")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field}_must_be_nonnegative_integer")
    return value


def _split_channels(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_ws_message(raw: object) -> dict[str, Any]:
    if raw == "pong":
        return {"event": "pong"}
    if not isinstance(raw, str):
        return {"event": "non_text", "raw_type": type(raw).__name__}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"event": "unparsed_text"}
    return dict(parsed) if isinstance(parsed, Mapping) else {"event": "non_object_json"}


def _manifest(
    *,
    capture_started_at: str,
    capture_ended_at: str,
    capture_started_monotonic_ns: int,
    capture_ended_monotonic_ns: int,
    channels: list[str],
    message_count: int,
    data_message_count: int,
    channel_counts: Mapping[str, int],
    errors: list[Mapping[str, str]],
    connection_count: int,
    forced_reconnect_after_messages: int,
    forced_reconnect_count: int,
    public_ws_url: str,
    collector_commit: str,
    runtime_identity: Mapping[str, str],
    monotonic_tiebreak_adjustment_count: int,
    monotonic_tiebreak_max_adjustment_ns: int,
) -> dict[str, Any]:
    duration_seconds = max(0.0, (capture_ended_monotonic_ns - capture_started_monotonic_ns) / 1_000_000_000.0)
    return {
        "schema_version": OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
        "data_version": f"okx_public_ws_l2_raw_preflight_{capture_started_at.replace(':', '').replace('-', '')}",
        "capture_start": capture_started_at,
        "capture_end": capture_ended_at,
        "capture_duration_seconds": duration_seconds,
        "capture_started_monotonic_ns": capture_started_monotonic_ns,
        "capture_ended_monotonic_ns": capture_ended_monotonic_ns,
        "public_ws_url": public_ws_url,
        "source_endpoint_category": "okx_public_market_data_websocket",
        "collector_commit": collector_commit,
        "runtime_identity": dict(runtime_identity),
        "venue": "okx",
        "venue_symbol": VENUE_SYMBOL,
        "symbol": SYMBOL,
        "public_channels": channels,
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_calls_used": False,
        "clock_source": (
            "system_utc_and_python_monotonic_ns_with_capture_sequence_tiebreaker"
        ),
        "required_time_bases": ["local_receive_ts", "monotonic_ns", "exchange_ts_when_present"],
        "raw_monotonic_ns_preserved": True,
        "monotonic_ordering_policy": (
            "max(raw_monotonic_ns,previous_monotonic_ns_plus_1)"
        ),
        "monotonic_tiebreak_adjustment_count": (
            monotonic_tiebreak_adjustment_count
        ),
        "monotonic_tiebreak_max_adjustment_ns": (
            monotonic_tiebreak_max_adjustment_ns
        ),
        "heartbeat_policy": "send_text_ping_after_20s_idle_capture_records_pong_events",
        "checksum_or_sequence_policy": "raw_ws_capture_before_order_book_replay_sequence_validation",
        "message_count": message_count,
        "data_message_count": data_message_count,
        "channel_counts": dict(channel_counts),
        "connection_count": connection_count,
        "forced_reconnect_after_messages": forced_reconnect_after_messages,
        "forced_reconnect_count": forced_reconnect_count,
        "error_count": len(errors),
        "gap_count": forced_reconnect_count,
    }


def _write_jsonl_atomic(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True))
            handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(path)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_websocket_module() -> Any:
    import websocket  # type: ignore[import-not-found]

    return websocket


def _initialize_websocket_client(ws_module: Any, timeout: float) -> Any:
    client = ws_module.WebSocket()
    client.settimeout(timeout)
    return client


def _write_pre_network_rejection(
    *,
    base_payload: Mapping[str, Any],
    report_path: Path,
    blockers: list[str],
    error_role: str,
    error: Exception,
) -> dict[str, Any]:
    payload = {
        **base_payload,
        "status": "rejected",
        "network_called": False,
        "websocket_client_initialized": False,
        "completed": False,
        "message_count": 0,
        "data_message_count": 0,
        "channel_counts": {},
        "connection_count": 0,
        "forced_reconnect_count": 0,
        "files": [],
        "errors": [
            {
                "role": error_role,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        ],
        "blockers": _dedupe(blockers),
    }
    _write_json_atomic(payload, report_path)
    return payload


def _error_record(role: str, error: Exception) -> dict[str, Any]:
    record: dict[str, Any] = {
        "role": role,
        "error_type": type(error).__name__,
        "error": str(error)[:500],
    }
    winerror = getattr(error, "winerror", None)
    if isinstance(winerror, int):
        record["winerror"] = winerror
    return record


def _git_head(root: Path) -> str:
    for candidate in (root, Path(__file__).resolve().parents[1]):
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=candidate,
            capture_output=True,
            text=True,
            check=False,
        )
        value = completed.stdout.strip()
        if completed.returncode == 0 and len(value) == 40:
            return value
    raise RuntimeError("btc_okx_public_ws_collector_git_head_unavailable")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
