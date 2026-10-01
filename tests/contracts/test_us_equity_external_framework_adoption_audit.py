from __future__ import annotations

from pathlib import Path

from scripts.build_us_equity_external_framework_adoption_audit import (
    build_us_equity_external_framework_adoption_audit,
)


REQUIRED_PATHS = [
    "quant_us/core/calendar.py",
    "tests/core/test_us_equity_calendar_external_providers.py",
    "quant_us/reports/quantstats_ledger_profile.py",
    "tests/reports/test_quantstats_ledger_profile.py",
    "quant_us/portfolio/optimizer.py",
    "integrations/pypfopt_adapter",
    "tests/portfolio/test_pypfopt_portfolio_candidate.py",
    "tests/integrations/test_pypfopt_adapter_contract.py",
    "integrations/vectorbt_adapter",
    "tests/integrations/test_vectorbt_adapter_contract.py",
    "integrations/qlib_adapter",
    "docs/integration/QLIB_DATA_CONTRACT.md",
    "tests/integrations/test_qlib_adapter_contract.py",
    "tests/integrations/test_qlib_to_pypfopt_pipeline.py",
    "integrations/openbb_adapter",
    "tests/integrations/test_openbb_adapter_contract.py",
    "docs/integration/EXTERNAL_ENGINE_ARCHITECTURE_STUDY.md",
    "tests/integrations/test_external_framework_reference_clone_script.py",
]


def test_external_framework_adoption_audit_allows_optional_qlib_openbb_dependency_gap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    refs = tmp_path / "refs"
    _touch_required_paths(repo)
    for name in ("nautilus_trader", "Lean", "zipline-reloaded"):
        (refs / name).mkdir(parents=True)

    payload = build_us_equity_external_framework_adoption_audit(
        repo_root=repo,
        reference_root=refs,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-07-08T00:00:00+00:00",
        dependency_overrides={
            "exchange_calendars": True,
            "pandas_market_calendars": True,
            "quantstats": True,
            "pypfopt": True,
            "vectorbt": True,
            "qlib": False,
            "openbb": False,
        },
    )

    assert payload["status"] == "adoption_complete"
    assert payload["summary"]["optional_dependency_missing_count"] == 2
    assert payload["summary"]["live_order_allowed"] is False
    qlib = _row(payload, "Qlib")
    assert qlib["status"] == "complete_optional_dependency_missing"
    openbb = _row(payload, "OpenBB")
    assert openbb["status"] == "complete_optional_dependency_missing"


def test_external_framework_adoption_audit_blocks_missing_required_dependency(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    refs = tmp_path / "refs"
    _touch_required_paths(repo)
    for name in ("nautilus_trader", "Lean", "zipline-reloaded"):
        (refs / name).mkdir(parents=True)

    payload = build_us_equity_external_framework_adoption_audit(
        repo_root=repo,
        reference_root=refs,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        dependency_overrides={
            "exchange_calendars": False,
            "pandas_market_calendars": True,
            "quantstats": True,
            "pypfopt": True,
            "vectorbt": True,
        },
    )

    assert payload["status"] == "adoption_incomplete"
    assert _row(payload, "exchange_calendars / pandas_market_calendars")["status"] == "missing_required"


def test_external_framework_adoption_audit_blocks_missing_reference_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    refs = tmp_path / "refs"
    _touch_required_paths(repo)

    payload = build_us_equity_external_framework_adoption_audit(
        repo_root=repo,
        reference_root=refs,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        dependency_overrides={
            "exchange_calendars": True,
            "pandas_market_calendars": True,
            "quantstats": True,
            "pypfopt": True,
            "vectorbt": True,
        },
    )

    assert payload["status"] == "adoption_incomplete"
    assert _row(payload, "NautilusTrader")["status"] == "missing_required"


def _touch_required_paths(repo: Path) -> None:
    for rel in REQUIRED_PATHS:
        path = repo / rel
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)


def _row(payload: dict, name: str) -> dict:
    return next(row for row in payload["frameworks"] if row["name"] == name)
