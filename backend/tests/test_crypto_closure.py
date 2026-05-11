from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.domain.models import BacktestArtifacts
from backend.app.services.crypto_closure import CryptoClosureService
from backend.app.services.data_management import CryptoResampleResult


UTC = timezone.utc


def _quality(interval: str, *, usable: bool = True, coverage: float = 100.0) -> dict:
    return {
        "status": "completed",
        "source": "sqlite",
        "actual_source": "sqlite",
        "symbol": "BTCUSDT",
        "interval": interval,
        "row_count": 120,
        "raw_row_count": 120,
        "expected_rows": 120,
        "coverage_pct": coverage,
        "missing_bars": 0 if usable else 12,
        "duplicate_timestamps": 0,
        "cleaning_loss_rows": 0,
        "invalid_ohlc": 0,
        "non_positive_prices": 0,
        "non_positive_volume": 0,
        "large_price_jumps": 0,
        "volume_anomalies": 0,
        "max_gap_bars": 0,
        "max_price_jump_pct": 0.0,
        "quality_score": 100.0 if usable else 40.0,
        "is_usable": usable,
        "fingerprint": f"fp-{interval}",
        "data_version": f"dv-{interval}",
        "issues": [],
    }


class FakeMarketDataService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resample_crypto_klines(self, spec):
        self.calls.append(spec.target_interval)
        start = spec.start or datetime(2024, 1, 1, tzinfo=UTC)
        end = spec.end or start + timedelta(hours=1)
        return CryptoResampleResult(
            status="completed",
            db_path="data/market_data.sqlite",
            exchange=spec.exchange,
            symbol=spec.symbol,
            source_interval=spec.source_interval,
            target_interval=spec.target_interval,
            start=start,
            end=end,
            source_rows=60,
            expected_source_rows=60,
            rows_written=1,
            coverage_pct=100.0,
            quality_score=100.0,
            data_version=f"resampled-{spec.target_interval}",
            fingerprint=f"fingerprint-{spec.target_interval}",
            quality_summary={"total_issue_count": 0},
        )


class FakeResearchService:
    def __init__(self) -> None:
        self.optimize_calls: list[str] = []
        self.event_calls: list[dict] = []

    def optimize_strategy(self, request: dict):
        strategy_id = request["strategy_id"]
        self.optimize_calls.append(strategy_id)
        score = 2.0 if strategy_id == "donchian_breakout" else 0.5
        return {
            "status": "completed",
            "best": {
                "strategy_id": strategy_id,
                "parameters": {"window": 20} if strategy_id == "donchian_breakout" else {},
                "score": score,
                "train": {"sharpe_ratio": 1.0},
                "validation": {
                    "total_return_pct": 3.0,
                    "sharpe_ratio": score,
                    "max_drawdown_pct": -4.0,
                    "profit_factor": 1.2,
                    "trade_count": 12,
                },
                "overfit_gap": 0.1,
            },
            "candidates": [],
            "recommendations": [],
        }

    def run_crypto_event(self, request: dict):
        self.event_calls.append(request)
        return BacktestArtifacts(
            mode="crypto_event",
            summary={
                "total_return_pct": 3.0,
                "annual_return_pct": 10.0,
                "annual_volatility_pct": 15.0,
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_drawdown_pct": -4.0,
                "calmar_ratio": 2.0,
                "win_rate_pct": 55.0,
                "profit_factor": 1.2,
                "trade_count": 12,
            },
            chart={"candles": [], "markers": [], "equity": [], "drawdown": [], "exposure": [], "net_units": []},
            strategy_details=[],
            latest_weights=[],
            diagnostics={
                "engine": "event_driven",
                "pnl_source": "ledger_fills",
                "ledger_equity_consistent": True,
            },
        )

    def run_event_driven_cost_stress(self, request: dict):
        return {
            "status": "completed",
            "engine": "event_driven",
            "survival_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "scenarios": [],
            "recommendations": [],
        }

    def run_walk_forward(self, request: dict):
        return {
            "status": "completed",
            "stability": {
                "fold_pass_rate_pct": 100.0,
                "pass_rate_pct": 100.0,
                "ledger_consistency_pct": 100.0,
                "regime_pass_rate_pct": 100.0,
            },
            "windows": [],
            "regimes": [],
            "recommendations": [],
        }


class FakePromotionGateService:
    def evaluate(self, request: dict):
        return {
            "status": "completed",
            "decision": "fail",
            "next_stage": "blocked",
            "manifest_id": "manifest-btc",
            "gates": [{"name": "cost_stress", "status": "fail", "message": "weak", "metrics": {}, "threshold": ""}],
            "recommendations": ["Do not enter paper."],
            "backtest_summary": {},
        }


class PassingPromotionGateService:
    def evaluate(self, request: dict):
        return {
            "status": "completed",
            "decision": "pass",
            "next_stage": "paper_candidate",
            "manifest_id": "manifest-btc-pass",
            "promotion_authority": {
                "service_layer_only": True,
                "paper_runtime_approved": False,
            },
            "gates": [],
            "recommendations": ["Research-only pass; manual review still required."],
            "backtest_summary": {},
        }


class WeakRiskResearchService(FakeResearchService):
    def run_event_driven_cost_stress(self, request: dict):
        return {
            "status": "completed",
            "engine": "event_driven",
            "survival_rate_pct": 0.0,
            "ledger_consistency_pct": 100.0,
            "scenarios": [],
            "recommendations": [],
        }

    def run_walk_forward(self, request: dict):
        return {
            "status": "completed",
            "stability": {
                "fold_pass_rate_pct": 50.0,
                "pass_rate_pct": 50.0,
                "ledger_consistency_pct": 100.0,
            },
            "windows": [],
            "regimes": [],
            "recommendations": [],
        }


class MalformedOptimizationResearchService(FakeResearchService):
    def optimize_strategy(self, request: dict):
        self.optimize_calls.append(request["strategy_id"])
        return {
            "status": "failed",
            "best": None,
            "candidates": [],
            "recommendations": ["optimizer failed"],
        }


class NonLedgerEventResearchService(FakeResearchService):
    def run_crypto_event(self, request: dict):
        self.event_calls.append(request)
        artifacts = super().run_crypto_event(request)
        artifacts.diagnostics = {"engine": "vectorized", "pnl_source": "signal_returns"}
        return artifacts

    def run_event_driven_cost_stress(self, request: dict):
        return {
            "status": "completed",
            "engine": "event_driven",
            "survival_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "scenarios": [],
            "recommendations": [],
        }

    def run_walk_forward(self, request: dict):
        return {
            "status": "completed",
            "stability": {
                "fold_pass_rate_pct": 100.0,
                "pass_rate_pct": 100.0,
                "ledger_consistency_pct": 100.0,
            },
            "windows": [],
            "regimes": [],
            "recommendations": [],
        }


def test_crypto_closure_runs_data_candidate_event_risk_and_gate() -> None:
    research = FakeResearchService()
    service = CryptoClosureService(
        research_service=research,
        promotion_gate_service=FakePromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd", "donchian_breakout"],
            "max_candidates_per_strategy": 2,
            "max_scenarios": 8,
            "windows": 2,
            "min_bars_by_interval": {"1h": 1},
        }
    )

    assert result["status"] == "completed"
    assert result["data_integrity"]["status"] == "pass"
    assert result["selected_candidate"]["strategy_id"] == "donchian_breakout"
    assert research.event_calls[0]["strategy_id"] == "donchian_breakout"
    assert result["event_backtest"]["diagnostics"]["pnl_source"] == "ledger_fills"
    assert result["cost_stress"]["engine"] == "event_driven"
    assert result["candidate_screen"]["qualification"]["selected_count"] == 1
    assert result["promotion_gate"]["decision"] == "fail"
    assert any("promotion_gate" in item for item in result["blockers"])


def test_crypto_closure_blocks_before_research_when_data_integrity_fails() -> None:
    research = FakeResearchService()
    service = CryptoClosureService(
        research_service=research,
        promotion_gate_service=FakePromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"], usable=False, coverage=50.0),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd"],
            "min_bars_by_interval": {"1h": 1},
        }
    )

    assert result["status"] == "blocked"
    assert result["decision"] == "blocked"
    assert result["selected_candidate"] is None
    assert research.optimize_calls == []
    assert any("coverage" in item for item in result["blockers"])


def test_crypto_closure_outer_blockers_override_passing_promotion_gate() -> None:
    service = CryptoClosureService(
        research_service=WeakRiskResearchService(),
        promotion_gate_service=PassingPromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd"],
            "min_bars_by_interval": {"1h": 1},
        }
    )

    assert result["blockers"]
    assert result["decision"] != "pass"
    assert result["next_stage"] != "paper_candidate"


def test_crypto_closure_rejects_malformed_optimizer_results_before_event_backtest() -> None:
    research = MalformedOptimizationResearchService()
    service = CryptoClosureService(
        research_service=research,
        promotion_gate_service=PassingPromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd"],
            "min_bars_by_interval": {"1h": 1},
        }
    )

    assert result["status"] == "blocked"
    assert result["selected_candidate"] is None
    assert research.event_calls == []


def test_crypto_closure_blocks_non_ledger_event_backtest_even_when_gate_passes() -> None:
    service = CryptoClosureService(
        research_service=NonLedgerEventResearchService(),
        promotion_gate_service=PassingPromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd"],
            "min_bars_by_interval": {"1h": 1},
        }
    )

    assert result["event_backtest"]["diagnostics"]["pnl_source"] != "ledger_fills"
    assert result["decision"] != "pass"
    assert any("ledger" in blocker.lower() or "event" in blocker.lower() for blocker in result["blockers"])


def test_crypto_closure_blocks_long_sample_failures_before_research() -> None:
    research = FakeResearchService()
    service = CryptoClosureService(
        research_service=research,
        promotion_gate_service=PassingPromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd"],
            "min_bars_by_interval": {"1h": 10_000},
        }
    )

    assert result["status"] == "blocked"
    assert result["data_integrity"]["validation_summary"]["status"] == "fail"
    assert any("long_sample_min_bars" in blocker for blocker in result["blockers"])
    assert research.optimize_calls == []


def test_crypto_closure_does_not_select_candidate_when_strict_qualification_fails() -> None:
    service = CryptoClosureService(
        research_service=WeakRiskResearchService(),
        promotion_gate_service=PassingPromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
    )

    result = service.run(
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": datetime(2024, 1, 1, tzinfo=UTC),
            "end": datetime(2024, 2, 1, tzinfo=UTC),
            "target_intervals": ["1h"],
            "strategy_ids": ["trend_macd"],
            "min_bars_by_interval": {"1h": 1},
        }
    )

    assert result["selected_candidate"] is None
    assert result["candidate_screen"]["qualification"]["selected_count"] == 0
    assert any("cost survival_rate" in blocker for blocker in result["blockers"])
