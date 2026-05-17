import json
from pathlib import Path


REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")


def test_btc_research_registry_statuses() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    items = registry["items"]

    assert registry["paper_queue"] == "LOCKED"
    assert registry["live"] == "FROZEN"
    assert items["perp_dual_trend"]["status"] == "archived"
    assert items["liquidation_shock_recovery"]["status"] == "archived"
    assert items["low_vol_uptrend"]["status"] == "hypothesis_rejected"
    assert "compression_expansion_breakout" in items
    assert items["compression_expansion_breakout"]["status"] == "candidate_gate_failed"
