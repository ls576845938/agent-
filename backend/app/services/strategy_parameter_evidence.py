"""Read-only, hash-bound projection of historical parameter-search evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from quant_crypto.adapters.btc_runtime_artifact_store import BTCRuntimeArtifactReader

HISTORY_ROOT_ENV = "QS_BTC_STRATEGY_HISTORY_ARTIFACT_ROOT"
PARAMETER_POINTER = "artifacts/strategy_parameter_map/index.json"
SCHEMA = "strategy_parameter_evidence_v1"
FALSE_FLAGS = ("paper", "live", "promotion", "private", "order", "real_order", "transfer", "withdraw")
SOURCE_FLAGS = ("broker_access_allowed", "live_order_allowed", "live_unlock_allowed", "oms_access_allowed", "order_endpoint_used", "paper_candidate_created", "paper_queue_write_allowed", "private_endpoint_used", "real_order_submitted")
METRICS = ("sharpe_ratio", "annual_return_pct", "max_drawdown_pct", "sortino_ratio")


class ParameterEvidenceError(ValueError):
    pass


def configured_history_reader(_promotion_reader: Any = None) -> Any:
    """Require an explicit history root; never consume a promotion reader."""
    root = os.environ.get(HISTORY_ROOT_ENV, "").strip()
    if not root:
        return None
    return BTCRuntimeArtifactReader.from_environment(
        source_repo_root=Path(__file__).resolve().parents[3],
        environment={"QS_BTC_RUNTIME_ARTIFACT_ROOT": root},
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def project_parameter_evidence(report: dict, *, source_sha256: str) -> dict:
    if report.get("schema_version") != "btc_long_short_trend_following_lab_v1" or report.get("status") != "complete_research_only":
        raise ParameterEvidenceError("parameter_source_schema_or_status_invalid")
    if re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
        raise ParameterEvidenceError("parameter_source_hash_invalid")
    if any(report.get("guardrails", {}).get(key) is not False for key in SOURCE_FLAGS):
        raise ParameterEvidenceError("parameter_source_safety_invalid")
    design, data = report.get("validation_design", {}), report.get("input", {})
    source_rows = report.get("long_short_research_rows", [])
    if not isinstance(source_rows, list) or not 0 < len(source_rows) <= 10000 or len(source_rows) != design.get("long_short_candidate_count"):
        raise ParameterEvidenceError("parameter_source_candidate_count_invalid")
    for key in ("exchange", "symbol", "source_interval", "base_decision_interval", "bar_4h_start", "bar_4h_end"):
        if not data.get(key):
            raise ParameterEvidenceError("parameter_source_data_context_missing")
    base_cost = design.get("cost_model", {}).get("base_cost_bps")
    if not _finite(base_cost) or base_cost < 0 or not design.get("execution_rule"):
        raise ParameterEvidenceError("parameter_source_execution_context_missing")
    rows, seen, seen_params = [], set(), set()
    for item in source_rows:
        identity, params = item.get("candidate_id"), item.get("params")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ParameterEvidenceError("parameter_source_candidate_identity_invalid")
        if not isinstance(params, dict) or not params or any(not isinstance(v, (str, int, float, bool)) or (isinstance(v, float) and not math.isfinite(v)) for v in params.values()):
            raise ParameterEvidenceError("parameter_source_params_invalid")
        seen.add(identity)
        parameter_bytes = json.dumps(params, sort_keys=True, allow_nan=False).encode("utf-8")
        parameter_hash = hashlib.sha256(parameter_bytes).hexdigest()
        if parameter_hash in seen_params:
            raise ParameterEvidenceError("parameter_source_duplicate_params")
        if item.get("params_hash") is not None and item["params_hash"] != hashlib.sha1(parameter_bytes).hexdigest()[:12]:
            raise ParameterEvidenceError("parameter_source_params_hash_mismatch")
        seen_params.add(parameter_hash)
        scenarios = [s for s in item.get("cost_stress", {}).get("scenarios", []) if s.get("cost_bps") == base_cost]
        if len(scenarios) != 1:
            raise ParameterEvidenceError("parameter_source_base_cost_scenario_missing_or_ambiguous")
        metrics = scenarios[0].get("metrics", {})
        for key in METRICS:
            if key in metrics and metrics[key] is not None and not _finite(metrics[key]):
                raise ParameterEvidenceError("parameter_source_metric_nonfinite")
            if key in item and item[key] != metrics.get(key):
                raise ParameterEvidenceError("parameter_source_metric_mismatch")
        family = item.get("family_id") or params.get("signal_type") or "unknown"
        stage = item.get("optimization_stage") or "unspecified"
        rows.append({"candidate_id": identity, "family": f"{family} / {stage}", "params_hash": parameter_hash, "params": params, "metrics": {key: metrics.get(key) for key in METRICS}})
    return {
        "schema_version": SCHEMA, "status": "historical_research_only", "rows": rows,
        "source": {"report_path": "artifacts/btc_long_short_trend_following_lab/latest/btc_long_short_trend_following_lab_report.json", "report_sha256": source_sha256, "code_commit": report.get("code_commit"), "generated_at": report.get("generated_at_utc"), "data": {k: data[k] for k in ("exchange", "symbol", "source_interval", "base_decision_interval", "bar_4h_start", "bar_4h_end")}, "cost_model": design["cost_model"], "funding_model": design.get("funding_model", {}), "execution_rule": design["execution_rule"], "sample": "full_research_window_already_used_for_selection", "freshness": "historical_not_current_head"},
        "coverage": {"published_count": len(rows), "declared_count": design["long_short_candidate_count"], "selection": "all_published_long_short_rows_not_top5"},
        "limitations": ["source_data_hashes_unavailable", "historical_window_already_used_for_selection", "not_replay_or_promotion_evidence"],
        "safety": {key: False for key in FALSE_FLAGS},
    }


def load_parameter_evidence(reader: Any, *, strategy_id: str) -> dict:
    if strategy_id not in ("long_short_donchian_top5", "long_short_donchian_top5_okx_native"):
        raise LookupError("该策略尚未发布可验证的参数网格")
    pointer = reader.read_json(PARAMETER_POINTER)
    digest = str(pointer.get("sha256", ""))
    path = f"artifacts/strategy_parameter_map/runs/{digest}/evidence.json"
    if pointer.get("schema_version") != SCHEMA or re.fullmatch(r"[0-9a-f]{64}", digest) is None or pointer.get("path") != path:
        raise ParameterEvidenceError("parameter_evidence_pointer_invalid")
    raw = reader.read_bytes(path)
    if len(raw) > 8_000_000 or hashlib.sha256(raw).hexdigest() != digest:
        raise ParameterEvidenceError("parameter_evidence_hash_invalid")
    payload = json.loads(raw)
    if payload.get("schema_version") != SCHEMA or payload.get("status") != "historical_research_only" or any(payload.get("safety", {}).get(k) is not False for k in FALSE_FLAGS):
        raise ParameterEvidenceError("parameter_evidence_contract_invalid")
    return {**payload, "strategy_id": strategy_id, "evidence_sha256": digest,
            "relationship": "同公式历史研究基线（非 OKX-native 原生回测）" if strategy_id.endswith("_okx_native") else "历史研究参数搜索 · Binance 现货信号 / 永续模拟"}
