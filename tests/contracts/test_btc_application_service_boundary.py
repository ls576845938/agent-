from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.tests.test_crypto_closure import (
    FakeMarketDataService,
    FakePromotionGateService,
    FakeResearchService,
    _quality,
)
from quant_crypto.adapters.closure_evidence_repository import FileClosureEvidenceUnitOfWork
from quant_crypto.application.btc_demo_runtime import BtcDemoRuntimeService
from quant_crypto.application.crypto_closure import CryptoClosureService
from quant_us.backtest.crypto_event import (
    default_crypto_cost_stress_scenarios,
    qualify_crypto_candidates,
    summarize_crypto_interval_validation,
)
from quant_us.research.validation import summarize_candidate_validation


UTC = timezone.utc
FIXED_NOW = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)


class RecordingEvidenceUnitOfWork:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.staged: dict[str, dict[str, object]] = {}
        self.commit_count = 0
        self.rollback_count = 0

    def stage_candidate_evidence(self, *, run_id_prefix: str, payload: dict[str, object]) -> str:
        self.staged[run_id_prefix] = payload
        return f"memory://{run_id_prefix}_strict_evidence.json"

    def commit(self) -> None:
        self.commit_count += 1
        if self.fail_commit:
            raise OSError("injected evidence commit failure")

    def rollback(self) -> None:
        self.rollback_count += 1
        self.staged.clear()


class FakeRuntimeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def status(self) -> dict[str, object]:
        return {"status": "stopped"}

    def start(self, payload) -> dict[str, object]:
        self.calls.append(("start", dict(payload)))
        return {"status": "started"}

    def stop(self, payload) -> dict[str, object]:
        self.calls.append(("stop", dict(payload)))
        return {"status": "stopped"}

    def reconcile(self, payload) -> dict[str, object]:
        self.calls.append(("reconcile", dict(payload)))
        return {"status": "reconciled"}

    def enter_cancel_only(self, payload) -> dict[str, object]:
        self.calls.append(("cancel_only", dict(payload)))
        return {"status": "cancel_only"}


def _service(uow: RecordingEvidenceUnitOfWork) -> CryptoClosureService:
    return CryptoClosureService(
        research_service=FakeResearchService(),
        promotion_gate_service=FakePromotionGateService(),
        market_data_service=FakeMarketDataService(),
        quality_inspector=lambda **kwargs: _quality(kwargs["interval"]),
        evidence_uow_factory=lambda _: uow,
        cost_stress_scenarios=default_crypto_cost_stress_scenarios,
        candidate_qualifier=qualify_crypto_candidates,
        interval_validation_summarizer=summarize_crypto_interval_validation,
        candidate_validation_summarizer=summarize_candidate_validation,
        clock=lambda: FIXED_NOW,
    )


def _request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "start": datetime(2024, 1, 1, tzinfo=UTC),
        "end": datetime(2024, 2, 1, tzinfo=UTC),
        "target_intervals": ["1h"],
        "strategy_ids": ["donchian_breakout"],
        "min_bars_by_interval": {"1h": 1},
        "persist_closure_evidence": True,
    }
    request.update(overrides)
    return request


def test_application_service_completes_with_fake_uow() -> None:
    uow = RecordingEvidenceUnitOfWork()

    result = _service(uow).run(_request())

    assert result["status"] == "completed"
    assert result["closure_evidence_paths"][0].startswith("memory://")
    assert uow.commit_count == 1
    assert uow.rollback_count == 0
    assert len(uow.staged) == 1
    assert next(iter(uow.staged.values()))["live_enabled"] is False


def test_application_service_rolls_back_when_commit_fails() -> None:
    uow = RecordingEvidenceUnitOfWork(fail_commit=True)

    with pytest.raises(OSError, match="injected evidence commit failure"):
        _service(uow).run(_request())

    assert uow.commit_count == 1
    assert uow.rollback_count == 1
    assert uow.staged == {}


def test_file_uow_duplicate_stage_is_idempotent(tmp_path: Path) -> None:
    first = FileClosureEvidenceUnitOfWork(str(tmp_path))
    first_path = first.stage_candidate_evidence(run_id_prefix="repeatable", payload={"value": 1})
    first.commit()
    original = Path(first_path).read_bytes()

    repeated = FileClosureEvidenceUnitOfWork(str(tmp_path))
    repeated_path = repeated.stage_candidate_evidence(run_id_prefix="repeatable", payload={"value": 2})
    repeated.commit()

    assert repeated_path == first_path
    assert Path(first_path).read_bytes() == original


def test_file_uow_removes_all_installed_files_after_partial_commit_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_crypto.adapters import closure_evidence_repository as repository_module

    uow = FileClosureEvidenceUnitOfWork(str(tmp_path))
    first_path = Path(uow.stage_candidate_evidence(run_id_prefix="first", payload={"value": 1}))
    second_path = Path(uow.stage_candidate_evidence(run_id_prefix="second", payload={"value": 2}))
    real_replace = repository_module.os.replace
    replacement_count = 0

    def failing_replace(source: str | Path, target: str | Path) -> None:
        nonlocal replacement_count
        replacement_count += 1
        if replacement_count == 2:
            raise OSError("injected second replace failure")
        real_replace(source, target)

    monkeypatch.setattr(repository_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="injected second replace failure"):
        uow.commit()

    assert first_path.exists() is False
    assert second_path.exists() is False
    assert list(tmp_path.rglob("*.tmp")) == []


def test_runtime_application_service_uses_only_injected_controller_and_read_models() -> None:
    controller = FakeRuntimeController()
    chart_calls: list[int] = []
    service = BtcDemoRuntimeService(
        controller=controller,
        native_demo_data_inspector=lambda: {
            "eligible": False,
            "blockers": ["fixture_not_eligible"],
        },
        readonly_chart_loader=lambda limit: chart_calls.append(limit) or {"candles": []},
        instrument_id="BTC-USDT-SWAP",
        authorization_ticket="fixture-ticket",
        confirmation_text="fixture-confirmation",
    )

    catalog = service.catalog()
    start = service.start({"strategy_id": "fixture"})
    chart = service.readonly_klines(limit=25)

    assert catalog["instrument_id"] == "BTC-USDT-SWAP"
    assert catalog["safety"]["live_order_allowed"] is False
    assert start == {"status": "started"}
    assert controller.calls == [("start", {"strategy_id": "fixture"})]
    assert chart == {"candles": []}
    assert chart_calls == [25]
