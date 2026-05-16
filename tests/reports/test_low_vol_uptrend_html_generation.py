from pathlib import Path

from scripts.reports.generate_btc_low_vol_uptrend_hypothesis_html import render_report


RUN = Path("artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend")


def test_low_vol_uptrend_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260516T120000Z_lowvol_uptrend" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "Hypothesis Decision" in html
    assert "hypothesis rejected; no strategy generated; paper queue remains LOCKED; live remains FROZEN." in html


def test_low_vol_uptrend_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "low_vol_uptrend_report.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Low-Vol Uptrend Event-Continuation Research Report" in output.read_text(encoding="utf-8")
