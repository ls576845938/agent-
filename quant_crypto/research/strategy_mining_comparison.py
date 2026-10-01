from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_shared.core.time import ensure_utc

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_EXTENDED_STRATEGY_MINING_COMPARISON_VERSION = "btc_extended_strategy_mining_comparison_v1"

DEFAULT_MARKET_DB = Path("data/market_data.sqlite")
DEFAULT_GA_REPORT = Path("artifacts/btc_ga_factor_mining/latest/ga_factor_mining_report.json")
DEFAULT_GA_REVIEW_PACKET = Path("artifacts/btc_ga_factor_mining/latest/ga_candidate_review_packet.json")
DEFAULT_DERIVATIVES_REPORT = Path("artifacts/btc_derivatives_sentiment/latest/btc_derivatives_sentiment_report.json")
DEFAULT_DERIVATIVES_FETCH_REPORT = Path(
    "artifacts/btc_derivatives_sentiment/latest/btc_binance_vision_derivatives_fetch_report.json"
)
DEFAULT_DERIVATIVES_STRATEGY_GATE = Path(
    "artifacts/btc_derivatives_sentiment/latest/btc_derivatives_strategy_gate_report.json"
)
DEFAULT_TIMESFM_REPORT = Path(
    "artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest/"
    "btc_timesfm_vs_trend_baseline_oos_report.json"
)
DEFAULT_INTRADAY_REPORT = Path("artifacts/btc_intraday_trend_v1/latest/btc_intraday_trend_v1_report.json")
DEFAULT_INTRADAY_GATE_REPORT = Path(
    "artifacts/btc_intraday_trend_v1/latest/btc_4h_atr_channel_validation_gate_report.json"
)
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_strategy_mining/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_extended_strategy_mining_comparison_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_extended_strategy_mining_comparison_summary_cn.md"

DERIVATIVE_VALUE_FIELDS = (
    "open_interest_usd",
    "funding_rate",
    "long_liquidation_usd",
    "short_liquidation_usd",
    "long_short_ratio",
)

UNSAFE_TRUE_KEYS = {
    "live_order_allowed",
    "live_unlock_allowed",
    "paper_queue_write_allowed",
    "paper_or_live_unlock_allowed",
    "paper_candidate_allowed",
    "paper_candidate_created",
    "order_endpoint_used",
    "private_endpoint_used",
    "real_order_submitted",
    "real_orders_created",
    "oms_access_allowed",
    "broker_access_allowed",
}


def write_btc_extended_strategy_mining_comparison(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    ga_report_path: Path = DEFAULT_GA_REPORT,
    ga_review_path: Path = DEFAULT_GA_REVIEW_PACKET,
    derivatives_report_path: Path = DEFAULT_DERIVATIVES_REPORT,
    derivatives_fetch_report_path: Path = DEFAULT_DERIVATIVES_FETCH_REPORT,
    derivatives_strategy_gate_path: Path = DEFAULT_DERIVATIVES_STRATEGY_GATE,
    timesfm_report_path: Path = DEFAULT_TIMESFM_REPORT,
    intraday_report_path: Path = DEFAULT_INTRADAY_REPORT,
    intraday_gate_report_path: Path = DEFAULT_INTRADAY_GATE_REPORT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "btc_extended_strategy_mining_comparison_report.json"
    markdown_path = output_dir / "btc_extended_strategy_mining_comparison_summary_cn.md"
    report = build_btc_extended_strategy_mining_comparison(
        market_db_path=market_db_path,
        ga_report_path=ga_report_path,
        ga_review_path=ga_review_path,
        derivatives_report_path=derivatives_report_path,
        derivatives_fetch_report_path=derivatives_fetch_report_path,
        derivatives_strategy_gate_path=derivatives_strategy_gate_path,
        timesfm_report_path=timesfm_report_path,
        intraday_report_path=intraday_report_path,
        intraday_gate_report_path=intraday_gate_report_path,
        report_paths={
            "json": _portable_path(report_path),
            "markdown_cn": _portable_path(markdown_path),
        },
        generated_at_utc=generated_at_utc,
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_btc_extended_strategy_mining_comparison_markdown(report), encoding="utf-8")
    return report


def build_btc_extended_strategy_mining_comparison(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    ga_report_path: Path = DEFAULT_GA_REPORT,
    ga_review_path: Path = DEFAULT_GA_REVIEW_PACKET,
    derivatives_report_path: Path = DEFAULT_DERIVATIVES_REPORT,
    derivatives_fetch_report_path: Path = DEFAULT_DERIVATIVES_FETCH_REPORT,
    derivatives_strategy_gate_path: Path = DEFAULT_DERIVATIVES_STRATEGY_GATE,
    timesfm_report_path: Path = DEFAULT_TIMESFM_REPORT,
    intraday_report_path: Path = DEFAULT_INTRADAY_REPORT,
    intraday_gate_report_path: Path = DEFAULT_INTRADAY_GATE_REPORT,
    report_paths: Mapping[str, str] | None = None,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    sources = {
        "ga_report": _read_json(ga_report_path),
        "ga_review_packet": _read_json(ga_review_path),
        "derivatives_sentiment_report": _read_json(derivatives_report_path),
        "derivatives_history_fetch_report": _read_json(derivatives_fetch_report_path),
        "derivatives_strategy_gate_report": _read_json(derivatives_strategy_gate_path),
        "timesfm_vs_trend_report": _read_json(timesfm_report_path),
        "intraday_trend_report": _read_json(intraday_report_path),
        "intraday_validation_gate_report": _read_json(intraday_gate_report_path),
    }
    source_paths = {
        "ga_report": _portable_path(ga_report_path),
        "ga_review_packet": _portable_path(ga_review_path),
        "derivatives_sentiment_report": _portable_path(derivatives_report_path),
        "derivatives_history_fetch_report": _portable_path(derivatives_fetch_report_path),
        "derivatives_strategy_gate_report": _portable_path(derivatives_strategy_gate_path),
        "timesfm_vs_trend_report": _portable_path(timesfm_report_path),
        "intraday_trend_report": _portable_path(intraday_report_path),
        "intraday_validation_gate_report": _portable_path(intraday_gate_report_path),
    }

    blockers = _missing_source_blockers(sources)
    warnings: list[str] = []
    unsafe_flags = _unsafe_flags(sources)
    blockers.extend(f"btc_extended_strategy_mining_unsafe_flag:{flag}" for flag in unsafe_flags)

    ohlcv_context = _sqlite_ohlcv_coverage(market_db_path)
    if not ohlcv_context.get("coverage_at_least_90d"):
        blockers.append("btc_1h_ohlcv_coverage_below_90_days")
    if ohlcv_context.get("coverage_at_least_90d") and not ohlcv_context.get("coverage_at_least_180d"):
        warnings.append("btc_1h_ohlcv_coverage_90d_pass_but_below_180d")

    sentiment_context = _derivatives_sentiment_context(
        _mapping(sources["derivatives_sentiment_report"]),
        _mapping(sources["derivatives_history_fetch_report"]),
        _mapping(sources["derivatives_strategy_gate_report"]),
    )
    if sentiment_context.get("visible_row_count", 0) < 720:
        blockers.append("btc_derivatives_sentiment_visible_rows_below_720")
    if sentiment_context.get("extended_fetch_status") == "blocked":
        warnings.append("btc_derivatives_sentiment_free_source_extended_fetch_blocked")

    ga_context = _ga_context(_mapping(sources["ga_report"]), _mapping(sources["ga_review_packet"]))
    trend_context = _trend_baseline_context(_mapping(sources["timesfm_vs_trend_report"]), _mapping(sources["ga_report"]))
    intraday_context = _intraday_context(
        _mapping(sources["intraday_trend_report"]),
        _mapping(sources["intraday_validation_gate_report"]),
    )
    timesfm_context = _timesfm_context(_mapping(sources["timesfm_vs_trend_report"]))

    comparison_rows = [
        ga_context["comparison_row"],
        trend_context["comparison_row"],
        intraday_context["comparison_row"],
        timesfm_context["comparison_row"],
    ]
    extended_shortlist = _extended_research_shortlist(
        ga_context=ga_context,
        trend_context=trend_context,
        intraday_context=intraday_context,
        timesfm_context=timesfm_context,
    )
    excluded_current_batch = _excluded_ga_current_batch(ga_context)
    manual_review = _manual_review_items(
        ga_context=ga_context,
        sentiment_context=sentiment_context,
        intraday_context=intraday_context,
        timesfm_context=timesfm_context,
    )

    payload = {
        "schema_version": BTC_EXTENDED_STRATEGY_MINING_COMPARISON_VERSION,
        "status": "blocked" if blockers else "complete_research_only",
        "scope": "btc_strategy_mining_extended_research_only_comparison",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "timeframe": "1h primary, 4h intraday candidate comparison",
        "read_only": True,
        "data_context": {
            "ohlcv_1h": ohlcv_context,
            "derivatives_sentiment": sentiment_context,
        },
        "comparison_universe": comparison_rows,
        "extended_research_shortlist": extended_shortlist,
        "excluded_current_batch": excluded_current_batch,
        "manual_review_required": manual_review,
        "gate": {
            "report_decision": "extended_research_shortlist_only",
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "broker_access_allowed": False,
            "oms_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "research-only comparison; shortlist members require further confirmation before any paper review",
        },
        "guardrails": {
            "research_only": True,
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
        },
        "source_paths": source_paths,
        "source_status": {
            name: {
                "present": bool(payload),
                "status": _mapping(payload).get("status"),
                "decision": _mapping(payload).get("decision"),
                "artifact_hash": _mapping(payload).get("artifact_hash"),
            }
            for name, payload in sources.items()
        },
        "report_paths": dict(report_paths or {}),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="btc_extended_research_shortlist_only_no_paper_no_live"
        if not blockers
        else "btc_extended_research_comparison_blocked",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
        input_hashes={
            "sources": stable_payload_hash({name: payload or {} for name, payload in sources.items()}),
            "source_paths": stable_payload_hash(source_paths),
            "ohlcv_context": stable_payload_hash(ohlcv_context),
            "sentiment_context": stable_payload_hash(sentiment_context),
        },
    )


def render_btc_extended_strategy_mining_comparison_markdown(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    data = _mapping(report.get("data_context"))
    ohlcv = _mapping(data.get("ohlcv_1h"))
    sentiment = _mapping(data.get("derivatives_sentiment"))
    shortlist = _list_of_mappings(report.get("extended_research_shortlist"))
    comparison = _list_of_mappings(report.get("comparison_universe"))
    excluded = _list_of_mappings(report.get("excluded_current_batch"))
    manual_review = [str(item) for item in report.get("manual_review_required", [])]

    lines = [
        "# BTC 扩展研究短名单对比报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        f"- 真实下单：`{gate.get('live_order_allowed')}`",
        "",
        "## 数据窗口",
        "",
        f"- BTCUSDT 1H OHLCV：`{ohlcv.get('start_time')}` 到 `{ohlcv.get('end_time')}`，"
        f"`{ohlcv.get('row_count')}` 行，约 `{ohlcv.get('coverage_days')}` 天。",
        f"- OHLCV 90 天通过：`{ohlcv.get('coverage_at_least_90d')}`；180 天通过：`{ohlcv.get('coverage_at_least_180d')}`。",
        f"- Derivatives sentiment：`{sentiment.get('event_start_time')}` 到 `{sentiment.get('event_end_time')}`，"
        f"`{sentiment.get('row_count')}` 行，可见行 `{sentiment.get('visible_row_count')}`。",
        f"- 180 天 sentiment 免费源扩展：`{sentiment.get('extended_fetch_status')}`；"
        f"错误：`{sentiment.get('extended_fetch_errors')}`。",
        "",
        "## 扩展研究短名单",
        "",
    ]
    if shortlist:
        lines.extend(
            [
                "| 名称 | 来源 | 状态 | 关键证据 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in shortlist:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md(row.get("candidate_id")),
                        _md(row.get("source_type")),
                        _md(row.get("shortlist_status")),
                        _md(row.get("evidence_summary")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- 本轮没有候选进入扩展研究短名单。")
    lines.extend(["", "## 全部对比对象", ""])
    lines.extend(["| 对象 | 来源 | 结论 | 关键指标 |", "| --- | --- | --- | --- |"])
    for row in comparison:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("candidate_id")),
                    _md(row.get("source_type")),
                    _md(row.get("shortlist_decision")),
                    _md(row.get("metric_summary")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## 当前批次未入短名单", ""])
    if excluded:
        for row in excluded[:20]:
            lines.append(
                f"- `{row.get('candidate_id')}`：`{row.get('review_verdict')}`；"
                f"原因 `{row.get('review_flags')}`。"
            )
    else:
        lines.append("- 无。")
    lines.extend(["", "## 人工复核事项", ""])
    for item in manual_review:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "结论：本报告只输出扩展研究短名单，不写 paper 队列，不解锁 live，不触达 OMS/broker。",
            "",
        ]
    )
    return "\n".join(lines)


def _sqlite_ohlcv_coverage(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "status": "missing",
            "db_path": _portable_path(db_path),
            "row_count": 0,
            "coverage_days": 0.0,
            "coverage_at_least_90d": False,
            "coverage_at_least_180d": False,
        }
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*), MIN(open_time), MAX(close_time), MIN(open_time_ms), MAX(close_time_ms)
            FROM market_klines
            WHERE exchange = 'binance_spot'
              AND symbol = 'BTCUSDT'
              AND interval = '1h'
            """
        ).fetchone()
    count = int(row[0] or 0)
    start_ms = int(row[3] or 0)
    end_ms = int(row[4] or 0)
    coverage_days = round(max(0.0, (end_ms - start_ms + 1) / 1000.0 / 86400.0), 3) if count else 0.0
    return {
        "status": "complete" if count else "missing",
        "db_path": _portable_path(db_path),
        "exchange": "binance_spot",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "row_count": count,
        "start_time": row[1],
        "end_time": row[2],
        "coverage_days": coverage_days,
        "coverage_at_least_90d": coverage_days >= 90.0,
        "coverage_at_least_180d": coverage_days >= 180.0,
    }


def _derivatives_sentiment_context(
    report: Mapping[str, Any],
    fetch_report: Mapping[str, Any],
    strategy_gate: Mapping[str, Any],
) -> dict[str, Any]:
    source_path = Path(str(report.get("source_path") or ""))
    rows_coverage = _derivatives_rows_coverage(source_path) if source_path else {}
    latest = _mapping(report.get("features"))
    quality = _mapping(report.get("quality"))
    contract = _mapping(strategy_gate.get("feature_contract"))
    return {
        "status": report.get("status") or "missing",
        "source_path": _portable_path(source_path) if source_path else "",
        "row_count": _int_value(report.get("row_count") or rows_coverage.get("row_count")),
        "visible_row_count": _int_value(latest.get("visible_row_count") or rows_coverage.get("row_count")),
        "event_start_time": rows_coverage.get("event_start_time"),
        "event_end_time": rows_coverage.get("event_end_time") or latest.get("latest_event_time"),
        "available_start_time": rows_coverage.get("available_start_time"),
        "available_end_time": rows_coverage.get("available_end_time") or latest.get("latest_available_time"),
        "field_non_null_counts": rows_coverage.get("field_non_null_counts", {}),
        "role_coverage": quality.get("role_coverage", {}),
        "feature_contract_inputs": [str(item) for item in contract.get("inputs", [])],
        "derived_features": [str(item) for item in contract.get("derived_features", [])],
        "pit_required": bool(quality.get("pit_required", True)),
        "available_time_rule": "derivatives rows are visible only when available_time <= decision_time",
        "extended_fetch_status": fetch_report.get("status") or "missing",
        "extended_fetch_blockers": [str(item) for item in fetch_report.get("blockers", [])],
        "extended_fetch_errors": [str(item) for item in fetch_report.get("fallback_errors", [])],
    }


def _derivatives_rows_coverage(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    rows = _list_of_mappings(_mapping(payload).get("rows") if isinstance(payload, Mapping) else payload)
    event_times = sorted(str(row.get("event_time")) for row in rows if row.get("event_time"))
    available_times = sorted(str(row.get("available_time")) for row in rows if row.get("available_time"))
    return {
        "row_count": len(rows),
        "event_start_time": event_times[0] if event_times else None,
        "event_end_time": event_times[-1] if event_times else None,
        "available_start_time": available_times[0] if available_times else None,
        "available_end_time": available_times[-1] if available_times else None,
        "field_non_null_counts": {
            field: sum(1 for row in rows if row.get(field) is not None) for field in DERIVATIVE_VALUE_FIELDS
        },
        "non_final_rows": sum(1 for row in rows if row.get("is_final") is False),
    }


def _ga_context(report: Mapping[str, Any], review_packet: Mapping[str, Any]) -> dict[str, Any]:
    ga_config = _mapping(report.get("ga_config"))
    holdout = _mapping(report.get("confirmatory_holdout"))
    coverage = _mapping(report.get("data_coverage"))
    review_summary = _mapping(review_packet.get("review_summary"))
    shortlist_ids = [str(item) for item in holdout.get("shortlist_for_extended_research_only", []) if item]
    candidate_rows = _list_of_mappings(holdout.get("candidate_rows"))
    shortlist_rows = [row for row in candidate_rows if str(row.get("candidate_id")) in set(shortlist_ids)]
    metric_summary = (
        f"selected={ga_config.get('selected_candidate_count')}, trial={ga_config.get('trial_count')}, "
        f"holdout_survivors={holdout.get('surviving_candidate_count')}"
    )
    return {
        "status": report.get("status") or "missing",
        "decision": report.get("decision"),
        "coverage": {
            "merged_rows_after_lookback": _int_value(coverage.get("merged_rows_after_lookback")),
            "derivatives_feature_rows_after_lookback": _int_value(
                coverage.get("derivatives_feature_rows_after_lookback")
            ),
            "ga_selection_rows": _int_value(coverage.get("ga_selection_rows")),
            "confirmatory_holdout_rows": _int_value(coverage.get("confirmatory_holdout_rows")),
        },
        "ga_config": ga_config,
        "holdout": holdout,
        "review_summary": review_summary,
        "shortlist_ids": shortlist_ids,
        "shortlist_rows": shortlist_rows,
        "candidate_reviews": _list_of_mappings(review_packet.get("candidate_reviews")),
        "comparison_row": {
            "candidate_id": "btc_ga_factor_mining_current_batch",
            "source_type": "ga_expression_mining",
            "status": report.get("status") or "missing",
            "shortlist_decision": "not_shortlisted_no_holdout_survivors"
            if not shortlist_ids
            else "shortlisted_expression_review_only",
            "metric_summary": metric_summary,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _trend_baseline_context(timesfm_report: Mapping[str, Any], ga_report: Mapping[str, Any]) -> dict[str, Any]:
    best = _best_trend_baseline(timesfm_report) or _best_ga_holdout_baseline(ga_report)
    metrics = _mapping(best.get("evaluation") or best.get("holdout_metrics"))
    candidate_id = str(best.get("model_id") or best.get("baseline_id") or "btc_trend_baseline_missing")
    pf = _float_value(metrics.get("profit_factor"))
    total_return = _float_value(metrics.get("total_return"))
    shortlist = pf >= 1.0 and total_return >= 0.0
    return {
        "candidate_id": candidate_id,
        "metrics": metrics,
        "shortlist": shortlist,
        "comparison_row": {
            "candidate_id": candidate_id,
            "source_type": "existing_btc_trend_baseline",
            "status": "complete" if best else "missing",
            "shortlist_decision": "extended_research_baseline_comparator_only"
            if shortlist
            else "not_shortlisted_trend_baseline_failed_current_comparison",
            "metric_summary": _metric_summary(metrics),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _intraday_context(report: Mapping[str, Any], gate_report: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(gate_report.get("selected_metrics"))
    guardrails = _mapping(gate_report.get("guardrails") or report.get("guardrails"))
    validation = _mapping(gate_report.get("validation_checks"))
    candidate_id = str(gate_report.get("candidate_id") or "btc_intraday_trend_candidate_missing")
    passed = str(gate_report.get("status") or "").startswith("research_validation_passed")
    unsafe = bool(
        guardrails.get("live_order_allowed")
        or guardrails.get("order_endpoint_used")
        or guardrails.get("private_endpoint_used")
        or guardrails.get("real_order_submitted")
    )
    shortlist = passed and not unsafe and bool(validation.get("walk_forward_pass_rate", True))
    return {
        "candidate_id": candidate_id,
        "metrics": selected,
        "shortlist": shortlist,
        "comparison_row": {
            "candidate_id": candidate_id,
            "source_type": "intraday_candidate_4h_atr_channel",
            "status": gate_report.get("status") or report.get("status") or "missing",
            "shortlist_decision": "extended_research_manual_review_only"
            if shortlist
            else "not_shortlisted_intraday_gate_not_passed",
            "metric_summary": _intraday_metric_summary(selected),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _timesfm_context(report: Mapping[str, Any]) -> dict[str, Any]:
    row = _model_metric_row(report, "timesfm_zero_shot_h24")
    metrics = _mapping(row.get("evaluation"))
    best_trend = _best_trend_baseline(report)
    best_trend_metrics = _mapping(best_trend.get("evaluation")) if best_trend else {}
    pf = _float_value(metrics.get("profit_factor"))
    beats_trend = pf > _float_value(best_trend_metrics.get("profit_factor"))
    return {
        "candidate_id": "timesfm_zero_shot_h24",
        "metrics": metrics,
        "shortlist": bool(beats_trend and pf >= 1.0),
        "beats_trend_baseline": beats_trend,
        "comparison_row": {
            "candidate_id": "timesfm_zero_shot_h24",
            "source_type": "timesfm_auxiliary_forecast",
            "status": report.get("status") or "missing",
            "shortlist_decision": "risk_auxiliary_only_not_strategy_shortlist"
            if not beats_trend
            else "extended_research_auxiliary_only",
            "metric_summary": _metric_summary(metrics),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _extended_research_shortlist(
    *,
    ga_context: Mapping[str, Any],
    trend_context: Mapping[str, Any],
    intraday_context: Mapping[str, Any],
    timesfm_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _list_of_mappings(ga_context.get("shortlist_rows")):
        rows.append(
            {
                "candidate_id": row.get("candidate_id"),
                "source_type": "ga_expression_mining",
                "shortlist_status": "extended_research_only_holdout_and_cost_survived",
                "evidence_summary": _metric_summary(_mapping(row.get("holdout_metrics"))),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    if trend_context.get("shortlist"):
        rows.append(
            {
                "candidate_id": trend_context.get("candidate_id"),
                "source_type": "existing_btc_trend_baseline",
                "shortlist_status": "extended_research_baseline_comparator_only",
                "evidence_summary": _metric_summary(_mapping(trend_context.get("metrics"))),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    if intraday_context.get("shortlist"):
        rows.append(
            {
                "candidate_id": intraday_context.get("candidate_id"),
                "source_type": "intraday_candidate_4h_atr_channel",
                "shortlist_status": "extended_research_manual_review_only",
                "evidence_summary": _intraday_metric_summary(_mapping(intraday_context.get("metrics"))),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    if timesfm_context.get("shortlist"):
        rows.append(
            {
                "candidate_id": timesfm_context.get("candidate_id"),
                "source_type": "timesfm_auxiliary_forecast",
                "shortlist_status": "extended_research_auxiliary_only",
                "evidence_summary": _metric_summary(_mapping(timesfm_context.get("metrics"))),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return rows


def _excluded_ga_current_batch(ga_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    shortlisted = set(str(item) for item in ga_context.get("shortlist_ids", []))
    rows: list[dict[str, Any]] = []
    for candidate in _list_of_mappings(ga_context.get("candidate_reviews")):
        candidate_id = str(candidate.get("candidate_id") or candidate.get("expression_hash") or "")
        if candidate_id in shortlisted:
            continue
        rows.append(
            {
                "candidate_id": candidate_id,
                "source_type": "ga_expression_mining",
                "review_verdict": candidate.get("review_verdict") or "not_shortlisted_current_batch",
                "review_flags": [str(item) for item in candidate.get("review_flags", [])],
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return rows


def _manual_review_items(
    *,
    ga_context: Mapping[str, Any],
    sentiment_context: Mapping[str, Any],
    intraday_context: Mapping[str, Any],
    timesfm_context: Mapping[str, Any],
) -> list[str]:
    items = [
        "当前报告不得写入 paper 队列，也不得解锁 live。",
        "GA 本轮未通过确认性 holdout 的候选不得进入短名单，除非重新设计后重跑。",
        "资金费率类候选进入任何门禁前，必须人工复核 timestamp 约定和小时摊销成本近似。",
    ]
    if sentiment_context.get("extended_fetch_status") == "blocked":
        items.append("免费 derivatives sentiment 180 天扩展抓取被公共源限制阻塞，需要更换数据源或分段修复。")
    if not ga_context.get("shortlist_ids"):
        items.append("GA 当前批次 holdout 存活候选数为 0，只能保留为失败证据和后续设计输入。")
    if intraday_context.get("shortlist"):
        items.append("4H intraday 候选只保留为扩展研究线，仍需人工复核 walk-forward、行情分段和回撤归因。")
    if not timesfm_context.get("beats_trend_baseline"):
        items.append("TimesFM 当前不优于现有趋势基线，只能作为风险辅助诊断，不作为策略短名单。")
    return _dedupe(items)


def _best_trend_baseline(report: Mapping[str, Any]) -> dict[str, Any]:
    rows = _comparison_metric_rows(report)
    trend_rows = [row for row in rows if str(row.get("model_id", "")).startswith("btc_trend_baseline_")]
    if not trend_rows:
        return {}
    return max(
        trend_rows,
        key=lambda row: (
            _float_value(_mapping(row.get("evaluation")).get("profit_factor")),
            _float_value(_mapping(row.get("evaluation")).get("rank_ic")),
        ),
    )


def _best_ga_holdout_baseline(report: Mapping[str, Any]) -> dict[str, Any]:
    holdout = _mapping(report.get("confirmatory_holdout"))
    rows = _list_of_mappings(holdout.get("baseline_rows"))
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: _float_value(_mapping(row.get("holdout_metrics")).get("profit_factor")),
    )


def _model_metric_row(report: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    for row in _comparison_metric_rows(report):
        if row.get("model_id") == model_id:
            return dict(row)
    return {}


def _comparison_metric_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    comparison = _mapping(report.get("baseline_comparison")) or _mapping(report.get("comparison"))
    return _list_of_mappings(comparison.get("metrics"))


def _metric_summary(metrics: Mapping[str, Any]) -> str:
    if not metrics:
        return "missing"
    return (
        f"PF={_round(metrics.get('profit_factor'))}, "
        f"return={_round(metrics.get('total_return'))}, "
        f"MDD={_round(metrics.get('max_drawdown'))}, "
        f"rank_ic={_round(metrics.get('rank_ic'))}"
    )


def _intraday_metric_summary(metrics: Mapping[str, Any]) -> str:
    if not metrics:
        return "missing"
    return (
        f"total_return_pct={_round(metrics.get('total_return_pct'))}, "
        f"MDD_pct={_round(metrics.get('max_drawdown_pct'))}, "
        f"Sharpe={_round(metrics.get('sharpe_ratio'))}"
    )


def _missing_source_blockers(sources: Mapping[str, Mapping[str, Any]]) -> list[str]:
    required = (
        "ga_report",
        "ga_review_packet",
        "derivatives_sentiment_report",
        "timesfm_vs_trend_report",
        "intraday_validation_gate_report",
    )
    return [f"btc_extended_strategy_mining_source_missing:{name}" for name in required if not sources.get(name)]


def _unsafe_flags(payloads: Mapping[str, Any]) -> list[str]:
    hits: list[str] = []

    def visit(node: Any, prefix: str = "") -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                name = str(key)
                path = f"{prefix}.{name}" if prefix else name
                if name in UNSAFE_TRUE_KEYS and value is True:
                    hits.append(path)
                visit(value, path)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for idx, value in enumerate(node):
                visit(value, f"{prefix}[{idx}]")

    visit(payloads)
    return _dedupe(hits)


def _read_json(path: Path) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _round(value: Any) -> float:
    return round(_float_value(value), 6)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _md(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")
