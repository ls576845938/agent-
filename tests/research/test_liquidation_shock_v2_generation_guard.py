import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")
V2_CONFIG = Path("configs/btc/candidate_validation/liquidation_shock_recovery_v2_event_ledger.yaml")


def test_liquidation_shock_v2_generation_guard_blocks_without_stable_evidence() -> None:
    decision = json.loads((RUN / "liquidation_shock_skeleton_decision.json").read_text(encoding="utf-8"))

    assert decision["decision"] == "archive_liquidation_shock_recovery"
    assert decision["v2_generated"] is False
    assert decision["v2_config_path"] == ""
    assert decision["evidence_supported_rules"] == []
    assert not V2_CONFIG.exists()
