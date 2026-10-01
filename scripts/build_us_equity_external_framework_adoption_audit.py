#!/usr/bin/env python3
"""Build an audit report for US equity external framework adoption."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "us_equity_external_framework_adoption_audit_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_external_framework_adoption/latest/us_equity_external_framework_adoption_audit.json")
DEFAULT_MARKDOWN_OUTPUT = Path("docs/integration/US_EQUITY_EXTERNAL_FRAMEWORK_ADOPTION_AUDIT.md")
DEFAULT_REFERENCE_ROOT = Path("D:/quant_open_source_reference")


@dataclass(frozen=True)
class FrameworkRequirement:
    name: str
    purpose: str
    dependency_import: str | None
    dependency_required: bool
    evidence_paths: tuple[str, ...]
    tests: tuple[str, ...]
    required_reference_dir: str = ""
    boundary: str = ""


REQUIREMENTS = (
    FrameworkRequirement(
        name="exchange_calendars / pandas_market_calendars",
        purpose="US equity sessions, holidays, early closes, month-end trading days",
        dependency_import="exchange_calendars",
        dependency_required=True,
        evidence_paths=("quant_us/core/calendar.py",),
        tests=("tests/core/test_us_equity_calendar_external_providers.py",),
        boundary="calendar provider only; strategy and execution logic remain local",
    ),
    FrameworkRequirement(
        name="pandas_market_calendars secondary provider",
        purpose="Calendar parity cross-check",
        dependency_import="pandas_market_calendars",
        dependency_required=True,
        evidence_paths=("quant_us/core/calendar.py",),
        tests=("tests/core/test_us_equity_calendar_external_providers.py",),
        boundary="secondary validation provider, not a separate trading clock",
    ),
    FrameworkRequirement(
        name="QuantStats",
        purpose="Ledger-derived reporting and tear-sheet metrics",
        dependency_import="quantstats",
        dependency_required=True,
        evidence_paths=("quant_us/reports/quantstats_ledger_profile.py",),
        tests=("tests/reports/test_quantstats_ledger_profile.py",),
        boundary="reporting only; metrics source remains local ledger PnL",
    ),
    FrameworkRequirement(
        name="PyPortfolioOpt",
        purpose="Portfolio construction, risk budget, ETF/multi-strategy weights prototype",
        dependency_import="pypfopt",
        dependency_required=True,
        evidence_paths=("quant_us/portfolio/optimizer.py", "integrations/pypfopt_adapter"),
        tests=("tests/portfolio/test_pypfopt_portfolio_candidate.py", "tests/integrations/test_pypfopt_adapter_contract.py"),
        boundary="research candidate weights only; local risk and allocator remain authoritative",
    ),
    FrameworkRequirement(
        name="vectorbt",
        purpose="Fast parameter scan and strategy idea screening",
        dependency_import="vectorbt",
        dependency_required=True,
        evidence_paths=("integrations/vectorbt_adapter",),
        tests=("tests/integrations/test_vectorbt_adapter_contract.py",),
        boundary="screening only; promising ideas must replay through event-driven ledger backtest",
    ),
    FrameworkRequirement(
        name="Qlib",
        purpose="Future ML alpha research line",
        dependency_import="qlib",
        dependency_required=False,
        evidence_paths=("integrations/qlib_adapter", "docs/integration/QLIB_DATA_CONTRACT.md"),
        tests=("tests/integrations/test_qlib_adapter_contract.py", "tests/integrations/test_qlib_to_pypfopt_pipeline.py"),
        boundary="research/model workflow only; not live execution or production data lineage authority",
    ),
    FrameworkRequirement(
        name="OpenBB",
        purpose="Supplemental data exploration and research panel manifest",
        dependency_import="openbb",
        dependency_required=False,
        evidence_paths=("integrations/openbb_adapter",),
        tests=("tests/integrations/test_openbb_adapter_contract.py",),
        boundary="supplemental exploration only; not production PIT source",
    ),
    FrameworkRequirement(
        name="NautilusTrader",
        purpose="Event-driven, order lifecycle and deterministic replay architecture study",
        dependency_import=None,
        dependency_required=False,
        evidence_paths=("docs/integration/EXTERNAL_ENGINE_ARCHITECTURE_STUDY.md",),
        tests=("tests/integrations/test_external_framework_reference_clone_script.py",),
        required_reference_dir="nautilus_trader",
        boundary="reference repo outside import path; no migration",
    ),
    FrameworkRequirement(
        name="QuantConnect LEAN",
        purpose="Algorithm lifecycle, brokerage/data model and CLI architecture study",
        dependency_import=None,
        dependency_required=False,
        evidence_paths=("docs/integration/EXTERNAL_ENGINE_ARCHITECTURE_STUDY.md",),
        tests=("tests/integrations/test_external_framework_reference_clone_script.py",),
        required_reference_dir="Lean",
        boundary="reference repo outside import path; no migration",
    ),
    FrameworkRequirement(
        name="Zipline Reloaded",
        purpose="Bundle, calendar, asset finder and Pipeline architecture study",
        dependency_import=None,
        dependency_required=False,
        evidence_paths=("docs/integration/EXTERNAL_ENGINE_ARCHITECTURE_STUDY.md",),
        tests=("tests/integrations/test_external_framework_reference_clone_script.py",),
        required_reference_dir="zipline-reloaded",
        boundary="reference repo outside import path; no migration",
    ),
)


def build_us_equity_external_framework_adoption_audit(
    *,
    repo_root: Path | None = None,
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    dependency_overrides: dict[str, bool] | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    reference = Path(reference_root)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    rows = [
        _requirement_row(req, root=root, reference_root=reference, dependency_overrides=dependency_overrides or {})
        for req in REQUIREMENTS
    ]
    blocking = [row for row in rows if row["status"] == "missing_required"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "adoption_complete" if not blocking else "adoption_incomplete",
        "summary": {
            "requirement_count": len(rows),
            "complete_count": sum(1 for row in rows if row["status"] == "complete"),
            "optional_dependency_missing_count": sum(1 for row in rows if row["status"] == "complete_optional_dependency_missing"),
            "missing_required_count": len(blocking),
            "reference_root": str(reference),
            "live_order_allowed": False,
            "paper_unlock_allowed": False,
            "third_party_engine_migration_allowed": False,
        },
        "frameworks": rows,
        "guardrails": {
            "external_outputs_are_evidence_inputs_only": True,
            "local_ledger_pnl_authoritative": True,
            "local_promotion_gate_authoritative": True,
            "strategy_may_not_import_broker_or_live": True,
            "qlib_openbb_are_optional_research_surfaces": True,
        },
        "outputs": {
            "json": str((root / output).resolve()),
            "markdown": str((root / markdown_output).resolve()),
        },
    }
    _write_json(root / output, payload)
    _write_text(root / markdown_output, _markdown(payload))
    return payload


def _requirement_row(
    req: FrameworkRequirement,
    *,
    root: Path,
    reference_root: Path,
    dependency_overrides: dict[str, bool],
) -> dict[str, Any]:
    evidence = [{"path": path, "exists": (root / path).exists()} for path in req.evidence_paths]
    tests = [{"path": path, "exists": (root / path).exists()} for path in req.tests]
    dependency_available = True
    if req.dependency_import:
        dependency_available = dependency_overrides.get(req.dependency_import, _module_available(req.dependency_import))
    reference_exists = True
    reference_path = ""
    if req.required_reference_dir:
        reference_path = str(reference_root / req.required_reference_dir)
        reference_exists = (reference_root / req.required_reference_dir).exists()
    required_missing = (
        any(not item["exists"] for item in evidence)
        or any(not item["exists"] for item in tests)
        or (req.dependency_required and not dependency_available)
        or (bool(req.required_reference_dir) and not reference_exists)
    )
    if required_missing:
        status = "missing_required"
    elif req.dependency_import and not req.dependency_required and not dependency_available:
        status = "complete_optional_dependency_missing"
    else:
        status = "complete"
    return {
        "name": req.name,
        "status": status,
        "purpose": req.purpose,
        "dependency_import": req.dependency_import or "",
        "dependency_required": req.dependency_required,
        "dependency_available": dependency_available,
        "evidence_paths": evidence,
        "tests": tests,
        "reference_path": reference_path,
        "reference_exists": reference_exists,
        "boundary": req.boundary,
    }


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, encoding="utf-8").strip()
    except Exception:
        return ""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# US Equity External Framework Adoption Audit",
        "",
        f"- Status: `{payload['status']}`",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Commit: `{payload['commit']}`",
        f"- Reference root: `{payload['summary']['reference_root']}`",
        "",
        "| Framework | Status | Dependency | Reference | Boundary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["frameworks"]:
        dependency = "n/a"
        if row["dependency_import"]:
            dependency = f"{row['dependency_import']}={'yes' if row['dependency_available'] else 'no'}"
        reference = "n/a"
        if row["reference_path"]:
            reference = "yes" if row["reference_exists"] else "no"
        lines.append(
            f"| {row['name']} | `{row['status']}` | {dependency} | {reference} | {row['boundary']} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- External framework output is evidence input only.",
            "- Local ledger PnL and local promotion gates remain authoritative.",
            "- Qlib and OpenBB remain optional research surfaces.",
            "- NautilusTrader, LEAN, and Zipline Reloaded are reference repos outside the import path.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity external framework adoption audit.")
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--reference-root", default=str(DEFAULT_REFERENCE_ROOT), help="External reference clone root.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON output path.")
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT), help="Markdown output path.")
    args = parser.parse_args()
    payload = build_us_equity_external_framework_adoption_audit(
        repo_root=Path(args.repo_root),
        reference_root=Path(args.reference_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
    )
    print(json.dumps({"status": payload["status"], "summary": payload["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
