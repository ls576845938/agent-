from quant_us.research.btc_hypothesis_lab import DEFAULT_CONFIG_PATH, evaluate_hypothesis, load_hypothesis_config


def test_top_positive_tail_dependency_blocks_hypothesis(monkeypatch, tmp_path) -> None:
    config = load_hypothesis_config(DEFAULT_CONFIG_PATH)
    monkeypatch.setattr("quant_us.research.btc_hypothesis_lab.write_strategy_skeleton", lambda *a, **k: None)
    report = {
        "overall": {"active_event_count": 300},
        "selected_direction": "upside_breakout",
        "selected_direction_event_count": 120,
        "selected_direction_distribution": {
            "event_PF_proxy": 1.30,
            "median_return": 0.0001,
        },
        "fold_stability": {"pass_rate": 1.0},
        "horizon_analysis": {
            "1h": {"event_PF_proxy": 1.20},
            "4h": {"event_PF_proxy": 1.15},
        },
        "tail_dependency": {"top5_positive_contribution": 0.90},
        "no_lookahead": {"status": "pass"},
    }

    decision = evaluate_hypothesis(run_dir=tmp_path, config=config, distribution_report=report)

    assert decision["decision"] == "hypothesis_rejected"
    assert "top5_positive_contribution_too_high" in decision["reasons"]
