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


def build_global_registry(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    btc_registry = _read_json(root / BTC_REGISTRY_PATH)
    btc_items = btc_registry.get("items", {}) if isinstance(btc_registry, dict) else {}
    return {
        "schema_version": "global_research_registry_v1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "paper_queue_status": "locked",
        "live_status": "frozen",
        "candidate_passed_internal_gate": 0,
        "assets": {
            "us_equity": {
                "status": "mainline",
                "latest_data_status": None,
                "latest_factor_evidence": None,
                "latest_portfolio_report": None,
                "current_candidates": [],
            },
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
