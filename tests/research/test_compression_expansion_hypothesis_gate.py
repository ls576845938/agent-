from pathlib import Path

from quant_us.research.btc_hypothesis_lab import DEFAULT_CONFIG_PATH, evaluate_hypothesis, load_hypothesis_config


def _passing_report() -> dict:
    return {
        "overall": {"active_event_count": 300},
        "selected_direction": "upside_breakout",
        "selected_direction_event_count": 120,
        "selected_direction_distribution": {
            "event_PF_proxy": 1.25,
            "median_return": 0.0001,
        },
        "fold_stability": {"pass_rate": 0.75},
        "horizon_analysis": {
            "1h": {"event_PF_proxy": 1.20},
            "4h": {"event_PF_proxy": 1.12},
            "12h": {"event_PF_proxy": 1.00},
        },
        "tail_dependency": {"top5_positive_contribution": 0.20},
        "no_lookahead": {"status": "pass"},
    }


def test_compression_expansion_failed_gate_does_not_generate_skeleton(monkeypatch, tmp_path) -> None:
    config = load_hypothesis_config(DEFAULT_CONFIG_PATH)
    report = _passing_report()
    report["selected_direction_distribution"]["event_PF_proxy"] = 1.01
    calls = []
    monkeypatch.setattr("quant_us.research.btc_hypothesis_lab.write_strategy_skeleton", lambda *a, **k: calls.append(a))

    decision = evaluate_hypothesis(run_dir=tmp_path, config=config, distribution_report=report)

    assert decision["decision"] == "hypothesis_rejected"
    assert decision["strategy_skeleton_generated"] is False
    assert "event_PF_proxy_below_1_15" in decision["reasons"]
    assert calls == []


def test_compression_expansion_passing_gate_is_research_candidate_only(monkeypatch, tmp_path) -> None:
    config = load_hypothesis_config(DEFAULT_CONFIG_PATH)
    calls = []
    monkeypatch.setattr("quant_us.research.btc_hypothesis_lab.write_strategy_skeleton", lambda *a, **k: calls.append(a))

    decision = evaluate_hypothesis(run_dir=tmp_path, config=config, distribution_report=_passing_report())

    assert decision["decision"] == "hypothesis_passed_for_strategy_skeleton"
    assert decision["strategy_skeleton_generated"] is True
    assert decision["paper_queue_status"] == "LOCKED"
    assert decision["live_status"] == "FROZEN"
    assert Path(decision["strategy_skeleton_path"]).name == "compression_expansion_breakout_v1_skeleton.yaml"
    assert len(calls) == 1
