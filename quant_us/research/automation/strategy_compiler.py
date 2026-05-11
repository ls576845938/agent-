"""Compile research-only strategy logic/config artifacts from factor candidates.

The compiler turns mined factor candidates into reproducible, reviewable
research artifacts. It does not auto-enable paper trading or live trading.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from quant_us.core.clock import utc_now


def normalize_validation_summary(
    validation_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize PBO/DSR/CPCV summaries for compiled research artifacts."""
    payload = dict(validation_summary or {})
    if not payload:
        return {
            "status": "pending_research_validation",
            "pbo": {
                "pbo": None,
                "passed": None,
                "missing_reason": "requires_cpcv_or_walk_forward_backtest",
            },
            "dsr": {
                "dsr": None,
                "passed": None,
                "missing_reason": "requires_backtest_return_distribution",
            },
            "cpcv": {
                "method": None,
                "path_count": 0,
                "fold_count": 0,
                "purged": None,
                "embargoed": None,
                "passed": None,
                "missing_reason": "requires_cpcv_or_purged_walk_forward_validation",
            },
            "available_components": {
                "pbo": False,
                "dsr": False,
                "cpcv": False,
            },
        }

    cv_summary = dict(payload.get("cv_summary", {}) or {})
    dsr_summary = dict(payload.get("deflated_sharpe_ratio", {}) or {})
    pbo_summary = dict(payload.get("pbo", {}) or {})
    available = dict(payload.get("available_components", {}) or {})
    method = str(cv_summary.get("method", "") or "").lower() or None
    cpcv_allowed = method == "cpcv"

    normalized = {
        "status": str(payload.get("status", "partial") or "partial"),
        "pbo": {
            "pbo": pbo_summary.get("pbo"),
            "passed": pbo_summary.get("passed"),
            "trial_count": pbo_summary.get("trial_count"),
            "overfit_path_count": pbo_summary.get("overfit_path_count"),
            "missing_reason": None if pbo_summary.get("pbo") is not None else "pbo_missing_from_validation",
        },
        "dsr": {
            "dsr": dsr_summary.get("dsr"),
            "passed": dsr_summary.get("passed"),
            "observed_sharpe": dsr_summary.get("observed_sharpe"),
            "trial_count": dsr_summary.get("trial_count"),
            "missing_reason": None if dsr_summary.get("dsr") is not None else "deflated_sharpe_ratio_missing_from_validation",
        },
        "cpcv": {
            "method": method,
            "path_count": int(cv_summary.get("path_count", 0) or 0),
            "fold_count": int(cv_summary.get("fold_count", 0) or 0),
            "purged": cv_summary.get("purged"),
            "embargoed": cv_summary.get("embargoed"),
            "pass_rate": cv_summary.get("pass_rate"),
            "passed": True if cpcv_allowed and int(cv_summary.get("path_count", 0) or 0) > 0 else None,
            "missing_reason": None if cpcv_allowed and int(cv_summary.get("path_count", 0) or 0) > 0 else "cpcv_validation_metadata_missing",
        },
        "available_components": {
            "pbo": bool(available.get("pbo", pbo_summary.get("pbo") is not None)),
            "dsr": bool(
                available.get("deflated_sharpe_ratio", dsr_summary.get("dsr") is not None)
            ),
            "cpcv": bool(
                method == "cpcv"
                and int(cv_summary.get("path_count", 0) or 0) > 0
            ),
        },
    }
    return normalized


class ResearchStrategyCompiler:
    """Persist research-only strategy artifacts with logic and evidence."""

    compiler_name = "research_strategy_compiler"
    compiler_version = "v1"
    schema_version = "research_strategy_artifact_v1"

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def compile(
        self,
        *,
        run_id: str,
        strategy_key: str,
        logic: Mapping[str, Any],
        config: Mapping[str, Any],
        candidate_evidence: Mapping[str, Any] | None = None,
        validation_summary: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], Path]:
        artifact = self.build_artifact(
            run_id=run_id,
            strategy_key=strategy_key,
            logic=logic,
            config=config,
            candidate_evidence=candidate_evidence,
            validation_summary=validation_summary,
        )
        path = self._artifact_path(run_id, strategy_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(artifact, indent=2, default=str, sort_keys=True),
            encoding="utf-8",
        )
        return artifact, path

    def build_artifact(
        self,
        *,
        run_id: str,
        strategy_key: str,
        logic: Mapping[str, Any],
        config: Mapping[str, Any],
        candidate_evidence: Mapping[str, Any] | None = None,
        validation_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = dict(candidate_evidence or {})
        normalized_validation = normalize_validation_summary(validation_summary)
        logic_payload = dict(logic)
        artifact = {
            **logic_payload,
            "schema_version": self.schema_version,
            "artifact_type": "research_strategy_logic_template",
            "compiler": {
                "name": self.compiler_name,
                "version": self.compiler_version,
                "run_id": run_id,
                "strategy_key": strategy_key,
                "generated_at": utc_now().isoformat(),
            },
            "reproducibility": {
                "template_id": config.get("template_id"),
                "strategy_id": config.get("strategy_id"),
                "bar_size": config.get("bar_size"),
                "timeframe": config.get("timeframe"),
                "symbols": list(config.get("symbols", []) or []),
                "factor_ids": list(config.get("factor_ids", []) or []),
                "params": dict(config.get("params", {}) or {}),
                "candidate_rank": config.get("candidate_rank"),
                "research_score": config.get("research_score"),
                "generation_family": evidence.get("generation_family"),
                "generation_families": dict(evidence.get("generation_families", {}) or {}),
                "formula_signature": evidence.get("formula_signature"),
                "component_formula_signatures": dict(
                    evidence.get("component_formula_signatures", {}) or {}
                ),
            },
            "research_controls": {
                "promotion_status": "RESEARCH_ONLY",
                "paper_trading_enabled": False,
                "live_trading_enabled": False,
                "auto_paper": False,
                "auto_live": False,
                "requires_manual_review": True,
            },
            "safeguards": {
                "no_lookahead": {
                    "status": "required",
                    "guard": logic_payload.get("lookahead_guard"),
                    "execution_semantics": logic_payload.get("execution_semantics"),
                },
                "capacity": dict(evidence.get("capacity", {}) or {}),
                "turnover": dict(evidence.get("turnover", {}) or {}),
                "style_exposure": dict(evidence.get("style_exposure", {}) or {}),
            },
            "validation_summary": normalized_validation,
            "candidate_evidence": evidence,
        }
        return artifact

    def _artifact_path(self, run_id: str, strategy_key: str) -> Path:
        return (
            self.data_root
            / "research"
            / "generated_strategies"
            / f"{run_id}_{_safe_name(strategy_key)}.json"
        )


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value)).strip("_")[:120] or "item"
