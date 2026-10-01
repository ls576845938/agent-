from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_MULTI_STRATEGY_ATTRIBUTION_VERSION = "btc_multi_strategy_attribution_v1"

CRITICAL_STRATEGY_SOURCES = (
    "trend_forward_observation",
    "intraday_canonical_backtest",
    "ga_factor_diagnostics",
)

UNSAFE_TRUE_KEYS = {
    "live_order_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
    "real_orders_created",
    "paper_queue_write_allowed",
    "paper_or_live_unlock_allowed",
    "live_unlock_allowed",
    "oms_access_allowed",
    "broker_access_allowed",
    "strategy_skeleton_generated",
}


def build_btc_multi_strategy_attribution(
    *,
    generated_at_utc: datetime,
    sources: Mapping[str, Mapping[str, Any] | None],
    source_paths: Mapping[str, str] | None = None,
    report_paths: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    paths = dict(source_paths or {})
    blockers: list[str] = []
    warnings: list[str] = []

    for name in CRITICAL_STRATEGY_SOURCES:
        if not sources.get(name):
            blockers.append(f"btc_multi_strategy_attribution_source_missing:{name}")

    unsafe_flags = _unsafe_flags({name: payload for name, payload in sources.items() if payload})
    blockers.extend(f"btc_multi_strategy_attribution_unsafe_flag:{flag}" for flag in unsafe_flags)

    trend = _trend_bucket(_mapping(sources.get("trend_forward_observation")), paths)
    intraday = _intraday_bucket(
        canonical=_mapping(sources.get("intraday_canonical_backtest")),
        fold_audit=_mapping(sources.get("intraday_fold_audit")),
        trade_ledger_summary=_mapping(sources.get("intraday_trade_ledger_summary")),
        trade_attribution_summary=_mapping(sources.get("intraday_trade_attribution_summary")),
        paths=paths,
    )
    ga = _ga_bucket(_mapping(sources.get("ga_factor_diagnostics")), paths)
    buckets = {
        trend["strategy_bucket_id"]: trend,
        intraday["strategy_bucket_id"]: intraday,
        ga["strategy_bucket_id"]: ga,
    }

    auxiliary_models = _auxiliary_models(sources=sources, paths=paths)
    archived_candidates = _archived_candidates(sources=sources, paths=paths)
    contamination_controls = _contamination_controls(buckets)
    blockers.extend(
        f"btc_multi_strategy_attribution_contamination_violation:{item}"
        for item in contamination_controls["violations"]
    )

    payload = {
        "multi_strategy_attribution_version": BTC_MULTI_STRATEGY_ATTRIBUTION_VERSION,
        "status": "blocked" if blockers else "complete",
        "scope": "btc_read_only_multi_strategy_attribution",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "read_only": True,
        "strategy_buckets": buckets,
        "auxiliary_research_models": auxiliary_models,
        "archived_candidate_attribution": archived_candidates,
        "contamination_controls": contamination_controls,
        "gate": {
            "report_decision": "research_only_attribution_review",
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "reason": "multi-strategy attribution is evidence separation only; each strategy keeps its own gate",
        },
        "guardrails": {
            "live_order_allowed": False,
            "private_endpoint_used": _any_true(sources, "private_endpoint_used"),
            "order_endpoint_used": _any_true(sources, "order_endpoint_used"),
            "real_order_submitted": _any_true(sources, "real_order_submitted"),
            "paper_queue_write_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
        },
        "source_report_details": {
            name: _source_summary(name, payload, paths.get(name, ""))
            for name, payload in sources.items()
        },
        "report_paths": dict(report_paths or {}),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="btc_multi_strategy_attribution_complete"
        if not blockers
        else "btc_multi_strategy_attribution_blocked",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
        input_hashes={
            "sources": stable_payload_hash({name: payload or {} for name, payload in sources.items()}),
            "source_paths": stable_payload_hash(paths),
            "strategy_buckets": stable_payload_hash(buckets),
        },
    )


def render_btc_multi_strategy_attribution_markdown(report: Mapping[str, Any]) -> str:
    buckets = _mapping(report.get("strategy_buckets"))
    gate = _mapping(report.get("gate"))
    guardrails = _mapping(report.get("guardrails"))
    lines = [
        "# BTC 多策略归因只读报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 生成时间：`{report.get('generated_at')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 写 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        f"- 真实下单：`{guardrails.get('real_order_submitted')}`",
        "",
        "## 策略线归因",
        "",
    ]
    for bucket_id, bucket in buckets.items():
        bucket_map = _mapping(bucket)
        gate_map = _mapping(bucket_map.get("gate"))
        metrics = _mapping(bucket_map.get("metrics"))
        lines.extend(
            [
                f"### {bucket_id}",
                "",
                f"- 策略/来源：`{bucket_map.get('strategy_id')}`",
                f"- 归因范围：`{bucket_map.get('attribution_scope')}`",
                f"- 账本范围：`{bucket_map.get('ledger_scope')}`",
                f"- 来源 gate：`{gate_map.get('source_gate_status')}`",
                f"- 本报告 paper candidate 允许：`{gate_map.get('paper_candidate_allowed')}`",
                f"- 本报告 live 允许：`{gate_map.get('live_allowed')}`",
                f"- 核心指标：`{_compact_metrics(metrics)}`",
                "",
            ]
        )
    controls = _mapping(report.get("contamination_controls"))
    lines.extend(
        [
            "## 防污染控制",
            "",
            f"- 共用 ledger 允许：`{controls.get('shared_ledger_allowed')}`",
            f"- 跨策略复用 PnL 允许：`{controls.get('cross_strategy_pnl_reuse_allowed')}`",
            f"- 跨策略 gate 继承允许：`{controls.get('cross_strategy_gate_inheritance_allowed')}`",
            f"- 违规：`{controls.get('violations')}`",
            "",
            "说明：这是只读 evidence separation 报告，不写 paper 队列，不生成候选，不解锁 live，不触达 OMS/broker。",
            "",
        ]
    )
    return "\n".join(lines)


def _trend_bucket(daily: Mapping[str, Any], paths: Mapping[str, str]) -> dict[str, Any]:
    forward = _mapping(daily.get("forward_observation"))
    data = _mapping(daily.get("data"))
    guardrails = _mapping(daily.get("guardrails"))
    observation_days = _int_value(forward.get("observation_days"))
    source_status = str(daily.get("status") or "missing")
    gate_status = "forward_observation_incomplete"
    if source_status.upper() == "PASS" and observation_days >= 30:
        gate_status = "forward_observation_minimum_window_reached_needs_manual_review"
    elif source_status.upper() == "PASS":
        gate_status = "forward_observation_active_under_30_days"
    return {
        "strategy_bucket_id": "trend_forward_observation",
        "strategy_id": "btc_trend_raw_forward_observation",
        "source_type": "forward_observation_daily_report",
        "attribution_scope": "trend_forward_observation_only",
        "ledger_scope": "forward_observation_ledger_only",
        "source_paths": _non_empty_paths(
            {
                "daily_observation": paths.get("trend_forward_observation", ""),
            }
        ),
        "metrics": {
            "status": source_status,
            "observation_days": observation_days,
            "sample_start": data.get("sample_start"),
            "sample_end": data.get("sample_end"),
            "daily_rows": _int_value(data.get("daily_rows")),
            "public_rest_only": bool(data.get("public_rest_only", False)),
            "simulated_only": bool(guardrails.get("simulated_only", False)),
            "forward_observation_is_not_alpha_validation": bool(
                guardrails.get("forward_observation_is_not_alpha_validation", False)
            ),
        },
        "gate": {
            "source_gate_status": gate_status,
            "paper_candidate_allowed": False,
            "paper_queue_write_allowed": False,
            "live_allowed": False,
            "promotion_scope": "paper_observing_only_no_live_unlock",
            "blockers": []
            if observation_days >= 30
            else ["btc_trend_forward_observation_less_than_30_days"],
        },
        "contamination_policy": {
            "may_import_intraday_pnl": False,
            "may_import_ga_score": False,
            "may_unlock_other_strategy_gate": False,
        },
    }


def _intraday_bucket(
    *,
    canonical: Mapping[str, Any],
    fold_audit: Mapping[str, Any],
    trade_ledger_summary: Mapping[str, Any],
    trade_attribution_summary: Mapping[str, Any],
    paths: Mapping[str, str],
) -> dict[str, Any]:
    gate = _mapping(canonical.get("gate_decision"))
    metrics = _mapping(canonical.get("metrics"))
    strategy_id = str(canonical.get("strategy_id") or gate.get("strategy_id") or "btc_intraday_event_ledger")
    source_gate_status = str(gate.get("status") or canonical.get("status") or "missing")
    source_paths = _non_empty_paths(
        {
            "canonical_backtest": paths.get("intraday_canonical_backtest", ""),
            "fold_audit": paths.get("intraday_fold_audit", ""),
            "trade_ledger": paths.get("intraday_trade_ledger_summary", ""),
            "trade_attribution": paths.get("intraday_trade_attribution_summary", ""),
        }
    )
    return {
        "strategy_bucket_id": "intraday_event_ledger",
        "strategy_id": strategy_id,
        "source_type": "intraday_canonical_event_ledger_backtest",
        "attribution_scope": "intraday_event_ledger_only",
        "ledger_scope": "intraday_trade_ledger_only",
        "source_paths": source_paths,
        "metrics": {
            "source_gate_passed": bool(gate.get("passed", False)),
            "profit_factor": _float_or_none(metrics.get("profit_factor")),
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "total_return_pct": _float_or_none(metrics.get("total_return_pct")),
            "max_drawdown": _float_or_none(metrics.get("max_drawdown")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
            "trade_count": _int_value(metrics.get("trade_count")),
            "fill_count": _int_value(metrics.get("fill_count")),
            "trade_ledger_rows": _int_value(trade_ledger_summary.get("row_count")),
            "trade_attribution_rows": _int_value(trade_attribution_summary.get("row_count")),
            "fold_contract_status": _mapping(fold_audit.get("fold_contract")).get("status"),
            "regime_contract_status": _mapping(fold_audit.get("regime_contract")).get("status"),
        },
        "gate": {
            "source_gate_status": source_gate_status,
            "source_gate_passed": bool(gate.get("passed", False)),
            "source_fail_reasons": [str(item) for item in gate.get("fail_reasons", []) if item],
            "paper_candidate_allowed": False,
            "paper_queue_write_allowed": False,
            "live_allowed": False,
            "promotion_scope": "intraday_research_gate_only_manual_review_required",
            "blockers": [
                "btc_intraday_not_written_to_paper_queue_by_multi_strategy_attribution",
                "btc_intraday_requires_separate_manual_review_before_any_paper_candidate",
            ],
        },
        "contamination_policy": {
            "may_import_trend_forward_pnl": False,
            "may_import_ga_score": False,
            "may_unlock_other_strategy_gate": False,
        },
    }


def _ga_bucket(ga: Mapping[str, Any], paths: Mapping[str, str]) -> dict[str, Any]:
    summary = _mapping(ga.get("diagnostic_summary"))
    gate = _mapping(ga.get("gate"))
    promotion = _mapping(ga.get("promotion"))
    return {
        "strategy_bucket_id": "ga_factor_research",
        "strategy_id": "btc_ga_factor_expression_mining",
        "source_type": "ga_factor_diagnostics",
        "attribution_scope": "research_expression_only",
        "ledger_scope": "no_trade_ledger_expression_candidate_only",
        "source_paths": _non_empty_paths(
            {
                "ga_factor_diagnostics": paths.get("ga_factor_diagnostics", ""),
                "ga_candidate_review": paths.get("ga_candidate_review", ""),
            }
        ),
        "metrics": {
            "status": ga.get("status"),
            "source_decision": summary.get("source_decision"),
            "selected_candidate_count": _int_value(summary.get("selected_candidate_count")),
            "trial_count": _int_value(summary.get("trial_count")),
            "rejected_count": _int_value(summary.get("rejected_count")),
            "oos_pass_rate": _float_or_none(summary.get("oos_pass_rate")),
            "median_validation_profit_factor": _float_or_none(summary.get("median_validation_profit_factor")),
            "failure_reasons": [str(item) for item in summary.get("failure_reasons", []) if item],
        },
        "gate": {
            "source_gate_status": gate.get("current_ga_batch_decision")
            or promotion.get("recommendation")
            or ga.get("decision"),
            "paper_candidate_allowed": False,
            "paper_queue_write_allowed": False,
            "live_allowed": False,
            "promotion_scope": "research_only_expression_review_no_paper_or_live_unlock",
            "blockers": [
                str(item)
                for item in summary.get("failure_reasons", [])
                if item
            ]
            or ["btc_ga_factor_research_only"],
        },
        "contamination_policy": {
            "may_import_trend_forward_pnl": False,
            "may_import_intraday_ledger_pnl": False,
            "may_unlock_other_strategy_gate": False,
        },
    }


def _auxiliary_models(
    *,
    sources: Mapping[str, Mapping[str, Any] | None],
    paths: Mapping[str, str],
) -> dict[str, Any]:
    timesfm = _mapping(sources.get("timesfm_vs_trend_baseline"))
    if not timesfm:
        return {}
    comparison = _mapping(timesfm.get("comparison"))
    metrics = [item for item in comparison.get("metrics", []) if isinstance(item, Mapping)]
    timesfm_metric = _first_metric(metrics, "timesfm")
    best_metric = _best_metric(metrics)
    return {
        "timesfm_auxiliary_forecast": {
            "model_id": "timesfm",
            "source_type": "shared_forecasting_research_only",
            "attribution_scope": "auxiliary_model_diagnostic_only",
            "source_path": paths.get("timesfm_vs_trend_baseline", ""),
            "status": timesfm.get("status"),
            "decision_count": _nested_int(timesfm, "input.decision_count"),
            "timesfm_evaluation": _mapping(timesfm_metric.get("evaluation")),
            "best_oos_metric_model_id": best_metric.get("model_id"),
            "best_oos_evaluation": _mapping(best_metric.get("evaluation")),
            "gate": {
                "paper_candidate_allowed": False,
                "live_allowed": False,
                "reason": _mapping(timesfm.get("gate")).get("reason")
                or "TimesFM is auxiliary research only",
            },
        }
    }


def _archived_candidates(
    *,
    sources: Mapping[str, Mapping[str, Any] | None],
    paths: Mapping[str, str],
) -> dict[str, Any]:
    compression = _mapping(sources.get("compression_expansion_attribution"))
    if not compression:
        return {}
    return {
        "compression_expansion_breakout": {
            "source_path": paths.get("compression_expansion_attribution", ""),
            "status": compression.get("status"),
            "strategy_id": compression.get("strategy_id"),
            "gate_status": compression.get("gate_status"),
            "allowed_next_action": compression.get("allowed_next_action"),
            "paper_review_pending_allowed": bool(compression.get("paper_review_pending_allowed", False)),
            "promotion_ready": bool(compression.get("promotion_ready", False)),
            "paper_queue": compression.get("paper_queue"),
            "live": compression.get("live"),
            "candidate_metrics": _mapping(compression.get("candidate_metrics")),
            "blockers": [str(item) for item in compression.get("blockers", []) if item],
        }
    }


def _contamination_controls(buckets: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    bucket_source_paths: dict[str, list[str]] = {}
    ledger_scopes: dict[str, str] = {}
    violations: list[str] = []
    seen_ledger_paths: dict[str, str] = {}
    for bucket_id, bucket in buckets.items():
        source_paths = _mapping(bucket.get("source_paths"))
        bucket_source_paths[bucket_id] = [str(value) for value in source_paths.values() if value]
        ledger_scope = str(bucket.get("ledger_scope") or "")
        ledger_scopes[bucket_id] = ledger_scope
        for label, path in source_paths.items():
            label_text = str(label)
            path_text = str(path)
            if not path_text or "ledger" not in label_text:
                continue
            previous = seen_ledger_paths.get(path_text)
            if previous and previous != bucket_id:
                violations.append(f"shared_ledger_path:{previous}:{bucket_id}:{path_text}")
            seen_ledger_paths[path_text] = bucket_id
    return {
        "shared_ledger_allowed": False,
        "cross_strategy_pnl_reuse_allowed": False,
        "cross_strategy_gate_inheritance_allowed": False,
        "strategy_bucket_ids": list(buckets.keys()),
        "per_bucket_source_paths": bucket_source_paths,
        "per_bucket_ledger_scope": ledger_scopes,
        "policy": [
            "trend_forward_observation_does_not_inherit_intraday_or_ga_pnl",
            "intraday_event_ledger_does_not_inherit_trend_or_ga_pnl",
            "ga_factor_research_has_no_trade_ledger_and_cannot_unlock_paper_or_live",
        ],
        "violations": _dedupe(violations),
    }


def _source_summary(name: str, payload: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    data = _mapping(payload)
    return {
        "source_name": name,
        "path": path,
        "present": bool(data),
        "status": _summary_status(data),
        "decision": str(data.get("decision") or ""),
        "generated_at": str(data.get("generated_at") or data.get("generated_at_utc") or ""),
        "as_of_utc": str(data.get("as_of_utc") or ""),
        "artifact_hash": str(data.get("artifact_hash") or stable_payload_hash(data)) if data else "",
        "blockers": [str(item) for item in data.get("blockers", []) if item],
    }


def _summary_status(payload: Mapping[str, Any]) -> str:
    if not payload:
        return "missing"
    for key in ("status", "gate_status", "decision"):
        if payload.get(key):
            return str(payload[key])
    gate = _mapping(payload.get("gate_decision"))
    if gate.get("status"):
        return str(gate["status"])
    return "present"


def _unsafe_flags(sources: Mapping[str, Mapping[str, Any]]) -> list[str]:
    flags: list[str] = []
    for source_name, payload in sources.items():
        for path, value in _walk(payload):
            if value is True and path.split(".")[-1] in UNSAFE_TRUE_KEYS:
                flags.append(f"{source_name}.{path}=true")
    return _dedupe(flags)


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _any_true(sources: Mapping[str, Mapping[str, Any] | None], key: str) -> bool:
    return any(path.endswith(key) and value is True for payload in sources.values() for path, value in _walk(payload or {}))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_int(payload: Mapping[str, Any], path: str) -> int:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return 0
        value = value.get(part)
    return _int_value(value)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _non_empty_paths(paths: Mapping[str, str]) -> dict[str, str]:
    return {key: str(value) for key, value in paths.items() if value}


def _first_metric(metrics: list[Mapping[str, Any]], token: str) -> Mapping[str, Any]:
    token_lower = token.lower()
    for item in metrics:
        if token_lower in str(item.get("model_id", "")).lower():
            return item
    return {}


def _best_metric(metrics: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not metrics:
        return {}

    def score(item: Mapping[str, Any]) -> tuple[float, float]:
        evaluation = _mapping(item.get("evaluation"))
        return (
            _float_or_none(evaluation.get("profit_factor")) or -1.0,
            _float_or_none(evaluation.get("total_return")) or -1.0,
        )

    return max(metrics, key=score)


def _compact_metrics(metrics: Mapping[str, Any]) -> str:
    selected = {
        key: value
        for key, value in metrics.items()
        if key
        in {
            "observation_days",
            "profit_factor",
            "event_profit_factor",
            "total_return_pct",
            "max_drawdown",
            "selected_candidate_count",
            "trial_count",
            "oos_pass_rate",
            "median_validation_profit_factor",
        }
    }
    return ", ".join(f"{key}={value}" for key, value in selected.items()) or "no compact metrics"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
