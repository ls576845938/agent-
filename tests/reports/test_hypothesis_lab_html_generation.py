from pathlib import Path

from scripts.reports.generate_btc_hypothesis_lab_html import render_report


RUN = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion")


def test_hypothesis_lab_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260516T122000Z_compression_expansion" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "Hypothesis Decision" in html
    assert "hypothesis passed; strategy skeleton generated; paper queue remains LOCKED; live remains FROZEN." in html


def test_hypothesis_lab_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "compression_expansion_report.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Compression-to-Expansion Event Breakout Research Report" in output.read_text(encoding="utf-8")
