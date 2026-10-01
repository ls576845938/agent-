#!/usr/bin/env python3
"""Freeze the rejected BTC 5m high-frequency candidate."""

from __future__ import annotations

import argparse
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


SCHEMA_VERSION = "btc_5m_hft_freeze_report_v1"
STRATEGY_ID = "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
FAMILY_ID = "btc_intraday_short_cycle"
DEFAULT_30D_EVALUATION = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_evaluation_report.json")
DEFAULT_90D_EVALUATION = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_evaluation_90d_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_paper_readiness/latest/btc_5m_hft_freeze_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 5m高频策略冻结记录.md")


def build_btc_5m_hft_freeze_report(
    *,
    repo_root: Path | None = None,
    evaluation_30d: Path = DEFAULT_30D_EVALUATION,
    evaluation_90d: Path = DEFAULT_90D_EVALUATION,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    eval_30d_path = _resolve(root, evaluation_30d)
    eval_90d_path = _resolve(root, evaluation_90d)
    output_path = _resolve(root, output)
    markdown_path = _resolve(root, markdown_output)

    eval_30d_payload = _read_json(eval_30d_path)
    eval_90d_payload = _read_json(eval_90d_path)
    primary = eval_90d_payload or eval_30d_payload
    metrics = _mapping(primary.get("metrics"))
    hft_fit = _mapping(primary.get("high_frequency_fit"))
    conclusion = _mapping(primary.get("conclusion"))
    evidence = _freeze_evidence(metrics=metrics, hft_fit=hft_fit)
    status = _freeze_status(primary=primary, evidence=evidence)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "strategy_identity": {
            "family_id": FAMILY_ID,
            "strategy_id": STRATEGY_ID,
            "declared_style": "high_frequency",
            "observed_style": "sparse_event_filter",
        },
        "source_reports": {
            "evaluation_30d": _source_report(eval_30d_path, root, eval_30d_payload),
            "evaluation_90d": _source_report(eval_90d_path, root, eval_90d_payload),
            "primary_evaluation": "evaluation_90d" if eval_90d_payload else "evaluation_30d",
        },
        "status": status,
        "decision": "freeze_strategy_no_more_parameter_tuning",
        "freeze_reason": (
            "90-day evidence shows only 4 entry segments, so the candidate is not a high-frequency strategy."
            if status == "frozen_rejected_as_high_frequency"
            else "freeze evidence is incomplete; do not promote until reviewed."
        ),
        "evidence": evidence,
        "conclusion_snapshot": {
            "system": str(conclusion.get("system", "")),
            "strategy_sample": str(conclusion.get("strategy_sample", "")),
            "high_frequency_fit": str(conclusion.get("high_frequency_fit", "")),
            "profitability": str(conclusion.get("profitability", "")),
        },
        "guardrails": {
            "research_record_only": True,
            "parameter_tuning_allowed": False,
            "reuse_as_hft_candidate_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "resume_180d_5m_pull_allowed": False,
        },
        "allowed_next_actions": [
            "Keep the paper validation infrastructure and daily roll mechanism.",
            "Use this candidate only as a failure-mode reference.",
            "Move BTC research to daily trend exposure-management v0.",
        ],
        "blocked_next_actions": [
            "Do not tune current 5m parameters to force more trades.",
            "Do not relabel this candidate as high-frequency.",
            "Do not promote this candidate to paper/live trading.",
            "Do not restart the 180-day 5m pull for this candidate.",
        ],
    }
    _write_json(output_path, payload)
    _write_text(markdown_path, _markdown(payload))
    return payload


def _freeze_evidence(*, metrics: Mapping[str, Any], hft_fit: Mapping[str, Any]) -> dict[str, Any]:
    days = _int_or(metrics.get("days_completed"), 0)
    entry_segments = _int_or(hft_fit.get("entry_segments"), 0)
    return {
        "days_completed": days,
        "entry_segments": entry_segments,
        "entry_segments_per_day": _round_float(hft_fit.get("entry_segments_per_day")),
        "trade_days": _int_or(metrics.get("trade_days"), 0),
        "trade_day_ratio": _round_float(hft_fit.get("trade_day_ratio")),
        "total_fills": _int_or(metrics.get("total_fills"), 0),
        "total_orders": _int_or(metrics.get("total_orders"), 0),
        "total_rejected": _int_or(metrics.get("total_rejected"), 0),
        "total_signals": _int_or(metrics.get("total_signals"), 0),
        "no_trade_days": _int_or(metrics.get("no_trade_days"), 0),
        "max_consecutive_no_trade_days": _int_or(metrics.get("max_consecutive_no_trade_days"), 0),
        "total_return_pct": _round_float(metrics.get("total_return_pct")),
        "max_drawdown_pct": _round_float(metrics.get("max_drawdown_pct")),
        "hft_fit_status": str(hft_fit.get("status", "")),
        "hft_fit_reason": str(hft_fit.get("reason", "")),
        "system_passed": bool(metrics.get("system_passed", False)),
    }


def _freeze_status(*, primary: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    if not primary:
        return "blocked_missing_evaluation_report"
    days = _int_or(evidence.get("days_completed"), 0)
    segments = _int_or(evidence.get("entry_segments"), 0)
    hft_status = str(evidence.get("hft_fit_status", ""))
    if days >= 90 and segments <= 4 and hft_status == "FAIL":
        return "frozen_rejected_as_high_frequency"
    return "frozen_pending_manual_review"


def _source_report(path: Path, root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _relpath(path, root),
        "exists": path.exists(),
        "status": str(payload.get("status", "")) if payload else "",
        "generated_at": str(payload.get("generated_at", "")) if payload else "",
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    evidence = _mapping(payload.get("evidence"))
    guardrails = _mapping(payload.get("guardrails"))
    lines = [
        "# BTC 5m 高频策略冻结记录",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 冻结结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
        "当前 5m 候选冻结为失败研究记录，不再作为高频策略调参。90 天只有 4 个入场段，实际是低频事件过滤器，不是高频策略。",
        "",
        "## 证据",
        "",
        "| 指标 | 数值 |",
        "| --- | ---: |",
        f"| 完成天数 | {evidence.get('days_completed', 0)} |",
        f"| 入场段 | {evidence.get('entry_segments', 0)} |",
        f"| 入场段/日 | {evidence.get('entry_segments_per_day', 0)} |",
        f"| 交易日 | {evidence.get('trade_days', 0)} |",
        f"| 成交数 | {evidence.get('total_fills', 0)} |",
        f"| 拒单数 | {evidence.get('total_rejected', 0)} |",
        f"| 无成交天数 | {evidence.get('no_trade_days', 0)} |",
        f"| 最长连续无成交天数 | {evidence.get('max_consecutive_no_trade_days', 0)} |",
        f"| 总收益率 | {evidence.get('total_return_pct', 0)}% |",
        f"| 最大回撤 | {evidence.get('max_drawdown_pct', 0)}% |",
        "",
        "## 禁止事项",
        "",
        f"- 继续调参：`{guardrails.get('parameter_tuning_allowed', False)}`",
        f"- 继续按高频候选复用：`{guardrails.get('reuse_as_hft_candidate_allowed', False)}`",
        f"- 纸盘/实盘晋级：`{guardrails.get('paper_or_live_unlock_allowed', False)}`",
        f"- 重启 180 日 5m 拉取：`{guardrails.get('resume_180d_5m_pull_allowed', False)}`",
        "",
        "## 后续方向",
        "",
        "1. 保留纸盘链路和每日滚动机制，作为系统能力资产。",
        "2. 5m 候选只保留为失败模式样本，不再调参。",
        "3. 下一步转向 BTC 日线趋势暴露管理 v0：买入持有、固定 50%、MA120/200、12 个月动量、MA 趋势 + 波动率仓位。",
        "",
    ]
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


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


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_or(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _round_float(value: object) -> float:
    try:
        return round(float(value), 6)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the rejected BTC 5m high-frequency candidate.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--evaluation-30d", default=str(DEFAULT_30D_EVALUATION))
    parser.add_argument("--evaluation-90d", default=str(DEFAULT_90D_EVALUATION))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_5m_hft_freeze_report(
        repo_root=Path(args.repo_root),
        evaluation_30d=Path(args.evaluation_30d),
        evaluation_90d=Path(args.evaluation_90d),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
