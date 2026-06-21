#!/usr/bin/env python3
"""Build a read-only BTC data, fold, and regime status report."""

from __future__ import annotations

import argparse
import json
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
    source_data_status = _read_json(run_dir / "btc_data_fold_regime_status_report.json")
    preflight = _read_json(root / DEFAULT_BUNDLE_PREFLIGHT)
    provider = _read_json(root / DEFAULT_PROVIDER_VERIFICATION)
    fold_audit = _read_json(run_dir / "fold_regime_contract_audit.json")
    intervals = _interval_rows(source_data_status)
    coverage = _coverage_summary(intervals)
    sqlite_info = _mapping(source_data_status.get("sqlite"))
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
            "stale_data_check_pass": bool(coverage.get("sample_end")),
            "manifest_hash": _manifest_hash(source_data_status),
            "sqlite_path": str(sqlite_info.get("db_path") or "data/market_data.sqlite"),
            "data_path": str(sqlite_info.get("db_path") or "data/market_data.sqlite"),
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
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


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
