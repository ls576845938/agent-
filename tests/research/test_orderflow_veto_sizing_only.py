from scripts.run_btc_canonical_attribution import STRATEGIES


def test_canonical_sprint_does_not_run_orderflow_as_standalone_entry_strategy() -> None:
    strategy_ids = set(STRATEGIES)

    assert "btc_orderflow_pressure" not in strategy_ids
    assert "btc_orderflow_confirmed_trend_v1" not in strategy_ids
