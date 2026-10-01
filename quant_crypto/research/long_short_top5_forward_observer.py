from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.btc_confirmatory_holdout_lock import DEFAULT_LOCK_CONFIG_PATH
from quant_crypto.research.btc_observe_only_lock import (
    holdout_lock_blockers,
    observation_row_lock_stamp,
    observe_only_lock_status,
    read_holdout_lock_config,
)
from quant_crypto.research.long_short_top5_review import (
    DEFAULT_REPORT_PATH as DEFAULT_TOP5_REVIEW_REPORT_PATH,
    _loss_control_review,
    _slice_metrics,
    _trade_ledger,
)
from quant_crypto.research.long_short_trend_following_lab import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    BASE_COST_BPS,
    INITIAL_CAPITAL,
    LongShortTrendSpec,
    aggregate_ohlcv,
    aggregate_ohlcv_calendar,
    align_derivatives_to_index,
    evaluate_long_short_trend_rule,
    load_market_1h,
    long_short_trend_following_specs,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _round


SCHEMA_VERSION = "btc_long_short_top5_forward_observer_v1"
OBSERVATION_ROW_SCHEMA_VERSION = "btc_long_short_top5_forward_observation_row_v1"
OBSERVER_ID = "btc_long_short_donchian_top5_observe_only_v1"

DEFAULT_OUTPUT_DIR = Path("artifacts/btc_long_short_top5_forward_observer/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_top5_forward_observer_report.json"
DEFAULT_OBSERVATION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_top5_forward_observations_latest.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_long_short_top5_forward_observer_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_OBSERVATION_LEDGER_PATH = Path("data/forward_observation/btc_long_short_top5/observations.jsonl")


def run_btc_long_short_top5_forward_observer(
    *,
    source_top5_review_report_path: Path = DEFAULT_TOP5_REVIEW_REPORT_PATH,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    observation_ledger_path: Path = DEFAULT_OBSERVATION_LEDGER_PATH,
    holdout_lock_path: Path = DEFAULT_LOCK_CONFIG_PATH,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    top_n: int = 5,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    observation_csv_path = output_dir / DEFAULT_OBSERVATION_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    source = _read_json(source_top5_review_report_path)
    source_rows = _source_candidate_rows(source, top_n=top_n)
    blockers = _source_blockers(source, source_rows)
    holdout_lock_config, holdout_lock_load_blockers = read_holdout_lock_config(holdout_lock_path)
    blockers.extend(holdout_lock_load_blockers)

    bars_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    specs = {spec.candidate_id: spec for spec in long_short_trend_following_specs(run_profile="formal_narrow")}

    latest_rows: list[dict[str, Any]] = []
    if not blockers:
        for source_row in source_rows:
            spec = specs.get(str(source_row.get("candidate_id", "")))
            if spec is None:
                blockers.append(f"btc_long_short_top5_observer_missing_spec:{source_row.get('candidate_id')}")
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
            latest_rows.append(
                _observation_row(
                    source_row=source_row,
                    spec=spec,
                    item=item,
                    generated_at_utc=generated,
                    initial_capital=initial_capital,
                )
            )

    holdout_lock = observe_only_lock_status(
        lock_config=holdout_lock_config,
        decision_times=[row.get("decision_time") for row in latest_rows],
        observer_id=OBSERVER_ID,
        holdout_lock_path=holdout_lock_path,
    )
    blockers.extend(holdout_lock_blockers(holdout_lock))
    for row in latest_rows:
        row["holdout_lock"] = observation_row_lock_stamp(holdout_lock, row.get("decision_time"))

    existing = _read_jsonl(observation_ledger_path)
    new_rows = 0
    already_processed_count = 0
    if latest_rows and not blockers:
        observation_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with observation_ledger_path.open("a", encoding="utf-8") as fh:
            for row in latest_rows:
                already_processed = any(
                    existing_row.get("observer_id") == OBSERVER_ID
                    and existing_row.get("candidate_id") == row.get("candidate_id")
                    and existing_row.get("decision_time") == row.get("decision_time")
                    for existing_row in existing
                )
                if already_processed:
                    already_processed_count += 1
                    continue
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                existing.append(row)
                new_rows += 1

    observer_rows = [row for row in existing if row.get("observer_id") == OBSERVER_ID]
    _write_csv(observation_csv_path, observer_rows[-300:])
    progress = _progress(observer_rows)
    health = _health(latest_rows=latest_rows, progress=progress)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": _decision(blockers=blockers, health=health),
        "scope": "daily_observe_only_for_btc_long_short_donchian_top5",
        "code_commit": _git_commit(),
        "input": {
            "source_top5_review_report_path": _portable_path(source_top5_review_report_path),
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "observation_ledger_path": _portable_path(observation_ledger_path),
            "holdout_lock_path": _portable_path(holdout_lock_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
        },
        "observer_design": {
            "observer_id": OBSERVER_ID,
            "source_strategy_line": "robust_long_short_donchian_top5",
            "recommended_frequency": "daily_after_latest_4h_bar_is_complete",
            "decision_rule": "record the latest completed 4h raw signal and already-shifted theoretical exposure; no orders are produced",
            "minimum_forward_observation_days": 30,
            "target_forward_observation_days": 60,
            "holdout_lock_enforced": True,
            "observe_only_purpose": holdout_lock.get("observe_only_purpose"),
            "forbidden_selection_purposes": holdout_lock.get("selection_forbidden_purposes_checked", []),
            "writes_order_intent": False,
            "writes_paper_queue": False,
            "unlocks_live": False,
        },
        "holdout_lock": holdout_lock,
        "latest_observations": latest_rows,
        "observation_automation": {
            "new_observation_rows_written": new_rows,
            "already_processed_count": already_processed_count,
            "candidate_count": len(latest_rows),
            "observation_count": progress["observation_count"],
            "observation_days": progress["observation_days"],
            "observation_ledger_path": _portable_path(observation_ledger_path),
            "observation_csv_path": _portable_path(observation_csv_path),
        },
        "observation_progress": progress,
        "watchlist_health": health,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, health=health, holdout_lock=holdout_lock),
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
    _write_csv(observation_csv_path, observer_rows[-300:])
    _write_text(markdown_path, render_btc_long_short_top5_forward_observer_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _observation_row(
    *,
    source_row: Mapping[str, Any],
    spec: LongShortTrendSpec,
    item: Any,
    generated_at_utc: datetime,
    initial_capital: float,
) -> dict[str, Any]:
    latest_ts = pd.Timestamp(item.returns.index.max())
    current_exposure = float(item.exposure.loc[latest_ts])
    decision_signal = float(item.raw_signal.loc[latest_ts]) if latest_ts in item.raw_signal.index else 0.0
    recent = {}
    for days in (30, 60):
        idx = _last_days_index(item.returns.index, days)
        recent[f"{days}d"] = _slice_metrics(item, idx, initial_capital=initial_capital)
    trades = _trade_ledger(item)
    loss_control = _loss_control_review(trades)
    return {
        "schema_version": OBSERVATION_ROW_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc.astimezone(timezone.utc).isoformat(),
        "observer_id": OBSERVER_ID,
        "rank": int(source_row.get("rank", 0) or 0),
        "candidate_id": spec.candidate_id,
        "variant_id": spec.variant_id,
        "decision_time": _ts(latest_ts),
        "latest_completed_bar_rule": "4h bar derived from completed 1h bars",
        "decision_signal": {
            "side": _side(decision_signal),
            "value": _round(decision_signal),
            "applies_next_bar": True,
        },
        "theoretical_exposure": {
            "side": _side(current_exposure),
            "value": _round(current_exposure),
            "already_shifted_one_4h_bar": True,
        },
        "latest_net_return_pct": _round(float(item.returns.loc[latest_ts]) * 100.0),
        "latest_turnover": _round(float(item.turnover.loc[latest_ts]) if latest_ts in item.turnover.index else 0.0),
        "recent_window_metrics": recent,
        "trend_following_shape": {
            "loss_control_passed": bool(loss_control.get("passed")),
            "average_loss_pct": loss_control.get("average_loss_pct"),
            "worst_loss_pct": loss_control.get("worst_loss_pct"),
            "loss_trade_count": loss_control.get("loss_trade_count"),
            "source_holdout_passed": bool(source_row.get("holdout_passed")),
            "source_trend_profile_passed": bool(source_row.get("trend_profile_passed")),
        },
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _source_candidate_rows(source: Mapping[str, Any], *, top_n: int) -> list[Mapping[str, Any]]:
    rows = source.get("candidate_rows", [])
    if not isinstance(rows, list):
        return []
    sorted_rows = sorted(
        [row for row in rows if isinstance(row, Mapping)],
        key=lambda row: int(row.get("rank", 9999) or 9999),
    )
    return sorted_rows[:top_n]


def _source_blockers(source: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not source:
        blockers.append("btc_long_short_top5_observer_source_report_missing")
    if source and source.get("status") != "complete_research_only":
        blockers.append("btc_long_short_top5_observer_source_not_complete_research_only")
    if source and source.get("gate", {}).get("paper_queue_write_allowed") is not False:
        blockers.append("btc_long_short_top5_observer_source_paper_gate_not_locked")
    if source and source.get("gate", {}).get("live_unlock_allowed") is not False:
        blockers.append("btc_long_short_top5_observer_source_live_gate_not_locked")
    if not rows:
        blockers.append("btc_long_short_top5_observer_missing_top5_rows")
    return blockers


def _progress(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dates = sorted({str(row.get("decision_time", ""))[:10] for row in rows if row.get("decision_time")})
    candidates = sorted({str(row.get("candidate_id")) for row in rows if row.get("candidate_id")})
    return {
        "observation_count": len(rows),
        "candidate_count": len(candidates),
        "observation_days": len(dates),
        "first_observation_date": dates[0] if dates else None,
        "latest_observation_date": dates[-1] if dates else None,
        "under_30d": len(dates) < 30,
        "under_60d": len(dates) < 60,
    }


def _health(*, latest_rows: Sequence[Mapping[str, Any]], progress: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(latest_rows)
    downgrade_reasons: list[str] = []
    if not rows:
        downgrade_reasons.append("no_latest_observation_rows")
    for row in rows:
        metrics_30 = row.get("recent_window_metrics", {}).get("30d", {})
        if float(metrics_30.get("max_drawdown_abs_pct", 0.0) or 0.0) > 15.0:
            downgrade_reasons.append(f"{row.get('variant_id')}:recent_30d_drawdown_gt_15pct")
        if bool(row.get("trend_following_shape", {}).get("loss_control_passed")) is not True:
            downgrade_reasons.append(f"{row.get('variant_id')}:loss_control_shape_failed")
    return {
        "status": "observe_only_collecting" if progress.get("under_30d") else ("downgraded" if downgrade_reasons else "ready_for_manual_30d_review"),
        "downgrade_triggered": bool(downgrade_reasons),
        "downgrade_reasons": sorted(set(downgrade_reasons)),
        "manual_review_required": True,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _decision(*, blockers: Sequence[str], health: Mapping[str, Any]) -> str:
    if blockers:
        return "long_short_top5_forward_observer_blocked_no_write_no_paper_no_live"
    if health.get("downgrade_triggered"):
        return "long_short_top5_forward_observer_observe_only_downgraded_no_paper_no_live"
    return "long_short_top5_forward_observer_active_no_paper_no_live"


def render_btc_long_short_top5_forward_observer_markdown(report: Mapping[str, Any]) -> str:
    auto = report.get("observation_automation", {})
    progress = report.get("observation_progress", {})
    health = report.get("watchlist_health", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC Long/Short Donchian Top5 observe-only 观察器",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 本次新增观察行：`{auto.get('new_observation_rows_written')}`",
        f"- 累计观察行 / 天数：`{progress.get('observation_count')}` / `{progress.get('observation_days')}`",
        f"- 观察健康状态：`{health.get('status')}`",
        f"- 是否触发降级：`{health.get('downgrade_triggered')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 最新 Top5",
        "",
        "| 排名 | 候选 | 决策信号 | 当前理论仓位 | 30天收益 | 30天回撤 | 形态 |",
        "|---:|---|---|---|---:|---:|---|",
    ]
    for row in report.get("latest_observations", [])[:5]:
        m30 = row.get("recent_window_metrics", {}).get("30d", {})
        lines.append(
            "| {rank} | `{variant}` | `{signal}` | `{exposure}` | {ret} | {dd} | `{shape}` |".format(
                rank=row.get("rank"),
                variant=row.get("variant_id"),
                signal=row.get("decision_signal", {}).get("side"),
                exposure=row.get("theoretical_exposure", {}).get("side"),
                ret=m30.get("total_return_pct"),
                dd=m30.get("max_drawdown_abs_pct"),
                shape="loss_ok" if row.get("trend_following_shape", {}).get("loss_control_passed") else "loss_review",
            )
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本观察器只记录 Top5 趋势策略的理论观察状态，不产生订单意图，不写 paper 队列，不连接 broker/OMS/live。",
        ]
    )
    return "\n".join(lines) + "\n"


def _gate() -> dict[str, Any]:
    return {
        "forward_observation_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Long/short Top5 forward observations cannot promote candidates without a separate manual gate.",
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


def _warnings(*, blockers: Sequence[str], health: Mapping[str, Any], holdout_lock: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_long_short_top5_forward_observer_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_long_short_top5_forward_observer_blocked")
    if health.get("downgrade_triggered"):
        warnings.append("btc_long_short_top5_forward_observer_downgrade_triggered")
    warnings.extend(str(item) for item in holdout_lock.get("warnings", []))
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    holdout_lock = report.get("holdout_lock", {})
    return {
        "schema_version": "btc_long_short_top5_forward_observer_safety_status_v1",
        "status": "research_only",
        "forward_observation_only": True,
        "holdout_lock_enforced": bool(holdout_lock.get("lock_config_present")),
        "observe_only_violation_count": int(holdout_lock.get("observe_only_violation_count", 0) or 0),
        "selection_use_blocked_by_lock": bool(holdout_lock.get("selection_use_blocked_by_lock")),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Observe-only report cannot unlock paper or live.",
    }


def _last_days_index(index: pd.DatetimeIndex, days: int) -> pd.DatetimeIndex:
    if len(index) == 0:
        return pd.DatetimeIndex([])
    end = pd.Timestamp(index.max())
    return pd.DatetimeIndex(index[index > end - pd.Timedelta(days=days)])


def _side(value: float) -> str:
    if value > 1e-12:
        return "long"
    if value < -1e-12:
        return "short"
    return "flat"


def _ts(value: Any) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat() if pd.Timestamp(value).tzinfo else pd.Timestamp(value, tz="UTC").isoformat()


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
