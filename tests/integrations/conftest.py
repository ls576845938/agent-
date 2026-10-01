from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.integrations.helpers import make_bar_frame, write_cleaned_bars


@pytest.fixture
def fake_market_root(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    write_cleaned_bars(
        data_root,
        "AAPL",
        make_bar_frame("AAPL", [100.0, 101.5, 102.0, 103.0, 104.0]),
    )
    write_cleaned_bars(
        data_root,
        "MSFT",
        make_bar_frame("MSFT", [200.0, 199.0, 201.0, 202.0, 203.5]),
    )
    return data_root


@pytest.fixture
def fake_scores_frame() -> pd.DataFrame:
    dates = pd.bdate_range(start="2026-01-05", periods=5, tz="UTC")
    rows = []
    for timestamp, aapl_score, msft_score in zip(
        dates,
        [0.10, 0.30, 0.20, 0.40, 0.25],
        [0.05, 0.10, 0.35, 0.20, 0.45],
        strict=True,
    ):
        rows.append(
            {
                "datetime": timestamp,
                "instrument": "AAPL",
                "symbol": "AAPL",
                "score": aapl_score,
            }
        )
        rows.append(
            {
                "datetime": timestamp,
                "instrument": "MSFT",
                "symbol": "MSFT",
                "score": msft_score,
            }
        )
    return pd.DataFrame(rows)
