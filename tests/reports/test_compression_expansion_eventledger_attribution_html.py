from pathlib import Path

from scripts.reports.generate_btc_compression_expansion_eventledger_attribution_html import render_report


RUN = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def test_compression_expansion_eventledger_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260516T133000Z_compression_expansion_eventledger" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "event_PF" in html
    assert "compression-expansion failed event-ledger gate; paper queue remains LOCKED; live remains FROZEN." in html


def test_compression_expansion_eventledger_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "compression_expansion_eventledger.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Compression-Expansion Event-Ledger Attribution Report" in output.read_text(encoding="utf-8")
