import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend")


def test_low_vol_uptrend_safety_status_locked_and_frozen() -> None:
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert safety["candidate_passed_internal_gate"] == 0
    assert safety["paper_queue"] == "LOCKED"
    assert safety["paper_queue_locked"] is True
    assert safety["paper_auto_start"] is False
    assert safety["live"] == "FROZEN"
    assert safety["live_frozen"] is True
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False


def test_low_vol_uptrend_research_code_has_no_live_side_effects() -> None:
    combined = "\n".join(
        [
            Path("quant_us/research/btc_low_vol_uptrend.py").read_text(encoding="utf-8"),
            Path("scripts/research/run_btc_low_vol_uptrend_research.py").read_text(encoding="utf-8"),
            Path("scripts/research/build_btc_low_vol_uptrend_event_profile.py").read_text(encoding="utf-8"),
        ]
    )

    assert "quant_us.live" not in combined
    assert "submit_order" not in combined
    assert "broker.submit" not in combined
    assert "live_enabled: true" not in combined
