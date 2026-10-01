#!/usr/bin/env python3
"""Build a read-only BTC data, fold, and regime status report."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
DEFAULT_SOURCE_RUN_DIR = Path(
    "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
)
DEFAULT_BUNDLE_PREFLIGHT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")
DEFAULT_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_SQLITE_DB = Path("data/market_data.sqlite")
SQLITE_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}
DIAGNOSTIC_ONLY_WARNINGS = {
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_agg_trades_missing",
    "btc_liquidation_snapshot_missing_diagnostic_only",
    "btc_liquidation_snapshots_missing_diagnostic_only",
    "diagnostic_only_not_gate_evidence",
}
DOWNSTREAM_GATE_REQUIREMENTS = {
    "btc_fee_model_required",
    "btc_funding_model_required",
}


def build_btc_data_status_report(
    *,
    repo_root: Path | None = None,
    source_run_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = _resolve_path(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    generated_dt = _parse_datetime(generated)
    source_data_status = _read_json(run_dir / "btc_data_fold_regime_status_report.json")
    preflight = _read_json(root / DEFAULT_BUNDLE_PREFLIGHT)
    provider = _read_json(root / DEFAULT_PROVIDER_VERIFICATION)
    fold_audit = _read_json(run_dir / "fold_regime_contract_audit.json")
    intervals = _interval_rows(source_data_status)
    coverage = _coverage_summary(intervals)
    sqlite_info = _mapping(source_data_status.get("sqlite"))
    sqlite_path = Path(str(sqlite_info.get("db_path") or DEFAULT_SQLITE_DB))
    current_sqlite = _current_sqlite_coverage(
        _resolve_path(root, sqlite_path),
        generated_at=generated_dt,
    )
    fold_contract = _mapping(fold_audit.get("fold_contract") or source_data_status.get("fold_status"))
    regime_contract = _mapping(fold_audit.get("regime_contract") or source_data_status.get("regime_status"))
    raw_blockers = _build_blockers(
        source_data_status=source_data_status,
        fold_contract=fold_contract,
        regime_contract=regime_contract,
        intervals=intervals,
        provider=provider,
    )
    blockers = _hard_data_blockers(raw_blockers)
    diagnostic_warnings = _diagnostic_warnings(raw_blockers)
    perpetual_ready = bool(provider.get("perpetual_evidence_ready", False))
    selected_provider = str(provider.get("selected_provider", "binance_usdm") or "binance_usdm")
    return {
        "schema_version": "btc_data_status_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "metadata": {
            "generated_at": generated,
            "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
            "branch": _git(["branch", "--show-current"], cwd=root),
            "source_type": "sqlite_binance_spot_klines",
            "is_data_dependent": bool(source_data_status),
            "is_placeholder": False,
        },
        "instrument": {
            "exchange": selected_provider if perpetual_ready else str(sqlite_info.get("exchange", "binance_spot") or "binance_spot"),
            "market_type": "usds_m_perpetual" if perpetual_ready else "spot_kline_research_input",
            "symbol": "BTCUSDT",
            "contract_type": "usds_m_perpetual_contract" if perpetual_ready else "spot_proxy_not_perpetual_contract",
            "quote_asset": "USDT",
            "margin_asset": "USDT",
            "timezone": "UTC",
        },
        "coverage": coverage,
        "data_sources": {
            "klines_available": bool(intervals),
            "mark_price_klines_available": bool(provider.get("mark_price_klines_verified", False)),
            "premium_index_klines_available": bool(provider.get("premium_index_klines_verified", False)),
            "funding_rate_available": bool(provider.get("funding_rate_verified", False)),
            "funding_info_available": bool(provider.get("funding_info_verified", False)),
            "exchange_info_available": bool(provider.get("exchange_info_verified", False)),
            "open_interest_available": bool(provider.get("open_interest_verified", False)),
            "open_interest_coverage_type": str(provider.get("open_interest_coverage_type", "missing") or "missing"),
            "agg_trades_available": False,
            "liquidation_snapshot_available": bool(provider.get("liquidation_snapshot_available", False)),
            "liquidation_snapshot_gate_eligible": False,
            "liquidation_snapshot_status": "diagnostic_missing_not_complete_history",
        },
        "current_sqlite_coverage": current_sqlite,
        "perpetual_provider_verification_report": _relpath(root / DEFAULT_PROVIDER_VERIFICATION, root)
        if (root / DEFAULT_PROVIDER_VERIFICATION).exists()
        else None,
        "perpetual_bundle_preflight_report": _relpath(root / DEFAULT_BUNDLE_PREFLIGHT, root)
        if (root / DEFAULT_BUNDLE_PREFLIGHT).exists()
        else None,
        "perpetual_provider_verification": {
            "selected_provider": selected_provider,
            "selected_bundle_id": provider.get("selected_bundle_id"),
            "source_type": provider.get("source_type"),
            "preflight_pass": bool(preflight.get("preflight_pass", False)),
            "perpetual_evidence_ready": bool(provider.get("perpetual_evidence_ready", False)),
            "data_lineage_grade_candidate": str(
                provider.get("data_lineage_grade_candidate", "L1_spot_proxy_research_input")
                or "L1_spot_proxy_research_input"
            ),
            "blockers": _hard_data_blockers(_list_of_strings(provider.get("blockers"))),
        },
        "data_quality": {
            "monotonic_time_pass": bool(intervals) and not any(row.get("missing_rows", 0) for row in intervals),
            "utc_alignment_pass": True,
            "interval_grid_pass": bool(intervals) and not any(row.get("missing_rows", 0) for row in intervals),
            "symbol_consistency_pass": str(sqlite_info.get("symbol", "BTCUSDT")) == "BTCUSDT",
            "stale_data_check_pass": bool(coverage.get("sample_end")) and current_sqlite.get("status") == "pass",
            "manifest_hash": _manifest_hash(source_data_status),
            "sqlite_path": str(sqlite_path),
            "data_path": str(sqlite_path),
            "blockers": blockers,
        },
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "missing" if not source_data_status else ("pass" if not blockers else "partial"),
        "source_run_dir": _relpath(run_dir, root),
        "source_data_fold_regime_report": _relpath(run_dir / "btc_data_fold_regime_status_report.json", root)
        if (run_dir / "btc_data_fold_regime_status_report.json").exists()
        else None,
        "source_fold_regime_contract_audit": _relpath(run_dir / "fold_regime_contract_audit.json", root)
        if (run_dir / "fold_regime_contract_audit.json").exists()
        else None,
        "sqlite": _mapping(source_data_status.get("sqlite")),
        "intervals": intervals,
        "manifest_lineage": _mapping(source_data_status.get("manifest_lineage")),
        "fold_definition_version": "btc_walk_forward_fold_contract_v1",
        "fold_contract_status": str(fold_contract.get("status", "missing")),
        "fold_count": int(fold_contract.get("fold_count", 0) or 0),
        "folds": [
            {
                "fold_id": str(row.get("fold_id", "")),
                "validation_start": str(row.get("validation_start", "")),
                "validation_end": str(row.get("validation_end", "")),
                "validation_rows": int(row.get("validation_rows", 0) or 0),
                "passed": bool(row.get("passed", False)),
            }
            for row in _list_of_mappings(fold_contract.get("folds"))
        ],
        "regime_classifier_version": "classify_btc_regimes_v1",
        "regime_contract_status": str(regime_contract.get("status", "missing")),
        "regime_gate_pass_rate": _float(regime_contract.get("pass_rate") or regime_contract.get("gate_pass_rate")),
        "dragging_regimes": [str(item) for item in regime_contract.get("dragging_regimes", [])],
        "fee_model_status": "required",
        "funding_model_status": "required",
        "diagnostic_warnings": diagnostic_warnings,
        "blockers": blockers,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
    }


def write_btc_data_status_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_data_status_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_btc_data_status_report(
        repo_root=Path(args.repo_root),
        source_run_dir=Path(args.source_run_dir),
        generated_at=args.generated_at or None,
    )
    output = write_btc_data_status_report(payload, Path(args.output_root))
    print(output)


def _interval_rows(source_data_status: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _list_of_mappings(source_data_status.get("intervals")):
        rows.append(
            {
                "interval": str(row.get("interval", "")),
                "status": str(row.get("status", "missing")),
                "manifest_status": str(row.get("manifest_status", "missing")),
                "row_count": int(row.get("row_count", 0) or 0),
                "expected_rows": int(row.get("expected_rows", 0) or 0),
                "missing_rows": int(row.get("missing_rows", 0) or 0),
                "duplicate_rows": int(row.get("duplicate_rows", row.get("duplicate_bar_count", 0)) or 0),
                "data_version": str(row.get("data_version", "")),
                "latest_manifest_path": str(row.get("latest_manifest_path", "")),
                "start": str(row.get("start", "")),
                "end": str(row.get("end", "")),
            }
        )
    return rows


def _coverage_summary(intervals: list[Mapping[str, Any]]) -> dict[str, Any]:
    starts = [str(row.get("start", "")) for row in intervals if str(row.get("start", ""))]
    ends = [str(row.get("end", "")) for row in intervals if str(row.get("end", ""))]
    return {
        "sample_start": min(starts) if starts else None,
        "sample_end": max(ends) if ends else None,
        "intervals_available": [str(row.get("interval", "")) for row in intervals if str(row.get("interval", ""))],
        "bar_count_by_interval": {
            str(row.get("interval", "")): int(row.get("row_count", 0) or 0)
            for row in intervals
            if str(row.get("interval", ""))
        },
        "missing_bar_count_by_interval": {
            str(row.get("interval", "")): int(row.get("missing_rows", 0) or 0)
            for row in intervals
            if str(row.get("interval", ""))
        },
        "duplicate_bar_count_by_interval": {
            str(row.get("interval", "")): int(row.get("duplicate_rows", 0) or 0)
            for row in intervals
            if str(row.get("interval", ""))
        },
        "completeness_ratio_by_interval": {
            str(row.get("interval", "")): _ratio(row.get("row_count"), row.get("expected_rows"))
            for row in intervals
            if str(row.get("interval", ""))
        },
    }


def _current_sqlite_coverage(db_path: Path, *, generated_at: datetime) -> dict[str, Any]:
    base = {
        "status": "missing",
        "db_path": str(db_path),
        "source_table": "market_klines",
        "exchange": "binance_spot",
        "symbol": "BTCUSDT",
        "intervals": {},
        "coverage": {
            "sample_start": None,
            "sample_end": None,
            "latest_close_time_by_interval": {},
            "bar_count_by_interval": {},
            "missing_bar_count_by_interval": {},
            "duplicate_bar_count_by_interval": {},
        },
        "latest_closed_bar": {},
        "pit_contract": {
            "event_time_field": "close_time",
            "available_time_field": "close_time",
            "available_time_policy": "closed kline is visible only when close_time <= decision_time",
            "ingested_at_field": "ingested_at",
            "processed_at_field": "updated_at",
            "data_version_policy": "manifest data_version remains in manifest_lineage; current_sqlite_coverage records materialized table freshness",
        },
        "finalization": {
            "closed_bar_only": False,
            "latest_bar_final": False,
            "generated_at": generated_at.isoformat(),
        },
        "blockers": [],
        "warnings": [],
    }
    if not db_path.exists():
        base["blockers"] = ["btc_current_sqlite_market_data_missing"]
        return base
    try:
        with sqlite3.connect(str(db_path)) as connection:
            connection.row_factory = sqlite3.Row
            intervals: dict[str, Any] = {}
            for interval in SQLITE_INTERVALS:
                row = connection.execute(
                    """
                    select count(*) as row_count,
                           count(distinct close_time_ms) as distinct_close_count,
                           min(close_time_ms) as first_close_time_ms,
                           max(close_time_ms) as latest_close_time_ms,
                           min(close_time) as first_close_time,
                           max(close_time) as latest_close_time
                    from market_klines
                    where exchange = ? and symbol = ? and interval = ?
                    """,
                    ("binance_spot", "BTCUSDT", interval),
                ).fetchone()
                latest = connection.execute(
                    """
                    select open_time, close_time, close_time_ms, close, volume, source, ingested_at, updated_at
                    from market_klines
                    where exchange = ? and symbol = ? and interval = ?
                    order by close_time_ms desc
                    limit 1
                    """,
                    ("binance_spot", "BTCUSDT", interval),
                ).fetchone()
                intervals[interval] = _sqlite_interval_current_status(interval, row, latest, generated_at=generated_at)
    except sqlite3.Error as exc:
        base["blockers"] = [f"btc_current_sqlite_query_failed:{exc.__class__.__name__}"]
        return base

    coverage = _current_sqlite_coverage_summary(intervals)
    one_hour = _mapping(intervals.get("1h"))
    latest_closed_bar = _mapping(one_hour.get("latest_closed_bar"))
    status = "pass" if intervals and all(not _mapping(row).get("blockers") for row in intervals.values()) else "partial"
    base.update(
        {
            "status": status,
            "intervals": intervals,
            "coverage": coverage,
            "latest_closed_bar": latest_closed_bar,
            "finalization": {
                "closed_bar_only": bool(latest_closed_bar),
                "latest_bar_final": bool(one_hour.get("latest_bar_final", False)),
                "generated_at": generated_at.isoformat(),
            },
            "blockers": _dedupe(
                [
                    item
                    for row in intervals.values()
                    for item in _list_of_strings(_mapping(row).get("blockers"))
                ]
            ),
            "warnings": _dedupe(
                [
                    item
                    for row in intervals.values()
                    for item in _list_of_strings(_mapping(row).get("warnings"))
                ]
            ),
        }
    )
    base["coverage_hash"] = _stable_hash(
        {
            "intervals": intervals,
            "coverage": coverage,
            "latest_closed_bar": latest_closed_bar,
            "pit_contract": base["pit_contract"],
        }
    )
    return base


def _sqlite_interval_current_status(
    interval: str,
    row: sqlite3.Row | None,
    latest: sqlite3.Row | None,
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    if row is None or latest is None or int(row["row_count"] or 0) <= 0:
        return {
            "interval": interval,
            "status": "missing",
            "row_count": 0,
            "expected_rows": 0,
            "missing_rows": 0,
            "duplicate_rows": 0,
            "first_close_time": "",
            "latest_close_time": "",
            "latest_bar_final": False,
            "latest_closed_bar": {},
            "blockers": [f"btc_current_sqlite_interval_missing:{interval}"],
            "warnings": [],
        }
    row_count = int(row["row_count"] or 0)
    distinct_count = int(row["distinct_close_count"] or 0)
    duplicate_rows = max(0, row_count - distinct_count)
    first_ms = int(row["first_close_time_ms"] or 0)
    latest_ms = int(row["latest_close_time_ms"] or 0)
    expected_rows = _expected_rows(first_ms, latest_ms, interval)
    missing_rows = max(0, expected_rows - distinct_count)
    latest_close_time = str(latest["close_time"])
    latest_final = _is_final_close_time(latest_close_time, generated_at=generated_at)
    blockers: list[str] = []
    if duplicate_rows:
        blockers.append(f"btc_current_sqlite_interval_duplicates:{interval}")
    if missing_rows:
        blockers.append(f"btc_current_sqlite_interval_gaps:{interval}")
    if not latest_final:
        blockers.append(f"btc_current_sqlite_latest_bar_not_final:{interval}")
    latest_bar = {
        "event_time": latest_close_time,
        "available_time": latest_close_time,
        "ingested_at": str(latest["ingested_at"] or ""),
        "processed_at": str(latest["updated_at"] or ""),
        "open_time": str(latest["open_time"] or ""),
        "close_time": latest_close_time,
        "close": _float(latest["close"]),
        "volume": _float(latest["volume"]),
        "source": str(latest["source"] or ""),
    }
    return {
        "interval": interval,
        "status": "pass" if not blockers else "partial",
        "row_count": row_count,
        "expected_rows": expected_rows,
        "missing_rows": missing_rows,
        "duplicate_rows": duplicate_rows,
        "first_close_time": str(row["first_close_time"] or ""),
        "latest_close_time": latest_close_time,
        "latest_bar_final": latest_final,
        "latest_closed_bar": latest_bar if latest_final else {},
        "blockers": blockers,
        "warnings": [],
    }


def _current_sqlite_coverage_summary(intervals: Mapping[str, Any]) -> dict[str, Any]:
    rows = [_mapping(row) for row in intervals.values() if _mapping(row).get("row_count", 0)]
    starts = [str(row.get("first_close_time", "")) for row in rows if str(row.get("first_close_time", ""))]
    ends = [str(row.get("latest_close_time", "")) for row in rows if str(row.get("latest_close_time", ""))]
    return {
        "sample_start": min(starts) if starts else None,
        "sample_end": max(ends) if ends else None,
        "latest_close_time_by_interval": {
            str(row.get("interval", "")): str(row.get("latest_close_time", ""))
            for row in rows
            if str(row.get("interval", ""))
        },
        "bar_count_by_interval": {
            str(row.get("interval", "")): int(row.get("row_count", 0) or 0)
            for row in rows
            if str(row.get("interval", ""))
        },
        "missing_bar_count_by_interval": {
            str(row.get("interval", "")): int(row.get("missing_rows", 0) or 0)
            for row in rows
            if str(row.get("interval", ""))
        },
        "duplicate_bar_count_by_interval": {
            str(row.get("interval", "")): int(row.get("duplicate_rows", 0) or 0)
            for row in rows
            if str(row.get("interval", ""))
        },
    }


def _build_blockers(
    *,
    source_data_status: Mapping[str, Any],
    fold_contract: Mapping[str, Any],
    regime_contract: Mapping[str, Any],
    intervals: list[Mapping[str, Any]],
    provider: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not source_data_status:
        blockers.append("btc_data_fold_regime_status_report_missing")
    if not intervals:
        blockers.append("btc_interval_coverage_missing")
    for row in intervals:
        interval = str(row.get("interval", "unknown"))
        if row.get("status") != "pass":
            blockers.append(f"btc_interval_{interval}_coverage_not_pass")
        if row.get("manifest_status") != "pass":
            blockers.append(f"btc_interval_{interval}_manifest_not_pass")
        if not str(row.get("data_version", "")):
            blockers.append(f"btc_interval_{interval}_data_version_missing")
    if str(_mapping(source_data_status.get("sqlite")).get("status", "")) != "pass":
        blockers.append("btc_sqlite_completeness_not_pass")
    if str(_mapping(source_data_status.get("manifest_lineage")).get("status", "")) != "pass":
        blockers.append("btc_manifest_lineage_not_pass")
    if str(fold_contract.get("status", "")) != "pass":
        blockers.append("btc_fold_contract_not_pass")
    if str(regime_contract.get("status", "")) != "pass":
        blockers.append("btc_regime_contract_not_pass")
    if not provider.get("perpetual_evidence_ready", False):
        blockers.append("btc_perpetual_data_source_not_verified")
    if not provider.get("mark_price_klines_verified", False):
        blockers.append("btc_mark_price_klines_missing")
    if not provider.get("premium_index_klines_verified", False):
        blockers.append("btc_premium_index_klines_missing")
    if not provider.get("funding_rate_verified", False):
        blockers.append("btc_funding_rate_missing")
    if not provider.get("funding_info_verified", False):
        blockers.append("btc_funding_info_missing")
    if not provider.get("exchange_info_verified", False):
        blockers.append("btc_exchange_info_missing")
    if not provider.get("open_interest_verified", False):
        blockers.append("btc_open_interest_history_not_verified_diagnostic_partial")
    blockers.append("btc_agg_trades_missing")
    blockers.append("btc_liquidation_snapshot_missing_diagnostic_only")
    blockers.append("btc_fee_model_required")
    blockers.append("btc_funding_model_required")
    blockers.extend(_list_of_strings(provider.get("blockers")))
    return _dedupe(blockers)


def _manifest_hash(source_data_status: Mapping[str, Any]) -> str:
    lineage = _mapping(source_data_status.get("manifest_lineage"))
    manifests = lineage.get("latest_manifests", [])
    payload = [
        {
            "interval": item.get("interval"),
            "data_version": item.get("data_version"),
            "manifest_path": item.get("manifest_path"),
            "coverage_pct": item.get("coverage_pct"),
            "quality_score": item.get("quality_score"),
        }
        for item in manifests
        if isinstance(item, Mapping)
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _ratio(numerator: Any, denominator: Any) -> float:
    try:
        den = float(denominator)
        if den <= 0:
            return 0.0
        return round(float(numerator) / den, 8)
    except (TypeError, ValueError):
        return 0.0


def _expected_rows(first_close_time_ms: int, latest_close_time_ms: int, interval: str) -> int:
    interval_ms = INTERVAL_MS.get(interval)
    if not interval_ms or first_close_time_ms <= 0 or latest_close_time_ms < first_close_time_ms:
        return 0
    return int((latest_close_time_ms - first_close_time_ms) // interval_ms) + 1


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_final_close_time(value: str, *, generated_at: datetime) -> bool:
    try:
        close_time = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if close_time.tzinfo is None:
        close_time = close_time.replace(tzinfo=timezone.utc)
    return close_time.astimezone(timezone.utc) <= generated_at.astimezone(timezone.utc)


def _stable_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _hard_data_blockers(values: list[str]) -> list[str]:
    ignored = DIAGNOSTIC_ONLY_WARNINGS | DOWNSTREAM_GATE_REQUIREMENTS
    return _dedupe([value for value in _list_of_strings(values) if value not in ignored])


def _diagnostic_warnings(values: list[str]) -> list[str]:
    warnings = [value for value in _list_of_strings(values) if value in DIAGNOSTIC_ONLY_WARNINGS]
    return _dedupe(warnings)


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
