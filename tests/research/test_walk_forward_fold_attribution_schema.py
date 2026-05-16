import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_walk_forward_fold_attribution_has_required_fields() -> None:
    report = json.loads((RUN / "walk_forward_fold_attribution.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_walk_forward_fold_attribution_v1"
    assert report["pass_rate"] == 0.5
    assert report["failed_folds"] == [3, 4]
    assert len(report["folds"]) == 4
    for fold in report["folds"]:
        for field in [
            "fold_id",
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "event_PF",
            "PF",
            "Sharpe",
            "MDD",
            "turnover",
            "trade_count",
            "passed",
            "fail_reasons",
            "signal_flip_exit_count",
            "long_trades_PF",
            "short_trades_PF",
        ]:
            assert field in fold
        assert isinstance(fold["fail_reasons"], list)


def test_walk_forward_fold_report_answers_failure_sources() -> None:
    report = json.loads((RUN / "walk_forward_fold_attribution.json").read_text(encoding="utf-8"))

    assert "failure_sources" in report["answers"]
    assert "event_profit_factor" in report["answers"]["failure_sources"]
