"""Tests for ExposureDecomposer."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from quant_us.research.portfolio_research.exposure_decomp import (
    ExposureDecomposition,
    ExposureDecomposer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeManifest:
    strategy_candidate_id: str
    scorecard: dict = field(default_factory=dict)
    params_frozen: bool = True
    strategy_template: str = "momentum"
    symbols: list[str] = field(default_factory=list)


def _save_manifest(tmpdir: str, m: FakeManifest) -> None:
    """Save a fake manifest to disk."""
    from quant_us.research.strategy_manifest import (
        StrategyCandidateManifest,
    )

    sm = StrategyCandidateManifest(
        strategy_candidate_id=m.strategy_candidate_id,
        source_candidate_id=m.strategy_candidate_id,
        source_experiment_id="exp_1",
        strategy_template=m.strategy_template,
        params_frozen=m.params_frozen,
        symbols=m.symbols,
        scorecard=m.scorecard,
    )
    manifests_dir = Path(tmpdir) / "research" / "manifests"
    path = manifests_dir / sm.strategy_candidate_id / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    import dataclasses
    path.write_text(
        json.dumps(dataclasses.asdict(sm), indent=2, default=str),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExposureDecomposer:
    """Tests for ExposureDecomposer."""

    def test_decompose_empty_manifest_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decomposer = ExposureDecomposer(data_root=tmpdir)
            with pytest.raises(ValueError, match="least one strategy"):
                decomposer.decompose([], {})

    def test_decompose_zero_total_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _save_manifest(tmpdir, FakeManifest(strategy_candidate_id="strat_1"))
            decomposer = ExposureDecomposer(data_root=tmpdir)
            with pytest.raises(ValueError, match="Total weight"):
                decomposer.decompose(["strat_1"], {"strat_1": 0.0})

    def test_decompose_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decomposer = ExposureDecomposer(data_root=tmpdir)
            with pytest.raises(ValueError, match="not found"):
                decomposer.decompose(["does_not_exist"], {"does_not_exist": 1.0})

    def test_decompose_missing_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _save_manifest(tmpdir, FakeManifest(strategy_candidate_id="strat_1"))
            decomposer = ExposureDecomposer(data_root=tmpdir)
            with pytest.raises(ValueError, match="not found in weights"):
                decomposer.decompose(["strat_1"], {"wrong_id": 1.0})

    def test_decompose_single_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            m = FakeManifest(
                strategy_candidate_id="strat_1",
                strategy_template="momentum",
                scorecard={
                    "sharpe_ratio": 1.5,
                    "max_drawdown_pct": 0.1,
                    "total_return_pct": 15.0,
                    "holdings": {"AAPL": 0.5, "MSFT": 0.5},
                },
            )
            _save_manifest(tmpdir, m)
            decomposer = ExposureDecomposer(data_root=tmpdir)
            decomp = decomposer.decompose(
                ["strat_1"], {"strat_1": 1.0}
            )

            assert isinstance(decomp, ExposureDecomposition)
            assert decomp.strategy_exposure == {"strat_1": 1.0}
            assert decomp.symbol_exposure.get("AAPL", 0) == 0.5
            assert decomp.symbol_exposure.get("MSFT", 0) == 0.5
            assert decomp.long_exposure == 1.0
            assert decomp.short_exposure == 0.0
            assert decomp.cash_exposure == 0.0
            assert "momentum" in decomp.factor_exposure

    def test_decompose_two_strategies_equal_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = FakeManifest(
                strategy_candidate_id="strat_1",
                strategy_template="momentum",
                scorecard={
                    "sharpe_ratio": 1.5,
                    "max_drawdown_pct": 0.1,
                    "total_return_pct": 15.0,
                    "holdings": {"AAPL": 1.0},
                },
            )
            m2 = FakeManifest(
                strategy_candidate_id="strat_2",
                strategy_template="value",
                scorecard={
                    "sharpe_ratio": 0.8,
                    "max_drawdown_pct": 0.2,
                    "total_return_pct": 8.0,
                    "holdings": {"MSFT": 1.0},
                },
            )
            _save_manifest(tmpdir, m1)
            _save_manifest(tmpdir, m2)
            decomposer = ExposureDecomposer(data_root=tmpdir)
            decomp = decomposer.decompose(
                ["strat_1", "strat_2"],
                {"strat_1": 0.5, "strat_2": 0.5},
            )

            assert decomp.strategy_exposure["strat_1"] == 0.5
            assert decomp.strategy_exposure["strat_2"] == 0.5
            assert decomp.symbol_exposure.get("AAPL", 0) == 0.5
            assert decomp.symbol_exposure.get("MSFT", 0) == 0.5

    def test_decompose_normalizes_weights(self) -> None:
        """Weights should be normalized to sum to 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = FakeManifest(
                strategy_candidate_id="strat_1",
                strategy_template="momentum",
                scorecard={"holdings": {"AAPL": 1.0}},
            )
            m2 = FakeManifest(
                strategy_candidate_id="strat_2",
                strategy_template="value",
                scorecard={"holdings": {"MSFT": 1.0}},
            )
            _save_manifest(tmpdir, m1)
            _save_manifest(tmpdir, m2)
            decomposer = ExposureDecomposer(data_root=tmpdir)
            # Raw weights sum to 0.75, should be normalized
            decomp = decomposer.decompose(
                ["strat_1", "strat_2"],
                {"strat_1": 0.25, "strat_2": 0.5},
            )
            assert abs(decomp.strategy_exposure["strat_1"] - 0.33333) < 0.001
            assert abs(decomp.strategy_exposure["strat_2"] - 0.66666) < 0.001

    def test_check_limits_passes(self) -> None:
        decomp = ExposureDecomposition(
            strategy_exposure={"s1": 1.0},
            symbol_exposure={"AAPL": 0.1, "MSFT": 0.2},
            sector_exposure={"Tech": 0.3},
            factor_exposure={"momentum": 1.0},
            long_exposure=0.3,
        )
        decomposer = ExposureDecomposer()
        passed, violations = decomposer.check_limits(decomp)
        assert passed
        assert len(violations) == 0

    def test_check_limits_fails_symbol(self) -> None:
        decomp = ExposureDecomposition(
            strategy_exposure={"s1": 1.0},
            symbol_exposure={"AAPL": 0.5},
            sector_exposure={"Tech": 0.3},
            factor_exposure={"momentum": 1.0},
            long_exposure=0.5,
        )
        decomposer = ExposureDecomposer()
        passed, violations = decomposer.check_limits(decomp, max_symbol=0.25)
        assert not passed
        assert any("AAPL" in v for v in violations)

    def test_check_limits_fails_sector(self) -> None:
        decomp = ExposureDecomposition(
            strategy_exposure={"s1": 1.0},
            symbol_exposure={"AAPL": 0.1},
            sector_exposure={"Tech": 0.6},
            factor_exposure={"momentum": 1.0},
            long_exposure=0.1,
        )
        decomposer = ExposureDecomposer()
        passed, violations = decomposer.check_limits(decomp, max_sector=0.40)
        assert not passed
        assert any("Tech" in v for v in violations)

    def test_decompose_no_holdings_returns_empty_symbol_exposure(self) -> None:
        """Manifest without holdings yields empty symbol exposure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = FakeManifest(
                strategy_candidate_id="strat_1",
                strategy_template="momentum",
                scorecard={"sharpe_ratio": 1.5},
            )
            _save_manifest(tmpdir, m)
            decomposer = ExposureDecomposer(data_root=tmpdir)
            decomp = decomposer.decompose(
                ["strat_1"], {"strat_1": 1.0}
            )
            assert decomp.symbol_exposure == {}
            assert decomp.long_exposure == 1.0  # default when no holdings

    def test_decompose_sector_exposure_from_scorecard(self) -> None:
        """Sector exposure reads from scorecard if available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = FakeManifest(
                strategy_candidate_id="strat_1",
                strategy_template="momentum",
                scorecard={
                    "sector_exposures": {"Tech": 0.7, "Healthcare": 0.3},
                    "holdings": {"AAPL": 1.0},
                },
            )
            _save_manifest(tmpdir, m)
            decomposer = ExposureDecomposer(data_root=tmpdir)
            decomp = decomposer.decompose(
                ["strat_1"], {"strat_1": 1.0}
            )
            assert decomp.sector_exposure.get("Tech", 0) == 0.7
            assert decomp.sector_exposure.get("Healthcare", 0) == 0.3

    def test_decompose_fallback_unknown_sector(self) -> None:
        """Without sector data, all weight goes to 'unknown'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = FakeManifest(
                strategy_candidate_id="strat_1",
                strategy_template="momentum",
                scorecard={"holdings": {"AAPL": 1.0}},
            )
            _save_manifest(tmpdir, m)
            decomposer = ExposureDecomposer(data_root=tmpdir)
            decomp = decomposer.decompose(
                ["strat_1"], {"strat_1": 1.0}
            )
            assert decomp.sector_exposure.get("unknown", 0) == 1.0
