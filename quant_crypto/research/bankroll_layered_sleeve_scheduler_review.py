from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.bankroll_spike_defense_review import DEFAULT_REPORT_PATH as DEFAULT_SPIKE_DEFENSE_REPORT_PATH
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_bankroll_layered_sleeve_scheduler_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_bankroll_layered_sleeve_scheduler/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_layered_sleeve_scheduler_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_layered_sleeve_scheduler_grid.csv"
DEFAULT_TOP_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_layered_sleeve_scheduler_top_survivors.csv"
DEFAULT_EVENT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_layered_sleeve_scheduler_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_layered_sleeve_scheduler_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

ONE_OFF_SPIKE_PCTS = (3.0, 5.0, 8.0, 10.0)
MAINTENANCE_MARGIN_RATE = 0.005
LIQUIDATION_FEE_RATE = 0.003
ROLE_PRIORITY = {"core": 0, "reserve": 1, "attack": 2}


@dataclass(frozen=True)
class SleeveTemplate:
    role: str
    leverage: float
    entry_delay_bars: int


@dataclass(frozen=True)
class LayeredScenario:
    scenario_id: str
    policy_id: str
    sleeve_templates: tuple[SleeveTemplate, ...]
    max_total_exposed: int
    max_attack_exposed: int
    extract_on_double: bool
    reserve_requires_pullback: bool = True


@dataclass
class LayeredSleeve:
    sleeve_id: int
    role: str
    leverage: float
    entry_delay_bars: int
    equity: float
    basis_equity: float
    reserve_cash: float = 0.0
    status: str = "alive"
    exposed_side: float = 0.0
    liquidation_count: int = 0
    extract_count: int = 0


@dataclass
class LayeredResult:
    scenario: LayeredScenario
    metrics: dict[str, Any]
    event_rows: list[dict[str, Any]]


def build_btc_bankroll_layered_sleeve_scheduler_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_spike_defense_report_path: Path = DEFAULT_SPIKE_DEFENSE_REPORT_PATH,
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
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    if not source_spike_defense_report_path.exists():
        blockers.append("btc_layered_sleeve_missing_source_spike_defense_report")
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    bars_4h = market["bars_4h"].reindex(direction.index)

    results: list[LayeredResult] = []
    event_rows: list[dict[str, Any]] = []
    scenarios = _scenario_grid()
    for scenario in scenarios:
        result = _simulate_layered_scheduler(
            scenario,
            market=market,
            direction=direction,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        results.append(result)
        event_rows.extend(result.event_rows)

    grid_rows = sorted((_result_row(result) for result in results), key=_rank_key)
    top_rows = grid_rows[:20]
    baseline_all_10x = _find_row(grid_rows, "baseline_all10x_max10_no_extract")
    baseline_all_5x = _find_row(grid_rows, "baseline_all5x_max10_no_extract")
    best = top_rows[0] if top_rows else {}
    summary = _summary(grid_rows=grid_rows, baseline_all_10x=baseline_all_10x, baseline_all_5x=baseline_all_5x, best=best)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "layered_sleeve_scheduler_review_research_only_no_paper_no_live",
        "scope": "core_attack_reserve_sleeve_scheduler_spike_survival_review",
        "code_commit": _git_commit(),
        "input": {
            "source_spike_defense_report_path": _portable_path(source_spike_defense_report_path),
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "frozen high-yield v3 loss-control direction, completed 1h->4h bars",
        },
        "review_design": {
            "objective": "test a layered sleeve scheduler: core exposure first, reserve after visible pullback, attack 10x last and capped",
            "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
            "scenario_count": len(grid_rows),
            "roles": ["core", "reserve", "attack"],
            "max_leverage": max(template.leverage for scenario in scenarios for template in scenario.sleeve_templates),
            "one_off_spike_pcts": list(ONE_OFF_SPIKE_PCTS),
            "reserve_entry_rule": "signal must persist past delay and previous completed 4h bar must be a pullback or >=1pct adverse bar",
            "attack_entry_rule": "signal must persist past delay, total exposure cap must allow it, and max_attack_exposed must not be exceeded",
            "liquidation_model": {
                "model": "isolated_sleeve_linear_perp_4h_high_low_mark_proxy",
                "threshold_formula": "max(0, 1/leverage - maintenance_margin_rate - liquidation_fee_rate)",
                "one_off_spike_survival": "for each bar, hypothetically liquidate currently exposed sleeves whose adverse move plus spike exceeds threshold",
                "promotion_evidence": False,
            },
        },
        "summary": summary,
        "baseline_all_10x": baseline_all_10x,
        "baseline_all_5x": baseline_all_5x,
        "top_survivors": top_rows,
        "grid_rows_sample": grid_rows[:25],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(summary),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_csv_path),
            "top_survivors_csv": _portable_path(top_csv_path),
            "events_csv": _portable_path(event_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_csv_path, grid_rows)
    _write_csv(top_csv_path, top_rows)
    _write_csv(event_csv_path, event_rows[:500])
    _write_text(markdown_path, render_btc_bankroll_layered_sleeve_scheduler_review_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _scenario_grid() -> list[LayeredScenario]:
    scenarios = [
        LayeredScenario(
            scenario_id="baseline_all10x_max10_no_extract",
            policy_id="baseline_all10x",
            sleeve_templates=tuple(SleeveTemplate("attack", 10.0, 0) for _ in range(INITIAL_SLEEVE_COUNT)),
            max_total_exposed=10,
            max_attack_exposed=10,
            extract_on_double=False,
            reserve_requires_pullback=False,
        ),
        LayeredScenario(
            scenario_id="baseline_all5x_max10_no_extract",
            policy_id="baseline_all5x",
            sleeve_templates=tuple(SleeveTemplate("core", 5.0, 0) for _ in range(INITIAL_SLEEVE_COUNT)),
            max_total_exposed=10,
            max_attack_exposed=0,
            extract_on_double=False,
            reserve_requires_pullback=False,
        ),
    ]
    for core_lev in (3.0, 5.0):
        for core_count in (4, 5, 6):
            for attack_count in (1, 2):
                for reserve_lev in (3.0, 5.0):
                    for max_total in (3, 5, 7):
                        for extract in (False, True):
                            reserve_count = INITIAL_SLEEVE_COUNT - core_count - attack_count
                            if reserve_count < 1:
                                continue
                            templates: list[SleeveTemplate] = []
                            templates.extend(SleeveTemplate("core", core_lev, i % 3) for i in range(core_count))
                            templates.extend(SleeveTemplate("reserve", reserve_lev, 6 + (i % 3) * 3) for i in range(reserve_count))
                            templates.extend(SleeveTemplate("attack", 10.0, 3 + i * 3) for i in range(attack_count))
                            scenario_id = (
                                f"layer_core{int(core_lev)}x{core_count}_reserve{int(reserve_lev)}x{reserve_count}"
                                f"_attack10x{attack_count}_max{max_total}_{'extract' if extract else 'noextract'}"
                            )
                            scenarios.append(
                                LayeredScenario(
                                    scenario_id=scenario_id,
                                    policy_id="layered_core_reserve_attack",
                                    sleeve_templates=tuple(templates),
                                    max_total_exposed=max_total,
                                    max_attack_exposed=attack_count,
                                    extract_on_double=extract,
                                )
                            )
    return scenarios


def _simulate_layered_scheduler(
    scenario: LayeredScenario,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> LayeredResult:
    direction = direction.dropna()
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    sleeves = [
        LayeredSleeve(
            sleeve_id=i + 1,
            role=template.role,
            leverage=template.leverage,
            entry_delay_bars=template.entry_delay_bars,
            equity=sleeve_initial,
            basis_equity=sleeve_initial,
        )
        for i, template in enumerate(scenario.sleeve_templates)
    ]
    equity_curve: list[float] = []
    exposed_count_curve: list[int] = []
    attack_exposed_curve: list[int] = []
    event_rows: list[dict[str, Any]] = []
    previous_signal = 0.0
    signal_age = 0
    total_normal_liquidations = 0
    max_same_bar_normal_liquidations = 0
    min_spike_remaining: dict[float, float] = {shock: 100.0 for shock in ONE_OFF_SPIKE_PCTS}
    max_spike_sleeves_lost: dict[float, int] = {shock: 0 for shock in ONE_OFF_SPIKE_PCTS}
    max_spike_equity_lost: dict[float, float] = {shock: 0.0 for shock in ONE_OFF_SPIKE_PCTS}
    fee_slippage_rate = float(base_cost_bps) / 10_000.0

    for pos, ts in enumerate(direction.index):
        side = float(direction.iloc[pos])
        if side == 0.0:
            signal_age = 0
        elif side == previous_signal:
            signal_age += 1
        else:
            signal_age = 1

        pullback_visible = _pullback_visible(returns=returns, high=high, low=low, close=close, pos=pos, side=side)
        eligible = [
            sleeve
            for sleeve in sleeves
            if sleeve.status == "alive"
            and side != 0.0
            and signal_age > sleeve.entry_delay_bars
            and (sleeve.role != "reserve" or not scenario.reserve_requires_pullback or pullback_visible)
        ]
        selected_ids = _select_sleeves(eligible, scenario=scenario)
        normal_liquidations_this_bar = 0
        adverse = _adverse_move(high=high, low=low, close=close, pos=pos, side=side)
        bar_return = 0.0 if pos == 0 else float(returns.iloc[pos])

        for sleeve in sleeves:
            if sleeve.status != "alive":
                sleeve.exposed_side = 0.0
                continue
            should_expose = sleeve.sleeve_id in selected_ids
            turnover_cost = fee_slippage_rate if should_expose and sleeve.exposed_side != side else 0.0
            if not should_expose:
                sleeve.exposed_side = 0.0
                continue
            threshold = _liquidation_threshold(sleeve.leverage)
            if adverse >= threshold:
                event_rows.append(_event(scenario=scenario, ts=ts, event_type="normal_liquidation", sleeve=sleeve, amount=sleeve.equity, note=f"adverse={_round(adverse * 100.0)} threshold={_round(threshold * 100.0)}"))
                sleeve.equity = 0.0
                sleeve.status = "liquidated"
                sleeve.exposed_side = 0.0
                sleeve.liquidation_count += 1
                total_normal_liquidations += 1
                normal_liquidations_this_bar += 1
                continue
            funding_return = -side * sleeve.leverage * float(funding.iloc[pos]) * (4.0 / 8.0)
            sleeve.equity = max(0.0, sleeve.equity * (1.0 + side * sleeve.leverage * bar_return + funding_return - turnover_cost))
            sleeve.exposed_side = side
            if sleeve.equity <= 0.0:
                sleeve.status = "dead"
                total_normal_liquidations += 1
                normal_liquidations_this_bar += 1
                continue
            if scenario.extract_on_double and sleeve.equity >= sleeve.basis_equity * 2.0:
                extracted = min(sleeve.basis_equity, sleeve.equity)
                sleeve.equity -= extracted
                sleeve.reserve_cash += extracted
                sleeve.basis_equity = max(sleeve.equity, 1e-9)
                sleeve.extract_count += 1
                event_rows.append(_event(scenario=scenario, ts=ts, event_type="extract_principal", sleeve=sleeve, amount=extracted, note="principal protected outside active sleeve"))

        total_equity = _total_equity(sleeves)
        exposed_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "alive" and sleeve.exposed_side != 0.0]
        for shock in ONE_OFF_SPIKE_PCTS:
            lost_equity = 0.0
            lost_count = 0
            for sleeve in exposed_sleeves:
                if adverse + shock / 100.0 >= _liquidation_threshold(sleeve.leverage):
                    lost_equity += sleeve.equity
                    lost_count += 1
            remaining_pct = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_spike_remaining[shock] = min(min_spike_remaining[shock], remaining_pct)
            max_spike_sleeves_lost[shock] = max(max_spike_sleeves_lost[shock], lost_count)
            max_spike_equity_lost[shock] = max(max_spike_equity_lost[shock], lost_equity)

        max_same_bar_normal_liquidations = max(max_same_bar_normal_liquidations, normal_liquidations_this_bar)
        equity_curve.append(total_equity)
        exposed_count_curve.append(len(exposed_sleeves))
        attack_exposed_curve.append(sum(1 for sleeve in exposed_sleeves if sleeve.role == "attack"))
        previous_signal = side

    equity = pd.Series(equity_curve, index=direction.index, dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    final_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((direction.index.max() - direction.index.min()).total_seconds()) / 86_400.0) if len(direction) else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    alive_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "alive"]
    reserve_cash = sum(sleeve.reserve_cash for sleeve in sleeves)
    exposed_series = pd.Series(exposed_count_curve)
    attack_series = pd.Series(attack_exposed_curve)
    metrics: dict[str, Any] = {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "reserve_cash": _round(reserve_cash),
        "reserve_cash_pct_of_initial": _round(reserve_cash / float(initial_capital) * 100.0),
        "alive_sleeve_count": len(alive_sleeves),
        "dead_sleeve_count": len(sleeves) - len(alive_sleeves),
        "normal_liquidation_count": total_normal_liquidations,
        "max_same_bar_normal_liquidations": max_same_bar_normal_liquidations,
        "average_concurrent_exposed_sleeves": _round(float(exposed_series.mean()) if len(exposed_series) else 0.0),
        "max_concurrent_exposed_sleeves_observed": int(exposed_series.max()) if len(exposed_series) else 0,
        "average_attack_exposed_sleeves": _round(float(attack_series.mean()) if len(attack_series) else 0.0),
        "max_attack_exposed_sleeves_observed": int(attack_series.max()) if len(attack_series) else 0,
        "extract_count": sum(sleeve.extract_count for sleeve in sleeves),
        "core_sleeve_count": sum(1 for sleeve in sleeves if sleeve.role == "core"),
        "reserve_sleeve_count": sum(1 for sleeve in sleeves if sleeve.role == "reserve"),
        "attack_sleeve_count": sum(1 for sleeve in sleeves if sleeve.role == "attack"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    for shock in ONE_OFF_SPIKE_PCTS:
        slug = _shock_slug(shock)
        metrics[f"min_remaining_capital_pct_after_{slug}_spike"] = _round(min_spike_remaining[shock])
        metrics[f"max_sleeves_lost_single_{slug}_spike"] = int(max_spike_sleeves_lost[shock])
        metrics[f"max_equity_lost_single_{slug}_spike"] = _round(max_spike_equity_lost[shock])
    return LayeredResult(scenario=scenario, metrics=metrics, event_rows=event_rows[:200])


def _select_sleeves(eligible: Sequence[LayeredSleeve], *, scenario: LayeredScenario) -> set[int]:
    selected: list[LayeredSleeve] = []
    attack_count = 0
    for sleeve in sorted(eligible, key=lambda item: (ROLE_PRIORITY[item.role], item.entry_delay_bars, item.sleeve_id)):
        if len(selected) >= scenario.max_total_exposed:
            break
        if sleeve.role == "attack" and attack_count >= scenario.max_attack_exposed:
            continue
        selected.append(sleeve)
        if sleeve.role == "attack":
            attack_count += 1
    return {sleeve.sleeve_id for sleeve in selected}


def _pullback_visible(*, returns: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, pos: int, side: float) -> bool:
    if pos <= 1 or side == 0.0:
        return False
    previous_return = float(returns.iloc[pos - 1])
    previous_adverse = _adverse_move(high=high, low=low, close=close, pos=pos - 1, side=side)
    return side * previous_return < 0.0 or previous_adverse >= 0.01


def _result_row(result: LayeredResult) -> dict[str, Any]:
    s = result.scenario
    return {
        "scenario_id": s.scenario_id,
        "policy_id": s.policy_id,
        "max_total_exposed": s.max_total_exposed,
        "max_attack_exposed": s.max_attack_exposed,
        "extract_on_double": s.extract_on_double,
        "reserve_requires_pullback": s.reserve_requires_pullback,
        "sleeve_roles": json.dumps([template.role for template in s.sleeve_templates], ensure_ascii=False),
        "sleeve_leverages": json.dumps([template.leverage for template in s.sleeve_templates], ensure_ascii=False),
        "sleeve_entry_delay_bars": json.dumps([template.entry_delay_bars for template in s.sleeve_templates], ensure_ascii=False),
        **result.metrics,
    }


def _rank_key(row: Mapping[str, Any]) -> tuple[float, float, float, float, str]:
    return (
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        int(row.get("normal_liquidation_count", 999)),
        float(row.get("max_drawdown_abs_pct", 999.0)),
        -float(row.get("total_return_pct", -999.0)),
        str(row.get("scenario_id")),
    )


def _summary(
    *,
    grid_rows: Sequence[Mapping[str, Any]],
    baseline_all_10x: Mapping[str, Any],
    baseline_all_5x: Mapping[str, Any],
    best: Mapping[str, Any],
) -> dict[str, Any]:
    layered_rows = [row for row in grid_rows if row.get("policy_id") == "layered_core_reserve_attack"]
    best_layered = _best_where(layered_rows, lambda row: True)
    best_extract = _best_where(layered_rows, lambda row: bool(row.get("extract_on_double")))
    best_10x_attack = _best_where(layered_rows, lambda row: int(row.get("max_attack_exposed_sleeves_observed", 0)) > 0)
    retained = [
        row
        for row in layered_rows
        if float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) >= 70.0
        and float(row.get("total_return_pct", -100.0)) > 0.0
        and int(row.get("normal_liquidation_count", 0)) == 0
        and int(row.get("max_attack_exposed_sleeves_observed", 0)) <= 2
    ]
    return {
        "scenario_count": len(grid_rows),
        "layered_scenario_count": len(layered_rows),
        "baseline_all_10x_min_remaining_capital_pct_after_10pct_spike": baseline_all_10x.get("min_remaining_capital_pct_after_10pct_spike"),
        "baseline_all_10x_total_return_pct": baseline_all_10x.get("total_return_pct"),
        "baseline_all_5x_min_remaining_capital_pct_after_10pct_spike": baseline_all_5x.get("min_remaining_capital_pct_after_10pct_spike"),
        "baseline_all_5x_total_return_pct": baseline_all_5x.get("total_return_pct"),
        "best_scenario_id": best.get("scenario_id"),
        "best_min_remaining_capital_pct_after_10pct_spike": best.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_total_return_pct": best.get("total_return_pct"),
        "best_layered_scenario_id": best_layered.get("scenario_id"),
        "best_layered_min_remaining_capital_pct_after_10pct_spike": best_layered.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_layered_total_return_pct": best_layered.get("total_return_pct"),
        "best_extract_scenario_id": best_extract.get("scenario_id"),
        "best_extract_min_remaining_capital_pct_after_10pct_spike": best_extract.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_extract_total_return_pct": best_extract.get("total_return_pct"),
        "best_10x_attack_scenario_id": best_10x_attack.get("scenario_id"),
        "best_10x_attack_min_remaining_capital_pct_after_10pct_spike": best_10x_attack.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_10x_attack_total_return_pct": best_10x_attack.get("total_return_pct"),
        "best_10x_attack_max_attack_exposed_sleeves_observed": best_10x_attack.get("max_attack_exposed_sleeves_observed"),
        "best_10x_attack_average_attack_exposed_sleeves": best_10x_attack.get("average_attack_exposed_sleeves"),
        "research_watchlist_count": len(retained),
        "primary_lesson": "layered_scheduler_trades_return_for_spike_survival",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _best_where(rows: Sequence[Mapping[str, Any]], predicate: Callable[[Mapping[str, Any]], bool]) -> dict[str, Any]:
    selected = [row for row in rows if predicate(row)]
    return dict(sorted(selected, key=_rank_key)[0]) if selected else {}


def _find_row(rows: Sequence[Mapping[str, Any]], scenario_id: str) -> dict[str, Any]:
    for row in rows:
        if row.get("scenario_id") == scenario_id:
            return dict(row)
    return {}


def _adverse_move(*, high: pd.Series, low: pd.Series, close: pd.Series, pos: int, side: float) -> float:
    if pos <= 0 or side == 0.0:
        return 0.0
    prev_close = float(close.iloc[pos - 1])
    if side > 0.0:
        return max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
    return max(0.0, float(high.iloc[pos]) / prev_close - 1.0)


def _liquidation_threshold(leverage: float) -> float:
    return max(0.0, 1.0 / float(leverage) - MAINTENANCE_MARGIN_RATE - LIQUIDATION_FEE_RATE)


def _total_equity(sleeves: Sequence[LayeredSleeve]) -> float:
    protected_cash = sum(max(0.0, sleeve.reserve_cash) for sleeve in sleeves)
    live_equity = sum(max(0.0, sleeve.equity) for sleeve in sleeves if sleeve.status == "alive")
    return protected_cash + live_equity


def _event(*, scenario: LayeredScenario, ts: pd.Timestamp, event_type: str, sleeve: LayeredSleeve, amount: float, note: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "timestamp": _ts(ts),
        "event_type": event_type,
        "sleeve_id": sleeve.sleeve_id,
        "role": sleeve.role,
        "leverage": sleeve.leverage,
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
        "reason": "Layered sleeve scheduler review is research-only and cannot promote paper/live.",
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
        "hundred_x_review_candidate_allowed": False,
    }


def _warnings(summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_bankroll_layered_sleeve_scheduler_review_research_only_no_paper_no_live"]
    if float(summary.get("baseline_all_10x_min_remaining_capital_pct_after_10pct_spike", 0.0) or 0.0) <= 0.0:
        warnings.append("btc_layered_sleeve_baseline_10x_all_at_once_can_wipe_out")
    if int(summary.get("research_watchlist_count", 0)) == 0:
        warnings.append("btc_layered_sleeve_no_research_watchlist")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_bankroll_layered_sleeve_scheduler_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "hundred_x_review_candidate_allowed": False,
        "reason": "Layered sleeve scheduler review cannot promote a strategy to paper/live.",
        "blockers": list(report.get("blockers", [])),
    }


def render_btc_bankroll_layered_sleeve_scheduler_review_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 分层 sleeve 调度器复核",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 场景数：`{summary.get('scenario_count')}`",
        f"- 10x 同时满仓基线 -10% 插针剩余：`{summary.get('baseline_all_10x_min_remaining_capital_pct_after_10pct_spike')}`%",
        f"- 5x 同时满仓基线 -10% 插针剩余：`{summary.get('baseline_all_5x_min_remaining_capital_pct_after_10pct_spike')}`%",
        f"- 最佳分层方案：`{summary.get('best_layered_scenario_id')}`",
        f"- 最佳分层 -10% 插针剩余：`{summary.get('best_layered_min_remaining_capital_pct_after_10pct_spike')}`%",
        f"- 最佳分层总收益：`{summary.get('best_layered_total_return_pct')}`%",
        f"- 实际使用 10x attack 的最佳方案：`{summary.get('best_10x_attack_scenario_id')}`，-10% 插针剩余 `{summary.get('best_10x_attack_min_remaining_capital_pct_after_10pct_spike')}`%",
        f"- 最佳提本金方案：`{summary.get('best_extract_scenario_id')}`",
        f"- 研究观察名单数量：`{summary.get('research_watchlist_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 口径",
        "",
        "本复核包评价 core / reserve / attack 三层 sleeve 调度，不生成策略骨架，不进入 paper/live。",
    ]
    return "\n".join(lines) + "\n"


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


def _ts(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _shock_slug(shock: float) -> str:
    return f"{int(shock)}pct"
