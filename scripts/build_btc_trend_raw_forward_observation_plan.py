#!/usr/bin/env python3
"""Build raw BTC trend forward-observation plan.

This freezes the volatility-position branch as a deferred risk-budget option
and ranks the raw trend candidates for forward observation. It does not start
paper trading, does not unlock live trading, and does not call any private or
order endpoint.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_btc_trend_all_strategy_backtest_report import _float, _guardrails, _mapping, _relpath, _resolve  # noqa: E402
from scripts.build_btc_trend_top_strategy_validation_report import DEFAULT_OUTPUT as DEFAULT_TOP_VALIDATION_REPORT  # noqa: E402
from scripts.build_btc_trend_volatility_position_report import DEFAULT_OUTPUT as DEFAULT_VOLATILITY_POSITION_REPORT  # noqa: E402


SCHEMA_VERSION = "btc_trend_raw_forward_observation_plan_v1"
FREEZE_SCHEMA_VERSION = "btc_trend_volatility_position_freeze_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_plan_report.json")
DEFAULT_CANDIDATE_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_candidates.csv")
DEFAULT_VOL_FREEZE_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_volatility_position_freeze_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势原始策略前向观察计划.md")
DEFAULT_VOL_FREEZE_MARKDOWN = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势波动率仓位冻结记录.md")

FAMILY_JUDGEMENT = {
    "t01_twelve_month_momentum": {
        "role": "primary",
        "priority_bias": 30.0,
        "rationale": "经典时间序列动量，规则最简单，walk-forward 可接受度最高，更适合先做小资金前向观察主线。",
        "review_notes": ["低换手，不是高频策略", "重点观察是否过度依赖 2024 大趋势"],
    },
    "t06_atr_channel_breakout": {
        "role": "aggressive_challenger",
        "priority_bias": 24.0,
        "rationale": "全样本收益最高，但参数族较宽且换仓次数极低，需要作为进攻型对照观察。",
        "review_notes": ["参数数较多", "检查是否只是少数大趋势段胜出"],
    },
    "oth_t02_ewmac_acceleration": {
        "role": "risk_balanced_challenger",
        "priority_bias": 18.0,
        "rationale": "回撤较低、换仓更多，信号形态和低换手突破类不同，适合作为风险更平滑的对照。",
        "review_notes": ["收益低于主趋势候选", "检查高换手费用敏感性"],
    },
    "t07_bollinger_breakout": {
        "role": "reserve_breakout",
        "priority_bias": 10.0,
        "rationale": "通过验证，但和 ATR channel 都属于通道突破类，先作为备用对照，不做主线。",
        "review_notes": ["和 ATR channel 信号重叠度可能较高", "不宜同时当作独立分散化"],
    },
    "t02_long_ma_trend": {
        "role": "excluded",
        "priority_bias": -100.0,
        "rationale": "Top 验证中 walk-forward OOS 正收益 fold 为 0/4，暂不进入前向观察主名单。",
        "review_notes": ["不是因为全样本差，而是 OOS 正收益不足"],
    },
}


def build_btc_trend_raw_forward_observation_plan(
    *,
    repo_root: Path | None = None,
    top_validation_report: Path = DEFAULT_TOP_VALIDATION_REPORT,
    volatility_position_report: Path = DEFAULT_VOLATILITY_POSITION_REPORT,
    output: Path = DEFAULT_OUTPUT,
    candidate_output: Path = DEFAULT_CANDIDATE_OUTPUT,
    volatility_freeze_output: Path = DEFAULT_VOL_FREEZE_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    volatility_freeze_markdown: Path = DEFAULT_VOL_FREEZE_MARKDOWN,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    top_abs = _resolve(root, top_validation_report)
    vol_abs = _resolve(root, volatility_position_report)
    output_abs = _resolve(root, output)
    candidates_abs = _resolve(root, candidate_output)
    vol_freeze_abs = _resolve(root, volatility_freeze_output)
    markdown_abs = _resolve(root, markdown_output)
    vol_freeze_md_abs = _resolve(root, volatility_freeze_markdown)

    top = _read_json(top_abs)
    vol = _read_json(vol_abs)
    blockers: list[str] = []
    if str(top.get("status", "")) != "top_strategy_validation_research_only":
        blockers.append("btc_trend_top_strategy_validation_report_missing_or_unexpected_status")
    if str(vol.get("status", "")) not in {"volatility_position_research_only", "volatility_position_blocked", ""}:
        blockers.append("btc_trend_volatility_position_report_unexpected_status")

    candidate_rows = _candidate_rows(top)
    if not candidate_rows:
        blockers.append("btc_trend_raw_forward_observation_no_candidate_rows")
    ranked_candidates = _rank_candidates(candidate_rows)
    forward_candidates = [row for row in ranked_candidates if row["forward_observation_allowed"]]
    if not forward_candidates:
        blockers.append("btc_trend_raw_forward_observation_no_allowed_candidates")

    freeze = _volatility_freeze_payload(
        generated=generated,
        root=root,
        vol_abs=vol_abs,
        volatility_position_report=vol,
    )
    _write_json(vol_freeze_abs, freeze)
    _write_text(vol_freeze_md_abs, _volatility_freeze_markdown_text(freeze))

    if blockers:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "raw_forward_observation_plan_blocked",
            "decision": "do_not_start_forward_observation",
            "top_validation_report": _relpath(top_abs, root),
            "volatility_position_report": _relpath(vol_abs, root),
            "volatility_position_freeze_report": _relpath(vol_freeze_abs, root),
            "candidate_ranking": [],
            "forward_observation": {},
            "guardrails": _plan_guardrails(),
            "blockers": _dedupe(blockers),
            "recommendations": ["前置 top 策略验证报告缺失或没有可观察候选，不启动前向观察。"],
        }
        _write_csv(candidates_abs, _candidate_fieldnames(), [])
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    observation = _forward_observation_plan(forward_candidates)
    _write_csv(candidates_abs, _candidate_fieldnames(), ranked_candidates)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "raw_trend_forward_observation_plan_ready",
        "decision": "observe_raw_trend_candidates_only_volatility_position_frozen",
        "top_validation_report": _relpath(top_abs, root),
        "volatility_position_report": _relpath(vol_abs, root),
        "volatility_position_freeze_report": _relpath(vol_freeze_abs, root),
        "candidate_ranking": ranked_candidates,
        "primary_candidate": forward_candidates[0],
        "forward_observation": observation,
        "outputs": {"candidate_csv": _relpath(candidates_abs, root)},
        "guardrails": _plan_guardrails(),
        "blockers": [],
        "recommendations": _recommendations(forward_candidates),
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _candidate_rows(top_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    wf_summary = _mapping(_mapping(top_report.get("walk_forward")).get("summary")).get("family_summary", {})
    param_summary = _mapping(_mapping(top_report.get("parameter_stability")).get("summary"))
    extreme_summary = _mapping(_mapping(top_report.get("extreme_year_contribution")).get("summary"))
    for row in top_report.get("candidate_summaries", []):
        item = _mapping(row)
        family_id = str(item.get("family_id", ""))
        metrics = _mapping(item.get("metrics"))
        checks = _mapping(item.get("checks"))
        wf = _mapping(_mapping(wf_summary).get(family_id))
        params = _mapping(_mapping(param_summary).get(family_id))
        extreme = _mapping(_mapping(extreme_summary).get(family_id))
        judgement = FAMILY_JUDGEMENT.get(family_id, {})
        passed = str(item.get("validation_status", "")) == "research_validation_passed"
        rows.append(
            {
                "family_id": family_id,
                "candidate_id": str(item.get("candidate_id", "")),
                "variant_id": str(item.get("variant_id", "")),
                "role": str(judgement.get("role", "candidate")),
                "validation_status": str(item.get("validation_status", "")),
                "forward_observation_allowed": bool(passed and str(judgement.get("role", "")) != "excluded"),
                "raw_score": _float(item, "score"),
                "priority_score": _priority_score(item, wf=wf, params=params, extreme=extreme, judgement=judgement),
                "total_return_pct": _float(metrics, "total_return_pct"),
                "annual_volatility_pct": _float(metrics, "annual_volatility_pct"),
                "max_drawdown_abs_pct": _float(metrics, "max_drawdown_abs_pct"),
                "sharpe_ratio": _float(metrics, "sharpe_ratio"),
                "average_exposure": _float(metrics, "average_exposure"),
                "exposure_change_count": int(_float(metrics, "exposure_change_count")),
                "walk_forward_pass": bool(checks.get("walk_forward", False)),
                "walk_forward_positive_fold_count": int(_float(wf, "positive_fold_count")),
                "walk_forward_fold_count": int(_float(wf, "fold_count")),
                "parameter_row_count": int(_float(params, "row_count")),
                "selected_score_percentile": _float(params, "selected_score_percentile"),
                "top_positive_year_share": _float(extreme, "top_positive_year_share"),
                "rationale": str(judgement.get("rationale", "")),
                "review_notes": list(judgement.get("review_notes", [])),
            }
        )
    return rows


def _priority_score(
    row: Mapping[str, Any],
    *,
    wf: Mapping[str, Any],
    params: Mapping[str, Any],
    extreme: Mapping[str, Any],
    judgement: Mapping[str, Any],
) -> float:
    metrics = _mapping(row.get("metrics"))
    checks = _mapping(row.get("checks"))
    score = 0.0
    score += float(judgement.get("priority_bias", 0.0) or 0.0)
    score += min(35.0, max(0.0, _float(metrics, "annual_return_pct")))
    score += 8.0 * _float(metrics, "sharpe_ratio")
    score -= 0.35 * _float(metrics, "max_drawdown_abs_pct")
    score += 4.0 if bool(checks.get("walk_forward", False)) else -25.0
    score += min(8.0, _float(wf, "positive_fold_count") * 2.0)
    score += 3.0 if _float(params, "selected_score_percentile") >= 0.75 else -5.0
    if _float(params, "row_count") > 100:
        score -= 5.0
    if _float(extreme, "top_positive_year_share") > 0.70:
        score -= 6.0
    if str(row.get("validation_status", "")) != "research_validation_passed":
        score -= 100.0
    return round(score, 6)


def _rank_candidates(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (-float(row.get("priority_score", 0.0) or 0.0), str(row.get("family_id", ""))))
    out = []
    for i, row in enumerate(ranked, start=1):
        item = dict(row)
        item["priority_rank"] = i
        out.append(item)
    return out


def _forward_observation_plan(forward_candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "scope": "raw_trend_research_forward_observation",
        "live_order_allowed": False,
        "paper_runner_start_allowed_by_this_report": False,
        "volatility_position_branch_allowed": False,
        "minimum_observation_days_before_review": 30,
        "preferred_review_days": [30, 60, 90],
        "primary_candidate_id": forward_candidates[0]["candidate_id"],
        "primary_family_id": forward_candidates[0]["family_id"],
        "watchlist_family_ids": [row["family_id"] for row in forward_candidates],
        "daily_record_fields": [
            "date",
            "candidate_id",
            "close",
            "raw_signal",
            "effective_exposure",
            "position_change_reason",
            "strategy_return",
            "equity",
            "drawdown",
            "notes",
        ],
        "manual_review_questions": [
            "主候选是否连续遵守 T+1 生效和无未来函数规则？",
            "低换手候选是否只是复制买入持有的大趋势暴露？",
            "2025 类震荡环境里是否持续小亏或频繁反复？",
            "前向信号是否和回测 ledger 中同规则信号一致？",
        ],
    }


def _volatility_freeze_payload(
    *,
    generated: str,
    root: Path,
    vol_abs: Path,
    volatility_position_report: Mapping[str, Any],
) -> dict[str, Any]:
    summaries = [_mapping(row) for row in volatility_position_report.get("family_summaries", []) if isinstance(row, Mapping)]
    largest_return_sacrifice = 0.0
    sharpe_improvements = 0
    for row in summaries:
        selected = _mapping(row.get("selected_variant"))
        largest_return_sacrifice = min(largest_return_sacrifice, _float(selected, "return_diff_vs_baseline_pct"))
        if _float(selected, "sharpe_diff_vs_baseline") > 0.0:
            sharpe_improvements += 1
    return {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "generated_at": generated,
        "status": "frozen_deferred_not_primary",
        "decision": "freeze_volatility_position_branch_keep_as_future_risk_budget_option",
        "source_report": _relpath(vol_abs, root),
        "freeze_reason": "当前 BTC 只投入小资金，波动率仓位会显著牺牲收益，而 Sharpe 改善弱且不稳定；先冻结为未来风险预算备选。",
        "evidence": {
            "source_status": str(volatility_position_report.get("status", "")),
            "family_count": len(summaries),
            "largest_return_diff_vs_baseline_pct": round(largest_return_sacrifice, 6),
            "families_with_positive_sharpe_diff": sharpe_improvements,
        },
        "guardrails": {
            "parameter_tuning_allowed": False,
            "paper_observation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "may_reopen_only_if": [
                "capital_allocation_increases",
                "manual_review_accepts_lower_return_for_lower_drawdown",
                "new_validation_shows_material_sharpe_improvement",
            ],
        },
    }


def _plan_guardrails() -> dict[str, Any]:
    return {
        **_guardrails(),
        "live_order_allowed": False,
        "paper_runner_start_allowed_by_this_report": False,
        "volatility_position_branch_frozen": True,
        "manual_review_required_before_paper_runner": True,
        "manual_review_required_before_live": True,
    }


def _recommendations(forward_candidates: list[Mapping[str, Any]]) -> list[str]:
    primary = forward_candidates[0]
    return [
        f"主观察候选设为 `{primary['family_id']}`，原因是规则简单、验证通过且更适合小资金先跟踪。",
        "波动率仓位分支已冻结为未来风控备选，不进入当前 forward observation。",
        "下一步若要继续，应只做模拟前向记录，不下真实订单，满 30 个日线周期后再人工审阅。",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 趋势原始策略前向观察计划",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
    ]
    if payload.get("status") == "raw_forward_observation_plan_blocked":
        lines.append("前向观察计划被阻断。")
        lines.append("")
        for blocker in payload.get("blockers", []):
            lines.append(f"- `{blocker}`")
        lines.append("")
        return "\n".join(lines)
    primary = _mapping(payload.get("primary_candidate"))
    lines += [
        "波动率仓位分支已冻结；当前只观察原始趋势策略。",
        f"主观察候选：`{primary.get('family_id', '')}` / `{primary.get('candidate_id', '')}`",
        "",
        "## 候选优先级",
        "",
        "| 优先级 | 策略族 | 角色 | 状态 | 收益 | 回撤 | Sharpe | WF正收益fold | 参数数 | 说明 |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload.get("candidate_ranking", []):
        item = _mapping(row)
        lines.append(
            f"| {item.get('priority_rank', '')} | {item.get('family_id', '')} | {item.get('role', '')} | "
            f"`{item.get('validation_status', '')}` | {item.get('total_return_pct', 0)}% | "
            f"{item.get('max_drawdown_abs_pct', 0)}% | {item.get('sharpe_ratio', 0)} | "
            f"{item.get('walk_forward_positive_fold_count', 0)}/{item.get('walk_forward_fold_count', 0)} | "
            f"{item.get('parameter_row_count', 0)} | {item.get('rationale', '')} |"
        )
    observation = _mapping(payload.get("forward_observation"))
    lines += [
        "",
        "## 前向观察规则",
        "",
        f"- 最短观察：{observation.get('minimum_observation_days_before_review', 0)} 个日线周期",
        f"- 复盘节点：{', '.join(str(x) for x in observation.get('preferred_review_days', []))} 日",
        "- 只记录模拟信号和权益，不下真实订单。",
        "- 本报告不允许启动实盘，也不自动启动纸盘 runner。",
        "",
        "## 输出",
        "",
        f"- 候选表：`{_mapping(payload.get('outputs')).get('candidate_csv', '')}`",
        f"- 波动率仓位冻结报告：`{payload.get('volatility_position_freeze_report', '')}`",
        "",
        "## 下一步",
        "",
    ]
    for note in payload.get("recommendations", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _volatility_freeze_markdown_text(payload: Mapping[str, Any]) -> str:
    evidence = _mapping(payload.get("evidence"))
    return "\n".join(
        [
            "# BTC 趋势波动率仓位冻结记录",
            "",
            f"生成时间：{payload.get('generated_at', '')}",
            "",
            "## 冻结结论",
            "",
            f"状态：`{payload.get('status', '')}`",
            "",
            str(payload.get("freeze_reason", "")),
            "",
            "## 证据",
            "",
            f"- 来源报告状态：`{evidence.get('source_status', '')}`",
            f"- 覆盖策略族：{evidence.get('family_count', 0)}",
            f"- 最大收益牺牲：{evidence.get('largest_return_diff_vs_baseline_pct', 0)}%",
            f"- Sharpe 改善策略族数：{evidence.get('families_with_positive_sharpe_diff', 0)}",
            "",
            "## 硬规则",
            "",
            "- 不继续调参",
            "- 不进入当前前向观察",
            "- 不接纸盘 runner",
            "- 不接实盘",
            "",
        ]
    )


def _candidate_fieldnames() -> list[str]:
    return [
        "priority_rank",
        "family_id",
        "candidate_id",
        "variant_id",
        "role",
        "validation_status",
        "forward_observation_allowed",
        "priority_score",
        "raw_score",
        "total_return_pct",
        "annual_volatility_pct",
        "max_drawdown_abs_pct",
        "sharpe_ratio",
        "average_exposure",
        "exposure_change_count",
        "walk_forward_pass",
        "walk_forward_positive_fold_count",
        "walk_forward_fold_count",
        "parameter_row_count",
        "selected_score_percentile",
        "top_positive_year_share",
        "rationale",
        "review_notes_json",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_csv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                csv_row = {key: row.get(key, "") for key in fieldnames}
                csv_row["review_notes_json"] = json.dumps(row.get("review_notes", []), ensure_ascii=False)
                writer.writerow(csv_row)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC raw trend forward-observation plan.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--top-validation-report", default=str(DEFAULT_TOP_VALIDATION_REPORT))
    parser.add_argument("--volatility-position-report", default=str(DEFAULT_VOLATILITY_POSITION_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--candidate-output", default=str(DEFAULT_CANDIDATE_OUTPUT))
    parser.add_argument("--volatility-freeze-output", default=str(DEFAULT_VOL_FREEZE_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--volatility-freeze-markdown", default=str(DEFAULT_VOL_FREEZE_MARKDOWN))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_raw_forward_observation_plan(
        repo_root=Path(args.repo_root),
        top_validation_report=Path(args.top_validation_report),
        volatility_position_report=Path(args.volatility_position_report),
        output=Path(args.output),
        candidate_output=Path(args.candidate_output),
        volatility_freeze_output=Path(args.volatility_freeze_output),
        markdown_output=Path(args.markdown_output),
        volatility_freeze_markdown=Path(args.volatility_freeze_markdown),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
