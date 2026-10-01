"""Stand-alone edge case tests for BacktestReplay.

Tests cover the replay module at unit level: construction, serialization
round-trip, determinism verification with various mismatch scenarios, and
edge cases (empty data, non-existent file, corrupted JSON).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.backtest.replay import BacktestReplay
from quant_us.core.enums import OrderSide
from quant_us.core.types import Bar, Fill, Order, PortfolioSnapshot, new_id
from quant_us.strategies.momentum_strategy import MomentumStrategy


def _deterministic_bars(n: int = 60, symbol: str = "AAPL") -> list[Bar]:
    """Deterministic upward-trend bars for reproducible backtest runs."""
    price = 150.0
    bars: list[Bar] = []
    for i in range(n):
        ts = datetime(2024, 1, 2, 10, i % 390, tzinfo=timezone.utc)
        price = price * (1.0 + 0.001)
        bars.append(
            Bar(
                timestamp_utc=ts, symbol=symbol,
                open=price * 0.999, high=price * 1.01, low=price * 0.99,
                close=price, volume=15000.0,
            )
        )
    return bars


class BacktestReplayFromResultTests(unittest.TestCase):
    """Tests for BacktestReplay.from_result constructor."""

    def setUp(self):
        self.bars = _deterministic_bars(60)
        self.strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        self.config = BacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            slippage_bps=0.0,
        )

    def _run_and_replay(self) -> tuple[BacktestReplay, ...]:
        engine = EventDrivenBacktestEngine(
            strategies=[self.strategy], config=self.config,
        )
        result = engine.run(self.bars)
        replay = BacktestReplay.from_result(result, self.bars, self.config)
        return replay, result

    def test_from_result_creates_replay_with_matching_fields(self):
        """from_result creates a replay whose fields match the engine result."""
        replay, result = self._run_and_replay()

        self.assertEqual(replay.run_id, result.run_id)
        self.assertEqual(len(replay.fills), len(result.fills))
        self.assertEqual(len(replay.orders), len(result.orders))
        self.assertEqual(len(replay.events), len(result.events))
        self.assertEqual(len(replay.snapshots), len(result.snapshots))
        self.assertEqual(dict(replay.summary), dict(result.summary))
        self.assertGreater(len(replay.bars), 0)
        self.assertGreater(len(replay.config), 0)

    def test_from_result_serializes_bars_as_dicts(self):
        """Bars in replay should be dicts (serialized), not Bar objects."""
        replay, _ = self._run_and_replay()
        self.assertGreater(len(replay.bars), 0)
        for bar in replay.bars:
            self.assertIsInstance(bar, dict)
            self.assertIn("symbol", bar)
            self.assertIn("close", bar)
            self.assertIn("timestamp_utc", bar)

    def test_from_result_serializes_fills_as_dicts(self):
        """Fills in replay should be dicts (serialized), not Fill objects."""
        replay, _ = self._run_and_replay()
        for fill in replay.fills:
            self.assertIsInstance(fill, dict)
            self.assertIn("symbol", fill)
            self.assertIn("price", fill)

    def test_from_result_serializes_orders_as_dicts(self):
        """Orders in replay should be dicts (serialized), not Order objects."""
        replay, _ = self._run_and_replay()
        for order in replay.orders:
            self.assertIsInstance(order, dict)
            self.assertIn("symbol", order)
            self.assertIn("quantity", order)


class BacktestReplaySaveLoadTests(unittest.TestCase):
    """Tests for save/load round-trip of BacktestReplay."""

    def setUp(self):
        self.bars = _deterministic_bars(60)
        self.strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        self.config = BacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            slippage_bps=0.0,
        )

    def _run_and_replay(self) -> BacktestReplay:
        engine = EventDrivenBacktestEngine(
            strategies=[self.strategy], config=self.config,
        )
        result = engine.run(self.bars)
        return BacktestReplay.from_result(result, self.bars, self.config)

    def test_save_returns_path(self):
        """save() should return a Path object pointing to the written file."""
        replay = self._run_and_replay()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            saved = replay.save(path)
            self.assertIsInstance(saved, Path)
            self.assertTrue(saved.exists())
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_save_load_roundtrip_all_fields_match(self):
        """Save then load: every field in the loaded replay should match the original."""
        replay = self._run_and_replay()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            replay.save(path)
            loaded = BacktestReplay.load(path)

            self.assertEqual(loaded.run_id, replay.run_id)
            self.assertEqual(loaded.config, replay.config)
            self.assertEqual(loaded.summary, replay.summary)
            self.assertEqual(len(loaded.bars), len(replay.bars))
            self.assertEqual(len(loaded.fills), len(replay.fills))
            self.assertEqual(len(loaded.orders), len(replay.orders))
            self.assertEqual(len(loaded.events), len(replay.events))
            self.assertEqual(len(loaded.snapshots), len(replay.snapshots))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_save_load_roundtrip_fill_content_preserved(self):
        """Specific fill fields survive the round-trip."""
        replay = self._run_and_replay()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            replay.save(path)
            loaded = BacktestReplay.load(path)
            if loaded.fills:
                first = loaded.fills[0]
                self.assertIn("symbol", first)
                self.assertIn("side", first)
                self.assertIn("price", first)
                self.assertIn("quantity", first)
                self.assertIn("commission", first)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_save_load_roundtrip_order_content_preserved(self):
        """Specific order fields survive the round-trip."""
        replay = self._run_and_replay()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            replay.save(path)
            loaded = BacktestReplay.load(path)
            if loaded.orders:
                first = loaded.orders[0]
                self.assertIn("symbol", first)
                self.assertIn("side", first)
                self.assertIn("quantity", first)
                self.assertIn("order_type", first)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_save_load_json_structure(self):
        """Saved JSON file contains all expected top-level keys."""
        replay = self._run_and_replay()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            saved_path = replay.save(path)
            raw = json.loads(Path(saved_path).read_text(encoding="utf-8"))
            expected_keys = {
                "run_id", "config", "bars_count", "events_count",
                "fills_count", "orders_count", "snapshots_count",
                "summary", "bars", "events", "fills", "orders", "snapshots",
            }
            self.assertEqual(set(raw.keys()), expected_keys)
            self.assertEqual(raw["run_id"], replay.run_id)
            self.assertEqual(raw["fills_count"], len(replay.fills))
            self.assertEqual(raw["orders_count"], len(replay.orders))
            self.assertEqual(raw["snapshots_count"], len(replay.snapshots))
            self.assertEqual(raw["events_count"], len(replay.events))
            self.assertEqual(raw["bars_count"], len(replay.bars))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_load_nonexistent_file_raises(self):
        """Loading from a non-existent file should raise FileNotFoundError."""
        bad_path = "/tmp/_test_replay_nonexistent_abc123.json"
        with self.assertRaises(FileNotFoundError):
            BacktestReplay.load(bad_path)

    def test_load_corrupted_json_raises(self):
        """Loading corrupted JSON should raise json.JSONDecodeError."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp.write(b"this is not valid json at all")
            path = tmp.name
        try:
            with self.assertRaises(json.JSONDecodeError):
                BacktestReplay.load(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_save_load_empty_replay(self):
        """Replay with no fills/orders/snapshots/bars survives save/load."""
        replay = BacktestReplay(
            run_id="empty_test",
            bars=[],
            fills=[],
            orders=[],
            snapshots=[],
            summary={},
            config={},
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            replay.save(path)
            loaded = BacktestReplay.load(path)
            self.assertEqual(loaded.run_id, "empty_test")
            self.assertEqual(len(loaded.fills), 0)
            self.assertEqual(len(loaded.orders), 0)
            self.assertEqual(len(loaded.snapshots), 0)
            self.assertEqual(len(loaded.bars), 0)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class BacktestReplayDeterminismTests(unittest.TestCase):
    """Tests for verify_determinism — identical and mismatching scenarios."""

    def setUp(self):
        self.bars = _deterministic_bars(60)
        self.strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        self.config = BacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0,
            slippage_bps=0.0,
        )

    def _run_and_replay(self) -> BacktestReplay:
        engine = EventDrivenBacktestEngine(
            strategies=[self.strategy], config=self.config,
        )
        result = engine.run(self.bars)
        return BacktestReplay.from_result(result, self.bars, self.config)

    def test_identical_run_is_deterministic(self):
        """Re-running the same bars with a fresh strategy should produce identical results."""
        replay = self._run_and_replay()
        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=self.config,
        )
        self.assertTrue(result["deterministic"])
        self.assertEqual(len(result["mismatches"]), 0)
        self.assertEqual(result["run_id"], replay.run_id)
        self.assertIn("replay_summary", result)

    def test_identical_run_multiple_symbols(self):
        """Determinism holds with a multi-symbol universe."""
        symbols = ["AAPL", "MSFT", "GOOGL"]
        all_bars: list[Bar] = []
        for sym in symbols:
            all_bars.extend(_deterministic_bars(30, sym))
        config = BacktestConfig(
            initial_cash=1_000_000.0,
            commission_rate=0.0,
            slippage_bps=0.0,
        )
        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        engine = EventDrivenBacktestEngine(strategies=[strategy], config=config)
        result = engine.run(all_bars)
        replay = BacktestReplay.from_result(result, all_bars, config)

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        det_result = replay.verify_determinism(
            strategies=[fresh],
            bars=all_bars,
            config=config,
        )
        self.assertTrue(det_result["deterministic"])

    def test_identical_run_with_commission(self):
        """Determinism holds when commission and slippage are non-zero."""
        config = BacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.001,
            slippage_bps=5.0,
        )
        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        engine = EventDrivenBacktestEngine(strategies=[strategy], config=config)
        result = engine.run(self.bars)
        replay = BacktestReplay.from_result(result, self.bars, config)

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        det_result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=config,
        )
        self.assertTrue(det_result["deterministic"])

    def test_different_fill_count_is_detected(self):
        """Adding an extra fill causes fill count mismatch."""
        replay = self._run_and_replay()
        extra_fill = {
            "order_id": new_id("ord"),
            "symbol": "AAPL",
            "side": OrderSide.BUY.value,
            "quantity": 10.0,
            "price": 100.0,
            "commission": 0.0,
            "filled_at": datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).isoformat(),
            "broker": "test",
            "fill_id": new_id("fill"),
        }
        replay.fills.append(extra_fill)

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=self.config,
        )
        self.assertFalse(result["deterministic"])
        self.assertTrue(
            any("fill count" in m for m in result["mismatches"]),
            f"Expected fill count mismatch, got: {result['mismatches']}",
        )

    def test_different_order_count_is_detected(self):
        """Adding an extra order causes order count mismatch."""
        replay = self._run_and_replay()
        extra_order: dict = {
            "order_id": new_id("ord"),
            "symbol": "AAPL",
            "side": OrderSide.BUY.value,
            "quantity": 10.0,
            "order_type": "MARKET",
            "time_in_force": "DAY",
            "client_order_id": new_id("coid"),
            "run_id": replay.run_id,
            "status": "CREATED",
            "timestamp_utc": datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).isoformat(),
            "created_at": datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).isoformat(),
            "updated_at": datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).isoformat(),
        }
        replay.orders.append(extra_order)

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=self.config,
        )
        self.assertFalse(result["deterministic"])
        self.assertTrue(
            any("order count" in m for m in result["mismatches"]),
            f"Expected order count mismatch, got: {result['mismatches']}",
        )

    def test_different_summary_metrics_are_detected(self):
        """Altering a summary metric causes mismatch."""
        replay = self._run_and_replay()
        replay.summary["total_return_pct"] = 999.0  # Deliberately wrong

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=self.config,
        )
        self.assertFalse(result["deterministic"])
        summary_mismatches = [
            m for m in result["mismatches"] if "total_return_pct" in m
        ]
        self.assertGreater(len(summary_mismatches), 0)

    def test_different_snapshot_count_is_detected(self):
        """Adding an extra snapshot causes snapshot count mismatch."""
        replay = self._run_and_replay()
        extra_snapshot: dict = {
            "timestamp_utc": datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc).isoformat(),
            "equity": 100_000.0,
            "cash": 100_000.0,
            "gross_exposure": 0.0,
            "net_exposure": 0.0,
            "daily_pnl": 0.0,
            "drawdown": 0.0,
        }
        replay.snapshots.append(extra_snapshot)

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=self.config,
        )
        self.assertFalse(result["deterministic"])
        self.assertTrue(
            any("snapshot count" in m for m in result["mismatches"]),
            f"Expected snapshot count mismatch, got: {result['mismatches']}",
        )

    def test_multiple_mismatches_together(self):
        """Altering fills, orders, snapshots, and summary simultaneously."""
        replay = self._run_and_replay()
        # Add one extra of each
        replay.fills.append({
            "order_id": new_id("ord"), "symbol": "AAPL",
            "side": OrderSide.BUY.value, "quantity": 1.0, "price": 150.0,
            "commission": 0.0, "filled_at": "2024-01-02T10:00:00+00:00",
            "broker": "test", "fill_id": new_id("fill"),
        })
        replay.orders.append({
            "order_id": new_id("ord"), "symbol": "AAPL",
            "side": OrderSide.BUY.value, "quantity": 1.0,
            "order_type": "MARKET", "time_in_force": "DAY",
            "client_order_id": new_id("coid"), "run_id": replay.run_id,
            "status": "CREATED",
            "timestamp_utc": "2024-01-02T10:00:00+00:00",
            "created_at": "2024-01-02T10:00:00+00:00",
            "updated_at": "2024-01-02T10:00:00+00:00",
        })
        replay.snapshots.append({
            "timestamp_utc": "2024-01-02T16:00:00+00:00",
            "equity": 100_000.0, "cash": 100_000.0,
            "gross_exposure": 0.0, "net_exposure": 0.0,
            "daily_pnl": 0.0, "drawdown": 0.0,
        })
        replay.summary["sharpe_ratio"] = 99.0

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=self.bars,
            config=self.config,
        )
        self.assertFalse(result["deterministic"])
        self.assertGreaterEqual(len(result["mismatches"]), 4)

    def test_empty_bars_deterministic(self):
        """With empty bars, both runs produce identical empty results."""
        config = BacktestConfig(initial_cash=100_000.0)
        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        engine = EventDrivenBacktestEngine(strategies=[strategy], config=config)
        result = engine.run([])
        replay = BacktestReplay.from_result(result, [], config)

        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        det_result = replay.verify_determinism(
            strategies=[fresh],
            bars=[],
            config=config,
        )
        self.assertTrue(det_result["deterministic"])

    def test_empty_replay_manual_verify(self):
        """Manually constructed empty replay still verifies determinism correctly."""
        replay = BacktestReplay(
            run_id="manual_empty",
            bars=[],
            fills=[],
            orders=[],
            snapshots=[],
            summary={},
            config={},
        )
        config = BacktestConfig(initial_cash=100_000.0)
        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        # This should not crash and should be deterministic (both empty)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=[],
            config=config,
        )
        self.assertTrue(result["deterministic"])


class BacktestReplayEdgeCaseTests(unittest.TestCase):
    """Edge-case tests for BacktestReplay construction and invariants."""

    def test_default_construction(self):
        """Default BacktestReplay has empty fields, not None."""
        replay = BacktestReplay()
        self.assertEqual(replay.run_id, "")
        self.assertEqual(replay.bars, [])
        self.assertEqual(replay.fills, [])
        self.assertEqual(replay.orders, [])
        self.assertEqual(replay.snapshots, [])
        self.assertEqual(replay.summary, {})
        self.assertEqual(replay.config, {})

    def test_replay_config_defaults_used_when_empty(self):
        """verify_determinism uses config defaults when replay.config is empty."""
        replay = BacktestReplay(
            run_id="no_config",
            config={},
            summary={"total_return_pct": 0.0, "sharpe_ratio": 0.0,
                     "max_drawdown_pct": 0.0, "trade_count": 0},
        )
        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        # Should not crash with empty config — uses defaults internally
        diag_bars = _deterministic_bars(10)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=diag_bars,
        )
        self.assertIsInstance(result["deterministic"], bool)

    def test_run_id_propagates_to_verify_result(self):
        """verify_determinism returns the original run_id."""
        replay = self._make_simple_replay()
        fresh = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        result = replay.verify_determinism(
            strategies=[fresh],
            bars=_deterministic_bars(20),
        )
        self.assertEqual(result["run_id"], "propagation_test")

    def _make_simple_replay(self) -> BacktestReplay:
        bars = _deterministic_bars(20)
        config = BacktestConfig(initial_cash=100_000.0)
        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        engine = EventDrivenBacktestEngine(strategies=[strategy], config=config)
        result = engine.run(bars)
        replay = BacktestReplay.from_result(result, bars, config)
        replay.run_id = "propagation_test"
        return replay


if __name__ == "__main__":
    unittest.main()
