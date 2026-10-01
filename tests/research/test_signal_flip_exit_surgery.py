import json
from pathlib import Path

import pandas as pd

from quant_us.research.btc_eventpf_wf import apply_exit_surgery_policy


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_exit_surgery_forces_flat_before_reverse() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
    raw = pd.Series([0.2, -0.2, -0.2, -0.2, 0.0], index=index)

    repaired = apply_exit_surgery_policy(raw, reverse_confirmation_bars=2, flip_cooldown_bars=1)

    assert repaired.iloc[0] > 0
    assert repaired.iloc[1] == 0.0
    assert repaired.iloc[2] < 0
    assert not ((repaired.shift(1) > 0) & (repaired < 0)).any()


def test_exit_surgery_ablation_reports_signal_flip_count() -> None:
    report = json.loads((RUN / "exit_surgery_ablation_report.json").read_text(encoding="utf-8"))

    for row in report["rows"]:
        assert "signal_flip_exit_count" in row
        assert row["signal_flip_exit_count"] == 0
    assert "combined_exit_surgery" in [row["mode"] for row in report["rows"]]
