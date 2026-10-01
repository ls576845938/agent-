import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")
CONFIG = Path("configs/btc/alpha_stabilization/btc_perp_dual_trend_v4_eventpf_wf.yaml")


def test_orderflow_is_not_entry_trigger_and_not_forced_into_v4() -> None:
    report = json.loads((RUN / "orderflow_keepout_confirmation.json").read_text(encoding="utf-8"))

    assert report["orderflow_entry_trigger_allowed"] is False
    assert report["orderflow_forced_into_v4"] is False
    assert report["adopted_in_v4"] is False
    assert report["source_conclusion"] == "do_not_force_orderflow"


def test_v4_config_does_not_reintroduce_orderflow_trigger() -> None:
    text = CONFIG.read_text(encoding="utf-8")

    assert "orderflow_mode: no_orderflow" in text
    assert "orderflow_entry_trigger" not in text
