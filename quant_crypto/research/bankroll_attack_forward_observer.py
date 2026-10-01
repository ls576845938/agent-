from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_attack_top_confirmation_review import (
    DEFAULT_REPORT_PATH as DEFAULT_TOP_CONFIRMATION_REPORT_PATH,
    MIN_REMAINING_AFTER_10PCT_SPIKE,
    TOP_SCENARIO_ID,
    StressPolicy,
    _default_top_scenario,
    _funding_cost_stress_policies,
    _liquidation_threshold,
    _simulate_stress,
)
from quant_crypto.research.btc_confirmatory_holdout_lock import DEFAULT_LOCK_CONFIG_PATH
from quant_crypto.research.btc_observe_only_lock import (
    holdout_lock_blockers,
    observation_row_lock_stamp,
    observe_only_lock_status,
    read_holdout_lock_config,
)
from quant_crypto.research.bankroll_layered_sleeve_scheduler_review import (
    LayeredScenario,
    LayeredSleeve,
    _adverse_move,
    _pullback_visible,
    _select_sleeves,
    _total_equity,
    _ts,
)
from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_bankroll_attack_forward_observer_v1"
OBSERVATION_ROW_SCHEMA_VERSION = "btc_bankroll_attack_forward_observation_row_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_bankroll_attack_forward_observer/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_forward_observer_report.json"
DEFAULT_OBSERVATION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_forward_observations_latest.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_forward_observer_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_OBSERVATION_LEDGER_PATH = Path("data/forward_observation/btc_bankroll_attack_top/observations.jsonl")
OBSERVER_ID = "btc_bankroll_attack_top_10x_observe_only_v1"


def run_btc_bankroll_attack_forward_observer(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_top_confirmation_report_path: Path = DEFAULT_TOP_CONFIRMATION_REPORT_PATH,
    observation_ledger_path: Path = DEFAULT_OBSERVATION_LEDGER_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    holdout_lock_path: Path = DEFAULT_LOCK_CONFIG_PATH,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    observation_csv_path = output_dir / DEFAULT_OBSERVATION_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    source = _source_confirmation_context(source_top_confirmation_report_path)
    blockers = _source_blockers(source)
    holdout_lock_config, holdout_lock_load_blockers = read_holdout_lock_config(holdout_lock_path)
    blockers.extend(holdout_lock_load_blockers)
    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers.extend(str(item) for item in market.get("blockers", []))
    scenario = _default_top_scenario()
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    bars_4h = market["bars_4h"].reindex(direction.index)

    observation_row: dict[str, Any] | None = None
    existing: list[dict[str, Any]] = _read_jsonl(observation_ledger_path)
    new_observation_written = False
    already_processed = False
    stress_summary: dict[str, Any] = {}
    holdout_lock: dict[str, Any] = {}
    if not blockers:
        observation_row = _daily_observation_row(
            scenario=scenario,
            market=market,
            direction=direction,
            generated_at_utc=generated,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
            source=source,
        )
        holdout_lock = observe_only_lock_status(
            lock_config=holdout_lock_config,
            decision_times=[observation_row.get("decision_time")],
            observer_id=OBSERVER_ID,
            holdout_lock_path=holdout_lock_path,
        )
        blockers.extend(holdout_lock_blockers(holdout_lock))
        observation_row["holdout_lock"] = observation_row_lock_stamp(holdout_lock, observation_row.get("decision_time"))
        already_processed = any(
            row.get("observer_id") == OBSERVER_ID and row.get("decision_time") == observation_row.get("decision_time")
            for row in existing
        )
        if not already_processed and not blockers:
            observation_ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with observation_ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(observation_row, ensure_ascii=False, sort_keys=True) + "\n")
            existing.append(observation_row)
            new_observation_written = True
        stress_summary = _stress_summary(scenario=scenario, market=market, direction=direction, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    else:
        holdout_lock = observe_only_lock_status(
            lock_config=holdout_lock_config,
            decision_times=[],
            observer_id=OBSERVER_ID,
            holdout_lock_path=holdout_lock_path,
        )

    observer_rows = [row for row in existing if row.get("observer_id") == OBSERVER_ID]
    _write_csv(observation_csv_path, observer_rows[-60:])
    progress = _observation_progress(observer_rows)
    decision = _decision(blockers=blockers, progress=progress, latest_row=observation_row)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "daily_observe_only_for_btc_actual_10x_attack_top_scheme",
        "code_commit": _git_commit(),
        "input": {
            "source_top_confirmation_report_path": _portable_path(source_top_confirmation_report_path),
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "observation_ledger_path": _portable_path(observation_ledger_path),
            "holdout_lock_path": _portable_path(holdout_lock_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
        },
        "source_confirmation": source,
        "observer_design": {
            "observer_id": OBSERVER_ID,
            "top_scenario_id": scenario.scenario_id,
            "recommended_frequency": "daily_after_latest_4h_bar_is_complete",
            "writes_order_intent": False,
            "writes_paper_queue": False,
            "unlocks_live": False,
            "holdout_lock_enforced": True,
            "observe_only_purpose": holdout_lock.get("observe_only_purpose"),
            "forbidden_selection_purposes": holdout_lock.get("selection_forbidden_purposes_checked", []),
            "recorded_fields": [
                "daily_signal",
                "theoretical_sleeve_exposure",
                "spike_remaining_capital",
                "funding_cost_pressure",
                "downgrade_triggered",
            ],
            "minimum_remaining_capital_pct_after_10pct_spike": MIN_REMAINING_AFTER_10PCT_SPIKE,
            "funding_model": "research approximation from visible derivatives rows; not live funding settlement evidence",
            "mark_index_model": "4h OHLCV adverse move plus explicit mark/index offset stress; not exchange mark/index replay",
        },
        "holdout_lock": holdout_lock,
        "latest_observation": observation_row or {},
        "observation_automation": {
            "new_observation_written": new_observation_written,
            "already_processed": already_processed,
            "observation_count": len(observer_rows),
            "latest_decision_time": (observation_row or {}).get("decision_time"),
            "observation_ledger_path": _portable_path(observation_ledger_path),
            "observation_csv_path": _portable_path(observation_csv_path),
        },
        "observation_progress": progress,
        "stress_summary": stress_summary,
        "gate": _gate(progress=progress),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, latest_row=observation_row, progress=progress, holdout_lock=holdout_lock),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "observation_csv": _portable_path(observation_csv_path),
            "observation_ledger_jsonl": _portable_path(observation_ledger_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_bankroll_attack_forward_observer_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _daily_observation_row(
    *,
    scenario: LayeredScenario,
    market: Mapping[str, Any],
    direction: pd.Series,
    generated_at_utc: datetime,
    initial_capital: float,
    base_cost_bps: float,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    state = _simulate_current_state(
        scenario=scenario,
        market=market,
        direction=direction,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    latest_ts = state["decision_time"]
    exposed = state["exposed_sleeves"]
    downgrade_reasons = _downgrade_reasons(state=state, source=source)
    caution_reasons = _caution_reasons(state=state, source=source)
    return {
        "schema_version": OBSERVATION_ROW_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc.astimezone(timezone.utc).isoformat(),
        "observer_id": OBSERVER_ID,
        "top_scenario_id": scenario.scenario_id,
        "decision_time": _ts(latest_ts),
        "latest_completed_bar_rule": "4h bar derived from completed 1h bars",
        "daily_signal": {
            "side": _side_label(float(state["side"])),
            "signal_value": _round(float(state["side"])),
            "signal_age_4h_bars": int(state["signal_age"]),
        },
        "theoretical_sleeve_exposure": {
            "exposed_sleeve_count": len(exposed),
            "attack_exposed_sleeve_count": sum(1 for item in exposed if item["role"] == "attack"),
            "max_total_exposed": scenario.max_total_exposed,
            "max_attack_exposed": scenario.max_attack_exposed,
            "gross_leverage_sum": _round(sum(float(item["leverage"]) for item in exposed)),
            "exposed_sleeves": exposed,
        },
        "spike_remaining_capital": {
            "current_adverse_move_pct": _round(float(state["adverse_move_pct"])),
            "remaining_after_5pct_spike_pct": _round(float(state["remaining_after_5pct_spike_pct"])),
            "remaining_after_10pct_spike_pct": _round(float(state["remaining_after_10pct_spike_pct"])),
            "remaining_after_12pct_spike_pct": _round(float(state["remaining_after_12pct_spike_pct"])),
            "max_sleeves_lost_after_10pct_spike": int(state["sleeves_lost_after_10pct_spike"]),
            "mark_index_stress_model": "research_4h_high_low_plus_spike_not_exchange_replay",
        },
        "funding_cost_pressure": {
            "funding_rate": _round(float(state["funding_rate"]), 10),
            "latest_bar_funding_cost_amount": _round(float(state["latest_bar_funding_cost_amount"])),
            "latest_bar_funding_cost_5x_amount": _round(float(state["latest_bar_funding_cost_5x_amount"])),
            "latest_bar_trading_cost_amount": _round(float(state["latest_bar_trading_cost_amount"])),
            "latest_bar_trading_cost_5x_amount": _round(float(state["latest_bar_trading_cost_5x_amount"])),
            "funding_approximation": True,
            "cost_bps_base": base_cost_bps,
        },
        "equity_snapshot": {
            "theoretical_total_equity": _round(float(state["total_equity"])),
            "normal_liquidation_count_to_date": int(state["normal_liquidation_count"]),
            "max_drawdown_abs_pct_to_date": _round(float(state["max_drawdown_abs_pct"])),
        },
        "downgrade_triggered": bool(downgrade_reasons),
        "downgrade_reasons": downgrade_reasons,
        "caution_reasons": caution_reasons,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _simulate_current_state(
    *,
    scenario: LayeredScenario,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
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
    previous_signal = 0.0
    signal_age = 0
    normal_liquidation_count = 0
    equity_curve: list[float] = []
    latest_payload: dict[str, Any] = {}
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
        adverse = _adverse_move(high=high, low=low, close=close, pos=pos, side=side)
        bar_return = 0.0 if pos == 0 else float(returns.iloc[pos])
        latest_funding_cost = 0.0
        latest_funding_cost_5x = 0.0
        latest_trading_cost = 0.0
        latest_trading_cost_5x = 0.0

        for sleeve in sleeves:
            if sleeve.status != "alive":
                sleeve.exposed_side = 0.0
                continue
            should_expose = sleeve.sleeve_id in selected_ids
            turnover_cost = fee_slippage_rate if should_expose and sleeve.exposed_side != side else 0.0
            if not should_expose:
                sleeve.exposed_side = 0.0
                continue
            threshold = _liquidation_threshold(sleeve.leverage, maintenance_margin_rate=0.005, liquidation_fee_rate=0.003)
            if adverse >= threshold:
                sleeve.equity = 0.0
                sleeve.status = "liquidated"
                sleeve.exposed_side = 0.0
                sleeve.liquidation_count += 1
                normal_liquidation_count += 1
                continue
            before_equity = sleeve.equity
            funding_rate = float(funding.iloc[pos])
            funding_return = -side * sleeve.leverage * funding_rate * (4.0 / 8.0)
            funding_return_5x = funding_return - sleeve.leverage * abs(funding_rate) * (4.0 / 8.0) * 4.0
            if funding_return < 0.0:
                latest_funding_cost += before_equity * abs(funding_return)
            if funding_return_5x < 0.0:
                latest_funding_cost_5x += before_equity * abs(funding_return_5x)
            if turnover_cost > 0.0:
                latest_trading_cost += before_equity * turnover_cost
                latest_trading_cost_5x += before_equity * turnover_cost * 5.0
            sleeve.equity = max(0.0, sleeve.equity * (1.0 + side * sleeve.leverage * bar_return + funding_return - turnover_cost))
            sleeve.exposed_side = side

        total_equity = _total_equity(sleeves)
        equity_curve.append(total_equity)
        exposed_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "alive" and sleeve.exposed_side != 0.0]
        remaining_5, lost_5 = _remaining_after_spike(total_equity=total_equity, exposed_sleeves=exposed_sleeves, adverse=adverse, spike_pct=5.0)
        remaining_10, lost_10 = _remaining_after_spike(total_equity=total_equity, exposed_sleeves=exposed_sleeves, adverse=adverse, spike_pct=10.0)
        remaining_12, _ = _remaining_after_spike(total_equity=total_equity, exposed_sleeves=exposed_sleeves, adverse=adverse, spike_pct=12.0)
        drawdown = pd.Series(equity_curve, dtype=float) / pd.Series(equity_curve, dtype=float).cummax() - 1.0
        latest_payload = {
            "decision_time": ts,
            "side": side,
            "signal_age": signal_age,
            "funding_rate": float(funding.iloc[pos]),
            "adverse_move_pct": adverse * 100.0,
            "remaining_after_5pct_spike_pct": remaining_5,
            "remaining_after_10pct_spike_pct": remaining_10,
            "remaining_after_12pct_spike_pct": remaining_12,
            "sleeves_lost_after_5pct_spike": lost_5,
            "sleeves_lost_after_10pct_spike": lost_10,
            "latest_bar_funding_cost_amount": latest_funding_cost,
            "latest_bar_funding_cost_5x_amount": latest_funding_cost_5x,
            "latest_bar_trading_cost_amount": latest_trading_cost,
            "latest_bar_trading_cost_5x_amount": latest_trading_cost_5x,
            "total_equity": total_equity,
            "normal_liquidation_count": normal_liquidation_count,
            "max_drawdown_abs_pct": abs(float(drawdown.min())) * 100.0 if len(drawdown) else 0.0,
            "exposed_sleeves": [
                {
                    "sleeve_id": sleeve.sleeve_id,
                    "role": sleeve.role,
                    "leverage": sleeve.leverage,
                    "entry_delay_bars": sleeve.entry_delay_bars,
                    "equity": _round(sleeve.equity),
                }
                for sleeve in exposed_sleeves
            ],
        }
        previous_signal = side
    return latest_payload


def _stress_summary(
    *,
    scenario: LayeredScenario,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    base = _simulate_stress(
        scenario,
        market=market,
        direction=direction,
        policy=StressPolicy(policy_id="observer_base_10pct_spike", stress_type="observer_base", one_off_adverse_spike_pct=10.0),
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    ).metrics
    stress_rows = []
    for policy in _funding_cost_stress_policies():
        if float(policy.funding_adverse_multiplier) == 5.0 and float(policy.cost_multiplier) == 5.0:
            stress_rows.append(
                _simulate_stress(
                    scenario,
                    market=market,
                    direction=direction,
                    policy=policy,
                    initial_capital=initial_capital,
                    base_cost_bps=base_cost_bps,
                ).metrics
            )
    worst = stress_rows[0] if stress_rows else {}
    return {
        "base_total_return_pct": base.get("total_return_pct"),
        "base_min_remaining_capital_pct_after_10pct_spike": base.get("min_remaining_capital_pct_after_policy_spike"),
        "base_normal_liquidation_count": base.get("normal_liquidation_count"),
        "funding5x_cost5x_total_return_pct": worst.get("total_return_pct"),
        "funding5x_cost5x_min_remaining_capital_pct_after_10pct_spike": worst.get("min_remaining_capital_pct_after_policy_spike"),
        "funding5x_cost5x_normal_liquidation_count": worst.get("normal_liquidation_count"),
    }


def _remaining_after_spike(*, total_equity: float, exposed_sleeves: Sequence[LayeredSleeve], adverse: float, spike_pct: float) -> tuple[float, int]:
    lost_equity = 0.0
    lost_count = 0
    for sleeve in exposed_sleeves:
        threshold = _liquidation_threshold(sleeve.leverage, maintenance_margin_rate=0.005, liquidation_fee_rate=0.003)
        if adverse + spike_pct / 100.0 >= threshold:
            lost_equity += sleeve.equity
            lost_count += 1
    remaining_pct = (float(total_equity) - lost_equity) / max(1e-9, float(total_equity)) * 100.0
    return _round(remaining_pct), lost_count


def _downgrade_reasons(*, state: Mapping[str, Any], source: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not bool(source.get("forward_observation_research_only_allowed")):
        reasons.append("source_confirmation_not_forward_observation_allowed")
    if int(state.get("normal_liquidation_count", 0)) > 0:
        reasons.append("normal_liquidation_observed_in_theoretical_path")
    if float(state.get("remaining_after_10pct_spike_pct", 0.0)) < MIN_REMAINING_AFTER_10PCT_SPIKE:
        reasons.append("current_10pct_spike_remaining_below_80pct")
    if float(state.get("total_equity", 0.0)) <= 0.0:
        reasons.append("theoretical_total_equity_wiped_out")
    return reasons


def _caution_reasons(*, state: Mapping[str, Any], source: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if float(state.get("remaining_after_12pct_spike_pct", 100.0)) < MIN_REMAINING_AFTER_10PCT_SPIKE:
        reasons.append("current_12pct_spike_remaining_below_80pct")
    if "btc_attack_top_confirmation_extreme_mark_spike_can_destroy_most_capital" in source.get("warnings", []):
        reasons.append("source_confirmation_extreme_mark_spike_can_destroy_most_capital")
    if not state.get("exposed_sleeves"):
        reasons.append("no_current_theoretical_exposure")
    return reasons


def _source_confirmation_context(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": _portable_path(path), "exists": False}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": _portable_path(path), "exists": False, "read_error": True}
    gate = report.get("gate", {})
    summary = report.get("summary", {})
    decision = report.get("forward_observation_decision", {})
    return {
        "path": _portable_path(path),
        "exists": True,
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "top_scenario_id": summary.get("top_scenario_id"),
        "forward_observation_research_only_allowed": bool(gate.get("forward_observation_research_only_allowed")),
        "paper_queue_write_allowed": bool(gate.get("paper_queue_write_allowed")),
        "live_unlock_allowed": bool(gate.get("live_unlock_allowed")),
        "decision_reason": decision.get("reason"),
        "warnings": list(report.get("warnings", [])),
    }


def _source_blockers(source: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not source.get("exists"):
        blockers.append("btc_attack_forward_observer_missing_top_confirmation_report")
    if source.get("top_scenario_id") not in {None, TOP_SCENARIO_ID}:
        blockers.append("btc_attack_forward_observer_top_scenario_mismatch")
    if not source.get("forward_observation_research_only_allowed"):
        blockers.append("btc_attack_forward_observer_source_not_observation_allowed")
    if source.get("paper_queue_write_allowed") or source.get("live_unlock_allowed"):
        blockers.append("btc_attack_forward_observer_source_boundary_invalid")
    return blockers


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _observation_progress(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("decision_time", "")))
    first = ordered[0].get("decision_time") if ordered else None
    latest = ordered[-1].get("decision_time") if ordered else None
    calendar_span_days = 0
    if first and latest:
        start = pd.Timestamp(first)
        end = pd.Timestamp(latest)
        calendar_span_days = max(1, int((end - start).total_seconds() // 86_400) + 1)
    observation_dates = sorted(
        {
            str(row.get("decision_time", ""))[:10]
            for row in ordered
            if isinstance(row.get("decision_time"), str) and len(str(row.get("decision_time"))) >= 10
        }
    )
    observation_days = len(observation_dates)
    downgrade_count = sum(1 for row in ordered if bool(row.get("downgrade_triggered")))
    return {
        "observation_count": len(ordered),
        "first_decision_time": first,
        "latest_decision_time": latest,
        "observation_days": observation_days,
        "unique_observation_days": observation_days,
        "calendar_span_days": calendar_span_days,
        "minimum_30d_complete": observation_days >= 30,
        "minimum_60d_complete": observation_days >= 60,
        "downgrade_count": downgrade_count,
        "latest_downgrade_triggered": bool(ordered[-1].get("downgrade_triggered")) if ordered else False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _decision(*, blockers: Sequence[str], progress: Mapping[str, Any], latest_row: Mapping[str, Any] | None) -> str:
    if blockers:
        return "attack_forward_observer_blocked_no_write_no_paper_no_live"
    if latest_row and bool(latest_row.get("downgrade_triggered")):
        return "attack_forward_observer_downgraded_research_only_no_paper_no_live"
    if bool(progress.get("minimum_60d_complete")):
        return "attack_forward_observer_60d_ready_for_manual_review_no_paper_no_live"
    if bool(progress.get("minimum_30d_complete")):
        return "attack_forward_observer_30d_reached_continue_to_60d_no_paper_no_live"
    return "attack_forward_observer_active_under_30d_no_paper_no_live"


def _gate(*, progress: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "forward_observation_only": True,
        "minimum_30d_complete": bool(progress.get("minimum_30d_complete")),
        "minimum_60d_complete": bool(progress.get("minimum_60d_complete")),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Observer records research-only theoretical state and cannot promote paper/live.",
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
        "strategy_skeleton_generated": False,
    }


def _warnings(*, blockers: Sequence[str], latest_row: Mapping[str, Any] | None, progress: Mapping[str, Any], holdout_lock: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_attack_forward_observer_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_attack_forward_observer_blocked")
    if latest_row and bool(latest_row.get("downgrade_triggered")):
        warnings.append("btc_attack_forward_observer_latest_row_downgraded")
    if not bool(progress.get("minimum_30d_complete")):
        warnings.append("btc_attack_forward_observer_less_than_30_days")
    warnings.extend(str(item) for item in holdout_lock.get("warnings", []))
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = report.get("gate", {})
    holdout_lock = report.get("holdout_lock", {})
    return {
        "schema_version": "btc_bankroll_attack_forward_observer_safety_status_v1",
        "status": "research_only",
        "forward_observation_only": True,
        "holdout_lock_enforced": bool(holdout_lock.get("lock_config_present")),
        "observe_only_violation_count": int(holdout_lock.get("observe_only_violation_count", 0) or 0),
        "selection_use_blocked_by_lock": bool(holdout_lock.get("selection_use_blocked_by_lock")),
        "minimum_30d_complete": bool(gate.get("minimum_30d_complete")),
        "minimum_60d_complete": bool(gate.get("minimum_60d_complete")),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Observe-only ledger records theoretical research state and cannot submit or authorize orders.",
        "blockers": list(report.get("blockers", [])),
    }


def render_btc_bankroll_attack_forward_observer_markdown(report: Mapping[str, Any]) -> str:
    latest = report.get("latest_observation", {})
    progress = report.get("observation_progress", {})
    gate = report.get("gate", {})
    exposure = latest.get("theoretical_sleeve_exposure", {}) if isinstance(latest, Mapping) else {}
    spike = latest.get("spike_remaining_capital", {}) if isinstance(latest, Mapping) else {}
    signal = latest.get("daily_signal", {}) if isinstance(latest, Mapping) else {}
    lines = [
        "# BTC 10x attack observe-only 观察器",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 最新决策时间：`{latest.get('decision_time')}`",
        f"- 每日信号：`{signal.get('side')}`，信号年龄 `{signal.get('signal_age_4h_bars')}` 根 4H",
        f"- 理论暴露 sleeve：`{exposure.get('exposed_sleeve_count')}`，其中 attack `{exposure.get('attack_exposed_sleeve_count')}`",
        f"- -10% 插针后理论剩余本金：`{spike.get('remaining_after_10pct_spike_pct')}`%",
        f"- 是否触发降级：`{latest.get('downgrade_triggered')}`",
        f"- 累计观察条数：`{progress.get('observation_count')}`，观察天数：`{progress.get('observation_days')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 口径",
        "",
        "本观察器只记录理论研究状态，不产生订单意图，不写 paper 队列，不连接 broker/OMS/live。30/60 天观察完成后仍需人工复核，不能自动晋级。",
    ]
    return "\n".join(lines) + "\n"


def _side_label(value: float) -> str:
    if value > 0.0:
        return "long"
    if value < 0.0:
        return "short"
    return "flat"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    flattened = [_flatten_row(row) for row in rows]
    for row in flattened:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in flattened:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _flatten_row(row: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Mapping):
            for subkey, subvalue in value.items():
                output[f"{key}.{subkey}"] = subvalue
        else:
            output[str(key)] = value
    return output


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
