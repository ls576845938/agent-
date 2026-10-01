from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.high_yield_v2_confirmation import (
    FROZEN_DRAWDOWN_GATE_PCT,
    FROZEN_MAX_LEVERAGE,
    FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
    FROZEN_VARIANT_ID,
    FROZEN_VOL_TARGET_PCT,
    _as_top5_like_item,
    _leverage_model_review,
    _run_frozen_simulation,
)
from quant_crypto.research.btc_confirmatory_holdout_lock import DEFAULT_LOCK_CONFIG_PATH
from quant_crypto.research.btc_observe_only_lock import (
    holdout_lock_blockers,
    observation_row_lock_stamp,
    observe_only_lock_status,
    read_holdout_lock_config,
)
from quant_crypto.research.long_short_top5_review import (
    _loss_control_review,
    _slice_metrics,
    _trade_ledger,
    _ts,
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


SCHEMA_VERSION = "btc_high_yield_v2_followup_v1"
OBSERVER_ID = "btc_high_yield_v2_frozen_observe_only_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_high_yield_v2_followup/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_followup_report.json"
DEFAULT_OBSERVATION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_daily_observation_latest.csv"
DEFAULT_LOSS_V3_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_loss_control_v3_grid.csv"
DEFAULT_PERP_EVIDENCE_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_perp_execution_evidence.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_followup_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_OBSERVATION_LEDGER_PATH = Path("data/forward_observation/btc_high_yield_v2_frozen/observations.jsonl")

DEFAULT_FUNDING_LEDGER_REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
DEFAULT_COST_MODEL_REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_PERPETUAL_POLICY_REPORT = Path("artifacts/btc_perpetual_policy/latest/btc_perpetual_policy_status_report.json")
DEFAULT_PROVIDER_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")


def build_btc_high_yield_v2_followup(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    observation_ledger_path: Path = DEFAULT_OBSERVATION_LEDGER_PATH,
    holdout_lock_path: Path = DEFAULT_LOCK_CONFIG_PATH,
    funding_ledger_report_path: Path = DEFAULT_FUNDING_LEDGER_REPORT,
    cost_model_report_path: Path = DEFAULT_COST_MODEL_REPORT,
    perpetual_policy_report_path: Path = DEFAULT_PERPETUAL_POLICY_REPORT,
    provider_report_path: Path = DEFAULT_PROVIDER_REPORT,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    observation_csv_path = output_dir / DEFAULT_OBSERVATION_CSV_PATH.name
    loss_v3_csv_path = output_dir / DEFAULT_LOSS_V3_CSV_PATH.name
    perp_evidence_path = output_dir / DEFAULT_PERP_EVIDENCE_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    holdout_lock_config, holdout_lock_load_blockers = read_holdout_lock_config(holdout_lock_path)
    blockers.extend(holdout_lock_load_blockers)
    frozen_sim = _run_frozen_simulation(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    observation = _run_daily_observation(
        frozen_sim,
        market=market,
        observation_ledger_path=observation_ledger_path,
        observation_csv_path=observation_csv_path,
        holdout_lock_config=holdout_lock_config,
        holdout_lock_path=holdout_lock_path,
        initial_capital=initial_capital,
        generated_at_utc=generated,
    )
    blockers.extend(holdout_lock_blockers(observation.get("holdout_lock", {})))
    loss_v3 = _run_loss_control_v3(
        market=market,
        loss_v3_csv_path=loss_v3_csv_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    perp_evidence = _build_perp_execution_evidence(
        frozen_sim,
        market=market,
        derivatives_rows_path=derivatives_rows_path,
        funding_ledger_report_path=funding_ledger_report_path,
        cost_model_report_path=cost_model_report_path,
        perpetual_policy_report_path=perpetual_policy_report_path,
        provider_report_path=provider_report_path,
        base_cost_bps=base_cost_bps,
    )
    _write_json(perp_evidence_path, perp_evidence)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_high_yield_v2_followup_research_only_no_paper_no_live",
        "scope": "daily_observation_loss_control_v3_perp_execution_evidence",
        "code_commit": _git_commit(),
        "frozen_candidate": {
            "variant_id": FROZEN_VARIANT_ID,
            "base_variant_id": BEST_BASE_VARIANT_ID,
            "vol_target_pct": FROZEN_VOL_TARGET_PCT,
            "max_leverage": FROZEN_MAX_LEVERAGE,
            "drawdown_gate_pct": FROZEN_DRAWDOWN_GATE_PCT,
            "min_liquidation_buffer_bps": FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
            "entry_structure_frozen": "Donchian 240 + daily EMA50/200 + cooldown 12 + risknone + volatility target",
        },
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "holdout_lock_path": _portable_path(holdout_lock_path),
            "market_4h_rows": int(len(market["bars_4h"])),
            "market_4h_start": _ts(market["bars_4h"].index.min()) if len(market["bars_4h"]) else None,
            "market_4h_end": _ts(market["bars_4h"].index.max()) if len(market["bars_4h"]) else None,
            "data_refresh_mode": "local_sqlite_completed_1h_to_4h_no_network",
        },
        "step_1_daily_observation_automation": observation,
        "step_2_loss_control_v3_narrow_experiment": loss_v3,
        "step_3_perpetual_execution_evidence": perp_evidence,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(loss_v3, perp_evidence),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "observation_csv": _portable_path(observation_csv_path),
            "observation_ledger_jsonl": _portable_path(observation_ledger_path),
            "loss_control_v3_csv": _portable_path(loss_v3_csv_path),
            "perp_execution_evidence": _portable_path(perp_evidence_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_json(safety_path, _safety_status(report))
    _write_text(markdown_path, render_btc_high_yield_v2_followup_markdown(report))
    return report


def _run_daily_observation(
    sim: Any,
    *,
    market: Mapping[str, Any],
    observation_ledger_path: Path,
    observation_csv_path: Path,
    holdout_lock_config: Mapping[str, Any],
    holdout_lock_path: Path,
    initial_capital: float,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    item = _as_top5_like_item(sim)
    latest_ts = pd.Timestamp(sim.returns.index.max()) if len(sim.returns.index) else None
    row = _daily_observation_row(sim, market=market, latest_ts=latest_ts, generated_at_utc=generated_at_utc, initial_capital=initial_capital)
    holdout_lock = observe_only_lock_status(
        lock_config=holdout_lock_config,
        decision_times=[row.get("decision_time")],
        observer_id=OBSERVER_ID,
        holdout_lock_path=holdout_lock_path,
    )
    if row:
        row["holdout_lock"] = observation_row_lock_stamp(holdout_lock, row.get("decision_time"))
    existing = _read_jsonl(observation_ledger_path)
    matching_index = next(
        (
            index
            for index, entry in enumerate(existing)
            if entry.get("variant_id") == FROZEN_VARIANT_ID and entry.get("decision_time") == row.get("decision_time")
        ),
        None,
    )
    already_processed = matching_index is not None
    existing_observation_upgraded = False
    if already_processed and matching_index is not None:
        current = dict(existing[matching_index])
        upgraded = {**current, **row}
        if current.get("holdout_lock") != upgraded.get("holdout_lock") or current.get("observer_id") != upgraded.get("observer_id"):
            existing[matching_index] = upgraded
            _write_jsonl(observation_ledger_path, existing)
            existing_observation_upgraded = True
    already_processed = any(
        entry.get("variant_id") == FROZEN_VARIANT_ID and entry.get("decision_time") == row.get("decision_time")
        for entry in existing
    )
    new_observation_written = False
    if not already_processed:
        observation_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with observation_ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        new_observation_written = True
        existing.append(row)
    _write_csv(observation_csv_path, existing[-60:])

    recent = {}
    for days in (30, 60):
        idx = _last_days_index(sim.returns.index, days)
        recent[f"{days}d"] = _slice_metrics(item, idx, initial_capital=initial_capital)
    return {
        "status": "complete_research_only",
        "automation_entrypoint": "scripts/research/run_btc_high_yield_v2_followup.py",
        "recommended_frequency": "daily_after_latest_4h_bar_is_complete",
        "data_refresh_mode": "local_sqlite_completed_1h_to_4h_no_network",
        "latest_decision_time": row.get("decision_time"),
        "latest_theoretical_side": row.get("theoretical_side"),
        "latest_theoretical_exposure": row.get("theoretical_exposure"),
        "latest_net_return_pct": row.get("net_return_pct"),
        "latest_max_adverse_move_pct": row.get("max_adverse_move_pct"),
        "holdout_lock_enforced": bool(holdout_lock.get("lock_config_present")),
        "holdout_lock": holdout_lock,
        "observe_only_violation_count": int(holdout_lock.get("observe_only_violation_count", 0) or 0),
        "selection_use_blocked_by_lock": bool(holdout_lock.get("selection_use_blocked_by_lock")),
        "new_observation_written": new_observation_written,
        "existing_observation_upgraded": existing_observation_upgraded,
        "already_processed": already_processed,
        "observation_count": len(existing),
        "observation_ledger_path": _portable_path(observation_ledger_path),
        "recent_window_metrics": recent,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _daily_observation_row(
    sim: Any,
    *,
    market: Mapping[str, Any],
    latest_ts: pd.Timestamp | None,
    generated_at_utc: datetime,
    initial_capital: float,
) -> dict[str, Any]:
    if latest_ts is None:
        return {}
    bars = market["bars_4h"].reindex(sim.exposure.index)
    exposure = float(sim.exposure.loc[latest_ts])
    row_pos = sim.exposure.index.get_loc(latest_ts)
    adverse = _bar_adverse_move_pct(bars, exposure=exposure, pos=int(row_pos))
    return {
        "schema_version": "btc_high_yield_v2_daily_observation_row_v1",
        "generated_at_utc": generated_at_utc.astimezone(timezone.utc).isoformat(),
        "observer_id": OBSERVER_ID,
        "variant_id": FROZEN_VARIANT_ID,
        "decision_time": _ts(latest_ts),
        "latest_completed_bar_rule": "4h bar derived from completed 1h bars",
        "theoretical_side": _side(exposure),
        "theoretical_exposure": _round(exposure),
        "net_return_pct": _round(float(sim.returns.loc[latest_ts]) * 100.0),
        "max_adverse_move_pct": adverse,
        "risk_control_triggered": _risk_trigger_label(sim, latest_ts),
        "equity": _round(float(sim.equity.loc[latest_ts]) if latest_ts in sim.equity.index else initial_capital),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "paper_candidate_created": False,
        "strategy_skeleton_generated": False,
    }


def _run_loss_control_v3(
    *,
    market: Mapping[str, Any],
    loss_v3_csv_path: Path,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    rows = []
    for fast_stop_base_pct in (6.0, 5.0, 4.5):
        for stop_cooldown_bars in (6, 12):
            for loss_trigger in (3, 2):
                for derisk_bars in (12, 18):
                    for failed_exit in (False, True):
                        variant = _v2_variant(
                            FROZEN_VOL_TARGET_PCT,
                            FROZEN_MAX_LEVERAGE,
                            (
                                f"hy_v3_lossctl_fs{str(fast_stop_base_pct).replace('.', 'p')}"
                                f"_scd{stop_cooldown_bars}_lt{loss_trigger}_db{derisk_bars}"
                                f"_fail{'1' if failed_exit else '0'}"
                            ),
                        )
                        policy = ReviewPolicy(
                            drawdown_gate_pct=FROZEN_DRAWDOWN_GATE_PCT,
                            min_liquidation_buffer_bps=FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
                            fast_stop_base_pct=fast_stop_base_pct,
                            stop_cooldown_bars=stop_cooldown_bars,
                            consecutive_loss_trigger_bars=loss_trigger,
                            consecutive_loss_derisk_bars=derisk_bars,
                            enable_failed_breakout_exit=failed_exit,
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
                        item = _as_top5_like_item(sim)
                        loss_control = _loss_control_review(_trade_ledger(item))
                        rows.append(_loss_v3_row(sim, policy=policy, loss_control=loss_control))
    rows = sorted(rows, key=lambda row: (row["retention_rank"], -float(row["annual_return_pct"]), float(row["average_loss_pct"]), row["variant_id"]))
    _write_csv(loss_v3_csv_path, rows)
    retained = [row for row in rows if row["retention_decision"] == "retain_loss_control_v3_research_watchlist_only"]
    best = rows[0] if rows else {}
    return {
        "status": "complete_research_only",
        "candidate_count": len(rows),
        "expected_candidate_count": 48,
        "entry_structure_changed": False,
        "searched_components": [
            "fast_stop_base_pct",
            "stop_cooldown_bars",
            "consecutive_loss_trigger_bars",
            "consecutive_loss_derisk_bars",
            "failed_breakout_exit",
        ],
        "retained_count": len(retained),
        "best_candidate": best,
        "watchlist": retained[:10],
        "csv_path": _portable_path(loss_v3_csv_path),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _loss_v3_row(sim: Any, *, policy: ReviewPolicy, loss_control: Mapping[str, Any]) -> dict[str, Any]:
    metrics = sim.metrics
    average_loss = float(loss_control.get("average_loss_pct", 0.0))
    decision = _loss_v3_decision(sim, loss_control)
    return {
        "variant_id": sim.variant.variant_id,
        "fast_stop_base_pct": policy.fast_stop_base_pct,
        "stop_cooldown_bars": policy.stop_cooldown_bars,
        "consecutive_loss_trigger_bars": policy.consecutive_loss_trigger_bars,
        "consecutive_loss_derisk_bars": policy.consecutive_loss_derisk_bars,
        "failed_breakout_exit": policy.enable_failed_breakout_exit,
        "annual_return_pct": metrics["annual_return_pct"],
        "total_return_pct": metrics["total_return_pct"],
        "max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
        "profit_factor": metrics["profit_factor"],
        "calmar_ratio": metrics["calmar_ratio"],
        "average_exposure": metrics["average_exposure"],
        "loss_control_passed": bool(loss_control.get("passed")),
        "average_loss_pct": _round(average_loss),
        "worst_loss_pct": loss_control.get("worst_loss_pct"),
        "loss_trade_count": loss_control.get("loss_trade_count"),
        "forced_risk_reduction_count": sim.diagnostics["forced_risk_reduction_count"],
        "consecutive_loss_derisk_count": sim.diagnostics["consecutive_loss_derisk_count"],
        "failed_breakout_exit_count": sim.diagnostics.get("failed_breakout_exit_count", 0),
        "simulated_liquidation_count": sim.diagnostics["simulated_liquidation_count"],
        "retention_decision": decision,
        "retention_rank": 0 if decision == "retain_loss_control_v3_research_watchlist_only" else 1,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _loss_v3_decision(sim: Any, loss_control: Mapping[str, Any]) -> str:
    metrics = sim.metrics
    if not bool(loss_control.get("passed")):
        return "reject_loss_control_not_improved_to_threshold"
    if float(metrics.get("annual_return_pct", 0.0)) < 60.0:
        return "reject_annual_return_below_high_yield_target"
    if float(metrics.get("max_drawdown_abs_pct", 999.0)) > 40.0:
        return "reject_drawdown_above_40"
    if float(metrics.get("profit_factor", 0.0)) < 1.15:
        return "reject_profit_factor_below_1p15"
    if int(sim.diagnostics.get("simulated_liquidation_count", 0)) > 0:
        return "reject_simulated_liquidation"
    return "retain_loss_control_v3_research_watchlist_only"


def _build_perp_execution_evidence(
    sim: Any,
    *,
    market: Mapping[str, Any],
    derivatives_rows_path: Path,
    funding_ledger_report_path: Path,
    cost_model_report_path: Path,
    perpetual_policy_report_path: Path,
    provider_report_path: Path,
    base_cost_bps: float,
) -> dict[str, Any]:
    derivatives_coverage = _derivatives_coverage(derivatives_rows_path)
    funding_ledger = _read_json(funding_ledger_report_path)
    cost_model = _read_json(cost_model_report_path)
    policy = _read_json(perpetual_policy_report_path)
    provider = _read_json(provider_report_path)
    leverage_review = _leverage_model_review(sim, market=market, base_cost_bps=base_cost_bps)
    evidence = {
        "schema_version": "btc_high_yield_v2_perp_execution_evidence_v1",
        "status": "incomplete_research_evidence",
        "instrument_assumption": "USDT linear perpetual would be required for 2.5x long/short execution; current signal research uses spot OHLCV proxy",
        "derivatives_sentiment_coverage": derivatives_coverage,
        "funding_ledger_source": _source_status(funding_ledger_report_path, funding_ledger),
        "cost_model_source": _source_status(cost_model_report_path, cost_model),
        "perpetual_policy_source": _source_status(perpetual_policy_report_path, policy),
        "provider_source": _source_status(provider_report_path, provider),
        "liquidation_proxy_review": leverage_review,
        "evidence_checklist": {
            "mark_index_price_path": _bool_from_sources(provider, policy, ["mark_price_verified", "index_price_verified", "mark_index_price_path_available"]),
            "funding_settlement_ledger": bool(funding_ledger.get("funding_payment_in_ledger") is True),
            "spread_depth_slippage": _bool_from_sources(cost_model, provider, ["depth_aware", "order_book_depth_verified", "spread_aware"]),
            "exchange_outage_model": _bool_from_sources(policy, provider, ["exchange_outage_model_available", "outage_policy_verified"]),
            "exact_liquidation_formula": _bool_from_sources(provider, policy, ["liquidation_formula_verified", "maintenance_margin_tiers_verified"]),
        },
        "paper_live_boundary": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "broker_access_allowed": False,
            "oms_access_allowed": False,
        },
    }
    missing = [name for name, passed in evidence["evidence_checklist"].items() if not passed]
    evidence["promotion_blockers"] = [f"missing_{name}" for name in missing]
    evidence["decision"] = "perp_execution_evidence_incomplete_no_paper_no_live" if missing else "perp_execution_evidence_present_but_manual_review_required"
    return evidence


def _derivatives_coverage(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    rows = payload.get("rows", []) if isinstance(payload, Mapping) else []
    if not isinstance(rows, list):
        rows = []
    fields = ["funding_rate", "open_interest_usd", "open_interest", "long_short_ratio", "top_trader_long_short_ratio", "taker_buy_sell_ratio"]
    counts = {field: sum(1 for row in rows if isinstance(row, Mapping) and row.get(field) is not None) for field in fields}
    event_times = [str(row.get("event_time")) for row in rows if isinstance(row, Mapping) and row.get("event_time")]
    available_times = [str(row.get("available_time")) for row in rows if isinstance(row, Mapping) and row.get("available_time")]
    return {
        "path": _portable_path(path),
        "row_count": len(rows),
        "event_time_start": min(event_times) if event_times else None,
        "event_time_end": max(event_times) if event_times else None,
        "available_time_start": min(available_times) if available_times else None,
        "available_time_end": max(available_times) if available_times else None,
        "nonnull_counts": counts,
        "usable_for_direction": False,
        "usage": "risk_filter_and_funding_approximation_only",
    }


def _source_status(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _portable_path(path),
        "exists": path.exists(),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "decision": payload.get("decision") or payload.get("policy_decision"),
        "blockers": payload.get("blockers", []),
    }


def _bool_from_sources(*sources_and_keys: Any) -> bool:
    *sources, keys = sources_and_keys
    if not isinstance(keys, list):
        return False
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            if source.get(key) is True:
                return True
            nested = source.get("evidence") or source.get("coverage") or source.get("checks")
            if isinstance(nested, Mapping) and nested.get(key) is True:
                return True
    return False


def render_btc_high_yield_v2_followup_markdown(report: Mapping[str, Any]) -> str:
    obs = report.get("step_1_daily_observation_automation", {})
    loss = report.get("step_2_loss_control_v3_narrow_experiment", {})
    perp = report.get("step_3_perpetual_execution_evidence", {})
    gate = report.get("gate", {})
    best = loss.get("best_candidate", {}) if isinstance(loss.get("best_candidate"), Mapping) else {}
    lines = [
        "# BTC 高收益 v2 后续三步执行报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 冻结候选：`{report.get('frozen_candidate', {}).get('variant_id')}`",
        f"- 观察器新增记录：`{obs.get('new_observation_written')}`，累计观察：`{obs.get('observation_count')}`",
        f"- v3 亏损控制候选数：`{loss.get('candidate_count')}`，保留数：`{loss.get('retained_count')}`",
        f"- v3 最佳候选：`{best.get('variant_id')}`，年化 `{best.get('annual_return_pct')}`，平均亏损 `{best.get('average_loss_pct')}`",
        f"- 永续证据结论：`{perp.get('decision')}`",
        f"- 永续证据缺口：`{', '.join(str(item) for item in perp.get('promotion_blockers', []))}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论",
        "",
        "三步均已生成 research-only 证据。观察器可以每日复跑；v3 只改退出/降仓；永续执行证据仍不完整，不能 paper/live。",
    ]
    return "\n".join(lines) + "\n"


def _warnings(loss_v3: Mapping[str, Any], perp_evidence: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_high_yield_v2_followup_research_only_no_paper_no_live"]
    if int(loss_v3.get("retained_count", 0)) == 0:
        warnings.append("btc_high_yield_v2_loss_control_v3_no_retained_candidate")
    if perp_evidence.get("promotion_blockers"):
        warnings.append("btc_high_yield_v2_perp_execution_evidence_incomplete")
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
        "reason": "Follow-up artifacts are observation and research diagnostics only.",
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
        "schema_version": "btc_high_yield_v2_followup_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "forward_observation_only": True,
        "loss_control_v3_research_only": True,
        "perp_execution_evidence_complete": not bool(report.get("step_3_perpetual_execution_evidence", {}).get("promotion_blockers")),
        "reason": "No paper/live promotion is allowed from follow-up artifacts.",
    }


def _last_days_index(index: pd.DatetimeIndex, days: int) -> pd.DatetimeIndex:
    if len(index) == 0:
        return pd.DatetimeIndex([])
    end = pd.Timestamp(index.max())
    return pd.DatetimeIndex(index[index > end - pd.Timedelta(days=days)])


def _bar_adverse_move_pct(bars: pd.DataFrame, *, exposure: float, pos: int) -> float:
    if pos <= 0 or abs(exposure) <= 1e-12:
        return 0.0
    prev_close = float(bars["close"].iloc[pos - 1])
    if exposure > 0.0:
        adverse = max(0.0, 1.0 - float(bars["low"].iloc[pos]) / prev_close)
    else:
        adverse = max(0.0, float(bars["high"].iloc[pos]) / prev_close - 1.0)
    return _round(adverse * 100.0)


def _risk_trigger_label(sim: Any, ts: pd.Timestamp) -> str:
    exposure = float(sim.exposure.loc[ts]) if ts in sim.exposure.index else 0.0
    turnover = float(sim.turnover.loc[ts]) if ts in sim.turnover.index else 0.0
    if abs(exposure) <= 1e-12 and turnover > 0.0:
        return "flat_after_exit_or_risk_control_proxy"
    if abs(exposure) <= 1e-12:
        return "flat_no_position"
    return "position_open_no_new_proxy_trigger"


def _side(exposure: float) -> str:
    if exposure > 1e-12:
        return "long"
    if exposure < -1e-12:
        return "short"
    return "flat"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


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
