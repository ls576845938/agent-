from pathlib import Path

from scripts.reports.generate_btc_liquidation_shock_attribution_html import render_report


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_attribution_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260517T010000Z_liquidation_shock_attribution" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "Skeleton Decision" in html
    assert "liquidation-shock recovery archived; paper queue remains LOCKED; live remains FROZEN." in html


def test_liquidation_shock_attribution_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "liquidation_shock_attribution.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Liquidation-Shock Event-Return Attribution" in output.read_text(encoding="utf-8")
