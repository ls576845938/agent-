from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.minute_quality_gate import _expected_regular_timestamps
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill
from quant_us.core.calendar import USEquityCalendar


TESTCLIENT_AVAILABLE = bool(importlib.util.find_spec("fastapi")) and bool(importlib.util.find_spec("httpx"))


def _write_portfolio_observability(data_root: Path) -> None:
    report_dir = data_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "portfolio_observability.json").write_text(
        """{
  "multi_strategy": {"status": "PASS", "strategies": ["trend_macd", "reversion_rsi"]},
  "multi_timeframe": {"status": "PASS", "timeframes": ["1d", "1h"]},
  "pnl_attribution": {"status": "PASS", "rows": [{"strategy_id": "trend_macd", "pnl": 1.0}]}
}""",
        encoding="utf-8",
    )


def _write_qlib_run(artifacts_root: Path, run_id: str, *, workflow_status: str = "completed", dataset_status: str = "completed") -> None:
    run_root = artifacts_root / run_id
    (run_root / "qlib_input").mkdir(parents=True, exist_ok=True)
    (run_root / "qlib_input" / "dataset_manifest.json").write_text(
        json.dumps({
            "status": dataset_status,
            "symbols_exported": ["AAPL", "MSFT"],
            "symbols_requested": ["AAPL", "MSFT"],
        }),
        encoding="utf-8",
    )
    (run_root / "provider_manifest.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (run_root / "workflow_run_result.json").write_text(json.dumps({"status": workflow_status}), encoding="utf-8")
    (run_root / "qlib_strategy_manifest.json").write_text(
        json.dumps({
            "status": "completed",
            "promotion_status": "READY_FOR_PAPER_REVIEW",
            "strategy_id": "trend_macd",
        }),
        encoding="utf-8",
    )


def _write_portfolio_run(artifacts_root: Path, run_id: str, *, optimizer: str = "max_sharpe") -> None:
    run_root = artifacts_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps({
            "source_score_run_id": "qlib_run_20260511",
            "config": {"optimizer": optimizer},
            "fallback_used": False,
        }),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "datetime": ["2026-05-11T00:00:00Z", "2026-05-11T00:00:00Z"],
            "symbol": ["AAPL", "MSFT"],
            "target_weight": [0.6, 0.4],
        }
    ).to_parquet(run_root / "target_weights.parquet", index=False)
    pd.DataFrame(
        {
            "timestamp_utc": ["2026-05-11T00:00:00Z"],
            "strategy_id": ["pypfopt_daily_only"],
            "symbol": ["AAPL"],
            "target_weight": [0.6],
            "target_quantity": [6],
        }
    ).to_parquet(run_root / "target_positions.parquet", index=False)


def _write_conflicting_registry(data_root: Path) -> None:
    registry_path = data_root / "research" / "evidence_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({
            "schema_version": "evidence_registry_v1",
            "generated_at": "2026-05-11T00:00:00Z",
            "registry_notes": ["conflicting_registry_evidence:paper_review:demo"],
            "counts": {},
            "evidence": {
                "paper_reviews": [
                    {
                        "id": "review_conflict_1",
                        "path": str(data_root / "research" / "paper_review" / "review_conflict_1.json"),
                        "integrity_status": "CONFLICT",
                        "details": {
                            "status": "CONFLICT",
                            "evidence_pack_path": str(data_root / "research" / "paper_review" / "pack.json"),
                        },
                    }
                ],
                "strategy_manifests": [
                    {
                        "id": "manifest_1",
                        "path": str(data_root / "research" / "strategy_manifests" / "manifest_1.json"),
                        "details": {"promotion_status": "READY_FOR_PAPER_REVIEW"},
                    }
                ],
            },
        }),
        encoding="utf-8",
    )


def _write_minute_partition(
    data_root: Path,
    *,
    root_subdir: str,
    symbol: str,
    bar_size: str,
    trading_day: str,
    timestamps: list[datetime],
) -> None:
    path = (
        data_root
        / root_subdir
        / "vendor=yfinance"
        / "asset_class=equity"
        / f"bar_size={bar_size}"
        / f"symbol={symbol}"
        / f"date={trading_day}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": [symbol] * len(timestamps),
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.5] * len(timestamps),
            "volume": [1_000] * len(timestamps),
        }
    ).to_parquet(path, index=False)


class ApiSchemaDefaultTests(unittest.TestCase):
    def test_backtest_request_defaults_are_us_equity(self) -> None:
        from backend.app.api.schemas import BaseBacktestRequest, DataQualityRequest

        payload = {
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-02-01T00:00:00Z",
        }
        backtest = BaseBacktestRequest.model_validate(payload)
        quality = DataQualityRequest.model_validate(payload)

        self.assertEqual(backtest.source, "yfinance")
        self.assertEqual(backtest.symbol, "SPY")
        self.assertEqual(backtest.interval, "1d")
        self.assertEqual(quality.source, "yfinance")
        self.assertEqual(quality.symbol, "SPY")
        self.assertEqual(quality.interval, "1d")

    def test_system_overview_payload_is_read_only_pre_live(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            payload = _system_overview_payload(directory)
            self.assertFalse((root / "research" / "evidence_registry.json").exists())

        self.assertEqual(payload["mode"], "pre_live")
        self.assertEqual(payload["execution"]["live_state"], "frozen")
        self.assertFalse(payload["execution"]["live_submit_allowed"])
        self.assertEqual(payload["execution"]["paper_submit_default"], "disabled")
        self.assertEqual(payload["portfolio_observability"]["live_state"], "FROZEN")
        self.assertEqual(payload["portfolio_observability"]["multi_strategy"]["status"], "PASS")
        self.assertEqual(payload["portfolio_observability"]["multi_timeframe"]["status"], "PASS")
        self.assertEqual(payload["portfolio_observability"]["pnl_attribution"]["status"], "PASS")
        self.assertEqual(payload["minute_data_quality"]["status"], "MISSING")
        self.assertEqual(len(payload["minute_data_quality"]["datasets"]), 2)
        self.assertEqual(
            {item["root_subdir"] for item in payload["minute_data_quality"]["datasets"]},
            {"raw", "cleaned"},
        )
        self.assertEqual(
            payload["portfolio_observability"]["paper_submit_gates"]["state"],
            "BLOCKED_BY_DEFAULT",
        )
        self.assertFalse(payload["execution"]["paper_network_submit_confirmation"])
        self.assertEqual(payload["registry"]["state"], "missing")
        self.assertIn("integrations", payload)
        self.assertIn("data_coverage", payload)
        self.assertIn("diagnostics", payload["paper_review"])
        self.assertTrue(payload["next_actions"])

    def test_system_overview_payload_includes_latest_runs_and_conflict_diagnostics(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            _write_conflicting_registry(root)
            qlib_root = root / "artifacts" / "qlib_runs"
            portfolio_root = root / "artifacts" / "portfolio_runs"
            _write_qlib_run(qlib_root, "qlib_run_20260510")
            _write_qlib_run(qlib_root, "qlib_run_20260511")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260510")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260511")

            payload = _system_overview_payload(
                directory,
                qlib_artifacts_root=str(qlib_root),
                portfolio_artifacts_root=str(portfolio_root),
            )

        self.assertEqual(payload["integrations"]["qlib"]["latest_run"]["run_id"], "qlib_run_20260511")
        self.assertEqual(payload["integrations"]["portfolio"]["latest_run"]["portfolio_run_id"], "portfolio_run_20260511")
        self.assertTrue(payload["paper_review"]["diagnostics"]["conflict_detected"])
        self.assertEqual(payload["paper_review"]["status"], "CONFLICT")
        self.assertIn("coverage_pct", payload["data_coverage"])

    def test_system_overview_payload_blocks_on_minute_quality_fail(self) -> None:
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            calendar = USEquityCalendar.with_holidays()
            trading_day = datetime(2026, 5, 8, tzinfo=timezone.utc).date()
            trading_days = [trading_day]
            while len(trading_days) < 5:
                trading_days.append(calendar.previous_trading_day(trading_days[-1]))
            for current_day in sorted(trading_days):
                for bar_size in ("1m", "5m", "15m"):
                    full = _expected_regular_timestamps(
                        current_day,
                        int(bar_size.removesuffix("m")),
                        calendar,
                    )
                    raw_timestamps = full[:100] if (bar_size == "1m" and current_day == trading_day) else full
                    _write_minute_partition(
                        root,
                        root_subdir="raw",
                        symbol="AAPL",
                        bar_size=bar_size,
                        trading_day=current_day.isoformat(),
                        timestamps=raw_timestamps,
                    )
                    _write_minute_partition(
                        root,
                        root_subdir="cleaned",
                        symbol="AAPL",
                        bar_size=bar_size,
                        trading_day=current_day.isoformat(),
                        timestamps=full,
                    )
            payload = _system_overview_payload(directory)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stage"], "registry_blocked")
        self.assertEqual(payload["minute_data_quality"]["status"], "FAIL")
        dataset_statuses = payload["minute_data_quality"]["dataset_statuses"]
        self.assertEqual(dataset_statuses["raw"]["status"], "FAIL")
        self.assertEqual(dataset_statuses["cleaned"]["status"], "PASS")

    def test_system_overview_payload_does_not_block_on_placeholder_minute_layout(self) -> None:
        from quant_us.reports.paper_validation import PaperValidationEvidence
        from backend.app.api.app_factory import _system_overview_payload

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            for bar_size in ("1m", "5m", "15m"):
                (
                    root
                    / "raw"
                    / "vendor=yfinance"
                    / "asset_class=equity"
                    / f"bar_size={bar_size}"
                ).mkdir(parents=True, exist_ok=True)

            paper_evidence = PaperValidationEvidence(
                data_root=directory,
                ledger_root=str(root / "paper_ledger"),
                validation_state_path=str(root / "reports" / "paper_production" / "validation_state.json"),
                days_required=30,
                days_completed=30,
                consecutive_clean_days=30,
                paper_submit_orders="disabled",
                readiness_state="PASS",
                audit_blocker_status="PASS",
                data_strict_status="PASS",
                recovery_status="PASS",
                gaps=[],
                evidence=[],
            )

            with (
                patch(
                    "backend.app.api.app_factory._fast_saved_evidence_registry",
                    return_value={
                        "registry_status": "present",
                        "registry_integrity_status": "PASS/STABLE",
                        "registry_path": str(root / "research" / "evidence_registry.json"),
                        "counts": {},
                        "registry_notes": [],
                        "rebuild_available": True,
                    },
                ),
                patch(
                    "backend.app.api.app_factory._fast_paper_review_status",
                    return_value={
                        "status": "APPROVED",
                        "entry_allowed": True,
                        "manual_review_pending": False,
                        "summary": "approved",
                        "evidence_path": str(root / "reports" / "paper_review.json"),
                        "diagnostics": {},
                    },
                ),
                patch(
                    "quant_us.reports.paper_validation.inspect_paper_validation_evidence",
                    return_value=paper_evidence,
                ),
                patch(
                    "quant_us.live.paper_adapter_contract.audit_apca_paper_credentials",
                    return_value={
                        "credentials_present": True,
                        "base_url_valid": True,
                    },
                ),
            ):
                payload = _system_overview_payload(directory)

        self.assertEqual(payload["minute_data_quality"]["status"], "MISSING")
        self.assertEqual(payload["stage"], "paper_ready_for_manual_gate")
        self.assertEqual(payload["status"], "reviewable")
        self.assertGreaterEqual(payload["minute_data_quality"]["remediation_summary"]["action_count"], 1)
        self.assertTrue(
            any("ingest_intraday.py" in step for step in payload["next_actions"]),
        )


@unittest.skipUnless(TESTCLIENT_AVAILABLE, "FastAPI TestClient dependencies are not installed in the current environment")
class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.api.app_factory import create_app

        self.client = TestClient(create_app())

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")

    def test_crypto_resample_endpoint_serializes_dataclass_result(self) -> None:
        from backend.app.services.data_management import CryptoResampleResult

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        fake_result = CryptoResampleResult(
            status="completed",
            db_path="data/market_data.sqlite",
            exchange="binance_spot",
            symbol="BTCUSDT",
            source_interval="1m",
            target_interval="1h",
            start=start,
            end=end,
            source_rows=60,
            expected_source_rows=60,
            rows_written=1,
            coverage_pct=100.0,
            quality_score=100.0,
            data_version="btc-resample-test",
            quality_summary={"issues": 0},
        )
        with patch(
            "backend.app.api.app_factory.market_data_service.resample_crypto_klines",
            return_value=fake_result,
        ):
            response = self.client.post(
                "/api/data/resample",
                json={
                    "exchange": "binance_spot",
                    "symbol": "BTCUSDT",
                    "source_interval": "1m",
                    "target_interval": "1h",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "persist_manifest": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["target_interval"], "1h")
        self.assertEqual(payload["rows_written"], 1)

    def test_crypto_event_backtest_endpoint_uses_research_service(self) -> None:
        from backend.app.domain.models import BacktestArtifacts

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)
        fake_artifacts = BacktestArtifacts(
            mode="crypto_event",
            summary={
                "total_return_pct": 0.0,
                "annual_return_pct": 0.0,
                "annual_volatility_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "calmar_ratio": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "trade_count": 0,
            },
            chart={"candles": [], "markers": [], "equity": [], "drawdown": [], "exposure": [], "net_units": []},
            strategy_details=[],
            latest_weights=[],
            diagnostics={"engine": "event_driven"},
        )
        with patch(
            "backend.app.api.app_factory.research_service.run_crypto_event",
            return_value=fake_artifacts,
        ) as run_crypto_event:
            response = self.client.post(
                "/api/backtests/crypto-event",
                json={
                    "source": "sqlite",
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "capital": 100000,
                    "commission_rate": 0.0004,
                    "slippage": 4,
                    "leverage": 1,
                    "strategy_id": "trend_macd",
                    "strategy_params": {},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["mode"], "crypto_event")
        self.assertEqual(payload["diagnostics"]["engine"], "event_driven")
        self.assertTrue(run_crypto_event.called)

    def test_system_overview_is_pre_live_and_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            response = self.client.get(
                "/api/system/overview",
                params={"data_root": directory},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "pre_live")
        self.assertEqual(payload["execution"]["live_state"], "frozen")
        self.assertFalse(payload["execution"]["live_submit_allowed"])
        self.assertEqual(payload["execution"]["paper_submit_default"], "disabled")
        self.assertEqual(payload["portfolio_observability"]["live_state"], "FROZEN")
        self.assertEqual(payload["portfolio_observability"]["multi_strategy"]["strategy_count"], 2)
        self.assertEqual(payload["portfolio_observability"]["multi_timeframe"]["timeframe_count"], 2)
        self.assertEqual(payload["portfolio_observability"]["pnl_attribution"]["row_count"], 1)
        self.assertIn("paper --data-root", payload["portfolio_observability"]["next_paper_command"])
        self.assertEqual(payload["minute_data_quality"]["status"], "MISSING")
        self.assertEqual(len(payload["minute_data_quality"]["datasets"]), 2)
        self.assertEqual(payload["registry"]["state"], "missing")
        self.assertIn("integrations", payload)
        self.assertIn("qlib", payload["integrations"])
        self.assertIn("portfolio", payload["integrations"])
        self.assertIn("data_coverage", payload)
        self.assertIn("next_actions", payload)

    def test_system_overview_api_surface_latest_runs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_portfolio_observability(root)
            _write_conflicting_registry(root)
            qlib_root = root / "artifacts" / "qlib_runs"
            portfolio_root = root / "artifacts" / "portfolio_runs"
            _write_qlib_run(qlib_root, "qlib_run_20260510")
            _write_qlib_run(qlib_root, "qlib_run_20260511")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260510")
            _write_portfolio_run(portfolio_root, "portfolio_run_20260511")
            response = self.client.get(
                "/api/system/overview",
                params={
                    "data_root": directory,
                    "qlib_artifacts_root": str(qlib_root),
                    "portfolio_artifacts_root": str(portfolio_root),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["integrations"]["qlib"]["latest_run"]["run_id"], "qlib_run_20260511")
        self.assertEqual(payload["integrations"]["portfolio"]["latest_run"]["portfolio_run_id"], "portfolio_run_20260511")
        self.assertTrue(payload["paper_review"]["diagnostics"]["conflict_detected"])
        self.assertEqual(payload["paper_review"]["status"], "CONFLICT")

    def test_metrics_endpoint(self) -> None:
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("quantstation_up 1", response.text)

    def test_single_backtest_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/single",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("summary", payload)

    def test_strategy_optimization_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/optimize",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "max_candidates": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["framework"][0]["status"], "selected")
        self.assertLessEqual(len(payload["candidates"]), 1)
        self.assertIsNotNone(payload["best"])

    def test_cost_stress_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/cost-stress",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "max_scenarios": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "交易成本压力测试")
        self.assertEqual(len(payload["scenarios"]), 1)
        self.assertIsNotNone(payload["baseline"])

    def test_walk_forward_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/walk-forward",
            json={
                "strategy_id": "trend_macd",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "windows": 2,
                "max_candidates": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "Walk-forward 与市场状态切片")
        self.assertGreaterEqual(len(payload["windows"]), 1)
        self.assertIn("pass_rate_pct", payload["stability"])

    def test_portfolio_optimization_endpoint(self) -> None:
        response = self.client.post(
            "/api/backtests/portfolio-optimize",
            json={
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.5},
                    {"strategy_id": "reversion_rsi", "weight": 0.25},
                    {"strategy_id": "donchian_breakout", "weight": 0.25},
                ],
                "max_single_weight": 0.6,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "组合层相关性与资金分配")
        self.assertIn("optimized_weights", payload)
        self.assertIn("risk_budget", payload)

    def test_research_promotion_gate_endpoint(self) -> None:
        response = self.client.post(
            "/api/research/promotion-gate",
            json={
                "mode": "portfolio",
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-02-15T23:00:00Z",
                "weights": [
                    {"strategy_id": "trend_macd", "weight": 0.5},
                    {"strategy_id": "reversion_rsi", "weight": 0.25},
                    {"strategy_id": "donchian_breakout", "weight": 0.25},
                ],
                "skip_deep_checks": True,
                "persist_manifest": False,
                "register_experiment": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "研究准入与实验晋级门")
        self.assertIn(payload["decision"], {"pass", "warn", "fail"})
        self.assertTrue(payload["strategy_version"].startswith("strategy_"))
        self.assertEqual(payload["experiment_record"], {})
        self.assertGreaterEqual(len(payload["gates"]), 4)

    def test_data_database_endpoint_initializes_sqlite(self) -> None:
        with TemporaryDirectory() as directory:
            response = self.client.get(
                "/api/data/database",
                params={"db_path": f"{directory}/market.sqlite"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["initialized"])
        self.assertIn("market.sqlite", payload["db_path"])

    def test_data_quality_endpoint_returns_versioned_gate(self) -> None:
        response = self.client.post(
            "/api/data/quality",
            json={
                "source": "fixture",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-10T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_priority"], "数据质量与特征版本治理")
        self.assertTrue(payload["is_usable"])
        self.assertIn("data_version", payload)

    def test_paper_review_create_accepts_portfolio_evidence_pack(self) -> None:
        class FakeReview:
            paper_review_id = "prev_001"
            status = "PENDING_HUMAN_REVIEW"
            evidence_pack_path = "/tmp/research/evidence_packs/psim_001/evidence_pack.json"
            evidence_gate_status = "READY_FOR_REVIEW"
            proposed_symbols = ["SPY", "QQQ"]
            proposed_capital = 101500.0
            created_at = "2026-05-11T00:00:00+00:00"

        with patch(
            "quant_us.research.paper_review_bridge.PaperReviewManager.create_from_portfolio_evidence",
            return_value=FakeReview(),
        ) as create_from_pack:
            response = self.client.post(
                "/api/research/paper-review/create",
                json={
                    "portfolio_evidence_pack_id": "psim_001",
                    "data_root": "/tmp/quant-data",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["paper_review_id"], "prev_001")
        self.assertEqual(payload["evidence_gate_status"], "READY_FOR_REVIEW")
        self.assertTrue(payload["evidence_pack_path"].endswith("/psim_001/evidence_pack.json"))
        create_from_pack.assert_called_once_with("psim_001")

    def test_paper_review_create_accepts_candidate_or_manifest_preparation_path(self) -> None:
        class FakeReview:
            paper_review_id = "prev_prepare_001"
            status = "PENDING_HUMAN_REVIEW"
            evidence_pack_path = "/tmp/research/evidence_packs/pending_review_sman_001/evidence_pack.json"
            evidence_gate_status = "READY_FOR_REVIEW"
            proposed_symbols = ["SPY"]
            proposed_capital = 100000.0
            source_candidate_ids = ["cand_001"]
            created_at = "2026-05-11T00:00:00+00:00"

        with patch(
            "quant_us.research.paper_review_bridge.PaperReviewManager.create_from_candidate_evidence",
            return_value=FakeReview(),
        ) as create_from_candidate:
            response = self.client.post(
                "/api/research/paper-review/create",
                json={
                    "strategy_manifest_id": "sman_001",
                    "prepared_evidence_pack_id": "pending_review_sman_001",
                    "data_root": "/tmp/quant-data",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["paper_review_id"], "prev_prepare_001")
        self.assertEqual(payload["source_candidate_ids"], ["cand_001"])
        self.assertIn("never approves or submits paper orders", payload["note"])
        create_from_candidate.assert_called_once_with(
            candidate_id="",
            strategy_manifest_id="sman_001",
            portfolio_evidence_pack_id="pending_review_sman_001",
        )

    def test_paper_review_pending_uses_requested_data_root(self) -> None:
        class FakeReview:
            paper_review_id = "prev_pending_001"
            strategy_manifest_id = "sman_001"
            portfolio_sim_id = "psim_001"
            status = "PENDING_HUMAN_REVIEW"
            proposed_symbols = ["SPY"]
            proposed_capital = 100000.0
            created_at = "2026-05-11T00:00:00+00:00"

        with patch("quant_us.research.paper_review_bridge.PaperReviewManager") as manager_cls:
            manager = manager_cls.return_value
            manager.list_pending.return_value = [FakeReview()]
            response = self.client.get(
                "/api/research/paper-review/pending",
                params={"data_root": "/tmp/quant-data"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["paper_review_id"], "prev_pending_001")
        manager_cls.assert_called_once_with(data_root="/tmp/quant-data")
        manager.list_pending.assert_called_once_with()

    def test_factor_mine_and_run_endpoint_is_research_only(self) -> None:
        class FakeMiningResult:
            strategy_configs = [
                {
                    "strategy_id": "factor_rank",
                    "timeframe": "1d",
                    "bar_size": "1d",
                    "params": {"factor_name": "momentum_20d", "top_n": 1},
                }
            ]

            def to_dict(self) -> dict:
                return {
                    "run_id": "fmine_test",
                    "selected_factors": [{"factor_id": "momentum_20d"}],
                    "strategy_configs": list(self.strategy_configs),
                }

        with (
            patch(
                "quant_us.research.automation.factor_mining.FactorMiningEngine.mine",
                return_value=FakeMiningResult(),
            ) as mine,
            patch(
                "quant_us.research.automation.pipeline.ResearchAutomationPipeline.run",
                return_value={"status": "completed", "candidate_ids": ["cand_factor"]},
            ) as run_pipeline,
            patch(
                "quant_us.research.evidence_registry.rebuild_evidence_registry",
                return_value={"counts": {"candidate_count": 1}},
            ),
        ):
            response = self.client.post(
                "/api/research/factors/mine-and-run",
                json={
                    "symbols": ["AAPL", "MSFT"],
                    "start": "2024-01-01",
                    "end": "2024-02-01",
                    "bar_sizes": ["1d"],
                    "factor_ids": ["momentum_20d"],
                    "max_runs": 1,
                    "skip_registry_rebuild": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["candidate_ids"], ["cand_factor"])
        self.assertIn("no paper/live order path", payload["note"])
        mine.assert_called_once()
        run_pipeline.assert_called_once()

    def test_qlib_pypfopt_integration_endpoints_are_research_only(self) -> None:
        from tests.integrations.helpers import write_portfolio_config, write_qlib_run_inputs

        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            score_dates = pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True)
            scores = pd.DataFrame(
                [
                    {"datetime": score_dates[0], "symbol": "AAPL", "score": 0.70, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                    {"datetime": score_dates[0], "symbol": "MSFT", "score": 0.55, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                    {"datetime": score_dates[1], "symbol": "AAPL", "score": 0.50, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                    {"datetime": score_dates[1], "symbol": "MSFT", "score": 0.82, "model_id": "lgbm_alpha158", "feature_set": "Alpha158"},
                ]
            )
            write_qlib_run_inputs(artifacts, "qlib_http", scores)
            qlib_root = artifacts / "qlib_runs"

            response = self.client.post(
                "/api/integrations/qlib/import-pred-score",
                json={"run_id": "qlib_http", "artifacts_root": str(qlib_root)},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["research_only"])
            self.assertFalse(payload["live_enabled"])
            self.assertEqual(payload["status"], "completed")

            config_path = root / "qlib.yaml"
            config_path.write_text(
                "model:\n  name: lgbm_alpha158\n  feature_set: Alpha158\n  strategy_version: qlib_lgbm_alpha158_us_daily_v1\n",
                encoding="utf-8",
            )
            response = self.client.post(
                "/api/integrations/qlib/compile-strategy-manifest",
                json={"run_id": "qlib_http", "artifacts_root": str(qlib_root), "config": str(config_path)},
            )
            self.assertEqual(response.status_code, 200)
            manifest_payload = response.json()["strategy_manifest"]
            self.assertEqual(manifest_payload["promotion_status"], "candidate")
            self.assertEqual(manifest_payload["execution_freq"], "deferred_to_system")

            portfolio_root = artifacts / "portfolio_runs" / "pf_http"
            portfolio_root.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "portfolio_run_id": "pf_http",
                        "source_score_run_id": "qlib_http",
                        "datetime": "2026-01-06T00:00:00+00:00",
                        "symbol": "AAPL",
                        "target_weight": 0.15,
                        "raw_weight": 0.20,
                        "clipped_weight": 0.15,
                        "optimizer": "max_sharpe",
                        "constraints_hash": "abc123",
                        "fallback": "equal_weight_topk",
                        "created_at": "2026-05-11T00:00:00+00:00",
                    }
                ]
            ).to_parquet(portfolio_root / "target_weights.parquet", index=False)
            (portfolio_root / "run_manifest.json").write_text(
                '{"source_score_run_id": "qlib_http", "config": {"optimizer": "max_sharpe", "strategy_id": "pypfopt_daily_only"}}',
                encoding="utf-8",
            )
            portfolio_config = write_portfolio_config(
                root / "portfolio.yaml",
                score_runs_root=qlib_root,
                portfolio_runs_root=artifacts / "portfolio_runs",
                portfolio_run_id="pf_http",
            )
            response = self.client.post(
                "/api/integrations/portfolio/import-target-weights",
                json={"portfolio_run_id": "pf_http", "config": str(portfolio_config)},
            )
            self.assertEqual(response.status_code, 200)
            target_payload = response.json()
            self.assertEqual(target_payload["order_generation"], "disabled")
            self.assertTrue(target_payload["research_only"])
            self.assertNotIn("side", target_payload["preview"][0])
            self.assertNotIn("order_type", target_payload["preview"][0])

    def test_us_event_backtest_endpoint_uses_local_data_lake(self) -> None:
        with TemporaryDirectory() as directory:
            timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
            price = 100.0
            rows = []
            while len(rows) < 80:
                if timestamp.weekday() < 5:
                    price *= 1.004
                    rows.append(
                        {
                            "timestamp": timestamp,
                            "symbol": "AAPL",
                            "open": price * 0.99,
                            "high": price * 1.01,
                            "low": price * 0.98,
                            "close": price,
                            "volume": 10_000_000,
                        }
                    )
                timestamp += timedelta(days=1)
            service = DataLakeService(DataLakeConfig(data_root=Path(directory)))
            cleaned = BarCleaner().clean(pd.DataFrame(rows), symbol="AAPL", source="unit").frame
            service.cleaned_store.write_bars(cleaned, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="AAPL")
            msft_rows = [{**row, "symbol": "MSFT", "close": row["close"] * 1.01} for row in rows]
            cleaned_msft = BarCleaner().clean(pd.DataFrame(msft_rows), symbol="MSFT", source="unit").frame
            service.cleaned_store.write_bars(cleaned_msft, vendor="yfinance", asset_class="equity", bar_size="1d", symbol="MSFT")

            response = self.client.post(
                "/api/us/backtests/event",
                json={
                    "symbol": "AAPL",
                    "symbols": ["AAPL", "MSFT"],
                    "bar_size": "1d",
                    "strategy_params": {"lookback_bars": 5, "entry_threshold": 0.01},
                    "default_strategy_weight": 0.12,
                    "cash_reserve_weight": 0.10,
                    "min_trade_notional": 50.0,
                    "min_weight_change": 0.001,
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2024-06-30T00:00:00Z",
                    "data_root": directory,
                    "auto_sync": False,
                    "corporate_actions": [
                        {"symbol": "AAPL", "action_type": "split", "ex_date": "2024-03-01", "ratio": 2.0}
                    ],
                    "earnings_events": [
                        {"symbol": "AAPL", "event_date": "2024-04-01", "source": "unit"}
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertGreater(payload["fill_count"], 0)
        self.assertEqual(payload["diagnostics"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(payload["diagnostics"]["strategy_params"]["lookback_bars"], 5)
        self.assertEqual(payload["diagnostics"]["backtest_parameters"]["cash_reserve_weight"], 0.10)
        self.assertEqual(payload["diagnostics"]["data_filters"]["corporate_action_count"], 1)
        self.assertGreater(payload["diagnostics"]["data_filters"]["earnings_blackout_removed_rows"], 0)

    def test_us_reconcile_endpoint_checks_local_ledger(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = JsonlLedgerStore(directory)
            ledger.append_fill(
                Fill(
                    order_id="order_1",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    quantity=1.0,
                    price=100.0,
                    commission=0.0,
                    filled_at=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
                )
            )
            response = self.client.post(
                "/api/us/reconcile",
                json={"ledger_dir": directory},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "clean")
        self.assertEqual(payload["break_count"], 0)


if __name__ == "__main__":
    unittest.main()
