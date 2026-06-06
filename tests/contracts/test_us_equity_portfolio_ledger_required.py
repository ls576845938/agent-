from __future__ import annotations

from pathlib import Path

from quant_us.portfolio.fixture_event_ledger import build_portfolio_fixture_event_ledger_report
from scripts.build_us_equity_portfolio_canonical_report import build_us_equity_portfolio_canonical_report
from scripts.build_us_equity_portfolio_fixture_event_ledger_report import (
    write_portfolio_fixture_event_ledger_report,
)


def test_portfolio_canonical_report_records_fixture_maturity_but_blocks_promotion(tmp_path: Path) -> None:
    fixture_report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)
    write_portfolio_fixture_event_ledger_report(
        fixture_report,
        tmp_path / "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
    )

    payload = build_us_equity_portfolio_canonical_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )
    report = payload["portfolio_canonical_report"]

    assert report["portfolio_evidence_maturity"]["contract_ready"] is True
    assert report["portfolio_evidence_maturity"]["fixture_ledger_available"] is True
    assert report["portfolio_evidence_maturity"]["production_ledger_available"] is False
    assert report["portfolio_evidence_maturity"]["promotion_ready"] is False
    assert report["promotion_ready"] is False


def test_portfolio_canonical_report_requires_fills_and_ledger_pnl_for_promotion(tmp_path: Path) -> None:
    report = build_us_equity_portfolio_canonical_report(repo_root=tmp_path)["portfolio_canonical_report"]

    assert report["ledger_validation"]["fills_available"] is False
    assert report["ledger_validation"]["ledger_pnl_available"] is False
    assert "fills_required" in report["ledger_validation"]["blockers"]
    assert "ledger_pnl_required" in report["ledger_validation"]["blockers"]
    assert report["promotion_ready"] is False


def test_portfolio_canonical_report_blocks_optimizer_only_outputs(tmp_path: Path) -> None:
    report = build_us_equity_portfolio_canonical_report(repo_root=tmp_path)["portfolio_canonical_report"]

    assert report["ledger_validation"]["event_ledger_candidate"] is False
    assert report["ledger_validation"]["production_data_required"] is True
    assert "production_event_ledger_required" in report["ledger_validation"]["blockers"]
    assert "us_equity_event_ledger_portfolio_backtest_required" in report["blockers"]


def test_fixture_ledger_is_not_event_ledger_candidate(tmp_path: Path) -> None:
    fixture_report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)
    write_portfolio_fixture_event_ledger_report(
        fixture_report,
        tmp_path / "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
    )

    report = build_us_equity_portfolio_canonical_report(repo_root=tmp_path)["portfolio_canonical_report"]

    assert report["ledger_validation"]["source_type"] == "fixture"
    assert report["ledger_validation"]["fills_available"] is True
    assert report["ledger_validation"]["ledger_pnl_available"] is True
    assert report["ledger_validation"]["event_ledger_candidate"] is False
    assert "source_type_fixture_not_promotion_evidence" in report["ledger_validation"]["blockers"]
