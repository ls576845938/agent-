from pathlib import Path

from quant_us.research.btc_hypothesis_lab import load_hypothesis_config


CONFIG = Path("configs/btc/hypotheses/compression_expansion_breakout_v0.yaml")


def test_btc_hypothesis_lab_config_schema() -> None:
    config = load_hypothesis_config(CONFIG)

    assert config["hypothesis_id"] == "compression_expansion_breakout_v0"
    assert config["mode"] == "research_only"
    assert config["timeframes"]["base"] == "1h"
    assert config["feature_config"]["no_lookahead"] is True
    assert config["direction_config"]["analyze_upside"] is True
    assert config["direction_config"]["analyze_downside"] is True
    assert config["sample_thresholds"]["min_active_events"] == 200
    assert config["acceptance_gate"]["min_event_pf_proxy"] == 1.15


def test_btc_hypothesis_lab_safety_defaults_locked_frozen() -> None:
    config = load_hypothesis_config(CONFIG)

    assert config["safety"]["paper_queue"] == "LOCKED"
    assert config["safety"]["live"] == "FROZEN"
    assert config["safety"]["real_broker_api_allowed"] is False
    assert config["safety"]["real_orders_allowed"] is False
