"""Research promotion gate for evaluating candidate readiness.

Determines whether a strategy candidate is ready to proceed to
human paper-review evaluation. This is the final automated research
arbiter before paper review; it NEVER triggers paper trading or live
trading.

Decision outcomes:
- BLOCKED: Missing required evidence or fatal risk.
- WATCHLIST: Some checks passed but needs more data or analysis.
- NEED_MORE_RESEARCH: Additional research required before promotion
  (e.g., high correlation redundancy).
- READY_FOR_PAPER_REVIEW: All checks pass. Candidate enters
  the human review pool for paper trading consideration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from quant_us.data.storage.data_manifest import (
    DataManifest,
    DataManifestStore,
    validate_manifest_for_promotion,
)
from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash


ALLOWED_DATA_SOURCES = {"yfinance", "alpaca", "sqlite"}
CRYPTO_SYMBOL_SUFFIXES = ("USDT", "USD", "BTC", "ETH")
DATA_MANIFEST_ADVISORY_WARNINGS = {
    "universe_id_missing",
    "universe_source_missing",
    "survivorship_bias_risk_unmarked",
}


@dataclass
class PromotionGateResult:
    """Result of a promotion gate evaluation.

    Attributes:
        candidate_id: The evaluated candidate.
        decision: BLOCKED | WATCHLIST | NEED_MORE_RESEARCH | READY_FOR_PAPER_REVIEW.
        reasons: Blocking reasons (fatal issues).
        warnings: Non-blocking concerns.
        needs_more_research: Items requiring additional research before promotion.
        evidence: Dict of evidence collected during evaluation, e.g.
            {"manifest_exists": True, "scorecard_exists": True, ...}.
    """

    candidate_id: str
    decision: str = "BLOCKED"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_more_research: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


class ResearchPromotionGate:
    """Evaluate candidates for promotion from research to paper review.

    The gate checks REQUIRED evidence:
    - ExperimentManifest exists
    - RobustScorecard exists
    - Canonical backtest manifest evidence exists
    - OverfitDetector report (no overfit)
    - WalkForward result (must be run)
    - Trade count > 10
    - Cost stress passed
    - Max drawdown < 50%
    - Monte Carlo survival rate > 80%  (R6)
    - Alpha decay half-life > 5 days   (R6)
    - Param stability score > 0.5      (R6)
    - Correlation redundancy < 0.70    (R7)
    - Stress survival rate > 70%       (R8)

    READY_FOR_PAPER_REVIEW means the candidate is ready for HUMAN REVIEW
    only. It does NOT enter paper trading automatically.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def evaluate(self, candidate_id: str) -> PromotionGateResult:
        """Evaluate a candidate for promotion readiness."""
        reasons: list[str] = []
        warnings: list[str] = []
        evidence: dict[str, Any] = {}
        needs_more_research: list[str] = []

        candidate_data = self._load_candidate(candidate_id)
        manifest_exists = candidate_data is not None
        evidence["manifest_exists"] = manifest_exists
        if not manifest_exists:
            reasons.append("missing_manifest: candidate file not found")
            return PromotionGateResult(
                candidate_id=candidate_id,
                decision="BLOCKED",
                reasons=reasons,
                warnings=warnings,
                needs_more_research=needs_more_research,
                evidence=evidence,
            )

        metrics = candidate_data.get("metrics", {}) or {}
        stored_status = str(candidate_data.get("promotion_status", "RESEARCH_ONLY"))
        evidence["stored_promotion_status"] = stored_status

        experiment_id = candidate_data.get("experiment_id", "")
        experiment_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        manifest_ok = experiment_path.exists()
        evidence["experiment_manifest_exists"] = manifest_ok
        experiment_data: dict[str, Any] = {}
        if not manifest_ok:
            reasons.append("missing_manifest: experiment manifest not found")
        else:
            experiment_data = json.loads(experiment_path.read_text(encoding="utf-8"))

        backtest_manifest = self._load_backtest_manifest(
            candidate_data=candidate_data,
            metrics=metrics,
            evidence=evidence,
            reasons=reasons,
        )
        self._evaluate_data_scope(
            candidate_data=candidate_data,
            experiment_data=experiment_data,
            backtest_manifest=backtest_manifest,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
        )

        scorecard_path = (
            self.data_root
            / "research"
            / "scorecards"
            / f"{candidate_id}.json"
        )
        scorecard_exists = scorecard_path.exists()
        evidence["scorecard_exists"] = scorecard_exists
        if not scorecard_exists:
            reasons.append("missing_scorecard: robust scorecard not found")

        from quant_us.research.automation.overfit import OverfitDetector

        detector = OverfitDetector(data_root=str(self.data_root))
        try:
            report = detector.check(candidate_id)
            evidence["overfit_report"] = {
                "is_overfit": report.is_overfit,
                "degradation_pct": report.degradation_pct,
                "reason_count": len(report.reasons),
            }
            if report.is_overfit:
                reasons.append("overfit_risk_high: " + "; ".join(report.reasons))
        except ValueError:
            evidence["overfit_report"] = {"error": "candidate_not_found"}
            reasons.append("missing_data: cannot run overfit check")

        self._evaluate_event_ledger_evidence(
            metrics=metrics,
            backtest_manifest=backtest_manifest,
            evidence=evidence,
            reasons=reasons,
        )
        self._record_unified_backtest_report_evidence(
            backtest_manifest=backtest_manifest,
            evidence=evidence,
            reasons=reasons,
        )

        wf_pass_rate = float(metrics.get("walk_forward_pass_rate", -1.0))
        wf_run = wf_pass_rate >= 0.0
        evidence["walk_forward_run"] = wf_run
        if not wf_run:
            warnings.append("needs_walk_forward: walk-forward analysis not run")

        trade_count = int(metrics.get("trade_count", 0))
        evidence["trade_count"] = trade_count
        if trade_count <= 10:
            warnings.append(
                f"trade_count_too_low: only {trade_count} trades "
                f"(need > 10 for statistical significance)"
            )

        cost_sensitivity = float(metrics.get("cost_sensitivity", 0.0))
        evidence["cost_sensitivity"] = cost_sensitivity
        if cost_sensitivity > 0.5:
            reasons.append(
                f"cost_impact_too_high: cost_sensitivity={cost_sensitivity:.3f} "
                "(> 0.5 threshold)"
            )

        max_dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
        evidence["max_drawdown"] = max_dd
        if max_dd >= 0.50:
            reasons.append(
                f"max_drawdown_too_high: {max_dd:.1%} "
                "(>= 50% threshold)"
            )

        monte_carlo_survival = float(metrics.get("monte_carlo_survival_rate", 0.0))
        evidence["monte_carlo_survival_rate"] = monte_carlo_survival
        if monte_carlo_survival <= 0.80:
            reasons.append(
                f"monte_carlo_survival_low: survival_rate={monte_carlo_survival:.3f} "
                "(<= 0.80 threshold)"
            )

        alpha_decay_half_life = float(metrics.get("alpha_decay_half_life_days", 0.0))
        evidence["alpha_decay_half_life_days"] = alpha_decay_half_life
        if alpha_decay_half_life <= 5.0:
            warnings.append(
                f"rapid_alpha_decay: half_life={alpha_decay_half_life:.1f} days "
                "(<= 5 days threshold)"
            )

        param_stability = float(metrics.get("param_stability_score", 0.0))
        evidence["param_stability_score"] = param_stability
        if param_stability <= 0.5:
            reasons.append(
                f"param_unstable: stability_score={param_stability:.3f} "
                "(<= 0.5 threshold)"
            )

        correlation_redundancy = float(metrics.get("correlation_redundancy", 0.0))
        evidence["correlation_redundancy"] = correlation_redundancy
        if correlation_redundancy >= 0.70:
            needs_more_research.append(
                f"high_redundancy: correlation_redundancy={correlation_redundancy:.3f} "
                "(>= 0.70 threshold)"
            )

        stress_survival_rate = float(metrics.get("stress_survival_rate", 0.0))
        evidence["stress_survival_rate"] = stress_survival_rate
        if stress_survival_rate <= 0.70:
            reasons.append(
                f"stress_survival_low: survival_rate={stress_survival_rate:.3f} "
                "(<= 0.70 threshold)"
            )

        if stored_status == "PAPER_ELIGIBLE" and (
            reasons or warnings or needs_more_research
        ):
            reasons.append(
                "promotion_status_inconsistent: stored PAPER_ELIGIBLE but "
                "current gate evidence is not clean"
            )

        if reasons:
            decision = "BLOCKED"
        elif needs_more_research:
            decision = "NEED_MORE_RESEARCH"
        elif warnings:
            decision = "WATCHLIST"
        else:
            decision = "READY_FOR_PAPER_REVIEW"

        return PromotionGateResult(
            candidate_id=candidate_id,
            decision=decision,
            reasons=reasons,
            warnings=warnings,
            needs_more_research=needs_more_research,
            evidence=evidence,
        )

    def _load_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_backtest_manifest(
        self,
        *,
        candidate_data: dict[str, Any],
        metrics: dict[str, Any],
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any] | None:
        raw_path = (
            candidate_data.get("backtest_manifest_path")
            or metrics.get("backtest_manifest_path")
            or ""
        )
        inline_manifest = (
            candidate_data.get("backtest_manifest")
            or metrics.get("backtest_manifest")
        )

        evidence["backtest_manifest_path"] = str(raw_path or "")
        evidence["backtest_manifest_inline"] = isinstance(inline_manifest, dict)
        evidence["backtest_manifest_present"] = False

        manifest_path = self._resolve_backtest_manifest_path(raw_path)
        if manifest_path is None:
            evidence["backtest_manifest_source"] = (
                "inline_untrusted" if isinstance(inline_manifest, dict) else "missing"
            )
            if isinstance(inline_manifest, dict):
                reasons.append(
                    "inline_backtest_manifest_not_allowed: promotion requires a "
                    "persisted canonical backtest_manifest_path"
                )
            reasons.append(
                "missing_backtest_manifest_evidence: READY_FOR_PAPER_REVIEW requires canonical backtest manifest evidence"
            )
            return None

        if not manifest_path.exists():
            evidence["backtest_manifest_source"] = "missing"
            reasons.append(
                f"backtest_manifest_path_missing: manifest not found at {manifest_path}"
            )
            if isinstance(inline_manifest, dict):
                reasons.append(
                    "inline_backtest_manifest_not_allowed: inline manifest cannot "
                    "replace a missing persisted backtest manifest"
                )
            reasons.append(
                "missing_backtest_manifest_evidence: READY_FOR_PAPER_REVIEW requires canonical backtest manifest evidence"
            )
            return None

        evidence["backtest_manifest_present"] = True
        evidence["backtest_manifest_source"] = "path"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        evidence["backtest_manifest_engine"] = str(manifest.get("engine", ""))
        evidence["backtest_manifest_canonical_for_promotion"] = bool(
            manifest.get("canonical_for_promotion", False)
        )
        return manifest

    def _resolve_backtest_manifest_path(self, raw_path: Any) -> Path | None:
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        if candidate.exists() or candidate.is_absolute():
            return candidate
        data_relative = self.data_root / candidate
        if data_relative.exists():
            return data_relative
        return candidate

    def _evaluate_data_scope(
        self,
        candidate_data: dict[str, Any],
        experiment_data: dict[str, Any],
        backtest_manifest: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
        warnings: list[str],
    ) -> None:
        metrics = candidate_data.get("metrics", {}) or {}
        manifest_evidence = (
            backtest_manifest.get("evidence", {}) if isinstance(backtest_manifest, dict) else {}
        )
        manifest_scope = manifest_evidence.get("data_scope", {}) or {}
        embedded_data_manifest = self._embedded_data_manifest(backtest_manifest)

        symbols = (
            candidate_data.get("symbols")
            or experiment_data.get("symbols")
            or metrics.get("symbols")
            or []
        )
        if isinstance(symbols, str):
            symbols = [symbols]
        normalized_symbols = [str(symbol).upper() for symbol in symbols]
        data_version = str(
            (backtest_manifest or {}).get("data_version", "")
            or candidate_data.get("data_version")
            or experiment_data.get("data_version")
            or metrics.get("data_version")
            or ""
        )
        data_source = str(
            getattr(embedded_data_manifest, "source", "")
            or candidate_data.get("data_source")
            or candidate_data.get("data_vendor")
            or candidate_data.get("source")
            or experiment_data.get("data_source")
            or experiment_data.get("data_vendor")
            or experiment_data.get("source")
            or metrics.get("data_source")
            or metrics.get("data_vendor")
            or metrics.get("source")
            or self._source_from_data_version(data_version)
            or ""
        ).lower()
        asset_class = str(
            getattr(embedded_data_manifest, "asset_class", "")
            or candidate_data.get("asset_class")
            or experiment_data.get("asset_class")
            or metrics.get("asset_class")
            or self._asset_class(normalized_symbols)
        ).lower()
        fixture_used = bool(manifest_scope.get("fixture_like_data_version", False)) or (
            data_source == "fixture" or "fixture" in data_version.lower()
        )
        scope_rejections = [
            str(item) for item in manifest_scope.get("scope_rejections", []) or []
        ]

        evidence["symbols"] = normalized_symbols
        evidence["data_version"] = data_version
        evidence["data_source"] = data_source
        evidence["asset_class"] = asset_class
        evidence["fixture_used"] = fixture_used
        evidence["backtest_manifest_scope_ok"] = bool(
            manifest_scope.get("promotion_scope_ok", True)
        )
        if scope_rejections:
            evidence["backtest_manifest_scope_rejections"] = scope_rejections

        if not normalized_symbols:
            reasons.append("missing_symbols: promotion requires explicit US equity symbols")
        if not data_version:
            reasons.append("missing_data_version: promotion requires governed data_version evidence")
        if fixture_used:
            reasons.append("fixture_data_not_allowed: fixture evidence cannot enter paper review")
        if scope_rejections:
            reasons.extend(
                f"backtest_manifest_scope_rejection:{rejection}"
                for rejection in scope_rejections
            )
        if (
            isinstance(backtest_manifest, dict)
            and manifest_scope
            and not bool(manifest_scope.get("promotion_scope_ok", False))
            and not scope_rejections
        ):
            reasons.append(
                "backtest_manifest_scope_invalid: manifest marks evidence out of promotion scope"
            )
        if data_source not in ALLOWED_DATA_SOURCES:
            reasons.append(
                f"unsupported_data_source: data_source={data_source or 'unknown'} "
                f"(allowed={sorted(ALLOWED_DATA_SOURCES)})"
            )
        if asset_class != "equity":
            reasons.append(
                f"asset_class_not_allowed: asset_class={asset_class or 'unknown'} "
                "must be equity"
            )
        if data_version:
            self._evaluate_data_manifest(
                data_version=data_version,
                data_source=data_source,
                asset_class=asset_class,
                symbols=normalized_symbols,
                embedded_manifest=embedded_data_manifest,
                evidence=evidence,
                reasons=reasons,
                warnings=warnings,
            )

    def _evaluate_event_ledger_evidence(
        self,
        *,
        metrics: dict[str, Any],
        backtest_manifest: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> None:
        manifest_evidence = (
            backtest_manifest.get("evidence", {}) if isinstance(backtest_manifest, dict) else {}
        )
        manifest_orders = manifest_evidence.get("orders", {}) or {}
        manifest_fills = manifest_evidence.get("fills", {}) or {}
        manifest_equity = manifest_evidence.get("equity", {}) or {}
        manifest_completeness = manifest_evidence.get("completeness", {}) or {}

        engine = str(
            (backtest_manifest or {}).get("engine", "")
            or metrics.get("engine")
            or metrics.get("canonical_engine")
            or metrics.get("backtest_engine")
            or ""
        )
        canonical_for_promotion = bool(
            (backtest_manifest or {}).get("canonical_for_promotion", False)
        ) if isinstance(backtest_manifest, dict) else False
        ledger_consistency_pct = (
            100.0
            if bool(manifest_equity.get("consistent", False))
            else self._as_pct(
                metrics.get(
                    "ledger_consistency_pct",
                    metrics.get("ledger_equity_consistency_pct", -1.0),
                )
            )
        )
        fill_count = int(
            manifest_fills.get(
                "count",
                metrics.get("total_fill_count", metrics.get("fill_count", 0)),
            )
            or 0
        )
        order_count = int(
            manifest_orders.get(
                "count",
                metrics.get("total_order_count", metrics.get("order_count", 0)),
            )
            or 0
        )
        baseline_fill_count = int(metrics.get("baseline_fill_count", fill_count) or 0)
        baseline_order_count = int(metrics.get("baseline_order_count", order_count) or 0)
        has_trade_metadata = all(
            value > 0
            for value in (fill_count, order_count, baseline_fill_count, baseline_order_count)
        )
        ledger_artifact_ok = self._evaluate_ledger_reconciliation_artifact(
            backtest_manifest=backtest_manifest,
            manifest_evidence=manifest_evidence,
            manifest_orders=manifest_orders,
            manifest_fills=manifest_fills,
            fill_count=fill_count,
            order_count=order_count,
            evidence=evidence,
            reasons=reasons,
        )

        evidence["engine"] = engine
        evidence["canonical_for_promotion"] = canonical_for_promotion
        evidence["ledger_consistency_pct"] = ledger_consistency_pct
        evidence["total_fill_count"] = fill_count
        evidence["total_order_count"] = order_count
        evidence["baseline_fill_count"] = baseline_fill_count
        evidence["baseline_order_count"] = baseline_order_count
        evidence["has_ledger_trade_metadata"] = has_trade_metadata

        if isinstance(backtest_manifest, dict):
            orders_have_risk = bool(
                manifest_orders.get("all_orders_have_risk_check_id", False)
            )
            fills_match_orders = bool(
                manifest_fills.get("all_fills_match_orders", False)
            )
            promotion_evidence_complete = bool(
                manifest_completeness.get("promotion_evidence_complete", False)
            )
            evidence["backtest_manifest_used_for_promotion"] = True
            evidence["orders_have_risk_check_id"] = orders_have_risk
            evidence["fills_match_orders"] = fills_match_orders
            evidence["promotion_evidence_complete"] = promotion_evidence_complete
            evidence["ledger_artifact_required"] = True
            evidence["ledger_artifact_ok"] = ledger_artifact_ok
        else:
            orders_have_risk = None
            fills_match_orders = None
            promotion_evidence_complete = None

        if engine != "event_driven":
            reasons.append("event_driven_required: promotion requires event_driven backtest evidence")
        if isinstance(backtest_manifest, dict) and not canonical_for_promotion:
            reasons.append(
                "canonical_backtest_manifest_required: backtest manifest must be canonical_for_promotion"
            )
        if ledger_consistency_pct < 100.0:
            reasons.append(
                f"ledger_consistency_failed: ledger_consistency_pct={ledger_consistency_pct:.2f} "
                "(need 100.0)"
            )
        if not has_trade_metadata:
            reasons.append("missing_ledger_trade_metadata: fills and orders must be present")
        if isinstance(backtest_manifest, dict) and not promotion_evidence_complete:
            reasons.append(
                "promotion_evidence_incomplete: backtest manifest completeness.promotion_evidence_complete must be true"
            )
        if isinstance(backtest_manifest, dict) and not orders_have_risk:
            reasons.append(
                "missing_order_risk_metadata: manifest must prove all orders have risk check ids"
            )
        if isinstance(backtest_manifest, dict) and not fills_match_orders:
            reasons.append(
                "missing_fill_order_linkage: manifest must prove all fills map to orders"
            )
        if isinstance(backtest_manifest, dict) and not ledger_artifact_ok:
            reasons.append(
                "ledger_reconciliation_artifact_invalid: promotion requires consistent ledger reconciliation artifact evidence"
            )

    def _evaluate_ledger_reconciliation_artifact(
        self,
        *,
        backtest_manifest: dict[str, Any] | None,
        manifest_evidence: dict[str, Any],
        manifest_orders: dict[str, Any],
        manifest_fills: dict[str, Any],
        fill_count: int,
        order_count: int,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> bool:
        if not isinstance(backtest_manifest, dict):
            evidence["ledger_artifact_present"] = False
            return False

        raw_artifact = manifest_evidence.get("ledger_artifact")
        if not isinstance(raw_artifact, dict):
            raw_artifact = backtest_manifest.get("ledger_artifact")
        artifact = raw_artifact if isinstance(raw_artifact, dict) else {}

        artifact_hash = str(artifact.get("artifact_hash", "") or "")
        generated_at = str(artifact.get("generated_at", "") or "")
        as_of_utc = str(artifact.get("as_of_utc", "") or "")
        hashes = artifact.get("hashes", {})
        if not isinstance(hashes, dict):
            hashes = {}
        artifact_fills_hash = str(hashes.get("fills_hash", "") or "")
        artifact_ledger_hash = str(hashes.get("ledger_hash", "") or "")
        artifact_orders_hash = str(hashes.get("orders_hash", "") or "")
        artifact_snapshots_hash = str(hashes.get("portfolio_snapshots_hash", "") or "")

        evidence["ledger_artifact_present"] = bool(artifact)
        evidence["ledger_artifact_hash"] = artifact_hash
        evidence["ledger_artifact_generated_at"] = generated_at
        evidence["ledger_artifact_as_of_utc"] = as_of_utc
        evidence["ledger_hash"] = artifact_ledger_hash
        evidence["fills_hash"] = artifact_fills_hash
        evidence["orders_hash"] = artifact_orders_hash
        evidence["portfolio_snapshots_hash"] = artifact_snapshots_hash

        if not artifact:
            reasons.append(
                "missing_ledger_reconciliation_artifact: promotion requires ledger reconciliation artifact evidence"
            )
            return False

        required_bindings = {
            "artifact_hash": str(
                backtest_manifest.get("ledger_artifact_hash")
                or manifest_evidence.get("ledger_artifact_hash")
                or ""
            ),
            "ledger_hash": str(
                backtest_manifest.get("ledger_hash")
                or manifest_evidence.get("ledger_hash")
                or ""
            ),
            "fills_hash": str(
                backtest_manifest.get("fills_hash")
                or manifest_evidence.get("fills_hash")
                or manifest_fills.get("fills_hash")
                or ""
            ),
        }
        manifest_reconciliation = manifest_evidence.get("reconciliation", {})
        if not isinstance(manifest_reconciliation, dict):
            manifest_reconciliation = {}
        manifest_summary = manifest_reconciliation.get("summary", {})
        if not isinstance(manifest_summary, dict) or not manifest_summary:
            top_level_summary = backtest_manifest.get("reconciliation", {})
            manifest_summary = dict(top_level_summary) if isinstance(top_level_summary, dict) else {}

        artifact_reconciliation = artifact.get("reconciliation", {})
        if not isinstance(artifact_reconciliation, dict):
            artifact_reconciliation = {}
        artifact_summary = artifact_reconciliation.get("summary", {})
        if not isinstance(artifact_summary, dict):
            artifact_summary = {}

        artifact_orders = artifact.get("orders", {})
        if not isinstance(artifact_orders, dict):
            artifact_orders = {}
        artifact_fills = artifact.get("fills", {})
        if not isinstance(artifact_fills, dict):
            artifact_fills = {}
        artifact_pnl = artifact.get("pnl", {})
        if not isinstance(artifact_pnl, dict):
            artifact_pnl = {}
        manifest_pnl = manifest_evidence.get("pnl", {})
        if not isinstance(manifest_pnl, dict):
            manifest_pnl = {}
        artifact_integrity = artifact.get("integrity", {})
        if not isinstance(artifact_integrity, dict):
            artifact_integrity = {}

        expected_hash = compute_ledger_reconciliation_artifact_hash(artifact)
        bindings_present = all(required_bindings.values())
        bindings_match = (
            required_bindings["artifact_hash"] == artifact_hash
            and required_bindings["ledger_hash"] == artifact_ledger_hash
            and required_bindings["fills_hash"] == artifact_fills_hash
        )
        summary_present = bool(artifact_summary) and bool(manifest_summary)
        summary_match = summary_present and artifact_summary == manifest_summary
        count_match = (
            int(artifact_orders.get("total_orders", -1) or -1) == order_count
            and int(artifact_fills.get("effective_fill_count", -1) or -1) == fill_count
        )
        manifest_pnl_value = manifest_pnl.get(
            "net_pnl",
            manifest_pnl.get("final_pnl"),
        )
        pnl_match = (
            bool(manifest_pnl)
            and str(artifact_pnl.get("source", "")) == "ledger_fills"
            and str(manifest_pnl.get("source", "")) == "ledger_fills"
            and self._numbers_close(
                artifact_pnl.get("final_equity"),
                manifest_pnl.get("final_equity"),
            )
            and self._numbers_close(artifact_pnl.get("net_pnl"), manifest_pnl_value)
        )
        hashes_present = all(
            [
                artifact_hash,
                generated_at,
                as_of_utc,
                artifact_fills_hash,
                artifact_ledger_hash,
                artifact_orders_hash,
                artifact_snapshots_hash,
            ]
        )
        integrity_passed = bool(artifact_integrity.get("passed", False))

        if not hashes_present:
            reasons.append(
                "ledger_reconciliation_artifact_fields_missing: artifact must include artifact_hash, generated_at, as_of_utc, ledger_hash, fills_hash, orders_hash, portfolio_snapshots_hash"
            )
        if artifact_hash != expected_hash:
            reasons.append(
                "ledger_reconciliation_artifact_hash_mismatch: artifact_hash does not match artifact payload"
            )
        if not bindings_present:
            reasons.append(
                "ledger_reconciliation_artifact_binding_missing: manifest must bind ledger_artifact_hash, ledger_hash, and fills_hash"
            )
        elif not bindings_match:
            reasons.append(
                "ledger_reconciliation_artifact_binding_mismatch: manifest hash bindings do not match artifact hashes"
            )
        if not summary_present:
            reasons.append(
                "ledger_reconciliation_summary_missing: manifest and artifact must both include reconciliation summary"
            )
        elif not summary_match:
            reasons.append(
                "ledger_reconciliation_summary_mismatch: artifact reconciliation summary differs from manifest reconciliation summary"
            )
        if not count_match:
            reasons.append(
                "ledger_reconciliation_trade_count_mismatch: artifact counts differ from manifest order/fill counts"
            )
        if not pnl_match:
            reasons.append(
                "ledger_reconciliation_pnl_mismatch: artifact PnL must match manifest ledger-backed PnL"
            )
        if not integrity_passed:
            reasons.append(
                "ledger_reconciliation_integrity_failed: artifact integrity.passed must be true"
            )

        return (
            hashes_present
            and artifact_hash == expected_hash
            and bindings_present
            and bindings_match
            and summary_present
            and summary_match
            and count_match
            and pnl_match
            and integrity_passed
        )

    def _record_unified_backtest_report_evidence(
        self,
        *,
        backtest_manifest: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> None:
        manifest_evidence = (
            backtest_manifest.get("evidence", {}) if isinstance(backtest_manifest, dict) else {}
        )
        if not isinstance(manifest_evidence, dict):
            manifest_evidence = {}

        reconciliation = manifest_evidence.get("reconciliation", {})
        if not isinstance(reconciliation, dict):
            reconciliation = {}
        reconciliation_summary = reconciliation.get("summary", {})
        if not isinstance(reconciliation_summary, dict):
            reconciliation_summary = {}
        reconciliation_snapshots = reconciliation.get("snapshots", [])
        if not isinstance(reconciliation_snapshots, list):
            reconciliation_snapshots = []
        adjustment_cross_check = reconciliation.get("adjustment_cross_check", {})
        if adjustment_cross_check is not None and not isinstance(adjustment_cross_check, dict):
            adjustment_cross_check = {}

        if not reconciliation_summary and isinstance(backtest_manifest, dict):
            top_level_summary = backtest_manifest.get("reconciliation", {})
            if isinstance(top_level_summary, dict):
                reconciliation_summary = dict(top_level_summary)

        has_reconciliation_evidence = bool(reconciliation_summary) or bool(reconciliation_snapshots)
        if not has_reconciliation_evidence:
            reconciliation_summary = {
                "snapshot_count": 0,
                "tolerance_pct": 0.0,
                "absolute_tolerance": 0.0,
                "max_abs_diff": 0.0,
                "max_pct_diff": 0.0,
                "passed": None,
                "message": "reconciliation evidence unavailable",
            }

        summary_passed_raw = reconciliation_summary.get("passed")
        summary_passed = (
            self._evidence_bool(summary_passed_raw)
            if summary_passed_raw is not None
            else None
        )
        failed_snapshots = [
            snapshot for snapshot in reconciliation_snapshots
            if not self._evidence_bool(snapshot.get("passed", False))
        ]

        evidence["reconciliation"] = {
            "summary": reconciliation_summary,
            "snapshots": reconciliation_snapshots,
            "adjustment_cross_check": adjustment_cross_check,
        }
        evidence["reconciliation_summary"] = reconciliation_summary
        evidence["reconciliation_passed"] = summary_passed
        evidence["reconciliation_max_abs_diff"] = float(
            reconciliation_summary.get("max_abs_diff", 0.0) or 0.0
        )
        evidence["reconciliation_max_pct_diff"] = float(
            reconciliation_summary.get("max_pct_diff", 0.0) or 0.0
        )
        evidence["reconciliation_failed_snapshot_count"] = len(failed_snapshots)
        evidence["reconciliation_failed_snapshot_summary"] = (
            self._summarize_failed_reconciliation_snapshots(failed_snapshots)
        )
        if adjustment_cross_check:
            evidence["reconciliation_adjustment_cross_check"] = adjustment_cross_check
        evidence["corporate_actions"] = {
            "digest": self._resolve_corporate_actions_digest(backtest_manifest, manifest_evidence),
        }
        evidence["corporate_actions_digest"] = evidence["corporate_actions"]["digest"]

        if has_reconciliation_evidence and summary_passed is False:
            reasons.append(
                "reconciliation_failed: backtest reconciliation summary.passed is false"
            )

    def _resolve_corporate_actions_digest(
        self,
        backtest_manifest: dict[str, Any] | None,
        manifest_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        digest: dict[str, Any] = {}
        if isinstance(backtest_manifest, dict):
            top_level = backtest_manifest.get("corporate_actions", {})
            if isinstance(top_level, dict):
                digest = dict(top_level)
        if not digest:
            nested = manifest_evidence.get("corporate_actions", {})
            if isinstance(nested, dict):
                nested_digest = nested.get("digest", {})
                if isinstance(nested_digest, dict):
                    digest = dict(nested_digest)
        return digest

    @staticmethod
    def _summarize_failed_reconciliation_snapshots(
        snapshots: list[dict[str, Any]],
    ) -> str:
        if not snapshots:
            return "none"

        first = snapshots[0]
        timestamp = str(first.get("timestamp_utc", "unknown"))
        diff = first.get("diff", {})
        if not isinstance(diff, dict):
            diff = {}
        cash_diff = first.get("cash_diff", diff.get("cash", "unknown"))
        equity_diff = first.get("equity_diff", diff.get("equity", "unknown"))
        max_abs_diff = first.get("max_abs_diff", "unknown")
        max_pct_diff = first.get("max_pct_diff", "unknown")
        return (
            f"count={len(snapshots)}; first={timestamp}; "
            f"cash_diff={ResearchPromotionGate._format_summary_number(cash_diff)}; "
            f"equity_diff={ResearchPromotionGate._format_summary_number(equity_diff)}; "
            f"max_abs_diff={ResearchPromotionGate._format_summary_number(max_abs_diff)}; "
            f"max_pct_diff={ResearchPromotionGate._format_summary_number(max_pct_diff)}"
        )

    @staticmethod
    def _format_summary_number(value: Any) -> str:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _evidence_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "passed", "pass"}
        return bool(value)

    @staticmethod
    def _numbers_close(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
        if left is None or right is None:
            return False
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            return False

    def _evaluate_data_manifest(
        self,
        *,
        data_version: str,
        data_source: str,
        asset_class: str,
        symbols: list[str],
        embedded_manifest: DataManifest | None,
        evidence: dict[str, Any],
        reasons: list[str],
        warnings: list[str],
    ) -> None:
        store_manifest = DataManifestStore(self.data_root / "manifests").read(data_version)

        evidence["data_manifest_embedded"] = embedded_manifest is not None
        evidence["data_manifest_store_exists"] = store_manifest is not None
        evidence["data_manifest_exists"] = store_manifest is not None
        if store_manifest is None:
            reasons.append(
                "missing_data_manifest: governed data manifest not found for data_version"
            )
            return

        manifest = store_manifest
        validation = validate_manifest_for_promotion(manifest)
        evidence["data_manifest_id"] = manifest.manifest_id
        evidence["data_manifest_checksum"] = manifest.effective_checksum
        evidence["data_manifest_fingerprint"] = manifest.fingerprint
        evidence["data_manifest_source"] = "manifest_store"
        evidence["data_manifest_validation"] = {
            "ok": validation.ok,
            "reasons": validation.reasons,
            "warnings": validation.warnings,
            "metrics": validation.metrics,
        }

        if embedded_manifest is not None:
            evidence["data_manifest_embedded_id"] = embedded_manifest.manifest_id
            evidence["data_manifest_embedded_checksum"] = (
                embedded_manifest.effective_checksum
            )
            evidence["data_manifest_embedded_fingerprint"] = (
                embedded_manifest.fingerprint
            )
            self._compare_embedded_data_manifest(
                embedded=embedded_manifest,
                governed=manifest,
                reasons=reasons,
            )

        manifest_symbol = manifest.symbol.upper()
        if symbols and manifest_symbol not in symbols:
            reasons.append(
                f"data_manifest_symbol_mismatch: manifest={manifest_symbol} "
                f"candidate={symbols}"
            )
        if manifest.source.lower() != data_source:
            reasons.append(
                f"data_manifest_source_mismatch: manifest={manifest.source.lower()} "
                f"candidate={data_source}"
            )
        if manifest.asset_class.lower() != asset_class:
            reasons.append(
                f"data_manifest_asset_class_mismatch: manifest={manifest.asset_class.lower()} "
                f"candidate={asset_class}"
            )
        reasons.extend(f"data_manifest_invalid:{reason}" for reason in validation.reasons)
        warnings.extend(
            f"data_manifest_warning:{warning}"
            for warning in validation.warnings
            if warning not in DATA_MANIFEST_ADVISORY_WARNINGS
        )

    def _compare_embedded_data_manifest(
        self,
        *,
        embedded: DataManifest,
        governed: DataManifest,
        reasons: list[str],
    ) -> None:
        if embedded.data_version != governed.data_version:
            reasons.append(
                "data_manifest_version_mismatch: "
                f"embedded={embedded.data_version} governed={governed.data_version}"
            )
        if embedded.manifest_id != governed.manifest_id:
            reasons.append(
                "data_manifest_id_mismatch: "
                f"embedded={embedded.manifest_id} governed={governed.manifest_id}"
            )
        if embedded.effective_checksum != governed.effective_checksum:
            reasons.append(
                "data_manifest_checksum_mismatch: "
                f"embedded={embedded.effective_checksum} "
                f"governed={governed.effective_checksum}"
            )
        if embedded.fingerprint != governed.fingerprint:
            reasons.append(
                "data_manifest_fingerprint_mismatch: "
                f"embedded={embedded.fingerprint} governed={governed.fingerprint}"
            )

    def _embedded_data_manifest(
        self,
        backtest_manifest: dict[str, Any] | None,
    ) -> DataManifest | None:
        if not isinstance(backtest_manifest, dict):
            return None
        raw = backtest_manifest.get("data_manifest")
        if not isinstance(raw, dict):
            return None

        valid_fields = {item.name for item in fields(DataManifest)}
        payload = {
            key: value
            for key, value in raw.items()
            if key in valid_fields
        }
        required = {"data_version", "source", "symbol", "interval"}
        if not required.issubset(payload):
            return None
        return DataManifest(**payload)

    @staticmethod
    def _source_from_data_version(data_version: str) -> str:
        normalized = data_version.lower()
        for source in (*ALLOWED_DATA_SOURCES, "fixture"):
            if source in normalized:
                return source
        return ""

    @staticmethod
    def _asset_class(symbols: list[str]) -> str:
        if any(symbol.endswith(CRYPTO_SYMBOL_SUFFIXES) for symbol in symbols):
            return "crypto"
        return "equity"

    @staticmethod
    def _as_pct(value: Any) -> float:
        pct = float(value)
        if 0.0 <= pct <= 1.0:
            return pct * 100.0
        return pct
