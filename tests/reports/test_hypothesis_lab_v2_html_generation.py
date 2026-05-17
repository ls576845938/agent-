from pathlib import Path

from scripts.reports.generate_btc_hypothesis_lab_v2_lifecycle_html import render_report


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")


def test_hypothesis_lab_v2_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260517T020000Z_hypothesis_lab_v2_lifecycle" in html
    assert "lifecycle_drag" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "hypothesis rejected; no strategy generated; paper queue remains LOCKED; live remains FROZEN." in html


def test_hypothesis_lab_v2_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "hypothesis_lab_v2.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Hypothesis Lab v2 Lifecycle-Aware Research Report" in output.read_text(encoding="utf-8")
