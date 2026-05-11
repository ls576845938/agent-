from __future__ import annotations

import numpy as np
import pandas as pd

from quant_us.research.benchmarks import estimate_style_exposure


def test_style_exposure_recovers_benchmark_betas() -> None:
    index = pd.date_range("2024-01-01", periods=80, freq="B")
    market = pd.Series(np.linspace(-0.01, 0.01, len(index)), index=index)
    size = pd.Series(np.sin(np.linspace(0, 4, len(index))) * 0.003, index=index)
    benchmarks = pd.DataFrame({"MKT": market, "SMB": size}, index=index)
    strategy = 0.0002 + 1.5 * benchmarks["MKT"] - 0.4 * benchmarks["SMB"]

    result = estimate_style_exposure(strategy, benchmarks, min_observations=20)

    assert result.observations == 80
    assert result.alpha_period == pytest_approx(0.0002)
    assert result.betas["MKT"] == pytest_approx(1.5)
    assert result.betas["SMB"] == pytest_approx(-0.4)
    assert result.r_squared > 0.99
    assert not result.warnings


def test_style_exposure_is_fail_closed_on_short_samples() -> None:
    index = pd.date_range("2024-01-01", periods=3, freq="B")
    strategy = pd.Series([0.01, 0.02, -0.01], index=index)
    benchmarks = pd.DataFrame({"MKT": [0.01, 0.01, -0.02]}, index=index)

    result = estimate_style_exposure(strategy, benchmarks, min_observations=20)

    assert result.observations == 3
    assert result.betas == {}
    assert result.warnings == ["insufficient_observations:3<20"]


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, abs=1e-8)
