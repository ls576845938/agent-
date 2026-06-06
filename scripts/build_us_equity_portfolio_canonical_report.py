#!/usr/bin/env python3
"""Build read-only US equity portfolio canonical report artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_portfolio/latest")
PORTFOLIO_RUNS_ROOT = Path("artifacts/portfolio_runs")
FACTOR_EVIDENCE_PACK = Path("artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json")
FIXTURE_EVENT_LEDGER_REPORT = Path(
    "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json"
)


def build_us_equity_portfolio_canonical_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    run_manifests = sorted((root / PORTFOLIO_RUNS_ROOT).glob("*/run_manifest.json"))
    latest_manifest_path = _latest_existing_path(run_manifests)
    latest_manifest = _read_json(latest_manifest_path) if latest_manifest_path else {}
    factor_pack_path = root / FACTOR_EVIDENCE_PACK
    fixture_ledger_path = root / FIXTURE_EVENT_LEDGER_REPORT
    fixture_ledger = _read_json(fixture_ledger_path)
    target_weights_path = _resolve_output_path(
        root=root,
        run_manifest=latest_manifest,
        run_manifest_path=latest_manifest_path,
        output_key="target_weights",
    )
    target_positions_path = _resolve_output_path(
        root=root,
        run_manifest=latest_manifest,
        run_manifest_path=latest_manifest_path,
        output_key="target_positions",
    )
    target_weights = _read_target_weights(target_weights_path)
    exposure_report = _build_exposure_report(
        generated_at=generated,
        target_weights=target_weights,
        target_weights_path=_relpath(target_weights_path, root) if target_weights_path else None,
    )
    cost_stress_report = _build_cost_stress_report(generated_at=generated)
    rebalance_drift_report = _build_rebalance_drift_report(
        generated_at=generated,
        target_weights=target_weights,
        max_turnover=_config_float(latest_manifest, "max_turnover"),
    )
    blockers = _build_blockers(
        latest_manifest_path=latest_manifest_path,
        factor_pack_exists=factor_pack_path.exists(),
        target_weights_path=target_weights_path,
        target_weights=target_weights,
        exposure_report=exposure_report,
        cost_stress_report=cost_stress_report,
        fixture_ledger=fixture_ledger,
    )
    portfolio_evidence_maturity = _portfolio_evidence_maturity(
        fixture_ledger=fixture_ledger,
        exposure_report=exposure_report,
        cost_stress_report=cost_stress_report,
    )
    ledger_validation = _ledger_validation(fixture_ledger=fixture_ledger)
    report = {
        "schema_version": "us_equity_portfolio_canonical_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "missing" if latest_manifest_path is None else ("complete" if not blockers else "partial"),
        "portfolio_run_id": str(latest_manifest.get("portfolio_run_id", "")),
        "source_score_run_id": str(latest_manifest.get("source_score_run_id", "")),
        "source_run_manifest": _relpath(latest_manifest_path, root) if latest_manifest_path else None,
        "factor_evidence_pack": _relpath(factor_pack_path, root) if factor_pack_path.exists() else None,
        "dependency_available": bool(latest_manifest.get("dependency_available", False)),
        "fallback_used": bool(latest_manifest.get("fallback_used", False)),
        "optimizer": str(_mapping(latest_manifest.get("config")).get("optimizer", "")),
        "constraints_hash": str(_mapping(latest_manifest.get("config")).get("constraints_hash", "")),
        "target_weights_path": _relpath(target_weights_path, root) if target_weights_path else None,
        "target_positions_path": _relpath(target_positions_path, root) if target_positions_path else None,
        "weight_summary": _weight_summary(target_weights),
        "exposure_report_path": str(DEFAULT_OUTPUT_ROOT / "exposure_report.json"),
        "cost_stress_report_path": str(DEFAULT_OUTPUT_ROOT / "cost_stress_report.json"),
        "rebalance_drift_report_path": str(DEFAULT_OUTPUT_ROOT / "rebalance_drift_report.json"),
        "portfolio_fixture_event_ledger_report": _relpath(fixture_ledger_path, root) if fixture_ledger_path.exists() else None,
        "portfolio_evidence_maturity": portfolio_evidence_maturity,
        "ledger_validation": ledger_validation,
        "event_ledger_status": {
            "status": "missing",
            "required": True,
            "blocker": "us_equity_event_ledger_portfolio_backtest_required",
        },
        "required_evidence": [
            "factor_evidence_pack",
            "target_weights",
            "exposure_report",
            "cost_stress_report",
            "rebalance_drift_report",
            "event_ledger_portfolio_backtest",
            "ledger_pnl",
            "walk_forward",
            "promotion_gate",
        ],
        "blockers": blockers,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
    }
    return {
        "portfolio_canonical_report": report,
        "exposure_report": exposure_report,
        "cost_stress_report": cost_stress_report,
        "rebalance_drift_report": rebalance_drift_report,
    }


def write_us_equity_portfolio_canonical_report(
    payload: Mapping[str, Any],
    output_root: Path,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "portfolio_canonical_report": output_root / "portfolio_canonical_report.json",
        "exposure_report": output_root / "exposure_report.json",
        "cost_stress_report": output_root / "cost_stress_report.json",
        "rebalance_drift_report": output_root / "rebalance_drift_report.json",
    }
    payload_to_write = {key: dict(payload[key]) for key in paths}
    payload_to_write["portfolio_canonical_report"]["exposure_report_path"] = str(paths["exposure_report"])
    payload_to_write["portfolio_canonical_report"]["cost_stress_report_path"] = str(paths["cost_stress_report"])
    payload_to_write["portfolio_canonical_report"]["rebalance_drift_report_path"] = str(paths["rebalance_drift_report"])
    for key, path in paths.items():
        path.write_text(json.dumps(payload_to_write[key], indent=2, sort_keys=True), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_us_equity_portfolio_canonical_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    paths = write_us_equity_portfolio_canonical_report(payload, Path(args.output_root))
    print(json.dumps(paths, indent=2, sort_keys=True))


def _build_exposure_report(
    *,
    generated_at: str,
    target_weights: pd.DataFrame,
    target_weights_path: str | None,
) -> dict[str, Any]:
    latest = _latest_weights(target_weights)
    weights = _weights_by_symbol(latest)
    gross = sum(abs(value) for value in weights.values())
    net = sum(weights.values())
    max_symbol_weight = max((abs(value) for value in weights.values()), default=0.0)
    hhi = sum(value * value for value in weights.values())
    return {
        "schema_version": "us_equity_portfolio_exposure_report_v1",
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": "missing" if target_weights.empty else "partial",
        "target_weights_path": target_weights_path,
        "timestamp": _latest_timestamp(latest),
        "symbol_count": len(weights),
        "gross_exposure": round(gross, 10),
        "net_exposure": round(net, 10),
        "max_symbol_weight": round(max_symbol_weight, 10),
        "hhi": round(hhi, 10),
        "single_symbol_weights": {symbol: round(value, 10) for symbol, value in sorted(weights.items())},
        "sector_exposures": {},
        "style_exposures": {},
        "blockers": [
            "us_equity_sector_exposure_missing",
            "us_equity_style_exposure_missing",
        ],
        "promotion_ready": False,
    }


def _build_cost_stress_report(*, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": "us_equity_portfolio_cost_stress_report_v1",
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": "missing",
        "commission_model": None,
        "slippage_model": None,
        "market_impact_model": None,
        "borrow_cost_model": None,
        "stress_scenarios": [],
        "blockers": ["us_equity_portfolio_cost_stress_required"],
        "promotion_ready": False,
    }


def _build_rebalance_drift_report(
    *,
    generated_at: str,
    target_weights: pd.DataFrame,
    max_turnover: float,
) -> dict[str, Any]:
    turnover_values: list[float] = []
    if "turnover_from_previous" in target_weights.columns:
        sample = target_weights[["datetime", "turnover_from_previous"]].dropna()
        if not sample.empty:
            turnover_values = [
                float(value)
                for value in sample.groupby("datetime")["turnover_from_previous"].max().tolist()
            ]
    max_observed = max(turnover_values, default=0.0)
    return {
        "schema_version": "us_equity_portfolio_rebalance_drift_report_v1",
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": "missing" if target_weights.empty else "partial",
        "rebalance_count": len(turnover_values),
        "max_observed_turnover": round(max_observed, 10),
        "avg_observed_turnover": round(sum(turnover_values) / len(turnover_values), 10) if turnover_values else 0.0,
        "configured_max_turnover": round(max_turnover, 10),
        "turnover_limit_passed": bool(turnover_values and (max_turnover <= 0.0 or max_observed <= max_turnover + 1e-9)),
        "blockers": ["us_equity_rebalance_drift_event_ledger_required"],
        "promotion_ready": False,
    }


def _build_blockers(
    *,
    latest_manifest_path: Path | None,
    factor_pack_exists: bool,
    target_weights_path: Path | None,
    target_weights: pd.DataFrame,
    exposure_report: Mapping[str, Any],
    cost_stress_report: Mapping[str, Any],
    fixture_ledger: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if latest_manifest_path is None:
        blockers.append("us_equity_portfolio_run_manifest_missing")
    if not factor_pack_exists:
        blockers.append("us_equity_factor_evidence_pack_required")
    if target_weights_path is None or not target_weights_path.exists():
        blockers.append("us_equity_target_weights_missing")
    if target_weights.empty:
        blockers.append("us_equity_target_weights_unreadable_or_empty")
    if exposure_report.get("blockers"):
        blockers.extend(str(item) for item in exposure_report["blockers"])
    if cost_stress_report.get("blockers"):
        blockers.extend(str(item) for item in cost_stress_report["blockers"])
    if fixture_ledger:
        blockers.append("us_equity_fixture_ledger_not_promotion_evidence")
    blockers.append("us_equity_event_ledger_portfolio_backtest_required")
    blockers.append("us_equity_ledger_pnl_required")
    blockers.append("us_equity_portfolio_walk_forward_required")
    blockers.append("us_equity_promotion_gate_required")
    return _dedupe(blockers)


def _portfolio_evidence_maturity(
    *,
    fixture_ledger: Mapping[str, Any],
    exposure_report: Mapping[str, Any],
    cost_stress_report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "contract_ready": True,
        "fixture_ledger_available": bool(fixture_ledger),
        "sample_ledger_available": False,
        "production_ledger_available": False,
        "event_ledger_validated": False,
        "cost_stress_available": not bool(cost_stress_report.get("blockers")),
        "walk_forward_available": False,
        "exposure_report_available": bool(exposure_report) and exposure_report.get("status") != "missing",
        "promotion_ready": False,
    }


def _ledger_validation(*, fixture_ledger: Mapping[str, Any]) -> dict[str, Any]:
    fixture_validation = _mapping(fixture_ledger.get("ledger_validation"))
    source_type = str(fixture_ledger.get("source_type") or "none")
    fills_available = bool(fixture_validation.get("fills_available", False))
    ledger_pnl_available = bool(fixture_validation.get("ledger_pnl_available", False))
    cost_model_available = bool(fixture_validation.get("cost_model_applied", False))
    cash_conservation_pass = bool(fixture_validation.get("cash_conservation_check", False))
    position_conservation_pass = bool(fixture_validation.get("position_conservation_check", False))
    blockers = [
        "production_data_required",
        "production_event_ledger_required",
        "event_ledger_candidate_required",
    ]
    if source_type in {"fixture", "sample"}:
        blockers.append(f"source_type_{source_type}_not_promotion_evidence")
    if not fills_available:
        blockers.append("fills_required")
    if not ledger_pnl_available:
        blockers.append("ledger_pnl_required")
    if not cost_model_available:
        blockers.append("cost_model_required")
    return {
        "source_type": source_type,
        "fills_available": fills_available,
        "ledger_pnl_available": ledger_pnl_available,
        "cost_model_available": cost_model_available,
        "cash_conservation_pass": cash_conservation_pass,
        "position_conservation_pass": position_conservation_pass,
        "event_ledger_candidate": False,
        "production_data_required": True,
        "blockers": _dedupe(blockers),
    }


def _weight_summary(target_weights: pd.DataFrame) -> dict[str, Any]:
    latest = _latest_weights(target_weights)
    weights = _weights_by_symbol(latest)
    gross = sum(abs(value) for value in weights.values())
    max_symbol = max((abs(value) for value in weights.values()), default=0.0)
    return {
        "timestamp": _latest_timestamp(latest),
        "symbol_count": len(weights),
        "gross_weight": round(gross, 10),
        "net_weight": round(sum(weights.values()), 10),
        "cash_weight_estimate": round(max(0.0, 1.0 - gross), 10),
        "max_symbol_weight": round(max_symbol, 10),
        "top_symbols": [
            {"symbol": symbol, "target_weight": round(weight, 10)}
            for symbol, weight in sorted(weights.items(), key=lambda item: (-abs(item[1]), item[0]))[:20]
        ],
    }


def _latest_weights(target_weights: pd.DataFrame) -> pd.DataFrame:
    if target_weights.empty or "datetime" not in target_weights.columns:
        return pd.DataFrame()
    frame = target_weights.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["datetime"])
    if frame.empty:
        return pd.DataFrame()
    latest_timestamp = frame["datetime"].max()
    return frame[frame["datetime"] == latest_timestamp].copy()


def _weights_by_symbol(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty or "symbol" not in frame.columns or "target_weight" not in frame.columns:
        return {}
    result: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).upper()
        if not symbol:
            continue
        result[symbol] = result.get(symbol, 0.0) + float(getattr(row, "target_weight", 0.0) or 0.0)
    return result


def _latest_timestamp(frame: pd.DataFrame) -> str:
    if frame.empty or "datetime" not in frame.columns:
        return ""
    value = pd.to_datetime(frame["datetime"], utc=True, errors="coerce").max()
    return "" if pd.isna(value) else pd.Timestamp(value).isoformat()


def _read_target_weights(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _resolve_output_path(
    *,
    root: Path,
    run_manifest: Mapping[str, Any],
    run_manifest_path: Path | None,
    output_key: str,
) -> Path | None:
    outputs = _mapping(run_manifest.get("output_files"))
    raw = str(outputs.get(output_key, "") or "")
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else root / path
    if run_manifest_path is None:
        return None
    candidate = run_manifest_path.parent / f"{output_key}.parquet"
    return candidate if candidate.exists() else None


def _config_float(run_manifest: Mapping[str, Any], key: str) -> float:
    value = _mapping(run_manifest.get("config")).get(key, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _latest_existing_path(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


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
