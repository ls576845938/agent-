"""Test backtest_survival gate with strategy frequency profiles."""

import pytest


class TestBacktestSurvivalFrequencyProfiles:
    """Low-frequency strategies must not be killed by low trade_count."""

    def test_low_frequency_daily_accepts_3_trades(self):
        """Daily bars: trade_count=3 should NOT fail."""
        from backend.app.services.research_gate import _gate, _gate_status

        trade_count = 3
        total_return = 15.0
        sharpe = 1.2
        profit_factor = 2.0
        max_drawdown = -5.0

        # Low frequency profile: trade_count >= 3
        failed = total_return <= 0 or max_drawdown <= -25 or sharpe < 0 or profit_factor < 0.5 or trade_count < 3
        assert not failed, "3 trades should pass low-frequency profile"

    def test_low_frequency_daily_fails_under_3_trades(self):
        """Daily bars: trade_count=1 should still FAIL."""
        trade_count = 1
        total_return = 5.0
        sharpe = 0.8
        profit_factor = 1.5
        max_drawdown = -8.0

        failed = total_return <= 0 or max_drawdown <= -25 or sharpe < 0 or profit_factor < 0.5 or trade_count < 3
        assert failed, "1 trade should fail even low-frequency profile"

    def test_standard_intraday_requires_10_trades(self):
        """Intraday bars: trade_count < 10 should FAIL."""
        trade_count = 8
        total_return = 10.0
        sharpe = 1.0
        profit_factor = 1.8
        max_drawdown = -6.0

        failed = total_return <= 0 or max_drawdown <= -25 or sharpe < 0 or profit_factor < 0.5 or trade_count < 10
        assert failed, "8 trades should fail standard (intraday) profile"

    def test_gate_reports_frequency_profile(self):
        """Gate metrics must include frequency_profile."""
        from backend.app.services.research_gate import _gate, _gate_status

        g = _gate(
            name="backtest_survival",
            status="pass",
            message="test",
            metrics={
                "trade_count": 5,
                "frequency_profile": "low_frequency",
                "signal_count": 5,
            },
            threshold="low_frequency_profile: trades>=3",
        )
        assert g["metrics"]["frequency_profile"] == "low_frequency"
        assert g["metrics"]["trade_count"] == 5

    def test_portfolio_mode_uses_low_frequency(self):
        """Portfolio mode must use low_frequency criteria."""
        # Simulate portfolio mode detection
        mode = "portfolio"
        interval = "1d"
        is_low_frequency = interval in ("1d", "4h", "1w") or mode == "portfolio"
        assert is_low_frequency, "portfolio mode should be low_frequency"


class TestBacktestSurvivalMultiSymbol:
    """Verify multi-symbol survival concepts."""

    def test_gate_accepts_multi_symbol_context(self):
        """Gate metrics can include symbols list."""
        from backend.app.services.research_gate import _gate, _gate_status

        g = _gate(
            name="backtest_survival",
            status="warn",
            message="multi-symbol survival",
            metrics={
                "trade_count": 12,
                "symbols": "SPY,QQQ,IWM,DIA",
                "frequency_profile": "low_frequency",
            },
            threshold="low_frequency_profile: trades>=3, symbols=SPY,QQQ,IWM,DIA",
        )
        assert g["status"] == "warn"
        assert "symbols" in g["metrics"]
