#!/usr/bin/env python3
"""Build a BTC tail dependency diagnostic report from ledger trade PnL."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SOURCE_RUN_DIR = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_tail_dependency/latest")


def build_btc_tail_dependency_report(
    *,
    repo_root: Path | None = None,
    source_run_dir: Path | None = None,
    source_type: str = "research_event_ledger",
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = _resolve(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    trade_ledger = run_dir / "trade_ledger.csv"
    pnl = _read_pnl(trade_ledger)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    blockers: list[str] = []
    if not trade_ledger.exists():
        blockers.append("btc_tail_dependency_ledger_returns_missing")
    if source_type in {"fixture", "sample"}:
        blockers.append(f"btc_tail_dependency_source_type_{source_type}_not_promotion_evidence")
    metrics = _tail_metrics(pnl)
    if not pnl:
        blockers.append("btc_tail_dependency_returns_empty")
    if metrics["tail_event_count"] < 5:
        blockers.append("btc_tail_dependency_event_count_too_low")
    if metrics["single_event_pnl_contribution_ratio"] > 0.25:
        blockers.append("btc_tail_dependency_single_event_contribution_too_high")
    pass_status = bool(pnl) and source_type not in {"fixture", "sample"} and not blockers
    return {
        "schema_version": "btc_tail_dependency_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "source_type": source_type,
        "input_returns_source": _relpath(trade_ledger, root) if trade_ledger.exists() else None,
        "ledger_returns_source": _relpath(trade_ledger, root) if trade_ledger.exists() else None,
        "tail_event_definition": "trade_net_pnl_bottom_5pct_top_5pct",
        "left_tail_threshold": metrics["left_tail_threshold"],
        "right_tail_threshold": metrics["right_tail_threshold"],
        "tail_event_count": metrics["tail_event_count"],
        "worst_tail_loss": metrics["worst_tail_loss"],
        "best_tail_gain": metrics["best_tail_gain"],
        "tail_concentration_ratio": metrics["tail_concentration_ratio"],
        "extreme_event_dependency_score": metrics["extreme_event_dependency_score"],
        "single_event_pnl_contribution_ratio": metrics["single_event_pnl_contribution_ratio"],
        "tail_dependency_pass": pass_status,
        "promotion_evidence": False,
        "blockers": _dedupe(blockers),
    }


def write_btc_tail_dependency_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "tail_dependency_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--source-type", default="research_event_ledger")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_tail_dependency_report(
        repo_root=Path(args.repo_root),
        source_run_dir=Path(args.source_run_dir),
        source_type=args.source_type,
        generated_at=args.generated_at or None,
    )
    print(write_btc_tail_dependency_report(payload, Path(args.output_root)))


def _read_pnl(path: Path) -> list[float]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return [float(row["net_pnl"]) for row in rows if row.get("net_pnl") not in {None, ""}]


def _tail_metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "left_tail_threshold": 0.0,
            "right_tail_threshold": 0.0,
            "tail_event_count": 0,
            "worst_tail_loss": None,
            "best_tail_gain": None,
            "tail_concentration_ratio": 0.0,
            "extreme_event_dependency_score": 0.0,
            "single_event_pnl_contribution_ratio": 0.0,
        }
    ordered = sorted(values)
    left_index = max(0, int(math.floor(len(ordered) * 0.05)) - 1)
    right_index = min(len(ordered) - 1, int(math.ceil(len(ordered) * 0.95)) - 1)
    left = ordered[left_index]
    right = ordered[right_index]
    tails = [value for value in values if value <= left or value >= right]
    abs_total = sum(abs(value) for value in values) or 1.0
    tail_abs = sum(abs(value) for value in tails)
    single = max(abs(value) for value in values) / abs_total
    concentration = tail_abs / abs_total
    return {
        "left_tail_threshold": round(left, 6),
        "right_tail_threshold": round(right, 6),
        "tail_event_count": len(tails),
        "worst_tail_loss": round(min(values), 6),
        "best_tail_gain": round(max(values), 6),
        "tail_concentration_ratio": round(concentration, 6),
        "extreme_event_dependency_score": round(max(concentration, single), 6),
        "single_event_pnl_contribution_ratio": round(single, 6),
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
