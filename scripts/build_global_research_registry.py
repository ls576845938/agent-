#!/usr/bin/env python3
"""Build a read-only QuantStation global research registry.

The builder only summarizes existing artifacts. It does not run backtests,
paper runtimes, live runtimes, brokers, optimizers, or strategy generation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT = Path("artifacts/global_research_registry/research_registry.json")
BTC_REGISTRY_PATH = Path("artifacts/btc_research_registry/research_registry.json")
DATA_MANIFEST_ROOT = Path("data/manifests")
QLIB_RUNS_ROOT = Path("artifacts/qlib_runs")
PORTFOLIO_RUNS_ROOT = Path("artifacts/portfolio_runs")
GENERATED_FACTORS_PATH = Path("data/research/generated_factors/factors.json")
GENERATED_STRATEGIES_ROOT = Path("data/research/generated_strategies")
FACTOR_MINING_ROOT = Path("data/research/factor_mining")
US_EQUITY_DATA_STATUS_REPORT = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
US_EQUITY_UNIVERSE_MANIFEST = Path("artifacts/us_equity_data_status/latest/universe_manifest.json")
US_EQUITY_CORPORATE_ACTION_REPORT = Path("artifacts/us_equity_data_status/latest/corporate_action_report.json")


def build_global_registry(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    btc_registry = _read_json(root / BTC_REGISTRY_PATH)
    btc_items = btc_registry.get("items", {}) if isinstance(btc_registry, dict) else {}
    us_equity = _build_us_equity_summary(root)
    return {
        "schema_version": "global_research_registry_v1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "paper_queue_status": "locked",
        "live_status": "frozen",
        "candidate_passed_internal_gate": 0,
        "assets": {
            "us_equity": us_equity,
            "btc": {
                "status": "research_sandbox",
                "latest_registry": str(BTC_REGISTRY_PATH),
                "current_candidates": _btc_current_candidates(btc_items),
                "archived_or_rejected": _btc_archived_or_rejected(btc_items),
            },
        },
    }


def write_registry(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_global_registry(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    output = write_registry(payload, Path(args.output))
    print(output)


def _btc_current_candidates(items: Mapping[str, Any]) -> list[dict[str, str]]:
    compression = items.get("compression_expansion_breakout", {})
    return [
        {
            "name": "compression_expansion_breakout",
            "status": str(compression.get("status", "candidate_gate_failed")),
            "allowed_next_action": "attribution_only",
        }
    ]


def _btc_archived_or_rejected(items: Mapping[str, Any]) -> list[str]:
    names = []
    for name, row in sorted(items.items()):
        status = str(row.get("status", ""))
        if status in {"archived", "hypothesis_rejected"}:
            names.append(name)
    fallback = [
        "perp_dual_trend",
        "low_vol_uptrend",
        "liquidation_shock_recovery",
        "range_reclaim_momentum",
    ]
    return names or fallback


def _build_us_equity_summary(root: Path) -> dict[str, Any]:
    data_lineage = _us_data_lineage(root)
    factor_evidence = _us_factor_evidence(root)
    portfolio_evidence = _us_portfolio_evidence(root)
    candidates = _us_current_candidates(root)
    blockers = _merge_blockers(
        data_lineage.get("blockers", []),
        factor_evidence.get("blockers", []),
        portfolio_evidence.get("blockers", []),
    )
    return {
        "status": "mainline",
        "latest_data_status": data_lineage.get("data_status_report")
        or data_lineage.get("latest_data_manifest"),
        "latest_factor_evidence": factor_evidence.get("latest_factor_mining_report"),
        "latest_portfolio_report": portfolio_evidence.get("latest_portfolio_run_manifest"),
        "data_lineage": data_lineage,
        "factor_evidence": factor_evidence,
        "portfolio_evidence": portfolio_evidence,
        "blockers": blockers,
        "allowed_next_actions": [
            "build_us_equity_data_status_report",
            "standardize_factor_evidence_pack",
            "internal_event_backtest_required",
        ],
        "current_candidates": candidates,
    }


def _us_data_lineage(root: Path) -> dict[str, Any]:
    data_status_path = root / US_EQUITY_DATA_STATUS_REPORT
    universe_manifest_path = root / US_EQUITY_UNIVERSE_MANIFEST
    corporate_action_report_path = root / US_EQUITY_CORPORATE_ACTION_REPORT
    data_status = _read_json(data_status_path)
    universe_manifest = _read_json(universe_manifest_path)
    corporate_action_report = _read_json(corporate_action_report_path)
    manifest_paths = [
        path
        for path in sorted((root / DATA_MANIFEST_ROOT).glob("*.json"))
        if not path.stem.startswith("run_")
    ]
    manifest_items = [
        (path, payload)
        for path in manifest_paths
        for payload in [_read_json(path)]
        if _looks_like_us_equity_manifest(payload)
    ]
    manifests = [payload for _, payload in manifest_items]
    latest_path = _latest_existing_path([path for path, _ in manifest_items])
    survivorship_values = sorted(
        {
            str(item.get("survivorship_bias_risk", "unknown") or "unknown")
            for item in manifests
        }
    )
    adjustment_policies = sorted(
        {
            str(
                item.get("adjustment_policy")
                or item.get("corporate_action_adjustment")
                or item.get("adjustment")
                or "unknown"
            )
            for item in manifests
        }
    )
    blockers: list[str] = []
    if not data_status_path.exists():
        blockers.append("us_equity_data_status_report_missing")
    if not manifests:
        blockers.append("us_equity_data_manifest_missing")
    if not universe_manifest_path.exists():
        blockers.append("us_equity_universe_manifest_missing")
    elif isinstance(universe_manifest.get("blockers"), list):
        blockers.extend(str(item) for item in universe_manifest["blockers"])
    if not corporate_action_report_path.exists():
        blockers.append("us_equity_corporate_action_report_missing")
    elif isinstance(corporate_action_report.get("blockers"), list):
        blockers.extend(str(item) for item in corporate_action_report["blockers"])
    if isinstance(data_status.get("blockers"), list):
        blockers.extend(str(item) for item in data_status["blockers"])
    if not survivorship_values or "unknown" in survivorship_values:
        blockers.append("us_equity_survivorship_status_unconfirmed")
    blockers = _merge_blockers(blockers)
    data_status_report = _relpath(data_status_path, root) if data_status_path.exists() else None
    universe_manifest_report = _relpath(universe_manifest_path, root) if universe_manifest_path.exists() else None
    corporate_action_report_ref = (
        _relpath(corporate_action_report_path, root)
        if corporate_action_report_path.exists()
        else None
    )
    status = "missing" if not manifests else ("complete" if not blockers else "partial")
    return {
        "status": status,
        "data_status_report": data_status_report,
        "latest_data_manifest": _relpath(latest_path, root) if latest_path else None,
        "manifest_count": len(manifests),
        "data_versions": [
            str(item.get("data_version", ""))
            for item in manifests
            if item.get("data_version")
        ][:50],
        "symbols": sorted({str(item.get("symbol", "")) for item in manifests if item.get("symbol")})[:100],
        "universe_manifest": universe_manifest_report,
        "corporate_action_report": corporate_action_report_ref,
        "survivorship_status": "mixed" if len(survivorship_values) > 1 else (survivorship_values[0] if survivorship_values else "unknown"),
        "adjustment_policies": adjustment_policies,
        "blockers": blockers,
    }


def _us_factor_evidence(root: Path) -> dict[str, Any]:
    factor_mining_reports = sorted((root / FACTOR_MINING_ROOT).glob("*.json"))
    generated_strategies = sorted((root / GENERATED_STRATEGIES_ROOT).glob("*.json"))
    latest_factor_mining = _latest_existing_path(factor_mining_reports)
    generated_factors_exists = (root / GENERATED_FACTORS_PATH).exists()
    blockers: list[str] = []
    if not latest_factor_mining and not generated_strategies:
        blockers.append("us_equity_factor_evidence_missing")
    if not generated_factors_exists:
        blockers.append("us_equity_generated_factor_registry_missing")
    blockers.append("us_equity_factor_evidence_pack_schema_required")
    return {
        "status": "partial" if (latest_factor_mining or generated_strategies or generated_factors_exists) else "missing",
        "latest_factor_mining_report": _relpath(latest_factor_mining, root) if latest_factor_mining else None,
        "generated_factors_path": str(GENERATED_FACTORS_PATH) if generated_factors_exists else None,
        "generated_strategy_count": len(generated_strategies),
        "blockers": blockers,
    }


def _us_portfolio_evidence(root: Path) -> dict[str, Any]:
    run_manifests = sorted((root / PORTFOLIO_RUNS_ROOT).glob("*/run_manifest.json"))
    latest_manifest = _latest_existing_path(run_manifests)
    blockers: list[str] = []
    if not latest_manifest:
        blockers.append("us_equity_portfolio_report_missing")
    blockers.append("us_equity_portfolio_canonical_report_required")
    blockers.append("us_equity_event_ledger_portfolio_backtest_required")
    return {
        "status": "research_only" if latest_manifest else "missing",
        "latest_portfolio_run_manifest": _relpath(latest_manifest, root) if latest_manifest else None,
        "portfolio_run_count": len(run_manifests),
        "blockers": blockers,
    }


def _us_current_candidates(root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in sorted((root / QLIB_RUNS_ROOT).glob("*/qlib_strategy_manifest.json")):
        manifest = _read_json(path)
        if not manifest:
            continue
        candidates.append(
            {
                "name": str(manifest.get("strategy_id") or manifest.get("run_id") or path.parent.name),
                "source": "qlib",
                "status": "evidence_candidate",
                "evidence_path": _relpath(path, root),
                "data_versions": [str(item) for item in manifest.get("data_versions", [])],
                "blockers": [
                    "internal_event_ledger_backtest_required",
                    "cost_stress_required",
                    "walk_forward_required",
                    "regime_report_required",
                    "promotion_gate_required",
                ],
                "allowed_next_action": "internal_event_backtest_required",
            }
        )
    return candidates[:20]


def _merge_blockers(*groups: object) -> list[str]:
    blockers: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            text = str(item)
            if text and text not in blockers:
                blockers.append(text)
    return blockers


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _looks_like_data_manifest(data: Mapping[str, Any]) -> bool:
    return all(data.get(key) for key in ("data_version", "source", "symbol", "interval"))


def _looks_like_us_equity_manifest(data: Mapping[str, Any]) -> bool:
    if not _looks_like_data_manifest(data):
        return False
    source = str(data.get("source", "")).lower()
    asset_class = str(data.get("asset_class", "equity")).lower()
    return source in {"yfinance", "alpaca"} and asset_class == "equity"


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
