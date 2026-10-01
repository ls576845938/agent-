from __future__ import annotations

import csv
import io
import json
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "btc_binance_vision_book_depth_diagnostic_v1"
SYMBOL = "BTCUSDT"
BINANCE_VISION_BASE = "https://data.binance.vision/data/futures/um"
BINANCE_VISION_S3_LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BOOK_DEPTH_PREFIX = f"data/futures/um/daily/bookDepth/{SYMBOL}/"
DEFAULT_DATA_ROOT = Path("data/external/btc_perpetual/binance_vision_book_depth/BTCUSDT")
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_cost_model/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_binance_vision_book_depth_diagnostic_report.json"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_binance_vision_book_depth_diagnostic_summary.csv"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "btc_binance_vision_book_depth_diagnostic_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_binance_vision_book_depth_safety_status.json"
MIN_DIAGNOSTIC_COVERAGE_DAYS = 14.0
USER_AGENT = "QuantStationVNEXT-btc-binance-vision-book-depth/1.0"


@dataclass(frozen=True)
class BookDepthRow:
    timestamp: datetime
    percentage: float
    depth: float
    notional: float
    source_file: str


def build_btc_binance_vision_book_depth_diagnostic(
    *,
    data_root: Path = DEFAULT_DATA_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    execute_network: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
    lookback_days: int = 14,
    sleep_seconds: float = 0.02,
    request_timeout_seconds: int = 30,
    network_route_label: str = "",
    use_latest_available_when_network: bool = True,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    data_root.mkdir(parents=True, exist_ok=True)
    raw_dir = data_root / "raw_archives"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    discovery: dict[str, Any] = {
        "used": False,
        "status": "not_run",
        "latest_available_date": None,
        "zip_key_count": 0,
        "error": None,
    }
    if start_date is None or end_date is None:
        if execute_network and use_latest_available_when_network:
            discovery = discover_latest_book_depth_date(request_timeout_seconds=request_timeout_seconds)
        if discovery.get("latest_available_date"):
            end = date.fromisoformat(str(discovery["latest_available_date"]))
        else:
            end = generated.date() - timedelta(days=1)
        start = end - timedelta(days=max(1, int(lookback_days)) - 1)
    else:
        start = start_date
        end = end_date

    attempts: list[dict[str, Any]] = []
    if execute_network:
        for day in _days(start, end):
            attempt = _download_daily_zip(
                day,
                raw_dir=raw_dir,
                request_timeout_seconds=request_timeout_seconds,
            )
            attempts.append(attempt)
            time.sleep(max(0.0, float(sleep_seconds)))
    else:
        attempts = [
            {
                "date": day.isoformat(),
                "url": _daily_zip_url(day),
                "status_code": None,
                "rows": 0,
                "network_called": False,
                "local_file_exists": (_daily_zip_path(raw_dir, day)).exists(),
            }
            for day in _days(start, end)
        ]

    rows, parse_errors = _read_local_rows(raw_dir=raw_dir, start_date=start, end_date=end)
    coverage = _coverage_summary(rows)
    bucket_summary = _percentage_bucket_summary(rows)
    one_percent = _side_depth_summary(rows, abs_percentage=1.0)
    five_percent = _side_depth_summary(rows, abs_percentage=5.0)
    blockers = _blockers(rows=rows, coverage=coverage, execute_network=execute_network)
    status = "complete_diagnostic_only" if rows else ("blocked_no_free_rows" if execute_network else "planned_no_network_or_local_rows")
    if rows and not _diagnostic_has_14d_coverage(coverage):
        status = "partial_diagnostic_only"

    report_path = output_dir / DEFAULT_REPORT_PATH.name
    csv_path = output_dir / DEFAULT_CSV_PATH.name
    summary_path = output_dir / DEFAULT_SUMMARY_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "decision": (
            "binance_vision_book_depth_cross_venue_diagnostic_only_not_okx_gate_evidence"
            if rows
            else "binance_vision_book_depth_free_rows_missing_no_paper_no_live"
        ),
        "asset": "btc",
        "symbol": SYMBOL,
        "source_provider": "binance_vision_usdm_daily_bookDepth",
        "source_url_template": f"{BINANCE_VISION_BASE}/daily/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-YYYY-MM-DD.zip",
        "source_directory_url": f"https://data.binance.vision/?prefix={urllib.parse.quote(BOOK_DEPTH_PREFIX, safe='')}",
        "source_format_note": "daily aggregate percentage-depth CSV: timestamp, percentage, depth, notional",
        "requested_window": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "lookback_days": lookback_days,
        },
        "network": {
            "execute_network": bool(execute_network),
            "network_called": bool(execute_network),
            "network_route_label": network_route_label,
            "public_market_data_only": True,
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
            "discovery": discovery,
            "download_attempts": attempts,
        },
        "local_data": {
            "data_root": _portable_path(data_root),
            "raw_dir": _portable_path(raw_dir),
            "local_zip_count": len(list(raw_dir.glob(f"{SYMBOL}-bookDepth-*.zip"))),
            "parse_errors": parse_errors,
        },
        "coverage": coverage,
        "row_count": len(rows),
        "percentage_bucket_summary": bucket_summary,
        "one_percent_depth_diagnostic": one_percent,
        "five_percent_depth_diagnostic": five_percent,
        "execution_gate_interpretation": {
            "free_public_depth_diagnostic_available": bool(rows),
            "free_public_depth_diagnostic_coverage_14d": _diagnostic_has_14d_coverage(coverage),
            "venue": "binance_usdm",
            "selected_execution_venue": "okx_swap",
            "gate_eligible_for_selected_venue": False,
            "depth_aware_slippage_history_verified_for_selected_venue": False,
            "reason": "Binance Vision bookDepth is cross-venue aggregate percentage depth, not OKX per-level order book or paper fill replay.",
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "warnings": [
            "cross_venue_depth_diagnostic_only",
            "aggregate_percentage_depth_not_per_level_order_book",
            "not_sufficient_for_okx_depth_aware_slippage_gate",
        ],
        "code_commit": _git_commit(),
        "outputs": {
            "json": _portable_path(report_path),
            "csv": _portable_path(csv_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_bucket_csv(csv_path, bucket_summary)
    _write_text(summary_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def discover_latest_book_depth_date(*, request_timeout_seconds: int = 30, max_pages: int = 10) -> dict[str, Any]:
    keys: list[str] = []
    token: str | None = None
    try:
        for _ in range(max_pages):
            query = {
                "list-type": "2",
                "prefix": BOOK_DEPTH_PREFIX,
                "max-keys": "1000",
            }
            if token:
                query["continuation-token"] = token
            url = BINANCE_VISION_S3_LIST_URL + "?" + urllib.parse.urlencode(query)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:  # noqa: S310
                payload = response.read()
            root = ET.fromstring(payload)
            namespace = "{http://s3.amazonaws.com/doc/2006-03-01/}"
            keys.extend(
                str(item.text)
                for item in root.findall(f"{namespace}Contents/{namespace}Key")
                if item.text
            )
            truncated = (root.findtext(f"{namespace}IsTruncated") or "").lower() == "true"
            token = root.findtext(f"{namespace}NextContinuationToken")
            if not truncated or not token:
                break
        zip_dates = [_date_from_key(key) for key in keys if key.endswith(".zip")]
        zip_dates = [value for value in zip_dates if value is not None]
        return {
            "used": True,
            "status": "complete" if zip_dates else "empty",
            "latest_available_date": max(zip_dates).isoformat() if zip_dates else None,
            "earliest_available_date": min(zip_dates).isoformat() if zip_dates else None,
            "zip_key_count": len(zip_dates),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic discovery must not break offline report.
        return {
            "used": True,
            "status": "failed",
            "latest_available_date": None,
            "zip_key_count": 0,
            "error": f"{type(exc).__name__}:{exc}",
        }


def render_summary_cn(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    interpretation = _mapping(report.get("execution_gate_interpretation"))
    network = _mapping(report.get("network"))
    lines = [
        "# BTC Binance Vision bookDepth 免费深度诊断",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 行数：`{report.get('row_count')}`",
        f"- 覆盖：`{coverage.get('sample_start')}` 到 `{coverage.get('sample_end')}`，约 `{coverage.get('coverage_days')}` 天",
        f"- 两边盘口时间点：`{coverage.get('two_sided_timestamp_count')}` / `{coverage.get('timestamp_count')}`",
        f"- 是否可替代 OKX 深度滑点门禁：`{interpretation.get('gate_eligible_for_selected_venue')}`",
        f"- 是否使用私有或下单接口：`{network.get('private_endpoint_used') or False}` / `{network.get('order_endpoint_used') or False}`",
        "",
        "## 口径",
        "",
        "- 这个数据来自 Binance Vision 免费公开 USD-M 期货 `bookDepth` 日文件。",
        "- 它是按价格百分比聚合后的深度，不是逐档 L2 盘口，也不是 OKX 的盘口。",
        "- 因此它只能补充“市场深度环境诊断”，不能解除 OKX 深度滑点、paper replay 或 live 门禁。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 剩余缺口"])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _download_daily_zip(day: date, *, raw_dir: Path, request_timeout_seconds: int) -> dict[str, Any]:
    url = _daily_zip_url(day)
    target = _daily_zip_path(raw_dir, day)
    attempt: dict[str, Any] = {
        "date": day.isoformat(),
        "url": url,
        "status_code": None,
        "rows": 0,
        "network_called": True,
        "local_file_exists_before": target.exists(),
        "local_file": _portable_path(target),
    }
    try:
        if not target.exists():
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:  # noqa: S310
                attempt["status_code"] = getattr(response, "status", 200)
                target.write_bytes(response.read())
        else:
            attempt["status_code"] = 200
        attempt["rows"] = _zip_row_count(target)
        attempt["local_file_exists_after"] = target.exists()
    except urllib.error.HTTPError as exc:
        attempt["status_code"] = int(exc.code)
        attempt["error"] = f"HTTPError:{exc}"
        attempt["local_file_exists_after"] = target.exists()
    except Exception as exc:  # noqa: BLE001 - record public data failure and continue.
        attempt["error"] = f"{type(exc).__name__}:{exc}"
        attempt["local_file_exists_after"] = target.exists()
    return attempt


def _read_local_rows(*, raw_dir: Path, start_date: date, end_date: date) -> tuple[list[BookDepthRow], list[dict[str, Any]]]:
    rows: list[BookDepthRow] = []
    errors: list[dict[str, Any]] = []
    for day in _days(start_date, end_date):
        path = _daily_zip_path(raw_dir, day)
        if not path.exists():
            continue
        try:
            rows.extend(_read_zip_rows(path))
        except Exception as exc:  # noqa: BLE001
            errors.append({"path": _portable_path(path), "error": f"{type(exc).__name__}:{exc}"})
    rows.sort(key=lambda row: (row.timestamp, row.percentage))
    return rows, errors


def _read_zip_rows(path: Path) -> list[BookDepthRow]:
    with zipfile.ZipFile(path) as archive:
        name = next(item for item in archive.namelist() if item.endswith(".csv"))
        data = archive.read(name).decode("utf-8")
    reader = csv.DictReader(io.StringIO(data))
    rows: list[BookDepthRow] = []
    for raw in reader:
        timestamp = _parse_timestamp(raw.get("timestamp"))
        percentage = _float(raw.get("percentage"))
        depth = _float(raw.get("depth"))
        notional = _float(raw.get("notional"))
        if timestamp is None or percentage is None or depth is None or notional is None:
            continue
        rows.append(
            BookDepthRow(
                timestamp=timestamp,
                percentage=percentage,
                depth=depth,
                notional=notional,
                source_file=path.name,
            )
        )
    return rows


def _coverage_summary(rows: Sequence[BookDepthRow]) -> dict[str, Any]:
    timestamps = sorted({row.timestamp for row in rows})
    coverage_days = 0.0
    if len(timestamps) >= 2:
        coverage_days = (timestamps[-1] - timestamps[0]).total_seconds() / 86_400.0
    two_sided = 0
    for timestamp, grouped in _group_by_timestamp(rows).items():
        percentages = {row.percentage for row in grouped}
        if any(value < 0 for value in percentages) and any(value > 0 for value in percentages):
            two_sided += 1
    dates = sorted({row.timestamp.date().isoformat() for row in rows})
    return {
        "row_count": len(rows),
        "timestamp_count": len(timestamps),
        "two_sided_timestamp_count": two_sided,
        "sample_start": timestamps[0].isoformat() if timestamps else None,
        "sample_end": timestamps[-1].isoformat() if timestamps else None,
        "date_count": len(dates),
        "sample_start_date": dates[0] if dates else None,
        "sample_end_date": dates[-1] if dates else None,
        "coverage_days": round(coverage_days, 6),
    }


def _percentage_bucket_summary(rows: Sequence[BookDepthRow]) -> list[dict[str, Any]]:
    grouped: dict[float, list[BookDepthRow]] = {}
    for row in rows:
        grouped.setdefault(row.percentage, []).append(row)
    output: list[dict[str, Any]] = []
    for percentage in sorted(grouped):
        values = grouped[percentage]
        notionals = [row.notional for row in values]
        depths = [row.depth for row in values]
        output.append(
            {
                "percentage": round(percentage, 4),
                "side": "bid_depth" if percentage < 0 else "ask_depth",
                "row_count": len(values),
                "median_notional_usd": round(_percentile(notionals, 0.5), 6),
                "p10_notional_usd": round(_percentile(notionals, 0.1), 6),
                "p90_notional_usd": round(_percentile(notionals, 0.9), 6),
                "median_depth_btc": round(_percentile(depths, 0.5), 8),
            }
        )
    return output


def _side_depth_summary(rows: Sequence[BookDepthRow], *, abs_percentage: float) -> dict[str, Any]:
    bid = [row.notional for row in rows if round(row.percentage, 6) == -abs_percentage]
    ask = [row.notional for row in rows if round(row.percentage, 6) == abs_percentage]
    return {
        "abs_percentage": abs_percentage,
        "bid_row_count": len(bid),
        "ask_row_count": len(ask),
        "bid_median_notional_usd": round(_percentile(bid, 0.5), 6) if bid else None,
        "ask_median_notional_usd": round(_percentile(ask, 0.5), 6) if ask else None,
        "bid_p10_notional_usd": round(_percentile(bid, 0.1), 6) if bid else None,
        "ask_p10_notional_usd": round(_percentile(ask, 0.1), 6) if ask else None,
        "interpretation": "aggregate notional within percentage band; not an executable order-book walk",
    }


def _blockers(*, rows: Sequence[BookDepthRow], coverage: Mapping[str, Any], execute_network: bool) -> list[str]:
    blockers: list[str] = []
    if not rows:
        blockers.append("btc_binance_vision_book_depth_rows_missing")
        if not execute_network:
            blockers.append("btc_binance_vision_book_depth_execute_network_false_or_no_local_archives")
    if rows and not _diagnostic_has_14d_coverage(coverage):
        blockers.append("btc_binance_vision_book_depth_diagnostic_coverage_below_14d")
    blockers.append("btc_binance_vision_book_depth_cross_venue_not_okx_execution_gate")
    return blockers


def _group_by_timestamp(rows: Iterable[BookDepthRow]) -> dict[datetime, list[BookDepthRow]]:
    grouped: dict[datetime, list[BookDepthRow]] = {}
    for row in rows:
        grouped.setdefault(row.timestamp, []).append(row)
    return grouped


def _diagnostic_has_14d_coverage(coverage: Mapping[str, Any]) -> bool:
    return (
        float(coverage.get("coverage_days") or 0.0) >= MIN_DIAGNOSTIC_COVERAGE_DAYS
        or int(coverage.get("date_count") or 0) >= int(MIN_DIAGNOSTIC_COVERAGE_DAYS)
    )


def _zip_row_count(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        name = next(item for item in archive.namelist() if item.endswith(".csv"))
        with archive.open(name) as handle:
            return max(0, sum(1 for _ in handle) - 1)


def _daily_zip_url(day: date) -> str:
    return f"{BINANCE_VISION_BASE}/daily/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-{day:%Y-%m-%d}.zip"


def _daily_zip_path(raw_dir: Path, day: date) -> Path:
    return raw_dir / f"{SYMBOL}-bookDepth-{day:%Y-%m-%d}.zip"


def _date_from_key(key: str) -> date | None:
    prefix = f"{SYMBOL}-bookDepth-"
    name = key.rsplit("/", 1)[-1]
    if not name.startswith(prefix) or not name.endswith(".zip"):
        return None
    try:
        return date.fromisoformat(name[len(prefix) : -4])
    except ValueError:
        return None


def _days(start: date, end: date) -> list[date]:
    if end < start:
        return []
    out: list[date] = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_allowed": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "public_market_data_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_binance_vision_book_depth_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        **_gate(),
        "blockers": list(report.get("blockers", [])),
    }


def _write_bucket_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "percentage",
        "side",
        "row_count",
        "median_notional_usd",
        "p10_notional_usd",
        "p90_notional_usd",
        "median_depth_btc",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path.cwd(), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"
