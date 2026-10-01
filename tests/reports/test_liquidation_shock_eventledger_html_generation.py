from pathlib import Path

from scripts.reports.generate_btc_liquidation_shock_eventledger_html import render_report


RUN = Path("artifacts/btc_candidate_validation/20260516T234000Z_liquidation_shock_eventledger")


def test_liquidation_shock_eventledger_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260516T234000Z_liquidation_shock_eventledger" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "event_PF" in html
    assert "liquidation-shock recovery failed event-ledger gate; paper queue remains LOCKED; live remains FROZEN." in html


def test_liquidation_shock_eventledger_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "liquidation_shock_eventledger.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Liquidation-Shock Event-Ledger Candidate Validation Report" in output.read_text(encoding="utf-8")
