#!/usr/bin/env python3
"""Run one guarded BTC daily paper roll.

The roll is public-data only: it may refresh the OKX public bundle, then runs
the latest paper-validation cycle and writes a single monitoring report with
blocking reasons suitable for a scheduler.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_btc_paper_validation_readiness import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    DEFAULT_INTERVAL,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_READINESS_REPORT,
    DEFAULT_START_REPORT,
    MARKET_TYPE,
    SYMBOL,
)
from scripts.fetch_btc_okx_swap_public_data import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_ROOT as DEFAULT_OKX_OUTPUT_ROOT,
    capture_okx_public_bundle,
)
from scripts.run_btc_paper_validation import (  # noqa: E402
    DEFAULT_CYCLE_HOURS,
    DEFAULT_DAYS_REQUIRED,
    run_btc_paper_validation,
)


SCHEMA_VERSION = "btc_daily_paper_roll_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_paper_readiness/latest/btc_daily_paper_roll_report.json")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_data_status/latest/btc_daily_paper_roll_okx_capture_report.json")
DEFAULT_BUNDLE_ID = "btc_okx_swap_btcusdt_daily_roll_90d_v1"
DEFAULT_HISTORY_DAYS = 90
DEFAULT_MIN_5M_BARS = 200
DEFAULT_MIN_15M_BARS = 60


def run_btc_daily_paper_roll(
    *,
    repo_root: Path | None = None,
    symbols: list[str] | None = None,
    market_type: str = MARKET_TYPE,
    interval: str = DEFAULT_INTERVAL,
    ledger_root: Path | None = None,
    data_root: Path | None = None,
    readiness_report: Path | None = None,
    start_report: Path | None = None,
    output: Path | None = None,
    config_path: Path | None = None,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    okx_output_root: Path | None = None,
    okx_capture_report: Path | None = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
    request_sleep_seconds: float = 0.12,
    execute_network: bool = False,
    skip_data_refresh: bool = False,
    update_config: bool = True,
    days_required: int = DEFAULT_DAYS_REQUIRED,
    cycle_hours: int = DEFAULT_CYCLE_HOURS,
    min_5m_bars: int = DEFAULT_MIN_5M_BARS,
    min_15m_bars: int = DEFAULT_MIN_15M_BARS,
    require_start_report_ready: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root or DEFAULT_LEDGER_ROOT)
    data = _resolve(root, data_root or DEFAULT_DATA_ROOT)
    readiness_path = _resolve(root, readiness_report or DEFAULT_READINESS_REPORT)
    start_path = _resolve(root, start_report or DEFAULT_START_REPORT)
    output_path = _resolve(root, output or DEFAULT_OUTPUT)
    config_abs = _resolve(root, config_path or DEFAULT_CONFIG)

    data_refresh = _data_refresh_payload(
        repo_root=root,
        bundle_id=bundle_id,
        okx_output_root=okx_output_root or DEFAULT_OKX_OUTPUT_ROOT,
        config_path=config_abs,
        okx_capture_report=okx_capture_report or DEFAULT_CAPTURE_REPORT,
        execute_network=execute_network,
        skip_data_refresh=skip_data_refresh,
        update_config=update_config,
        history_days=history_days,
        request_sleep_seconds=request_sleep_seconds,
        generated_at=generated,
    )
    bundle_dir = _resolve_selected_bundle_dir(root, config_abs=config_abs, data_refresh=data_refresh)
    data_quality = _bundle_data_quality(bundle_dir, min_5m_bars=min_5m_bars, min_15m_bars=min_15m_bars)
    refresh_blockers = _data_refresh_blockers(
        data_refresh=data_refresh,
        skip_data_refresh=skip_data_refresh,
        execute_network=execute_network,
    )

    validation_result: dict[str, Any] = {}
    validation_status = "not_run"
    if not data_quality["blockers"] and not refresh_blockers:
        validation_result = run_btc_paper_validation(
            repo_root=root,
            symbols=symbols or [SYMBOL],
            market_type=market_type,
            interval=interval,
            ledger_root=ledger,
            data_root=data,
            readiness_report=readiness_path,
            start_report=start_path,
            days_required=days_required,
            cycle_hours=cycle_hours,
            resume=(ledger / "validation_state.json").exists(),
            require_start_report_ready=bool(require_start_report_ready),
            generated_at=generated,
        )
        validation_status = _validation_status(validation_result)

    monitoring = _monitoring_payload(validation_result, ledger=ledger)
    blockers = _daily_roll_blockers(
        data_refresh=data_refresh,
        data_quality=data_quality,
        validation_status=validation_status,
        validation_result=validation_result,
        monitoring=monitoring,
        skip_data_refresh=skip_data_refresh,
        execute_network=execute_network,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "BLOCKED" if blockers else "PASS",
        "asset": "btc",
        "symbol": SYMBOL,
        "market_type": MARKET_TYPE,
        "interval": interval,
        "ledger_root": _path_text(ledger),
        "bundle_dir": _path_text(bundle_dir) if bundle_dir else "",
        "data_refresh": data_refresh,
        "data_quality": data_quality,
        "validation": {
            "status": validation_status,
            "raw_status": str(validation_result.get("status", "")),
            "reason": str(validation_result.get("reason", "")),
            "run_id": str(validation_result.get("run_id", "")),
            "validation_state_path": str(validation_result.get("validation_state_path", "")),
            "monitoring_report_path": str(validation_result.get("monitoring_report_path", "")),
        },
        "monitoring": monitoring,
        "alert": {
            "should_alert": bool(blockers),
            "level": "blocker" if blockers else "none",
            "blockers": blockers,
        },
        "blockers": blockers,
    }
    _write_json(output_path, payload)
    return payload


def _data_refresh_payload(
    *,
    repo_root: Path,
    bundle_id: str,
    okx_output_root: Path,
    config_path: Path,
    okx_capture_report: Path,
    execute_network: bool,
    skip_data_refresh: bool,
    update_config: bool,
    history_days: int,
    request_sleep_seconds: float,
    generated_at: str,
) -> dict[str, Any]:
    if skip_data_refresh:
        return {
            "status": "skipped",
            "reason": "operator_requested_skip_data_refresh",
            "generated_at": generated_at,
            "network_called": False,
            "public_rest_only": True,
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "blockers": [],
        }
    try:
        return dict(
            capture_okx_public_bundle(
                repo_root=repo_root,
                bundle_id=bundle_id,
                output_root=okx_output_root,
                config_path=config_path,
                capture_report_path=okx_capture_report,
                execute_network=execute_network,
                update_config=update_config,
                history_days=history_days,
                request_sleep_seconds=request_sleep_seconds,
                captured_at=generated_at,
            )
        )
    except Exception as exc:
        return {
            "schema_version": "btc_okx_public_bundle_capture_report_v1",
            "status": "rejected",
            "generated_at": generated_at,
            "bundle_id": bundle_id,
            "history_days": int(history_days),
            "network_called": bool(execute_network),
            "public_rest_only": True,
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "config_updated": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "blockers": ["btc_daily_paper_data_refresh_exception"],
        }


def _resolve_selected_bundle_dir(
    root: Path,
    *,
    config_abs: Path,
    data_refresh: Mapping[str, Any],
) -> Path | None:
    refresh_bundle = str(data_refresh.get("bundle_dir", "") or "").strip()
    if refresh_bundle:
        return _resolve(root, Path(refresh_bundle))
    if not config_abs.exists():
        return None
    config = yaml.safe_load(config_abs.read_text(encoding="utf-8")) or {}
    providers = config.get("providers")
    if not isinstance(providers, Mapping):
        return None
    selected = str(config.get("selected_provider", "okx_swap") or "okx_swap")
    provider = providers.get(selected)
    if not isinstance(provider, Mapping):
        return None
    provider_root = Path(str(provider.get("root", "") or ""))
    bundle_id = str(provider.get("selected_bundle_id", "") or "").strip()
    if not provider_root or not bundle_id:
        return None
    return _resolve(root, provider_root) / "bundles" / bundle_id


def _bundle_data_quality(bundle_dir: Path | None, *, min_5m_bars: int, min_15m_bars: int) -> dict[str, Any]:
    blockers: list[str] = []
    if bundle_dir is None:
        return {
            "status": "BLOCKED",
            "bundle_dir": "",
            "klines_5m": {"exists": False, "row_count": 0},
            "klines_15m": {"exists": False, "row_count": 0},
            "blockers": ["btc_daily_paper_bundle_dir_missing"],
        }
    k5 = _csv_time_quality(bundle_dir / "klines_5m.csv")
    k15 = _csv_time_quality(bundle_dir / "klines_15m.csv")
    if not k5["exists"] or int(k5["row_count"]) < int(min_5m_bars):
        blockers.append("btc_daily_paper_5m_data_missing_or_too_short")
    if not k15["exists"] or int(k15["row_count"]) < int(min_15m_bars):
        blockers.append("btc_daily_paper_15m_data_missing_or_too_short")
    return {
        "status": "BLOCKED" if blockers else "PASS",
        "bundle_dir": _path_text(bundle_dir),
        "klines_5m": k5,
        "klines_15m": k15,
        "min_5m_bars": int(min_5m_bars),
        "min_15m_bars": int(min_15m_bars),
        "blockers": blockers,
    }


def _csv_time_quality(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": _path_text(path), "row_count": 0, "start": "", "end": ""}
    row_count = 0
    first = ""
    last = ""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = str(row.get("timestamp", "") or "")
            if row_count == 0:
                first = timestamp
            last = timestamp
            row_count += 1
    return {
        "exists": True,
        "path": _path_text(path),
        "row_count": row_count,
        "start": first,
        "end": last,
    }


def _validation_status(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "") or "")
    reason = str(result.get("reason", "") or "")
    if status == "BLOCKED" and reason == "btc_paper_validation_cycle_already_completed":
        return "SKIPPED_ALREADY_COMPLETED"
    return status or "unknown"


def _monitoring_payload(result: Mapping[str, Any], *, ledger: Path) -> dict[str, Any]:
    monitoring = result.get("monitoring")
    if isinstance(monitoring, Mapping):
        return dict(monitoring)
    latest = ledger / "audit" / "paper_cycle_monitoring_latest.json"
    if latest.exists():
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


def _daily_roll_blockers(
    *,
    data_refresh: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    validation_status: str,
    validation_result: Mapping[str, Any],
    monitoring: Mapping[str, Any],
    skip_data_refresh: bool,
    execute_network: bool,
) -> list[str]:
    blockers: list[str] = []
    blockers.extend(
        _data_refresh_blockers(
            data_refresh=data_refresh,
            skip_data_refresh=skip_data_refresh,
            execute_network=execute_network,
        )
    )
    blockers.extend(str(item) for item in data_quality.get("blockers", []) if item)
    if blockers:
        return _dedupe(blockers)

    if validation_status not in {"IN_PROGRESS", "PASS", "SKIPPED_ALREADY_COMPLETED"}:
        reason = str(validation_result.get("reason", "") or "btc_daily_paper_validation_not_pass")
        blockers.append(reason)
    if not monitoring:
        blockers.append("btc_daily_paper_monitoring_missing")
        return _dedupe(blockers)
    if validation_status != "SKIPPED_ALREADY_COMPLETED":
        if not bool(monitoring.get("monitoring_pass", False)):
            blockers.append("btc_daily_paper_monitoring_not_pass")
        if not bool(monitoring.get("reconciliation_passed", False)):
            blockers.append("btc_daily_paper_reconciliation_failed")
        if not bool(monitoring.get("equity_consistent", False)):
            blockers.append("btc_daily_paper_equity_inconsistent")
        if int(monitoring.get("rejected_count", 0) or 0) > 0:
            blockers.append("btc_daily_paper_rejected_orders_present")
        if int(_mapping(monitoring.get("cycle")).get("bar_count", 0) or 0) <= 0:
            blockers.append("btc_daily_paper_cycle_no_data")
        if float(monitoring.get("commission_rate", 0.0) or 0.0) < 0.0:
            blockers.append("btc_daily_paper_cost_model_invalid_commission")
        if float(monitoring.get("slippage_bps", 0.0) or 0.0) < 0.0:
            blockers.append("btc_daily_paper_cost_model_invalid_slippage")
    return _dedupe(blockers)


def _data_refresh_blockers(
    *,
    data_refresh: Mapping[str, Any],
    skip_data_refresh: bool,
    execute_network: bool,
) -> list[str]:
    blockers: list[str] = []
    if not skip_data_refresh and not execute_network:
        blockers.append("btc_daily_paper_data_refresh_not_executed")
    if not skip_data_refresh and str(data_refresh.get("status", "")) != "verified":
        blockers.append("btc_daily_paper_data_refresh_not_verified")
    blockers.extend(str(item) for item in data_refresh.get("blockers", []) if item)
    return _dedupe(blockers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh OKX public BTC data and run one daily paper cycle.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", default=SYMBOL)
    parser.add_argument("--market-type", default=MARKET_TYPE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--start-report", default=str(DEFAULT_START_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--okx-output-root", default=str(DEFAULT_OKX_OUTPUT_ROOT))
    parser.add_argument("--okx-capture-report", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.12)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--skip-data-refresh", action="store_true")
    parser.add_argument("--no-update-config", action="store_true")
    parser.add_argument("--days-required", type=int, default=DEFAULT_DAYS_REQUIRED)
    parser.add_argument("--cycle-hours", type=int, default=DEFAULT_CYCLE_HOURS)
    parser.add_argument("--min-5m-bars", type=int, default=DEFAULT_MIN_5M_BARS)
    parser.add_argument("--min-15m-bars", type=int, default=DEFAULT_MIN_15M_BARS)
    parser.add_argument("--no-start-report-ready-required", action="store_true")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_btc_daily_paper_roll(
        repo_root=Path(args.repo_root),
        symbols=_parse_symbols(args.symbols),
        market_type=args.market_type,
        interval=args.interval,
        ledger_root=Path(args.ledger_root),
        data_root=Path(args.data_root),
        readiness_report=Path(args.readiness_report),
        start_report=Path(args.start_report),
        output=Path(args.output),
        config_path=Path(args.config_path),
        bundle_id=args.bundle_id,
        okx_output_root=Path(args.okx_output_root),
        okx_capture_report=Path(args.okx_capture_report),
        history_days=args.history_days,
        request_sleep_seconds=args.request_sleep_seconds,
        execute_network=bool(args.execute_network),
        skip_data_refresh=bool(args.skip_data_refresh),
        update_config=not args.no_update_config,
        days_required=args.days_required,
        cycle_hours=args.cycle_hours,
        min_5m_bars=args.min_5m_bars,
        min_15m_bars=args.min_15m_bars,
        require_start_report_ready=not args.no_start_report_ready_required,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(f"BTC daily paper roll status: {payload['status']}")
        print(f"validation_status: {payload['validation']['status']}")
        print(f"blockers: {', '.join(payload['blockers']) if payload['blockers'] else 'none'}")
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


def _parse_symbols(raw: str) -> list[str]:
    return sorted({item.strip().upper() for item in raw.split(",") if item.strip()})


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), indent=2, sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _path_text(path: Path | None) -> str:
    return "" if path is None else str(path).replace("\\", "/")


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


if __name__ == "__main__":
    main()
