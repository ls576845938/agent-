from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.domain.models import BacktestArtifacts
from backend.app.services.crypto_closure import CryptoClosureService
from backend.app.services.data_management import CryptoResampleResult


UTC = timezone.utc


class _StubResearchService:
    def __init__(self) -> None:
        self.crypto_event_request: dict[str, object] | None = None
        self.cost_request: dict[str, object] | None = None
        self.walk_request: dict[str, object] | None = None
        self.cpcv_request: dict[str, object] | None = None

    def optimize_strategy(self, request: dict[str, object]) -> dict[str, object]:
        return {
            "status": "completed",
            "best": {
                "parameters": {"threshold": 1.0},
                "score": 2.5,
                "validation": {
                    "total_return_pct": 8.0,
                    "sharpe_ratio": 1.4,
                    "profit_factor": 1.6,
                    "max_drawdown_pct": -6.0,
                    "trade_count": 18,
                },
                "train": {"total_return_pct": 12.0},
                "overfit_gap": 0.1,
            },
            "candidates": [{"parameters": {"threshold": 1.0}}],
            "recommendations": [],
        }

    def run_crypto_event(self, request: dict[str, object]) -> BacktestArtifacts:
        self.crypto_event_request = dict(request)
        return BacktestArtifacts(
            mode="crypto_event",
            summary={"trade_count": 2, "total_return_pct": 4.0, "profit_factor": 1.5, "sharpe_ratio": 1.2, "max_drawdown_pct": -4.0},
            chart={},
            strategy_details=[],
            latest_weights=[],
            diagnostics={
                "engine": "event_driven",
                "pnl_source": "ledger_fills",
                "ledger_equity_consistent": True,
                "manifest_id": "event_manifest_id",
                "manifest_path": "/tmp/event_manifest.json",
                "ledger_artifact_path": "/tmp/event_ledger.json",
                "data_version": request["data_version"],
                "strategy_version": request["strategy_version"],
                "run_id": request["run_id"],
            },
        )

    def run_event_driven_cost_stress(self, request: dict[str, object]) -> dict[str, object]:
        self.cost_request = dict(request)
        return {
            "engine": "event_driven",
            "asset_class": "crypto",
            "data_version": request["data_version"],
            "strategy_version": request["strategy_version"],
            "run_id_prefix": request["run_id_prefix"],
            "survival_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "scenario_manifests_complete": True,
            "missing_manifest_scenarios": [],
            "baseline": {
                "execution": {"pnl_source": "ledger_fills"},
            },
            "scenarios": [],
            "recommendations": [],
        }

    def run_walk_forward(self, request: dict[str, object]) -> dict[str, object]:
        self.walk_request = dict(request)
        return {
            "status": "completed",
            "stability": {
                "fold_pass_rate_pct": 100.0,
                "ledger_consistency_pct": 100.0,
                "regime_pass_rate_pct": 100.0,
                "manifest_path": "/tmp/walk_forward_manifest.json",
            },
            "audit": {
                "aggregate_manifest_path": "/tmp/walk_forward_manifest.json",
            },
            "recommendations": [],
        }

    def run_cpcv_validation(self, request: dict[str, object]) -> dict[str, object]:
        self.cpcv_request = dict(request)
        pbo_trials = [
            {"split_id": "p1", "config_id": "a", "train_sharpe": 1.4, "test_sharpe": 1.3},
            {"split_id": "p1", "config_id": "b", "train_sharpe": 0.7, "test_sharpe": 0.5},
            {"split_id": "p2", "config_id": "a", "train_sharpe": 1.2, "test_sharpe": 1.1},
            {"split_id": "p2", "config_id": "b", "train_sharpe": 0.6, "test_sharpe": 0.4},
        ]
        return {
            "status": "completed",
            "validation_method": "cpcv",
            "cv_method": "cpcv",
            "n_splits": 3,
            "test_splits": 1,
            "combination_count": 3,
            "path_count": 3,
            "purged": True,
            "purge_bars": 1,
            "embargoed": True,
            "embargo_bars": 1,
            "lookahead_guard": "event_driven_signal_replay_no_future_features",
            "config_count": 2,
            "trial_count": len(pbo_trials),
            "folds": [
                {"split_id": "p1", "oos_sharpe": 1.3, "max_drawdown_pct": -2.0, "passed": True},
                {"split_id": "p2", "oos_sharpe": 1.1, "max_drawdown_pct": -3.0, "passed": True},
            ],
            "fold_sharpes": [1.3, 1.1],
            "fold_drawdowns": [-2.0, -3.0],
            "fold_returns": [3.0, 2.5, 2.0, 1.8],
            "pbo_trials": pbo_trials,
            "bar_count": 1000,
            "return_observation_count": 4,
        }


class _StubPromotionGateService:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def evaluate(self, request: dict[str, object]) -> dict[str, object]:
        self.request = dict(request)
        return {
            "decision": "pass",
            "next_stage": "paper_candidate",
            "recommendations": ["gate ok"],
        }


class _AuditFailResearchService(_StubResearchService):
    def run_event_driven_cost_stress(self, request: dict[str, object]) -> dict[str, object]:
        payload = super().run_event_driven_cost_stress(request)
        payload["scenario_manifests_complete"] = False
        payload["missing_manifest_scenarios"] = ["base"]
        return payload

    def run_walk_forward(self, request: dict[str, object]) -> dict[str, object]:
        self.walk_request = dict(request)
        return {
            "status": "completed",
            "stability": {
                "fold_pass_rate_pct": 100.0,
                "ledger_consistency_pct": 100.0,
                "regime_pass_rate_pct": 100.0,
            },
            "audit": {},
            "recommendations": [],
        }


class _NoCandidatePassesResearchService(_StubResearchService):
    def run_event_driven_cost_stress(self, request: dict[str, object]) -> dict[str, object]:
        payload = super().run_event_driven_cost_stress(request)
        payload["survival_rate_pct"] = 0.0
        return payload


class _WeakStatisticalValidationResearchService(_StubResearchService):
    def run_cpcv_validation(self, request: dict[str, object]) -> dict[str, object]:
        self.cpcv_request = dict(request)
        return {
            "status": "completed",
            "validation_method": "cpcv",
            "cv_method": "cpcv",
            "n_splits": 3,
            "test_splits": 1,
            "combination_count": 2,
            "path_count": 2,
            "purged": True,
            "purge_bars": request["purge_bars"],
            "embargoed": True,
            "embargo_bars": request["embargo_bars"],
            "lookahead_guard": "",
            "config_count": 2,
            "trial_count": 4,
            "folds": [
                {"split_id": "p1", "oos_sharpe": -0.2, "max_drawdown_pct": -8.0, "passed": False},
                {"split_id": "p2", "oos_sharpe": -0.3, "max_drawdown_pct": -9.0, "passed": False},
            ],
            "fold_sharpes": [-0.2, -0.3],
            "fold_drawdowns": [-8.0, -9.0],
            "fold_returns": [],
            "pbo_trials": [
                {"split_id": "p1", "config_id": "selected", "train_sharpe": 2.0, "test_sharpe": -1.0},
                {"split_id": "p1", "config_id": "alt", "train_sharpe": 0.5, "test_sharpe": 1.0},
                {"split_id": "p2", "config_id": "selected", "train_sharpe": 2.0, "test_sharpe": -1.0},
                {"split_id": "p2", "config_id": "alt", "train_sharpe": 0.5, "test_sharpe": 1.0},
            ],
            "bar_count": 1,
            "return_observation_count": 0,
        }


class _StubMarketDataService:
    def resample_crypto_klines(self, spec) -> CryptoResampleResult:
        return CryptoResampleResult(
            status="completed",
            db_path=str(spec.db_path),
            exchange=str(spec.exchange),
            symbol=str(spec.symbol),
            source_interval=str(spec.source_interval),
            target_interval=str(spec.target_interval),
            start=spec.start,
            end=spec.end,
            source_rows=200_000,
            expected_source_rows=200_000,
            rows_written=120_000,
            coverage_pct=100.0,
            quality_score=100.0,
            manifest_path=f"/tmp/{spec.target_interval}.json",
            data_version=f"qs-sqlite-BTCUSDT-{spec.target_interval}-fixture",
            fingerprint=f"fp-{spec.target_interval}",
        )


def _quality_inspector(*, interval: str, **_: object) -> dict[str, object]:
    return {
        "interval": interval,
        "row_count": 120_000,
        "coverage_pct": 100.0,
        "quality_score": 100.0,
        "is_usable": True,
        "missing_bars": 0,
        "data_version": f"qs-sqlite-BTCUSDT-{interval}-fixture",
        "fingerprint": f"quality-fp-{interval}",
    }


def _btc_closure_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "start": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        "end": datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        "data_root": "/tmp/crypto-closure",
        "max_scenarios": 1,
        "windows": 2,
        "validation_candidate_count": 1,
    }
    request.update(overrides)
    return request


def test_crypto_closure_propagates_audit_context_across_btc_pipeline() -> None:
    research_service = _StubResearchService()
    promotion_gate_service = _StubPromotionGateService()
    service = CryptoClosureService(
        research_service=research_service,
        promotion_gate_service=promotion_gate_service,
        market_data_service=_StubMarketDataService(),
        quality_inspector=_quality_inspector,
    )

    result = service.run(
        _btc_closure_request()
    )

    audit = result["candidate_screen"]["audit"]
    assert result["decision"] == "pass"
    assert result["data_integrity"]["audit"]["manifest_path"] == "/tmp/1h.json"
    assert research_service.crypto_event_request is not None
    assert research_service.cost_request is not None
    assert research_service.walk_request is not None
    assert research_service.cpcv_request is not None
    assert promotion_gate_service.request is not None
    assert research_service.crypto_event_request["data_version"] == audit["data_version"]
    assert research_service.cost_request["data_version"] == audit["data_version"]
    assert research_service.walk_request["data_version"] == audit["data_version"]
    assert promotion_gate_service.request["data_version"] == audit["data_version"]
    assert research_service.crypto_event_request["run_id"] == audit["event_run_id"]
    assert research_service.cost_request["run_id_prefix"] == audit["run_id_prefix"]
    assert research_service.walk_request["run_id_prefix"] == audit["run_id_prefix"]
    assert research_service.cpcv_request["purge_bars"] == 1
    assert research_service.cpcv_request["embargo_bars"] == 1
    assert result["event_backtest"]["audit"]["data_version"] == audit["data_version"]
    assert result["cost_stress"]["audit"]["scenario_manifests_complete"] is True
    assert result["walk_forward"]["audit"]["aggregate_manifest_path"] == "/tmp/walk_forward_manifest.json"
    assert result["promotion_gate"]["closure_audit"]["event_run_id"] == audit["event_run_id"]
    assert len(result["blockers"]) == len(set(result["blockers"]))


def test_crypto_closure_blocks_when_cost_or_walk_forward_manifests_are_missing() -> None:
    research_service = _AuditFailResearchService()
    service = CryptoClosureService(
        research_service=research_service,
        promotion_gate_service=_StubPromotionGateService(),
        market_data_service=_StubMarketDataService(),
        quality_inspector=_quality_inspector,
    )

    result = service.run(
        _btc_closure_request()
    )

    assert result["decision"] == "fail"
    assert "cost_stress missing manifests: base" in result["blockers"]
    assert "walk_forward manifest_path is missing" in result["blockers"]


def test_crypto_closure_skips_promotion_gate_when_no_candidate_passes_strict_qualification() -> None:
    research_service = _NoCandidatePassesResearchService()
    promotion_gate_service = _StubPromotionGateService()
    service = CryptoClosureService(
        research_service=research_service,
        promotion_gate_service=promotion_gate_service,
        market_data_service=_StubMarketDataService(),
        quality_inspector=_quality_inspector,
    )

    result = service.run(_btc_closure_request())

    assert result["selected_candidate"] is None
    assert result["promotion_gate"]["status"] == "skipped"
    assert result["promotion_gate"]["decision"] == "fail"
    assert result["promotion_gate"]["next_stage"] == "blocked"
    assert promotion_gate_service.request is None
    assert result["decision"] == "fail"
    assert result["next_stage"] == "blocked"
    assert "no BTC candidate passed cost stress, walk-forward, CPCV/DSR/PBO gates" in result["blockers"]


def test_crypto_closure_cannot_skip_cpcv_dsr_pbo_or_lookahead_blockers() -> None:
    research_service = _WeakStatisticalValidationResearchService()
    promotion_gate_service = _StubPromotionGateService()
    service = CryptoClosureService(
        research_service=research_service,
        promotion_gate_service=promotion_gate_service,
        market_data_service=_StubMarketDataService(),
        quality_inspector=_quality_inspector,
    )

    result = service.run(_btc_closure_request(purge_bars=3, embargo_bars=2))

    blockers = "\n".join(result["blockers"])
    assert research_service.cpcv_request is not None
    assert research_service.cpcv_request["purge_bars"] == 3
    assert research_service.cpcv_request["embargo_bars"] == 2
    assert result["selected_candidate"] is None
    assert result["promotion_gate"]["status"] == "skipped"
    assert promotion_gate_service.request is None
    assert "CPCV/DSR/PBO promotion contract blocked" in blockers
    assert "DSR below promotion threshold" in blockers
    assert "PBO above promotion threshold or missing" in blockers
    assert "multiple testing control did not pass" in blockers


def test_crypto_closure_does_not_request_live_or_broker_side_effects() -> None:
    research_service = _StubResearchService()
    promotion_gate_service = _StubPromotionGateService()
    service = CryptoClosureService(
        research_service=research_service,
        promotion_gate_service=promotion_gate_service,
        market_data_service=_StubMarketDataService(),
        quality_inspector=_quality_inspector,
    )

    result = service.run(_btc_closure_request())

    assert result["decision"] == "pass"
    assert promotion_gate_service.request is not None
    assert promotion_gate_service.request["source"] == "sqlite"
    assert promotion_gate_service.request["mode"] == "single"
    assert promotion_gate_service.request["skip_deep_checks"] is False
    assert "runtime_mode" not in promotion_gate_service.request
    assert "broker" not in promotion_gate_service.request
    service_source = Path("backend/app/services/crypto_closure.py").read_text()
    assert "quant_us.live" not in service_source
    assert "quant_us.execution" not in service_source


def test_crypto_closure_reports_progress_and_persists_research_only_evidence(tmp_path) -> None:
    research_service = _StubResearchService()
    service = CryptoClosureService(
        research_service=research_service,
        promotion_gate_service=_StubPromotionGateService(),
        market_data_service=_StubMarketDataService(),
        quality_inspector=_quality_inspector,
    )
    progress_updates: list[dict[str, object]] = []

    result = service.run(
        _btc_closure_request(data_root=str(tmp_path), persist_closure_evidence=True),
        progress_callback=lambda **kwargs: progress_updates.append(dict(kwargs)),
    )

    assert result["decision"] == "pass"
    assert [item["stage"] for item in progress_updates] == [
        "data_integrity",
        "candidate_screen",
        "candidate_validation",
        "promotion_gate",
        "completed",
    ]
    evidence_paths = result["closure_evidence_paths"]
    assert len(evidence_paths) == 1
    evidence_path = Path(evidence_paths[0])
    assert evidence_path.exists()
    payload = json.loads(evidence_path.read_text())
    assert payload["scope"] == "btc_closure_candidate_strict_validation"
    assert payload["status"] == "research_only"
    assert payload["live_enabled"] is False
    assert payload["candidate_key"].startswith("trend_macd|")
    assert payload["event_backtest"]["diagnostics"]["pnl_source"] == "ledger_fills"


def test_crypto_closure_quality_check_uses_resampled_complete_interval_end() -> None:
    requested_end = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    complete_hour_end = datetime(2026, 4, 30, 23, 0, tzinfo=UTC)
    observed_quality_ends: dict[str, datetime] = {}

    class _TrailingBucketMarketDataService(_StubMarketDataService):
        def resample_crypto_klines(self, spec) -> CryptoResampleResult:
            result = super().resample_crypto_klines(spec)
            result.end = complete_hour_end if str(spec.target_interval) == "1h" else spec.end
            return result

    def _recording_quality_inspector(*, interval: str, end: datetime, **kwargs: object) -> dict[str, object]:
        observed_quality_ends[interval] = end
        return _quality_inspector(interval=interval, end=end, **kwargs)

    service = CryptoClosureService(
        research_service=_StubResearchService(),
        promotion_gate_service=_StubPromotionGateService(),
        market_data_service=_TrailingBucketMarketDataService(),
        quality_inspector=_recording_quality_inspector,
    )

    result = service.run(
        _btc_closure_request(end=requested_end, target_intervals=["1h"])
    )

    assert result["data_integrity"]["status"] == "pass"
    assert observed_quality_ends["1m"] == requested_end
    assert observed_quality_ends["1h"] == complete_hour_end
