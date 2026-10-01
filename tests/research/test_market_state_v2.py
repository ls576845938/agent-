from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math

import pytest

from quant_shared.trend_environment import Bar
from quant_shared.trend_environment.state_v2 import (
    CausalStateStreamV2,
    StateDefinitionV2,
    StateSourceBinding,
    batch_estimate_v2,
)


START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def source(data_version: str = "fixture-v1") -> StateSourceBinding:
    return StateSourceBinding(
        data_version=data_version,
        manifest_git_spec="f" * 40 + ":.agent/data_manifests/fixture.json",
        manifest_sha256="1" * 64,
        aggregate_sha256="2" * 64,
        source_evidence_hash="3" * 64,
    )


def bars(count: int, asset: str = "BTC-USDT-SWAP") -> list[Bar]:
    result = []
    for index in range(count):
        event = START + timedelta(hours=index)
        close = event + timedelta(hours=1)
        price = 100 + index * 0.03 + math.sin(index / 7) * 2
        result.append(Bar(asset, event, close, close, price, True))
    return result


def definition() -> StateDefinitionV2:
    return StateDefinitionV2(
        horizons=(6, 12, 24),
        primary_horizon=12,
        volatility_history_bars=16,
        state_history_bars=12,
        minimum_history_observations=8,
        calendar="UTC_24x7_fixture",
        periods_per_year=8760,
        max_age_seconds=3600,
    )


def test_batch_incremental_and_frozen_restore_are_identical():
    rows = bars(96)
    expected = [row.close_time for row in rows]
    batch = batch_estimate_v2(rows, expected_close_times=expected,
                              definition=definition(), source=source())

    stream = CausalStateStreamV2(asset=rows[0].asset, definition=definition(), source=source())
    incremental = [stream.push(row, expected_close_time=row.close_time,
                               decision_time=row.available_time) for row in rows]
    assert [row.to_dict() for row in batch] == [row.to_dict() for row in incremental]

    first = CausalStateStreamV2(asset=rows[0].asset, definition=definition(), source=source())
    prefix = [first.push(row, expected_close_time=row.close_time,
                         decision_time=row.available_time) for row in rows[:53]]
    restored = CausalStateStreamV2.restore(json.loads(json.dumps(first.freeze())),
                                           definition=definition(), source=source())
    suffix = [restored.push(row, expected_close_time=row.close_time,
                            decision_time=row.available_time) for row in rows[53:]]
    assert [row.to_dict() for row in batch] == [row.to_dict() for row in prefix + suffix]


def test_future_append_does_not_change_past_visible_values_or_input_hash():
    rows = bars(110)
    short = batch_estimate_v2(rows[:80], expected_close_times=[x.close_time for x in rows[:80]],
                              definition=definition(), source=source())
    long = batch_estimate_v2(rows, expected_close_times=[x.close_time for x in rows],
                             definition=definition(), source=source())
    assert [x.to_dict() for x in short] == [x.to_dict() for x in long[:80]]
    assert short[-1].input_hash == long[79].input_hash
    assert short[-1].content_hash == long[79].content_hash


def test_state_fields_are_bounded_descriptions_not_probabilities():
    observed = [row for row in batch_estimate_v2(
        bars(100), expected_close_times=[x.close_time for x in bars(100)],
        definition=definition(), source=source()) if row.status == "observed"][-1]
    assert -1 <= observed.direction_score <= 1
    assert 0 <= observed.normalized_trend_strength <= 1
    assert 0 <= observed.multi_scale_agreement <= 1
    assert 0 <= observed.path_efficiency_by_horizon["12"] <= 1
    assert 0 <= observed.volatility_relative_position <= 1
    assert observed.volatility_regime in {"contracting", "stable", "expanding"}
    assert 0 <= observed.direction_persistence <= 1
    assert 0 <= observed.switching_frequency <= 1
    assert observed.optional_inputs == {
        "funding": {"status": "missing", "value": None},
        "open_interest": {"status": "missing", "value": None},
        "depth": {"status": "missing", "value": None},
    }
    rendered = json.dumps(observed.to_dict(), sort_keys=True)
    assert "probability" not in rendered


def test_missing_bar_is_unknown_and_asset_or_binding_mix_is_rejected():
    stream = CausalStateStreamV2(asset="BTC-USDT-SWAP", definition=definition(), source=source())
    missing = stream.push(None, expected_close_time=START, decision_time=START)
    assert missing.status == "unknown"
    assert "missing_expected_bar" in missing.reasons
    with pytest.raises(ValueError, match="state_asset_mismatch"):
        stream.push(bars(1, asset="ETH-USDT-SWAP")[0],
                    expected_close_time=START + timedelta(hours=1),
                    decision_time=START + timedelta(hours=1))
    frozen = stream.freeze()
    with pytest.raises(ValueError, match="state_source_binding_mismatch"):
        CausalStateStreamV2.restore(frozen, definition=definition(), source=source("fixture-v2"))


def test_duplicate_is_rejected_without_mutation_and_next_matches_baseline():
    rows = bars(80)
    baseline = CausalStateStreamV2(asset=rows[0].asset, definition=definition(), source=source())
    tested = CausalStateStreamV2(asset=rows[0].asset, definition=definition(), source=source())
    for row in rows[:70]:
        baseline.push(row, expected_close_time=row.close_time, decision_time=row.available_time)
        tested.push(row, expected_close_time=row.close_time, decision_time=row.available_time)
    before = tested.freeze()
    with pytest.raises(ValueError, match="state_expected_close_not_strictly_increasing"):
        tested.push(rows[69], expected_close_time=rows[69].close_time,
                    decision_time=rows[69].available_time)
    assert tested.freeze() == before
    expected = baseline.push(rows[70], expected_close_time=rows[70].close_time,
                             decision_time=rows[70].available_time)
    observed = tested.push(rows[70], expected_close_time=rows[70].close_time,
                           decision_time=rows[70].available_time)
    assert observed.to_dict() == expected.to_dict()


def test_missing_or_future_bar_breaks_continuity_and_forces_new_warmup_after_restore():
    rows = bars(90)
    stream = CausalStateStreamV2(asset=rows[0].asset, definition=definition(), source=source())
    for row in rows[:70]:
        stream.push(row, expected_close_time=row.close_time, decision_time=row.available_time)
    missing = stream.push(None, expected_close_time=rows[70].close_time,
                          decision_time=rows[70].available_time)
    assert missing.status == "unknown"
    assert "missing_expected_bar" in missing.reasons
    after = stream.push(rows[71], expected_close_time=rows[71].close_time,
                        decision_time=rows[71].available_time)
    assert after.status == "unknown"
    assert "warmup" in after.reasons
    restored = CausalStateStreamV2.restore(stream.freeze(), definition=definition(), source=source())
    future = Bar(rows[72].asset, rows[72].event_time, rows[72].close_time,
                 rows[72].available_time + timedelta(hours=1), rows[72].close, True)
    rejected = restored.push(future, expected_close_time=future.close_time,
                             decision_time=rows[72].available_time)
    assert rejected.status == "unknown"
    assert "future_or_unavailable_bar" in rejected.reasons
    assert restored.freeze()["bars"] == []


@pytest.mark.parametrize("mutation", ["bad_close", "bad_time", "bad_direction", "last_time"])
def test_restore_rejects_rehashed_malformed_bounded_state(mutation):
    rows = bars(40)
    stream = CausalStateStreamV2(asset=rows[0].asset, definition=definition(), source=source())
    for row in rows:
        stream.push(row, expected_close_time=row.close_time, decision_time=row.available_time)
    frozen = stream.freeze()
    if mutation == "bad_close":
        frozen["bars"][-1]["close"] = -1
    elif mutation == "bad_time":
        frozen["bars"][-1]["available_time"] = "not-a-time"
    elif mutation == "bad_direction":
        frozen["direction_history"][-1] = 7
    else:
        frozen["last_expected_close"] = rows[0].close_time.isoformat()
    unsigned = {key: value for key, value in frozen.items() if key != "snapshot_hash"}
    from quant_shared.trend_environment.model import digest
    frozen["snapshot_hash"] = digest(unsigned)
    with pytest.raises(ValueError, match="state_snapshot_"):
        CausalStateStreamV2.restore(frozen, definition=definition(), source=source())
