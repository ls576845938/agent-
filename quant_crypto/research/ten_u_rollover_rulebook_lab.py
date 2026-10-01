from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.short_interval_data_refresh import load_market_klines_frame
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
    align_derivatives_to_index,
    load_market_1h,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _round


SCHEMA_VERSION = "btc_10u_rollover_rulebook_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_10u_rollover_rulebook_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_lab_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_lab_grid.csv"
DEFAULT_EVENTS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

BASE_LEVERAGE_GRID = (10.0, 15.0, 20.0)
DAILY_FLAT_GRID = (True, False)
ADD_ENABLED_GRID = (True, False)
SIGNAL_MODE_GRID = ("monthly_only", "monthly_plus_donchian")
STOP_LOSS_PCT = 0.03
EMERGENCY_5M_ADVERSE_PCT = 0.05
ADD_TRIGGER_PCT = 0.30
ADD_ALLOCATION_MULTIPLIERS = (1.0, 0.8, 0.6)
PROFIT_EXTRACT_MULTIPLE = 3.0
PROFIT_EXTRACT_FLOATING_FRACTION = 0.50
DYNAMIC_PROTECTION_PCT = 0.08
COOLDOWN_HOURS_AFTER_LOSS = 48
LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS = 0.80
CONSECUTIVE_LOSS_PAUSE_TRIGGER = 3
GLOBAL_PAUSE_DAYS = 7
WEEKLY_PROFIT_SAFE_TRANSFER_FRACTION = 0.60
WEEKLY_PROFIT_STRATEGIC_RESERVE_FRACTION = 0.40
DAILY_FLAT_HOUR_UTC = 23
MAINTENANCE_MARGIN_RATE = 0.005
LIQUIDATION_FEE_RATE = 0.003
MARK_ADVERSE_OFFSET_BPS = 50.0
SPIKE_STRESS_PCTS = (5.0, 10.0, 12.0)
MONTHLY_TREND_LOOKBACK_MONTHS = 2


@dataclass(frozen=True)
class RulebookScenario:
    scenario_id: str
    base_leverage: float
    daily_flat_enabled: bool
    add_enabled: bool
    signal_mode: str
    emergency_kill_enabled: bool = True


@dataclass
class SleeveAccount:
    sleeve_id: int
    balance: float


@dataclass
class ActiveUnit:
    sleeve_id: int
    level: int
    entry_price: float
    last_price: float
    equity: float
    basis_equity: float
    leverage: float
    opened_at: pd.Timestamp
    peak_price: float
    protection_active: bool = False


@dataclass(frozen=True)
class RulebookResult:
    scenario: RulebookScenario
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def build_btc_10u_rollover_rulebook_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_path = output_dir / DEFAULT_GRID_CSV_PATH.name
    events_path = output_dir / DEFAULT_EVENTS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    market = _prepare_rulebook_market(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    scenarios = _scenario_grid()
    results: list[RulebookResult] = []
    event_rows: list[dict[str, Any]] = []
    if not blockers:
        for scenario in scenarios:
            result = _simulate_rulebook(
                scenario,
                market=market,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            results.append(result)
            event_rows.extend(result.events)

    grid_rows = sorted((_result_row(result) for result in results), key=_rank_key)
    watchlist_rows = [row for row in grid_rows if row["research_decision"] == "retain_10u_rulebook_research_watchlist_only"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_10u_rollover_rulebook_lab_research_only_no_paper_no_live",
        "scope": "literal_10u_rollover_rulebook_research_only",
        "code_commit": _git_commit(),
        "research_question": "Translate the 10U rollover guide into auditable BTC research rules and compare its capital discipline against existing sleeve ideas.",
        "economic_hypothesis": "Small isolated accounts plus strict trend validation, quick loss containment, staged adds and profit extraction may preserve bankroll while allowing high convexity.",
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_1h_rows": int(len(market.get("bars_1h", []))),
            "market_1h_start": _ts(market["bars_1h"].index.min()) if len(market.get("bars_1h", [])) else None,
            "market_1h_end": _ts(market["bars_1h"].index.max()) if len(market.get("bars_1h", [])) else None,
            "market_5m_rows": int(len(market.get("bars_5m", []))),
            "direction_source": "monthly_only is the literal guide filter; monthly_plus_donchian is a local enhanced comparison using shifted frozen Donchian direction",
            "funding_source": "visible derivatives rows aligned to completed 1h decision times; research approximation",
        },
        "research_design": _research_design(scenario_count=len(scenarios), candidate_count=len(grid_rows)),
        "summary": _summary(grid_rows=grid_rows, watchlist_rows=watchlist_rows, market=market),
        "top_watchlist": watchlist_rows[:20],
        "grid_rows_sample": grid_rows[:25],
        "event_sample": event_rows[:300],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, market=market, grid_rows=grid_rows),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "events_csv": _portable_path(events_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_path, grid_rows)
    _write_csv(events_path, event_rows[:1500])
    _write_text(markdown_path, render_btc_10u_rollover_rulebook_lab_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _scenario_grid() -> list[RulebookScenario]:
    scenarios: list[RulebookScenario] = []
    for leverage in BASE_LEVERAGE_GRID:
        for daily_flat in DAILY_FLAT_GRID:
            for add_enabled in ADD_ENABLED_GRID:
                for signal_mode in SIGNAL_MODE_GRID:
                    scenario_id = (
                        f"tenu_{signal_mode}_lev{_num_slug(leverage)}"
                        f"_{'dailyflat' if daily_flat else 'swing'}"
                        f"_{'add30' if add_enabled else 'noadd'}"
                        "_kill5m"
                    )
                    scenarios.append(
                        RulebookScenario(
                            scenario_id=scenario_id,
                            base_leverage=leverage,
                            daily_flat_enabled=daily_flat,
                            add_enabled=add_enabled,
                            signal_mode=signal_mode,
                            emergency_kill_enabled=True,
                        )
                    )
    return scenarios


def _prepare_rulebook_market(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    try:
        bars_1h = load_market_1h(market_db_path)
    except Exception as exc:  # pragma: no cover - surfaced in report
        return {"blockers": [f"market_1h_load_failed:{exc}"], "bars_1h": pd.DataFrame(), "bars_5m": pd.DataFrame()}
    if len(bars_1h) < 24 * 60:
        blockers.append("btc_10u_rulebook_less_than_60_days_1h_data")
    bars_5m = load_market_klines_frame(market_db_path, interval="5m")
    uses_1h_emergency_proxy = bool(bars_5m.empty)
    derivatives_1h = align_derivatives_to_index(derivatives_rows_path, pd.DatetimeIndex(bars_1h.index))
    monthly_up = _completed_monthly_trend_up(bars_1h)
    try:
        from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv

        bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
        direction_4h = _frozen_v3_direction(
            {
                "bars_4h": bars_4h,
                "derivatives_4h": align_derivatives_to_index(derivatives_rows_path, pd.DatetimeIndex(bars_4h.index)),
                "base_signal": pd.Series(0.0, index=bars_4h.index),
            },
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        direction_1h = direction_4h.reindex(bars_1h.index, method="ffill").shift(1).fillna(0.0)
    except Exception as exc:
        blockers.append(f"btc_10u_rulebook_direction_source_failed:{exc}")
        direction_1h = pd.Series(0.0, index=bars_1h.index, dtype=float)
    visible_long_signals = pd.DataFrame(index=bars_1h.index)
    visible_long_signals["monthly_only"] = (monthly_up > 0.0).astype(float)
    visible_long_signals["monthly_plus_donchian"] = ((direction_1h > 0.0) & (monthly_up > 0.0)).astype(float)
    emergency_adverse = _five_minute_adverse_by_hour(bars_1h=bars_1h, bars_5m=bars_5m)
    return {
        "blockers": blockers,
        "bars_1h": bars_1h,
        "bars_5m": bars_5m,
        "derivatives_1h": derivatives_1h,
        "monthly_trend_up": monthly_up.reindex(bars_1h.index).fillna(0.0),
        "direction_1h": direction_1h.reindex(bars_1h.index).fillna(0.0),
        "visible_long_signals": visible_long_signals.reindex(bars_1h.index).fillna(0.0),
        "visible_long_signal": visible_long_signals["monthly_only"].reindex(bars_1h.index).fillna(0.0),
        "emergency_5m_adverse": emergency_adverse.reindex(bars_1h.index).fillna(0.0),
        "uses_1h_emergency_proxy": uses_1h_emergency_proxy,
    }


def _completed_monthly_trend_up(bars_1h: pd.DataFrame) -> pd.Series:
    if bars_1h.empty:
        return pd.Series(dtype=float)
    close = bars_1h["close"].astype(float)
    try:
        monthly_close = close.resample("ME").last()
    except ValueError:
        monthly_close = close.resample("M").last()
    completed_signal = (monthly_close.shift(1) > monthly_close.shift(1 + MONTHLY_TREND_LOOKBACK_MONTHS)).astype(float)
    return completed_signal.reindex(close.index, method="ffill").fillna(0.0)


def _five_minute_adverse_by_hour(*, bars_1h: pd.DataFrame, bars_5m: pd.DataFrame) -> pd.Series:
    if bars_1h.empty:
        return pd.Series(dtype=float)
    if bars_5m.empty:
        prev_close = bars_1h["close"].shift(1)
        return (1.0 - bars_1h["low"].astype(float) / prev_close).clip(lower=0.0).fillna(0.0)
    frame = bars_5m.copy()
    previous_close = frame["close"].astype(float).shift(1)
    frame["adverse"] = (1.0 - frame["low"].astype(float) / previous_close).clip(lower=0.0).fillna(0.0)
    hourly = frame["adverse"].groupby(pd.Grouper(freq="1h")).max()
    return hourly.reindex(bars_1h.index, method="ffill").fillna(0.0)


def _simulate_rulebook(
    scenario: RulebookScenario,
    *,
    market: Mapping[str, Any],
    initial_capital: float,
    base_cost_bps: float,
) -> RulebookResult:
    bars = market["bars_1h"]
    derivatives = market["derivatives_1h"].reindex(bars.index)
    signal_frame = market.get("visible_long_signals")
    if isinstance(signal_frame, pd.DataFrame) and scenario.signal_mode in signal_frame:
        signal = signal_frame[scenario.signal_mode].reindex(bars.index).fillna(0.0)
    else:
        signal = market["visible_long_signal"].reindex(bars.index).fillna(0.0)
    emergency_adverse = market["emergency_5m_adverse"].reindex(bars.index).fillna(0.0)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=bars.index)), errors="coerce").fillna(0.0)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    sleeves = [SleeveAccount(sleeve_id=i + 1, balance=sleeve_initial) for i in range(INITIAL_SLEEVE_COUNT)]
    active: list[ActiveUnit] = []
    events: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    exposure_curve: list[float] = []
    safe_cash = 0.0
    strategic_reserve = 0.0
    current_leverage = float(scenario.base_leverage)
    cooldown_until: pd.Timestamp | None = None
    global_pause_until: pd.Timestamp | None = None
    campaign_anchor_price: float | None = None
    next_add_level = 0
    consecutive_losses = 0
    last_week_key: tuple[int, int] | None = None
    counts = {
        "entry_count": 0,
        "add_count": 0,
        "stop_loss_count": 0,
        "emergency_5m_kill_count": 0,
        "daily_flat_count": 0,
        "signal_exit_count": 0,
        "liquidation_count": 0,
        "extract_count": 0,
        "weekly_transfer_count": 0,
        "cooldown_count": 0,
        "global_pause_count": 0,
        "leverage_derisk_count": 0,
    }
    leverage_entries: list[float] = []
    min_remaining = {shock: 100.0 for shock in SPIKE_STRESS_PCTS}
    max_sleeves_lost = {shock: 0 for shock in SPIKE_STRESS_PCTS}
    funding_cost_amount = 0.0
    fee_slippage_cost_amount = 0.0
    cost_rate = float(base_cost_bps) / 10_000.0

    index = pd.DatetimeIndex(bars.index)
    for pos, ts in enumerate(index):
        price = float(close.iloc[pos])
        if pos > 0 and active:
            active, close_events, safe_delta, fee_delta, funding_delta = _mark_active_units(
                active,
                scenario=scenario,
                ts=ts,
                previous_price=float(close.iloc[pos - 1]),
                close_price=price,
                high_price=float(high.iloc[pos]),
                low_price=float(low.iloc[pos]),
                emergency_adverse=float(emergency_adverse.iloc[pos]),
                funding_rate=float(funding.iloc[pos]),
                base_cost_rate=cost_rate,
            )
            safe_cash += safe_delta
            fee_slippage_cost_amount += fee_delta
            funding_cost_amount += funding_delta
            events.extend(close_events)
            for event in close_events:
                event_type = str(event.get("event_type"))
                if event_type in counts:
                    counts[event_type] += 1
            _settle_closed_units(close_events, sleeves=sleeves)
            terminal_events = [
                event
                for event in close_events
                if str(event.get("event_type")) in {"stop_loss_count", "emergency_5m_kill_count", "liquidation_count"}
            ]
            if not active and terminal_events:
                pnl = sum(float(event.get("realized_pnl", -float(event.get("amount", 0.0)))) for event in terminal_events)
                consecutive_losses, cooldown_until, global_pause_until, current_leverage = _after_campaign_close(
                    pnl=pnl,
                    ts=ts,
                    consecutive_losses=consecutive_losses,
                    current_leverage=current_leverage,
                    counts=counts,
                )
                campaign_anchor_price = None
                next_add_level = 0
        if active:
            _extract_profit_if_needed(active, ts=ts, events=events, safe_cash_ref=[safe_cash], counts=counts)
            safe_cash = _safe_cash_from_events(events, default=safe_cash)

        if scenario.daily_flat_enabled and active and ts.hour == DAILY_FLAT_HOUR_UTC:
            pnl = _close_all_active(
                active,
                sleeves=sleeves,
                ts=ts,
                exit_price=price,
                event_type="daily_flat_count",
                events=events,
                cost_rate=cost_rate,
            )
            fee_slippage_cost_amount += sum(float(event.get("fee_slippage_cost_amount", 0.0)) for event in events[-len(active) :])
            active = []
            counts["daily_flat_count"] += 1
            consecutive_losses, cooldown_until, global_pause_until, current_leverage = _after_campaign_close(
                pnl=pnl,
                ts=ts,
                consecutive_losses=consecutive_losses,
                current_leverage=current_leverage,
                counts=counts,
            )
            campaign_anchor_price = None
            next_add_level = 0

        if active and float(signal.iloc[pos]) <= 0.0:
            pnl = _close_all_active(
                active,
                sleeves=sleeves,
                ts=ts,
                exit_price=price,
                event_type="signal_exit_count",
                events=events,
                cost_rate=cost_rate,
            )
            active = []
            counts["signal_exit_count"] += 1
            consecutive_losses, cooldown_until, global_pause_until, current_leverage = _after_campaign_close(
                pnl=pnl,
                ts=ts,
                consecutive_losses=consecutive_losses,
                current_leverage=current_leverage,
                counts=counts,
            )
            campaign_anchor_price = None
            next_add_level = 0

        if not active:
            campaign_anchor_price = None
            next_add_level = 0

        if _week_key(ts) != last_week_key:
            safe_delta, reserve_delta, transfer_events = _weekly_profit_transfer(sleeves=sleeves, sleeve_initial=sleeve_initial, ts=ts)
            if transfer_events:
                safe_cash += safe_delta
                strategic_reserve += reserve_delta
                counts["weekly_transfer_count"] += len(transfer_events)
                events.extend(transfer_events)
            last_week_key = _week_key(ts)

        can_trade = (
            float(signal.iloc[pos]) > 0.0
            and (cooldown_until is None or ts >= cooldown_until)
            and (global_pause_until is None or ts >= global_pause_until)
        )
        if can_trade:
            if not active:
                opened = _open_unit(
                    sleeves=sleeves,
                    level=0,
                    allocation_multiplier=ADD_ALLOCATION_MULTIPLIERS[0],
                    leverage=current_leverage,
                    entry_price=price,
                    ts=ts,
                    events=events,
                    cost_rate=cost_rate,
                    event_type="entry_count",
                    sleeve_initial=sleeve_initial,
                )
                if opened is not None:
                    active.append(opened)
                    counts["entry_count"] += 1
                    leverage_entries.append(current_leverage)
                    campaign_anchor_price = price
                    next_add_level = 1
            elif scenario.add_enabled and campaign_anchor_price:
                favorable = price / campaign_anchor_price - 1.0
                while next_add_level < len(ADD_ALLOCATION_MULTIPLIERS) and favorable >= ADD_TRIGGER_PCT * next_add_level:
                    opened = _open_unit(
                        sleeves=sleeves,
                        level=next_add_level,
                        allocation_multiplier=ADD_ALLOCATION_MULTIPLIERS[next_add_level],
                        leverage=current_leverage,
                        entry_price=price,
                        ts=ts,
                        events=events,
                        cost_rate=cost_rate,
                        event_type="add_count",
                        sleeve_initial=sleeve_initial,
                    )
                    if opened is None:
                        break
                    active.append(opened)
                    counts["add_count"] += 1
                    leverage_entries.append(current_leverage)
                    next_add_level += 1

        total_equity = _total_equity(sleeves=sleeves, active=active, safe_cash=safe_cash, strategic_reserve=strategic_reserve)
        gross_exposure = sum(unit.equity * unit.leverage for unit in active)
        exposure_curve.append(gross_exposure / max(1e-9, total_equity))
        equity_curve.append(total_equity)
        for shock in SPIKE_STRESS_PCTS:
            lost_equity = 0.0
            lost_count = 0
            for unit in active:
                threshold = _liquidation_threshold(unit.leverage)
                if shock / 100.0 >= threshold:
                    lost_equity += unit.equity
                    lost_count += 1
            remaining = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_remaining[shock] = min(min_remaining[shock], remaining)
            max_sleeves_lost[shock] = max(max_sleeves_lost[shock], lost_count)

    if active and len(index):
        pnl = _close_all_active(
            active,
            sleeves=sleeves,
            ts=index[-1],
            exit_price=float(close.iloc[-1]),
            event_type="end_of_sample_close",
            events=events,
            cost_rate=cost_rate,
        )
        active = []
        if pnl < 0:
            consecutive_losses += 1
    equity = pd.Series(equity_curve, index=index[: len(equity_curve)], dtype=float)
    exposure = pd.Series(exposure_curve, index=index[: len(exposure_curve)], dtype=float)
    metrics = _metrics(
        scenario=scenario,
        equity=equity,
        exposure=exposure,
        sleeves=sleeves,
        active=active,
        safe_cash=safe_cash,
        strategic_reserve=strategic_reserve,
        initial_capital=initial_capital,
        counts=counts,
        leverage_entries=leverage_entries,
        min_remaining=min_remaining,
        max_sleeves_lost=max_sleeves_lost,
        funding_cost_amount=funding_cost_amount,
        fee_slippage_cost_amount=fee_slippage_cost_amount,
    )
    return RulebookResult(scenario=scenario, metrics=metrics, events=tuple(events[:1500]))


def _mark_active_units(
    active: Sequence[ActiveUnit],
    *,
    scenario: RulebookScenario,
    ts: pd.Timestamp,
    previous_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
    emergency_adverse: float,
    funding_rate: float,
    base_cost_rate: float,
) -> tuple[list[ActiveUnit], list[dict[str, Any]], float, float, float]:
    survivors: list[ActiveUnit] = []
    events: list[dict[str, Any]] = []
    safe_delta = 0.0
    fee_delta = 0.0
    funding_delta = 0.0
    for unit in active:
        adverse = max(0.0, 1.0 - low_price / max(1e-12, previous_price))
        threshold = _liquidation_threshold(unit.leverage)
        if adverse >= threshold:
            events.append(_unit_event(unit=unit, ts=ts, event_type="liquidation_count", amount=unit.equity, note="isolated sleeve liquidation proxy"))
            continue
        stop_price = unit.entry_price * (1.0 - STOP_LOSS_PCT)
        protect_price = unit.peak_price * (1.0 - DYNAMIC_PROTECTION_PCT)
        if low_price <= stop_price:
            closed = _closed_unit_event(
                unit=unit,
                ts=ts,
                exit_price=stop_price,
                event_type="stop_loss_count",
                note="3pct reverse stop from unit entry",
                funding_rate=funding_rate,
                base_cost_rate=base_cost_rate,
            )
            events.append(closed)
            fee_delta += float(closed["fee_slippage_cost_amount"])
            funding_delta += float(closed["funding_cost_amount"])
            continue
        if scenario.emergency_kill_enabled and emergency_adverse >= EMERGENCY_5M_ADVERSE_PCT:
            kill_price = min(close_price, previous_price * (1.0 - EMERGENCY_5M_ADVERSE_PCT))
            closed = _closed_unit_event(
                unit=unit,
                ts=ts,
                exit_price=kill_price,
                event_type="emergency_5m_kill_count",
                note="5m adverse move exceeded 5pct",
                funding_rate=funding_rate,
                base_cost_rate=base_cost_rate,
            )
            events.append(closed)
            fee_delta += float(closed["fee_slippage_cost_amount"])
            funding_delta += float(closed["funding_cost_amount"])
            continue
        if unit.protection_active and low_price <= protect_price:
            closed = _closed_unit_event(
                unit=unit,
                ts=ts,
                exit_price=protect_price,
                event_type="dynamic_protection_exit",
                note="dynamic protection line after 200pct profit extraction",
                funding_rate=funding_rate,
                base_cost_rate=base_cost_rate,
            )
            events.append(closed)
            fee_delta += float(closed["fee_slippage_cost_amount"])
            funding_delta += float(closed["funding_cost_amount"])
            continue
        funding_return = -unit.leverage * float(funding_rate) * (1.0 / 8.0)
        if funding_return < 0.0:
            funding_delta += unit.equity * abs(funding_return)
        unit.equity = max(0.0, unit.equity * (1.0 + unit.leverage * (close_price / max(1e-12, unit.last_price) - 1.0) + funding_return))
        unit.last_price = close_price
        unit.peak_price = max(unit.peak_price, high_price, close_price)
        survivors.append(unit)
    return survivors, events, safe_delta, fee_delta, funding_delta


def _extract_profit_if_needed(active: Sequence[ActiveUnit], *, ts: pd.Timestamp, events: list[dict[str, Any]], safe_cash_ref: list[float], counts: dict[str, int]) -> None:
    safe_cash = float(safe_cash_ref[0])
    for unit in active:
        if unit.equity < unit.basis_equity * PROFIT_EXTRACT_MULTIPLE:
            continue
        floating_profit = max(0.0, unit.equity - unit.basis_equity)
        extracted = floating_profit * PROFIT_EXTRACT_FLOATING_FRACTION
        if extracted <= 0.0:
            continue
        unit.equity -= extracted
        unit.basis_equity = max(unit.equity, 1e-9)
        unit.protection_active = True
        safe_cash += extracted
        counts["extract_count"] += 1
        events.append(_unit_event(unit=unit, ts=ts, event_type="extract_count", amount=extracted, note="200pct profit rule extracted 50pct floating profit"))
        events.append({"event_type": "_safe_cash_marker", "safe_cash": _round(safe_cash), "timestamp": _ts(ts)})
    safe_cash_ref[0] = safe_cash


def _safe_cash_from_events(events: Sequence[Mapping[str, Any]], *, default: float) -> float:
    for event in reversed(events):
        if event.get("event_type") == "_safe_cash_marker":
            return float(event.get("safe_cash", default))
    return default


def _open_unit(
    *,
    sleeves: Sequence[SleeveAccount],
    level: int,
    allocation_multiplier: float,
    leverage: float,
    entry_price: float,
    ts: pd.Timestamp,
    events: list[dict[str, Any]],
    cost_rate: float,
    event_type: str,
    sleeve_initial: float,
) -> ActiveUnit | None:
    target = max(1e-9, sleeve_initial * float(allocation_multiplier))
    for sleeve in sleeves:
        if sleeve.balance < target * 0.25:
            continue
        allocation = min(sleeve.balance, target)
        sleeve.balance -= allocation
        opening_cost = allocation * cost_rate
        unit = ActiveUnit(
            sleeve_id=sleeve.sleeve_id,
            level=level,
            entry_price=entry_price,
            last_price=entry_price,
            equity=max(0.0, allocation - opening_cost),
            basis_equity=max(1e-9, allocation),
            leverage=leverage,
            opened_at=ts,
            peak_price=entry_price,
        )
        events.append(
            _unit_event(
                unit=unit,
                ts=ts,
                event_type=event_type,
                amount=allocation,
                note=f"allocation_multiplier={allocation_multiplier} leverage={_round(leverage)} opening_cost={_round(opening_cost)}",
            )
        )
        return unit
    return None


def _close_all_active(
    active: Sequence[ActiveUnit],
    *,
    sleeves: Sequence[SleeveAccount],
    ts: pd.Timestamp,
    exit_price: float,
    event_type: str,
    events: list[dict[str, Any]],
    cost_rate: float,
) -> float:
    pnl = 0.0
    for unit in active:
        before = unit.equity
        unit.equity = max(0.0, unit.equity * (1.0 + unit.leverage * (exit_price / max(1e-12, unit.last_price) - 1.0) - cost_rate))
        pnl += unit.equity - unit.basis_equity
        for sleeve in sleeves:
            if sleeve.sleeve_id == unit.sleeve_id:
                sleeve.balance += unit.equity
                break
        events.append(_unit_event(unit=unit, ts=ts, event_type=event_type, amount=unit.equity, note=f"closed_from={_round(before)} exit_price={_round(exit_price)}"))
    return pnl


def _closed_unit_event(
    *,
    unit: ActiveUnit,
    ts: pd.Timestamp,
    exit_price: float,
    event_type: str,
    note: str,
    funding_rate: float,
    base_cost_rate: float,
) -> dict[str, Any]:
    funding_return = -unit.leverage * float(funding_rate) * (1.0 / 8.0)
    funding_cost = unit.equity * abs(funding_return) if funding_return < 0.0 else 0.0
    fee_cost = unit.equity * base_cost_rate
    unit.equity = max(0.0, unit.equity * (1.0 + unit.leverage * (exit_price / max(1e-12, unit.last_price) - 1.0) + funding_return - base_cost_rate))
    return {
        **_unit_event(unit=unit, ts=ts, event_type=event_type, amount=unit.equity, note=note),
        "closed": True,
        "realized_pnl": _round(unit.equity - unit.basis_equity),
        "funding_cost_amount": _round(funding_cost),
        "fee_slippage_cost_amount": _round(fee_cost),
    }


def _settle_closed_units(events: Sequence[Mapping[str, Any]], *, sleeves: Sequence[SleeveAccount]) -> None:
    for event in events:
        if not bool(event.get("closed")):
            continue
        sleeve_id = int(event.get("sleeve_id", 0))
        for sleeve in sleeves:
            if sleeve.sleeve_id == sleeve_id:
                sleeve.balance += float(event.get("amount", 0.0))
                break


def _after_campaign_close(
    *,
    pnl: float,
    ts: pd.Timestamp,
    consecutive_losses: int,
    current_leverage: float,
    counts: dict[str, int],
) -> tuple[int, pd.Timestamp | None, pd.Timestamp | None, float]:
    if pnl >= 0.0:
        return 0, None, None, current_leverage
    consecutive_losses += 1
    counts["cooldown_count"] += 1
    counts["leverage_derisk_count"] += 1
    next_leverage = max(1.0, current_leverage * LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS)
    cooldown_until = ts + pd.Timedelta(hours=COOLDOWN_HOURS_AFTER_LOSS)
    pause_until = None
    if consecutive_losses >= CONSECUTIVE_LOSS_PAUSE_TRIGGER:
        counts["global_pause_count"] += 1
        pause_until = ts + pd.Timedelta(days=GLOBAL_PAUSE_DAYS)
        consecutive_losses = 0
    return consecutive_losses, cooldown_until, pause_until, next_leverage


def _weekly_profit_transfer(*, sleeves: Sequence[SleeveAccount], sleeve_initial: float, ts: pd.Timestamp) -> tuple[float, float, list[dict[str, Any]]]:
    if ts.weekday() != 0 or ts.hour != 0:
        return 0.0, 0.0, []
    safe_delta = 0.0
    reserve_delta = 0.0
    events: list[dict[str, Any]] = []
    for sleeve in sleeves:
        profit = sleeve.balance - sleeve_initial
        if profit <= 0.0:
            continue
        safe = profit * WEEKLY_PROFIT_SAFE_TRANSFER_FRACTION
        reserve = profit * WEEKLY_PROFIT_STRATEGIC_RESERVE_FRACTION
        sleeve.balance = sleeve_initial
        safe_delta += safe
        reserve_delta += reserve
        events.append(
            {
                "timestamp": _ts(ts),
                "event_type": "weekly_profit_transfer",
                "sleeve_id": sleeve.sleeve_id,
                "safe_transfer": _round(safe),
                "strategic_reserve": _round(reserve),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return safe_delta, reserve_delta, events


def _metrics(
    *,
    scenario: RulebookScenario,
    equity: pd.Series,
    exposure: pd.Series,
    sleeves: Sequence[SleeveAccount],
    active: Sequence[ActiveUnit],
    safe_cash: float,
    strategic_reserve: float,
    initial_capital: float,
    counts: Mapping[str, int],
    leverage_entries: Sequence[float],
    min_remaining: Mapping[float, float],
    max_sleeves_lost: Mapping[float, int],
    funding_cost_amount: float,
    fee_slippage_cost_amount: float,
) -> dict[str, Any]:
    final_equity = float(equity.iloc[-1]) if len(equity) else _total_equity(sleeves=sleeves, active=active, safe_cash=safe_cash, strategic_reserve=strategic_reserve)
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((equity.index.max() - equity.index.min()).total_seconds()) / 86_400.0) if len(equity) else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    metrics: dict[str, Any] = {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "safe_cash": _round(safe_cash),
        "strategic_reserve": _round(strategic_reserve),
        "sleeve_bankroll_balance": _round(sum(sleeve.balance for sleeve in sleeves)),
        "active_unit_count_at_end": len(active),
        "average_gross_exposure": _round(float(exposure.mean()) if len(exposure) else 0.0),
        "max_gross_exposure": _round(float(exposure.max()) if len(exposure) else 0.0),
        "average_entry_leverage": _round(mean(leverage_entries)) if leverage_entries else 0.0,
        "min_entry_leverage_after_derisk": _round(min(leverage_entries)) if leverage_entries else 0.0,
        "max_entry_leverage": _round(max(leverage_entries)) if leverage_entries else 0.0,
        "max_research_leverage": _round(float(scenario.base_leverage)),
        "funding_cost_amount": _round(funding_cost_amount),
        "fee_slippage_cost_amount": _round(fee_slippage_cost_amount),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }
    metrics.update({key: int(value) for key, value in counts.items()})
    for shock, remaining in min_remaining.items():
        slug = _shock_slug(shock)
        metrics[f"min_remaining_capital_pct_after_{slug}_spike"] = _round(remaining)
        metrics[f"max_sleeves_lost_single_{slug}_spike"] = int(max_sleeves_lost.get(shock, 0))
    return metrics


def _result_row(result: RulebookResult) -> dict[str, Any]:
    s = result.scenario
    row = {
        "scenario_id": s.scenario_id,
        "base_leverage": s.base_leverage,
        "daily_flat_enabled": s.daily_flat_enabled,
        "add_enabled": s.add_enabled,
        "signal_mode": s.signal_mode,
        "emergency_kill_enabled": s.emergency_kill_enabled,
        "stop_loss_pct": STOP_LOSS_PCT,
        "emergency_5m_adverse_pct": EMERGENCY_5M_ADVERSE_PCT,
        "add_trigger_pct": ADD_TRIGGER_PCT,
        "add_allocation_multipliers": json.dumps(list(ADD_ALLOCATION_MULTIPLIERS), ensure_ascii=False),
        "profit_extract_multiple": PROFIT_EXTRACT_MULTIPLE,
        "profit_extract_floating_fraction": PROFIT_EXTRACT_FLOATING_FRACTION,
        "cooldown_hours_after_loss": COOLDOWN_HOURS_AFTER_LOSS,
        "consecutive_loss_pause_trigger": CONSECUTIVE_LOSS_PAUSE_TRIGGER,
        "global_pause_days": GLOBAL_PAUSE_DAYS,
        **result.metrics,
    }
    row["research_decision"] = _research_decision(row)
    return row


def _research_decision(row: Mapping[str, Any]) -> str:
    if float(row.get("base_leverage", 0.0)) > 10.0:
        return "extreme_leverage_rulebook_research_only_not_paper_eligible"
    if float(row.get("total_return_pct", -100.0)) <= 0.0:
        return "reject_non_positive_rulebook_return"
    if int(row.get("liquidation_count", 0)) > 0:
        return "reject_liquidation_observed"
    if float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) < 40.0:
        return "reject_below_40pct_remaining_after_10pct_spike"
    return "retain_10u_rulebook_research_watchlist_only"


def _rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, str]:
    retained = 0 if row.get("research_decision") == "retain_10u_rulebook_research_watchlist_only" else 1
    return (
        retained,
        -float(row.get("annual_return_pct", -999.0)),
        -float(row.get("total_return_pct", -999.0)),
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        str(row.get("scenario_id", "")),
    )


def _research_design(*, scenario_count: int, candidate_count: int) -> dict[str, Any]:
    return {
        "source_rulebook": "user supplied 10U rollover guide translated into explicit research rules",
        "scenario_count": scenario_count,
        "candidate_count": candidate_count,
        "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
        "base_leverage_grid": list(BASE_LEVERAGE_GRID),
        "daily_flat_grid": list(DAILY_FLAT_GRID),
        "add_enabled_grid": list(ADD_ENABLED_GRID),
        "signal_mode_grid": list(SIGNAL_MODE_GRID),
        "monthly_trend_rule": f"only use completed monthly bars; prior completed month close > close {MONTHLY_TREND_LOOKBACK_MONTHS} months before",
        "direction_rule": "monthly_only uses only completed monthly trend; monthly_plus_donchian additionally requires shifted frozen Donchian high-yield v3 direction to be long",
        "stop_loss_pct": STOP_LOSS_PCT,
        "emergency_5m_adverse_pct": EMERGENCY_5M_ADVERSE_PCT,
        "add_trigger_pct": ADD_TRIGGER_PCT,
        "add_allocation_multipliers": list(ADD_ALLOCATION_MULTIPLIERS),
        "profit_extract_rule": "when sleeve equity reaches 3x basis, extract 50pct of floating profit and activate dynamic protection",
        "cooldown_after_loss_hours": COOLDOWN_HOURS_AFTER_LOSS,
        "leverage_derisk_multiplier_after_loss": LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS,
        "consecutive_loss_pause_trigger": CONSECUTIVE_LOSS_PAUSE_TRIGGER,
        "global_pause_days": GLOBAL_PAUSE_DAYS,
        "weekly_profit_transfer": {
            "safe_account_fraction": WEEKLY_PROFIT_SAFE_TRANSFER_FRACTION,
            "strategic_reserve_fraction": WEEKLY_PROFIT_STRATEGIC_RESERVE_FRACTION,
        },
        "liquidation_model": {
            "maintenance_margin_rate": MAINTENANCE_MARGIN_RATE,
            "liquidation_fee_rate": LIQUIDATION_FEE_RATE,
            "mark_adverse_offset_bps": MARK_ADVERSE_OFFSET_BPS,
            "threshold_formula": "1/leverage - maintenance_margin - liquidation_fee - mark_offset",
        },
        "same_bar_profit_allowed": False,
        "paper_live_boundary": "research-only artifact; no strategy skeleton, paper queue write, broker, OMS, order, or live unlock",
    }


def _summary(*, grid_rows: Sequence[Mapping[str, Any]], watchlist_rows: Sequence[Mapping[str, Any]], market: Mapping[str, Any]) -> dict[str, Any]:
    best = grid_rows[0] if grid_rows else {}
    monthly = market.get("monthly_trend_up", pd.Series(dtype=float))
    signal_frame = market.get("visible_long_signals", pd.DataFrame())
    monthly_only_signal = signal_frame["monthly_only"] if isinstance(signal_frame, pd.DataFrame) and "monthly_only" in signal_frame else pd.Series(dtype=float)
    donchian_signal = signal_frame["monthly_plus_donchian"] if isinstance(signal_frame, pd.DataFrame) and "monthly_plus_donchian" in signal_frame else pd.Series(dtype=float)
    extreme_rows = [row for row in grid_rows if float(row.get("base_leverage", 0.0)) > 10.0]
    return {
        "candidate_count": len(grid_rows),
        "watchlist_count": len(watchlist_rows),
        "extreme_leverage_candidate_count": len(extreme_rows),
        "best_scenario_id": best.get("scenario_id"),
        "best_research_decision": best.get("research_decision"),
        "best_annual_return_pct": best.get("annual_return_pct"),
        "best_total_return_pct": best.get("total_return_pct"),
        "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct"),
        "best_min_remaining_after_10pct_spike": best.get("min_remaining_capital_pct_after_10pct_spike"),
        "monthly_trend_up_ratio": _round(float(monthly.mean()) if len(monthly) else 0.0),
        "visible_long_signal_ratio": _round(float(monthly_only_signal.mean()) if len(monthly_only_signal) else 0.0),
        "monthly_only_signal_ratio": _round(float(monthly_only_signal.mean()) if len(monthly_only_signal) else 0.0),
        "monthly_plus_donchian_signal_ratio": _round(float(donchian_signal.mean()) if len(donchian_signal) else 0.0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _warnings(*, blockers: Sequence[str], market: Mapping[str, Any], grid_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_10u_rollover_rulebook_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_10u_rollover_rulebook_blocked_or_degraded_inputs")
    if bool(market.get("uses_1h_emergency_proxy")):
        warnings.append("5m_emergency_kill_used_1h_proxy_due_to_missing_5m_data")
    if any(float(row.get("base_leverage", 0.0)) > 10.0 for row in grid_rows):
        warnings.append("15x_20x_are_extreme_research_only_not_paper_eligible")
    if any(int(row.get("liquidation_count", 0)) > 0 for row in grid_rows):
        warnings.append("liquidations_observed_in_rulebook_grid")
    return warnings


def render_btc_10u_rollover_rulebook_lab_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 10U 滚仓规则原文实验室 v1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 候选数：`{summary.get('candidate_count')}`，普通 watchlist：`{summary.get('watchlist_count')}`",
        f"- 最佳场景：`{summary.get('best_scenario_id')}`",
        f"- 最佳年化 / 总收益 / 回撤：`{summary.get('best_annual_return_pct')}` / `{summary.get('best_total_return_pct')}` / `{summary.get('best_max_drawdown_abs_pct')}`",
        f"- -10% 插针后最低剩余本金：`{summary.get('best_min_remaining_after_10pct_spike')}`%",
        f"- 月线向上覆盖率：`{summary.get('monthly_trend_up_ratio')}`，最终可交易信号覆盖率：`{summary.get('visible_long_signal_ratio')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 已按原文落地的纪律",
        "",
        "- 初始资金分 10 份，每次从独立 sleeve 分配保证金。",
        "- 只在已完成月线趋势向上且冻结 Donchian 方向为多时允许建仓。",
        "- 固定 3% 反向离场、5m 反向 5% 急停、每日固定清仓可开关对比。",
        "- 正向 30% 后按 100/80/60 递减式加码。",
        "- 单 sleeve 达到 200% 浮盈后提取 50% 浮盈，并启用动态保护线。",
        "- 亏损后 48 小时冷却、后续杠杆降 20%、三连错暂停 7 天。",
        "- 每周将 sleeve 超额利润 60% 转安全账户，40% 转战略储备。",
        "",
        "## Top 场景",
        "",
        "| 排名 | 场景 | 杠杆 | 日清 | 加码 | 年化 | 回撤 | -10%剩余 | 强平 | 结论 |",
        "|---:|---|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(report.get("top_watchlist", [])[:10], start=1):
        lines.append(
            f"| {idx} | `{row.get('scenario_id')}` | {row.get('base_leverage')} | `{row.get('daily_flat_enabled')}` | "
            f"`{row.get('add_enabled')}` | {row.get('annual_return_pct')} | {row.get('max_drawdown_abs_pct')} | "
            f"{row.get('min_remaining_capital_pct_after_10pct_spike')} | {row.get('liquidation_count')} | `{row.get('research_decision')}` |"
        )
    if not report.get("top_watchlist"):
        lines.append("| - | 无普通 watchlist | - | - | - | - | - | - | - | 全部仍为 research-only 或未过基础线 |")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本实验只把 10U 滚仓指南翻译为可审计规则。15x/20x 只算极端研究样本，不允许进入 paper/live；5m、funding、mark/index 仍是研究近似，不能作为实盘证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "10U rulebook lab is a research translation of a high-risk rollover guide.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_10u_rollover_rulebook_lab_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
        "reason": "10U rollover rulebook output is diagnostic research only.",
        "blockers": list(report.get("blockers", [])),
    }


def _liquidation_threshold(leverage: float) -> float:
    return max(0.0, 1.0 / float(leverage) - MAINTENANCE_MARGIN_RATE - LIQUIDATION_FEE_RATE - MARK_ADVERSE_OFFSET_BPS / 10_000.0)


def _total_equity(*, sleeves: Sequence[SleeveAccount], active: Sequence[ActiveUnit], safe_cash: float, strategic_reserve: float) -> float:
    return sum(max(0.0, sleeve.balance) for sleeve in sleeves) + sum(max(0.0, unit.equity) for unit in active) + max(0.0, safe_cash) + max(0.0, strategic_reserve)


def _unit_event(*, unit: ActiveUnit, ts: pd.Timestamp, event_type: str, amount: float, note: str) -> dict[str, Any]:
    return {
        "timestamp": _ts(ts),
        "event_type": event_type,
        "sleeve_id": unit.sleeve_id,
        "level": unit.level,
        "leverage": _round(unit.leverage),
        "amount": _round(amount),
        "unit_equity_after": _round(unit.equity),
        "entry_price": _round(unit.entry_price),
        "last_price": _round(unit.last_price),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _week_key(ts: pd.Timestamp) -> tuple[int, int]:
    iso = ts.isocalendar()
    return int(iso.year), int(iso.week)


def _shock_slug(value: float) -> str:
    if math.isclose(value, round(value)):
        return f"{int(round(value))}pct"
    return str(value).replace(".", "p").replace("-", "m") + "pct"


def _num_slug(value: float) -> str:
    if math.isclose(value, round(value)):
        return str(int(round(value))) + "x"
    return str(value).replace(".", "p") + "x"


def _ts(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
