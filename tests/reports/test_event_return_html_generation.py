from pathlib import Path

from scripts.reports.generate_btc_event_return_alpha_renewal_html import render_report


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_event_return_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260516T100000Z_eventreturn_alpha" in html
    assert "PAPER QUEUE" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "Alpha Renewal Decision" in html
    assert "perp_dual_trend archived; paper queue remains LOCKED; live remains FROZEN." in html


def test_event_return_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "event_return_report.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Event-Return Attribution and Alpha Renewal Report" in output.read_text(encoding="utf-8")
