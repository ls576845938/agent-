"""Verify no broker access from portfolio code.

Portfolio construction modules must not import from live/execution.
"""

from __future__ import annotations

import unittest


_PORTFOLIO_MODULES = [
    "quant_us.portfolio",
    "quant_us.portfolio.allocation",
    "quant_us.portfolio.position_sizer",
    "quant_us.portfolio.rebalance",
    "quant_us.portfolio.optimizer",
    "quant_us.portfolio.construction.engine",
    "quant_us.portfolio.construction.allocator",
    "quant_us.portfolio.construction.exposure",
    "quant_us.portfolio.construction.backtest",
    "quant_us.portfolio.construction.scorecard",
]

_FORBIDDEN = ["submit_order", "AlpacaBroker", "quant_us.live", "quant_us.execution", "QUANT_LIVE"]


class TestPortfolioNoBroker(unittest.TestCase):
    """Verify portfolio modules have no broker/live access."""

    def _check_module(self, module_name: str) -> list[str]:
        import importlib
        try:
            mod = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError):
            return [f"Could not import {module_name}"]

        source_file = getattr(mod, "__file__", None)
        if source_file is None:
            return [f"No __file__ for {module_name}"]

        try:
            with open(source_file, encoding="utf-8") as f:
                content = f.read()
        except (FileNotFoundError, OSError):
            return [f"Could not read {source_file}"]

        violations = []
        import re
        for forbidden in _FORBIDDEN:
            if forbidden in {"quant_us.live", "quant_us.execution"}:
                if re.search(rf'(from\s+{re.escape(forbidden)}\s+import|import\s+{re.escape(forbidden)})', content):
                    violations.append(f"{module_name} contains an import of '{forbidden}'")
            elif forbidden in content:
                violations.append(f"{module_name} contains '{forbidden}'")
        return violations

    def test_no_broker_in_portfolio_package(self) -> None:
        all_violations = []
        for mod_name in _PORTFOLIO_MODULES:
            all_violations.extend(self._check_module(mod_name))
        self.assertEqual(all_violations, [])

    def test_engine_no_submit_method(self) -> None:
        from quant_us.portfolio.construction.engine import PortfolioConstructionEngine
        methods = [attr for attr in dir(PortfolioConstructionEngine) if "submit" in attr.lower()]
        self.assertEqual(methods, [])

    def test_backtest_no_order_methods(self) -> None:
        from quant_us.portfolio.construction.backtest import PortfolioBacktestRunner
        methods = [attr for attr in dir(PortfolioBacktestRunner) if "submit" in attr.lower() or "order" in attr.lower()]
        self.assertEqual(methods, [])

    def test_scorecard_no_broker_refs(self) -> None:
        from quant_us.portfolio.construction.scorecard import PortfolioScorecardBuilder
        import inspect
        source = inspect.getsource(PortfolioScorecardBuilder)
        for forbidden in _FORBIDDEN:
            self.assertNotIn(forbidden, source)

    def test_allocation_no_broker(self) -> None:
        import quant_us.portfolio.allocation as allocation
        with open(allocation.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        for forbidden in _FORBIDDEN:
            self.assertNotIn(forbidden, content)
