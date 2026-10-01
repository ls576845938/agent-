from __future__ import annotations

import unittest

import pandas as pd

from backend.app.domain.risk import DrawdownCircuitBreaker, KellySizer, OrthogonalizationEngine, VolatilityScaler


class RiskControlTests(unittest.TestCase):
    def test_volatility_scaler_uses_sqrt_annualization(self) -> None:
        returns = pd.Series([0.01, -0.01, 0.02, -0.02], dtype=float)
        scaler = VolatilityScaler(target_annual_vol=0.2, min_scaler=0.1, max_scaler=10.0)
        multiplier = scaler.multiplier(returns, periods_per_year=4.0)

        self.assertAlmostEqual(multiplier, 6.324555320336759, places=6)

    def test_kelly_sizer_rewards_profitable_series(self) -> None:
        winning = pd.Series([0.01] * 30 + [-0.002] * 10)
        losing = pd.Series([-0.01] * 30 + [0.002] * 10)
        sizer = KellySizer(min_observations=10)

        self.assertGreater(sizer.multiplier(winning), 1.0)
        self.assertLess(sizer.multiplier(losing), 1.0)

    def test_orthogonalization_penalizes_high_correlation(self) -> None:
        data = pd.DataFrame(
            {
                "trend_macd": [0.01, 0.02, 0.03, 0.04, 0.05] * 10,
                "donchian_breakout": [0.011, 0.019, 0.031, 0.041, 0.049] * 10,
                "dynamic_grid": [-0.005, 0.003, -0.004, 0.006, -0.002] * 10,
            }
        )
        adjusted, scaler = OrthogonalizationEngine().apply(
            {
                "trend_macd": 0.4,
                "donchian_breakout": 0.4,
                "dynamic_grid": 0.2,
            },
            data,
        )

        self.assertLess(adjusted["donchian_breakout"], 0.4)
        self.assertGreaterEqual(scaler, 0.6)

    def test_drawdown_breaker_triggers_decay(self) -> None:
        breaker = DrawdownCircuitBreaker(max_drawdown_pct=0.1, cooldown_bars=2, leverage_decay=0.4)
        breaker.update(100.0)
        decay = breaker.update(89.0)

        self.assertEqual(decay, 0.4)
        self.assertEqual(breaker.update(90.0), 0.4)


if __name__ == "__main__":
    unittest.main()
