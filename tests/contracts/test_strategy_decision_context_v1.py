from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from collections import deque

import pytest

from quant_shared.strategy_runtime import (
    JsonFileStrategyStateStore,
    StrategyDecisionCapability,
    StrategyRuntimeMode,
    StrategyStateConflictError,
    StrategyStateKey,
    StrategyStateSnapshot,
    StrategyStateStoreCorruptError,
)
from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.backtest.replay import BacktestReplay
from quant_us.backtest.walk_forward import WalkForwardConfig, run_walk_forward
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, Position
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from quant_us.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyDecision,
    build_strategy_context,
)
from quant_us.strategies.decision_service import StrategyDecisionService
from quant_us.strategies.composite import CompositeStrategy
from quant_us.strategies.donchian_breakout_strategy import DonchianBreakoutStrategy
from quant_us.strategies.earnings_drift_strategy import EarningsDriftStrategy
from quant_us.strategies.etf_rotation_strategy import EtfMomentumRotationStrategy
from quant_us.strategies.factory import STRATEGY_REGISTRY, build_strategy
from quant_us.strategies.macro_trend_strategy import MacroTrendStrategy
from quant_us.strategies.mean_reversion_strategy import MeanReversionStrategy
from quant_us.strategies.momentum_strategy import MomentumStrategy
from quant_us.strategies.reversion_rsi_strategy import ReversionRsiStrategy
from quant_us.strategies.time_window_strategy import TimeWindowStrategy
from quant_us.strategies.trend_macd_strategy import TrendMacdStrategy
from quant_us.strategies.volatility_squeeze_strategy import VolatilitySqueezeStrategy


UTC = timezone.utc
EVENT_TIME = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class _CaptureStrategy(Strategy):
    version = "capture_v1"

    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id
        self.contexts: list[StrategyContext] = []

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        self.contexts.append(context)
        return []


class _StatefulCounterStrategy(Strategy):
    version = "counter_v1"

    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id
        self.seen_revisions: list[int] = []

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        return []

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        self.seen_revisions.append(context.state.revision)
        next_count = int(context.state.payload.get("count", 0)) + 1
        return StrategyDecision(
            state_transition=context.state.transition(
                {"count": next_count},
                reason="completed_market_event",
            )
        )


def _bar(*, minute_offset: int = 0) -> Bar:
    return Bar(
        timestamp_utc=EVENT_TIME + timedelta(minutes=minute_offset),
        symbol="BTC-USD",
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=10.0,
        source="immutable_fixture_v1",
        bar_size="5m",
    )


def _price_bars(prices: list[float]) -> list[Bar]:
    return [
        Bar(
            timestamp_utc=EVENT_TIME + timedelta(minutes=index),
            symbol="BTC-USD",
            open=price,
            high=price * 1.001,
            low=price * 0.999,
            close=price,
            volume=10.0,
            source="immutable_fixture_v1",
            bar_size="1m",
        )
        for index, price in enumerate(prices)
    ]


def _signal_fingerprint(signal) -> tuple:
    return (
        signal.timestamp_utc,
        signal.strategy_id,
        signal.symbol,
        signal.direction,
        round(float(signal.strength), 12),
        signal.horizon,
        signal.reason,
        dict(signal.metadata),
    )


def _context(*, mode: StrategyRuntimeMode = StrategyRuntimeMode.REPLAY) -> StrategyContext:
    position = Position(
        symbol="BTC-USD",
        quantity=2.0,
        avg_price=90.0,
        market_price=101.0,
        unrealized_pnl=22.0,
    )
    account = AccountState(
        timestamp_utc=EVENT_TIME,
        account_id="fixture-account",
        cash=1_000.0,
        equity=1_202.0,
        buying_power=500.0,
        positions={"BTC-USD": position},
    )
    return build_strategy_context(
        run_id="run-v1",
        strategy_id="fixture-strategy",
        strategy_version="strategy-v1",
        code_version="code-v1",
        data_version="data-v1",
        runtime_mode=mode,
        event_time=EVENT_TIME,
        decision_time=EVENT_TIME,
        available_time=EVENT_TIME,
        account=account,
        market_prices={"BTC-USD": 101.0},
        features={"BTC-USD": {"ofi": 0.25}},
        universe=["BTC-USD"],
        parameters={"nested": {"thresholds": [1, 2]}},
        capabilities=(StrategyDecisionCapability.SIGNAL,),
    )


def test_context_is_deeply_immutable_and_has_no_execution_capability() -> None:
    market = {"BTC-USD": 101.0}
    features = {"BTC-USD": {"ofi": 0.25}}
    parameters = {"nested": {"thresholds": [1, 2]}}
    context = build_strategy_context(
        run_id="run-v1",
        strategy_id="fixture-strategy",
        strategy_version="strategy-v1",
        code_version="code-v1",
        data_version="data-v1",
        runtime_mode=StrategyRuntimeMode.BACKTEST,
        event_time=EVENT_TIME,
        account=None,
        market_prices=market,
        features=features,
        universe=["BTC-USD"],
        parameters=parameters,
    )

    market["BTC-USD"] = 999.0
    features["BTC-USD"]["ofi"] = 0.99
    parameters["nested"]["thresholds"].append(3)

    assert context.market_prices["BTC-USD"] == 101.0
    assert context.features["BTC-USD"]["ofi"] == 0.25
    assert context.parameters["nested"]["thresholds"] == (1, 2)
    with pytest.raises(TypeError):
        context.market_prices["BTC-USD"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        context.features["BTC-USD"]["ofi"] = 1.0  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        context.universe = ("ETH-USD",)  # type: ignore[misc]

    forbidden = {
        "broker",
        "exchange",
        "order",
        "submit_order",
        "cancel_order",
        "ledger",
        "database",
    }
    assert forbidden.isdisjoint(vars(context))
    assert forbidden.isdisjoint(dir(context))


def test_account_and_position_views_are_snapshots_not_mutable_runtime_objects() -> None:
    account_position = Position(
        symbol="BTC-USD",
        quantity=2.0,
        avg_price=90.0,
        market_price=101.0,
        unrealized_pnl=22.0,
    )
    account = AccountState(
        timestamp_utc=EVENT_TIME,
        account_id="fixture-account",
        cash=1_000.0,
        equity=1_202.0,
        buying_power=500.0,
        positions={"BTC-USD": account_position},
    )
    context = build_strategy_context(
        run_id="run-v1",
        strategy_id="fixture-strategy",
        strategy_version="strategy-v1",
        code_version="code-v1",
        data_version="data-v1",
        runtime_mode=StrategyRuntimeMode.PAPER,
        event_time=EVENT_TIME,
        account=account,
    )

    account_position.quantity = 99.0
    assert context.account is not account
    assert context.account is not None
    assert context.account.positions["BTC-USD"].quantity == 2.0
    with pytest.raises(FrozenInstanceError):
        context.account.positions["BTC-USD"].quantity = 3.0  # type: ignore[misc]


def test_clock_and_identity_semantics_are_typed_across_all_modes() -> None:
    modes = (
        StrategyRuntimeMode.BACKTEST,
        StrategyRuntimeMode.PAPER,
        StrategyRuntimeMode.SHADOW,
        StrategyRuntimeMode.LIVE,
        StrategyRuntimeMode.REPLAY,
        StrategyRuntimeMode.WARMUP,
    )
    contexts = [_context(mode=mode) for mode in modes]

    assert [context.clock.mode for context in contexts] == list(modes)
    for context in contexts:
        assert context.identity.run_id == "run-v1"
        assert context.identity.strategy_id == "fixture-strategy"
        assert context.identity.strategy_version == "strategy-v1"
        assert context.identity.code_version == "code-v1"
        assert context.identity.data_version == "data-v1"
        assert context.clock.event_time == EVENT_TIME
        assert context.clock.available_time == EVENT_TIME
        assert context.clock.decision_time == EVENT_TIME
        assert context.clock.is_new_bar is True
        assert context.clock.is_final is True
        assert context.parameters["runtime_mode"] == context.clock.mode.value


def test_file_state_store_is_revisioned_atomic_and_restart_recoverable(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    key = StrategyStateKey(run_id="run-v1", strategy_id="strategy-a")
    first_store = JsonFileStrategyStateStore(path)
    empty = first_store.load(key)
    transition = empty.transition({"counter": 1}, reason="first_event")

    applied = first_store.apply(transition)
    assert applied.revision == 1
    assert applied.payload["counter"] == 1

    restarted_store = JsonFileStrategyStateStore(path)
    recovered = restarted_store.load(key)
    assert recovered == applied
    with pytest.raises(StrategyStateConflictError):
        restarted_store.apply(transition)

    other = restarted_store.load(
        StrategyStateKey(run_id="run-v1", strategy_id="strategy-b")
    )
    assert other.revision == 0
    assert dict(other.payload) == {}


def test_state_payload_rejects_values_that_change_type_after_json_restart() -> None:
    key = StrategyStateKey(run_id="run-v1", strategy_id="strategy-a")
    state = StrategyStateSnapshot.empty(key)

    with pytest.raises(TypeError, match="JSON-stable"):
        state.transition({"when": EVENT_TIME}, reason="invalid_datetime")
    with pytest.raises(ValueError, match="must be finite"):
        state.transition({"ratio": float("nan")}, reason="invalid_float")


def test_walk_forward_warmup_and_oos_share_explicit_data_identity() -> None:
    created: list[_StatefulCounterStrategy] = []

    def factory() -> _StatefulCounterStrategy:
        strategy = _StatefulCounterStrategy("strategy-a")
        created.append(strategy)
        return strategy

    results = run_walk_forward(
        [_bar(), _bar(minute_offset=5)],
        factory,
        config=WalkForwardConfig(
            train_bars=1,
            test_bars=1,
            step_bars=1,
            data_version="frozen-data-v1",
        ),
        backtest_config=BacktestConfig(
            run_id="walk-forward-v1",
            data_version="",
        ),
    )

    assert len(results) == 1
    assert created[0].seen_revisions == [0, 1]


def test_decision_service_isolates_strategies_and_recovers_state_after_restart(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    event = MarketEvent.from_bar(_bar())
    base_context = _context()
    strategy_a = _StatefulCounterStrategy("strategy-a")
    strategy_b = _StatefulCounterStrategy("strategy-b")

    first_service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    first_a = first_service.decide(strategy_a, event, base_context)
    first_b = first_service.decide(strategy_b, event, base_context)

    restarted_service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    next_event = MarketEvent.from_bar(_bar(minute_offset=5))
    second_a = restarted_service.decide(strategy_a, next_event, base_context)

    assert strategy_a.seen_revisions == [0, 1]
    assert strategy_b.seen_revisions == [0]
    assert first_a.state.revision == 1
    assert first_b.state.revision == 1
    assert second_a.state.revision == 2
    assert second_a.state.payload["count"] == 2


def test_duplicate_event_is_suppressed_after_state_store_restart(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    event = MarketEvent.from_bar(_bar())
    strategy = _StatefulCounterStrategy("strategy-a")

    first = StrategyDecisionService(JsonFileStrategyStateStore(path)).decide(
        strategy,
        event,
        _context(),
    )
    duplicate = StrategyDecisionService(JsonFileStrategyStateStore(path)).decide(
        strategy,
        event,
        _context(),
    )

    assert strategy.seen_revisions == [0]
    assert first.duplicate is False
    assert first.state.revision == 1
    assert first.state.last_decision_id
    assert duplicate.duplicate is True
    assert duplicate.signals == ()
    assert duplicate.target_positions == ()
    assert duplicate.state == first.state


def test_stateless_strategy_still_persists_duplicate_watermark(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    event = MarketEvent.from_bar(_bar())
    strategy = _CaptureStrategy("strategy-a")

    first = StrategyDecisionService(JsonFileStrategyStateStore(path)).decide(
        strategy,
        event,
        _context(),
    )
    duplicate = StrategyDecisionService(JsonFileStrategyStateStore(path)).decide(
        strategy,
        event,
        _context(),
    )

    assert len(strategy.contexts) == 1
    assert first.state.revision == 1
    assert first.state.payload == {}
    assert duplicate.duplicate is True
    assert duplicate.state == first.state


def test_identity_version_change_does_not_restore_incompatible_state(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    event = MarketEvent.from_bar(_bar())
    service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    strategy = _StatefulCounterStrategy("strategy-a")

    first = service.decide(strategy, event, _context())
    changed_identity_context = build_strategy_context(
        run_id="run-v1",
        strategy_id="fixture-strategy",
        strategy_version="strategy-v1",
        code_version="code-v2",
        data_version="data-v2",
        runtime_mode=StrategyRuntimeMode.REPLAY,
        event_time=EVENT_TIME,
    )
    changed = service.decide(strategy, event, changed_identity_context)

    assert first.state.revision == 1
    assert changed.context.state.revision == 0
    assert changed.state.revision == 1


def test_corrupt_file_state_fails_closed(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    path.write_text("{not-json", encoding="utf-8")
    store = JsonFileStrategyStateStore(path)
    with pytest.raises(StrategyStateStoreCorruptError):
        store.load(StrategyStateKey(run_id="run-v1", strategy_id="strategy-a"))


def test_paper_loop_trips_kill_switch_on_corrupt_strategy_state(tmp_path) -> None:
    state_path = tmp_path / "strategy-state-v1.json"
    state_path.write_text("{not-json", encoding="utf-8")
    loop = PaperTradingLoop(
        config=PaperTradingConfig(
            ledger_root=str(tmp_path / "ledger"),
            max_data_delay_seconds=10**12,
            max_data_staleness_seconds=10**12,
        ),
        strategy_state_store=JsonFileStrategyStateStore(state_path),
    )

    result = loop.run_day(
        bars=[_bar()],
        strategies=[_CaptureStrategy("strategy-a")],
    )

    assert loop.kill_switch.triggered is True
    assert result.orders_submitted == 0
    assert any("strategy_state_fail_closed" in error for error in result.errors)


def test_composite_namespaces_and_commits_child_state_as_one_parent_transition(tmp_path) -> None:
    path = tmp_path / "strategy-state-v1.json"
    event = MarketEvent.from_bar(_bar())
    child_a = _StatefulCounterStrategy("child-a")
    child_b = _StatefulCounterStrategy("child-b")
    composite = CompositeStrategy(
        strategies=[child_a, child_b],
        strategy_id="composite",
    )

    first_service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    first = first_service.decide(composite, event, _context())
    restarted_service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    next_event = MarketEvent.from_bar(_bar(minute_offset=5))
    second = restarted_service.decide(composite, next_event, _context())

    assert first.state.revision == 1
    assert second.state.revision == 2
    assert child_a.seen_revisions == [0, 1]
    assert child_b.seen_revisions == [0, 1]
    assert second.state.payload["children"]["child-a"]["payload"]["count"] == 2
    assert second.state.payload["children"]["child-b"]["payload"]["count"] == 2


@pytest.mark.parametrize(
    ("factory", "prices"),
    (
        (
            lambda: MomentumStrategy(
                lookback_bars=3,
                entry_threshold=0.01,
                exit_threshold=0.0,
                allow_short=True,
            ),
            [100.0, 101.0, 102.0, 105.0, 103.0, 99.0, 98.0],
        ),
        (
            lambda: MeanReversionStrategy(
                window=3,
                entry_zscore=1.0,
                exit_zscore=0.2,
                allow_short=True,
            ),
            [100.0, 100.0, 101.0, 90.0, 100.0, 110.0, 100.0],
        ),
        (
            lambda: TrendMacdStrategy(
                fast_window=2,
                slow_window=3,
                signal_window=2,
            ),
            [100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 101.0, 99.0, 102.0],
        ),
        (
            lambda: VolatilitySqueezeStrategy(
                boll_window=3,
                boll_dev=0.5,
                width_threshold=1.0,
            ),
            [100.0, 100.0, 101.0, 103.0, 99.0, 98.0, 102.0],
        ),
        (
            lambda: DonchianBreakoutStrategy(channel_window=3),
            [100.0, 101.0, 102.0, 99.0, 98.0, 103.0],
        ),
        (
            lambda: MacroTrendStrategy(short_ma=2, medium_ma=3, long_ma=4),
            [100.0, 101.0, 102.0, 103.0, 102.0, 100.0, 98.0, 101.0],
        ),
        (
            lambda: ReversionRsiStrategy(
                rsi_window=2,
                boll_window=3,
                boll_dev=0.5,
                rsi_long=40.0,
                rsi_short=60.0,
            ),
            [100.0, 101.0, 99.0, 97.0, 100.0, 103.0, 99.0],
        ),
    ),
)
def test_default_portfolio_state_contract_matches_legacy_and_survives_restart(
    tmp_path,
    factory,
    prices,
) -> None:
    bars = _price_bars(prices)
    legacy_strategy = factory()
    legacy_signals = []
    for bar in bars:
        legacy_signals.extend(
            legacy_strategy.on_bar(
                MarketEvent.from_bar(bar),
                StrategyContext(run_id="legacy-parity"),
            )
        )

    path = tmp_path / "strategy-state-v1.json"
    stateful_strategy = factory()
    service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    stateful_signals = []
    for index, bar in enumerate(bars):
        if index == len(bars) // 2:
            stateful_strategy = factory()
            service = StrategyDecisionService(JsonFileStrategyStateStore(path))
        context = build_strategy_context(
            run_id="restart-parity",
            strategy_id=stateful_strategy.strategy_id,
            strategy_version=stateful_strategy.version,
            code_version="code-v1",
            data_version="data-v1",
            runtime_mode=StrategyRuntimeMode.REPLAY,
            event_time=bar.timestamp_utc,
            market_prices={bar.symbol: float(bar.close)},
            universe=[bar.symbol],
        )
        decision = service.decide(
            stateful_strategy,
            MarketEvent.from_bar(bar),
            context,
        )
        stateful_signals.extend(decision.signals)

    assert [_signal_fingerprint(item) for item in stateful_signals] == [
        _signal_fingerprint(item) for item in legacy_signals
    ]


def _assert_restart_parity(
    *,
    tmp_path,
    factory,
    bars: list[Bar],
    configure=None,
) -> None:
    legacy_strategy = factory()
    if configure is not None:
        configure(legacy_strategy)
    legacy_signals = []
    for bar in bars:
        legacy_signals.extend(
            legacy_strategy.on_bar(
                MarketEvent.from_bar(bar),
                StrategyContext(run_id="legacy-parity"),
            )
        )

    path = tmp_path / "strategy-state-v1.json"
    stateful_strategy = factory()
    if configure is not None:
        configure(stateful_strategy)
    service = StrategyDecisionService(JsonFileStrategyStateStore(path))
    stateful_signals = []
    market_prices: dict[str, float] = {}
    for index, bar in enumerate(bars):
        if index == len(bars) // 2:
            stateful_strategy = factory()
            if configure is not None:
                configure(stateful_strategy)
            service = StrategyDecisionService(JsonFileStrategyStateStore(path))
        market_prices[bar.symbol] = float(bar.close)
        context = build_strategy_context(
            run_id="restart-parity",
            strategy_id=stateful_strategy.strategy_id,
            strategy_version=stateful_strategy.version,
            code_version="code-v1",
            data_version="data-v1",
            runtime_mode=StrategyRuntimeMode.REPLAY,
            event_time=bar.timestamp_utc,
            market_prices=market_prices,
            universe=sorted(market_prices),
        )
        decision = service.decide(
            stateful_strategy,
            MarketEvent.from_bar(bar),
            context,
        )
        stateful_signals.extend(decision.signals)

    assert [_signal_fingerprint(item) for item in stateful_signals] == [
        _signal_fingerprint(item) for item in legacy_signals
    ]


def test_time_window_state_survives_restart_with_signal_parity(tmp_path) -> None:
    timestamps = (
        datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
        datetime(2026, 8, 31, 2, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
        datetime(2026, 9, 4, 15, 0, tzinfo=UTC),
        datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
    )
    bars = [
        Bar(
            timestamp_utc=timestamp,
            symbol="BTC-USD",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10.0,
            source="immutable_fixture_v1",
            bar_size="1h",
        )
        for timestamp in timestamps
    ]
    _assert_restart_parity(
        tmp_path=tmp_path,
        factory=lambda: TimeWindowStrategy(),
        bars=bars,
    )


def test_etf_rotation_state_survives_restart_with_signal_parity(tmp_path) -> None:
    bars: list[Bar] = []
    for day_index, timestamp in enumerate(
        (
            datetime(2026, 9, 7, 20, 0, tzinfo=UTC),
            datetime(2026, 9, 14, 20, 0, tzinfo=UTC),
            datetime(2026, 9, 21, 20, 0, tzinfo=UTC),
        )
    ):
        for symbol, base_price in (("SPY", 100.0), ("QQQ", 90.0)):
            close = base_price + day_index * (2.0 if symbol == "SPY" else 1.0)
            bars.append(Bar(
                timestamp_utc=timestamp,
                symbol=symbol,
                open=close,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=10.0,
                source="immutable_fixture_v1",
                bar_size="1d",
            ))
    _assert_restart_parity(
        tmp_path=tmp_path,
        factory=lambda: EtfMomentumRotationStrategy(
            lookback_days=2,
            top_n=1,
            universe=["SPY", "QQQ"],
        ),
        bars=bars,
    )


def test_earnings_drift_state_survives_pending_entry_and_exit_restart(tmp_path) -> None:
    earnings_date = datetime(2026, 9, 2, 20, 0, tzinfo=UTC).date()
    bars = [
        Bar(
            timestamp_utc=datetime(2026, 9, day, 20, 0, tzinfo=UTC),
            symbol="AAPL",
            open=price,
            high=price + 1.0,
            low=price - 1.0,
            close=price,
            volume=10.0,
            source="immutable_fixture_v1",
            bar_size="1d",
        )
        for day, price in ((1, 100.0), (2, 102.0), (3, 103.0), (4, 104.0))
    ]

    def configure(strategy: EarningsDriftStrategy) -> None:
        strategy.set_earnings_dates("AAPL", {earnings_date})

    _assert_restart_parity(
        tmp_path=tmp_path,
        factory=lambda: EarningsDriftStrategy(
            drift_period_days=2,
            reaction_lookback_days=1,
        ),
        bars=bars,
        configure=configure,
    )


def test_registered_strategies_with_mutable_legacy_fields_override_versioned_decide() -> None:
    for strategy_id in sorted(STRATEGY_REGISTRY):
        strategy = build_strategy(strategy_id, {})
        mutable_private_fields = {
            name
            for name, value in vars(strategy).items()
            if name.startswith("_") and isinstance(value, (dict, list, set, deque))
        }
        if mutable_private_fields:
            assert type(strategy).decide is not Strategy.decide, (
                strategy_id,
                mutable_private_fields,
            )


def test_backtest_constructs_distinct_strategy_bound_contexts() -> None:
    strategy_a = _CaptureStrategy("strategy-a")
    strategy_b = _CaptureStrategy("strategy-b")
    engine = EventDrivenBacktestEngine(
        [strategy_a, strategy_b],
        config=BacktestConfig(run_id="context-v1-test"),
    )

    engine.run([_bar()])

    assert len(strategy_a.contexts) == 1
    assert len(strategy_b.contexts) == 1
    context_a = strategy_a.contexts[0]
    context_b = strategy_b.contexts[0]
    assert context_a is not context_b
    assert context_a.identity.strategy_id == "strategy-a"
    assert context_b.identity.strategy_id == "strategy-b"
    assert context_a.clock.mode is StrategyRuntimeMode.BACKTEST
    assert context_b.clock.mode is StrategyRuntimeMode.BACKTEST
    assert context_a.state.revision == 0
    assert context_b.state.revision == 0


def test_replay_adapter_binds_replay_mode_instead_of_backtest_mode() -> None:
    original_strategy = _CaptureStrategy("original")
    config = BacktestConfig(run_id="replay-mode-test")
    original = EventDrivenBacktestEngine([original_strategy], config=config).run([_bar()])
    replay = BacktestReplay.from_result(original, [_bar()], config)
    replay_strategy = _CaptureStrategy("replayed")

    replay.verify_determinism([replay_strategy], [_bar()], config)

    assert len(replay_strategy.contexts) == 1
    assert replay_strategy.contexts[0].clock.mode is StrategyRuntimeMode.REPLAY
