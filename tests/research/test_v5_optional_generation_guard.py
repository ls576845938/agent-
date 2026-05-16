import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")
V5_CONFIG = Path("configs/btc/alpha_renewal/btc_perp_dual_trend_v5_eventreturn.yaml")


def test_no_v5_generated_without_event_return_support() -> None:
    decision = json.loads((RUN / "alpha_renewal_decision.json").read_text(encoding="utf-8"))

    assert decision["v5_generated"] is False
    assert "No cross-fold stable event-return failure pattern" in decision["v5_generation_blocked_reason"]
    assert not V5_CONFIG.exists()


def test_v5_artifacts_absent_when_line_archived() -> None:
    assert not (RUN / "btc_perp_dual_trend_v5_eventreturn_results.json").exists()
    assert not (RUN / "btc_perp_dual_trend_v5_eventreturn_gate_input.json").exists()
    assert not (RUN / "btc_perp_dual_trend_v5_eventreturn_decision.json").exists()
