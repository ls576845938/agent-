import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260516T232000Z_liquidation_shock_recovery")


def test_liquidation_shock_feature_profile_schema() -> None:
    profile = json.loads((RUN / "liquidation_shock_recovery_feature_profile.json").read_text(encoding="utf-8"))

    assert profile["schema_version"] == "btc_liquidation_shock_recovery_feature_profile_v1"
    assert profile["hypothesis_id"] == "liquidation_shock_recovery_v0"
    assert profile["no_lookahead"]["status"] == "pass"
    assert profile["feature_definitions"]["future_return_usage"] == "labels_only"
    assert profile["active_event_count"] >= 80


def test_liquidation_shock_distribution_report_gate_inputs() -> None:
    report = json.loads((RUN / "liquidation_shock_recovery_distribution_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_liquidation_shock_recovery_distribution_report_v1"
    assert report["primary_horizon"] == "24h"
    assert report["overall_distribution"]["event_PF_proxy"] >= 1.15
    assert report["fold_stability"]["pass_rate"] >= 0.75
    assert report["tail_dependency"]["edge_depends_on_extreme_events"] is False


def test_liquidation_shock_decision_only_generates_research_skeleton() -> None:
    decision = json.loads((RUN / "liquidation_shock_recovery_hypothesis_decision.json").read_text(encoding="utf-8"))
    skeleton = Path(decision["strategy_skeleton_path"])

    assert decision["decision"] == "hypothesis_passed_for_strategy_skeleton"
    assert decision["strategy_skeleton_generated"] is True
    assert skeleton.exists()
    text = skeleton.read_text(encoding="utf-8")
    assert "status: research_candidate" in text
    assert "paper_ready: false" in text
    assert "live_ready: false" in text
    assert "live_enabled: false" in text


def test_liquidation_shock_safety_stays_locked_and_frozen() -> None:
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert safety["candidate_passed_internal_gate"] == 0
    assert safety["paper_queue"] == "LOCKED"
    assert safety["live"] == "FROZEN"
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False
