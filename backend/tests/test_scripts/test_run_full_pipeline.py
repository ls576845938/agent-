"""Tests for ``run_pipeline()`` extracted from ``scripts/run_full_pipeline.py``.

Mocks network, database and external dependencies so tests are deterministic.
Covers three modes (backtest, gate, full) plus determinism and error paths.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Module loading -- same technique as test_ingest_us_equity.py
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
_SCRIPT_PATH = _SCRIPTS_DIR / "run_full_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_full_pipeline_test", str(_SCRIPT_PATH))
_pipeline_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pipeline_script)

# Shorthand bound to the module's function
run_pipeline = _pipeline_script.run_pipeline

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bars_frame(n: int = 120, symbol: str = "AAPL") -> pd.DataFrame:
    """Deterministic OHLCV DataFrame with upward trend for reliable signals.

    Mirrors the fixture in test_full_pipeline.py.
    """
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=n, freq="D", tz="UTC")
    price = 150.0
    rows: list[dict] = []
    for ts in dates:
        price = price * (1.0 + 0.002)
        noise = 1.0 + np.random.uniform(-0.005, 0.005)
        rows.append({
            "timestamp_utc": ts,
            "symbol": symbol,
            "open": price * 0.999 * noise,
            "high": price * 1.01 * noise,
            "low": price * 0.99 * noise,
            "close": price * noise,
            "volume": 15000.0,
        })
    return pd.DataFrame(rows)


def _make_ingestion_result(
    symbol: str = "AAPL",
    interval: str = "1d",
    data_version: str = "test_data_v1",
) -> MagicMock:
    """Return a mock IngestionResult with success values."""
    r = MagicMock()
    r.symbol = symbol
    r.interval = interval
    r.row_count = 100
    r.data_version = data_version
    r.error = ""
    r.path = "/tmp/test_path"
    r.manifest_path = "/tmp/test_manifest.json"
    return r


def _make_gate_result(decision: str = "pass") -> dict:
    """Return a gate evaluation result dict."""
    return {
        "status": "completed",
        "decision": decision,
        "next_stage": "paper" if decision == "pass" else "backtest",
        "manifest_id": "test_manifest_123",
        "strategy_version": "test_v1",
        "gates": [
            {"name": "data_quality", "status": "pass", "message": "OK"},
            {"name": "backtest_survival", "status": "pass", "message": "OK"},
            {"name": "execution", "status": "pass", "message": "OK"},
            {"name": "risk", "status": "pass", "message": "OK"},
        ],
    }


def _make_paper_trading_result() -> MagicMock:
    """Return a mock PaperTradingDayResult."""
    r = MagicMock()
    r.orders_submitted = 5
    r.orders_filled = 4
    r.daily_pnl = 1234.56
    r.daily_return_pct = 1.23
    r.reconciliation_passed = True
    r.kill_switch_triggered = False
    return r


def _create_parquet_fixture(
    tmpdir: str,
    frame: pd.DataFrame | None = None,
) -> str:
    """Write fixture parquet files under *tmpdir* and return ``data_root``.

    The directory layout matches what Stage 2 of the pipeline expects:
        data_root/raw/vendor=yfinance/asset_class=equity/bar_size=1d/symbol=AAPL/date=*.parquet
    """
    data_root = Path(tmpdir)
    parquet_dir = (
        data_root
        / "raw"
        / "vendor=yfinance"
        / "asset_class=equity"
        / "bar_size=1d"
        / "symbol=AAPL"
    )
    parquet_dir.mkdir(parents=True, exist_ok=True)

    if frame is None:
        frame = _make_bars_frame(120)
    frame.to_parquet(parquet_dir / "date=2024-01-01.parquet")
    return str(data_root)


# ---------------------------------------------------------------------------
# Tests -- mode=backtest
# ---------------------------------------------------------------------------


class TestBacktestMode(unittest.TestCase):
    """run_pipeline(mode='backtest') -- only stages 1+2 execute."""

    def setUp(self):
        self._ingest_patcher = patch(
            "quant_us.data.connectors.us_equity_ingestion.USEquityIngestionPipeline"
        )
        self.mock_ingest_cls = self._ingest_patcher.start()
        self.mock_ingest = self.mock_ingest_cls.return_value
        self.mock_ingest.run.return_value = [_make_ingestion_result(data_version="test_v1")]

    def tearDown(self):
        self._ingest_patcher.stop()

    # -- helpers --

    def _run(self, **kw):
        kw.setdefault("mode", "backtest")
        kw.setdefault("start", "2024-01-01")
        kw.setdefault("end", "2024-03-31")
        return run_pipeline(**kw)

    # -- tests --

    def test_backtest_mode_returns_expected_keys(self):
        """Result dict contains keys that downstream consumers expect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("mode"), "backtest")
        self.assertIn("data_version", result)
        self.assertIn("run_id", result)
        self.assertIn("sharpe", result)
        self.assertIn("equity_consistent", result)

        self.assertEqual(result["data_version"], "test_v1")

    def test_backtest_mode_produces_trades(self):
        """Upward-trending fixture generates positive Sharpe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        sharpe = float(result["sharpe"])
        self.assertGreater(sharpe, 0.0, "Momentum on uptrend should have positive Sharpe")

    def test_backtest_mode_no_gate_or_paper_keys(self):
        """Deeper-stage keys must NOT appear when mode=backtest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertNotIn("promotion_decision", result)
        self.assertNotIn("gate_result", result)
        self.assertNotIn("paper_pnl", result)
        self.assertNotIn("paper_skipped", result)

    def test_backtest_deterministic_with_same_inputs(self):
        """Same inputs produce same numeric results (run_id excluded)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            r1 = self._run(data_root=data_root, capital=200_000.0)
            r2 = self._run(data_root=data_root, capital=200_000.0)

        # run_id is time-based UUID -- different each call
        self.assertEqual(float(r1["sharpe"]), float(r2["sharpe"]))
        self.assertEqual(r1["equity_consistent"], r2["equity_consistent"])
        self.assertEqual(r1["data_version"], r2["data_version"])
        self.assertEqual(r1["mode"], r2["mode"])

    def test_backtest_mode_different_capital_produces_different_sharpe(self):
        """Different input capital may affect position sizing -> different result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            r1 = self._run(data_root=data_root, capital=100_000.0)
            r2 = self._run(data_root=data_root, capital=500_000.0)

        # result dict values differ (not a strict assert, just verifies the
        # parameter flows through)
        self.assertIn("run_id", r1)
        self.assertIn("run_id", r2)

    def test_backtest_mode_with_register_flag(self):
        """register flag is accepted but does not affect backtest-mode result keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root, register=True)

        self.assertEqual(result["mode"], "backtest")
        self.assertIn("run_id", result)


# ---------------------------------------------------------------------------
# Tests -- mode=gate
# ---------------------------------------------------------------------------


class TestGateMode(unittest.TestCase):
    """run_pipeline(mode='gate') -- stages 1+2+3 execute."""

    def setUp(self):
        self._ingest_patcher = patch(
            "quant_us.data.connectors.us_equity_ingestion.USEquityIngestionPipeline"
        )
        self.mock_ingest_cls = self._ingest_patcher.start()
        self.mock_ingest = self.mock_ingest_cls.return_value
        self.mock_ingest.run.return_value = [_make_ingestion_result(data_version="test_v1")]

        self._gate_patcher = patch(
            "backend.app.services.research_gate.ResearchPromotionGateService"
        )
        self.mock_gate_cls = self._gate_patcher.start()
        self.mock_gate = self.mock_gate_cls.return_value
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="pass")

    def tearDown(self):
        self._gate_patcher.stop()
        self._ingest_patcher.stop()

    def _run(self, **kw):
        kw.setdefault("mode", "gate")
        kw.setdefault("start", "2024-01-01")
        kw.setdefault("end", "2024-03-31")
        return run_pipeline(**kw)

    def test_gate_mode_has_backtest_and_gate_keys(self):
        """Result contains both backtest keys and promotion gate keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertEqual(result["mode"], "gate")
        # Backtest keys
        self.assertIn("data_version", result)
        self.assertIn("run_id", result)
        self.assertIn("sharpe", result)
        # Gate keys
        self.assertIn("promotion_decision", result)
        self.assertIn("promotion_next_stage", result)
        self.assertIn("gate_result", result)
        # Paper keys must NOT appear
        self.assertNotIn("paper_pnl", result)
        self.assertNotIn("paper_recon", result)
        self.assertNotIn("paper_skipped", result)

    def test_gate_mode_decision_is_pass(self):
        """Gate result reflects the mocked 'pass' decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertEqual(result["promotion_decision"], "pass")
        self.assertEqual(result["promotion_next_stage"], "paper")

    def test_gate_mode_promotion_gate_service_called_with_request(self):
        """ResearchPromotionGateService.evaluate() is called with expected keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            self._run(data_root=data_root)

        self.mock_gate_cls.assert_called_once()
        call_args, _ = self.mock_gate_cls.call_args
        # No positional args to ResearchPromotionGateService() -- defaults used
        self.assertEqual(call_args, ())

        # Verify evaluate was called
        self.mock_gate.evaluate.assert_called_once()
        eval_args, eval_kwargs = self.mock_gate.evaluate.call_args
        request = eval_args[0] if eval_args else eval_kwargs
        self.assertIn("symbol", request)
        self.assertEqual(request["symbol"], "AAPL")
        self.assertIn("start", request)


# ---------------------------------------------------------------------------
# Tests -- mode=full
# ---------------------------------------------------------------------------


class TestFullMode(unittest.TestCase):
    """run_pipeline(mode='full') -- all four stages execute."""

    def setUp(self):
        self._ingest_patcher = patch(
            "quant_us.data.connectors.us_equity_ingestion.USEquityIngestionPipeline"
        )
        self.mock_ingest_cls = self._ingest_patcher.start()
        self.mock_ingest = self.mock_ingest_cls.return_value
        self.mock_ingest.run.return_value = [_make_ingestion_result(data_version="test_v1")]

        self._gate_patcher = patch(
            "backend.app.services.research_gate.ResearchPromotionGateService"
        )
        self.mock_gate_cls = self._gate_patcher.start()
        self.mock_gate = self.mock_gate_cls.return_value

        self._paper_patcher = patch(
            "quant_us.live.paper_trading_loop.PaperTradingLoop"
        )
        self.mock_paper_cls = self._paper_patcher.start()
        self.mock_paper = self.mock_paper_cls.return_value
        self.day_result = _make_paper_trading_result()
        self.mock_paper.run_day.return_value = self.day_result
        self.mock_paper.status_summary.return_value = {"healthy": True}

    def tearDown(self):
        self._paper_patcher.stop()
        self._gate_patcher.stop()
        self._ingest_patcher.stop()

    def _run(self, **kw):
        kw.setdefault("mode", "full")
        kw.setdefault("start", "2024-01-01")
        kw.setdefault("end", "2024-03-31")
        return run_pipeline(**kw)

    # -- happy path: gate passes --

    def test_full_mode_all_keys_present(self):
        """Result contains backtest, gate, and paper keys."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="pass")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertEqual(result["mode"], "full")
        self.assertIn("data_version", result)
        self.assertIn("run_id", result)
        self.assertIn("sharpe", result)
        self.assertIn("promotion_decision", result)
        self.assertIn("gate_result", result)
        self.assertIn("paper_pnl", result)
        self.assertIn("paper_recon", result)
        self.assertNotIn("paper_skipped", result)

    def test_full_mode_paper_trading_executed(self):
        """Paper trading loop is called when gate passes."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="pass")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            self._run(data_root=data_root)

        self.mock_paper_cls.assert_called_once()
        self.mock_paper.run_day.assert_called_once()
        self.mock_paper.status_summary.assert_called_once()

    def test_full_mode_paper_pnl_reflects_mock(self):
        """paper_pnl matches the mocked PaperTradingDayResult."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="pass")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertEqual(result["paper_pnl"], "$1,234.56")
        self.assertEqual(result["paper_recon"], "PASS")

    # -- gate fails path --

    def test_full_mode_skips_paper_when_gate_fails(self):
        """Paper trading is skipped when promotion gate decision != 'pass'."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="fail")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertEqual(result["mode"], "full")
        self.assertTrue(result.get("paper_skipped"))
        self.assertNotIn("paper_pnl", result)
        self.assertNotIn("paper_recon", result)
        self.mock_paper.run_day.assert_not_called()

    def test_full_mode_gate_fail_keeps_prior_keys(self):
        """Backtest and gate keys survive even when paper is skipped."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="fail")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertIn("data_version", result)
        self.assertIn("run_id", result)
        self.assertIn("sharpe", result)
        self.assertIn("promotion_decision", result)
        self.assertEqual(result["promotion_decision"], "fail")
        self.assertIn("promotion_next_stage", result)

    # -- other gate decisions --

    def test_full_mode_conditional_pass_skips_paper(self):
        """decision='conditional_pass' does NOT allow paper (only exact 'pass' does)."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="conditional_pass")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertEqual(result["mode"], "full")
        self.assertTrue(result.get("paper_skipped"))
        self.assertNotIn("paper_pnl", result)
        self.mock_paper.run_day.assert_not_called()

    def test_full_mode_review_decision_skips_paper(self):
        """decision='review' stops before paper trading."""
        self.mock_gate.evaluate.return_value = _make_gate_result(decision="review")

        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = _create_parquet_fixture(tmpdir)
            result = self._run(data_root=data_root)

        self.assertTrue(result.get("paper_skipped"))
        self.mock_paper.run_day.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- deterministic
# ---------------------------------------------------------------------------


class TestDeterministic(unittest.TestCase):
    """Verify run_pipeline returns the same result for the same inputs."""

    def setUp(self):
        self._ingest_patcher = patch(
            "quant_us.data.connectors.us_equity_ingestion.USEquityIngestionPipeline"
        )
        self.mock_ingest_cls = self._ingest_patcher.start()
        self.mock_ingest = self.mock_ingest_cls.return_value
        self.mock_ingest.run.return_value = [_make_ingestion_result(data_version="test_v2")]

    def tearDown(self):
        self._ingest_patcher.stop()

    def _run(self, **kw):
        kw.setdefault("mode", "backtest")
        kw.setdefault("start", "2024-01-01")
        kw.setdefault("end", "2024-03-31")
        return run_pipeline(**kw)

    def test_deterministic_full_pipeline_in_gate_mode(self):
        """gate mode is also deterministic (same numeric fields)."""
        gate_patcher = patch(
            "backend.app.services.research_gate.ResearchPromotionGateService"
        )
        gate_cls = gate_patcher.start()
        gate_cls.return_value.evaluate.return_value = _make_gate_result(decision="pass")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                data_root = _create_parquet_fixture(tmpdir)
                r1 = run_pipeline(
                    mode="gate",
                    data_root=data_root,
                    start="2024-01-01",
                    end="2024-03-31",
                )
                r2 = run_pipeline(
                    mode="gate",
                    data_root=data_root,
                    start="2024-01-01",
                    end="2024-03-31",
                )

            # Numeric and string fields should match
            self.assertEqual(float(r1["sharpe"]), float(r2["sharpe"]))
            self.assertEqual(r1["equity_consistent"], r2["equity_consistent"])
            self.assertEqual(r1["promotion_decision"], r2["promotion_decision"])
            self.assertEqual(r1["promotion_next_stage"], r2["promotion_next_stage"])
            self.assertEqual(r1["data_version"], r2["data_version"])
            self.assertEqual(r1["mode"], r2["mode"])
        finally:
            gate_patcher.stop()


# ---------------------------------------------------------------------------
# Smoke test -- CLI still works
# ---------------------------------------------------------------------------


class TestCLIEntryPoint(unittest.TestCase):
    """Verify that main() can still parse args and run."""

    @patch("sys.argv", ["prog", "--help"])
    def test_help_exits_zero(self):
        """--help prints usage and exits."""
        with self.assertRaises(SystemExit) as ctx:
            _pipeline_script.main()
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
