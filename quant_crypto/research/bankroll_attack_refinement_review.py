from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.bankroll_layered_sleeve_scheduler_review import (
    DEFAULT_REPORT_PATH as DEFAULT_LAYERED_REPORT_PATH,
    ONE_OFF_SPIKE_PCTS,
    LayeredResult,
    LayeredScenario,
    SleeveTemplate,
    _result_row,
    _simulate_layered_scheduler,
    _ts,
)
from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_bankroll_attack_refinement_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_bankroll_attack_refinement/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_refinement_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_refinement_grid.csv"
DEFAULT_WATCHLIST_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_refinement_watchlist.csv"
DEFAULT_EVENT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_refinement_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_refinement_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

MIN_REMAINING_AFTER_10PCT_SPIKE = 80.0
MAX_RESEARCH_LEVERAGE = 10.0


def build_btc_bankroll_attack_refinement_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_layered_report_path: Path = DEFAULT_LAYERED_REPORT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_csv_path = output_dir / DEFAULT_GRID_CSV_PATH.name
    watchlist_csv_path = output_dir / DEFAULT_WATCHLIST_CSV_PATH.name
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
    source_context = _source_context(source_layered_report_path)
    if not source_context:
        blockers.append("btc_attack_refinement_missing_source_layered_sleeve_scheduler_report")

    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    bars_4h = market["bars_4h"].reindex(direction.index)

    scenarios = _scenario_grid()
    results: list[LayeredResult] = []
    event_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        result = _simulate_layered_scheduler(
            scenario,
            market=market,
            direction=direction,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        results.append(result)
        event_rows.extend(_event_rows_with_policy_context(result))

    grid_rows = sorted((_attack_result_row(result) for result in results), key=_attack_rank_key)
    watchlist_rows = [row for row in grid_rows if _is_watchlist_row(row)]
    top_watchlist = watchlist_rows[:20]
    summary = _summary(grid_rows=grid_rows, watchlist_rows=watchlist_rows, source_context=source_context)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "attack_refinement_research_only_no_paper_no_live",
        "scope": "actual_10x_attack_spike_survival_refinement_for_small_account_research",
        "code_commit": _git_commit(),
        "input": {
            "source_layered_report_path": _portable_path(source_layered_report_path),
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "frozen high-yield v3 loss-control direction, completed 1h->4h bars",
        },
        "source_context": source_context,
        "review_design": {
            "objective": "refine around scenarios that actually used 10x attack sleeves while keeping worst remaining capital after a hypothetical -10pct spike above 80pct",
            "small_account_risk_tolerance_note": "用户接受小资金研究线可以全部亏完；这只改变研究排序的风险偏好，不改变 paper/live 安全门禁。",
            "target_existing_actual_attack_scenario_id": source_context.get("best_10x_attack_scenario_id"),
            "target_existing_actual_attack_total_return_pct": source_context.get("best_10x_attack_total_return_pct"),
            "target_existing_actual_attack_min_remaining_capital_pct_after_10pct_spike": source_context.get("best_10x_attack_min_remaining_capital_pct_after_10pct_spike"),
            "initial_sleeve_count": INITIAL_SLEEVE_COUNT,
            "scenario_count": len(grid_rows),
            "watchlist_min_remaining_capital_pct_after_10pct_spike": MIN_REMAINING_AFTER_10PCT_SPIKE,
            "watchlist_requires_actual_attack_exposure": True,
            "max_research_leverage": MAX_RESEARCH_LEVERAGE,
            "core_leverage": 5.0,
            "reserve_leverage_grid": [3.0, 5.0],
            "attack_leverage": 10.0,
            "core_count_grid": [5, 6],
            "attack_count_grid": [1, 2, 3],
            "max_total_exposed_grid": [7, 8, 10],
            "attack_delay_profiles": sorted(_attack_delay_profiles().keys()),
            "one_off_spike_pcts": list(ONE_OFF_SPIKE_PCTS),
            "liquidation_model": {
                "model": "isolated_sleeve_linear_perp_4h_high_low_mark_proxy",
                "promotion_evidence": False,
                "spike_survival_metric": "min_remaining_capital_pct_after_10pct_spike",
            },
        },
        "summary": summary,
        "top_attack_watchlist": top_watchlist,
        "grid_rows_sample": grid_rows[:25],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(summary),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_csv_path),
            "watchlist_csv": _portable_path(watchlist_csv_path),
            "events_csv": _portable_path(event_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_csv_path, grid_rows)
    _write_csv(watchlist_csv_path, watchlist_rows)
    _write_csv(event_csv_path, event_rows[:800])
    _write_text(markdown_path, render_btc_bankroll_attack_refinement_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _scenario_grid() -> list[LayeredScenario]:
    scenarios: list[LayeredScenario] = []
    for core_count in (5, 6):
        for reserve_lev in (3.0, 5.0):
            for attack_count in (1, 2, 3):
                reserve_count = INITIAL_SLEEVE_COUNT - core_count - attack_count
                if reserve_count < 1:
                    continue
                for max_total in (7, 8, 10):
                    for max_attack in range(1, attack_count + 1):
                        if max_attack > max_total:
                            continue
                        for profile_id, attack_delays in _attack_delay_profiles().items():
                            for extract in (False, True):
                                templates: list[SleeveTemplate] = []
                                templates.extend(SleeveTemplate("core", 5.0, i % 3) for i in range(core_count))
                                templates.extend(SleeveTemplate("reserve", reserve_lev, 6 + (i % 3) * 3) for i in range(reserve_count))
                                templates.extend(SleeveTemplate("attack", 10.0, attack_delays[i]) for i in range(attack_count))
                                scenario_id = (
                                    f"attack_ref_core5x{core_count}_reserve{int(reserve_lev)}x{reserve_count}"
                                    f"_attack10x{attack_count}_max{max_total}_atkcap{max_attack}"
                                    f"_delay{profile_id}_{'extract' if extract else 'noextract'}"
                                )
                                scenarios.append(
                                    LayeredScenario(
                                        scenario_id=scenario_id,
                                        policy_id=f"actual_10x_attack_refinement_{profile_id}",
                                        sleeve_templates=tuple(templates),
                                        max_total_exposed=max_total,
                                        max_attack_exposed=max_attack,
                                        extract_on_double=extract,
                                        reserve_requires_pullback=True,
                                    )
                                )
    return scenarios


def _attack_delay_profiles() -> dict[str, tuple[int, int, int]]:
    return {
        "early": (0, 1, 2),
        "balanced": (3, 6, 9),
        "late": (6, 9, 12),
    }


def _attack_result_row(result: LayeredResult) -> dict[str, Any]:
    row = _result_row(result)
    row["attack_delay_profile"] = _delay_profile_from_row(row)
    row["actual_attack_used"] = int(row.get("max_attack_exposed_sleeves_observed", 0)) > 0
    row["survives_80pct_after_10pct_spike"] = float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) >= MIN_REMAINING_AFTER_10PCT_SPIKE
    row["watchlist_decision"] = _watchlist_decision(row)
    row["small_account_attack_research_line"] = True
    row["paper_queue_write_allowed"] = False
    row["paper_candidate_created"] = False
    row["live_unlock_allowed"] = False
    return row


def _delay_profile_from_row(row: Mapping[str, Any]) -> str:
    scenario_id = str(row.get("scenario_id", ""))
    marker = "_delay"
    if marker not in scenario_id:
        return "unknown"
    suffix = scenario_id.split(marker, 1)[1]
    return suffix.split("_", 1)[0]


def _is_watchlist_row(row: Mapping[str, Any]) -> bool:
    return _watchlist_decision(row) == "retain_attack_refinement_research_watchlist_only"


def _watchlist_decision(row: Mapping[str, Any]) -> str:
    if int(row.get("max_attack_exposed_sleeves_observed", 0)) <= 0:
        return "reject_no_actual_10x_attack_exposure"
    if float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) < MIN_REMAINING_AFTER_10PCT_SPIKE:
        return "reject_below_80pct_remaining_after_10pct_spike"
    if float(row.get("total_return_pct", -100.0)) <= 0.0:
        return "reject_non_positive_total_return"
    if int(row.get("normal_liquidation_count", 0)) > 0:
        return "reject_normal_liquidation_observed"
    if max(_loads_float_list(row.get("sleeve_leverages", "[]")) or [0.0]) > MAX_RESEARCH_LEVERAGE:
        return "reject_leverage_above_10x"
    return "retain_attack_refinement_research_watchlist_only"


def _attack_rank_key(row: Mapping[str, Any]) -> tuple[int, int, float, float, float, float, str]:
    return (
        0 if _is_watchlist_row(row) else 1,
        0 if bool(row.get("actual_attack_used")) else 1,
        -float(row.get("total_return_pct", -999.0)),
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        float(row.get("max_drawdown_abs_pct", 999.0)),
        -float(row.get("reserve_cash_pct_of_initial", 0.0)),
        str(row.get("scenario_id")),
    )


def _summary(
    *,
    grid_rows: Sequence[Mapping[str, Any]],
    watchlist_rows: Sequence[Mapping[str, Any]],
    source_context: Mapping[str, Any],
) -> dict[str, Any]:
    actual_attack_rows = [row for row in grid_rows if int(row.get("max_attack_exposed_sleeves_observed", 0)) > 0]
    best_return = dict(watchlist_rows[0]) if watchlist_rows else {}
    best_survival = dict(sorted(watchlist_rows, key=_survival_rank_key)[0]) if watchlist_rows else {}
    best_actual_attack = dict(sorted(actual_attack_rows, key=_actual_attack_rank_key)[0]) if actual_attack_rows else {}
    return {
        "scenario_count": len(grid_rows),
        "actual_attack_scenario_count": len(actual_attack_rows),
        "watchlist_count": len(watchlist_rows),
        "watchlist_min_remaining_capital_pct_after_10pct_spike": MIN_REMAINING_AFTER_10PCT_SPIKE,
        "source_best_10x_attack_scenario_id": source_context.get("best_10x_attack_scenario_id"),
        "source_best_10x_attack_total_return_pct": source_context.get("best_10x_attack_total_return_pct"),
        "source_best_10x_attack_min_remaining_capital_pct_after_10pct_spike": source_context.get("best_10x_attack_min_remaining_capital_pct_after_10pct_spike"),
        "best_return_watchlist_scenario_id": best_return.get("scenario_id"),
        "best_return_watchlist_total_return_pct": best_return.get("total_return_pct"),
        "best_return_watchlist_annual_return_pct": best_return.get("annual_return_pct"),
        "best_return_watchlist_min_remaining_capital_pct_after_10pct_spike": best_return.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_return_watchlist_max_attack_exposed_sleeves_observed": best_return.get("max_attack_exposed_sleeves_observed"),
        "best_return_watchlist_average_attack_exposed_sleeves": best_return.get("average_attack_exposed_sleeves"),
        "best_return_watchlist_max_drawdown_abs_pct": best_return.get("max_drawdown_abs_pct"),
        "best_survival_watchlist_scenario_id": best_survival.get("scenario_id"),
        "best_survival_watchlist_min_remaining_capital_pct_after_10pct_spike": best_survival.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_survival_watchlist_total_return_pct": best_survival.get("total_return_pct"),
        "best_actual_attack_any_survival_scenario_id": best_actual_attack.get("scenario_id"),
        "best_actual_attack_any_survival_total_return_pct": best_actual_attack.get("total_return_pct"),
        "best_actual_attack_any_survival_min_remaining_capital_pct_after_10pct_spike": best_actual_attack.get("min_remaining_capital_pct_after_10pct_spike"),
        "primary_lesson": "10x attack can be studied only when exposure is capped and spike-survival is measured separately from final return",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _survival_rank_key(row: Mapping[str, Any]) -> tuple[float, float, float, str]:
    return (
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        -float(row.get("total_return_pct", -999.0)),
        float(row.get("max_drawdown_abs_pct", 999.0)),
        str(row.get("scenario_id")),
    )


def _actual_attack_rank_key(row: Mapping[str, Any]) -> tuple[float, float, float, str]:
    return (
        -float(row.get("total_return_pct", -999.0)),
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        float(row.get("max_drawdown_abs_pct", 999.0)),
        str(row.get("scenario_id")),
    )


def _source_context(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    summary = report.get("summary", {})
    if not isinstance(summary, Mapping):
        return {}
    return {
        "schema_version": report.get("schema_version"),
        "decision": report.get("decision"),
        "best_10x_attack_scenario_id": summary.get("best_10x_attack_scenario_id"),
        "best_10x_attack_total_return_pct": summary.get("best_10x_attack_total_return_pct"),
        "best_10x_attack_min_remaining_capital_pct_after_10pct_spike": summary.get("best_10x_attack_min_remaining_capital_pct_after_10pct_spike"),
        "best_10x_attack_max_attack_exposed_sleeves_observed": summary.get("best_10x_attack_max_attack_exposed_sleeves_observed"),
        "best_10x_attack_average_attack_exposed_sleeves": summary.get("best_10x_attack_average_attack_exposed_sleeves"),
    }


def _event_rows_with_policy_context(result: LayeredResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in result.event_rows:
        output = dict(row)
        output["policy_id"] = result.scenario.policy_id
        output["max_total_exposed"] = result.scenario.max_total_exposed
        output["max_attack_exposed"] = result.scenario.max_attack_exposed
        output["attack_delay_profile"] = _delay_profile_from_row({"scenario_id": result.scenario.scenario_id})
        output["paper_queue_write_allowed"] = False
        output["live_unlock_allowed"] = False
        rows.append(output)
    return rows


def _loads_float_list(value: Any) -> list[float]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            raw = []
    output: list[float] = []
    for item in raw:
        try:
            output.append(float(item))
        except (TypeError, ValueError):
            continue
    return output


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Attack refinement is research-only. Small-account risk tolerance does not unlock paper/live.",
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
        "max_research_leverage": MAX_RESEARCH_LEVERAGE,
    }


def _warnings(summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_attack_refinement_research_only_no_paper_no_live"]
    if int(summary.get("watchlist_count", 0) or 0) == 0:
        warnings.append("btc_attack_refinement_no_80pct_survival_watchlist")
    if int(summary.get("actual_attack_scenario_count", 0) or 0) == 0:
        warnings.append("btc_attack_refinement_no_actual_10x_attack_exposure")
    if float(summary.get("best_return_watchlist_min_remaining_capital_pct_after_10pct_spike", 0.0) or 0.0) < MIN_REMAINING_AFTER_10PCT_SPIKE:
        warnings.append("btc_attack_refinement_best_watchlist_below_survival_threshold")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_bankroll_attack_refinement_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "hundred_x_review_candidate_allowed": False,
        "max_research_leverage": MAX_RESEARCH_LEVERAGE,
        "reason": "Actual 10x attack refinement remains research-only and cannot promote a strategy to paper/live.",
        "blockers": list(report.get("blockers", [])),
    }


def render_btc_bankroll_attack_refinement_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 10x attack 分仓细化复核包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 场景数：`{summary.get('scenario_count')}`",
        f"- 实际发生过 10x attack 暴露的场景数：`{summary.get('actual_attack_scenario_count')}`",
        f"- 符合“实际 attack + -10% 插针后剩余本金 >=80%”的研究观察数：`{summary.get('watchlist_count')}`",
        f"- 上一轮真实 attack 最佳：`{summary.get('source_best_10x_attack_scenario_id')}`，-10% 插针剩余 `{summary.get('source_best_10x_attack_min_remaining_capital_pct_after_10pct_spike')}`%，总收益 `{summary.get('source_best_10x_attack_total_return_pct')}`%",
        f"- 本轮按收益排序最佳观察：`{summary.get('best_return_watchlist_scenario_id')}`",
        f"- 本轮最佳观察总收益：`{summary.get('best_return_watchlist_total_return_pct')}`%",
        f"- 本轮最佳观察年化：`{summary.get('best_return_watchlist_annual_return_pct')}`%",
        f"- 本轮最佳观察 -10% 插针后剩余本金：`{summary.get('best_return_watchlist_min_remaining_capital_pct_after_10pct_spike')}`%",
        f"- 本轮最佳观察最大回撤：`{summary.get('best_return_watchlist_max_drawdown_abs_pct')}`%",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 口径",
        "",
        "本包只研究小资金激进线：允许 10x attack 真实暴露，但必须把插针后剩余本金比例作为主约束。用户能接受小资金归零，只代表研究口径更激进，不代表系统可以绕过 paper/live 门禁。",
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
