from pathlib import Path

from scripts.reports.generate_btc_range_reclaim_lifecycle_html import render_report


RUN = Path("artifacts/btc_hypothesis/20260518T010000Z_range_reclaim_lifecycle")


def test_range_reclaim_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260518T010000Z_range_reclaim_lifecycle" in html
    assert "full_lifecycle_event_PF_proxy" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "paper queue remains LOCKED; live remains FROZEN" in html


def test_range_reclaim_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "range_reclaim.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Range-Reclaim Momentum Lifecycle Research Report" in output.read_text(encoding="utf-8")
