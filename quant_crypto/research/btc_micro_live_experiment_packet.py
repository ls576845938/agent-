from __future__ import annotations

import csv
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import _frozen_v3_direction
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _prepare_market_context


SCHEMA_VERSION = "btc_micro_live_experiment_packet_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_micro_live_experiment_packet/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_experiment_packet_report.json"
DEFAULT_SIGNALS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_experiment_signals.csv"
DEFAULT_ALERTS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_experiment_alerts.csv"
DEFAULT_REHEARSAL_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_experiment_no_trade_rehearsal.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_micro_live_experiment_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_DEPTH_SLIPPAGE_REPORT = Path("artifacts/btc_cost_model/latest/btc_depth_slippage_report.json")
DEFAULT_FILL_MAPPING_REPORT = Path("artifacts/btc_cost_model/latest/btc_depth_slippage_fill_mapping_report.json")

TOTAL_BUDGET_RMB = 1000.0
SLEEVE_COUNT = 10
SLEEVE_RMB = 100.0
MAX_TOTAL_EXPOSED_SLEEVES = 3
DEFENSIVE_5X_MAX_SLEEVES = 2
ATTACK_10X_MAX_SLEEVES = 1
DEFENSIVE_LEVERAGE = 5.0
ATTACK_LEVERAGE = 10.0
MAINTENANCE_MARGIN_RATE = 0.005
LIQUIDATION_FEE_RATE = 0.003
DEFAULT_RMB_USDT_RATE = 0.14
DEFAULT_RECORD_COUNT = 12
FUNDING_CROWDING_ABS_THRESHOLD = 0.0005
FUNDING_SIDE_ADVERSE_THRESHOLD = 0.0003
SPIKE_STRESS_PCTS = (5.0, 8.0, 10.0)


def build_btc_micro_live_experiment_packet(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    depth_slippage_report_path: Path = DEFAULT_DEPTH_SLIPPAGE_REPORT,
    fill_mapping_report_path: Path = DEFAULT_FILL_MAPPING_REPORT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    rmb_usdt_rate: float = DEFAULT_RMB_USDT_RATE,
    record_count: int = DEFAULT_RECORD_COUNT,
    market_context: Mapping[str, Any] | None = None,
    direction: pd.Series | None = None,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    signals_path = output_dir / DEFAULT_SIGNALS_CSV_PATH.name
    alerts_path = output_dir / DEFAULT_ALERTS_CSV_PATH.name
    rehearsal_path = output_dir / DEFAULT_REHEARSAL_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    warnings: list[str] = []
    market = dict(market_context) if market_context is not None else _load_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
        blockers=blockers,
    )
    blockers.extend(str(item) for item in market.get("blockers", []) if str(item) not in blockers)
    bars_4h = _frame(market.get("bars_4h"))
    derivatives_4h = _frame(market.get("derivatives_4h")).reindex(bars_4h.index) if len(bars_4h) else pd.DataFrame()
    if direction is None and len(bars_4h) and not blockers:
        try:
            direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
        except Exception as exc:  # pragma: no cover - defensive artifact failure path
            blockers.append("btc_micro_live_direction_build_failed")
            warnings.append(f"direction_build_error:{type(exc).__name__}:{exc}")
            direction = pd.Series(0.0, index=bars_4h.index)
    elif direction is None:
        direction = pd.Series(0.0, index=bars_4h.index)
    else:
        direction = pd.Series(direction, dtype=float).reindex(bars_4h.index).fillna(0.0)

    if len(bars_4h) == 0:
        blockers.append("btc_micro_live_market_4h_context_missing")
    if len(direction) == 0:
        blockers.append("btc_micro_live_direction_series_missing")

    depth_report = _read_json(depth_slippage_report_path)
    fill_mapping_report = _read_json(fill_mapping_report_path)
    depth_context = _depth_context(depth_report, fill_mapping_report, depth_slippage_report_path, fill_mapping_report_path)
    if not depth_context["depth_snapshot_available"]:
        warnings.append("btc_micro_live_depth_snapshot_missing_no_trade_rehearsal_incomplete")
    if not depth_context["fill_mapping_verified"]:
        warnings.append("btc_micro_live_fill_mapping_unverified_no_paper_credit")

    records = _signal_records(
        bars_4h=bars_4h,
        derivatives_4h=derivatives_4h,
        direction=direction,
        record_count=record_count,
        rmb_usdt_rate=rmb_usdt_rate,
        base_cost_bps=base_cost_bps,
    )
    latest = records[-1] if records else {}
    alerts = _alert_rows(latest=latest, records=records, generated=generated)
    rehearsals = _no_trade_rehearsal_rows(latest=latest, depth_context=depth_context, rmb_usdt_rate=rmb_usdt_rate)
    checklist = _pre_live_checklist(latest=latest, alerts=alerts, rehearsals=rehearsals)
    status = "blocked_research_only" if blockers else "complete_research_only"

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": status,
        "decision": "btc_micro_live_experiment_packet_observe_only_alert_only_no_order_no_paper_no_live",
        "scope": "1000_rmb_micro_live_research_rules_packet_signal_recorder_alert_only_no_trade_rehearsal",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "depth_slippage_report_path": _portable_path(depth_slippage_report_path),
            "fill_mapping_report_path": _portable_path(fill_mapping_report_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "frozen Donchian high-yield v3 direction from completed 1h->4h bars",
            "derivatives_visibility_rule": "aligned by available_time <= decision_time through existing derivatives alignment",
            "rmb_usdt_rate": float(rmb_usdt_rate),
            "rmb_usdt_rate_note": "operator-configurable research approximation; not live sizing evidence",
        },
        "experiment_rules": _experiment_rules(),
        "observe_only_recorder": {
            "frequency": "4h_completed_bar_or_daily_batch",
            "record_count": len(records),
            "latest_decision_time": latest.get("decision_time"),
            "latest_direction": latest.get("direction"),
            "latest_triggered_strategies": latest.get("triggered_strategies", []),
            "records": records,
        },
        "alert_only": {
            "order_action_allowed": False,
            "alert_count": len(alerts),
            "block_alert_count": len([row for row in alerts if row.get("severity") == "block"]),
            "alerts": alerts,
        },
        "no_trade_execution_rehearsal": {
            "real_order_submitted": False,
            "order_endpoint_used": False,
            "depth_context": depth_context,
            "rows": rehearsals,
        },
        "pre_live_checklist": checklist,
        "summary": _summary(latest=latest, alerts=alerts, checklist=checklist, depth_context=depth_context),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": sorted(set(warnings)),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "signals_csv": _portable_path(signals_path),
            "alerts_csv": _portable_path(alerts_path),
            "no_trade_rehearsal_csv": _portable_path(rehearsal_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(signals_path, records)
    _write_csv(alerts_path, alerts)
    _write_csv(rehearsal_path, rehearsals)
    _write_text(markdown_path, render_btc_micro_live_experiment_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_micro_live_experiment_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    rules = _mapping(report.get("experiment_rules"))
    records = _mapping(report.get("observe_only_recorder")).get("records")
    latest = _mapping(records[-1] if isinstance(records, list) and records else {})
    checklist = _mapping(report.get("pre_live_checklist"))
    rows = [
        "# BTC 1000 RMB 实验规则包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 当前方向：`{summary.get('latest_direction')}`，触发：`{', '.join(summary.get('latest_triggered_strategies') or [])}`",
        f"- 预算：`{rules.get('total_budget_rmb')}` RMB，`{rules.get('sleeve_count')}` 个 sleeve，每个 `{rules.get('sleeve_rmb')}` RMB。",
        f"- 最多同时暴露：`{rules.get('max_total_exposed_sleeves')}` 个 sleeve；5x 防插针最多 `{rules.get('defensive_5x_max_sleeves')}` 个，10x attack 最多 `{rules.get('attack_10x_max_sleeves')}` 个。",
        f"- 最新 -10% 插针后估算剩余本金：`{latest.get('remaining_principal_pct_after_10pct_spike')}`%。",
        f"- 当前风险等级：`{checklist.get('current_risk_level')}`；当前 live/paper/order 均为 `false`。",
        "",
        "## 开仓纪律",
        "",
        "- 只研究两条线：5x 防插针 sleeve、少量 10x attack sleeve。",
        "- 方向来自已完成 4H K 线后的 frozen Donchian high-yield v3 方向；当前 raw 信号不直接下单。",
        "- 方向为空仓、funding 拥挤、插针剩余本金不足、处于冷却或暂停期时，禁止新增暴露。",
        "- 10x attack 必须依附 5x 防插针信号，且最多 1 个 sleeve，不允许单独扩张。",
        "",
        "## 停止与降杠杆",
        "",
        "- 单个 sleeve 亏完：该 sleeve 进入 48 小时冷却。",
        "- 连续 2 次失败：下一轮杠杆上限降低 20%。",
        "- 连续 3 次失败：全部暂停 7 天，只记录信号。",
        "- 趋势失败、funding 拥挤或插针风险过高时，只发提醒，不下单。",
        "",
        "## 当前检查单",
        "",
        f"- observe-only 允许：`{checklist.get('observe_only_allowed')}`",
        f"- paper 允许：`{checklist.get('paper_allowed')}`",
        f"- live 允许：`{checklist.get('live_allowed')}`",
        f"- broker/order 允许：`{checklist.get('broker_or_order_allowed')}`",
        f"- 本次最多投入：`{checklist.get('max_principal_this_signal_rmb')}` RMB",
        f"- 杠杆上限：`{checklist.get('leverage_cap')}`x",
        "",
        "## 重要边界",
        "",
        "这个包只做自动记录、提醒和 no-trade 演练。它不能写 paper 队列，不能解锁 live，也不能替代真实盘口、mark/index price、funding 结算和成交回放证据。",
    ]
    return "\n".join(rows) + "\n"


def _load_market_context(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    initial_capital: float,
    base_cost_bps: float,
    blockers: list[str],
) -> dict[str, Any]:
    try:
        return _prepare_market_context(
            market_db_path=market_db_path,
            derivatives_rows_path=derivatives_rows_path,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
    except Exception as exc:  # pragma: no cover - artifact failure path
        blockers.append("btc_micro_live_market_context_load_failed")
        return {"blockers": [f"market_context_error:{type(exc).__name__}:{exc}"]}


def _experiment_rules() -> dict[str, Any]:
    return {
        "rulebook_id": "btc_1000_rmb_micro_live_experiment_v1",
        "total_budget_rmb": TOTAL_BUDGET_RMB,
        "sleeve_count": SLEEVE_COUNT,
        "sleeve_rmb": SLEEVE_RMB,
        "max_total_exposed_sleeves": MAX_TOTAL_EXPOSED_SLEEVES,
        "reserve_sleeves_min": SLEEVE_COUNT - MAX_TOTAL_EXPOSED_SLEEVES,
        "research_lines": [
            {
                "line_id": "defensive_5x_spike_sleeve",
                "leverage": DEFENSIVE_LEVERAGE,
                "max_sleeves": DEFENSIVE_5X_MAX_SLEEVES,
                "role": "base exposure with spike-defense discipline",
            },
            {
                "line_id": "actual_10x_attack_limited",
                "leverage": ATTACK_LEVERAGE,
                "max_sleeves": ATTACK_10X_MAX_SLEEVES,
                "role": "small attack sleeve; only when defensive line is already allowed",
            },
        ],
        "entry_allowed_when": [
            "completed_4h_direction_is_long_or_short",
            "not_in_pause_or_cooldown",
            "funding_not_crowded",
            "remaining_principal_after_10pct_adverse_spike_above_attack_floor",
            "max_total_exposed_sleeves_not_exceeded",
        ],
        "must_stop_when": [
            "direction_turns_flat_or_opposite",
            "funding_or_cost_pressure_crowded",
            "spike_remaining_principal_below_floor",
            "cooldown_or_pause_active",
            "manual_rule_violation_detected",
        ],
        "loss_discipline": {
            "single_sleeve_loss_cooldown_hours": 48,
            "losses_to_reduce_leverage": 2,
            "leverage_reduction_pct": 20.0,
            "losses_to_pause_all": 3,
            "pause_all_days": 7,
        },
        "promotion_boundary": "observe_only_alert_only_no_order_no_paper_no_live",
    }


def _signal_records(
    *,
    bars_4h: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    direction: pd.Series,
    record_count: int,
    rmb_usdt_rate: float,
    base_cost_bps: float,
) -> list[dict[str, Any]]:
    if len(bars_4h) == 0 or len(direction) == 0:
        return []
    aligned = direction.reindex(bars_4h.index).fillna(0.0)
    records: list[dict[str, Any]] = []
    index = list(bars_4h.index[-max(1, int(record_count)):])
    previous_side = 0.0
    for ts in index:
        side = _side_value(aligned.loc[ts])
        close = _float(bars_4h.loc[ts, "close"])
        der = derivatives_4h.loc[ts] if ts in derivatives_4h.index else pd.Series(dtype=float)
        funding_rate = _float(der.get("funding_rate"), 0.0)
        funding_pressure = _funding_pressure(side=side, funding_rate=funding_rate)
        five_allowed = side != 0.0 and funding_pressure not in {"crowded_abs", "side_adverse_crowded"}
        ten_candidate = five_allowed
        exposures = _target_sleeves(five_allowed=five_allowed, ten_candidate=ten_candidate)
        spike = _spike_remaining_pct(exposures, side=side)
        ten_allowed = ten_candidate and spike[10.0] >= 80.0
        exposures = _target_sleeves(five_allowed=five_allowed, ten_candidate=ten_allowed)
        spike = _spike_remaining_pct(exposures, side=side)
        triggered = []
        if five_allowed:
            triggered.append("defensive_5x_spike_sleeve")
        if ten_allowed:
            triggered.append("actual_10x_attack_limited")
        if side == 0.0:
            triggered.append("flat_no_entry")
        records.append(
            {
                "decision_time": _ts(ts),
                "direction": _direction_label(side),
                "direction_value": side,
                "strategy_triggered": ",".join(triggered),
                "triggered_strategies": triggered,
                "close": _round(close, 4),
                "defensive_5x_sleeves": exposures["defensive_5x_spike_sleeve"]["sleeves"],
                "attack_10x_sleeves": exposures["actual_10x_attack_limited"]["sleeves"],
                "total_exposed_sleeves": exposures["total_exposed_sleeves"],
                "principal_exposed_rmb": exposures["principal_exposed_rmb"],
                "notional_exposed_rmb": exposures["notional_exposed_rmb"],
                "notional_exposed_usdt_estimate": _round(exposures["notional_exposed_rmb"] * rmb_usdt_rate),
                "defensive_5x_liquidation_price": _liquidation_price(close, side, DEFENSIVE_LEVERAGE),
                "attack_10x_liquidation_price": _liquidation_price(close, side, ATTACK_LEVERAGE) if ten_allowed else None,
                "liquidation_distance_bps_5x": _round(_liquidation_threshold(DEFENSIVE_LEVERAGE) * 10_000.0),
                "liquidation_distance_bps_10x": _round(_liquidation_threshold(ATTACK_LEVERAGE) * 10_000.0),
                "remaining_principal_pct_after_5pct_spike": spike[5.0],
                "remaining_principal_pct_after_8pct_spike": spike[8.0],
                "remaining_principal_pct_after_10pct_spike": spike[10.0],
                "funding_rate": _round(funding_rate, 8),
                "funding_pressure": funding_pressure,
                "base_cost_bps": float(base_cost_bps),
                "trend_failure": previous_side != 0.0 and side == 0.0,
                "order_action_allowed": False,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
        previous_side = side
    return records


def _target_sleeves(*, five_allowed: bool, ten_candidate: bool) -> dict[str, Any]:
    defensive_sleeves = DEFENSIVE_5X_MAX_SLEEVES if five_allowed else 0
    attack_sleeves = ATTACK_10X_MAX_SLEEVES if ten_candidate else 0
    total = min(MAX_TOTAL_EXPOSED_SLEEVES, defensive_sleeves + attack_sleeves)
    if total < defensive_sleeves + attack_sleeves:
        attack_sleeves = max(0, total - defensive_sleeves)
    principal = (defensive_sleeves + attack_sleeves) * SLEEVE_RMB
    notional = defensive_sleeves * SLEEVE_RMB * DEFENSIVE_LEVERAGE + attack_sleeves * SLEEVE_RMB * ATTACK_LEVERAGE
    return {
        "defensive_5x_spike_sleeve": {"sleeves": defensive_sleeves, "leverage": DEFENSIVE_LEVERAGE},
        "actual_10x_attack_limited": {"sleeves": attack_sleeves, "leverage": ATTACK_LEVERAGE},
        "total_exposed_sleeves": defensive_sleeves + attack_sleeves,
        "principal_exposed_rmb": _round(principal),
        "notional_exposed_rmb": _round(notional),
    }


def _spike_remaining_pct(exposures: Mapping[str, Any], *, side: float) -> dict[float, float]:
    if side == 0.0:
        return {shock: 100.0 for shock in SPIKE_STRESS_PCTS}
    active: list[tuple[int, float]] = []
    defensive = _mapping(exposures.get("defensive_5x_spike_sleeve"))
    attack = _mapping(exposures.get("actual_10x_attack_limited"))
    active.append((int(defensive.get("sleeves", 0) or 0), DEFENSIVE_LEVERAGE))
    active.append((int(attack.get("sleeves", 0) or 0), ATTACK_LEVERAGE))
    remaining: dict[float, float] = {}
    for shock in SPIKE_STRESS_PCTS:
        lost = 0.0
        for count, leverage in active:
            if shock / 100.0 >= _liquidation_threshold(leverage):
                lost += float(count) * SLEEVE_RMB
        remaining[shock] = _round((TOTAL_BUDGET_RMB - lost) / TOTAL_BUDGET_RMB * 100.0)
    return remaining


def _alert_rows(*, latest: Mapping[str, Any], records: Sequence[Mapping[str, Any]], generated: datetime) -> list[dict[str, Any]]:
    if not latest:
        return [
            _alert(generated, "block", "signal_missing", "市场方向记录缺失，只能观察，不能交易。", "do_not_trade")
        ]
    alerts: list[dict[str, Any]] = []
    triggered = set(str(latest.get("strategy_triggered", "")).split(","))
    if "defensive_5x_spike_sleeve" in triggered:
        alerts.append(_alert(generated, "info", "defensive_5x_entry_signal", "出现 5x 防插针 observe-only 信号。", "record_only"))
    if "actual_10x_attack_limited" in triggered:
        alerts.append(_alert(generated, "warn", "attack_10x_condition", "出现 10x attack observe-only 条件，但仍禁止下单。", "record_only"))
    if bool(latest.get("trend_failure")):
        alerts.append(_alert(generated, "warn", "trend_failure", "趋势由有仓方向转为空仓，理论上应停止新增暴露。", "record_only"))
    remaining_10 = _float(latest.get("remaining_principal_pct_after_10pct_spike"), 100.0)
    if remaining_10 < 80.0:
        alerts.append(_alert(generated, "block", "spike_risk_too_high", "-10% 插针后剩余本金低于 80%，禁止新增 attack。", "do_not_trade"))
    elif remaining_10 <= 90.0:
        alerts.append(_alert(generated, "warn", "spike_risk_near_floor", "-10% 插针会杀死 10x attack sleeve，需谨慎记录。", "record_only"))
    if str(latest.get("funding_pressure")) in {"crowded_abs", "side_adverse_crowded"}:
        alerts.append(_alert(generated, "block", "funding_crowded", "funding 拥挤或对当前方向不利，禁止新增暴露。", "do_not_trade"))
    if not alerts:
        alerts.append(_alert(generated, "info", "no_trade_observe_only", "没有触发进攻提醒；继续自动记录。", "record_only"))
    return alerts


def _no_trade_rehearsal_rows(
    *,
    latest: Mapping[str, Any],
    depth_context: Mapping[str, Any],
    rmb_usdt_rate: float,
) -> list[dict[str, Any]]:
    if not latest:
        return []
    side = str(latest.get("direction"))
    order_side = "buy" if side == "long" else ("sell" if side == "short" else "none")
    rows: list[dict[str, Any]] = []
    for line_id, leverage, sleeves in (
        ("defensive_5x_spike_sleeve", DEFENSIVE_LEVERAGE, int(latest.get("defensive_5x_sleeves", 0) or 0)),
        ("actual_10x_attack_limited", ATTACK_LEVERAGE, int(latest.get("attack_10x_sleeves", 0) or 0)),
    ):
        principal_rmb = sleeves * SLEEVE_RMB
        notional_rmb = principal_rmb * leverage
        notional_usdt = notional_rmb * float(rmb_usdt_rate)
        sim = _matching_depth_sim(depth_context, notional_usdt=notional_usdt, order_side=order_side)
        conforms = (
            side in {"long", "short"}
            and sleeves > 0
            and int(latest.get("total_exposed_sleeves", 0) or 0) <= MAX_TOTAL_EXPOSED_SLEEVES
            and leverage <= ATTACK_LEVERAGE
            and bool(sim.get("complete", False))
        )
        rows.append(
            {
                "line_id": line_id,
                "decision_time": latest.get("decision_time"),
                "direction": side,
                "order_side_proxy": order_side,
                "sleeves": sleeves,
                "principal_rmb": _round(principal_rmb),
                "notional_rmb": _round(notional_rmb),
                "notional_usdt_estimate": _round(notional_usdt),
                "depth_snapshot_available": bool(depth_context.get("depth_snapshot_available", False)),
                "depth_aware_history_verified": bool(depth_context.get("depth_aware_history_verified", False)),
                "fill_mapping_verified": bool(depth_context.get("fill_mapping_verified", False)),
                "snapshot_proxy_fill_complete": bool(sim.get("complete", False)) if sleeves > 0 and order_side != "none" else False,
                "snapshot_proxy_slippage_bps": sim.get("slippage_bps_vs_mid"),
                "snapshot_proxy_levels_used": sim.get("levels_used"),
                "distance_to_liquidation_bps": _round(_liquidation_threshold(leverage) * 10_000.0) if sleeves > 0 else None,
                "conforms_to_1000_rmb_rules": bool(conforms),
                "execution_gate_credit": False,
                "paper_order_allowed": False,
                "live_order_allowed": False,
                "order_endpoint_used": False,
                "rehearsal_status": "snapshot_proxy_only_not_gate_eligible" if sim else "blocked_no_depth_proxy",
            }
        )
    return rows


def _pre_live_checklist(
    *,
    latest: Mapping[str, Any],
    alerts: Sequence[Mapping[str, Any]],
    rehearsals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    block_alerts = [row for row in alerts if row.get("severity") == "block"]
    warn_alerts = [row for row in alerts if row.get("severity") == "warn"]
    allowed_rehearsals = [row for row in rehearsals if row.get("conforms_to_1000_rmb_rules") is True]
    risk_level = "blocked"
    if not block_alerts and latest:
        risk_level = "high" if warn_alerts else "normal_observe_only"
    max_principal = 0.0 if risk_level == "blocked" else _float(latest.get("principal_exposed_rmb"), 0.0)
    return {
        "checklist_id": "btc_pre_live_1000_rmb_checklist_v1",
        "strategy_allowed_now": False,
        "observe_only_allowed": True,
        "paper_allowed": False,
        "live_allowed": False,
        "broker_or_order_allowed": False,
        "current_risk_level": risk_level,
        "max_principal_this_signal_rmb": _round(min(max_principal, SLEEVE_RMB * MAX_TOTAL_EXPOSED_SLEEVES)),
        "leverage_cap": ATTACK_LEVERAGE if risk_level != "blocked" else 0.0,
        "cooldown_or_pause_state": "not_connected_to_live_state_research_default_no_new_order",
        "rule_violation_count": len(block_alerts),
        "warning_count": len(warn_alerts),
        "rule_violations": [str(row.get("alert_id")) for row in block_alerts],
        "matching_rehearsal_count": len(allowed_rehearsals),
        "operator_message_cn": "本页面只能告诉你是否符合 1000 RMB 实验规则；当前仍不允许 paper/live/order。",
    }


def _depth_context(
    depth_report: Mapping[str, Any],
    fill_mapping_report: Mapping[str, Any],
    depth_path: Path,
    fill_path: Path,
) -> dict[str, Any]:
    simulations = _list_of_mappings(depth_report.get("market_order_simulations"))
    return {
        "depth_slippage_report_path": _portable_path(depth_path),
        "fill_mapping_report_path": _portable_path(fill_path),
        "depth_snapshot_available": bool(depth_report.get("depth_snapshot_available", False)),
        "depth_aware": bool(depth_report.get("depth_aware", False)),
        "depth_aware_history_verified": bool(depth_report.get("depth_aware_slippage_history_verified", False)),
        "fill_mapping_verified": int(fill_mapping_report.get("mapped_fill_count", 0) or 0) > 0
        and not fill_mapping_report.get("blockers"),
        "gate_eligible": bool(depth_report.get("depth_aware_slippage_history_verified", False))
        and int(fill_mapping_report.get("mapped_fill_count", 0) or 0) > 0,
        "latest_snapshot": depth_report.get("latest_snapshot") if isinstance(depth_report.get("latest_snapshot"), Mapping) else {},
        "market_order_simulations": simulations,
        "depth_blockers": list(depth_report.get("blockers", [])) if isinstance(depth_report.get("blockers"), list) else [],
        "fill_mapping_blockers": list(fill_mapping_report.get("blockers", [])) if isinstance(fill_mapping_report.get("blockers"), list) else [],
    }


def _matching_depth_sim(depth_context: Mapping[str, Any], *, notional_usdt: float, order_side: str) -> Mapping[str, Any]:
    if not bool(depth_context.get("depth_snapshot_available", False)) or order_side not in {"buy", "sell"}:
        return {}
    sims = [
        row
        for row in _list_of_mappings(depth_context.get("market_order_simulations"))
        if str(row.get("side")) == order_side and _float(row.get("notional_usd"), math.inf) >= max(1.0, notional_usdt)
    ]
    if not sims:
        sims = [
            row
            for row in _list_of_mappings(depth_context.get("market_order_simulations"))
            if str(row.get("side")) == order_side
        ]
    if not sims:
        return {}
    return sorted(sims, key=lambda row: _float(row.get("notional_usd"), math.inf))[0]


def _summary(
    *,
    latest: Mapping[str, Any],
    alerts: Sequence[Mapping[str, Any]],
    checklist: Mapping[str, Any],
    depth_context: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "total_budget_rmb": TOTAL_BUDGET_RMB,
        "sleeve_rmb": SLEEVE_RMB,
        "latest_direction": latest.get("direction"),
        "latest_decision_time": latest.get("decision_time"),
        "latest_triggered_strategies": latest.get("triggered_strategies", []),
        "latest_total_exposed_sleeves": latest.get("total_exposed_sleeves"),
        "latest_principal_exposed_rmb": latest.get("principal_exposed_rmb"),
        "latest_remaining_after_10pct_spike": latest.get("remaining_principal_pct_after_10pct_spike"),
        "latest_funding_pressure": latest.get("funding_pressure"),
        "alert_count": len(alerts),
        "block_alert_count": len([row for row in alerts if row.get("severity") == "block"]),
        "current_risk_level": checklist.get("current_risk_level"),
        "depth_snapshot_available": depth_context.get("depth_snapshot_available"),
        "depth_gate_eligible": depth_context.get("gate_eligible"),
        "paper_allowed": False,
        "live_allowed": False,
        "order_allowed": False,
    }


def _funding_pressure(*, side: float, funding_rate: float) -> str:
    if not math.isfinite(funding_rate):
        return "unknown"
    if abs(funding_rate) >= FUNDING_CROWDING_ABS_THRESHOLD:
        return "crowded_abs"
    if side > 0.0 and funding_rate >= FUNDING_SIDE_ADVERSE_THRESHOLD:
        return "side_adverse_crowded"
    if side < 0.0 and funding_rate <= -FUNDING_SIDE_ADVERSE_THRESHOLD:
        return "side_adverse_crowded"
    return "normal"


def _liquidation_threshold(leverage: float) -> float:
    return max(0.0, 1.0 / float(leverage) - MAINTENANCE_MARGIN_RATE - LIQUIDATION_FEE_RATE)


def _liquidation_price(close: float, side: float, leverage: float) -> float | None:
    if close <= 0.0 or side == 0.0:
        return None
    threshold = _liquidation_threshold(leverage)
    if side > 0.0:
        return _round(close * (1.0 - threshold), 4)
    return _round(close * (1.0 + threshold), 4)


def _side_value(value: Any) -> float:
    number = _float(value, 0.0)
    if number > 1e-12:
        return 1.0
    if number < -1e-12:
        return -1.0
    return 0.0


def _direction_label(side: float) -> str:
    if side > 0.0:
        return "long"
    if side < 0.0:
        return "short"
    return "flat"


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "observe_only_allowed": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "broker_or_order_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
        "reason": "Micro-live packet is alert-only and no-trade rehearsal only.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "alert_only": True,
        "no_trade_rehearsal_only": True,
        "network_collection_used": False,
        "private_endpoint_used": False,
        "broker_access_allowed": False,
        "broker_or_order_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_micro_live_experiment_packet_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "broker_or_order_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
        "reason": "1000 RMB experiment packet records signals and rehearses only; it cannot place orders.",
    }


def _alert(generated: datetime, severity: str, alert_id: str, message_cn: str, action: str) -> dict[str, Any]:
    return {
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "severity": severity,
        "alert_id": alert_id,
        "message_cn": message_cn,
        "suggested_action": action,
        "order_action_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    csv_rows = [{key: _csv_value(row.get(key)) for key in fields} for row in rows]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(csv_rows)


def _frame(value: Any) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _float(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None
