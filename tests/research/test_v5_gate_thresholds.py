import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_archived_line_cannot_enter_v5_gate() -> None:
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))
    gate = promotion["candidate_gate_results"][0]

    assert gate["status"] == "research_failed"
    assert gate["passed"] is False
    assert "alpha_archived" in gate["fail_reasons"]
    assert "event_return_edge_too_thin" in gate["fail_reasons"]


def test_no_candidate_passed_internal_gate_for_archived_line() -> None:
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert safety["candidate_passed_internal_gate_count"] == 0
    assert safety["max_state"] == "research_failed"
