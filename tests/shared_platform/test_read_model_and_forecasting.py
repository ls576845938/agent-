from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_shared.evidence import FreshnessAssessment
from quant_shared.forecasting import (
    DriftForecastAdapter,
    TimeSeriesForecastRequest,
)
from quant_shared.forecasting.contracts import FORECASTING_CONTRACT_VERSION
from quant_shared.read_model import BlockerView, ReadModelSnapshot


def test_existing_shared_forecasting_contract_remains_compatible() -> None:
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    request = TimeSeriesForecastRequest(
        instrument_id="instrument-1",
        decision_time_utc=now,
        history_timestamps_utc=(now - timedelta(days=1), now),
        history_values=(100.0, 101.0),
        horizon_steps=2,
        frequency="1d",
    )
    result = DriftForecastAdapter(lookback_steps=1).forecast(request)
    assert FORECASTING_CONTRACT_VERSION == "shared_forecasting_v1"
    assert len(result.point_forecast) == 2
    assert result.paper_queue_write_allowed is False
    assert result.live_unlock_allowed is False
    assert result.order_intent_allowed is False


def test_read_model_is_projection_only_and_fails_closed() -> None:
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    blocked_freshness = FreshnessAssessment(
        status="blocked",
        blockers=("missing_source:data",),
        missing_count=1,
        stale_count=0,
        future_count=0,
        code_commit_mismatch_count=0,
        dependency_newer_count=0,
    )
    snapshot = ReadModelSnapshot(
        snapshot_id="snapshot-1",
        domain_id="domain-1",
        generated_at_utc=now,
        code_commit="a" * 40,
        data_version="data-v1",
        status="blocked",
        decision="await_data",
        freshness=blocked_freshness,
        blockers=(BlockerView("data-missing", "data_steward", "publish_manifest"),),
    )
    payload = snapshot.to_dict()
    assert payload["status"] == "blocked"
    assert payload["blockers"][0]["owner"] == "data_steward"
    assert not {"paper", "live", "order"}.intersection(payload)
    with pytest.raises(ValueError, match="passing read model"):
        ReadModelSnapshot(
            snapshot_id="snapshot-2",
            domain_id="domain-1",
            generated_at_utc=now,
            code_commit="a" * 40,
            data_version="data-v1",
            status="pass",
            decision="complete",
            freshness=blocked_freshness,
        )
