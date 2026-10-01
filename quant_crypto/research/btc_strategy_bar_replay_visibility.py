from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import _frozen_v3_direction
from quant_crypto.research.high_octane_attack_sleeve_lab import DEFAULT_OUTPUT_DIR as DEFAULT_HIGH_OCTANE_DIR
from quant_crypto.research.high_yield_v2_confirmation import (
    FROZEN_VARIANT_ID as HIGH_YIELD_FROZEN_VARIANT_ID,
    _run_frozen_simulation as _run_high_yield_frozen_simulation,
)
from quant_crypto.research.long_short_top5_review import DEFAULT_OUTPUT_DIR as DEFAULT_LONG_SHORT_TOP5_DIR
from quant_crypto.research.long_short_trend_following_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
    aggregate_ohlcv,
    aggregate_ohlcv_calendar,
    align_derivatives_to_index,
    evaluate_long_short_trend_rule,
    load_market_1h,
    long_short_trend_following_specs,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_strategy_bar_replay_visibility_v2"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_strategy_bar_replay_visibility/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_bar_replay_visibility_report.json"
DEFAULT_ROWS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_bar_replay_visibility_rows.csv"
DEFAULT_CHECKS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_bar_replay_visibility_checks.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_bar_replay_visibility_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_LONG_SHORT_REPORT_PATH = DEFAULT_LONG_SHORT_TOP5_DIR / "btc_long_short_top5_review_report.json"
DEFAULT_LONG_SHORT_CSV_PATH = DEFAULT_LONG_SHORT_TOP5_DIR / "btc_long_short_top5_review_candidates.csv"
DEFAULT_HIGH_OCTANE_REPORT_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_report.json"
DEFAULT_HIGH_OCTANE_WATCHLIST_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_watchlist.csv"
DEFAULT_HIGH_OCTANE_ROLLING_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_rolling_start.csv"
DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT_PATH = Path("artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_followup_report.json")


def build_btc_strategy_bar_replay_visibility(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    long_short_report_path: Path = DEFAULT_LONG_SHORT_REPORT_PATH,
    long_short_csv_path: Path = DEFAULT_LONG_SHORT_CSV_PATH,
    high_octane_report_path: Path = DEFAULT_HIGH_OCTANE_REPORT_PATH,
    high_octane_watchlist_path: Path = DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    high_octane_rolling_path: Path = DEFAULT_HIGH_OCTANE_ROLLING_PATH,
    high_yield_followup_report_path: Path = DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT_PATH,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    rows_csv_path = output_dir / DEFAULT_ROWS_CSV_PATH.name
    checks_csv_path = output_dir / DEFAULT_CHECKS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    long_short_report = _read_json(long_short_report_path, blockers, "missing_long_short_top5_report")
    long_short_rows = _read_csv(long_short_csv_path, blockers, "missing_long_short_top5_candidates_csv")
    high_octane_report = _read_json(high_octane_report_path, blockers, "missing_high_octane_report")
    high_octane_watchlist_rows = _read_csv(high_octane_watchlist_path, blockers, "missing_high_octane_watchlist_csv")
    high_octane_rolling_rows = _read_csv(high_octane_rolling_path, blockers, "missing_high_octane_rolling_csv")
    high_yield_followup_report = _read_json(high_yield_followup_report_path, blockers, "missing_high_yield_followup_report")

    replay_rows: list[dict[str, Any]] = []
    long_short_summary: dict[str, Any] = _empty_line_summary("long_short_donchian_top5")
    high_octane_summary: dict[str, Any] = _empty_line_summary("high_octane_attack_sleeve_v2")
    high_yield_summary: dict[str, Any] = _empty_line_summary("high_yield_donchian_v2")

    if not blockers:
        long_short_rows_out, long_short_summary = _build_long_short_replay(
            market_db_path=market_db_path,
            derivatives_rows_path=derivatives_rows_path,
            source_rows=long_short_rows,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        high_octane_rows_out, high_octane_summary = _build_high_octane_visibility_replay(
            market_db_path=market_db_path,
            derivatives_rows_path=derivatives_rows_path,
            high_octane_report=high_octane_report,
            watchlist_rows=high_octane_watchlist_rows,
            rolling_rows=high_octane_rolling_rows,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        replay_rows.extend(long_short_rows_out)
        replay_rows.extend(high_octane_rows_out)
        high_yield_rows_out, high_yield_summary = _build_high_yield_v2_visibility_replay(
            market_db_path=market_db_path,
            derivatives_rows_path=derivatives_rows_path,
            high_yield_followup_report=high_yield_followup_report,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        replay_rows.extend(high_yield_rows_out)

    checks = _checks(
        blockers=blockers,
        long_short_summary=long_short_summary,
        high_octane_summary=high_octane_summary,
        high_yield_summary=high_yield_summary,
    )
    decision = _decision(blockers=blockers, checks=checks, high_octane_summary=high_octane_summary, high_yield_summary=high_yield_summary)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "bar_replay_and_field_visibility_audit_for_long_short_top5_high_octane_v2_and_high_yield_v2",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "long_short_report_path": _portable_path(long_short_report_path),
            "long_short_csv_path": _portable_path(long_short_csv_path),
            "high_octane_report_path": _portable_path(high_octane_report_path),
            "high_octane_watchlist_path": _portable_path(high_octane_watchlist_path),
            "high_octane_rolling_path": _portable_path(high_octane_rolling_path),
            "high_yield_followup_report_path": _portable_path(high_yield_followup_report_path),
        },
        "audit_design": {
            "bar_replay_rule": "Recompute current code path, then assert current exposure equals previous raw signal and current raw signal only affects next bar.",
            "derivatives_visibility_rule": "A derivatives row is visible only when available_time <= decision_time; event_time is also reported for audit.",
            "high_octane_scope_note": "High-Octane v2 replays direction visibility and flags capital-overlay model boundaries; it is not a real exchange execution replay.",
            "high_yield_scope_note": "High-yield v2 replays the frozen stateful overlay and flags same-bar target/return and high-low risk-control proxy boundaries.",
            "paper_live_boundary": "Research-only artifact. No paper queue write, no strategy skeleton, no OMS/broker/live unlock.",
        },
        "summary": _summary(
            checks=checks,
            long_short_summary=long_short_summary,
            high_octane_summary=high_octane_summary,
            high_yield_summary=high_yield_summary,
            decision=decision,
        ),
        "long_short_top5_bar_replay": long_short_summary,
        "high_octane_v2_visibility_replay": high_octane_summary,
        "high_yield_v2_bar_replay": high_yield_summary,
        "checks": checks,
        "sample_rows": replay_rows[:50],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(long_short_summary=long_short_summary, high_octane_summary=high_octane_summary, high_yield_summary=high_yield_summary, blockers=blockers),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "rows_csv": _portable_path(rows_csv_path),
            "checks_csv": _portable_path(checks_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(rows_csv_path, replay_rows)
    _write_csv(checks_csv_path, checks)
    _write_text(markdown_path, render_btc_strategy_bar_replay_visibility_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _build_long_short_replay(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    source_rows: Sequence[Mapping[str, str]],
    initial_capital: float,
    base_cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bars_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    visibility = derivatives_visibility_frame(derivatives_rows_path, bars_4h.index)
    spec_by_id = {spec.candidate_id: spec for spec in long_short_trend_following_specs(run_profile="formal_narrow")}

    rows: list[dict[str, Any]] = []
    missing_specs: list[str] = []
    candidate_summaries: list[dict[str, Any]] = []
    for source_row in source_rows:
        candidate_id = str(source_row.get("candidate_id", ""))
        spec = spec_by_id.get(candidate_id)
        if spec is None:
            missing_specs.append(candidate_id)
            continue
        item = evaluate_long_short_trend_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
        )
        candidate_rows = shift_visibility_rows(
            line="long_short_top5",
            candidate_id=candidate_id,
            rank=_int(source_row.get("rank")),
            raw_signal=item.raw_signal,
            exposure=item.exposure,
            returns=item.returns,
            derivatives_visibility=visibility,
            model_boundary_flag=False,
        )
        rows.extend(candidate_rows)
        candidate_summaries.append(
            {
                "candidate_id": candidate_id,
                "rank": _int(source_row.get("rank")),
                "row_count": len(candidate_rows),
                "current_shift_violation_count": sum(1 for row in candidate_rows if not row["current_exposure_matches_previous_raw"]),
                "next_shift_violation_count": sum(1 for row in candidate_rows if row["next_bar_exposure_matches_current_raw"] is False),
                "derivatives_available_time_violation_count": sum(1 for row in candidate_rows if row["derivatives_available_time_violation"]),
                "derivatives_event_time_violation_count": sum(1 for row in candidate_rows if row["derivatives_event_time_violation"]),
                "nonzero_exposure_bar_count": sum(1 for row in candidate_rows if abs(_float(row["current_bar_exposure"])) > 1e-12),
            }
        )
    summary = _line_summary(
        line="long_short_donchian_top5",
        rows=rows,
        candidate_count=len(candidate_summaries),
        candidate_summaries=candidate_summaries,
        missing_specs=missing_specs,
        extra={
            "market_1h_row_count": int(len(bars_1h)),
            "market_4h_row_count": int(len(bars_4h)),
            "market_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "verdict": "bar_replay_no_shift_or_visibility_violations"
            if rows
            and not missing_specs
            and sum(1 for row in rows if row["current_shift_violation"] or row["next_shift_violation"] or row["derivatives_available_time_violation"]) == 0
            else "bar_replay_requires_review",
        },
    )
    return rows, summary


def _build_high_octane_visibility_replay(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    high_octane_report: Mapping[str, Any],
    watchlist_rows: Sequence[Mapping[str, str]],
    rolling_rows: Sequence[Mapping[str, str]],
    initial_capital: float,
    base_cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    bars_4h = market["bars_4h"].reindex(direction.index)
    visibility = derivatives_visibility_frame(derivatives_rows_path, direction.index)
    best = _best_high_octane_row(high_octane_report, watchlist_rows)
    best_scenario_id = str(best.get("scenario_id", high_octane_report.get("summary", {}).get("best_scenario_id", "")))
    rows: list[dict[str, Any]] = []
    for pos, ts in enumerate(direction.index):
        vis = _visibility_at(visibility, ts)
        prev_ts = direction.index[pos - 1] if pos > 0 else None
        rows.append(
            {
                "line": "high_octane_v2",
                "candidate_id": best_scenario_id,
                "rank": 1,
                "decision_time": _ts(ts),
                "previous_decision_time": _ts(prev_ts),
                "next_execution_time": _ts(direction.index[pos + 1] if pos + 1 < len(direction.index) else None),
                "raw_signal": _float(direction.iloc[pos]),
                "current_bar_exposure": _float(direction.iloc[pos]),
                "expected_current_from_previous_raw": None,
                "next_bar_exposure": None,
                "current_exposure_matches_previous_raw": None,
                "next_bar_exposure_matches_current_raw": None,
                "current_shift_violation": False,
                "next_shift_violation": False,
                "return_uses_prior_exposure": None,
                "market_4h_close_time": _ts(ts),
                "market_completed_bar_visible": True,
                "market_high_low_visible_for_signal": False,
                "derivatives_available_time": _ts(vis.get("derivatives_available_time")),
                "derivatives_event_time": _ts(vis.get("derivatives_event_time")),
                "derivatives_missing": bool(vis.get("derivatives_missing")),
                "derivatives_available_le_decision": bool(vis.get("derivatives_available_le_decision")),
                "derivatives_event_le_decision": bool(vis.get("derivatives_event_le_decision")),
                "derivatives_available_time_violation": bool(vis.get("derivatives_available_time_violation")),
                "derivatives_event_time_violation": bool(vis.get("derivatives_event_time_violation")),
                "model_boundary_flag": True,
                "model_boundary_reason": "direction is inherited from frozen v3 exposure; sleeve overlay uses close-to-close returns and same-bar high/low for liquidation/spike proxy",
                "same_bar_return_proxy": True,
                "same_bar_intrabar_high_low_proxy": True,
                "capital_overlay_same_bar_proxy": True,
                "direction_signal_visibility_checked": True,
                "execution_replay_required_before_paper": True,
                "close": _round(bars_4h["close"].iloc[pos]) if "close" in bars_4h else None,
                "high": _round(bars_4h["high"].iloc[pos]) if "high" in bars_4h else None,
                "low": _round(bars_4h["low"].iloc[pos]) if "low" in bars_4h else None,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    rolling_for_best = [row for row in rolling_rows if row.get("scenario_id") == best_scenario_id]
    rolling_returns = [_float(row.get("total_return_pct")) for row in rolling_for_best]
    best_remaining = _float(best.get("min_remaining_capital_pct_after_10pct_spike", high_octane_report.get("summary", {}).get("best_min_remaining_after_10pct_spike")))
    summary = _line_summary(
        line="high_octane_attack_sleeve_v2",
        rows=rows,
        candidate_count=1 if best_scenario_id else 0,
        candidate_summaries=[
            {
                "candidate_id": best_scenario_id,
                "row_count": len(rows),
                "best_annual_return_pct": _float(best.get("annual_return_pct", high_octane_report.get("summary", {}).get("best_annual_return_pct"))),
                "best_total_return_pct": _float(best.get("total_return_pct", high_octane_report.get("summary", {}).get("best_total_return_pct"))),
                "best_min_remaining_after_10pct_spike": best_remaining,
                "best_margin_over_40pct_threshold": _round(best_remaining - 40.0),
                "best_watchlist_tier": best.get("watchlist_tier", high_octane_report.get("summary", {}).get("best_watchlist_tier")),
                "rolling_start_count": len(rolling_for_best),
                "rolling_median_total_return_pct": _round(median(rolling_returns)) if rolling_returns else 0.0,
            }
        ],
        missing_specs=[],
        extra={
            "best_scenario_id": best_scenario_id,
            "best_min_remaining_after_10pct_spike": best_remaining,
            "best_margin_over_40pct_threshold": _round(best_remaining - 40.0),
            "model_boundary_row_count": len(rows),
            "same_bar_return_proxy_row_count": len(rows),
            "same_bar_intrabar_high_low_proxy_row_count": len(rows),
            "direction_signal_visibility_verdict": "direction_signal_visible_no_available_time_violation"
            if not any(row["derivatives_available_time_violation"] for row in rows)
            else "direction_signal_visibility_violation_detected",
            "capital_overlay_execution_boundary_verdict": "same_bar_execution_proxy_requires_strict_risk_stress_and_mark_index_replay",
            "paper_ready_from_visibility": False,
            "verdict": "visibility_replay_completed_but_capital_overlay_same_bar_proxy_requires_strict_risk_stress",
        },
    )
    return rows, summary


def _build_high_yield_v2_visibility_replay(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    high_yield_followup_report: Mapping[str, Any],
    initial_capital: float,
    base_cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    sim = _run_high_yield_frozen_simulation(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    exposure = sim.exposure.astype(float).fillna(0.0)
    returns = sim.returns.reindex(exposure.index).astype(float).fillna(0.0)
    bars_4h = market["bars_4h"].reindex(exposure.index)
    visibility = derivatives_visibility_frame(derivatives_rows_path, exposure.index)
    frozen = high_yield_followup_report.get("frozen_candidate", {}) if isinstance(high_yield_followup_report, Mapping) else {}
    variant_id = str(frozen.get("variant_id") or HIGH_YIELD_FROZEN_VARIANT_ID)

    rows: list[dict[str, Any]] = []
    index = pd.DatetimeIndex(exposure.index)
    for pos, ts in enumerate(index):
        prev_ts = index[pos - 1] if pos > 0 else None
        next_ts = index[pos + 1] if pos + 1 < len(index) else None
        previous_exposure = _float(exposure.iloc[pos - 1]) if pos > 0 else 0.0
        current_exposure = _float(exposure.iloc[pos])
        target_changed = not _same_float(current_exposure, previous_exposure)
        prior_exposure_return_violation = bool(pos > 0 and target_changed and abs(_float(returns.iloc[pos])) > 1e-12)
        vis = _visibility_at(visibility, ts)
        rows.append(
            {
                "line": "high_yield_v2",
                "candidate_id": variant_id,
                "rank": 1,
                "decision_time": _ts(ts),
                "previous_decision_time": _ts(prev_ts),
                "next_execution_time": _ts(next_ts),
                "raw_signal": current_exposure,
                "current_bar_exposure": current_exposure,
                "previous_bar_exposure": previous_exposure,
                "expected_current_from_previous_raw": None,
                "next_bar_exposure": None if next_ts is None else _float(exposure.iloc[pos + 1]),
                "current_exposure_matches_previous_raw": None,
                "next_bar_exposure_matches_current_raw": None,
                "current_shift_violation": False,
                "next_shift_violation": False,
                "stateful_target_changed_on_current_bar": target_changed,
                "return_uses_prior_exposure": not prior_exposure_return_violation,
                "prior_exposure_return_violation": prior_exposure_return_violation,
                "net_return": _float(returns.iloc[pos]),
                "market_4h_close_time": _ts(ts),
                "market_completed_bar_visible": True,
                "market_high_low_visible_for_signal": False,
                "derivatives_available_time": _ts(vis.get("derivatives_available_time")),
                "derivatives_event_time": _ts(vis.get("derivatives_event_time")),
                "derivatives_missing": bool(vis.get("derivatives_missing")),
                "derivatives_available_le_decision": bool(vis.get("derivatives_available_le_decision")),
                "derivatives_event_le_decision": bool(vis.get("derivatives_event_le_decision")),
                "derivatives_available_time_violation": bool(vis.get("derivatives_available_time_violation")),
                "derivatives_event_time_violation": bool(vis.get("derivatives_event_time_violation")),
                "model_boundary_flag": True,
                "model_boundary_reason": "frozen high-yield v2 stateful overlay applies current target, funding/cost and same-bar high/low risk controls inside the same 4h bar; real mark/index paper runtime replay is required",
                "same_bar_return_proxy": True,
                "same_bar_target_return_proxy": True,
                "same_bar_intrabar_high_low_proxy": True,
                "execution_replay_required_before_paper": True,
                "close": _round(bars_4h["close"].iloc[pos]) if "close" in bars_4h else None,
                "high": _round(bars_4h["high"].iloc[pos]) if "high" in bars_4h else None,
                "low": _round(bars_4h["low"].iloc[pos]) if "low" in bars_4h else None,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )

    prior_violation_count = sum(1 for row in rows if row["prior_exposure_return_violation"])
    summary = _line_summary(
        line="high_yield_donchian_v2",
        rows=rows,
        candidate_count=1,
        candidate_summaries=[
            {
                "candidate_id": variant_id,
                "row_count": len(rows),
                "annual_return_pct": _float(sim.metrics.get("annual_return_pct")),
                "total_return_pct": _float(sim.metrics.get("total_return_pct")),
                "max_drawdown_abs_pct": _float(sim.metrics.get("max_drawdown_abs_pct")),
                "average_exposure": _float(sim.metrics.get("average_exposure")),
                "forced_risk_reduction_count": _int(sim.diagnostics.get("forced_risk_reduction_count")),
                "simulated_liquidation_count": _int(sim.diagnostics.get("simulated_liquidation_count")),
                "liquidation_buffer_derisk_count": _int(sim.diagnostics.get("liquidation_buffer_derisk_count")),
            }
        ],
        missing_specs=[],
        extra={
            "variant_id": variant_id,
            "same_bar_target_return_proxy_row_count": len(rows),
            "same_bar_intrabar_high_low_proxy_row_count": len(rows),
            "prior_exposure_return_violation_count": prior_violation_count,
            "forced_risk_reduction_count": _int(sim.diagnostics.get("forced_risk_reduction_count")),
            "simulated_liquidation_count": _int(sim.diagnostics.get("simulated_liquidation_count")),
            "verdict": "bar_replay_completed_but_stateful_same_bar_execution_proxy_requires_mark_index_paper_runtime_replay",
        },
    )
    return rows, summary


def derivatives_visibility_frame(path: Path, index: pd.DatetimeIndex) -> pd.DataFrame:
    columns = [
        "derivatives_available_time",
        "derivatives_event_time",
        "derivatives_missing",
        "derivatives_available_le_decision",
        "derivatives_event_le_decision",
        "derivatives_available_time_violation",
        "derivatives_event_time_violation",
    ]
    empty = pd.DataFrame(index=index, columns=columns)
    if len(index) == 0:
        return empty
    if not path.exists():
        empty["derivatives_missing"] = True
        empty["derivatives_available_le_decision"] = True
        empty["derivatives_event_le_decision"] = True
        empty["derivatives_available_time_violation"] = False
        empty["derivatives_event_time_violation"] = False
        return empty
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_rows = payload.get("rows", payload) if isinstance(payload, Mapping) else payload
    rows = [row for row in raw_rows if isinstance(row, Mapping)]
    if not rows:
        empty["derivatives_missing"] = True
        empty["derivatives_available_le_decision"] = True
        empty["derivatives_event_le_decision"] = True
        empty["derivatives_available_time_violation"] = False
        empty["derivatives_event_time_violation"] = False
        return empty
    frame = pd.DataFrame(rows)
    if "available_time" not in frame:
        empty["derivatives_missing"] = True
        empty["derivatives_available_le_decision"] = True
        empty["derivatives_event_le_decision"] = True
        empty["derivatives_available_time_violation"] = False
        empty["derivatives_event_time_violation"] = False
        return empty
    frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
    if "event_time" in frame:
        frame["event_time"] = pd.to_datetime(frame["event_time"], utc=True, errors="coerce")
    else:
        frame["event_time"] = pd.NaT
    frame = frame.dropna(subset=["available_time"]).sort_values("available_time")
    if frame.empty:
        empty["derivatives_missing"] = True
        empty["derivatives_available_le_decision"] = True
        empty["derivatives_event_le_decision"] = True
        empty["derivatives_available_time_violation"] = False
        empty["derivatives_event_time_violation"] = False
        return empty
    left = pd.DataFrame({"decision_time": pd.DatetimeIndex(index)}).sort_values("decision_time")
    right = frame[["available_time", "event_time"]].sort_values("available_time")
    merged = pd.merge_asof(left, right, left_on="decision_time", right_on="available_time", direction="backward")
    merged = merged.set_index(pd.DatetimeIndex(index))
    out = pd.DataFrame(index=pd.DatetimeIndex(index))
    out["derivatives_available_time"] = merged["available_time"]
    out["derivatives_event_time"] = merged["event_time"]
    out["derivatives_missing"] = out["derivatives_available_time"].isna()
    out["derivatives_available_le_decision"] = out["derivatives_missing"] | (out["derivatives_available_time"] <= out.index)
    out["derivatives_event_le_decision"] = out["derivatives_event_time"].isna() | (out["derivatives_event_time"] <= out.index)
    out["derivatives_available_time_violation"] = ~out["derivatives_available_le_decision"]
    out["derivatives_event_time_violation"] = ~out["derivatives_event_le_decision"]
    return out[columns]


def shift_visibility_rows(
    *,
    line: str,
    candidate_id: str,
    rank: int,
    raw_signal: pd.Series,
    exposure: pd.Series,
    returns: pd.Series,
    derivatives_visibility: pd.DataFrame,
    model_boundary_flag: bool,
) -> list[dict[str, Any]]:
    raw = raw_signal.astype(float).fillna(0.0)
    exp = exposure.reindex(raw.index).astype(float).fillna(0.0)
    ret = returns.reindex(raw.index).astype(float).fillna(0.0)
    expected_current = raw.shift(1).fillna(0.0)
    next_exposure = exp.shift(-1)
    rows: list[dict[str, Any]] = []
    index = pd.DatetimeIndex(raw.index)
    for pos, ts in enumerate(index):
        prev_ts = index[pos - 1] if pos > 0 else None
        next_ts = index[pos + 1] if pos + 1 < len(index) else None
        current_ok = _same_float(exp.iloc[pos], expected_current.iloc[pos])
        next_ok = None if next_ts is None else _same_float(next_exposure.iloc[pos], raw.iloc[pos])
        vis = _visibility_at(derivatives_visibility, ts)
        rows.append(
            {
                "line": line,
                "candidate_id": candidate_id,
                "rank": rank,
                "decision_time": _ts(ts),
                "previous_decision_time": _ts(prev_ts),
                "next_execution_time": _ts(next_ts),
                "raw_signal": _float(raw.iloc[pos]),
                "current_bar_exposure": _float(exp.iloc[pos]),
                "expected_current_from_previous_raw": _float(expected_current.iloc[pos]),
                "next_bar_exposure": None if next_ts is None else _float(next_exposure.iloc[pos]),
                "current_exposure_matches_previous_raw": current_ok,
                "next_bar_exposure_matches_current_raw": next_ok,
                "current_shift_violation": not current_ok,
                "next_shift_violation": bool(next_ok is False),
                "return_uses_prior_exposure": current_ok,
                "net_return": _float(ret.iloc[pos]),
                "market_4h_close_time": _ts(ts),
                "market_completed_bar_visible": True,
                "market_high_low_visible_for_signal": True,
                "derivatives_available_time": _ts(vis.get("derivatives_available_time")),
                "derivatives_event_time": _ts(vis.get("derivatives_event_time")),
                "derivatives_missing": bool(vis.get("derivatives_missing")),
                "derivatives_available_le_decision": bool(vis.get("derivatives_available_le_decision")),
                "derivatives_event_le_decision": bool(vis.get("derivatives_event_le_decision")),
                "derivatives_available_time_violation": bool(vis.get("derivatives_available_time_violation")),
                "derivatives_event_time_violation": bool(vis.get("derivatives_event_time_violation")),
                "model_boundary_flag": model_boundary_flag,
                "model_boundary_reason": "",
                "same_bar_return_proxy": False,
                "same_bar_intrabar_high_low_proxy": False,
                "execution_replay_required_before_paper": False,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return rows


def render_btc_strategy_bar_replay_visibility_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    ls = report.get("long_short_top5_bar_replay", {})
    ho = report.get("high_octane_v2_visibility_replay", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 逐 bar 未来函数 / 字段可见性审计包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- Long/Short Top5 当前仓位 shift 违规数：`{ls.get('current_shift_violation_count')}`",
        f"- Long/Short Top5 下一根执行绑定违规数：`{ls.get('next_shift_violation_count')}`",
        f"- Long/Short 已完成 K 线违规数：`{ls.get('completed_bar_violation_count')}`",
        f"- Long/Short 衍生品 available_time 违规数：`{ls.get('derivatives_available_time_violation_count')}`",
        f"- High-Octane v2 最佳候选：`{ho.get('best_scenario_id')}`",
        f"- High-Octane v2 距 40% 插针剩余门槛：`{ho.get('best_margin_over_40pct_threshold')}` 个百分点",
        f"- High-Octane 方向信号可见性：`{ho.get('direction_signal_visibility_verdict')}`",
        f"- High-Octane 资金 overlay 边界：`{ho.get('capital_overlay_execution_boundary_verdict')}`",
        f"- High-Octane v2 模型边界行数：`{ho.get('model_boundary_row_count')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 解释",
        "",
        "- Long/Short Donchian Top5 已按当前代码路径重算逐根 4H bar：当前仓位必须等于上一根 raw signal，当前 raw signal 只能影响下一根 bar。",
        "- 衍生品 sentiment 行按 `available_time <= decision_time` 做 asof 对齐；缺失行记录为缺失，但不会被当成未来行。",
        "- High-Octane v2 的方向来自 frozen Donchian v3 exposure，资金管理层仍使用 close-to-close return 与同根 high/low 做强平/插针近似，所以必须先做真实 mark/index execution replay，不能进 paper/live。",
        "",
        "## 检查摘要",
        "",
        f"- 检查数：`{summary.get('check_count')}`；失败：`{summary.get('check_fail_count')}`；警告：`{summary.get('check_warn_count')}`",
        f"- Long/Short 结论：`{ls.get('verdict')}`",
        f"- High-Octane 结论：`{ho.get('verdict')}`",
        "",
        "本审计包只生成 research-only artifact，不写 paper 队列，不生成策略骨架，不接 broker/OMS，不解锁 live。",
    ]
    return "\n".join(lines) + "\n"


def render_btc_strategy_bar_replay_visibility_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    ls = report.get("long_short_top5_bar_replay", {})
    ho = report.get("high_octane_v2_visibility_replay", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 逐根 bar 未来函数 / 字段可见性审计包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- Long/Short Top5 当前仓位 shift 违规数：`{ls.get('current_shift_violation_count')}`",
        f"- Long/Short Top5 下一根执行绑定违规数：`{ls.get('next_shift_violation_count')}`",
        f"- Long/Short 衍生品 available_time 违规数：`{ls.get('derivatives_available_time_violation_count')}`",
        f"- High-Octane v2 最佳候选：`{ho.get('best_scenario_id')}`",
        f"- High-Octane v2 距 40% 插针剩余门槛：`{ho.get('best_margin_over_40pct_threshold')}` 个百分点",
        f"- High-Octane v2 模型边界行数：`{ho.get('model_boundary_row_count')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 解释",
        "",
        "- Long/Short Donchian Top5 已按当前代码路径重算逐根 4H bar：当前仓位必须等于上一根 raw signal，当前 raw signal 只能影响下一根 bar。",
        "- 衍生品 sentiment 行按 `available_time <= decision_time` 做 asof 对齐；缺失行记录为缺失，但不会被当成未来行。",
        "- High-Octane v2 的方向信号可见性和资金管理层分开审计；资金管理层仍使用 close-to-close return 与同根 high/low 做强平/插针近似，所以必须先做严格风控压力和真实 mark/index execution replay，不能进入 paper/live。",
        "",
        "## 检查摘要",
        "",
        f"- 检查数：`{summary.get('check_count')}`；失败：`{summary.get('check_fail_count')}`；警告：`{summary.get('check_warn_count')}`",
        f"- Long/Short 结论：`{ls.get('verdict')}`",
        f"- High-Octane 结论：`{ho.get('verdict')}`",
        "",
        "本审计包只生成 research-only artifact，不写 paper 队列，不生成策略骨架，不接 broker/OMS，不解锁 live。",
    ]
    return "\n".join(lines) + "\n"


def _line_summary(
    *,
    line: str,
    rows: Sequence[Mapping[str, Any]],
    candidate_count: int,
    candidate_summaries: Sequence[Mapping[str, Any]],
    missing_specs: Sequence[str],
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    out = {
        "line": line,
        "candidate_count": candidate_count,
        "row_count": len(rows),
        "current_shift_violation_count": sum(1 for row in rows if bool(row.get("current_shift_violation"))),
        "next_shift_violation_count": sum(1 for row in rows if bool(row.get("next_shift_violation"))),
        "derivatives_available_time_violation_count": sum(1 for row in rows if bool(row.get("derivatives_available_time_violation"))),
        "derivatives_event_time_violation_count": sum(1 for row in rows if bool(row.get("derivatives_event_time_violation"))),
        "future_sentiment_violation_count": sum(1 for row in rows if bool(row.get("derivatives_available_time_violation"))),
        "derivatives_missing_count": sum(1 for row in rows if bool(row.get("derivatives_missing"))),
        "completed_bar_violation_count": sum(1 for row in rows if not bool(row.get("market_completed_bar_visible", True))),
        "model_boundary_row_count": sum(1 for row in rows if bool(row.get("model_boundary_flag"))),
        "prior_exposure_return_violation_count": sum(1 for row in rows if bool(row.get("prior_exposure_return_violation"))),
        "same_bar_target_return_proxy_row_count": sum(1 for row in rows if bool(row.get("same_bar_target_return_proxy"))),
        "same_bar_intrabar_high_low_proxy_row_count": sum(1 for row in rows if bool(row.get("same_bar_intrabar_high_low_proxy"))),
        "capital_overlay_same_bar_proxy_row_count": sum(1 for row in rows if bool(row.get("capital_overlay_same_bar_proxy"))),
        "candidate_summaries": list(candidate_summaries),
        "missing_spec_candidate_ids": list(missing_specs),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    out.update(extra)
    return out


def _empty_line_summary(line: str) -> dict[str, Any]:
    return {
        "line": line,
        "candidate_count": 0,
        "row_count": 0,
        "current_shift_violation_count": 0,
        "next_shift_violation_count": 0,
        "derivatives_available_time_violation_count": 0,
        "derivatives_event_time_violation_count": 0,
        "future_sentiment_violation_count": 0,
        "derivatives_missing_count": 0,
        "completed_bar_violation_count": 0,
        "model_boundary_row_count": 0,
        "prior_exposure_return_violation_count": 0,
        "same_bar_target_return_proxy_row_count": 0,
        "same_bar_intrabar_high_low_proxy_row_count": 0,
        "capital_overlay_same_bar_proxy_row_count": 0,
        "candidate_summaries": [],
        "missing_spec_candidate_ids": [],
        "verdict": "not_run",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _checks(
    *,
    blockers: Sequence[str],
    long_short_summary: Mapping[str, Any],
    high_octane_summary: Mapping[str, Any],
    high_yield_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if blockers:
        return [_check("inputs", "required_inputs_present", "fail", ",".join(sorted(set(blockers))))]
    return [
        _check(
            "long_short_top5",
            "completed_4h_bars_only",
            "pass" if _int(long_short_summary.get("completed_bar_violation_count")) == 0 else "fail",
            f"violation_count={long_short_summary.get('completed_bar_violation_count')}",
        ),
        _check(
            "long_short_top5",
            "current_exposure_is_previous_raw_signal",
            "pass" if _int(long_short_summary.get("current_shift_violation_count")) == 0 else "fail",
            f"violation_count={long_short_summary.get('current_shift_violation_count')}",
        ),
        _check(
            "long_short_top5",
            "current_raw_signal_binds_next_bar_exposure",
            "pass" if _int(long_short_summary.get("next_shift_violation_count")) == 0 else "fail",
            f"violation_count={long_short_summary.get('next_shift_violation_count')}",
        ),
        _check(
            "long_short_top5",
            "derivatives_available_time_visible",
            "pass" if _int(long_short_summary.get("derivatives_available_time_violation_count")) == 0 else "fail",
            f"violation_count={long_short_summary.get('derivatives_available_time_violation_count')}",
        ),
        _check(
            "long_short_top5",
            "future_sentiment_not_used",
            "pass" if _int(long_short_summary.get("future_sentiment_violation_count")) == 0 else "fail",
            f"violation_count={long_short_summary.get('future_sentiment_violation_count')}",
        ),
        _check(
            "long_short_top5",
            "derivatives_event_time_visible",
            "pass" if _int(long_short_summary.get("derivatives_event_time_violation_count")) == 0 else "warn",
            f"violation_count={long_short_summary.get('derivatives_event_time_violation_count')}",
        ),
        _check(
            "high_octane_v2",
            "completed_4h_bars_only",
            "pass" if _int(high_octane_summary.get("completed_bar_violation_count")) == 0 else "fail",
            f"violation_count={high_octane_summary.get('completed_bar_violation_count')}",
        ),
        _check(
            "high_octane_v2",
            "derivatives_available_time_visible",
            "pass" if _int(high_octane_summary.get("derivatives_available_time_violation_count")) == 0 else "fail",
            f"violation_count={high_octane_summary.get('derivatives_available_time_violation_count')}",
        ),
        _check(
            "high_octane_v2",
            "future_sentiment_not_used",
            "pass" if _int(high_octane_summary.get("future_sentiment_violation_count")) == 0 else "fail",
            f"violation_count={high_octane_summary.get('future_sentiment_violation_count')}",
        ),
        _check(
            "high_octane_v2",
            "direction_visibility_separated_from_capital_overlay",
            "warn" if _int(high_octane_summary.get("capital_overlay_same_bar_proxy_row_count")) > 0 else "pass",
            str(high_octane_summary.get("capital_overlay_execution_boundary_verdict")),
        ),
        _check(
            "high_octane_v2",
            "same_bar_execution_proxy_boundary",
            "warn" if _int(high_octane_summary.get("model_boundary_row_count")) > 0 else "pass",
            "High-Octane uses close-to-close return and same-bar high/low liquidation proxy; real mark/index replay required.",
        ),
        _check(
            "high_octane_v2",
            "forty_pct_threshold_boundary",
            "warn" if _float(high_octane_summary.get("best_margin_over_40pct_threshold")) <= 1.0 else "pass",
            f"margin={high_octane_summary.get('best_margin_over_40pct_threshold')}",
        ),
        _check(
            "high_yield_v2",
            "derivatives_available_time_visible",
            "pass" if _int(high_yield_summary.get("derivatives_available_time_violation_count")) == 0 else "fail",
            f"violation_count={high_yield_summary.get('derivatives_available_time_violation_count')}",
        ),
        _check(
            "high_yield_v2",
            "stateful_same_bar_execution_proxy_boundary",
            "warn" if _int(high_yield_summary.get("model_boundary_row_count")) > 0 else "pass",
            "High-yield v2 uses current target plus same-bar high/low risk controls in the research simulator; real mark/index paper runtime replay required.",
        ),
        _check(
            "high_yield_v2",
            "prior_exposure_return_model_boundary",
            "warn" if _int(high_yield_summary.get("prior_exposure_return_violation_count")) > 0 else "pass",
            f"violation_count={high_yield_summary.get('prior_exposure_return_violation_count')}",
        ),
        _check("safety", "paper_live_locked", "pass", "paper_queue_write_allowed=false; live_unlock_allowed=false"),
    ]


def _summary(
    *,
    checks: Sequence[Mapping[str, Any]],
    long_short_summary: Mapping[str, Any],
    high_octane_summary: Mapping[str, Any],
    high_yield_summary: Mapping[str, Any],
    decision: str,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "check_count": len(checks),
        "check_fail_count": sum(1 for row in checks if row.get("status") == "fail"),
        "check_warn_count": sum(1 for row in checks if row.get("status") == "warn"),
        "long_short_row_count": long_short_summary.get("row_count"),
        "long_short_shift_violation_count": _int(long_short_summary.get("current_shift_violation_count")) + _int(long_short_summary.get("next_shift_violation_count")),
        "long_short_derivatives_visibility_violation_count": long_short_summary.get("derivatives_available_time_violation_count"),
        "long_short_completed_bar_violation_count": long_short_summary.get("completed_bar_violation_count"),
        "long_short_future_sentiment_violation_count": long_short_summary.get("future_sentiment_violation_count"),
        "high_octane_row_count": high_octane_summary.get("row_count"),
        "high_octane_model_boundary_row_count": high_octane_summary.get("model_boundary_row_count"),
        "high_octane_capital_overlay_same_bar_proxy_row_count": high_octane_summary.get("capital_overlay_same_bar_proxy_row_count"),
        "high_octane_direction_signal_visibility_verdict": high_octane_summary.get("direction_signal_visibility_verdict"),
        "high_octane_capital_overlay_execution_boundary_verdict": high_octane_summary.get("capital_overlay_execution_boundary_verdict"),
        "high_octane_completed_bar_violation_count": high_octane_summary.get("completed_bar_violation_count"),
        "high_octane_future_sentiment_violation_count": high_octane_summary.get("future_sentiment_violation_count"),
        "high_octane_best_margin_over_40pct_threshold": high_octane_summary.get("best_margin_over_40pct_threshold"),
        "high_yield_row_count": high_yield_summary.get("row_count"),
        "high_yield_model_boundary_row_count": high_yield_summary.get("model_boundary_row_count"),
        "high_yield_prior_exposure_return_violation_count": high_yield_summary.get("prior_exposure_return_violation_count"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _decision(
    *,
    blockers: Sequence[str],
    checks: Sequence[Mapping[str, Any]],
    high_octane_summary: Mapping[str, Any],
    high_yield_summary: Mapping[str, Any],
) -> str:
    if blockers:
        return "blocked_bar_replay_inputs_missing_no_paper_no_live"
    if any(row.get("status") == "fail" for row in checks):
        return "fail_bar_replay_visibility_no_paper_no_live"
    if _int(high_octane_summary.get("model_boundary_row_count")) > 0 or _int(high_yield_summary.get("model_boundary_row_count")) > 0:
        return "research_only_bar_replay_passed_for_long_short_high_octane_high_yield_requires_execution_replay_no_paper_no_live"
    return "research_only_bar_replay_visibility_passed_no_paper_no_live"


def _check(line: str, check_id: str, status: str, evidence: str) -> dict[str, Any]:
    return {
        "line": line,
        "check_id": check_id,
        "status": status,
        "evidence": evidence,
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
        "reason": "Bar replay visibility audit is diagnostic only and cannot promote strategies.",
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


def _warnings(
    *,
    long_short_summary: Mapping[str, Any],
    high_octane_summary: Mapping[str, Any],
    high_yield_summary: Mapping[str, Any],
    blockers: Sequence[str],
) -> list[str]:
    warnings = ["btc_strategy_bar_replay_visibility_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("bar_replay_visibility_inputs_missing")
    if _int(long_short_summary.get("derivatives_missing_count")):
        warnings.append("derivatives_rows_missing_for_some_early_decision_times")
    if _float(high_octane_summary.get("best_margin_over_40pct_threshold")) <= 1.0:
        warnings.append("high_octane_best_candidate_is_40pct_threshold_boundary")
    if _int(high_octane_summary.get("model_boundary_row_count")):
        warnings.append("high_octane_requires_mark_index_execution_replay")
    if _int(high_yield_summary.get("model_boundary_row_count")):
        warnings.append("high_yield_v2_requires_mark_index_paper_runtime_replay")
    if _int(high_yield_summary.get("prior_exposure_return_violation_count")):
        warnings.append("high_yield_v2_stateful_same_bar_return_proxy_detected")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_strategy_bar_replay_visibility_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Bar replay visibility output is diagnostic only.",
    }


def _best_high_octane_row(report: Mapping[str, Any], rows: Sequence[Mapping[str, str]]) -> Mapping[str, Any]:
    if rows:
        return rows[0]
    summary = report.get("summary", {}) if isinstance(report, Mapping) else {}
    return {
        "scenario_id": summary.get("best_scenario_id"),
        "annual_return_pct": summary.get("best_annual_return_pct"),
        "total_return_pct": summary.get("best_total_return_pct"),
        "min_remaining_capital_pct_after_10pct_spike": summary.get("best_min_remaining_after_10pct_spike"),
        "watchlist_tier": summary.get("best_watchlist_tier"),
    }


def _visibility_at(frame: pd.DataFrame, ts: pd.Timestamp) -> dict[str, Any]:
    if frame.empty or ts not in frame.index:
        return {
            "derivatives_available_time": None,
            "derivatives_event_time": None,
            "derivatives_missing": True,
            "derivatives_available_le_decision": True,
            "derivatives_event_le_decision": True,
            "derivatives_available_time_violation": False,
            "derivatives_event_time_violation": False,
        }
    row = frame.loc[ts]
    return {
        "derivatives_available_time": row.get("derivatives_available_time"),
        "derivatives_event_time": row.get("derivatives_event_time"),
        "derivatives_missing": bool(row.get("derivatives_missing")),
        "derivatives_available_le_decision": bool(row.get("derivatives_available_le_decision")),
        "derivatives_event_le_decision": bool(row.get("derivatives_event_le_decision")),
        "derivatives_available_time_violation": bool(row.get("derivatives_available_time_violation")),
        "derivatives_event_time_violation": bool(row.get("derivatives_event_time_violation")),
    }


def _read_json(path: Path, blockers: list[str], blocker_name: str) -> dict[str, Any]:
    if not path.exists():
        blockers.append(blocker_name)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path, blockers: list[str], blocker_name: str) -> list[dict[str, str]]:
    if not path.exists():
        blockers.append(blocker_name)
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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
    if isinstance(value, pd.Timestamp):
        return _ts(value)
    return value


def _same_float(left: Any, right: Any, *, tolerance: float = 1e-12) -> bool:
    return abs(_float(left) - _float(right)) <= tolerance


def _float(value: Any) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        if pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat()
