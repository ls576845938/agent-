from pathlib import Path

from scripts.reports.generate_btc_eventpf_wf_stabilization_html import render_report


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_html_eventpf_wf_report_contains_required_safety_terms() -> None:
    html = render_report(RUN)

    assert "20260516T080000Z_eventpf_wf" in html
    assert "event PF" in html or "event_PF" in html
    assert "PAPER QUEUE" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "v4 failed internal gate; paper queue remains LOCKED; live remains FROZEN." in html


def test_html_eventpf_wf_report_can_be_written(tmp_path) -> None:
    output = tmp_path / "report.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "QuantStation VNEXT - BTC Event-PF Bridge" in output.read_text(encoding="utf-8")
