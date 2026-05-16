import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")
DOC = Path("docs/research/BTC_ALPHA_RENEWAL_DECISION.md")


def test_alpha_renewal_decision_uses_allowed_status() -> None:
    decision = json.loads((RUN / "alpha_renewal_decision.json").read_text(encoding="utf-8"))

    assert decision["decision"] in {
        "continue_with_v5",
        "archive_perp_dual_trend",
        "research_invalid",
    }
    assert decision["decision"] == "archive_perp_dual_trend"
    assert decision["status"] == "research_failed"
    assert decision["v5_generated"] is False


def test_alpha_renewal_decision_doc_and_backlog_exist() -> None:
    decision = json.loads((RUN / "alpha_renewal_decision.json").read_text(encoding="utf-8"))

    assert DOC.exists()
    assert len(decision["alpha_hypothesis_backlog"]) == 3
    for item in decision["alpha_hypothesis_backlog"]:
        assert "rationale" in item
        assert "first_experiment_plan" in item
        assert "stop_condition" in item
