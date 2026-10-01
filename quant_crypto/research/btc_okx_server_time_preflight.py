from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import sleep, time
from typing import Any, Mapping

try:
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector, PUBLIC_ENDPOINTS
except ModuleNotFoundError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector, PUBLIC_ENDPOINTS


SCHEMA_VERSION = "btc_okx_server_time_preflight_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_okx_server_time_preflight_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "btc_okx_server_time_preflight_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_okx_server_time_preflight_safety_status.json"
DEFAULT_RAW_DIR_NAME = "okx_server_time_raw"
DEFAULT_MAX_ABS_OFFSET_MS = 2_000.0
DEFAULT_MAX_ROUND_TRIP_MS = 5_000.0
DEFAULT_REQUEST_RETRY_COUNT = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25


def build_btc_okx_server_time_preflight_report(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    execute_network: bool = False,
    generated_at_utc: datetime | None = None,
    max_abs_offset_ms: float = DEFAULT_MAX_ABS_OFFSET_MS,
    max_round_trip_ms: float = DEFAULT_MAX_ROUND_TRIP_MS,
    sample_count: int = 5,
    request_retry_count: int = DEFAULT_REQUEST_RETRY_COUNT,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    collector_factory: type[OkxSwapPublicCollector] = OkxSwapPublicCollector,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    output = output_dir if output_dir.is_absolute() else root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / DEFAULT_RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    generated = generated_at_utc or datetime.now(timezone.utc)

    planned_request = collector_factory(dry_run=True, allow_network=False).request_by_name("server_time", {})
    blockers: list[str] = []
    captures: list[dict[str, Any]] = []
    raw_files: list[dict[str, Any]] = []
    sample_metrics: list[dict[str, Any]] = []
    capture_errors: list[dict[str, Any]] = []
    retry_count = max(0, int(request_retry_count))
    retry_backoff = max(0.0, float(retry_backoff_seconds))
    if execute_network:
        collector = collector_factory(dry_run=False, allow_network=True)
        for sample_index in range(1, max(1, int(sample_count)) + 1):
            capture: dict[str, Any] = {}
            local_send_ms = 0.0
            local_receive_ms = 0.0
            for attempt in range(1, retry_count + 2):
                local_send_ms = time() * 1000.0
                try:
                    capture = collector.request_by_name("server_time", {})
                    local_receive_ms = time() * 1000.0
                    capture["retry_attempt"] = attempt
                    break
                except Exception as exc:  # pragma: no cover - network defensive boundary
                    local_receive_ms = time() * 1000.0
                    capture_errors.append(
                        {
                            "sample_index": sample_index,
                            "retry_attempt": attempt,
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:240],
                        }
                    )
                    if attempt <= retry_count and retry_backoff > 0:
                        sleep(retry_backoff * attempt)
            captures.append(capture)
            if capture:
                raw_path = raw_dir / f"server_time_raw_{sample_index}.json"
                _write_json(raw_path, _mapping(capture.get("payload")))
                raw_files.append(
                    {
                        "sample_index": sample_index,
                        "path": _portable_path(raw_path, root),
                        "sha256": _sha256(raw_path),
                        "size_bytes": raw_path.stat().st_size,
                    }
                )
            sample_metrics.append(
                {
                    "sample_index": sample_index,
                    **_time_metrics(
                        payload=_mapping(capture.get("payload")),
                        local_send_ms=local_send_ms,
                        local_receive_ms=local_receive_ms,
                    ),
                }
            )
    else:
        blockers.append("btc_okx_server_time_network_capture_not_executed")

    payload = _mapping(captures[-1].get("payload")) if captures else {}
    metrics = _select_time_metrics(sample_metrics)
    local_clock_diagnostic = _local_clock_diagnostic()
    validation = _validation(
        metrics=metrics,
        payload=payload,
        execute_network=execute_network,
        max_abs_offset_ms=max_abs_offset_ms,
        max_round_trip_ms=max_round_trip_ms,
        capture_errors=capture_errors,
    )
    blockers.extend(validation["blockers"])
    blockers = sorted(set(blockers))
    verified = not blockers

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "verified_research_only" if verified else ("dry_run" if not execute_network else "incomplete_research_only"),
        "decision": (
            "okx_server_time_offset_verified_research_only_no_paper_no_live"
            if verified
            else "okx_server_time_offset_incomplete_fail_closed_no_paper_no_live"
        ),
        "scope": "btc_okx_public_server_time_offset_preflight_no_order_no_broker",
        "venue": "OKX",
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "network_called": bool(execute_network),
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "planned_request": planned_request,
        "sample_count_requested": max(1, int(sample_count)),
        "retry_policy": {
            "request_retry_count": retry_count,
            "retry_backoff_seconds": retry_backoff,
            "retry_used": bool(capture_errors),
            "capture_error_count": len(capture_errors),
        },
        "capture_summary": _capture_summary(captures[-1] if captures else {}),
        "capture_summaries": [_capture_summary(capture) for capture in captures],
        "capture_errors": capture_errors,
        "raw_response_files": raw_files,
        "validation": validation,
        "local_clock_diagnostic": local_clock_diagnostic,
        "server_time_offset_verified": bool(verified),
        "server_time_metrics": metrics,
        "sample_metrics": sample_metrics,
        "warnings": validation.get("warnings", []),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(output / DEFAULT_REPORT_PATH.name, root),
            "summary_cn": _portable_path(output / DEFAULT_SUMMARY_PATH.name, root),
            "paper_live_safety_status": _portable_path(output / DEFAULT_SAFETY_PATH.name, root),
        },
    }
    _write_json(output / DEFAULT_REPORT_PATH.name, report)
    _write_text(output / DEFAULT_SUMMARY_PATH.name, render_summary_cn(report))
    _write_json(output / DEFAULT_SAFETY_PATH.name, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    metrics = _mapping(report.get("server_time_metrics"))
    validation = _mapping(report.get("validation"))
    lines = [
        "# BTC OKX server time offset 预检",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 公共 REST：`{report.get('public_rest_only')}`",
        f"- 私有/下单接口：`private={report.get('private_endpoint_used')}`，`order={report.get('order_endpoint_used')}`",
        f"- offset ms：`{metrics.get('offset_ms')}`",
        f"- round trip ms：`{metrics.get('round_trip_ms')}`",
        (
            "- offset abs p50/p95/max ms："
            f"`{metrics.get('abs_offset_p50_ms')}` / "
            f"`{metrics.get('abs_offset_p95_ms')}` / "
            f"`{metrics.get('abs_offset_max_ms')}`"
        ),
        (
            "- RTT p50/p95/max ms："
            f"`{metrics.get('round_trip_p50_ms')}` / "
            f"`{metrics.get('round_trip_p95_ms')}` / "
            f"`{metrics.get('round_trip_max_ms')}`"
        ),
        f"- offset 阈值：`{validation.get('max_abs_offset_ms')}`",
        f"- RTT 阈值：`{validation.get('max_round_trip_ms')}`",
        f"- 已验证：`{report.get('server_time_offset_verified')}`",
        "",
        "该报告只验证本机时间与 OKX 公共 server time 的偏移，不写 paper 队列，不接 broker/OMS，不访问 private/order endpoint，不解锁 live。",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(["", "## 阻断项"])
        lines.extend(f"- `{item}`" for item in blockers)
    return "\n".join(lines) + "\n"


def _time_metrics(
    *,
    payload: Mapping[str, Any],
    local_send_ms: float | None,
    local_receive_ms: float | None,
) -> dict[str, Any]:
    server_ts_ms = _server_ts_ms(payload)
    if local_send_ms is None or local_receive_ms is None or server_ts_ms is None:
        return {
            "server_ts_ms": server_ts_ms,
            "local_send_ms": local_send_ms,
            "local_receive_ms": local_receive_ms,
            "round_trip_ms": None,
            "local_midpoint_ms": None,
            "offset_ms": None,
            "abs_offset_ms": None,
        }
    midpoint = (local_send_ms + local_receive_ms) / 2.0
    offset = server_ts_ms - midpoint
    return {
        "server_ts_ms": round(server_ts_ms, 3),
        "local_send_ms": round(local_send_ms, 3),
        "local_receive_ms": round(local_receive_ms, 3),
        "round_trip_ms": round(local_receive_ms - local_send_ms, 3),
        "local_midpoint_ms": round(midpoint, 3),
        "offset_ms": round(offset, 3),
        "abs_offset_ms": round(abs(offset), 3),
    }


def _select_time_metrics(sample_metrics: list[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [
        dict(item)
        for item in sample_metrics
        if _float_or_none(item.get("round_trip_ms")) is not None and _float_or_none(item.get("abs_offset_ms")) is not None
    ]
    if not valid:
        return {
            "selection_method": "no_valid_sample",
            "requested_sample_count": len(sample_metrics),
            "valid_sample_count": 0,
            "server_ts_ms": None,
            "local_send_ms": None,
            "local_receive_ms": None,
            "round_trip_ms": None,
            "local_midpoint_ms": None,
            "offset_ms": None,
            "abs_offset_ms": None,
            "abs_offset_p50_ms": None,
            "abs_offset_p95_ms": None,
            "abs_offset_max_ms": None,
            "round_trip_p50_ms": None,
            "round_trip_p95_ms": None,
            "round_trip_max_ms": None,
        }
    selected = min(valid, key=lambda item: (_float_or_none(item.get("round_trip_ms")) or float("inf"), item.get("sample_index", 0)))
    offsets = sorted(_float_or_none(item.get("abs_offset_ms")) or 0.0 for item in valid)
    round_trips = sorted(
        _float_or_none(item.get("round_trip_ms")) or 0.0 for item in valid
    )
    mid = len(offsets) // 2
    median_abs_offset = offsets[mid] if len(offsets) % 2 else (offsets[mid - 1] + offsets[mid]) / 2.0
    selected["selection_method"] = "minimum_round_trip_sample"
    selected["requested_sample_count"] = len(sample_metrics)
    selected["valid_sample_count"] = len(valid)
    selected["median_abs_offset_ms"] = round(median_abs_offset, 3)
    selected["max_abs_offset_ms_observed"] = round(max(offsets), 3)
    selected["abs_offset_p50_ms"] = round(_percentile(offsets, 50.0), 3)
    selected["abs_offset_p95_ms"] = round(_percentile(offsets, 95.0), 3)
    selected["abs_offset_max_ms"] = round(max(offsets), 3)
    selected["round_trip_p50_ms"] = round(
        _percentile(round_trips, 50.0),
        3,
    )
    selected["round_trip_p95_ms"] = round(
        _percentile(round_trips, 95.0),
        3,
    )
    selected["round_trip_max_ms"] = round(max(round_trips), 3)
    return selected


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile_values_empty")
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * percentile / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _validation(
    *,
    metrics: Mapping[str, Any],
    payload: Mapping[str, Any],
    execute_network: bool,
    max_abs_offset_ms: float,
    max_round_trip_ms: float,
    capture_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    code = payload.get("code")
    offset = _float_or_none(metrics.get("abs_offset_max_ms"))
    round_trip = _float_or_none(metrics.get("round_trip_max_ms"))
    if not execute_network:
        blockers.append("btc_okx_server_time_network_capture_not_executed")
    if capture_errors:
        warnings.append("btc_okx_server_time_retry_used")
    if execute_network and code != "0":
        blockers.append("btc_okx_server_time_response_code_not_ok")
    if execute_network and metrics.get("server_ts_ms") is None:
        blockers.append("btc_okx_server_time_timestamp_missing")
    if offset is None:
        if execute_network:
            blockers.append("btc_okx_server_time_offset_not_calculated")
    elif offset > max_abs_offset_ms:
        blockers.append("btc_okx_server_time_offset_exceeds_threshold")
        warnings.append("local_clock_ntp_check_required_before_paper")
    if round_trip is None:
        if execute_network:
            blockers.append("btc_okx_server_time_round_trip_not_calculated")
    elif round_trip > max_round_trip_ms:
        blockers.append("btc_okx_server_time_round_trip_exceeds_threshold")
    blockers = sorted(set(blockers))
    return {
        "server_time_offset_verified": not blockers,
        "max_abs_offset_ms": float(max_abs_offset_ms),
        "max_round_trip_ms": float(max_round_trip_ms),
        "response_code": code,
        "offset_warning": "local_clock_ntp_check_required_before_paper" if offset is not None and offset > max_abs_offset_ms else "",
        "retry_error_count": len(capture_errors),
        "blockers": blockers,
        "warnings": warnings,
    }


def _local_clock_diagnostic() -> dict[str, Any]:
    commands = (
        ["w32tm", "/query", "/status"],
        ["timedatectl", "show", "--property=NTPSynchronized", "--property=TimeUSec", "--property=NTPSyncUSec"],
    )
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode in (0, 1):
            output = (completed.stdout or completed.stderr or "").strip()
            return {
                "diagnostic_status": "available" if completed.returncode == 0 else "command_returned_warning",
                "command": " ".join(command),
                "returncode": completed.returncode,
                "output_preview": output[:1000],
                "paper_gate_interpretation": "diagnostic_only_human_must_fix_clock_if_offset_exceeds_threshold",
            }
    return {
        "diagnostic_status": "unavailable",
        "command": "",
        "returncode": None,
        "output_preview": "",
        "paper_gate_interpretation": "diagnostic_unavailable_keep_server_time_preflight_fail_closed_if_offset_exceeds_threshold",
    }


def _server_ts_ms(payload: Mapping[str, Any]) -> float | None:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = _mapping(data[0])
    return _float_or_none(first.get("ts"))


def _capture_summary(capture: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(capture.get("payload"))
    return {
        "endpoint": capture.get("endpoint") or PUBLIC_ENDPOINTS["server_time"],
        "url": capture.get("url"),
        "duration_ms": capture.get("duration_ms"),
        "network_called": capture.get("network_called") is True,
        "code": payload.get("code"),
        "message": payload.get("msg"),
    }


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_okx_server_time_preflight_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "server_time_offset_verified": bool(report.get("server_time_offset_verified")),
        "blockers": list(report.get("blockers", [])),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
