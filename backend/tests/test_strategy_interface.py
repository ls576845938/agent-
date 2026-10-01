"""Verify all strategies conform to the Strategy contract.

Every strategy must:
  1. Return only Signal[] from on_bar()
  2. NOT import broker, OMS, account, or execution modules directly
  3. Have no reference to execution-layer objects
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from quant_us.strategies.base import Strategy
from quant_us.strategies.factory import STRATEGY_REGISTRY, available_strategies
from quant_us.core.types import Signal

STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "quant_us" / "strategies"

# Modules that a strategy must NOT import directly
FORBIDDEN_IMPORTS = {
    "broker",
    "oms",
    "account",
    "execution",
    "ledger",
    "broker_simulator",
    "SimulatedBroker",
    "OrderManagementSystem",
    "PreTradeRiskEngine",
    "KillSwitch",
    "JsonlLedgerStore",
    "ReconciliationService",
}

# Strategy files that are allowed to import from these namespaces (e.g. factory.py)
EXEMPT_FILES = {"factory.py"}


class StrategyInterfaceTests(unittest.TestCase):

    # ------------------------------------------------------------------
    # Import check — no strategy file imports broker/OMS/account
    # ------------------------------------------------------------------

    def _strategy_files(self) -> list[Path]:
        return [
            p for p in STRATEGIES_DIR.glob("*.py")
            if p.name != "__init__.py" and p.name not in EXEMPT_FILES
        ]

    def test_no_strategy_imports_forbidden_modules(self) -> None:
        """Assert no strategy .py file imports broker/OMS/account."""
        errors: list[str] = []
        for path in self._strategy_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(forbidden in alias.name for forbidden in FORBIDDEN_IMPORTS):
                            errors.append(f"{path.name} imports forbidden module: {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(forbidden in node.module for forbidden in FORBIDDEN_IMPORTS):
                        errors.append(f"{path.name} imports from forbidden module: {node.module}")
                    for alias in (node.names or []):
                        if alias.name in FORBIDDEN_IMPORTS:
                            errors.append(f"{path.name} imports forbidden symbol: {alias.name}")
        self.assertEqual([], errors, f"Forbidden imports found:\n" + "\n".join(errors))

    # ------------------------------------------------------------------
    # on_bar return type — must be Iterable[Signal]
    # ------------------------------------------------------------------

    def test_strategy_on_bar_returns_iterable_of_signals(self) -> None:
        """Check that each strategy's on_bar returns a Signal iterable.

        Uses the registry to instantiate each strategy and calls on_bar with
        a minimal dummy MarketEvent + StrategyContext.
        """
        from quant_us.core.enums import SignalDirection
        from quant_us.core.events import MarketEvent
        from quant_us.core.types import Bar
        from quant_us.strategies.base import StrategyContext

        from datetime import datetime, timezone

        bar = Bar(
            timestamp_utc=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            symbol="SPY",
            open=450.0,
            high=452.0,
            low=449.0,
            close=451.0,
            volume=1_000_000,
        )
        event = MarketEvent.from_bar(bar)
        context = StrategyContext(run_id="test", market_prices={"SPY": 451.0})

        errors: list[str] = []
        for sid, cls in STRATEGY_REGISTRY.items():
            strategy = cls()
            result = strategy.on_bar(event, context)
            self.assertIsNotNone(result, f"{sid}.on_bar() returned None")
            signals = list(result)
            for s in signals:
                if not isinstance(s, Signal):
                    errors.append(f"{sid}.on_bar() returned non-Signal: {type(s).__name__}")
        self.assertEqual([], errors, "\n".join(errors))

    # ------------------------------------------------------------------
    # Base strategy class has no broker/execution references
    # ------------------------------------------------------------------

    def test_strategy_base_inherits_no_broker(self) -> None:
        """Ensure the Strategy base class only defines abstract on_bar."""
        # Strategy should not have any method or attribute referencing broker/execution
        members = dir(Strategy)
        forbidden_in_base = {"broker", "oms", "ledger", "execution", "risk_engine"}
        found = {m for m in members if any(f in m.lower() for f in forbidden_in_base)}
        self.assertEqual(set(), found, f"Strategy base class contains forbidden references: {found}")

    # ------------------------------------------------------------------
    # Every registered strategy has a valid strategy_id
    # ------------------------------------------------------------------

    def test_all_registered_strategies_have_nonempty_id(self) -> None:
        for sid in available_strategies():
            cls = STRATEGY_REGISTRY[sid]
            instance = cls()
            self.assertIsInstance(instance.strategy_id, str)
            self.assertGreater(len(instance.strategy_id), 0)

    # ------------------------------------------------------------------
    # Verify no strategy script uses ast.Import with execution-level keywords
    # ------------------------------------------------------------------

    def test_no_direct_broker_call_in_source(self) -> None:
        """Use regex scan for any method call that looks like a broker/OMS call."""
        import re

        broker_patterns = re.compile(
            r"\b(broker|order_management|oms|ledger|risk_engine|kill_switch)\."
        )
        errors: list[str] = []
        for path in self._strategy_files():
            source = path.read_text(encoding="utf-8")
            matches = broker_patterns.findall(source)
            if matches:
                errors.append(f"{path.name} contains broker/OMS references: {set(matches)}")
        self.assertEqual([], errors, "\n".join(errors))
