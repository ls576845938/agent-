from __future__ import annotations

import json
from pathlib import Path

from quant_us.portfolio.fixture_event_ledger import build_portfolio_fixture_event_ledger_report
from scripts.build_global_research_registry import build_global_registry
from scripts.build_us_equity_portfolio_fixture_event_ledger_report import (
    write_portfolio_fixture_event_ledger_report,
)


def test_fixture_ledger_can_be_built(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["schema_version"] == "us_equity_portfolio_fixture_event_ledger_report_v1"
    assert report["source_type"] == "fixture"
    assert report["fixture_chain"]["alpha_scores"]
    assert report["fixture_chain"]["rebalance_orders"]
    assert report["fixture_chain"]["fills"]
    assert report["fixture_chain"]["ledger_pnl"]


def test_fixture_ledger_requires_fills_and_ledger_pnl_fields(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)

    assert report["ledger_validation"]["fills_available"] is True
    assert report["ledger_validation"]["ledger_pnl_available"] is True
    assert report["input_artifacts"]["fills"] == "embedded_fixture:simulated_fills"
    assert report["input_artifacts"]["ledger_pnl"] == "embedded_fixture:ledger_pnl"


def test_fixture_ledger_has_cash_and_position_conservation_checks(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)

    assert report["ledger_validation"]["cash_conservation_check"] is True
    assert report["ledger_validation"]["position_conservation_check"] is True
    assert report["ledger_validation"]["no_short_when_long_only_check"] is True


def test_fixture_source_cannot_be_promotion_ready(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)

    assert report["promotion_ready"] is False
    assert report["promotion_evidence"] is False
    assert "source_type_fixture" in report["blockers"]


def test_fixture_portfolio_report_cannot_allow_paper_review(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)

    assert report["paper_review_allowed"] is False
    assert report["candidate_passed_internal_gate"] == 0
    assert report["paper_queue_status"] == "locked"
    assert report["live_status"] == "frozen"


def test_fixture_portfolio_ledger_writer_persists_artifact(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)
    output = write_portfolio_fixture_event_ledger_report(
        report,
        tmp_path / "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["source_type"] == "fixture"
    assert persisted["promotion_ready"] is False


def test_registry_does_not_treat_fixture_portfolio_ledger_as_candidate(tmp_path: Path) -> None:
    report = build_portfolio_fixture_event_ledger_report(repo_root=tmp_path)
    write_portfolio_fixture_event_ledger_report(
        report,
        tmp_path / "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
    )
    _write_json(
        tmp_path / "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        {
            "schema_version": "us_equity_portfolio_canonical_report_v1",
            "status": "partial",
            "portfolio_run_id": "fixture",
            "event_ledger_status": {"status": "missing"},
            "blockers": ["us_equity_event_ledger_portfolio_backtest_required"],
            "promotion_ready": False,
        },
    )

    registry = build_global_registry(repo_root=tmp_path, generated_at="2026-05-19T00:00:00Z")

    assert registry["assets"]["us_equity"]["current_factor_candidates"] == []
    assert registry["assets"]["us_equity"]["portfolio_evidence"]["promotion_ready"] is False
    assert registry["paper_queue_status"] == "locked"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
