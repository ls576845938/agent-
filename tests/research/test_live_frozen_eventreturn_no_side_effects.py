import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_eventreturn_safety_keeps_live_frozen() -> None:
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert safety["live_status"] == "FROZEN"
    assert safety["live_frozen"] is True
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False


def test_eventreturn_research_code_has_no_live_or_broker_side_effects() -> None:
    combined = "\n".join(
        [
            Path("quant_us/research/btc_eventreturn_alpha.py").read_text(encoding="utf-8"),
            Path("scripts/research/run_btc_eventreturn_alpha_renewal.py").read_text(encoding="utf-8"),
        ]
    )

    assert "quant_us.live" not in combined
    assert "submit_order" not in combined
    assert "live_enabled: true" not in combined
