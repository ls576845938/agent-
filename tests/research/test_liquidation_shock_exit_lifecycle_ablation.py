import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_exit_lifecycle_ablation_variants() -> None:
    report = json.loads((RUN / "liquidation_shock_exit_lifecycle_ablation.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_liquidation_shock_exit_lifecycle_ablation_v1"
    variants = {row["variant"] for row in report["ablation_results"]}
    assert {
        "baseline_v1_time_exit_24",
        "time_exit_6",
        "time_exit_12",
        "time_exit_18",
        "time_exit_24",
        "time_exit_36",
        "trailing_recovery_exit",
        "event_return_deterioration_exit",
        "second_confirmation_required",
        "second_confirmation_plus_time_exit_12",
    }.issubset(variants)
    assert report["best_by_event_PF"]["event_PF"] < 1.15
    assert report["time_exit_should_shorten"] is False
    for row in report["ablation_results"]:
        assert "fold3_result" in row
        assert "mean_reverting_chop_result" in row
        assert "cost_stress_base_pass" in row
