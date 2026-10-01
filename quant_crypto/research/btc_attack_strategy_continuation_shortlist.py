from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "btc_attack_strategy_continuation_shortlist_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_attack_strategy_continuation_shortlist/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_strategy_continuation_shortlist_report.json"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_strategy_continuation_shortlist_rows.csv"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_strategy_continuation_shortlist_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_BANKROLL_REVIEW_PATH = Path(
    "artifacts/btc_bankroll_rollover_review/latest/btc_bankroll_rollover_review_report.json"
)
DEFAULT_HIGH_OCTANE_PATH = Path(
    "artifacts/btc_high_octane_attack_sleeve_lab/latest/btc_high_octane_attack_sleeve_lab_report.json"
)
DEFAULT_PYRAMIDING_PATH = Path(
    "artifacts/btc_pyramiding_sleeve_lab/latest/btc_pyramiding_sleeve_lab_report.json"
)
DEFAULT_RISK_STRESS_PATH = Path(
    "artifacts/btc_attack_sleeve_risk_stress_review/latest/btc_attack_sleeve_risk_stress_review_report.json"
)


def build_btc_attack_strategy_continuation_shortlist(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    bankroll_review_path: Path = DEFAULT_BANKROLL_REVIEW_PATH,
    high_octane_path: Path = DEFAULT_HIGH_OCTANE_PATH,
    pyramiding_path: Path = DEFAULT_PYRAMIDING_PATH,
    risk_stress_path: Path = DEFAULT_RISK_STRESS_PATH,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir = _resolve(root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bankroll = _read_json(_resolve(root, bankroll_review_path))
    high_octane = _read_json(_resolve(root, high_octane_path))
    pyramiding = _read_json(_resolve(root, pyramiding_path))
    risk_stress = _read_json(_resolve(root, risk_stress_path))

    rows = _build_rows(
        bankroll=bankroll.payload,
        high_octane=high_octane.payload,
        pyramiding=pyramiding.payload,
        risk_stress=risk_stress.payload,
        sources={
            "bankroll": bankroll,
            "high_octane": high_octane,
            "pyramiding": pyramiding,
            "risk_stress": risk_stress,
        },
    )
    missing_sources = [
        source_name
        for source_name, source in {
            "bankroll_rollover_review": bankroll,
            "high_octane_attack_sleeve_lab": high_octane,
            "pyramiding_sleeve_lab": pyramiding,
            "attack_sleeve_risk_stress_review": risk_stress,
        }.items()
        if not source.exists
    ]
    safety_violations = [
        f"{row['strategy_id']}:{item}"
        for row in rows
        for item in _find_true_safety_flags(row)
    ]
    blockers = sorted(
        set(
            [f"missing_source:{item}" for item in missing_sources]
            + safety_violations
            + [blocker for row in rows for blocker in row.get("blockers", [])]
        )
    )
    status = "incomplete_research_only" if missing_sources or safety_violations else "complete_research_only"
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
        "scope": "btc_aggressive_attack_strategy_continuation_shortlist_research_only",
        "line_count": len(rows),
        "continued_research_strategy_count": sum(1 for row in rows if row["continue_research"] is True),
        "danger_reference_count": sum(1 for row in rows if row["research_role"] == "danger_reference"),
        "source_status": {
            "bankroll_rollover_review": _source_status(bankroll_review_path, bankroll),
            "high_octane_attack_sleeve_lab": _source_status(high_octane_path, high_octane),
            "pyramiding_sleeve_lab": _source_status(pyramiding_path, pyramiding),
            "attack_sleeve_risk_stress_review": _source_status(risk_stress_path, risk_stress),
        },
        "strategy_lines": rows,
        "global_next_steps": [
            "围绕 High-Octane v2 做严格 mark/index、funding、滑点、插针、rolling-start 复核。",
            "把 5x 防插针/分仓版与实际 10x 限暴露版同窗口比较，重点看插针后剩余本金和收益中位数。",
            "原始 10x 爆炸版只作为收益天花板/危险样本，不进入 forward observation。",
            "任何候选进入 paper 前，必须先通过未来函数/过拟合审计、真实盘口/mark/index/fill gate 和人工复核。",
        ],
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
    _write_text(summary_path, render_btc_attack_strategy_continuation_shortlist_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_attack_strategy_continuation_shortlist_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 激进/分仓滚仓继续研究短名单",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 短名单数量：`{report.get('line_count')}`",
        f"- 继续研究数量：`{report.get('continued_research_strategy_count')}`",
        "- 边界：只做 research-only，不写 paper 队列，不生成策略骨架，不接 broker/OMS/order，不解锁 live。",
        "",
        "| 排名 | 策略 | 角色 | 年化 | 总收益 | 最大回撤 | -10%插针后剩余 | 结论 | 下一步 |",
        "|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in _list_of_mappings(report.get("strategy_lines")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("rank")),
                    _md(row.get("display_name_cn")),
                    _md(row.get("research_role")),
                    _md(_pct(row.get("annual_return_pct"))),
                    _md(_pct(row.get("total_return_pct"))),
                    _md(_pct(row.get("max_drawdown_abs_pct"))),
                    _md(_pct(row.get("min_remaining_after_10pct_spike_pct"))),
                    _md(row.get("retention_decision")),
                    _md(row.get("next_action")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## 关键解释", ""])
    for row in _list_of_mappings(report.get("strategy_lines")):
        lines.append(f"### {row.get('display_name_cn')}")
        lines.append("")
        lines.append(f"- 研究结论：`{row.get('retention_decision')}`")
        lines.append(f"- 为什么保留：{row.get('why_keep')}")
        lines.append(f"- 主要风险：{row.get('primary_risk')}")
        lines.append(f"- 阻塞原因：{'; '.join(_list_of_strings(row.get('blockers'))) or '无'}")
        lines.append("")
    lines.extend(["## 全局下一步", ""])
    for step in _list_of_strings(report.get("global_next_steps")):
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


class _JsonSource:
    def __init__(self, path: Path, payload: dict[str, Any], exists: bool) -> None:
        self.path = path
        self.payload = payload
        self.exists = exists


def _build_rows(
    *,
    bankroll: Mapping[str, Any],
    high_octane: Mapping[str, Any],
    pyramiding: Mapping[str, Any],
    risk_stress: Mapping[str, Any],
    sources: Mapping[str, _JsonSource],
) -> list[dict[str, Any]]:
    bankroll_rows = _list_of_mappings(_nested(bankroll, "source_attribution", "rows"))
    original_10x = _find_row(bankroll_rows, "scenario_id", "br_review_no_rollover_lev10p0")
    split_2 = _find_row(bankroll_rows, "scenario_id", "br_review_split_2_on_double_lev10p0")
    five_x = _find_row(bankroll_rows, "scenario_id", "br_review_no_rollover_lev5p0")
    high_summary = _mapping(high_octane.get("summary"))
    high_top = _first_mapping(high_octane.get("top_watchlist"))
    pyramiding_summary = _mapping(pyramiding.get("summary"))
    pyramiding_top = _first_mapping(pyramiding.get("top_watchlist"))
    actual_attack = _first_mapping(pyramiding.get("top_actual_attack_watchlist"))
    risk_summary = _mapping(risk_stress.get("summary"))

    original_blockers = [
        "原始 10x 同方向同杠杆，-5%/-8%/-10% 合成插针可导致 sleeve 同时归零。",
        "split_2 相比 10x no_rollover 的增量为 0，收益主要来自杠杆复利，不是拆仓防守。",
        "复核结论为 path_dependent_not_forward_observation_ready。",
    ]
    high_boundary = _threshold_distance(high_summary.get("best_min_remaining_after_10pct_spike"), 40.0)
    high_blockers = [
        "最佳候选只压过 40% 插针剩余本金线，存在参数边界挖掘风险。",
        "严格风控压力包当前结论不是 forward observation ready。",
    ]
    if _num(risk_summary.get("not_forward_observation_ready")) == 1:
        high_blockers.append("risk stress 标记 not_forward_observation_ready。")

    rows = [
        {
            "rank": 1,
            "strategy_id": "original_10x_explosive_reference",
            "display_name_cn": "10x no_rollover / split_2_on_double 原始爆炸版",
            "research_role": "danger_reference",
            "continue_research": False,
            "source_report_path": _portable_path(sources["bankroll"].path),
            "source_scenario_id": _str(original_10x.get("scenario_id"), "br_review_no_rollover_lev10p0"),
            "comparison_scenario_id": _str(split_2.get("scenario_id"), "br_review_split_2_on_double_lev10p0"),
            "annual_return_pct": _num(original_10x.get("annual_return_pct")),
            "total_return_pct": _num(original_10x.get("total_return_pct")),
            "max_drawdown_abs_pct": _num(original_10x.get("max_drawdown_abs_pct")),
            "min_remaining_after_10pct_spike_pct": 0.0,
            "max_leverage": _num(original_10x.get("leverage")),
            "max_concurrent_exposed_sleeves": _num(split_2.get("active_sleeve_count") or original_10x.get("active_sleeve_count")),
            "rolling_median_total_return_pct": None,
            "retention_decision": "keep_as_danger_ceiling_only_not_candidate",
            "why_keep": "它证明同一方向 10x 趋势信号在历史大趋势里收益天花板很高，但也暴露一次插针全灭的结构性风险。",
            "primary_risk": "同一方向、同一杠杆、同一根 K 线同时承担风险，-10% 插针后剩余本金按 0% 处理。",
            "next_action": "只作为危险收益天花板和压力测试参照，不进入 observe-only / paper。",
            "blockers": original_blockers,
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
        {
            "rank": 2,
            "strategy_id": "high_octane_attack_sleeve_v2",
            "display_name_cn": "High-Octane Attack Sleeve v2",
            "research_role": "primary_high_octane_research",
            "continue_research": True,
            "source_report_path": _portable_path(sources["high_octane"].path),
            "source_scenario_id": _str(high_summary.get("best_scenario_id") or high_top.get("scenario_id")),
            "comparison_scenario_id": _str(risk_summary.get("source_best_scenario_id")),
            "annual_return_pct": _num(high_summary.get("best_annual_return_pct")),
            "total_return_pct": _num(high_summary.get("best_total_return_pct")),
            "max_drawdown_abs_pct": _num(high_summary.get("best_max_drawdown_abs_pct")),
            "min_remaining_after_10pct_spike_pct": _num(high_summary.get("best_min_remaining_after_10pct_spike")),
            "threshold_margin_over_40pct": high_boundary,
            "max_leverage": _num(high_top.get("max_template_leverage")),
            "max_concurrent_exposed_sleeves": _num(high_top.get("max_concurrent_exposed_sleeves_observed")),
            "rolling_median_total_return_pct": _num(high_summary.get("best_rolling_median_total_return_pct")),
            "retention_decision": "continue_research_but_boundary_mined",
            "why_keep": "当前小资金进攻线里收益最高，rolling start 中位数仍为正，且没有模拟全灭。",
            "primary_risk": "40% 生存线余量很薄，严格 mark/funding/slippage/插针假设下还没通过 forward-ready 复核。",
            "next_action": "围绕 Top 20 做严格风控压力、邻域稳定性和 30/60 天 observe-only，不扩大新策略空间。",
            "blockers": high_blockers,
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
        {
            "rank": 3,
            "strategy_id": "defensive_5x_mixed_sleeve",
            "display_name_cn": "防插针 5x / mixed sleeve 版本",
            "research_role": "spike_defense_research",
            "continue_research": True,
            "source_report_path": _portable_path(sources["bankroll"].path),
            "source_scenario_id": _str(five_x.get("scenario_id"), "br_review_no_rollover_lev5p0"),
            "comparison_scenario_id": _str(pyramiding_summary.get("best_scenario_id") or pyramiding_top.get("scenario_id")),
            "annual_return_pct": _num(five_x.get("annual_return_pct")),
            "total_return_pct": _num(five_x.get("total_return_pct")),
            "max_drawdown_abs_pct": _num(five_x.get("max_drawdown_abs_pct")),
            "min_remaining_after_10pct_spike_pct": _num(pyramiding_summary.get("best_min_remaining_after_10pct_spike"), 100.0),
            "max_leverage": 5.0,
            "max_concurrent_exposed_sleeves": _num(pyramiding_top.get("max_concurrent_exposed_sleeves_observed")),
            "rolling_median_total_return_pct": None,
            "retention_decision": "continue_research_as_spike_defense_baseline",
            "why_keep": "5x 版本收益/风险比明显好于原始 10x 全暴露，且防插针 pyramiding 报告中 -10% 插针剩余本金达到 100%。",
            "primary_risk": "收益口径来自 5x 复利参照，分仓 mixed sleeve 的真实执行、mark/index 与 funding 仍是研究近似。",
            "next_action": "与 High-Octane v2 同窗口比较，重点复核收益中位数、插针后本金和成本压力。",
            "blockers": [
                "需要统一 5x 复利参照和 pyramiding sleeve 防插针口径。",
                "缺真实永续 mark/index、盘口深度和成交回放证据。",
            ],
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
        {
            "rank": 4,
            "strategy_id": "actual_10x_attack_limited_exposure",
            "display_name_cn": "实际 10x attack 但限制暴露版本",
            "research_role": "limited_attack_exposure_research",
            "continue_research": True,
            "source_report_path": _portable_path(sources["pyramiding"].path),
            "source_scenario_id": _str(pyramiding_summary.get("best_actual_attack_scenario_id") or actual_attack.get("scenario_id")),
            "comparison_scenario_id": _str(actual_attack.get("scenario_id")),
            "annual_return_pct": _num(pyramiding_summary.get("best_actual_attack_annual_return_pct") or actual_attack.get("annual_return_pct")),
            "total_return_pct": _num(actual_attack.get("total_return_pct")),
            "max_drawdown_abs_pct": _num(pyramiding_summary.get("best_actual_attack_max_drawdown_abs_pct") or actual_attack.get("max_drawdown_abs_pct")),
            "min_remaining_after_10pct_spike_pct": _num(pyramiding_summary.get("best_actual_attack_min_remaining_after_10pct_spike") or actual_attack.get("min_remaining_capital_pct_after_10pct_spike")),
            "max_leverage": 10.0,
            "max_concurrent_exposed_sleeves": _num(actual_attack.get("max_concurrent_exposed_sleeves_observed")),
            "rolling_median_total_return_pct": None,
            "retention_decision": "continue_research_as_limited_attack_discipline",
            "why_keep": "它保留了真实用过 10x attack 的进攻性，同时通过限制暴露、错峰和提本金显著降低一次插针打穿全局本金的概率。",
            "primary_risk": "收益率相对 High-Octane 明显低，价值主要在风控纪律，不是当前最高收益来源。",
            "next_action": "作为纪律模块嫁接到 High-Octane v2，测试 attack cap、提本金和冷却降杠杆组合。",
            "blockers": [
                "需要证明限制暴露不是只在样本内有效。",
                "需要继续做真实 mark/index、funding、滑点和 rolling-start 复核。",
            ],
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    ]
    return rows


def _source_status(path: Path, source: _JsonSource) -> dict[str, Any]:
    return {
        "path": _portable_path(path),
        "exists": source.exists,
        "status": source.payload.get("status"),
        "decision": source.payload.get("decision"),
        "generated_at_utc": source.payload.get("generated_at_utc") or source.payload.get("generated_at"),
    }


def _read_json(path: Path) -> _JsonSource:
    if not path.exists():
        return _JsonSource(path=path, payload={}, exists=False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _JsonSource(path=path, payload={}, exists=False)
    return _JsonSource(path=path, payload=payload if isinstance(payload, dict) else {}, exists=True)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "strategy_id",
        "display_name_cn",
        "research_role",
        "continue_research",
        "annual_return_pct",
        "total_return_pct",
        "max_drawdown_abs_pct",
        "min_remaining_after_10pct_spike_pct",
        "retention_decision",
        "next_action",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _gate() -> dict[str, bool | str]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "reason": "Continuation shortlist is a read-only research management artifact.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_attack_strategy_continuation_shortlist_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
        "reason": "BTC aggressive strategy continuation shortlist is not a promotion artifact.",
    }


def _decision(status: str) -> str:
    if status == "complete_research_only":
        return "btc_attack_strategy_continuation_shortlist_complete_research_only_no_paper_no_live"
    return "btc_attack_strategy_continuation_shortlist_incomplete_research_only_no_paper_no_live"


def _find_true_safety_flags(row: Mapping[str, Any]) -> list[str]:
    return [
        key
        for key in (
            "paper_queue_write_allowed",
            "paper_allowed",
            "live_unlock_allowed",
            "broker_or_order_allowed",
        )
        if row.get(key) is True
    ]


def _threshold_distance(value: Any, threshold: float) -> float | None:
    number = _num(value)
    return None if number is None else round(number - threshold, 6)


def _find_row(rows: Sequence[Mapping[str, Any]], key: str, value: str) -> dict[str, Any]:
    for row in rows:
        if row.get(key) == value:
            return dict(row)
    return {}


def _first_mapping(value: Any) -> dict[str, Any]:
    items = _list_of_mappings(value)
    return dict(items[0]) if items else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _num(value: Any, fallback: float | None = None) -> float | None:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return fallback


def _str(value: Any, fallback: str = "-") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _pct(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.2f}%"


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _git(args: Sequence[str], *, cwd: Path) -> str | None:
    try:
        completed = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None
