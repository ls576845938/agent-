from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_pyramiding_sleeve_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_pyramiding_sleeve_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_grid.csv"
DEFAULT_TOP_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_top_watchlist.csv"
DEFAULT_ATTACK_TOP_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_actual_attack_watchlist.csv"
DEFAULT_EVENT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

ONE_OFF_SPIKE_PCTS = (5.0, 8.0, 10.0, 12.0)
MAINTENANCE_MARGIN_RATE = 0.005
LIQUIDATION_FEE_RATE = 0.003
ROLE_PRIORITY = {"core": 0, "reserve": 1, "attack": 2}


@dataclass(frozen=True)
class PyramidTemplate:
    role: str
    leverage: float
    entry_delay_bars: int
    trigger_atr: float


@dataclass(frozen=True)
class PyramidScenario:
    scenario_id: str
    policy_id: str
    sleeve_templates: tuple[PyramidTemplate, ...]
    max_total_exposed: int
    max_attack_exposed: int
    extract_on_double: bool
    reserve_requires_pullback: bool
    pyramid_step_atr: float


@dataclass
class PyramidSleeve:
    sleeve_id: int
    role: str
    leverage: float
    entry_delay_bars: int
    trigger_atr: float
    equity: float
    basis_equity: float
    reserve_cash: float = 0.0
    status: str = "alive"
    exposed_side: float = 0.0
    liquidation_count: int = 0
    extract_count: int = 0
    pyramid_entry_count: int = 0


@dataclass
class PyramidResult:
    scenario: PyramidScenario
    metrics: dict[str, Any]
    event_rows: list[dict[str, Any]]


def build_btc_pyramiding_sleeve_lab(
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
    top_csv_path = output_dir / DEFAULT_TOP_CSV_PATH.name
    event_csv_path = output_dir / DEFAULT_EVENT_CSV_PATH.name
    attack_top_csv_path = output_dir / DEFAULT_ATTACK_TOP_CSV_PATH.name
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
    bars_4h = market["bars_4h"].reindex(direction.index)

    results: list[PyramidResult] = []
    event_rows: list[dict[str, Any]] = []
    scenarios = _scenario_grid()
    for scenario in scenarios:
        result = _simulate_pyramid_sleeves(
            scenario,
            market=market,
            direction=direction,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        results.append(result)
        event_rows.extend(result.event_rows)

    grid_rows = sorted((_result_row(result) for result in results), key=_rank_key)
    watchlist = [row for row in grid_rows if row["retention_decision"] == "retain_pyramiding_sleeve_research_watchlist_only"]
    actual_attack_watchlist = [row for row in watchlist if bool(row.get("actual_attack_used"))]
    baseline = _find_row(grid_rows, "baseline_no_pyramid_core5x_max5_extract")
    best = watchlist[0] if watchlist else (grid_rows[0] if grid_rows else {})
    best_attack = actual_attack_watchlist[0] if actual_attack_watchlist else {}
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_pyramiding_sleeve_lab_research_only_no_paper_no_live",
        "scope": "atr_favorable_pyramiding_plus_sleeve_spike_defense_research_only",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "frozen Donchian high-yield v3 direction; completed 1h bars resampled to 4h",
        },
        "research_design": {
            "idea": "Turtle-style favorable-move pyramiding: add sleeve exposure only after the existing trend moves by ATR steps.",
            "baseline": "same Donchian direction without ATR trigger-based add-ons",
            "scenario_count": len(grid_rows),
            "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
            "pyramid_step_atr_grid": [0.75, 1.0, 1.5],
            "max_leverage_allowed": 10.0,
            "one_off_spike_pcts": list(ONE_OFF_SPIKE_PCTS),
            "liquidation_model": "isolated sleeve linear perp proxy using completed 4h high/low and explicit adverse spike stress",
            "funding_model": "research approximation from visible derivatives rows; not live settlement evidence",
        },
        "summary": {
            "baseline_scenario_id": baseline.get("scenario_id"),
            "baseline_total_return_pct": baseline.get("total_return_pct"),
            "baseline_min_remaining_after_10pct_spike": baseline.get("min_remaining_capital_pct_after_10pct_spike"),
            "best_scenario_id": best.get("scenario_id"),
            "best_total_return_pct": best.get("total_return_pct"),
            "best_annual_return_pct": best.get("annual_return_pct"),
            "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct"),
            "best_min_remaining_after_10pct_spike": best.get("min_remaining_capital_pct_after_10pct_spike"),
            "watchlist_count": len(watchlist),
            "actual_attack_watchlist_count": len(actual_attack_watchlist),
            "best_actual_attack_scenario_id": best_attack.get("scenario_id"),
            "best_actual_attack_annual_return_pct": best_attack.get("annual_return_pct"),
            "best_actual_attack_max_drawdown_abs_pct": best_attack.get("max_drawdown_abs_pct"),
            "best_actual_attack_min_remaining_after_10pct_spike": best_attack.get("min_remaining_capital_pct_after_10pct_spike"),
            "normal_liquidation_watchlist_count": sum(1 for row in watchlist if int(row.get("normal_liquidation_count", 0)) > 0),
        },
        "baseline_no_pyramid": baseline,
        "top_watchlist": watchlist[:20],
        "top_actual_attack_watchlist": actual_attack_watchlist[:20],
        "grid_rows_sample": grid_rows[:25],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(watchlist=watchlist, blockers=blockers),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_csv_path),
            "top_watchlist_csv": _portable_path(top_csv_path),
            "actual_attack_watchlist_csv": _portable_path(attack_top_csv_path),
            "events_csv": _portable_path(event_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_csv_path, grid_rows)
    _write_csv(top_csv_path, watchlist[:50])
    _write_csv(attack_top_csv_path, actual_attack_watchlist[:50])
    _write_csv(event_csv_path, event_rows[:1000])
    _write_text(markdown_path, render_btc_pyramiding_sleeve_lab_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _scenario_grid() -> list[PyramidScenario]:
    scenarios = [
        PyramidScenario(
            scenario_id="baseline_no_pyramid_core5x_max5_extract",
            policy_id="baseline_no_pyramid",
            sleeve_templates=tuple(PyramidTemplate("core", 5.0, i % 3, 0.0) for i in range(INITIAL_SLEEVE_COUNT)),
            max_total_exposed=5,
            max_attack_exposed=0,
            extract_on_double=True,
            reserve_requires_pullback=False,
            pyramid_step_atr=0.0,
        )
    ]
    for step in (0.75, 1.0, 1.5):
        for core_lev in (3.0, 5.0):
            for core_count in (4, 5, 6):
                for attack_count in (0, 1, 2):
                    for reserve_lev in (3.0, 5.0):
                        for max_total in (3, 5, 7):
                            for extract in (False, True):
                                reserve_count = INITIAL_SLEEVE_COUNT - core_count - attack_count
                                if reserve_count < 1:
                                    continue
                                max_attack = min(1, attack_count)
                                templates: list[PyramidTemplate] = []
                                templates.extend(PyramidTemplate("core", core_lev, i % 3, float(i % 2) * step) for i in range(core_count))
                                templates.extend(PyramidTemplate("reserve", reserve_lev, 6 + (i % 3) * 3, step * (1.0 + (i % 3))) for i in range(reserve_count))
                                templates.extend(PyramidTemplate("attack", 10.0, 9 + i * 3, step * (2.0 + i)) for i in range(attack_count))
                                scenario_id = (
                                    f"pyr_step{str(step).replace('.', 'p')}_core{int(core_lev)}x{core_count}"
                                    f"_reserve{int(reserve_lev)}x{reserve_count}_attack10x{attack_count}"
                                    f"_max{max_total}_{'extract' if extract else 'noextract'}"
                                )
                                scenarios.append(
                                    PyramidScenario(
                                        scenario_id=scenario_id,
                                        policy_id="atr_favorable_pyramiding_sleeve_defense",
                                        sleeve_templates=tuple(templates),
                                        max_total_exposed=max_total,
                                        max_attack_exposed=max_attack,
                                        extract_on_double=extract,
                                        reserve_requires_pullback=True,
                                        pyramid_step_atr=step,
                                    )
                                )
    return scenarios


def _simulate_pyramid_sleeves(
    scenario: PyramidScenario,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> PyramidResult:
    direction = direction.dropna()
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    atr = _atr(bars, 20).reindex(direction.index).ffill().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    sleeves = [
        PyramidSleeve(
            sleeve_id=i + 1,
            role=template.role,
            leverage=template.leverage,
            entry_delay_bars=template.entry_delay_bars,
            trigger_atr=template.trigger_atr,
            equity=sleeve_initial,
            basis_equity=sleeve_initial,
        )
        for i, template in enumerate(scenario.sleeve_templates)
    ]
    equity_curve: list[float] = []
    exposed_count_curve: list[int] = []
    attack_count_curve: list[int] = []
    event_rows: list[dict[str, Any]] = []
    previous_signal = 0.0
    signal_age = 0
    campaign_anchor: float | None = None
    normal_liquidation_count = 0
    max_same_bar_normal_liquidations = 0
    fee_rate = float(base_cost_bps) / 10_000.0
    min_remaining = {shock: 100.0 for shock in ONE_OFF_SPIKE_PCTS}
    max_sleeves_lost = {shock: 0 for shock in ONE_OFF_SPIKE_PCTS}
    max_equity_lost = {shock: 0.0 for shock in ONE_OFF_SPIKE_PCTS}

    for pos, ts in enumerate(direction.index):
        side = float(direction.iloc[pos])
        if side == 0.0:
            signal_age = 0
            campaign_anchor = None
        elif side == previous_signal and campaign_anchor is not None:
            signal_age += 1
        else:
            signal_age = 1
            campaign_anchor = float(close.iloc[pos - 1]) if pos > 0 else float(close.iloc[pos])
        favorable_atr = _favorable_atr(close=float(close.iloc[pos]), anchor=campaign_anchor, side=side, atr=float(atr.iloc[pos]))
        pullback_visible = _pullback_visible(returns=returns, high=high, low=low, close=close, pos=pos, side=side)
        eligible = [
            sleeve
            for sleeve in sleeves
            if sleeve.status == "alive"
            and side != 0.0
            and signal_age > sleeve.entry_delay_bars
            and favorable_atr >= sleeve.trigger_atr
            and (sleeve.role != "reserve" or not scenario.reserve_requires_pullback or pullback_visible)
        ]
        selected_ids = _select_sleeves(eligible, scenario=scenario)
        adverse = _adverse_move(high=high, low=low, close=close, pos=pos, side=side)
        bar_return = 0.0 if pos == 0 else float(returns.iloc[pos])
        normal_liq_this_bar = 0

        for sleeve in sleeves:
            if sleeve.status != "alive":
                sleeve.exposed_side = 0.0
                continue
            should_expose = sleeve.sleeve_id in selected_ids
            if not should_expose:
                sleeve.exposed_side = 0.0
                continue
            if sleeve.exposed_side == 0.0 and sleeve.trigger_atr > 0.0:
                sleeve.pyramid_entry_count += 1
                event_rows.append(_event(scenario=scenario, ts=ts, event_type="pyramid_entry", sleeve=sleeve, amount=sleeve.equity, note=f"favorable_atr={_round(favorable_atr)} trigger_atr={sleeve.trigger_atr}"))
            turnover_cost = fee_rate if sleeve.exposed_side != side else 0.0
            threshold = _liquidation_threshold(sleeve.leverage)
            if adverse >= threshold:
                event_rows.append(_event(scenario=scenario, ts=ts, event_type="normal_liquidation", sleeve=sleeve, amount=sleeve.equity, note=f"adverse={_round(adverse * 100.0)} threshold={_round(threshold * 100.0)}"))
                sleeve.equity = 0.0
                sleeve.status = "liquidated"
                sleeve.exposed_side = 0.0
                sleeve.liquidation_count += 1
                normal_liquidation_count += 1
                normal_liq_this_bar += 1
                continue
            funding_return = -side * sleeve.leverage * float(funding.iloc[pos]) * (4.0 / 8.0)
            sleeve.equity = max(0.0, sleeve.equity * (1.0 + side * sleeve.leverage * bar_return + funding_return - turnover_cost))
            sleeve.exposed_side = side
            if scenario.extract_on_double and sleeve.equity >= sleeve.basis_equity * 2.0:
                extracted = min(sleeve.basis_equity, sleeve.equity)
                sleeve.equity -= extracted
                sleeve.reserve_cash += extracted
                sleeve.basis_equity = max(sleeve.equity, 1e-9)
                sleeve.extract_count += 1
                event_rows.append(_event(scenario=scenario, ts=ts, event_type="extract_principal", sleeve=sleeve, amount=extracted, note="principal protected outside active sleeve"))

        total_equity = _total_equity(sleeves)
        exposed = [sleeve for sleeve in sleeves if sleeve.status == "alive" and sleeve.exposed_side != 0.0]
        for shock in ONE_OFF_SPIKE_PCTS:
            lost_equity = 0.0
            lost_count = 0
            for sleeve in exposed:
                if adverse + shock / 100.0 >= _liquidation_threshold(sleeve.leverage):
                    lost_equity += sleeve.equity
                    lost_count += 1
            remaining_pct = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_remaining[shock] = min(min_remaining[shock], remaining_pct)
            max_sleeves_lost[shock] = max(max_sleeves_lost[shock], lost_count)
            max_equity_lost[shock] = max(max_equity_lost[shock], lost_equity)
        equity_curve.append(total_equity)
        exposed_count_curve.append(len(exposed))
        attack_count_curve.append(sum(1 for sleeve in exposed if sleeve.role == "attack"))
        max_same_bar_normal_liquidations = max(max_same_bar_normal_liquidations, normal_liq_this_bar)
        previous_signal = side

    equity = pd.Series(equity_curve, index=direction.index, dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    final_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((direction.index.max() - direction.index.min()).total_seconds()) / 86_400.0) if len(direction) else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    exposed_series = pd.Series(exposed_count_curve, dtype=float)
    attack_series = pd.Series(attack_count_curve, dtype=float)
    reserve_cash = sum(sleeve.reserve_cash for sleeve in sleeves)
    metrics: dict[str, Any] = {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "reserve_cash": _round(reserve_cash),
        "reserve_cash_pct_of_initial": _round(reserve_cash / float(initial_capital) * 100.0),
        "alive_sleeve_count": sum(1 for sleeve in sleeves if sleeve.status == "alive"),
        "dead_sleeve_count": sum(1 for sleeve in sleeves if sleeve.status != "alive"),
        "normal_liquidation_count": normal_liquidation_count,
        "max_same_bar_normal_liquidations": max_same_bar_normal_liquidations,
        "average_concurrent_exposed_sleeves": _round(float(exposed_series.mean()) if len(exposed_series) else 0.0),
        "max_concurrent_exposed_sleeves_observed": int(exposed_series.max()) if len(exposed_series) else 0,
        "average_attack_exposed_sleeves": _round(float(attack_series.mean()) if len(attack_series) else 0.0),
        "max_attack_exposed_sleeves_observed": int(attack_series.max()) if len(attack_series) else 0,
        "extract_count": sum(sleeve.extract_count for sleeve in sleeves),
        "pyramid_entry_count": sum(sleeve.pyramid_entry_count for sleeve in sleeves),
        "actual_attack_used": bool(attack_series.max() > 0) if len(attack_series) else False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }
    for shock in ONE_OFF_SPIKE_PCTS:
        slug = _shock_slug(shock)
        metrics[f"min_remaining_capital_pct_after_{slug}_spike"] = _round(min_remaining[shock])
        metrics[f"max_sleeves_lost_single_{slug}_spike"] = int(max_sleeves_lost[shock])
        metrics[f"max_equity_lost_single_{slug}_spike"] = _round(max_equity_lost[shock])
    return PyramidResult(scenario=scenario, metrics=metrics, event_rows=event_rows[:300])


def _select_sleeves(eligible: Sequence[PyramidSleeve], *, scenario: PyramidScenario) -> set[int]:
    selected: list[PyramidSleeve] = []
    attack_count = 0
    for sleeve in sorted(eligible, key=lambda item: (ROLE_PRIORITY[item.role], item.trigger_atr, item.entry_delay_bars, item.sleeve_id)):
        if len(selected) >= scenario.max_total_exposed:
            break
        if sleeve.role == "attack" and attack_count >= scenario.max_attack_exposed:
            continue
        selected.append(sleeve)
        if sleeve.role == "attack":
            attack_count += 1
    return {sleeve.sleeve_id for sleeve in selected}


def _result_row(result: PyramidResult) -> dict[str, Any]:
    s = result.scenario
    row = {
        "scenario_id": s.scenario_id,
        "policy_id": s.policy_id,
        "pyramid_step_atr": s.pyramid_step_atr,
        "max_total_exposed": s.max_total_exposed,
        "max_attack_exposed": s.max_attack_exposed,
        "extract_on_double": s.extract_on_double,
        "reserve_requires_pullback": s.reserve_requires_pullback,
        "sleeve_roles": json.dumps([template.role for template in s.sleeve_templates], ensure_ascii=False),
        "sleeve_leverages": json.dumps([template.leverage for template in s.sleeve_templates], ensure_ascii=False),
        "sleeve_trigger_atr": json.dumps([template.trigger_atr for template in s.sleeve_templates], ensure_ascii=False),
        "max_template_leverage": max(template.leverage for template in s.sleeve_templates),
        **result.metrics,
    }
    row["retention_decision"] = _retention_decision(row)
    return row


def _retention_decision(row: Mapping[str, Any]) -> str:
    if float(row.get("max_template_leverage", 0.0)) > 10.0:
        return "reject_leverage_above_10x"
    if int(row.get("normal_liquidation_count", 0)) > 0:
        return "reject_normal_liquidation"
    if float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) < 80.0:
        return "reject_10pct_spike_survival_below_80pct"
    if int(row.get("pyramid_entry_count", 0)) <= 0 and row.get("policy_id") != "baseline_no_pyramid":
        return "reject_no_actual_pyramid_entry"
    if float(row.get("max_drawdown_abs_pct", 999.0)) > 40.0:
        return "reject_drawdown_above_40pct"
    if float(row.get("annual_return_pct", 0.0)) < 45.0:
        return "defer_low_return_for_attack_line"
    return "retain_pyramiding_sleeve_research_watchlist_only"


def _rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, str]:
    retained = 0 if row.get("retention_decision") == "retain_pyramiding_sleeve_research_watchlist_only" else 1
    return (
        retained,
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        -float(row.get("annual_return_pct", 0.0)),
        float(row.get("max_drawdown_abs_pct", 999.0)),
        str(row.get("scenario_id", "")),
    )


def _find_row(rows: Sequence[Mapping[str, Any]], scenario_id: str) -> dict[str, Any]:
    for row in rows:
        if row.get("scenario_id") == scenario_id:
            return dict(row)
    return {}


def render_btc_pyramiding_sleeve_lab_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC Pyramiding Sleeve Lab v1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 场景数：`{report.get('research_design', {}).get('scenario_count')}`",
        f"- 研究观察名单数：`{summary.get('watchlist_count')}`",
        f"- 最佳场景：`{summary.get('best_scenario_id')}`",
        f"- 最佳年化 / 回撤：`{summary.get('best_annual_return_pct')}` / `{summary.get('best_max_drawdown_abs_pct')}`",
        f"- 最佳 -10% 插针后剩余本金：`{summary.get('best_min_remaining_after_10pct_spike')}`%",
        f"- 实际 10x attack 观察名单数：`{summary.get('actual_attack_watchlist_count')}`",
        f"- 最佳实际 10x attack：`{summary.get('best_actual_attack_scenario_id')}`，年化 `{summary.get('best_actual_attack_annual_return_pct')}`，-10% 剩余 `{summary.get('best_actual_attack_min_remaining_after_10pct_spike')}`%",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 口径",
        "",
        "本实验室把 ATR 浮盈阶梯加仓接到已有 Donchian 方向信号上，测试分 sleeve、错峰、提本金和插针剩余本金；它只输出 research-only artifact。",
        "",
        "## Top 10",
        "",
        "| 排名 | 场景 | 年化 | 回撤 | -10%剩余 | pyramid次数 | attack用过 | 结论 |",
        "|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for idx, row in enumerate(report.get("top_watchlist", [])[:10], 1):
        lines.append(
            f"| {idx} | `{row.get('scenario_id')}` | {row.get('annual_return_pct')} | {row.get('max_drawdown_abs_pct')} | "
            f"{row.get('min_remaining_capital_pct_after_10pct_spike')} | {row.get('pyramid_entry_count')} | "
            f"`{row.get('actual_attack_used')}` | `{row.get('retention_decision')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "不写 paper 队列，不解锁 live，不接 broker/OMS。强平、funding 和 mark/index 都是研究近似，不能作为实盘证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _favorable_atr(*, close: float, anchor: float | None, side: float, atr: float) -> float:
    if anchor is None or side == 0.0 or atr <= 0.0:
        return 0.0
    return max(0.0, side * (close - anchor) / atr)


def _pullback_visible(*, returns: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, pos: int, side: float) -> bool:
    if pos <= 1 or side == 0.0:
        return False
    previous_return = float(returns.iloc[pos - 1])
    previous_adverse = _adverse_move(high=high, low=low, close=close, pos=pos - 1, side=side)
    return side * previous_return < 0.0 or previous_adverse >= 0.01


def _adverse_move(*, high: pd.Series, low: pd.Series, close: pd.Series, pos: int, side: float) -> float:
    if pos <= 0 or side == 0.0:
        return 0.0
    prev_close = float(close.iloc[pos - 1])
    if side > 0.0:
        return max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
    return max(0.0, float(high.iloc[pos]) / prev_close - 1.0)


def _liquidation_threshold(leverage: float) -> float:
    return max(0.0, 1.0 / float(leverage) - MAINTENANCE_MARGIN_RATE - LIQUIDATION_FEE_RATE)


def _total_equity(sleeves: Sequence[PyramidSleeve]) -> float:
    return sum(max(0.0, sleeve.equity) + max(0.0, sleeve.reserve_cash) for sleeve in sleeves)


def _atr(bars: pd.DataFrame, window: int) -> pd.Series:
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.shift(1).rolling(int(window), min_periods=max(2, int(window) // 2)).mean()


def _event(*, scenario: PyramidScenario, ts: pd.Timestamp, event_type: str, sleeve: PyramidSleeve, amount: float, note: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "event_time": _ts(ts),
        "event_type": event_type,
        "sleeve_id": sleeve.sleeve_id,
        "role": sleeve.role,
        "leverage": sleeve.leverage,
        "trigger_atr": sleeve.trigger_atr,
        "amount": _round(amount),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Pyramiding sleeve results are research-only capital-management diagnostics.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(*, watchlist: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_pyramiding_sleeve_lab_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_pyramiding_sleeve_lab_blocked")
    if not watchlist:
        warnings.append("btc_pyramiding_sleeve_lab_no_watchlist_candidate")
    warnings.append("btc_pyramiding_sleeve_lab_liquidation_funding_mark_index_are_research_approximations")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_pyramiding_sleeve_lab_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "No paper/live promotion is allowed from pyramiding sleeve artifacts.",
    }


def _shock_slug(shock: float) -> str:
    text = ("%g" % shock).replace(".", "p")
    return f"{text}pct"


def _ts(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat()


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
