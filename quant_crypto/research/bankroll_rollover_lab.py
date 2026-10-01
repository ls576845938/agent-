from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.high_yield_v2_confirmation import (
    FROZEN_DRAWDOWN_GATE_PCT,
    FROZEN_MAX_LEVERAGE,
    FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
    FROZEN_VOL_TARGET_PCT,
)
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import (
    BEST_BASE_VARIANT_ID,
    ReviewPolicy,
    _git_commit,
    _prepare_market_context,
    _portable_path,
    _round,
    _simulate_review_variant,
    _v2_variant,
)


SCHEMA_VERSION = "btc_bankroll_rollover_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_bankroll_rollover_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_lab_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_lab_grid.csv"
DEFAULT_EVENTS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

ROLLOVER_POLICIES = ("no_rollover", "extract_principal_roll_profit", "split_2_on_double", "split_5_on_double")
LEVERAGE_LEVELS = (3.0, 5.0, 10.0, 20.0, 50.0, 100.0)
INITIAL_SLEEVE_COUNT = 10
MAX_SLEEVE_COUNT = 100
ROLL_MULTIPLE = 2.0
MAINTENANCE_MARGIN_RATE = 0.005
LIQUIDATION_FEE_RATE = 0.003


@dataclass
class Sleeve:
    sleeve_id: int
    equity: float
    basis_equity: float
    status: str = "active"
    liquidation_count: int = 0
    rollover_count: int = 0


@dataclass(frozen=True)
class BankrollScenario:
    scenario_id: str
    rollover_policy: str
    leverage: float
    funding_stress_multiplier: float = 1.0
    cost_multiplier: float = 1.0


@dataclass
class BankrollResult:
    scenario: BankrollScenario
    equity: pd.Series
    active_exposure: pd.Series
    metrics: dict[str, Any]
    events: list[dict[str, Any]]
    sleeve_distribution: dict[str, Any]


def build_btc_bankroll_rollover_lab(
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
    grid_csv_path = output_dir / DEFAULT_GRID_CSV_PATH.name
    events_csv_path = output_dir / DEFAULT_EVENTS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    results: list[BankrollResult] = []
    for leverage in LEVERAGE_LEVELS:
        for policy in ROLLOVER_POLICIES:
            scenario = BankrollScenario(
                scenario_id=f"br_{policy}_lev{str(leverage).replace('.', 'p')}",
                rollover_policy=policy,
                leverage=leverage,
            )
            result = _simulate_bankroll(
                scenario,
                market=market,
                direction=direction,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            results.append(result)
            rows.append(_candidate_row(result))
            event_rows.extend(result.events[:200])

    rows = sorted(rows, key=lambda row: (-float(row["final_equity"]), float(row["total_liquidation_count"]), row["scenario_id"]))
    stress = _stress_summary(
        market=market,
        direction=direction,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
        rows=rows,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_bankroll_rollover_lab_research_only_no_paper_no_live",
        "scope": "isolated_sleeve_bankroll_rollover_research",
        "code_commit": _git_commit(),
        "research_question": "Can isolated sleeve rollover with high leverage capture BTC trends without unacceptable wipeout and liquidation risk?",
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(market["bars_4h"])),
            "market_4h_start": _ts(market["bars_4h"].index.min()) if len(market["bars_4h"]) else None,
            "market_4h_end": _ts(market["bars_4h"].index.max()) if len(market["bars_4h"]) else None,
            "direction_source": "frozen high-yield v3 loss-control direction, generated from completed 1h->4h bars",
            "funding_source": "derivatives rows aligned by available_time <= decision_time; research approximation",
        },
        "experiment_design": {
            "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
            "max_sleeve_count": MAX_SLEEVE_COUNT,
            "roll_multiple": ROLL_MULTIPLE,
            "leverage_levels": list(LEVERAGE_LEVELS),
            "rollover_policies": list(ROLLOVER_POLICIES),
            "candidate_count": len(rows),
            "expected_candidate_count": len(LEVERAGE_LEVELS) * len(ROLLOVER_POLICIES),
            "liquidation_model": {
                "model": "isolated_linear_perp_intrabar_mark_proxy",
                "maintenance_margin_rate": MAINTENANCE_MARGIN_RATE,
                "liquidation_fee_rate": LIQUIDATION_FEE_RATE,
                "threshold_formula": "max(0, 1/leverage - maintenance_margin_rate - liquidation_fee_rate)",
                "price_path": "uses 4h high/low as mark proxy; not production-eligible",
            },
            "funding_model": {
                "settlement": "4h prorated from 8h funding rate when visible",
                "visibility_rule": "available_time <= decision_time via existing derivatives alignment",
                "promotion_evidence": False,
            },
        },
        "candidate_rows": rows,
        "stress_summary": stress,
        "event_sample": _event_sample(event_rows),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(rows),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_csv_path),
            "events_csv": _portable_path(events_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_csv_path, rows)
    _write_csv(events_csv_path, event_rows[:200])
    _write_json(safety_path, _safety_status(report))
    _write_text(markdown_path, render_btc_bankroll_rollover_lab_markdown(report))
    return report


def _frozen_v3_direction(market: Mapping[str, Any], *, initial_capital: float, base_cost_bps: float) -> pd.Series:
    variant = _v2_variant(FROZEN_VOL_TARGET_PCT, FROZEN_MAX_LEVERAGE, "hy_v3_lossctl_direction_source")
    policy = ReviewPolicy(
        drawdown_gate_pct=FROZEN_DRAWDOWN_GATE_PCT,
        min_liquidation_buffer_bps=FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
        fast_stop_base_pct=6.0,
        stop_cooldown_bars=12,
        consecutive_loss_trigger_bars=3,
        consecutive_loss_derisk_bars=12,
        enable_failed_breakout_exit=True,
    )
    sim = _simulate_review_variant(
        variant,
        base_signal=market["base_signal"],
        bars=market["bars_4h"],
        derivatives=market["derivatives_4h"],
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
        policy=policy,
    )
    return sim.exposure.apply(lambda value: 1.0 if value > 1e-12 else (-1.0 if value < -1e-12 else 0.0))


def _simulate_bankroll(
    scenario: BankrollScenario,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> BankrollResult:
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close_returns = close.pct_change().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    sleeves: list[Sleeve] = [Sleeve(sleeve_id=i + 1, equity=sleeve_initial, basis_equity=sleeve_initial) for i in range(INITIAL_SLEEVE_COUNT)]
    next_sleeve_id = INITIAL_SLEEVE_COUNT + 1
    reserve_cash = 0.0
    previous_side = 0.0
    equity_curve: list[float] = []
    active_exposure_curve: list[float] = []
    events: list[dict[str, Any]] = []
    per_bar_liquidations: list[int] = []
    max_sleeves_observed = len(sleeves)
    cost_rate = float(base_cost_bps) * float(scenario.cost_multiplier) / 10_000.0
    liq_threshold = max(0.0, 1.0 / float(scenario.leverage) - MAINTENANCE_MARGIN_RATE - LIQUIDATION_FEE_RATE)

    for pos, ts in enumerate(direction.index):
        side = float(direction.iloc[pos])
        active_before = [sleeve for sleeve in sleeves if sleeve.status == "active" and sleeve.equity > 0.0]
        turnover_cost = cost_rate if side != previous_side else 0.0
        liquidations_this_bar = 0
        if pos == 0:
            bar_return = 0.0
        else:
            bar_return = float(close_returns.iloc[pos])
        for sleeve in active_before:
            if side == 0.0:
                continue
            adverse = _adverse_move(high=high, low=low, close=close, pos=pos, side=side)
            if adverse >= liq_threshold:
                events.append(
                    _event(
                        scenario=scenario,
                        ts=ts,
                        sleeve=sleeve,
                        event_type="liquidation",
                        amount=sleeve.equity,
                        note=f"adverse_move={_round(adverse * 100.0)} pct >= liquidation_threshold={_round(liq_threshold * 100.0)} pct",
                    )
                )
                sleeve.equity = 0.0
                sleeve.status = "liquidated"
                sleeve.liquidation_count += 1
                liquidations_this_bar += 1
                continue
            base_funding_return = -side * float(scenario.leverage) * float(funding.iloc[pos]) * (4.0 / 8.0)
            funding_return = base_funding_return - abs(base_funding_return) * max(0.0, float(scenario.funding_stress_multiplier) - 1.0)
            price_return = side * float(scenario.leverage) * bar_return
            net_return = price_return + funding_return - turnover_cost
            sleeve.equity = max(0.0, sleeve.equity * (1.0 + net_return))
            if sleeve.equity <= 0.0:
                sleeve.status = "dead"
                liquidations_this_bar += 1

        if side != 0.0:
            next_sleeve_id, reserve_cash = _apply_rollover(
                sleeves,
                scenario=scenario,
                ts=ts,
                events=events,
                next_sleeve_id=next_sleeve_id,
                reserve_cash=reserve_cash,
            )
        max_sleeves_observed = max(max_sleeves_observed, len([s for s in sleeves if s.status == "active"]))
        per_bar_liquidations.append(liquidations_this_bar)
        total_equity = reserve_cash + sum(max(0.0, sleeve.equity) for sleeve in sleeves if sleeve.status == "active")
        active_exposure = sum(abs(side) * scenario.leverage * sleeve.equity for sleeve in sleeves if sleeve.status == "active") / total_equity if total_equity > 0.0 else 0.0
        equity_curve.append(total_equity)
        active_exposure_curve.append(active_exposure)
        previous_side = side

    equity = pd.Series(equity_curve, index=direction.index, dtype=float)
    active_exposure = pd.Series(active_exposure_curve, index=direction.index, dtype=float)
    metrics = _metrics(
        equity=equity,
        active_exposure=active_exposure,
        sleeves=sleeves,
        reserve_cash=reserve_cash,
        initial_capital=initial_capital,
        liquidations_per_bar=per_bar_liquidations,
        max_sleeves_observed=max_sleeves_observed,
        liq_threshold=liq_threshold,
    )
    distribution = _sleeve_distribution(sleeves, sleeve_initial=sleeve_initial, reserve_cash=reserve_cash)
    return BankrollResult(scenario=scenario, equity=equity, active_exposure=active_exposure, metrics=metrics, events=events, sleeve_distribution=distribution)


def _apply_rollover(
    sleeves: list[Sleeve],
    *,
    scenario: BankrollScenario,
    ts: pd.Timestamp,
    events: list[dict[str, Any]],
    next_sleeve_id: int,
    reserve_cash: float,
) -> tuple[int, float]:
    active = [sleeve for sleeve in sleeves if sleeve.status == "active" and sleeve.equity >= sleeve.basis_equity * ROLL_MULTIPLE]
    for sleeve in active:
        if scenario.rollover_policy == "no_rollover":
            sleeve.basis_equity = sleeve.equity
            continue
        if scenario.rollover_policy == "extract_principal_roll_profit":
            extract = min(sleeve.basis_equity, sleeve.equity)
            sleeve.equity -= extract
            reserve_cash += extract
            sleeve.basis_equity = max(sleeve.equity, 1e-9)
            sleeve.rollover_count += 1
            events.append(_event(scenario=scenario, ts=ts, sleeve=sleeve, event_type="extract_principal", amount=extract, note="principal moved to reserve cash"))
            continue
        split_count = 2 if scenario.rollover_policy == "split_2_on_double" else 5
        active_count = len([item for item in sleeves if item.status == "active"])
        if active_count + split_count - 1 > MAX_SLEEVE_COUNT:
            sleeve.basis_equity = sleeve.equity
            events.append(_event(scenario=scenario, ts=ts, sleeve=sleeve, event_type="rollover_skipped_max_sleeves", amount=0.0, note="max sleeve count reached"))
            continue
        parent_equity = sleeve.equity
        child_equity = parent_equity / split_count
        sleeve.status = "rolled"
        sleeve.rollover_count += 1
        for _ in range(split_count):
            sleeves.append(Sleeve(sleeve_id=next_sleeve_id, equity=child_equity, basis_equity=child_equity))
            next_sleeve_id += 1
        events.append(_event(scenario=scenario, ts=ts, sleeve=sleeve, event_type=f"split_{split_count}_on_double", amount=parent_equity, note="equity split into child sleeves"))
        sleeve.equity = 0.0
    return next_sleeve_id, reserve_cash


def _metrics(
    *,
    equity: pd.Series,
    active_exposure: pd.Series,
    sleeves: Sequence[Sleeve],
    reserve_cash: float,
    initial_capital: float,
    liquidations_per_bar: Sequence[int],
    max_sleeves_observed: int,
    liq_threshold: float,
) -> dict[str, Any]:
    if equity.empty:
        return {}
    final_equity = float(equity.iloc[-1])
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((equity.index.max() - equity.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    drawdown = equity / equity.cummax() - 1.0
    total_liq = sum(sleeve.liquidation_count for sleeve in sleeves)
    active_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "active" and sleeve.equity > 0.0]
    dead_sleeves = [sleeve for sleeve in sleeves if sleeve.status in {"liquidated", "dead"}]
    rolled_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "rolled"]
    return {
        "final_equity": _round(final_equity),
        "reserve_cash": _round(reserve_cash),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0),
        "active_sleeve_count": len(active_sleeves),
        "dead_sleeve_count": len(dead_sleeves),
        "rolled_sleeve_count": len(rolled_sleeves),
        "total_sleeve_count": len(sleeves),
        "max_sleeves_observed": int(max_sleeves_observed),
        "total_liquidation_count": int(total_liq),
        "max_same_bar_liquidation_count": int(max(liquidations_per_bar) if liquidations_per_bar else 0),
        "all_sleeves_dead": len(active_sleeves) == 0,
        "average_gross_exposure": _round(float(active_exposure.mean()) if len(active_exposure) else 0.0),
        "max_gross_exposure": _round(float(active_exposure.max()) if len(active_exposure) else 0.0),
        "liquidation_threshold_pct": _round(liq_threshold * 100.0),
        "liquidation_threshold_bps": _round(liq_threshold * 10_000.0),
    }


def _sleeve_distribution(sleeves: Sequence[Sleeve], *, sleeve_initial: float, reserve_cash: float) -> dict[str, Any]:
    terminal = [max(0.0, sleeve.equity) for sleeve in sleeves if sleeve.status != "rolled"]
    if not terminal:
        terminal = [0.0]
    sorted_terminal = sorted(terminal)
    worst_5_index = max(0, int(len(sorted_terminal) * 0.05) - 1)
    return {
        "terminal_sleeve_count": len(terminal),
        "median_terminal_sleeve_equity": _round(float(pd.Series(terminal).median())),
        "worst_5pct_terminal_sleeve_equity": _round(float(sorted_terminal[worst_5_index])),
        "best_terminal_sleeve_equity": _round(max(terminal)),
        "sleeves_above_initial_count": sum(1 for value in terminal if value >= sleeve_initial),
        "reserve_cash": _round(reserve_cash),
    }


def _candidate_row(result: BankrollResult) -> dict[str, Any]:
    row = {
        "scenario_id": result.scenario.scenario_id,
        "rollover_policy": result.scenario.rollover_policy,
        "leverage": result.scenario.leverage,
        "funding_stress_multiplier": result.scenario.funding_stress_multiplier,
        "cost_multiplier": result.scenario.cost_multiplier,
        **result.metrics,
        **{f"distribution_{key}": value for key, value in result.sleeve_distribution.items()},
        "research_decision": _research_decision(result),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    return row


def _research_decision(result: BankrollResult) -> str:
    m = result.metrics
    if bool(m.get("all_sleeves_dead")):
        return "reject_all_sleeves_dead"
    if int(m.get("total_liquidation_count", 0)) > INITIAL_SLEEVE_COUNT:
        return "reject_excessive_liquidations"
    if float(m.get("max_drawdown_abs_pct", 100.0)) > 70.0:
        return "reject_bankroll_drawdown_above_70"
    if float(m.get("total_return_pct", -100.0)) <= 0.0:
        return "reject_non_positive_bankroll_return"
    return "retain_bankroll_rollover_research_watchlist_only"


def _stress_summary(
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    retained = [row for row in rows if row.get("research_decision") == "retain_bankroll_rollover_research_watchlist_only"]
    source = retained[0] if retained else (rows[0] if rows else {})
    if not source:
        return {"rows": []}
    stress_scenarios = [
        BankrollScenario(str(source["scenario_id"]) + "_base", str(source["rollover_policy"]), float(source["leverage"]), 1.0, 1.0),
        BankrollScenario(str(source["scenario_id"]) + "_cost2x", str(source["rollover_policy"]), float(source["leverage"]), 1.0, 2.0),
        BankrollScenario(str(source["scenario_id"]) + "_funding2x", str(source["rollover_policy"]), float(source["leverage"]), 2.0, 1.0),
        BankrollScenario(str(source["scenario_id"]) + "_cost2x_funding2x", str(source["rollover_policy"]), float(source["leverage"]), 2.0, 2.0),
    ]
    stress_rows = []
    for scenario in stress_scenarios:
        result = _simulate_bankroll(
            scenario,
            market=market,
            direction=direction,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        stress_rows.append(_candidate_row(result))
    return {
        "base_source_scenario_id": source.get("scenario_id"),
        "stress_rows": stress_rows,
        "stress_passed": all(row.get("research_decision") == "retain_bankroll_rollover_research_watchlist_only" for row in stress_rows),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _event(*, scenario: BankrollScenario, ts: pd.Timestamp, sleeve: Sleeve, event_type: str, amount: float, note: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "timestamp": _ts(ts),
        "sleeve_id": sleeve.sleeve_id,
        "event_type": event_type,
        "amount": _round(amount),
        "sleeve_equity_after": _round(sleeve.equity),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _event_sample(events: Sequence[Mapping[str, Any]], *, limit: int = 200) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    priority = [event for event in events if event.get("event_type") == "liquidation"]
    for event in list(priority[: limit // 2]) + list(events):
        key = (str(event.get("scenario_id")), str(event.get("timestamp")), int(event.get("sleeve_id", 0) or 0))
        if key in seen:
            continue
        sampled.append(dict(event))
        seen.add(key)
        if len(sampled) >= limit:
            break
    return sampled


def _adverse_move(*, high: pd.Series, low: pd.Series, close: pd.Series, pos: int, side: float) -> float:
    if pos <= 0:
        return 0.0
    prev_close = float(close.iloc[pos - 1])
    if side > 0.0:
        return max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
    return max(0.0, float(high.iloc[pos]) / prev_close - 1.0)


def _warnings(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_bankroll_rollover_lab_research_only_no_paper_no_live"]
    if any(float(row.get("leverage", 0.0)) >= 50.0 for row in rows):
        warnings.append("btc_bankroll_rollover_extreme_leverage_research_stress_only")
    if any(int(row.get("total_liquidation_count", 0)) > 0 for row in rows):
        warnings.append("btc_bankroll_rollover_liquidations_observed")
    return warnings


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Bankroll rollover is a high-risk research-only money-management experiment.",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_bankroll_rollover_lab_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "extreme_leverage_research_only": True,
        "reason": "Rollover sleeve results cannot promote a strategy to paper/live.",
        "blockers": list(report.get("blockers", [])),
    }


def render_btc_bankroll_rollover_lab_markdown(report: Mapping[str, Any]) -> str:
    rows = report.get("candidate_rows", [])
    best = rows[0] if rows else {}
    gate = report.get("gate", {})
    lines = [
        "# BTC 分仓滚仓实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 候选数：`{report.get('experiment_design', {}).get('candidate_count')}`",
        f"- 最佳场景：`{best.get('scenario_id')}`",
        f"- 最佳最终权益：`{best.get('final_equity')}`，总收益 `{best.get('total_return_pct')}`，回撤 `{best.get('max_drawdown_abs_pct')}`",
        f"- 最佳强平次数：`{best.get('total_liquidation_count')}`，死亡 sleeve：`{best.get('dead_sleeve_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论",
        "",
        "这是高风险资金管理研究，不是稳定策略证据。100x 等极端杠杆只作为压力场景，任何候选都不得进入 paper/live。",
    ]
    return "\n".join(lines) + "\n"


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
