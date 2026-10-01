from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


SCHEMA_VERSION = "btc_freqtrade_style_leakage_cli_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_freqtrade_style_leakage_cli/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_freqtrade_style_leakage_cli_report.json"
DEFAULT_CHECKLIST_PATH = DEFAULT_OUTPUT_DIR / "btc_freqtrade_style_leakage_cli_checklist.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_freqtrade_style_leakage_cli_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_LEAKAGE_REPORT_PATH = Path(
    "artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json"
)
DEFAULT_BAR_REPLAY_REPORT_PATH = Path(
    "artifacts/btc_strategy_bar_replay_visibility/latest/btc_strategy_bar_replay_visibility_report.json"
)


@dataclass(frozen=True)
class SourceArtifact:
    source_id: str
    path: Path
    payload: Mapping[str, Any]
    missing_blocker: str

    @property
    def exists(self) -> bool:
        return bool(self.payload)


def build_btc_freqtrade_style_leakage_cli(
    *,
    repo_root: Path = Path("."),
    external_references_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    leakage_report_path: Path = DEFAULT_LEAKAGE_REPORT_PATH,
    bar_replay_report_path: Path = DEFAULT_BAR_REPLAY_REPORT_PATH,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    external_root = _resolve_external_root(root, external_references_root)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)

    sources, blockers = _load_sources(
        root=root,
        leakage_report_path=leakage_report_path,
        bar_replay_report_path=bar_replay_report_path,
    )
    freqtrade_ref = _freqtrade_reference(external_root)
    if not freqtrade_ref["reference_readme_exists"]:
        blockers.append("source_missing:freqtrade_reference_readme")

    checklist = _checklist(
        leakage=sources["leakage_report"].payload,
        bar_replay=sources["bar_replay_report"].payload,
        source_blocked=bool(blockers),
    )
    status = "blocked_research_only" if blockers else "complete_research_only"
    decision = _decision(blockers=blockers, checklist=checklist)
    warnings = _warnings(checklist=checklist, blockers=blockers)
    report_path = output / DEFAULT_REPORT_PATH.name
    checklist_path = output / DEFAULT_CHECKLIST_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    safety = _safety_bits()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "scope": "freqtrade_style_lookahead_recursive_cli_for_existing_btc_audit_artifacts",
        "freqtrade_reference": freqtrade_ref,
        "command_semantics": {
            "inspired_by": [
                "freqtrade_lookahead_analysis_cli",
                "freqtrade_recursive_analysis_cli",
            ],
            "source_code_copied": False,
            "source_copy_policy": "Freqtrade is GPL-3.0; only command UX and audit concepts are used as design reference.",
            "runs_strategy_backtest": False,
            "aggregates_existing_artifacts_only": True,
            "paper_gate_credit": False,
        },
        "source_artifacts": {
            source_id: {
                "path": _portable_path(source.path),
                "exists": source.exists,
                "status": source.payload.get("status"),
                "decision": source.payload.get("decision"),
                "generated_at": source.payload.get("generated_at") or source.payload.get("generated_at_utc"),
                "artifact_hash": source.payload.get("artifact_hash"),
            }
            for source_id, source in sources.items()
        },
        "checklist": checklist,
        "summary": _summary(checklist=checklist, decision=decision, blockers=blockers),
        "gate": safety,
        "guardrails": safety,
        "outputs": {
            "json": _portable_path(report_path),
            "checklist_csv": _portable_path(checklist_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    report = apply_btc_artifact_schema(
        payload,
        decision=decision,
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=_dedupe(blockers),
        warnings=warnings,
        input_hashes=_source_hashes(sources=sources, freqtrade_ref=freqtrade_ref),
    )
    _write_json(report_path, report)
    _write_checklist_csv(checklist_path, checklist)
    _write_text(markdown_path, render_btc_freqtrade_style_leakage_cli_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_freqtrade_style_leakage_cli_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# BTC Freqtrade 风格未来函数审计入口",
        "",
        f"- 当前状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 检查项：`{summary.get('check_count')}`",
        f"- 失败：`{summary.get('fail_count')}`，警告：`{summary.get('warn_count')}`，通过：`{summary.get('pass_count')}`",
        "- 边界：只聚合已有审计 artifact，不重跑策略，不写 paper 队列，不解锁 live，不接 broker/order。",
        "- 来源：借鉴 Freqtrade 的 lookahead / recursive 分析命令体验；Freqtrade 为 GPL-3.0，本仓库未复制其源码。",
        "",
        "## 重点检查",
        "",
        "| 类别 | 状态 | 结论 | paper gate 信用 |",
        "| --- | --- | --- | --- |",
    ]
    for row in _list_of_mappings(report.get("checklist")):
        lines.append(
            "| `{category}` | `{status}` | {message} | `{paper_gate_credit}` |".format(
                category=row.get("category", ""),
                status=row.get("status", ""),
                message=row.get("message_cn", ""),
                paper_gate_credit=row.get("paper_gate_credit"),
            )
        )
    lines.extend(
        [
            "",
            "## 不能误解",
            "",
            "- `lookahead` 检查通过，只说明没有直接发现未来函数，不等于可以 paper。",
            "- `recursive` / 状态递归检查是诊断入口，不等于真实交易链路已验证。",
            "- High-Octane / attack sleeve 的同根执行代理仍是研究边界，必须等待 runtime replay 和 current non-flat evidence。",
            "- GA、TimesFM、规则策略的边界必须分开看，不能把辅助模型或挖矿结果直接当下单策略。",
        ]
    )
    return "\n".join(lines) + "\n"


def _checklist(*, leakage: Mapping[str, Any], bar_replay: Mapping[str, Any], source_blocked: bool) -> list[dict[str, Any]]:
    if source_blocked:
        return [
            _row(
                "source_artifacts_available",
                "input",
                "blocked",
                "源审计 artifact 缺失，审计入口 fail-closed。",
                "补齐 btc_strategy_leakage_overfit_audit 与 btc_strategy_bar_replay_visibility 后重跑。",
                scope_line="all",
            )
        ]

    leakage_summary = _mapping(leakage.get("summary"))
    replay_summary = _mapping(bar_replay.get("summary"))
    rows = [
        _row(
            "future_function_visibility",
            "lookahead",
            _pass_fail(
                _int(replay_summary.get("long_short_shift_violation_count")) == 0
                and _int(replay_summary.get("long_short_completed_bar_violation_count")) == 0
            ),
            "Long/Short Donchian Top5 当前 exposure 来自上一根 raw signal，且未发现 completed-bar 违规。",
            "若未来出现 shift/completed-bar 违规，必须阻断 strategy promotion。",
            scope_line="stable_long_short",
            evidence={
                "long_short_shift_violation_count": _int(replay_summary.get("long_short_shift_violation_count")),
                "long_short_completed_bar_violation_count": _int(
                    replay_summary.get("long_short_completed_bar_violation_count")
                ),
            },
        ),
        _row(
            "future_sentiment_available_time",
            "lookahead",
            _pass_fail(
                _int(replay_summary.get("long_short_future_sentiment_violation_count")) == 0
                and _int(replay_summary.get("high_octane_future_sentiment_violation_count")) == 0
                and _int(leakage_summary.get("long_short_future_sentiment_violation_count")) == 0
                and _int(leakage_summary.get("high_octane_future_sentiment_violation_count")) == 0
            ),
            "衍生品 sentiment 按 available_time <= decision_time 可见性检查，当前未发现未来 sentiment 违规。",
            "任何 available_time > decision_time 行不得进入信号或风控过滤。",
            scope_line="stable_and_attack",
            evidence={
                "bar_replay_long_short_future_sentiment_violation_count": _int(
                    replay_summary.get("long_short_future_sentiment_violation_count")
                ),
                "bar_replay_high_octane_future_sentiment_violation_count": _int(
                    replay_summary.get("high_octane_future_sentiment_violation_count")
                ),
                "leakage_long_short_future_sentiment_violation_count": _int(
                    leakage_summary.get("long_short_future_sentiment_violation_count")
                ),
                "leakage_high_octane_future_sentiment_violation_count": _int(
                    leakage_summary.get("high_octane_future_sentiment_violation_count")
                ),
            },
        ),
        _row(
            "same_bar_execution_boundary",
            "lookahead",
            "warn" if _int(replay_summary.get("high_octane_capital_overlay_same_bar_proxy_row_count")) else "pass",
            "High-Octane 方向信号可见性可审，但资金管理 overlay 仍含同根执行/高低价代理边界。",
            "进入 paper 前必须由 runtime replay/current non-flat evidence 替代同根代理。",
            scope_line="attack_sleeve",
            evidence={
                "high_octane_same_bar_proxy_row_count": _int(
                    replay_summary.get("high_octane_capital_overlay_same_bar_proxy_row_count")
                ),
                "high_octane_boundary_verdict": leakage_summary.get(
                    "high_octane_capital_overlay_execution_boundary_verdict"
                )
                or replay_summary.get("high_octane_capital_overlay_execution_boundary_verdict"),
            },
        ),
        _row(
            "recursive_stateful_overlay_boundary",
            "recursive",
            "warn" if _int(replay_summary.get("high_yield_prior_exposure_return_violation_count")) else "pass",
            "状态递归类 overlay 需要确认当前决策只影响下一根可交易 bar；当前 high-yield 仍有状态代理诊断项。",
            "用 fixture/ledger 检查状态递归路径，不能把 recursive diagnostic 当 paper gate 信用。",
            scope_line="high_yield",
            evidence={
                "high_yield_prior_exposure_return_violation_count": _int(
                    replay_summary.get("high_yield_prior_exposure_return_violation_count")
                ),
                "high_yield_model_boundary_row_count": _int(replay_summary.get("high_yield_model_boundary_row_count")),
            },
        ),
        _row(
            "parameter_mining_boundary",
            "overfit",
            "warn"
            if leakage_summary.get("high_octane_likely_parameter_mined_boundary_candidate") is True
            or "parameter" in str(leakage_summary.get("high_octane_parameter_mining_verdict", ""))
            else "pass",
            "High-Octane 最佳候选仍接近 40% 生存线，存在参数压线/邻域不稳风险。",
            "冻结参数、限制 post-selection 使用，并以 forward observation 复核。",
            scope_line="attack_sleeve",
            evidence={
                "high_octane_parameter_mining_verdict": leakage_summary.get("high_octane_parameter_mining_verdict"),
                "high_octane_likely_parameter_mined_boundary_candidate": leakage_summary.get(
                    "high_octane_likely_parameter_mined_boundary_candidate"
                ),
                "high_octane_best_margin_over_40pct_threshold": leakage_summary.get(
                    "high_octane_best_margin_over_40pct_threshold"
                ),
            },
        ),
        _row(
            "return_concentration_and_path_dependency",
            "overfit",
            "warn"
            if "concentration" in str(leakage_summary.get("long_short_return_concentration_verdict", "")).lower()
            or "dependency" in str(leakage_summary.get("high_octane_return_dependency_verdict", "")).lower()
            else "pass",
            "趋势策略收益集中可以接受，但仍需确认不是单一年份/单一路径支撑。",
            "保留年度、rolling-start、Top trade 贡献归因，防止路径依赖伪 alpha。",
            scope_line="stable_and_attack",
            evidence={
                "long_short_return_concentration_verdict": leakage_summary.get("long_short_return_concentration_verdict"),
                "high_octane_return_dependency_verdict": leakage_summary.get("high_octane_return_dependency_verdict"),
            },
        ),
        _row(
            "holdout_forward_window",
            "overfit",
            "warn" if leakage_summary.get("forward_observe_clean_confirmation_ready") is not True else "pass",
            "30/60 天 observe-only 仍未形成确认性 forward 证据。",
            "forward 观察未完成前不得进入 paper/live。",
            scope_line="all_strategy_lines",
            evidence={
                "forward_observe_clean_confirmation_ready": leakage_summary.get("forward_observe_clean_confirmation_ready"),
                "forward_observe_only_anchor_rows_so_far": leakage_summary.get("forward_observe_only_anchor_rows_so_far"),
            },
        ),
        _row(
            "rolling_window_no_full_sample_normalization",
            "lookahead",
            "pass" if _int(leakage_summary.get("check_fail_count")) == 0 else "fail",
            "本入口未发现全样本归一化或 rolling window 失败项；仍以底层审计 checks 为准。",
            "后续新增 primitive/GA/ML 时必须补 rolling-only 标准化测试。",
            scope_line="ga_timesfm_rules",
            evidence={
                "leakage_check_fail_count": _int(leakage_summary.get("check_fail_count")),
                "leakage_check_warn_count": _int(leakage_summary.get("check_warn_count")),
            },
        ),
        _row(
            "ga_timesfm_rule_boundary",
            "scope",
            "warn",
            "GA、TimesFM、手写规则只在本报告中做边界提示；它们不能互相替代 paper gate 证据。",
            "GA 输出表达式、TimesFM 输出辅助预测、规则策略输出候选，全部继续 research-only。",
            scope_line="ga_timesfm_rules",
            evidence={
                "paper_gate_credit": False,
                "uses_current_reports_only": True,
            },
        ),
    ]
    return rows


def _row(
    category: str,
    freqtrade_style_check: str,
    status: str,
    message_cn: str,
    next_action_cn: str,
    *,
    scope_line: str,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "freqtrade_style_check": freqtrade_style_check,
        "scope_line": scope_line,
        "status": status,
        "message_cn": message_cn,
        "next_action_cn": next_action_cn,
        "evidence": dict(evidence or {}),
        "paper_gate_credit": False,
        "live_unlock_credit": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _summary(*, checklist: Sequence[Mapping[str, Any]], decision: str, blockers: Sequence[str]) -> dict[str, Any]:
    return {
        "decision": decision,
        "check_count": len(checklist),
        "pass_count": sum(1 for row in checklist if row.get("status") == "pass"),
        "warn_count": sum(1 for row in checklist if row.get("status") == "warn"),
        "fail_count": sum(1 for row in checklist if row.get("status") == "fail"),
        "blocked_count": sum(1 for row in checklist if row.get("status") == "blocked"),
        "blocker_count": len(blockers),
        "lookahead_or_future_function_fail_count": sum(
            1
            for row in checklist
            if row.get("freqtrade_style_check") == "lookahead" and row.get("status") in {"fail", "blocked"}
        ),
        "recursive_boundary_warn_count": sum(
            1 for row in checklist if row.get("freqtrade_style_check") == "recursive" and row.get("status") == "warn"
        ),
        "overfit_warn_count": sum(
            1 for row in checklist if row.get("freqtrade_style_check") == "overfit" and row.get("status") == "warn"
        ),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _decision(*, blockers: Sequence[str], checklist: Sequence[Mapping[str, Any]]) -> str:
    if blockers:
        return "btc_freqtrade_style_leakage_cli_blocked_missing_inputs_no_paper_no_live"
    if any(row.get("status") == "fail" for row in checklist):
        return "btc_freqtrade_style_leakage_cli_fail_closed_no_paper_no_live"
    if any(row.get("status") == "warn" for row in checklist):
        return "btc_freqtrade_style_leakage_cli_research_only_warnings_no_paper_no_live"
    return "btc_freqtrade_style_leakage_cli_passed_research_only_no_paper_no_live"


def _warnings(*, checklist: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_freqtrade_style_leakage_cli_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_freqtrade_style_leakage_cli_missing_source_artifacts")
    for row in checklist:
        if row.get("status") == "warn":
            warnings.append(f"check_warn:{row.get('category')}")
        if row.get("status") == "fail":
            warnings.append(f"check_fail:{row.get('category')}")
    return _dedupe(warnings)


def _load_sources(
    *,
    root: Path,
    leakage_report_path: Path,
    bar_replay_report_path: Path,
) -> tuple[dict[str, SourceArtifact], list[str]]:
    specs = {
        "leakage_report": (leakage_report_path, "source_missing:btc_strategy_leakage_overfit_audit_report"),
        "bar_replay_report": (bar_replay_report_path, "source_missing:btc_strategy_bar_replay_visibility_report"),
    }
    blockers: list[str] = []
    sources: dict[str, SourceArtifact] = {}
    for source_id, (path, missing_blocker) in specs.items():
        resolved = _resolve(root, path)
        payload = _read_json(resolved)
        if not payload:
            blockers.append(missing_blocker)
        sources[source_id] = SourceArtifact(source_id, resolved, payload, missing_blocker)
    return sources, blockers


def _freqtrade_reference(external_root: Path) -> dict[str, Any]:
    repo = external_root / "freqtrade"
    readme = repo / "README.md"
    return {
        "framework": "Freqtrade",
        "license_id": "GPL-3.0",
        "local_path": _portable_path(repo),
        "reference_readme_exists": readme.exists(),
        "commit": _git_head_short(repo),
        "concepts_used": [
            "lookahead_analysis_command_shape",
            "recursive_analysis_command_shape",
            "operator_readable_bias_report",
        ],
        "source_code_copied": False,
        "copy_allowed_after_review": False,
        "copy_policy": "GPL-3.0 design reference only; do not copy source into agent core.",
    }


def _source_hashes(*, sources: Mapping[str, SourceArtifact], freqtrade_ref: Mapping[str, Any]) -> dict[str, str]:
    values = {
        source_id: stable_payload_hash({"path": _portable_path(source.path), "payload": source.payload})
        for source_id, source in sources.items()
    }
    values["freqtrade_reference_commit"] = str(freqtrade_ref.get("commit", ""))
    values["freqtrade_reference_readme_exists"] = str(freqtrade_ref.get("reference_readme_exists", False))
    return values


def _safety_bits() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "strategy_skeleton_generated": False,
        "third_party_runtime_dependency_added": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "research_only_no_paper_no_live",
        "decision": report.get("decision"),
        **_mapping(report.get("gate")),
        "artifact_hash": report.get("artifact_hash"),
    }


def _write_checklist_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "category",
        "freqtrade_style_check",
        "scope_line",
        "status",
        "message_cn",
        "next_action_cn",
        "paper_gate_credit",
        "live_unlock_credit",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _resolve_external_root(root: Path, external_references_root: Path | None) -> Path:
    if external_references_root is not None:
        return _resolve(root, external_references_root)
    sibling = root.parent / "external_references"
    if sibling.exists():
        return sibling.resolve()
    return (root / "external_references").resolve()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _git_head_short(repo_path: Path) -> str:
    head_path = repo_path / ".git" / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        ref = head.split("ref:", 1)[1].strip()
        try:
            return (repo_path / ".git" / ref).read_text(encoding="utf-8").strip()[:7]
        except OSError:
            return ""
    return head[:7]


def _pass_fail(condition: bool) -> str:
    return "pass" if condition else "fail"


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
