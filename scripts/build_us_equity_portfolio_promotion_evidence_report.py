#!/usr/bin/env python3
"""Build the read-only US equity portfolio promotion-evidence report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.portfolio.promotion_evidence import (  # noqa: E402
    build_portfolio_promotion_evidence_report,
)


DEFAULT_OUTPUT = Path("artifacts/us_equity_portfolio/latest/portfolio_promotion_evidence_report.json")
DEFAULT_PORTFOLIO_CANONICAL = Path("artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json")
DEFAULT_FIXTURE_LEDGER = Path(
    "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json"
)
DEFAULT_STRATEGY_VALIDATION_GATE = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"
)
DEFAULT_WALK_FORWARD = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json"
)
DEFAULT_COST_STRESS = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_stress_report.json"
)


def build_us_equity_portfolio_promotion_evidence_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    portfolio_canonical_path: Path = DEFAULT_PORTFOLIO_CANONICAL,
    fixture_ledger_path: Path = DEFAULT_FIXTURE_LEDGER,
    strategy_validation_gate_path: Path = DEFAULT_STRATEGY_VALIDATION_GATE,
    walk_forward_path: Path = DEFAULT_WALK_FORWARD,
    cost_stress_path: Path = DEFAULT_COST_STRESS,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    return {
        **build_portfolio_promotion_evidence_report(
            repo_root=root,
            generated_at=generated_at,
            portfolio_canonical=_read_json(_resolve(root, portfolio_canonical_path)),
            fixture_ledger=_read_json(_resolve(root, fixture_ledger_path)),
            strategy_validation_gate=_read_json(_resolve(root, strategy_validation_gate_path)),
            walk_forward_report=_read_json(_resolve(root, walk_forward_path)),
            cost_stress_report=_read_json(_resolve(root, cost_stress_path)),
        ),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "outputs": {"json": str(DEFAULT_OUTPUT)},
    }


def write_us_equity_portfolio_promotion_evidence_report(
    payload: Mapping[str, Any],
    output: Path = DEFAULT_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity portfolio promotion-evidence report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    output = write_us_equity_portfolio_promotion_evidence_report(payload, Path(args.output))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(output)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
