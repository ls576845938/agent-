"""Performance contracts: reuse computation, never trust a changed input."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import ast
from pathlib import Path
import subprocess
import numpy as np
import os
import json

import pandas as pd
import pytest

from quant_crypto.application import donchian_offline_replay as replay
from quant_crypto.oms.okx_demo_paper_runtime import (
    OkxDemoPaperRuntimeController, OkxDemoPaperRuntimeError,
)


def _frame():
    return replay.build_trend_frame("long", end=datetime(2026, 7, 23, tzinfo=timezone.utc)).iloc[-32:]


def test_registered_donchian_does_not_compute_unused_calendar_bars(monkeypatch):
    from quant_crypto.application import btc_strategy_registry as registry
    monkeypatch.setattr(registry, "aggregate_ohlcv_calendar", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("unused_calendar_work")))
    registry.btc_strategy_registry.get(replay.STRATEGY_ID).signal_callable(_frame(), "1h")


@pytest.mark.parametrize("cooldown,failed,missing_atr", [(0, False, False), (12, False, False), (6, True, False), (12, True, True)])
def test_state_loop_array_access_preserves_all_frozen_decisions(cooldown, failed, missing_atr):
    from quant_crypto.research import long_short_trend_following_lab as lab
    source = subprocess.check_output(["git", "show", "9066207923dd29e8ef7afc997579570473959d53:quant_crypto/research/long_short_trend_following_lab.py"], text=True, encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_stateful_long_short_with_atr_trail")
    namespace = dict(vars(lab))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "frozen_state_loop", "exec"), namespace)
    rng = np.random.default_rng(41)
    index = pd.date_range("2024-01-01", periods=1200, freq="4h", tz="UTC")
    flags = [pd.Series(rng.random(len(index)) > threshold, index=index) for threshold in (.85, .95, .85, .95)]
    close = pd.Series(100 + rng.standard_normal(len(index)).cumsum(), index=index)
    atr = close.diff().abs().rolling(20).mean()
    if missing_atr:
        atr = atr.iloc[2:]
    kwargs = dict(close=close, atr=atr, atr_mult=2, cooldown_bars=cooldown,
                  use_failed_breakout_exit=failed, long_failure_line=close.shift(2), short_failure_line=close.shift(2))
    expected = namespace["_stateful_long_short_with_atr_trail"](*flags, **kwargs)
    pd.testing.assert_series_equal(lab._stateful_long_short_with_atr_trail(*flags, **kwargs), expected, check_exact=True)


def test_state_loop_does_not_repeat_timestamp_lookups(monkeypatch):
    from quant_crypto.research import long_short_trend_following_lab as lab
    close = _frame()["close"]
    flags = pd.Series(False, index=close.index)
    monkeypatch.setattr(lab, "_finite_at", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("repeated_timestamp_lookup")))
    assert lab._stateful_long_short_with_atr_trail(flags, flags, flags, flags, close=close, atr=close * 0.1, atr_mult=2).eq(0).all()


def _legacy_aggregate():
    from quant_crypto.research import simple_trend_rule_lab as lab
    source = subprocess.check_output(["git", "show", "9066207923dd29e8ef7afc997579570473959d53:quant_crypto/research/simple_trend_rule_lab.py"], text=True, encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "aggregate_ohlcv")
    namespace = dict(vars(lab))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "frozen_aggregate", "exec"), namespace)
    return namespace["aggregate_ohlcv"]


@pytest.mark.parametrize("hours", [1, 4, 24])
def test_regular_aggregation_matches_frozen_math_exactly(hours):
    from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv
    old = _legacy_aggregate()
    frame = replay.build_trend_frame("long", end=datetime(2026, 7, 23, tzinfo=timezone.utc)).iloc[-600:].copy()
    frame["volume"] = np.random.default_rng(17).lognormal(5, 4, len(frame))
    for start, count in ((0, 1), (0, 12), (1, 255), (3, 400), (5, 595)):
        sample = frame.iloc[start:start + count]
        pd.testing.assert_frame_equal(aggregate_ohlcv(sample, interval_hours=hours), old(sample, interval_hours=hours), check_exact=True)
    # Irregular/NaN inputs must preserve the old fallback, not silently resample.
    for changed in (frame.drop(frame.index[7]), frame.iloc[::-1], frame.assign(volume=np.nan)):
        pd.testing.assert_frame_equal(aggregate_ohlcv(changed, interval_hours=hours), old(changed, interval_hours=hours), check_exact=True)


def test_regular_aggregation_does_not_loop_pandas_groups(monkeypatch):
    from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv
    frame = _frame()
    expected = _legacy_aggregate()(frame, interval_hours=4)
    monkeypatch.setattr(pd.DataFrame, "groupby", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("repeated_pandas_group_work")))
    pd.testing.assert_frame_equal(aggregate_ohlcv(frame, interval_hours=4), expected, check_exact=True)


@pytest.mark.parametrize("timeframe", ["1w", "1mo"])
@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "object"])
def test_calendar_vectorization_preserves_frozen_boundaries(timeframe, zone):
    from quant_crypto.research import multi_timeframe_rule_lab as lab
    source = subprocess.check_output(["git", "show", "9066207923dd29e8ef7afc997579570473959d53:quant_crypto/research/multi_timeframe_rule_lab.py"], text=True, encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "aggregate_ohlcv_calendar")
    namespace = dict(vars(lab))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "frozen_calendar", "exec"), namespace)
    frame = replay.build_trend_frame("long", end=datetime(2024, 4, 7, tzinfo=timezone.utc)).iloc[-2200:].copy()
    if zone == "object":
        frame["open_time"] = frame["open_time"].astype(object)
    else:
        frame["open_time"] = frame["open_time"].dt.tz_convert(zone)
    pd.testing.assert_frame_equal(lab.aggregate_ohlcv_calendar(frame, timeframe=timeframe), namespace["aggregate_ohlcv_calendar"](frame, timeframe=timeframe), check_exact=True)


def _append_test_event(store, index):
    store.append(event_type="test", payload={"value": index}, state_after={"n": index},
                 idempotency_key=f"event-{index}", timestamp_utc="2025-01-01T00:00:00Z", run_id="test-run",
                 safety={"live_enabled": False})


def test_verified_recovery_prefix_avoids_old_hashes_and_is_not_caller_mutable(tmp_path, monkeypatch):
    from quant_crypto.oms import runtime_store as stores
    store = stores.BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    for i in range(8):
        _append_test_event(store, i)
    first = store.recover()
    first.events[0]["payload"]["value"] = "poison"
    first.state["n"] = "poison"
    count = []
    original = stores._digest
    def traced(value):
        count.append(value)
        return original(value)
    monkeypatch.setattr(stores, "_digest", traced)
    restored = store.recover()
    assert restored.events[0]["payload"]["value"] == 0
    assert restored.state["n"] == 7
    assert count == []
    _append_test_event(store, 8)
    count.clear()
    incremental = store.recover()
    assert incremental.last_sequence == 9
    assert len(count) == 1
    assert incremental == stores.BTCRuntimeStore(tmp_path).recover()


def test_verified_views_do_not_deserialize_unrequested_old_account_snapshots(tmp_path, monkeypatch):
    from quant_crypto.oms import runtime_store as stores
    store = stores.BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    for i in range(50):
        _append_test_event(store, i)
    store.checkpoint({"n": 49})
    store.recover()
    original = stores.pickle.loads
    calls = []
    def load(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(stores.pickle, "loads", load)
    recovered = store.recover()
    assert sum(row["event_type"] == "test" for row in recovered.events) == 50
    assert not calls
    selected = dict(recovered.events[0])
    assert json.loads(json.dumps(selected))["state_after"] == {"n": 0}
    assert len(calls) == 3  # only selected payload, state_after, safety


@pytest.mark.parametrize("mutation", ["same_size_same_mtime", "truncate", "bad_tail", "checkpoint", "valid_replacement"])
def test_verified_recovery_cache_preserves_original_corruption_checks(tmp_path, mutation):
    from quant_crypto.oms.runtime_store import BTCRuntimeStore, _canonical, _digest
    store = BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    for i in range(3):
        _append_test_event(store, i)
    store.checkpoint({"n": 2})
    assert store.recover().blockers == ()
    before = store.events_path.stat()
    raw = store.events_path.read_bytes()
    if mutation == "same_size_same_mtime":
        store.events_path.write_bytes(raw.replace(b'"value":0', b'"value":9', 1))
        os.utime(store.events_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif mutation == "truncate":
        store.events_path.write_bytes(raw[:raw.find(b'\n') + 1])
    elif mutation == "bad_tail":
        store.events_path.write_bytes(raw + b'{"unterminated":')
    elif mutation == "checkpoint":
        store.checkpoint_path.write_bytes(b'{}')
    else:
        rows = [json.loads(line) for line in raw.splitlines()]
        rows[0]["payload"]["value"] = 9
        previous = ""
        for row in rows:
            row["previous_event_hash"] = previous
            row["event_hash"] = _digest({key: value for key, value in row.items() if key != "event_hash"})
            previous = row["event_hash"]
        store.events_path.write_bytes(b'\n'.join(_canonical(row) for row in rows) + b'\n')
    actual = store.recover()
    expected = BTCRuntimeStore(tmp_path).recover()
    assert actual == expected
    assert actual.blockers


@pytest.mark.parametrize("kind", ["float64", "float32", "int64", "object"])
def test_canonical_encoding_matches_frozen_preoptimization_bytes(kind):
    source = subprocess.check_output([
        "git", "show", "9066207923dd29e8ef7afc997579570473959d53:quant_crypto/application/donchian_offline_replay.py",
    ], cwd=Path.cwd(), text=True, encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_canonical_frame")
    namespace = dict(vars(replay))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "frozen_canonical_frame", "exec"), namespace)
    frame = _frame()
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = frame[name].astype(kind)
    expected, digest = namespace["_canonical_frame"](frame)
    observed, new_digest = replay._canonical_frame(frame)
    pd.testing.assert_frame_equal(expected, observed)
    assert new_digest == digest


def test_canonical_cache_reuses_only_identical_prefix(monkeypatch):
    cache = replay._CanonicalFrameCache()
    frame = _frame()
    original = replay._decimal_text
    calls = []
    def counted(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(replay, "_decimal_text", counted)
    for count in (12, 13, 13, 20):
        normalized, digest = cache(frame.iloc[:count])
        with monkeypatch.context() as plain:
            plain.setattr(replay, "_decimal_text", original)
            expected, expected_digest = replay._canonical_frame(frame.iloc[:count])
        pd.testing.assert_frame_equal(normalized, expected)
        assert digest == expected_digest
    assert len(calls) == 20 * 5
    mutated = frame.iloc[:20].copy(deep=True)
    mutated.iloc[0, mutated.columns.get_loc("volume")] += 1
    assert cache(mutated)[1] == replay._canonical_frame(mutated)[1]
    assert cache(frame.iloc[:10])[1] == replay._canonical_frame(frame.iloc[:10])[1]


def test_canonical_cache_cannot_be_poisoned_through_returned_frame():
    cache = replay._CanonicalFrameCache()
    frame = _frame()
    normalized, digest = cache(frame)
    normalized.iloc[0, normalized.columns.get_loc("volume")] += 1
    assert cache(frame)[1] == digest
    assert cache(normalized)[1] != digest
    bad = frame.copy()
    bad.iloc[0, bad.columns.get_loc("high")] = 0
    with pytest.raises(OkxDemoPaperRuntimeError, match=":high"):
        cache(bad)
    future = pd.concat([frame, frame.iloc[-1:].set_axis(frame.index[-1:] + pd.Timedelta(hours=1))])
    future.iloc[-1, future.columns.get_loc("open_time")] += pd.Timedelta(hours=1)
    cache(future)
    assert cache(frame)[1] == digest


def test_signal_memo_is_instance_local_exact_and_clock_checked(monkeypatch):
    calls = []
    def original(self, strategy, *, client=None):
        calls.append(deepcopy(strategy))
        return {"nested": {"value": len(calls)}}
    monkeypatch.setattr(OkxDemoPaperRuntimeController, "_signal_decision", original)
    controller = object.__new__(replay._OfflineSignalMemoController)
    frame = _frame()
    from types import SimpleNamespace
    controller.config = SimpleNamespace(offline_completed_frame_provider=lambda: frame)
    clock = [frame.index[-1].to_pydatetime()]
    controller._clock = lambda: clock[0]
    strategy = replay.btc_strategy_registry.get(replay.STRATEGY_ID).identity()
    first = controller._signal_decision(strategy)
    first["nested"]["value"] = -99
    assert controller._signal_decision(strategy, client=object()) == {"nested": {"value": 1}}
    assert len(calls) == 1
    frame.iloc[0, frame.columns.get_loc("volume")] += 1
    controller._signal_decision(strategy)
    assert len(calls) == 2
    controller._signal_decision({**strategy, "params_hash": "changed"})
    assert len(calls) == 3
    clock[0] -= timedelta(hours=1)
    controller._signal_decision(strategy)
    assert len(calls) == 4  # validation delegated to original, never cached away
    clock[0] += timedelta(hours=1)
    controller._signal_decision(strategy, client=object())
    assert len(calls) == 5
