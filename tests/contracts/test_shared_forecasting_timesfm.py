from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_shared.forecasting.contracts import (
    ForecastQuantile,
    ForecastUsage,
    ModelUnavailableError,
    TimeSeriesForecastRequest,
    TimeSeriesForecastResult,
)
from quant_shared.forecasting import timesfm_adapter
from scripts.research.build_timesfm_shared_infra_readiness_report import (
    build_timesfm_shared_infra_readiness_report,
)


def _request() -> TimeSeriesForecastRequest:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return TimeSeriesForecastRequest(
        asset_namespace="btc",
        instrument_id="BTCUSDT",
        series_name="close",
        frequency="1h",
        decision_time_utc=base + timedelta(hours=3),
        history_timestamps_utc=[base, base + timedelta(hours=1), base + timedelta(hours=2)],
        history_values=[100.0, 101.0, 102.0],
        horizon_steps=2,
        allowed_usage=ForecastUsage.RESEARCH_ONLY,
    )


def test_forecast_request_rejects_future_visible_history() -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="after decision_time"):
        TimeSeriesForecastRequest(
            asset_namespace="us_equity",
            instrument_id="SPY",
            series_name="close",
            frequency="1d",
            decision_time_utc=base,
            history_timestamps_utc=[base - timedelta(days=1), base + timedelta(days=1)],
            history_values=[500.0, 501.0],
            horizon_steps=1,
        )


def test_forecast_request_rejects_paper_live_usage() -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="paper/live/OMS"):
        TimeSeriesForecastRequest(
            asset_namespace="btc",
            instrument_id="BTCUSDT",
            series_name="close",
            frequency="1h",
            decision_time_utc=base + timedelta(hours=1),
            history_timestamps_utc=[base, base + timedelta(hours=1)],
            history_values=[100.0, 101.0],
            horizon_steps=1,
            allowed_usage="paper_candidate",
        )


def test_forecast_result_is_research_or_risk_only() -> None:
    request = _request()
    result = TimeSeriesForecastResult(
        request=request,
        model_id="unit_model",
        model_version="v0",
        generated_at_utc=request.decision_time_utc,
        point_forecast=[103.0, 104.0],
        quantiles=[ForecastQuantile(step=1, quantile=0.5, value=103.0)],
    )
    audit = result.to_audit_dict()

    assert audit["allowed_usage"] == "research_only"
    assert audit["safety_flags"] == {
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "order_intent_allowed": False,
    }


def test_forecast_result_rejects_trading_side_effect_flags() -> None:
    request = _request()
    with pytest.raises(ValueError, match="paper/live/order"):
        TimeSeriesForecastResult(
            request=request,
            model_id="unit_model",
            model_version="v0",
            generated_at_utc=request.decision_time_utc,
            point_forecast=[103.0, 104.0],
            paper_queue_write_allowed=True,
        )


def test_timesfm_adapter_missing_dependency_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_find_spec = timesfm_adapter.importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "timesfm":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(timesfm_adapter.importlib.util, "find_spec", fake_find_spec)

    assert not timesfm_adapter.is_timesfm_available()
    with pytest.raises(ModelUnavailableError, match="not installed"):
        timesfm_adapter.TimesFMForecastAdapter()


def test_timesfm_readiness_report_is_shared_and_locked(tmp_path) -> None:
    report = build_timesfm_shared_infra_readiness_report(
        output_dir=tmp_path,
        timesfm_available=False,
        generated_at_utc=datetime(2026, 6, 28, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "timesfm_shared_infra_readiness_v1"
    assert report["status"] == "DESIGN_READY_OPTIONAL_DEPENDENCY_MISSING"
    assert report["module_boundary"]["shared_package"] == "quant_shared.forecasting"
    assert report["module_boundary"]["asset_specific_consumers"] == ["quant_crypto", "quant_us"]
    assert report["safety_flags"]["paper_queue_write_allowed"] is False
    assert report["safety_flags"]["live_unlock_allowed"] is False
    assert report["safety_flags"]["broker_access_allowed"] is False
    assert (tmp_path / "timesfm_shared_infra_readiness_report.json").exists()
    assert (tmp_path / "timesfm_shared_infra_readiness_report.md").exists()
