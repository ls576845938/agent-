from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_okx_liquidation_snapshot_observer_v1"
SYMBOL = "BTCUSDT"
VENUE_SYMBOL = "BTC-USDT-SWAP"
UNDERLYING = "BTC-USDT"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_liquidation_snapshot_observation/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_okx_liquidation_snapshot_observation_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "btc_okx_liquidation_snapshot_observation_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_DATA_PATH = Path("data/external/btc_perpetual/okx_swap/liquidation_snapshots/okx_liquidation_orders_observe_only.csv")


def run_btc_okx_liquidation_snapshot_observer(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    data_path: Path = DEFAULT_DATA_PATH,
    execute_network: bool = False,
    limit: int = 100,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    data_file = _resolve(root, data_path)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    captured_at = generated.isoformat()
    collector = OkxSwapPublicCollector(dry_run=not execute_network, allow_network=execute_network)
    request_params = {"instType": "SWAP", "uly": UNDERLYING, "state": "filled", "limit": str(max(1, min(100, int(limit))))}

    network_payload: dict[str, Any] = {}
    new_rows: list[dict[str, Any]] = []
    network_error: str | None = None
    response_available_at = captured_at
    if execute_network:
        try:
            response = collector.request_by_name("liquidation_orders", request_params)
            response_available_at = datetime.now(timezone.utc).isoformat()
            network_payload = response.get("payload", {}) if isinstance(response.get("payload"), Mapping) else {}
            new_rows = _flatten_okx_liquidation_payload(network_payload, captured_at=response_available_at)
        except Exception as exc:  # noqa: BLE001 - public data errors are report evidence.
            response_available_at = datetime.now(timezone.utc).isoformat()
            network_error = f"{type(exc).__name__}:{exc}"
    else:
        planned = collector.request_by_name("liquidation_orders", request_params)
        network_payload = {"planned_url": planned.get("url"), "dry_run": True}

    existing_rows = _read_rows(data_file)
    merged_rows = _merge_rows(existing_rows, new_rows)
    if execute_network:
        _write_rows(data_file, merged_rows)

    coverage = _coverage(merged_rows)
    blockers = _blockers(
        execute_network=execute_network,
        network_error=network_error,
        new_rows=new_rows,
        merged_rows=merged_rows,
    )
    report_path = output / DEFAULT_REPORT_PATH.name
    summary_path = output / DEFAULT_SUMMARY_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": _status(execute_network=execute_network, network_error=network_error, merged_rows=merged_rows),
        "decision": "okx_liquidation_snapshots_observe_only_diagnostic_not_gate_evidence_no_paper_no_live",
        "scope": "free_public_okx_liquidation_orders_snapshot_observation_no_order_no_broker",
        "code_commit": _git_commit(),
        "asset": "btc",
        "symbol": SYMBOL,
        "venue_symbol": VENUE_SYMBOL,
        "source": {
            "provider": "okx_public_rest",
            "endpoint": "/api/v5/public/liquidation-orders",
            "params": request_params,
            "free_public_only": True,
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "network_called": bool(execute_network),
            "network_error": network_error,
            "response_available_at": response_available_at,
            "response_code": network_payload.get("code") if isinstance(network_payload, Mapping) else None,
            "response_msg": network_payload.get("msg") if isinstance(network_payload, Mapping) else None,
        },
        "visibility_rule": {
            "event_time_source": "OKX detail ts/time",
            "available_time_source": "local capture generated_at_utc",
            "reason": "historical liquidation rows fetched from public REST are only visible to this system after capture time",
        },
        "data": {
            "path": _portable_path(data_file),
            "existing_row_count_before": len(existing_rows),
            "new_row_count": len(new_rows),
            "merged_row_count": len(merged_rows),
            "coverage": coverage,
        },
        "gate_interpretation": {
            "liquidation_snapshot_available": bool(merged_rows),
            "liquidation_snapshot_gate_eligible": False,
            "complete_liquidation_history_available": False,
            "reason": "OKX public liquidation-orders is a near/recent snapshot observer, not a complete 1h liquidation history archive.",
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "warnings": _warnings(merged_rows),
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(summary_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    data = _mapping(report.get("data"))
    gate = _mapping(report.get("gate"))
    coverage = _mapping(data.get("coverage"))
    lines = [
        "# BTC OKX 强平快照观察",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 新增行数：`{data.get('new_row_count')}`",
        f"- 累计行数：`{data.get('merged_row_count')}`",
        f"- 事件时间范围：`{coverage.get('event_start')}` 到 `{coverage.get('event_end')}`",
        f"- 观察可见时间范围：`{coverage.get('available_start')}` 到 `{coverage.get('available_end')}`",
        f"- 是否可用于 gate：`{_mapping(report.get('gate_interpretation')).get('liquidation_snapshot_gate_eligible')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 解释",
        "",
        "- 本报告只使用 OKX 免费公开 REST `liquidation-orders`。",
        "- `event_time` 是 OKX 记录的强平发生时间，`available_time` 是本系统抓到这批数据的时间。",
        "- 这能积累强平快照诊断，但不能冒充完整 1H 强平历史，也不能解除 paper/live 门禁。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 阻断项"])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _flatten_okx_liquidation_payload(payload: Mapping[str, Any], *, captured_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("data", []) if isinstance(payload.get("data"), list) else []:
        if not isinstance(item, Mapping):
            continue
        details = item.get("details")
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            ts = detail.get("ts") or detail.get("time")
            event_time = _iso_ms(ts)
            available_time = _max_iso(captured_at, event_time)
            price = _float(detail.get("bkPx") or detail.get("price"))
            size = _float(detail.get("sz") or detail.get("size"))
            rows.append(
                {
                    "event_time": event_time,
                    "available_time": available_time,
                    "available_time_source": "max_public_rest_response_time_and_event_time",
                    "ingested_at": captured_at,
                    "processed_at": available_time,
                    "ts": str(ts or ""),
                    "instId": str(item.get("instId") or detail.get("instId") or ""),
                    "uly": str(item.get("uly") or ""),
                    "state": str(item.get("state") or ""),
                    "side": str(detail.get("side") or ""),
                    "posSide": str(detail.get("posSide") or ""),
                    "bkPx": price,
                    "sz": size,
                    "notional_usd": round(price * size, 8) if price and size else 0.0,
                    "source_record_id": _source_id(item, detail, ts),
                }
            )
    return [row for row in rows if row.get("event_time")]


def _source_id(item: Mapping[str, Any], detail: Mapping[str, Any], ts: Any) -> str:
    parts = [
        "okx-liquidation",
        str(item.get("instId") or detail.get("instId") or ""),
        str(ts or ""),
        str(detail.get("side") or ""),
        str(detail.get("posSide") or ""),
        str(detail.get("bkPx") or detail.get("price") or ""),
        str(detail.get("sz") or detail.get("size") or ""),
    ]
    return ":".join(parts)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _merge_rows(existing: Sequence[Mapping[str, Any]], new_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for row in [*existing, *new_rows]:
        key = str(row.get("source_record_id") or "")
        if key:
            keyed[key] = dict(row)
    rows = list(keyed.values())
    rows.sort(key=lambda row: (str(row.get("event_time") or ""), str(row.get("source_record_id") or "")))
    return rows


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "event_time",
        "available_time",
        "available_time_source",
        "ingested_at",
        "processed_at",
        "ts",
        "instId",
        "uly",
        "state",
        "side",
        "posSide",
        "bkPx",
        "sz",
        "notional_usd",
        "source_record_id",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    event_times = sorted(str(row.get("event_time")) for row in rows if row.get("event_time"))
    available_times = sorted(str(row.get("available_time")) for row in rows if row.get("available_time"))
    return {
        "row_count": len(rows),
        "event_start": event_times[0] if event_times else None,
        "event_end": event_times[-1] if event_times else None,
        "available_start": available_times[0] if available_times else None,
        "available_end": available_times[-1] if available_times else None,
        "available_capture_count": len(set(available_times)),
    }


def _blockers(*, execute_network: bool, network_error: str | None, new_rows: Sequence[Mapping[str, Any]], merged_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not execute_network:
        blockers.append("btc_okx_liquidation_snapshot_observer_dry_run_no_network_executed")
    if network_error:
        blockers.append("btc_okx_liquidation_snapshot_public_fetch_failed")
    if execute_network and not new_rows:
        blockers.append("btc_okx_liquidation_snapshot_no_new_rows_returned")
    if not merged_rows:
        blockers.append("btc_okx_liquidation_snapshot_no_local_rows")
    blockers.append("btc_okx_liquidation_snapshot_observe_only_not_complete_1h_history")
    return _dedupe(blockers)


def _warnings(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_okx_liquidation_snapshot_observer_research_only_no_paper_no_live"]
    if rows:
        warnings.append("liquidation_snapshot_available_but_not_gate_eligible")
    return warnings


def _status(*, execute_network: bool, network_error: str | None, merged_rows: Sequence[Mapping[str, Any]]) -> str:
    if not execute_network:
        return "dry_run_research_only"
    if network_error:
        return "partial_research_only"
    return "complete_research_only" if merged_rows else "blocked_no_rows_research_only"


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "api_key_used": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_okx_liquidation_snapshot_observer_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "api_key_used": False,
        "blockers": list(report.get("blockers", [])),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_ms(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(int(float(value)) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _max_iso(left: str | None, right: str | None) -> str:
    candidates = [_timestamp(value) for value in (left, right) if value]
    candidates = [value for value in candidates if value is not None]
    if not candidates:
        return datetime.now(timezone.utc).isoformat()
    return max(candidates).isoformat()


def _timestamp(value: str) -> datetime | None:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
