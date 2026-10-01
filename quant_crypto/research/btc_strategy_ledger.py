from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "btc_strategy_ledger_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_strategy_ledger/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_ledger_report.json"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_ledger_rows.csv"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_ledger_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_OBJECTIVE_STATUS = Path(
    "artifacts/btc_perpetual_gate_objective_status/latest/btc_perpetual_gate_objective_status_report.json"
)
DEFAULT_GATE_DASHBOARD = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")

DANGEROUS_TRUE_KEYS = {
    "broker_access_allowed",
    "broker_calls_used",
    "live_allowed",
    "live_order_allowed",
    "live_unlock_allowed",
    "micro_live_allowed",
    "oms_access_allowed",
    "order_endpoint_used",
    "paper_allowed",
    "paper_candidate_allowed",
    "paper_candidate_created",
    "paper_order_intake_allowed",
    "paper_queue_write_allowed",
    "private_endpoint_used",
    "real_order_submitted",
    "strategy_skeleton_generated",
}


@dataclass(frozen=True)
class StrategyLineSpec:
    strategy_id: str
    display_name_cn: str
    bucket: str
    role: str
    report_path: Path
    fallback_report_path: Path | None
    input_data_default: tuple[str, ...]
    parameter_summary: str
    next_action: str
    keep_or_retire_recommendation: str
    is_trade_strategy: bool = True
    is_auxiliary_model: bool = False


STRATEGY_LINE_SPECS: tuple[StrategyLineSpec, ...] = (
    StrategyLineSpec(
        strategy_id="stable_long_short",
        display_name_cn="稳健线 Long/Short Donchian Top5",
        bucket="稳健线",
        role="低频、多空趋势跟踪，当前最接近未来 paper 复核基础线",
        report_path=Path(
            "artifacts/btc_long_short_top5_forward_observer/latest/"
            "btc_long_short_top5_forward_observer_report.json"
        ),
        fallback_report_path=None,
        input_data_default=(
            "data/market_data.sqlite BTCUSDT 1H completed bars",
            "1H derived 4H/1D/1W/1M bars",
            "derivatives sentiment rows as risk diagnostics",
        ),
        parameter_summary="Donchian Top5 long/short, completed 4H signal, shifted next-bar exposure.",
        next_action="继续 30/60 天 observe-only；等待 OKX depth 和 gate fill 证据补齐。",
        keep_or_retire_recommendation="keep_primary_observe_only",
    ),
    StrategyLineSpec(
        strategy_id="high_yield",
        display_name_cn="High-yield v2 高收益研究线",
        bucket="高收益线",
        role="小资金高收益 Donchian 改造观察线，优先级低于稳健线和 attack sleeve",
        report_path=Path("artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_followup_report.json"),
        fallback_report_path=None,
        input_data_default=(
            "data/market_data.sqlite BTCUSDT 1H completed bars",
            "derivatives sentiment rows",
            "confirmatory holdout lock",
        ),
        parameter_summary="Frozen high-yield v2 candidate plus loss-control v3 narrow diagnostics.",
        next_action="保留低优先级观察，不用新增结果替代已锁定候选。",
        keep_or_retire_recommendation="keep_low_priority_observe_only",
    ),
    StrategyLineSpec(
        strategy_id="attack_sleeve",
        display_name_cn="Attack sleeve 分仓滚仓线",
        bucket="激进小资金线",
        role="分仓、杠杆、插针剩余本金观察线，只做 observe-only",
        report_path=Path(
            "artifacts/btc_bankroll_attack_forward_observer/latest/"
            "btc_bankroll_attack_forward_observer_report.json"
        ),
        fallback_report_path=None,
        input_data_default=(
            "data/market_data.sqlite BTCUSDT 1H completed bars",
            "derivatives sentiment rows",
            "attack top confirmation review",
        ),
        parameter_summary="Attack sleeve observe-only; tracks theoretical sleeve exposure, spike survival and funding/cost pressure.",
        next_action="继续 30/60 天 observe-only；重点看插针剩余本金、funding 压力和降级触发。",
        keep_or_retire_recommendation="keep_high_risk_observe_only",
    ),
    StrategyLineSpec(
        strategy_id="raw_trend_legacy",
        display_name_cn="早期 raw trend 原始趋势线",
        bucket="历史基线",
        role="早期趋势观察基线，主要用于对照和历史连续性",
        report_path=Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json"),
        fallback_report_path=None,
        input_data_default=(
            "OKX public spot daily bundle",
            "raw trend forward observation ledger",
            "evaluation markdown report",
        ),
        parameter_summary="Legacy raw trend forward observation, simulated-only signal to target/order-intent boundary.",
        next_action="保留作历史基线；后续可人工决定是否归档。",
        keep_or_retire_recommendation="legacy_low_priority_consider_archive",
    ),
    StrategyLineSpec(
        strategy_id="timesfm_auxiliary",
        display_name_cn="TimesFM 辅助预测/风险诊断",
        bucket="辅助模型",
        role="预测辅助和风险诊断，不作为独立下单策略",
        report_path=Path(
            "artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest/"
            "btc_timesfm_vs_trend_baseline_oos_report.json"
        ),
        fallback_report_path=Path(
            "artifacts/shared_forecasting/timesfm/btc_1h_smoke_latest/"
            "btc_timesfm_1h_smoke_forecast_report.json"
        ),
        input_data_default=(
            "data/market_data.sqlite BTCUSDT 1H completed bars",
            "TimesFM checkpoint/cache",
            "trend baseline comparison artifact",
        ),
        parameter_summary="TimesFM zero-shot/OOS comparison against BTC trend baselines; diagnostic only.",
        next_action="只保留为辅助诊断；不能直接生成方向或 paper 候选。",
        keep_or_retire_recommendation="keep_auxiliary_diagnostic_only",
        is_trade_strategy=False,
        is_auxiliary_model=True,
    ),
)


def build_btc_strategy_ledger(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_paths: Mapping[str, Path] | None = None,
    objective_status_path: Path = DEFAULT_OBJECTIVE_STATUS,
    gate_dashboard_path: Path = DEFAULT_GATE_DASHBOARD,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at_utc or datetime.now(timezone.utc)
    path_overrides = dict(report_paths or {})
    rows = [
        _build_strategy_line(
            root=root,
            spec=spec,
            report_path=path_overrides.get(spec.strategy_id),
        )
        for spec in STRATEGY_LINE_SPECS
    ]
    objective = _read_json(root / objective_status_path)
    dashboard = _read_json(root / gate_dashboard_path)
    global_blockers = _global_blockers(objective.payload, dashboard.payload)
    line_blockers = [blocker for row in rows for blocker in row["blockers"]]
    unsafe_count = sum(1 for row in rows if row["upstream_safety_violations"])
    missing_count = sum(1 for row in rows if not row["latest_report_exists"])
    blockers = sorted(set(global_blockers + line_blockers))
    status = "incomplete_research_only" if blockers else "complete_research_only"
    output_dir = _resolve(root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    csv_path = output_dir / DEFAULT_CSV_PATH.name
    summary_path = output_dir / DEFAULT_SUMMARY_CN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "status": status,
        "decision": _decision(status),
        "scope": "read_only_btc_strategy_line_ledger_no_paper_no_live",
        "fixed_strategy_line_count": len(STRATEGY_LINE_SPECS),
        "line_count": len(rows),
        "missing_report_count": missing_count,
        "unsafe_line_count": unsafe_count,
        "global_gate": {
            "objective_status_path": _portable_path(objective_status_path),
            "objective_status_exists": objective.exists,
            "objective_status": _string_or_none(_nested(objective.payload, "status")),
            "objective_decision": _string_or_none(_nested(objective.payload, "decision")),
            "gate_dashboard_path": _portable_path(gate_dashboard_path),
            "gate_dashboard_exists": dashboard.exists,
            "blockers": global_blockers,
        },
        "strategy_lines": rows,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "csv": _portable_path(csv_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(csv_path, rows)
    _write_text(summary_path, render_btc_strategy_ledger_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_strategy_ledger_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 策略台账",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 策略线数量：`{report.get('line_count')}`",
        f"- 缺失报告数：`{report.get('missing_report_count')}`",
        f"- 上游安全异常线数：`{report.get('unsafe_line_count')}`",
        "- 边界：只读台账，不写 paper 队列，不解锁 live，不连接 broker/OMS/order。",
        "",
        "| 策略线 | 分桶 | 状态 | 最近报告 | 观察 | 最新信号/暴露 | 阻塞原因 | 下一步 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in _list_of_mappings(report.get("strategy_lines")):
        observation = _observation_cell(row)
        signal = _signal_cell(row.get("latest_signal_or_exposure"))
        blockers = "；".join(_list_of_strings(row.get("blockers"))) or "无"
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("display_name_cn")),
                    _md(row.get("bucket")),
                    _md(row.get("status")),
                    _md(row.get("latest_report_path") if row.get("latest_report_exists") else "缺失"),
                    _md(observation),
                    _md(signal),
                    _md(blockers),
                    _md(row.get("next_action")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 全局阻塞",
            "",
        ]
    )
    global_blockers = _list_of_strings(_nested(report, "global_gate", "blockers"))
    if global_blockers:
        lines.extend([f"- `{blocker}`" for blocker in global_blockers])
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- research_only：`{_nested(report, 'gate', 'research_only')}`",
            f"- 写 paper 队列：`{_nested(report, 'gate', 'paper_queue_write_allowed')}`",
            f"- 允许 paper：`{_nested(report, 'gate', 'paper_allowed')}`",
            f"- 解锁 live：`{_nested(report, 'gate', 'live_unlock_allowed')}`",
            f"- broker/order：`{_nested(report, 'gate', 'broker_or_order_allowed')}`",
            "",
            "本台账只是研究管理入口，不能作为 paper/live 晋级证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_strategy_line(*, root: Path, spec: StrategyLineSpec, report_path: Path | None = None) -> dict[str, Any]:
    selected_report_path = report_path or spec.report_path
    loaded = _read_json(root / selected_report_path)
    used_fallback = False
    if not loaded.exists and spec.fallback_report_path is not None and report_path is None:
        selected_report_path = spec.fallback_report_path
        loaded = _read_json(root / selected_report_path)
        used_fallback = True
    payload = loaded.payload
    unsafe = _unsafe_true_paths(payload)
    blockers = _list_of_strings(_nested(payload, "blockers"))
    if not loaded.exists:
        blockers.append(f"btc_strategy_ledger_missing_report:{spec.strategy_id}")
    if loaded.error:
        blockers.append(f"btc_strategy_ledger_invalid_json:{spec.strategy_id}")
    blockers.extend(f"unsafe_upstream_safety_flag:{path}" for path in unsafe)
    input_data = _input_data(payload, spec.input_data_default)
    latest_signal = _latest_signal_or_exposure(payload, spec.strategy_id)
    observation_count, observation_days = _observation_progress(payload, spec.strategy_id)
    return {
        "strategy_id": spec.strategy_id,
        "display_name_cn": spec.display_name_cn,
        "bucket": spec.bucket,
        "role": spec.role,
        "is_trade_strategy": spec.is_trade_strategy,
        "is_auxiliary_model": spec.is_auxiliary_model,
        "latest_report_path": _portable_path(selected_report_path),
        "latest_report_exists": loaded.exists,
        "used_fallback_report": used_fallback,
        "latest_report_status": _string_or_none(_nested(payload, "status")) if loaded.exists else "missing_report",
        "status": _line_status(payload, loaded.exists, unsafe),
        "decision": _string_or_none(_nested(payload, "decision"))
        or _string_or_none(_nested(payload, "research_decision", "decision")),
        "latest_report_generated_at_utc": _generated_at(payload),
        "input_data": input_data,
        "parameter_summary": _parameter_summary(payload, spec),
        "latest_signal_or_exposure": latest_signal,
        "observation_count": observation_count,
        "observation_days": observation_days,
        "blockers": sorted(set(blockers)),
        "upstream_safety_violations": unsafe,
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "next_action": spec.next_action,
        "keep_or_retire_recommendation": spec.keep_or_retire_recommendation,
    }


def _line_status(payload: Mapping[str, Any], exists: bool, unsafe: Sequence[str]) -> str:
    if not exists:
        return "missing_report"
    if unsafe:
        return "blocked_fail_closed_research_only"
    return _string_or_none(_nested(payload, "status")) or "unknown_research_only"


def _input_data(payload: Mapping[str, Any], defaults: Sequence[str]) -> list[str]:
    input_payload = _nested(payload, "input")
    values: list[str] = []
    if isinstance(input_payload, Mapping):
        for key, value in input_payload.items():
            if key.endswith("_path") or key.endswith("_db") or key in {"db_path", "market_db_path", "derivatives_rows_path"}:
                if isinstance(value, str) and value:
                    values.append(f"{key}: {value}")
    if not values:
        values.extend(defaults)
    return values


def _parameter_summary(payload: Mapping[str, Any], spec: StrategyLineSpec) -> dict[str, Any]:
    summary: dict[str, Any] = {"description": spec.parameter_summary}
    observer = _nested(payload, "observer_design")
    if isinstance(observer, Mapping):
        for key in ("observer_id", "source_strategy_line", "decision_rule", "minimum_forward_observation_days"):
            if key in observer:
                summary[key] = observer[key]
    if spec.strategy_id == "high_yield":
        frozen = _nested(payload, "frozen_candidate")
        if isinstance(frozen, Mapping):
            for key in ("candidate_id", "variant_id", "max_leverage", "vol_target"):
                if key in frozen:
                    summary[key] = frozen[key]
        loss = _nested(payload, "step_2_loss_control_v3_narrow_experiment")
        if isinstance(loss, Mapping):
            summary["loss_control_candidate_count"] = loss.get("candidate_count")
    if spec.strategy_id == "timesfm_auxiliary":
        model = _nested(payload, "model")
        if isinstance(model, Mapping):
            summary["model"] = model
        validation = _nested(payload, "validation_design")
        if isinstance(validation, Mapping):
            summary["validation_design"] = validation
    return summary


def _latest_signal_or_exposure(payload: Mapping[str, Any], strategy_id: str) -> dict[str, Any]:
    if strategy_id == "stable_long_short":
        rows = _list_of_mappings(_nested(payload, "latest_observations"))
        return {
            "kind": "latest_top5_signals",
            "decision_time": _first_string(row.get("decision_time") for row in rows),
            "items": [
                {
                    "rank": row.get("rank"),
                    "candidate_id": row.get("candidate_id"),
                    "signal_side": _nested(row, "decision_signal", "side"),
                    "signal_value": _nested(row, "decision_signal", "value"),
                    "exposure_side": _nested(row, "theoretical_exposure", "side"),
                    "exposure_value": _nested(row, "theoretical_exposure", "value"),
                }
                for row in rows[:5]
            ],
        }
    if strategy_id == "attack_sleeve":
        row = _mapping(_nested(payload, "latest_observation"))
        return {
            "kind": "attack_sleeve_latest_observation",
            "decision_time": row.get("decision_time"),
            "daily_signal": row.get("daily_signal"),
            "theoretical_sleeve_exposure": row.get("theoretical_sleeve_exposure"),
            "remaining_after_10pct_spike_pct": _nested(row, "spike_remaining_capital", "remaining_after_10pct_spike_pct"),
            "downgrade_triggered": row.get("downgrade_triggered"),
        }
    if strategy_id == "high_yield":
        step = _mapping(_nested(payload, "step_1_daily_observation_automation"))
        return {
            "kind": "high_yield_observe_only",
            "latest_decision_time": _nested(step, "holdout_lock", "latest_decision_time"),
            "new_observation_written": step.get("new_observation_written"),
            "already_processed": step.get("already_processed"),
            "loss_v3_candidate_count": _nested(payload, "step_2_loss_control_v3_narrow_experiment", "candidate_count"),
        }
    if strategy_id == "raw_trend_legacy":
        forward = _mapping(_nested(payload, "forward_observation"))
        return {
            "kind": "raw_trend_forward_observation",
            "new_observation_written": forward.get("new_observation_written"),
            "already_processed": forward.get("already_processed"),
            "observation_days": forward.get("observation_days"),
            "status": _nested(payload, "status"),
        }
    return {
        "kind": "auxiliary_forecast_diagnostic",
        "research_decision": _nested(payload, "research_decision"),
        "comparison": _nested(payload, "comparison"),
        "paper_or_live_note": "TimesFM is diagnostic only and cannot generate orders by itself.",
    }


def _observation_progress(payload: Mapping[str, Any], strategy_id: str) -> tuple[int | None, int | None]:
    candidates: list[Mapping[str, Any]] = []
    for key in (
        "observation_progress",
        "observation_automation",
        "step_1_daily_observation_automation",
        "forward_observation",
    ):
        item = _nested(payload, key)
        if isinstance(item, Mapping):
            candidates.append(item)
    for item in candidates:
        count = _int_or_none(item.get("observation_count"))
        days = _int_or_none(item.get("observation_days"))
        if count is not None or days is not None:
            return count, days
    if strategy_id == "timesfm_auxiliary":
        return _int_or_none(_nested(payload, "input", "decision_count")), None
    return None, None


def _global_blockers(objective: Mapping[str, Any], dashboard: Mapping[str, Any]) -> list[str]:
    blockers = _list_of_strings(objective.get("blockers"))
    blockers.extend(f"gate_dashboard:{item}" for item in _list_of_strings(dashboard.get("blockers")))
    if not objective:
        blockers.append("btc_strategy_ledger_missing_objective_status")
    return sorted(set(blockers))


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, Any]:
    return {
        "read_only_artifact_aggregation": True,
        "network_collection_used": False,
        "strategy_rerun_used": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "research_only",
        "schema_version": "btc_strategy_ledger_safety_status_v1",
        "source_report": _nested(report, "outputs", "json"),
        "line_count": report.get("line_count"),
        "missing_report_count": report.get("missing_report_count"),
        "unsafe_line_count": report.get("unsafe_line_count"),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
    }


def _decision(status: str) -> str:
    if status == "complete_research_only":
        return "btc_strategy_ledger_complete_research_only_no_paper_no_live"
    return "btc_strategy_ledger_incomplete_research_only_no_paper_no_live"


def _generated_at(payload: Mapping[str, Any]) -> str | None:
    for key in ("generated_at_utc", "generated_at", "created_at_utc"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _unsafe_true_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if key in DANGEROUS_TRUE_KEYS and child is True:
                paths.append(child_path)
            paths.extend(_unsafe_true_paths(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value[:200]):
            paths.extend(_unsafe_true_paths(child, f"{prefix}[{idx}]"))
    return paths


def _observation_cell(row: Mapping[str, Any]) -> str:
    count = row.get("observation_count")
    days = row.get("observation_days")
    parts = []
    if count is not None:
        parts.append(f"{count} 次")
    if days is not None:
        parts.append(f"{days} 天")
    return " / ".join(parts) if parts else "-"


def _signal_cell(value: Any) -> str:
    item = _mapping(value)
    kind = str(item.get("kind", ""))
    if kind == "latest_top5_signals":
        rows = _list_of_mappings(item.get("items"))
        sides = [str(_nested(row, "exposure_side") or _nested(row, "signal_side")) for row in rows]
        return "Top5 " + ",".join(sides[:5]) if sides else "Top5 无"
    if kind == "attack_sleeve_latest_observation":
        return f"{_nested(item, 'daily_signal', 'side') or '-'} / sleeves={_nested(item, 'theoretical_sleeve_exposure', 'exposed_sleeve_count')}"
    if kind == "high_yield_observe_only":
        return f"loss_v3候选={item.get('loss_v3_candidate_count')}"
    if kind == "raw_trend_forward_observation":
        return str(item.get("status") or "-")
    if kind == "auxiliary_forecast_diagnostic":
        return "辅助诊断，不下单"
    return "-"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = [
        "strategy_id",
        "display_name_cn",
        "bucket",
        "role",
        "status",
        "latest_report_path",
        "latest_report_exists",
        "latest_report_generated_at_utc",
        "observation_count",
        "observation_days",
        "research_only",
        "paper_queue_write_allowed",
        "paper_allowed",
        "live_unlock_allowed",
        "broker_or_order_allowed",
        "next_action",
        "keep_or_retire_recommendation",
        "blockers",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: ";".join(row.get(key, [])) if key == "blockers" else row.get(key)
                    for key in columns
                }
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> "_JsonLoad":
    if not path.exists():
        return _JsonLoad(payload={}, exists=False, error=None)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _JsonLoad(payload={}, exists=True, error=str(exc))
    if not isinstance(payload, Mapping):
        return _JsonLoad(payload={}, exists=True, error="json_root_not_object")
    return _JsonLoad(payload=dict(payload), exists=True, error=None)


@dataclass(frozen=True)
class _JsonLoad:
    payload: Mapping[str, Any]
    exists: bool
    error: str | None


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return str(path).replace("\\", "/")


def _git(args: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return value or "unknown"


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _first_string(values: Sequence[Any]) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _md(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")
