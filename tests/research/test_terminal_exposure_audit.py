import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_terminal_exposure_audit_outputs_three_policies() -> None:
    audit = json.loads((RUN / "terminal_exposure_audit.json").read_text(encoding="utf-8"))

    policies = {row["policy"]: row for row in audit["policies"]}
    assert set(policies) == {
        "mark_to_market_at_end",
        "force_flat_at_end",
        "closed_trades_only_diagnostic",
    }
    assert policies["mark_to_market_at_end"]["gate_eligible"] is True
    assert policies["force_flat_at_end"]["gate_eligible"] is False
    assert policies["closed_trades_only_diagnostic"]["gate_eligible"] is False


def test_terminal_policy_does_not_select_best_metric() -> None:
    audit = json.loads((RUN / "terminal_exposure_audit.json").read_text(encoding="utf-8"))

    assert audit["recommended_terminal_policy"]["policy"] == "mark_to_market_at_end_for_current_gate"
    assert audit["recommended_terminal_policy"]["do_not_select_best_metric"] is True
