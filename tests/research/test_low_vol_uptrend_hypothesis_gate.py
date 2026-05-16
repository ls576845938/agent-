import json
from pathlib import Path

from quant_us.research.btc_low_vol_uptrend import evaluate_low_vol_uptrend_hypothesis


RUN = Path("artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend")


def test_low_vol_uptrend_hypothesis_rejected_when_distribution_fails() -> None:
    decision = json.loads((RUN / "low_vol_uptrend_hypothesis_decision.json").read_text(encoding="utf-8"))

    assert decision["decision"] == "hypothesis_rejected"
    assert decision["strategy_skeleton_generated"] is False
    assert "event_PF_proxy_below_1_15" in decision["reasons"]
    assert "fold_pass_rate_below_75pct" in decision["reasons"]


def test_low_vol_uptrend_hypothesis_pass_only_allows_skeleton(monkeypatch, tmp_path) -> None:
    written_paths = []

    def fake_write_strategy_skeleton(path):
        written_paths.append(str(path))

    monkeypatch.setattr(
        "quant_us.research.btc_low_vol_uptrend.write_strategy_skeleton",
        fake_write_strategy_skeleton,
    )
    report = {
        "overall_distribution": {
            "active_event_count": 500,
            "event_PF_proxy": 1.25,
            "median_return": 0.0001,
        },
        "fold_stability": {
            "folds": [
                {"fold_id": "1", "passed": True},
                {"fold_id": "2", "passed": True},
                {"fold_id": "3", "passed": True},
                {"fold_id": "4", "passed": False},
            ]
        },
        "failure_analysis": {
            "single_extreme_event_dependency": False,
            "no_lookahead_pass": True,
        },
        "holding_horizon_analysis": {
            "4h": {"event_PF_proxy": 1.08},
            "12h": {"event_PF_proxy": 1.12},
        },
    }

    decision = evaluate_low_vol_uptrend_hypothesis(run_dir=tmp_path, distribution_report=report)

    assert decision["decision"] == "hypothesis_passed_for_strategy_skeleton"
    assert decision["paper_queue_status"] == "LOCKED"
    assert decision["live_status"] == "FROZEN"
    assert written_paths == ["configs/btc/hypothesis/low_vol_uptrend_event_continuation_v1.yaml"]
