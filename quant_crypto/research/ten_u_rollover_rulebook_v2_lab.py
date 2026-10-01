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

from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT
from quant_crypto.research.long_short_trend_following_lab import evaluate_long_short_trend_rule, long_short_trend_following_specs
from quant_crypto.research.multi_timeframe_rule_lab import aggregate_ohlcv_calendar
from quant_crypto.research.short_interval_data_refresh import load_market_klines_frame
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import BEST_BASE_VARIANT_ID, _git_commit, _portable_path, _round
from quant_crypto.research.ten_u_rollover_rulebook_lab import (
    ADD_ALLOCATION_MULTIPLIERS,
    CONSECUTIVE_LOSS_PAUSE_TRIGGER,
    COOLDOWN_HOURS_AFTER_LOSS,
    DYNAMIC_PROTECTION_PCT,
    EMERGENCY_5M_ADVERSE_PCT,
    GLOBAL_PAUSE_DAYS,
    LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS,
    LIQUIDATION_FEE_RATE,
    MAINTENANCE_MARGIN_RATE,
    MARK_ADVERSE_OFFSET_BPS,
    PROFIT_EXTRACT_FLOATING_FRACTION,
    PROFIT_EXTRACT_MULTIPLE,
    SPIKE_STRESS_PCTS,
    STOP_LOSS_PCT,
    WEEKLY_PROFIT_SAFE_TRANSFER_FRACTION,
    WEEKLY_PROFIT_STRATEGIC_RESERVE_FRACTION,
    SleeveAccount,
)


SCHEMA_VERSION = "btc_10u_rollover_rulebook_v2_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_10u_rollover_rulebook_v2_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_v2_lab_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_v2_lab_grid.csv"
DEFAULT_EVENTS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_v2_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_10u_rollover_rulebook_v2_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

BASE_LEVERAGE_GRID = (10.0, 15.0, 20.0)
ADD_TRIGGER_MODES = ("pct_8", "pct_12", "pct_16", "atr_1")
EXIT_MODES = ("no_daily_flat", "trend_failure", "max_hold_24h")
MAX_HOLD_HOURS = 24
MONTHLY_RISK_OFF_DRAWDOWN_PCT = 0.20
ATR_WINDOW = 24


@dataclass(frozen=True)
class RulebookV2Scenario:
    scenario_id: str
    base_leverage: float
    add_trigger_mode: str
    exit_mode: str


@dataclass
class ActiveUnitV2:
    sleeve_id: int
    level: int
    side: float
    entry_price: float
    last_price: float
    equity: float
    basis_equity: float
    leverage: float
    opened_at: pd.Timestamp
    best_price: float
    protection_active: bool = False


@dataclass(frozen=True)
class RulebookV2Result:
    scenario: RulebookV2Scenario
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def build_btc_10u_rollover_rulebook_v2_lab(
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

    market = _prepare_v2_market(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    scenarios = _scenario_grid()
    results: list[RulebookV2Result] = []
    event_rows: list[dict[str, Any]] = []
    if not blockers:
        for scenario in scenarios:
            result = _simulate_v2(
                scenario,
                market=market,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            results.append(result)
            event_rows.extend(result.events)

    grid_rows = sorted((_result_row(result) for result in results), key=_rank_key)
    watchlist_rows = [row for row in grid_rows if row["research_decision"] == "retain_10u_v2_research_watchlist_only"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_10u_rollover_rulebook_v2_lab_research_only_no_paper_no_live",
        "scope": "modified_10u_rollover_rulebook_v2_research_only",
        "code_commit": _git_commit(),
        "research_question": "Does a small modification of the 10U bankroll discipline become more suitable for BTC trend following when entries use Donchian long/short and monthly trend is only a risk switch?",
        "economic_hypothesis": "The original 10U bankroll discipline may be useful if combined with a real trend signal, closer add triggers, no forced daily flat, and strict sleeve isolation.",
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_1h_rows": int(len(market.get("bars_1h", []))),
            "market_1h_start": _ts(market["bars_1h"].index.min()) if len(market.get("bars_1h", [])) else None,
            "market_1h_end": _ts(market["bars_1h"].index.max()) if len(market.get("bars_1h", [])) else None,
            "market_5m_rows": int(len(market.get("bars_5m", []))),
            "signal_source": "shifted frozen Donchian long/short trend direction derived from completed 1h->4h bars",
            "monthly_risk_switch": "completed monthly bars only; risk-off when completed month drops more than 20pct versus two completed months earlier",
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
    _write_text(markdown_path, render_btc_10u_rollover_rulebook_v2_lab_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _scenario_grid() -> list[RulebookV2Scenario]:
    scenarios: list[RulebookV2Scenario] = []
    for leverage in BASE_LEVERAGE_GRID:
        for add_mode in ADD_TRIGGER_MODES:
            for exit_mode in EXIT_MODES:
                scenarios.append(
                    RulebookV2Scenario(
                        scenario_id=f"tenu_v2_donchian_lev{_num_slug(leverage)}_{add_mode}_{exit_mode}",
                        base_leverage=leverage,
                        add_trigger_mode=add_mode,
                        exit_mode=exit_mode,
                    )
                )
    return scenarios


def _prepare_v2_market(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    try:
        bars_1h = load_market_1h(market_db_path)
    except Exception as exc:  # pragma: no cover
        return {"blockers": [f"market_1h_load_failed:{exc}"], "bars_1h": pd.DataFrame(), "bars_5m": pd.DataFrame()}
    if len(bars_1h) < 24 * 60:
        blockers.append("btc_10u_v2_less_than_60_days_1h_data")
    bars_5m = load_market_klines_frame(market_db_path, interval="5m")
    uses_1h_emergency_proxy = bool(bars_5m.empty)
    derivatives_1h = align_derivatives_to_index(derivatives_rows_path, pd.DatetimeIndex(bars_1h.index))
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    try:
        direction_4h = _donchian_direction_4h(
            bars_1h=bars_1h,
            bars_4h=bars_4h,
            derivatives_4h=align_derivatives_to_index(derivatives_rows_path, pd.DatetimeIndex(bars_4h.index)),
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        direction_1h = direction_4h.reindex(bars_1h.index, method="ffill").shift(1).fillna(0.0)
    except Exception as exc:
        blockers.append(f"btc_10u_v2_direction_source_failed:{exc}")
        direction_1h = pd.Series(0.0, index=bars_1h.index, dtype=float)
    monthly_risk_on = _completed_monthly_risk_on(bars_1h)
    signal = direction_1h.where(monthly_risk_on > 0.0, 0.0).reindex(bars_1h.index).fillna(0.0)
    emergency = _directional_emergency_adverse_by_hour(bars_1h=bars_1h, bars_5m=bars_5m)
    atr_pct = _atr_pct(bars_1h)
    return {
        "blockers": blockers,
        "bars_1h": bars_1h,
        "bars_5m": bars_5m,
        "derivatives_1h": derivatives_1h,
        "direction_1h": direction_1h.reindex(bars_1h.index).fillna(0.0),
        "monthly_risk_on": monthly_risk_on.reindex(bars_1h.index).fillna(0.0),
        "trade_signal": signal,
        "emergency_adverse": emergency.reindex(bars_1h.index).fillna(0.0),
        "atr_pct": atr_pct.reindex(bars_1h.index).ffill().fillna(0.0),
        "uses_1h_emergency_proxy": uses_1h_emergency_proxy,
    }


def _donchian_direction_4h(
    *,
    bars_1h: pd.DataFrame,
    bars_4h: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> pd.Series:
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    spec_map = {spec.variant_id: spec for spec in long_short_trend_following_specs(run_profile="formal_narrow")}
    spec = spec_map.get(BEST_BASE_VARIANT_ID)
    if spec is None:
        raise ValueError(f"missing Donchian base spec: {BEST_BASE_VARIANT_ID}")
    evaluated = evaluate_long_short_trend_rule(
        spec,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
    )
    return evaluated.exposure.apply(_sign).reindex(bars_4h.index).fillna(0.0)


def _completed_monthly_risk_on(bars_1h: pd.DataFrame) -> pd.Series:
    close = bars_1h["close"].astype(float)
    try:
        monthly_close = close.resample("ME").last()
    except ValueError:
        monthly_close = close.resample("M").last()
    previous = monthly_close.shift(1)
    reference = monthly_close.shift(3)
    risk_on = (previous >= reference * (1.0 - MONTHLY_RISK_OFF_DRAWDOWN_PCT)).astype(float)
    return risk_on.reindex(close.index, method="ffill").fillna(0.0)


def _directional_emergency_adverse_by_hour(*, bars_1h: pd.DataFrame, bars_5m: pd.DataFrame) -> pd.DataFrame:
    if bars_1h.empty:
        return pd.DataFrame(columns=["long_adverse", "short_adverse"])
    if bars_5m.empty:
        prev_close = bars_1h["close"].shift(1)
        output = pd.DataFrame(index=bars_1h.index)
        output["long_adverse"] = (1.0 - bars_1h["low"].astype(float) / prev_close).clip(lower=0.0).fillna(0.0)
        output["short_adverse"] = (bars_1h["high"].astype(float) / prev_close - 1.0).clip(lower=0.0).fillna(0.0)
        return output
    frame = bars_5m.copy()
    previous_close = frame["close"].astype(float).shift(1)
    frame["long_adverse"] = (1.0 - frame["low"].astype(float) / previous_close).clip(lower=0.0).fillna(0.0)
    frame["short_adverse"] = (frame["high"].astype(float) / previous_close - 1.0).clip(lower=0.0).fillna(0.0)
    return frame[["long_adverse", "short_adverse"]].groupby(pd.Grouper(freq="1h")).max().reindex(bars_1h.index).fillna(0.0)


def _atr_pct(bars_1h: pd.DataFrame) -> pd.Series:
    high = bars_1h["high"].astype(float)
    low = bars_1h["low"].astype(float)
    close = bars_1h["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat([(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    return (true_range.rolling(ATR_WINDOW, min_periods=4).mean() / close).replace([math.inf, -math.inf], 0.0)


def _simulate_v2(
    scenario: RulebookV2Scenario,
    *,
    market: Mapping[str, Any],
    initial_capital: float,
    base_cost_bps: float,
) -> RulebookV2Result:
    bars = market["bars_1h"]
    derivatives = market["derivatives_1h"].reindex(bars.index)
    signal = market["trade_signal"].reindex(bars.index).fillna(0.0)
    emergency = market["emergency_adverse"].reindex(bars.index).fillna(0.0)
    atr_pct = market["atr_pct"].reindex(bars.index).fillna(0.0)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=bars.index)), errors="coerce").fillna(0.0)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    sleeves = [SleeveAccount(sleeve_id=i + 1, balance=sleeve_initial) for i in range(INITIAL_SLEEVE_COUNT)]
    active: list[ActiveUnitV2] = []
    events: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    exposure_curve: list[float] = []
    safe_cash = 0.0
    strategic_reserve = 0.0
    current_leverage = float(scenario.base_leverage)
    cooldown_until: pd.Timestamp | None = None
    global_pause_until: pd.Timestamp | None = None
    campaign_anchor_price: float | None = None
    campaign_side = 0.0
    next_add_level = 0
    consecutive_losses = 0
    last_week_key: tuple[int, int] | None = None
    counts = {key: 0 for key in [
        "entry_count",
        "add_count",
        "stop_loss_count",
        "emergency_5m_kill_count",
        "trend_failure_exit_count",
        "risk_switch_exit_count",
        "max_hold_exit_count",
        "liquidation_count",
        "extract_count",
        "weekly_transfer_count",
        "cooldown_count",
        "global_pause_count",
        "leverage_derisk_count",
        "long_entry_count",
        "short_entry_count",
    ]}
    leverage_entries: list[float] = []
    min_remaining = {shock: 100.0 for shock in SPIKE_STRESS_PCTS}
    max_sleeves_lost = {shock: 0 for shock in SPIKE_STRESS_PCTS}
    funding_cost_amount = 0.0
    fee_slippage_cost_amount = 0.0
    cost_rate = float(base_cost_bps) / 10_000.0
    index = pd.DatetimeIndex(bars.index)

    for pos, ts in enumerate(index):
        price = float(close.iloc[pos])
        side_signal = _sign(float(signal.iloc[pos]))
        if pos > 0 and active:
            active, close_events, fee_delta, funding_delta = _mark_active_units(
                active,
                ts=ts,
                previous_price=float(close.iloc[pos - 1]),
                close_price=price,
                high_price=float(high.iloc[pos]),
                low_price=float(low.iloc[pos]),
                emergency_row=emergency.iloc[pos],
                funding_rate=float(funding.iloc[pos]),
                base_cost_rate=cost_rate,
            )
            fee_slippage_cost_amount += fee_delta
            funding_cost_amount += funding_delta
            events.extend(close_events)
            terminal_events = _terminal_loss_events(close_events)
            for event in close_events:
                event_type = str(event.get("event_type"))
                if event_type in counts:
                    counts[event_type] += 1
            _settle_closed_units(close_events, sleeves=sleeves)
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
                campaign_side = 0.0
                next_add_level = 0

        if active:
            safe_cash = _extract_profit_if_needed(active, ts=ts, events=events, safe_cash=safe_cash, counts=counts)

        if active:
            exit_reason = _exit_reason(
                scenario=scenario,
                active=active,
                side_signal=side_signal,
                ts=ts,
                monthly_risk_on=float(market["monthly_risk_on"].reindex(index).iloc[pos]) > 0.0,
            )
            if exit_reason:
                pnl = _close_all_active(
                    active,
                    sleeves=sleeves,
                    ts=ts,
                    exit_price=price,
                    event_type=exit_reason,
                    events=events,
                    cost_rate=cost_rate,
                )
                counts[exit_reason] += 1
                active = []
                consecutive_losses, cooldown_until, global_pause_until, current_leverage = _after_campaign_close(
                    pnl=pnl,
                    ts=ts,
                    consecutive_losses=consecutive_losses,
                    current_leverage=current_leverage,
                    counts=counts,
                )
                campaign_anchor_price = None
                campaign_side = 0.0
                next_add_level = 0

        if not active:
            campaign_anchor_price = None
            campaign_side = 0.0
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
            side_signal != 0.0
            and float(market["monthly_risk_on"].reindex(index).iloc[pos]) > 0.0
            and (cooldown_until is None or ts >= cooldown_until)
            and (global_pause_until is None or ts >= global_pause_until)
        )
        if can_trade:
            if not active:
                opened = _open_unit(
                    sleeves=sleeves,
                    side=side_signal,
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
                    if side_signal > 0.0:
                        counts["long_entry_count"] += 1
                    else:
                        counts["short_entry_count"] += 1
                    leverage_entries.append(current_leverage)
                    campaign_anchor_price = price
                    campaign_side = side_signal
                    next_add_level = 1
            elif campaign_anchor_price and side_signal == campaign_side:
                while next_add_level < len(ADD_ALLOCATION_MULTIPLIERS) and _add_trigger_hit(
                    scenario=scenario,
                    side=campaign_side,
                    price=price,
                    anchor_price=campaign_anchor_price,
                    atr_pct=float(atr_pct.iloc[pos]),
                    level=next_add_level,
                ):
                    opened = _open_unit(
                        sleeves=sleeves,
                        side=campaign_side,
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
        equity_curve.append(total_equity)
        exposure_curve.append(gross_exposure / max(1e-9, total_equity))
        for shock in SPIKE_STRESS_PCTS:
            lost_equity = 0.0
            lost_count = 0
            for unit in active:
                if shock / 100.0 >= _liquidation_threshold(unit.leverage):
                    lost_equity += unit.equity
                    lost_count += 1
            remaining = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_remaining[shock] = min(min_remaining[shock], remaining)
            max_sleeves_lost[shock] = max(max_sleeves_lost[shock], lost_count)

    if active and len(index):
        _close_all_active(active, sleeves=sleeves, ts=index[-1], exit_price=float(close.iloc[-1]), event_type="end_of_sample_close", events=events, cost_rate=cost_rate)
        active = []
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
    return RulebookV2Result(scenario=scenario, metrics=metrics, events=tuple(events[:1500]))


def _mark_active_units(
    active: Sequence[ActiveUnitV2],
    *,
    ts: pd.Timestamp,
    previous_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
    emergency_row: Any,
    funding_rate: float,
    base_cost_rate: float,
) -> tuple[list[ActiveUnitV2], list[dict[str, Any]], float, float]:
    survivors: list[ActiveUnitV2] = []
    events: list[dict[str, Any]] = []
    fee_delta = 0.0
    funding_delta = 0.0
    for unit in active:
        adverse = _adverse_move(side=unit.side, high=high_price, low=low_price, previous_price=previous_price)
        threshold = _liquidation_threshold(unit.leverage)
        if adverse >= threshold:
            events.append(_unit_event(unit=unit, ts=ts, event_type="liquidation_count", amount=unit.equity, note="isolated sleeve liquidation proxy"))
            continue
        stop_hit = (unit.side > 0.0 and low_price <= unit.entry_price * (1.0 - STOP_LOSS_PCT)) or (
            unit.side < 0.0 and high_price >= unit.entry_price * (1.0 + STOP_LOSS_PCT)
        )
        if stop_hit:
            exit_price = unit.entry_price * (1.0 - STOP_LOSS_PCT) if unit.side > 0.0 else unit.entry_price * (1.0 + STOP_LOSS_PCT)
            closed = _closed_unit_event(unit=unit, ts=ts, exit_price=exit_price, event_type="stop_loss_count", note="3pct adverse stop", funding_rate=funding_rate, base_cost_rate=base_cost_rate)
            events.append(closed)
            fee_delta += float(closed["fee_slippage_cost_amount"])
            funding_delta += float(closed["funding_cost_amount"])
            continue
        directional_emergency = _emergency_adverse_for_side(emergency_row, unit.side)
        if directional_emergency >= EMERGENCY_5M_ADVERSE_PCT:
            exit_price = previous_price * (1.0 - EMERGENCY_5M_ADVERSE_PCT) if unit.side > 0.0 else previous_price * (1.0 + EMERGENCY_5M_ADVERSE_PCT)
            closed = _closed_unit_event(unit=unit, ts=ts, exit_price=exit_price, event_type="emergency_5m_kill_count", note="5m adverse move exceeded 5pct", funding_rate=funding_rate, base_cost_rate=base_cost_rate)
            events.append(closed)
            fee_delta += float(closed["fee_slippage_cost_amount"])
            funding_delta += float(closed["funding_cost_amount"])
            continue
        protection_hit = False
        if unit.protection_active:
            if unit.side > 0.0:
                protection_hit = low_price <= unit.best_price * (1.0 - DYNAMIC_PROTECTION_PCT)
            else:
                protection_hit = high_price >= unit.best_price * (1.0 + DYNAMIC_PROTECTION_PCT)
        if protection_hit:
            exit_price = unit.best_price * (1.0 - DYNAMIC_PROTECTION_PCT) if unit.side > 0.0 else unit.best_price * (1.0 + DYNAMIC_PROTECTION_PCT)
            closed = _closed_unit_event(unit=unit, ts=ts, exit_price=exit_price, event_type="dynamic_protection_exit", note="dynamic protection after profit extraction", funding_rate=funding_rate, base_cost_rate=base_cost_rate)
            events.append(closed)
            fee_delta += float(closed["fee_slippage_cost_amount"])
            funding_delta += float(closed["funding_cost_amount"])
            continue
        funding_return = -unit.side * unit.leverage * float(funding_rate) * (1.0 / 8.0)
        if funding_return < 0.0:
            funding_delta += unit.equity * abs(funding_return)
        unit.equity = max(0.0, unit.equity * (1.0 + unit.side * unit.leverage * (close_price / max(1e-12, unit.last_price) - 1.0) + funding_return))
        unit.last_price = close_price
        unit.best_price = max(unit.best_price, high_price, close_price) if unit.side > 0.0 else min(unit.best_price, low_price, close_price)
        survivors.append(unit)
    return survivors, events, fee_delta, funding_delta


def _exit_reason(
    *,
    scenario: RulebookV2Scenario,
    active: Sequence[ActiveUnitV2],
    side_signal: float,
    ts: pd.Timestamp,
    monthly_risk_on: bool,
) -> str:
    if not monthly_risk_on:
        return "risk_switch_exit_count"
    if not active:
        return ""
    current_side = _sign(active[0].side)
    if scenario.exit_mode == "trend_failure" and side_signal != current_side:
        return "trend_failure_exit_count"
    if scenario.exit_mode == "no_daily_flat" and side_signal == -current_side:
        return "trend_failure_exit_count"
    if scenario.exit_mode == "max_hold_24h":
        oldest = min(unit.opened_at for unit in active)
        if ts >= oldest + pd.Timedelta(hours=MAX_HOLD_HOURS):
            return "max_hold_exit_count"
        if side_signal == -current_side:
            return "trend_failure_exit_count"
    return ""


def _add_trigger_hit(*, scenario: RulebookV2Scenario, side: float, price: float, anchor_price: float, atr_pct: float, level: int) -> bool:
    favorable = side * (price / max(1e-12, anchor_price) - 1.0)
    if scenario.add_trigger_mode == "pct_8":
        return favorable >= 0.08 * level
    if scenario.add_trigger_mode == "pct_12":
        return favorable >= 0.12 * level
    if scenario.add_trigger_mode == "pct_16":
        return favorable >= 0.16 * level
    if scenario.add_trigger_mode == "atr_1":
        return favorable >= max(0.0, float(atr_pct)) * level
    return False


def _open_unit(
    *,
    sleeves: Sequence[SleeveAccount],
    side: float,
    level: int,
    allocation_multiplier: float,
    leverage: float,
    entry_price: float,
    ts: pd.Timestamp,
    events: list[dict[str, Any]],
    cost_rate: float,
    event_type: str,
    sleeve_initial: float,
) -> ActiveUnitV2 | None:
    target = max(1e-9, sleeve_initial * float(allocation_multiplier))
    for sleeve in sleeves:
        if sleeve.balance < target * 0.25:
            continue
        allocation = min(sleeve.balance, target)
        sleeve.balance -= allocation
        opening_cost = allocation * cost_rate
        unit = ActiveUnitV2(
            sleeve_id=sleeve.sleeve_id,
            level=level,
            side=side,
            entry_price=entry_price,
            last_price=entry_price,
            equity=max(0.0, allocation - opening_cost),
            basis_equity=max(1e-9, allocation),
            leverage=leverage,
            opened_at=ts,
            best_price=entry_price,
        )
        events.append(_unit_event(unit=unit, ts=ts, event_type=event_type, amount=allocation, note=f"side={_side_name(side)} allocation_multiplier={allocation_multiplier} leverage={_round(leverage)}"))
        return unit
    return None


def _close_all_active(
    active: Sequence[ActiveUnitV2],
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
        unit.equity = max(0.0, unit.equity * (1.0 + unit.side * unit.leverage * (exit_price / max(1e-12, unit.last_price) - 1.0) - cost_rate))
        pnl += unit.equity - unit.basis_equity
        for sleeve in sleeves:
            if sleeve.sleeve_id == unit.sleeve_id:
                sleeve.balance += unit.equity
                break
        events.append(_unit_event(unit=unit, ts=ts, event_type=event_type, amount=unit.equity, note=f"closed_from={_round(before)} exit_price={_round(exit_price)}"))
    return pnl


def _closed_unit_event(
    *,
    unit: ActiveUnitV2,
    ts: pd.Timestamp,
    exit_price: float,
    event_type: str,
    note: str,
    funding_rate: float,
    base_cost_rate: float,
) -> dict[str, Any]:
    funding_return = -unit.side * unit.leverage * float(funding_rate) * (1.0 / 8.0)
    funding_cost = unit.equity * abs(funding_return) if funding_return < 0.0 else 0.0
    fee_cost = unit.equity * base_cost_rate
    unit.equity = max(0.0, unit.equity * (1.0 + unit.side * unit.leverage * (exit_price / max(1e-12, unit.last_price) - 1.0) + funding_return - base_cost_rate))
    return {
        **_unit_event(unit=unit, ts=ts, event_type=event_type, amount=unit.equity, note=note),
        "closed": True,
        "realized_pnl": _round(unit.equity - unit.basis_equity),
        "funding_cost_amount": _round(funding_cost),
        "fee_slippage_cost_amount": _round(fee_cost),
    }


def _extract_profit_if_needed(active: Sequence[ActiveUnitV2], *, ts: pd.Timestamp, events: list[dict[str, Any]], safe_cash: float, counts: dict[str, int]) -> float:
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
    return safe_cash


def _settle_closed_units(events: Sequence[Mapping[str, Any]], *, sleeves: Sequence[SleeveAccount]) -> None:
    for event in events:
        if not bool(event.get("closed")):
            continue
        sleeve_id = int(event.get("sleeve_id", 0))
        for sleeve in sleeves:
            if sleeve.sleeve_id == sleeve_id:
                sleeve.balance += float(event.get("amount", 0.0))
                break


def _terminal_loss_events(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        event
        for event in events
        if str(event.get("event_type")) in {"stop_loss_count", "emergency_5m_kill_count", "liquidation_count"} and float(event.get("realized_pnl", -1.0)) < 0.0
    ]


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
        events.append({"timestamp": _ts(ts), "event_type": "weekly_profit_transfer", "sleeve_id": sleeve.sleeve_id, "safe_transfer": _round(safe), "strategic_reserve": _round(reserve), "paper_queue_write_allowed": False, "live_unlock_allowed": False})
    return safe_delta, reserve_delta, events


def _metrics(
    *,
    scenario: RulebookV2Scenario,
    equity: pd.Series,
    exposure: pd.Series,
    sleeves: Sequence[SleeveAccount],
    active: Sequence[ActiveUnitV2],
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


def _result_row(result: RulebookV2Result) -> dict[str, Any]:
    s = result.scenario
    row = {
        "scenario_id": s.scenario_id,
        "base_leverage": s.base_leverage,
        "add_trigger_mode": s.add_trigger_mode,
        "exit_mode": s.exit_mode,
        "entry_signal": "shifted_frozen_donchian_long_short",
        "monthly_risk_switch_only": True,
        "stop_loss_pct": STOP_LOSS_PCT,
        "emergency_5m_adverse_pct": EMERGENCY_5M_ADVERSE_PCT,
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
        return "extreme_leverage_v2_research_only_not_paper_eligible"
    if float(row.get("total_return_pct", -100.0)) <= 0.0:
        return "reject_non_positive_v2_return"
    if int(row.get("liquidation_count", 0)) > 0:
        return "reject_liquidation_observed"
    if float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) < 40.0:
        return "reject_below_40pct_remaining_after_10pct_spike"
    return "retain_10u_v2_research_watchlist_only"


def _rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, str]:
    retained = 0 if row.get("research_decision") == "retain_10u_v2_research_watchlist_only" else 1
    return (
        retained,
        -float(row.get("annual_return_pct", -999.0)),
        -float(row.get("total_return_pct", -999.0)),
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        str(row.get("scenario_id", "")),
    )


def _research_design(*, scenario_count: int, candidate_count: int) -> dict[str, Any]:
    return {
        "source": "10U rulebook v2 small modification requested by user",
        "scenario_count": scenario_count,
        "candidate_count": candidate_count,
        "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
        "base_leverage_grid": list(BASE_LEVERAGE_GRID),
        "add_trigger_modes": list(ADD_TRIGGER_MODES),
        "exit_modes": list(EXIT_MODES),
        "max_hold_hours": MAX_HOLD_HOURS,
        "entry_signal": "existing Donchian long/short trend direction, shifted before 1h execution",
        "monthly_risk_switch": {
            "role": "big risk switch only, not an entry signal",
            "risk_off_drawdown_pct": MONTHLY_RISK_OFF_DRAWDOWN_PCT,
            "visibility": "completed monthly bars only",
        },
        "stop_loss_pct": STOP_LOSS_PCT,
        "emergency_5m_adverse_pct": EMERGENCY_5M_ADVERSE_PCT,
        "add_allocation_multipliers": list(ADD_ALLOCATION_MULTIPLIERS),
        "profit_extract_rule": "when sleeve equity reaches 3x basis, extract 50pct of floating profit and activate dynamic protection",
        "cooldown_after_loss_hours": COOLDOWN_HOURS_AFTER_LOSS,
        "leverage_derisk_multiplier_after_loss": LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS,
        "consecutive_loss_pause_trigger": CONSECUTIVE_LOSS_PAUSE_TRIGGER,
        "global_pause_days": GLOBAL_PAUSE_DAYS,
        "same_bar_profit_allowed": False,
        "paper_live_boundary": "research-only artifact; no strategy skeleton, paper queue write, broker, OMS, order, or live unlock",
    }


def _summary(*, grid_rows: Sequence[Mapping[str, Any]], watchlist_rows: Sequence[Mapping[str, Any]], market: Mapping[str, Any]) -> dict[str, Any]:
    best = grid_rows[0] if grid_rows else {}
    signal = market.get("trade_signal", pd.Series(dtype=float))
    risk = market.get("monthly_risk_on", pd.Series(dtype=float))
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
        "trade_signal_nonzero_ratio": _round(float((signal != 0.0).mean()) if len(signal) else 0.0),
        "monthly_risk_on_ratio": _round(float(risk.mean()) if len(risk) else 0.0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _warnings(*, blockers: Sequence[str], market: Mapping[str, Any], grid_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_10u_rollover_rulebook_v2_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_10u_rollover_rulebook_v2_blocked_or_degraded_inputs")
    if bool(market.get("uses_1h_emergency_proxy")):
        warnings.append("5m_emergency_kill_used_1h_proxy_due_to_missing_5m_data")
    if any(float(row.get("base_leverage", 0.0)) > 10.0 for row in grid_rows):
        warnings.append("15x_20x_are_extreme_research_only_not_paper_eligible")
    return warnings


def render_btc_10u_rollover_rulebook_v2_lab_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 10U 滚仓小改版 v2 实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 候选数：`{summary.get('candidate_count')}`，普通 watchlist：`{summary.get('watchlist_count')}`",
        f"- 最佳场景：`{summary.get('best_scenario_id')}`",
        f"- 最佳年化 / 总收益 / 回撤：`{summary.get('best_annual_return_pct')}` / `{summary.get('best_total_return_pct')}` / `{summary.get('best_max_drawdown_abs_pct')}`",
        f"- -10% 插针后最低剩余本金：`{summary.get('best_min_remaining_after_10pct_spike')}`%",
        f"- Donchian 信号覆盖率：`{summary.get('trade_signal_nonzero_ratio')}`，月线风险开关通过率：`{summary.get('monthly_risk_on_ratio')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## v2 改动",
        "",
        "- 入场改为已有 Donchian long/short 趋势信号。",
        "- 月线只做大风险开关，不再单独当入场条件。",
        "- 加码触发从 30% 改成 8% / 12% / 16% / ATR。",
        "- 退出从每日清仓改成不日清、趋势失败才清、24h 最大持仓三档。",
        "- 仍保留 10 份资金隔离、3% 止损、5m 急停、提本金、冷却、降杠杆、三连错暂停。",
        "",
        "## Top 场景",
        "",
        "| 排名 | 场景 | 杠杆 | 加码 | 退出 | 年化 | 回撤 | -10%剩余 | 多/空入场 | 结论 |",
        "|---:|---|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(report.get("top_watchlist", [])[:10], start=1):
        entry_count = int(row.get("long_entry_count", 0)) + int(row.get("short_entry_count", 0))
        lines.append(
            f"| {idx} | `{row.get('scenario_id')}` | {row.get('base_leverage')} | `{row.get('add_trigger_mode')}` | `{row.get('exit_mode')}` | "
            f"{row.get('annual_return_pct')} | {row.get('max_drawdown_abs_pct')} | {row.get('min_remaining_capital_pct_after_10pct_spike')} | "
            f"{entry_count} | `{row.get('research_decision')}` |"
        )
    if not report.get("top_watchlist"):
        lines.append("| - | 无普通 watchlist | - | - | - | - | - | - | - | 全部仍为 research-only 或未过基础线 |")
    lines.extend(["", "本报告只做 research-only，不写 paper 队列，不生成策略骨架，不接 broker/OMS/order，不解锁 live。"])
    return "\n".join(lines) + "\n"


def _adverse_move(*, side: float, high: float, low: float, previous_price: float) -> float:
    if side > 0.0:
        return max(0.0, 1.0 - low / max(1e-12, previous_price))
    if side < 0.0:
        return max(0.0, high / max(1e-12, previous_price) - 1.0)
    return 0.0


def _emergency_adverse_for_side(row: Any, side: float) -> float:
    if isinstance(row, pd.Series):
        return float(row.get("long_adverse" if side > 0.0 else "short_adverse", 0.0))
    return 0.0


def _liquidation_threshold(leverage: float) -> float:
    return max(0.0, 1.0 / float(leverage) - MAINTENANCE_MARGIN_RATE - LIQUIDATION_FEE_RATE - MARK_ADVERSE_OFFSET_BPS / 10_000.0)


def _total_equity(*, sleeves: Sequence[SleeveAccount], active: Sequence[ActiveUnitV2], safe_cash: float, strategic_reserve: float) -> float:
    return sum(max(0.0, sleeve.balance) for sleeve in sleeves) + sum(max(0.0, unit.equity) for unit in active) + max(0.0, safe_cash) + max(0.0, strategic_reserve)


def _unit_event(*, unit: ActiveUnitV2, ts: pd.Timestamp, event_type: str, amount: float, note: str) -> dict[str, Any]:
    return {
        "timestamp": _ts(ts),
        "event_type": event_type,
        "sleeve_id": unit.sleeve_id,
        "level": unit.level,
        "side": _side_name(unit.side),
        "leverage": _round(unit.leverage),
        "amount": _round(amount),
        "unit_equity_after": _round(unit.equity),
        "entry_price": _round(unit.entry_price),
        "last_price": _round(unit.last_price),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _research_only_gate_reason() -> str:
    return "10U rulebook v2 is a high-risk research-only modification and cannot promote strategies."


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
        "reason": _research_only_gate_reason(),
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
        "schema_version": "btc_10u_rollover_rulebook_v2_lab_safety_status_v1",
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
        "reason": _research_only_gate_reason(),
        "blockers": list(report.get("blockers", [])),
    }


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def _side_name(side: float) -> str:
    return "long" if side > 0.0 else ("short" if side < 0.0 else "flat")


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
