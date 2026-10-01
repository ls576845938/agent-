import json
from pathlib import Path


def test_btc_canonical_research_code_has_no_live_or_broker_side_effects() -> None:
    combined = "\n".join(
        [
            Path("quant_us/research/btc_canonical.py").read_text(encoding="utf-8"),
            Path("scripts/run_btc_canonical_attribution.py").read_text(encoding="utf-8"),
        ]
    )

    assert "quant_us.live" not in combined
    assert "run_live" not in combined
    assert "submit_order" not in combined
    assert "live_enabled = True" not in combined


def test_canonical_promotion_decision_keeps_live_frozen() -> None:
    decision = json.loads(
        Path("artifacts/btc_canonical/20260516T061000Z_attribution/promotion_decision.json").read_text(encoding="utf-8")
    )

    assert decision["paper_review"]["paper_review_queue_locked"] is True
    assert decision["paper_review"]["paper_auto_start"] is False
    assert decision["paper_review"]["live_frozen"] is True
    assert decision["live_frozen"] is True


def test_eventpf_wf_sprint_keeps_live_frozen_and_creates_no_real_orders() -> None:
    status = json.loads(
        Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf/paper_live_safety_status.json").read_text(
            encoding="utf-8"
        )
    )

    assert status["live_status"] == "FROZEN"
    assert status["live_frozen"] is True
    assert status["real_broker_api_called"] is False
    assert status["real_orders_created"] is False


def test_eventpf_wf_research_code_has_no_live_runtime_imports() -> None:
    combined = "\n".join(
        [
            Path("quant_us/research/btc_eventpf_wf.py").read_text(encoding="utf-8"),
            Path("scripts/research/run_btc_eventpf_wf_stabilization.py").read_text(encoding="utf-8"),
        ]
    )

    assert "quant_us.live" not in combined
    assert "submit_order" not in combined
    assert "live_enabled: true" not in combined
