from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import sleep, time
from typing import Any, Mapping, Sequence

from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_exchange_public_runtime_dry_probe_v2"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_public_runtime_dry_probe_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_public_runtime_dry_probe_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_public_runtime_dry_probe_safety_status.json"
DEFAULT_RAW_DIR_NAME = "okx_public_runtime_dry_probe_raw"
DEFAULT_PUBLIC_WS_COVERAGE_PATH = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json"
)

DEFAULT_INSTRUMENT_ID = "BTC-USDT-SWAP"
DEFAULT_INDEX_ID = "BTC-USDT"
DEFAULT_MAX_ABS_OFFSET_MS = 2_000.0
DEFAULT_MAX_ROUND_TRIP_MS = 8_000.0
DEFAULT_RETRY_COUNT = 1
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25

REQUEST_PLAN: tuple[dict[str, Any], ...] = (
    {"check_id": "server_time", "name": "server_time", "params": {}, "requires_data": False},
    {"check_id": "symbol_rules", "name": "instruments", "params": {"instType": "SWAP", "instId": DEFAULT_INSTRUMENT_ID}},
    {"check_id": "funding", "name": "funding_rate", "params": {"instId": DEFAULT_INSTRUMENT_ID}},
    {"check_id": "mark_price", "name": "mark_price_candles", "params": {"instId": DEFAULT_INSTRUMENT_ID, "bar": "1m", "limit": "1"}},
    {"check_id": "index_price", "name": "index_candles", "params": {"instId": DEFAULT_INDEX_ID, "bar": "1m", "limit": "1"}},
    {"check_id": "public_depth", "name": "books", "params": {"instId": DEFAULT_INSTRUMENT_ID, "sz": "5"}},
    {"check_id": "open_interest", "name": "open_interest", "params": {"instType": "SWAP", "instId": DEFAULT_INSTRUMENT_ID}},
)


def build_btc_exchange_public_runtime_dry_probe(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    public_ws_coverage_path: Path = DEFAULT_PUBLIC_WS_COVERAGE_PATH,
    execute_network: bool = True,
    generated_at_utc: datetime | None = None,
    collector_factory: type[OkxSwapPublicCollector] = OkxSwapPublicCollector,
    request_retry_count: int = DEFAULT_RETRY_COUNT,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    max_abs_offset_ms: float = DEFAULT_MAX_ABS_OFFSET_MS,
    max_round_trip_ms: float = DEFAULT_MAX_ROUND_TRIP_MS,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / DEFAULT_RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))

    coverage = _read_json(_resolve(root, public_ws_coverage_path))
    planned = _planned_requests(collector_factory)
    captures: list[dict[str, Any]] = []
    capture_errors: list[dict[str, Any]] = []
    raw_files: list[dict[str, Any]] = []

    if execute_network:
        collector = collector_factory(dry_run=False, allow_network=True)
        for request_plan in REQUEST_PLAN:
            capture = _capture_public_request(
                collector=collector,
                request_plan=request_plan,
                retry_count=max(0, int(request_retry_count)),
                retry_backoff=max(0.0, float(retry_backoff_seconds)),
                capture_errors=capture_errors,
            )
            captures.append(capture)
            if capture.get("payload"):
                raw_path = raw_dir / f"{request_plan['check_id']}_raw.json"
                _write_json(raw_path, _mapping(capture.get("payload")))
                raw_files.append(
                    {
                        "check_id": request_plan["check_id"],
                        "path": _portable_path(raw_path),
                        "sha256": _sha256(raw_path),
                        "size_bytes": raw_path.stat().st_size,
                    }
                )
    else:
        capture_errors.append(
            {
                "check_id": "public_runtime_dry_probe",
                "error_type": "network_not_executed",
                "message": "public REST dry probe was run without network execution",
            }
        )

    check_results = _check_results(
        captures=captures,
        execute_network=execute_network,
        max_abs_offset_ms=max_abs_offset_ms,
        max_round_trip_ms=max_round_trip_ms,
    )
    normalized_market_metadata = _normalized_okx_swap_market_metadata(captures, execute_network=execute_network)
    ws_runtime = _public_ws_runtime_state(coverage)
    blockers = _blockers(
        check_results=check_results,
        ws_runtime=ws_runtime,
        capture_errors=capture_errors,
        normalized_market_metadata=normalized_market_metadata,
    )
    warnings = _warnings(blockers=blockers, ws_runtime=ws_runtime, capture_errors=capture_errors)
    status = "verified_research_only" if not blockers else "incomplete_research_only"
    report_path = output / DEFAULT_REPORT_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": status,
        "decision": (
            "btc_exchange_public_runtime_dry_probe_verified_no_order_no_private"
            if not blockers
            else "btc_exchange_public_runtime_dry_probe_incomplete_fail_closed_no_paper_no_live"
        ),
        "scope": "okx_public_rest_ws_runtime_dry_probe_no_private_no_order",
        "code_commit": _git_commit(),
        "venue": "OKX",
        "instrument_id": DEFAULT_INSTRUMENT_ID,
        "public_rest_only": True,
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "network_called": bool(execute_network),
        "planned_requests": planned,
        "capture_summaries": [_capture_summary(row) for row in captures],
        "capture_errors": capture_errors,
        "raw_response_files": raw_files,
        "checks": check_results,
        "normalized_market_metadata_contract": normalized_market_metadata,
        "third_party_reference_adaptation": {
            "ccxt": {
                "license": "MIT",
                "local_reference_path": _portable_path(root.parent / "external_references" / "ccxt"),
                "adapted_concepts": ["unified_exchange_id", "market_metadata", "precision_limits", "rate_limit_budget"],
                "adapted_public_fields": [
                    "instId",
                    "instType",
                    "baseCcy",
                    "quoteCcy",
                    "settleCcy",
                    "ctVal",
                    "ctValCcy",
                    "tickSz",
                    "lotSz",
                    "minSz",
                    "state",
                ],
                "source_code_copied": False,
                "copied_source_paths": [],
                "copy_allowed_after_provenance_review": True,
                "source_copy_decision": "do_not_copy_large_exchange_parser_keep_small_local_field_mapping",
            },
            "hummingbot": {
                "license": "Apache-2.0",
                "local_reference_path": _portable_path(root.parent / "external_references" / "hummingbot"),
                "adapted_concepts": ["connector_type", "rest_ws_connector_boundary", "perpetual_market_metadata"],
                "adapted_public_fields": [
                    "connector_family",
                    "public_rest_only",
                    "public_ws_only",
                    "private_endpoint_used",
                    "order_endpoint_used",
                ],
                "source_code_copied": False,
                "copied_source_paths": [],
                "copy_allowed_after_provenance_review": True,
                "source_copy_decision": "do_not_copy_connector_runtime_keep_no_order_public_boundary_contract",
            },
            "copy_decision_note": "MIT/Apache allow selective copying after provenance review, but the useful wheel here is the normalized public metadata contract; copying full exchange parsers would add unrelated markets, dependencies, and private/order surfaces.",
            "private_or_order_endpoint_imported": False,
        },
        "public_ws_runtime_state": ws_runtime,
        "runtime_layer": {
            "layer_id": "public_runtime_dry_probe",
            "status": "passed" if not blockers else "blocked",
            "server_time_verified": _check_passed(check_results, "server_time"),
            "symbol_rules_visible": _check_passed(check_results, "symbol_rules"),
            "normalized_market_metadata_visible": bool(normalized_market_metadata.get("contract_valid")),
            "tick_size_visible": bool(normalized_market_metadata.get("tick_size")),
            "lot_size_visible": bool(normalized_market_metadata.get("lot_size")),
            "min_size_visible": bool(normalized_market_metadata.get("min_order_size")),
            "contract_value_visible": bool(normalized_market_metadata.get("contract_value")),
            "mark_price_available": _check_passed(check_results, "mark_price"),
            "index_price_available": _check_passed(check_results, "index_price"),
            "funding_available": _check_passed(check_results, "funding"),
            "public_depth_available": _check_passed(check_results, "public_depth"),
            "open_interest_available": _check_passed(check_results, "open_interest"),
            "public_ws_replay_verified": bool(ws_runtime.get("public_ws_replay_verified")),
            "public_ws_resync_policy_verified": bool(ws_runtime.get("public_ws_resync_policy_verified")),
            "paper_gate_eligible": False,
            "meaning": "Verifies current public REST plus public WS replay health only; it cannot prove private paper fills.",
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "warnings": warnings,
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_exchange_public_runtime_dry_probe_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_exchange_public_runtime_dry_probe_markdown(report: Mapping[str, Any]) -> str:
    layer = _mapping(report.get("runtime_layer"))
    ws = _mapping(report.get("public_ws_runtime_state"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC Public Runtime Dry Probe",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- public REST 已执行：`{report.get('network_called')}`",
        f"- server time：`{layer.get('server_time_verified')}`",
        f"- symbol rules：`{layer.get('symbol_rules_visible')}`",
        f"- normalized metadata：`{layer.get('normalized_market_metadata_visible')}`",
        f"- mark/index/funding：`{layer.get('mark_price_available')}` / `{layer.get('index_price_available')}` / `{layer.get('funding_available')}`",
        f"- public WS replay/resync：`{ws.get('public_ws_replay_verified')}` / `{ws.get('public_ws_resync_policy_verified')}`",
        f"- paper gate eligible：`{layer.get('paper_gate_eligible')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "边界：本报告只验证 OKX public REST/WS dry runtime 层，不访问 private/account/order endpoint，不写 paper 队列，不解锁 live。",
    ]
    blockers = [str(item) for item in report.get("blockers", []) if str(item)]
    if blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{item}`" for item in blockers)
    return "\n".join(lines) + "\n"


def _planned_requests(collector_factory: type[OkxSwapPublicCollector]) -> list[dict[str, Any]]:
    collector = collector_factory(dry_run=True, allow_network=False)
    rows = []
    for item in REQUEST_PLAN:
        planned = collector.request_by_name(str(item["name"]), _mapping(item.get("params")))
        rows.append(
            {
                "check_id": item["check_id"],
                "endpoint_name": item["name"],
                "params": dict(_mapping(item.get("params"))),
                "url": planned.get("url"),
                "network_called": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
            }
        )
    return rows


def _capture_public_request(
    *,
    collector: OkxSwapPublicCollector,
    request_plan: Mapping[str, Any],
    retry_count: int,
    retry_backoff: float,
    capture_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    name = str(request_plan["name"])
    check_id = str(request_plan["check_id"])
    params = _mapping(request_plan.get("params"))
    for attempt in range(1, retry_count + 2):
        local_send_ms = time() * 1000.0
        try:
            capture = collector.request_by_name(name, params)
            local_receive_ms = time() * 1000.0
            capture["check_id"] = check_id
            capture["endpoint_name"] = name
            capture["retry_attempt"] = attempt
            capture["local_send_ms"] = local_send_ms
            capture["local_receive_ms"] = local_receive_ms
            return capture
        except Exception as exc:  # pragma: no cover - public network defensive boundary
            local_receive_ms = time() * 1000.0
            capture_errors.append(
                {
                    "check_id": check_id,
                    "retry_attempt": attempt,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:240],
                    "duration_ms": round(local_receive_ms - local_send_ms, 3),
                }
            )
            if attempt <= retry_count and retry_backoff > 0:
                sleep(retry_backoff * attempt)
    return {
        "check_id": check_id,
        "endpoint_name": name,
        "params": dict(params),
        "network_called": False,
        "payload": {},
    }


def _check_results(
    *,
    captures: Sequence[Mapping[str, Any]],
    execute_network: bool,
    max_abs_offset_ms: float,
    max_round_trip_ms: float,
) -> list[dict[str, Any]]:
    by_check = {str(row.get("check_id")): row for row in captures}
    rows: list[dict[str, Any]] = []
    for item in REQUEST_PLAN:
        check_id = str(item["check_id"])
        capture = by_check.get(check_id, {})
        payload = _mapping(capture.get("payload"))
        data = payload.get("data")
        response_code_ok = payload.get("code") == "0"
        data_available = isinstance(data, list) and bool(data)
        blockers: list[str] = []
        if not execute_network:
            blockers.append(f"btc_public_runtime_dry_probe_{check_id}_network_not_executed")
        if execute_network and not bool(capture.get("network_called")):
            blockers.append(f"btc_public_runtime_dry_probe_{check_id}_network_failed")
        if execute_network and not response_code_ok:
            blockers.append(f"btc_public_runtime_dry_probe_{check_id}_response_not_ok")
        if bool(item.get("requires_data", True)) and execute_network and not data_available:
            blockers.append(f"btc_public_runtime_dry_probe_{check_id}_data_missing")
        metrics = _server_time_metrics(capture) if check_id == "server_time" else {}
        if check_id == "server_time" and execute_network:
            if metrics.get("server_ts_ms") is None:
                blockers.append("btc_public_runtime_dry_probe_server_time_timestamp_missing")
            if _float_or_none(metrics.get("abs_offset_ms")) is None:
                blockers.append("btc_public_runtime_dry_probe_server_time_offset_missing")
            elif float(metrics["abs_offset_ms"]) > float(max_abs_offset_ms):
                blockers.append("btc_public_runtime_dry_probe_server_time_offset_exceeds_threshold")
            if _float_or_none(metrics.get("round_trip_ms")) is None:
                blockers.append("btc_public_runtime_dry_probe_server_time_round_trip_missing")
            elif float(metrics["round_trip_ms"]) > float(max_round_trip_ms):
                blockers.append("btc_public_runtime_dry_probe_server_time_round_trip_exceeds_threshold")
        rows.append(
            {
                "check_id": check_id,
                "endpoint_name": item["name"],
                "network_called": bool(capture.get("network_called")),
                "response_code": payload.get("code"),
                "response_code_ok": response_code_ok,
                "data_available": data_available,
                "row_count": len(data) if isinstance(data, list) else 0,
                "server_time_metrics": metrics,
                "passed": not blockers,
                "blockers": blockers,
            }
        )
    return rows


def _normalized_okx_swap_market_metadata(
    captures: Sequence[Mapping[str, Any]], *, execute_network: bool
) -> dict[str, Any]:
    symbol_capture = next((row for row in captures if row.get("check_id") == "symbol_rules"), {})
    payload = _mapping(symbol_capture.get("payload"))
    data = payload.get("data")
    first = _mapping(data[0]) if isinstance(data, list) and data else {}
    field_map = {
        "exchange_id": "okx",
        "venue": "OKX",
        "connector_family": "clob_cex_perpetual_public",
        "instrument_id": str(first.get("instId") or DEFAULT_INSTRUMENT_ID),
        "instrument_type": str(first.get("instType") or "SWAP"),
        "base_currency": str(first.get("baseCcy") or "BTC"),
        "quote_currency": str(first.get("quoteCcy") or "USDT"),
        "settle_currency": str(first.get("settleCcy") or ""),
        "contract_type": str(first.get("ctType") or ""),
        "contract_value": _float_or_none(first.get("ctVal")),
        "contract_value_currency": str(first.get("ctValCcy") or ""),
        "contract_multiplier": _float_or_none(first.get("ctMult")),
        "tick_size": _float_or_none(first.get("tickSz")),
        "lot_size": _float_or_none(first.get("lotSz")),
        "min_order_size": _float_or_none(first.get("minSz")),
        "max_limit_size": _float_or_none(first.get("maxLmtSz")),
        "max_market_size": _float_or_none(first.get("maxMktSz")),
        "state": str(first.get("state") or ""),
        "metadata_version": f"okx:{first.get('instId') or DEFAULT_INSTRUMENT_ID}:{first.get('instType') or 'SWAP'}",
        "public_rest_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "source_check_id": "symbol_rules",
        "source_endpoint": symbol_capture.get("endpoint"),
        "network_called": bool(symbol_capture.get("network_called")),
        "adapted_from_external_reference_style": "CCXT market metadata and Hummingbot connector boundary concepts",
        "third_party_source_code_copied": False,
    }
    required = [
        "instrument_id",
        "instrument_type",
        "settle_currency",
        "contract_value",
        "tick_size",
        "lot_size",
        "min_order_size",
        "state",
    ]
    missing = [
        key
        for key in required
        if field_map.get(key) in {"", None} or (isinstance(field_map.get(key), float) and field_map.get(key) <= 0.0)
    ]
    if not execute_network:
        missing.append("network_not_executed")
    return {
        **field_map,
        "required_fields": required,
        "missing_required_fields": sorted(set(missing)),
        "contract_valid": not missing,
        "paper_gate_eligible": False,
        "meaning": "Unified public market metadata only; does not authorize private or order endpoints.",
    }


def _server_time_metrics(capture: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(capture.get("payload"))
    data = payload.get("data")
    first = _mapping(data[0]) if isinstance(data, list) and data else {}
    server_ts_ms = _float_or_none(first.get("ts"))
    local_send_ms = _float_or_none(capture.get("local_send_ms"))
    local_receive_ms = _float_or_none(capture.get("local_receive_ms"))
    if server_ts_ms is None or local_send_ms is None or local_receive_ms is None:
        return {
            "server_ts_ms": server_ts_ms,
            "round_trip_ms": None,
            "offset_ms": None,
            "abs_offset_ms": None,
        }
    midpoint = (local_send_ms + local_receive_ms) / 2.0
    offset = server_ts_ms - midpoint
    return {
        "server_ts_ms": round(server_ts_ms, 3),
        "round_trip_ms": round(local_receive_ms - local_send_ms, 3),
        "offset_ms": round(offset, 3),
        "abs_offset_ms": round(abs(offset), 3),
    }


def _public_ws_runtime_state(coverage: Mapping[str, Any]) -> dict[str, Any]:
    validation = _mapping(coverage.get("validation"))
    totals = _mapping(coverage.get("coverage_totals"))
    verified_sessions = _int(totals.get("verified_public_session_count"))
    replay_ready = bool(validation.get("all_verified_sessions_have_replay_sequence_ready"))
    resync_ready = bool(validation.get("resync_policy_exercised"))
    required_channels = bool(validation.get("required_channels_observed"))
    return {
        "source_report_present": bool(coverage),
        "source_status": coverage.get("status"),
        "verified_public_session_count": verified_sessions,
        "public_ws_replay_verified": replay_ready and verified_sessions > 0,
        "public_ws_resync_policy_verified": resync_ready and verified_sessions > 0,
        "required_channels_observed": required_channels,
        "coverage_contract_satisfied": bool(coverage.get("coverage_contract_satisfied") or validation.get("coverage_contract_satisfied")),
        "history_days_satisfied": bool(validation.get("minimum_event_ledger_history_days_satisfied")),
        "calendar_span_satisfied": bool(validation.get("minimum_calendar_span_days_satisfied")),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "paper_gate_eligible": False,
        "meaning": "Public WS replay health is runtime plumbing evidence; long history coverage remains a separate data gate.",
    }


def _blockers(
    *,
    check_results: Sequence[Mapping[str, Any]],
    ws_runtime: Mapping[str, Any],
    capture_errors: Sequence[Mapping[str, Any]],
    normalized_market_metadata: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for row in check_results:
        blockers.extend(str(item) for item in row.get("blockers", []) if str(item))
    if not ws_runtime.get("source_report_present"):
        blockers.append("btc_public_runtime_dry_probe_public_ws_coverage_missing")
    if ws_runtime.get("public_ws_replay_verified") is not True:
        blockers.append("btc_public_runtime_dry_probe_public_ws_replay_not_verified")
    if ws_runtime.get("public_ws_resync_policy_verified") is not True:
        blockers.append("btc_public_runtime_dry_probe_public_ws_resync_not_verified")
    if ws_runtime.get("required_channels_observed") is not True:
        blockers.append("btc_public_runtime_dry_probe_public_ws_required_channels_missing")
    for field_name in normalized_market_metadata.get("missing_required_fields", []):
        blockers.append(f"btc_public_runtime_dry_probe_market_metadata_missing:{field_name}")
    for error in capture_errors:
        check_id = str(error.get("check_id") or "unknown")
        blockers.append(f"btc_public_runtime_dry_probe_capture_error:{check_id}:{error.get('error_type')}")
    return sorted(set(blockers))


def _warnings(
    *,
    blockers: Sequence[str],
    ws_runtime: Mapping[str, Any],
    capture_errors: Sequence[Mapping[str, Any]],
) -> list[str]:
    warnings = ["btc_public_runtime_dry_probe_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_public_runtime_dry_probe_incomplete_fail_closed")
    if capture_errors:
        warnings.append("btc_public_runtime_dry_probe_retry_or_capture_error_seen")
    if ws_runtime.get("coverage_contract_satisfied") is not True:
        warnings.append("public_ws_runtime_seen_but_long_history_coverage_gate_still_pending")
    return warnings


def _capture_summary(capture: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(capture.get("payload"))
    data = payload.get("data")
    return {
        "check_id": capture.get("check_id"),
        "endpoint_name": capture.get("endpoint_name"),
        "endpoint": capture.get("endpoint"),
        "url": capture.get("url"),
        "network_called": bool(capture.get("network_called")),
        "duration_ms": capture.get("duration_ms"),
        "response_code": payload.get("code"),
        "message": payload.get("msg"),
        "row_count": len(data) if isinstance(data, list) else 0,
    }


def _check_passed(check_results: Sequence[Mapping[str, Any]], check_id: str) -> bool:
    for row in check_results:
        if row.get("check_id") == check_id:
            return row.get("passed") is True
    return False


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "public_rest_only": True,
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_exchange_public_runtime_dry_probe_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "public_rest_only": True,
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
