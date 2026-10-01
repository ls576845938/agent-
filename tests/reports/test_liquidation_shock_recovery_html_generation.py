from pathlib import Path

from scripts.reports.generate_btc_liquidation_shock_recovery_html import render_report


RUN = Path("artifacts/btc_hypothesis/20260516T232000Z_liquidation_shock_recovery")


def test_liquidation_shock_recovery_html_contains_required_terms() -> None:
    html = render_report(RUN)

    assert "20260516T232000Z_liquidation_shock_recovery" in html
    assert "PAPER QUEUE" in html
    assert "LOCKED" in html
    assert "LIVE" in html
    assert "FROZEN" in html
    assert "Hypothesis Decision" in html
    assert "hypothesis passed; strategy skeleton generated; paper queue remains LOCKED; live remains FROZEN." in html


def test_liquidation_shock_recovery_html_can_be_written(tmp_path) -> None:
    output = tmp_path / "liquidation_shock_recovery.html"
    output.write_text(render_report(RUN), encoding="utf-8")

    assert output.exists()
    assert "BTC Liquidation-Shock Recovery Research Report" in output.read_text(encoding="utf-8")
