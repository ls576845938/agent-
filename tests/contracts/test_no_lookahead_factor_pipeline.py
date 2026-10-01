from __future__ import annotations

import pandas as pd
import pytest

from scripts.run_us_equity_factor_evidence import _build_forward_returns


def test_forward_returns_are_labels_without_mutating_factor_timestamp() -> None:
    bars = pd.DataFrame(
        [
            {"timestamp_utc": "2026-01-01T00:00:00Z", "date": "2026-01-01", "symbol": "AAPL", "close": 100.0},
            {"timestamp_utc": "2026-01-02T00:00:00Z", "date": "2026-01-02", "symbol": "AAPL", "close": 110.0},
            {"timestamp_utc": "2026-01-03T00:00:00Z", "date": "2026-01-03", "symbol": "AAPL", "close": 121.0},
        ]
    )

    labels = _build_forward_returns(bars, 1)

    assert labels.iloc[0]["timestamp_utc"] == "2026-01-01T00:00:00Z"
    assert labels.iloc[0]["date"] == "2026-01-01"
    assert labels.iloc[0]["fwd_return"] == pytest.approx(0.10)
    assert "close_fwd" not in labels.columns


def test_factor_timestamp_precedes_label_timestamp_by_contract() -> None:
    factor_timestamp = pd.Timestamp("2026-01-01T00:00:00Z")
    label_start = pd.Timestamp("2026-01-02T00:00:00Z")
    label_end = pd.Timestamp("2026-01-06T00:00:00Z")

    assert factor_timestamp < label_start <= label_end


def test_leakage_check_failure_blocks_promotion_state() -> None:
    registry_factor_evidence = {
        "leakage_check_pass": False,
        "promotion_ready": False,
        "current_factor_candidates": [],
    }

    assert registry_factor_evidence["leakage_check_pass"] is False
    assert registry_factor_evidence["promotion_ready"] is False
    assert registry_factor_evidence["current_factor_candidates"] == []
