from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from backend.app.core.exceptions import QuantStationError
from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.data_management import CryptoResampleSpec, MarketDataService
from backend.app.services.market_data import inspect_market_data_quality
from backend.app.services.research_gate import ResearchPromotionGateService
from quant_us.backtest.crypto_event import (
    default_crypto_cost_stress_scenarios,
    qualify_crypto_candidates,
    summarize_crypto_interval_validation,
)
from quant_us.research.validation import summarize_candidate_validation


DEFAULT_CRYPTO_TARGET_INTERVALS = ["5m", "15m", "1h", "4h", "1d"]
DEFAULT_CRYPTO_STRATEGIES = [
    "btc_low_turnover_trend",
    "trend_macd",
    "donchian_breakout",
    "reversion_rsi",
    "volatility_squeeze",
    "funding_sentiment",
    "macro_trend",
    "dynamic_grid",
    "time_window",
]


def _as_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class CryptoClosureService:
    """Orchestrate the BTC research closure path from data to promotion gate."""

    def __init__(
        self,
        *,
        research_service: ResearchBacktestService,
        promotion_gate_service: ResearchPromotionGateService,
        market_data_service: MarketDataService,
        quality_inspector: Callable[..., dict[str, Any]] = inspect_market_data_quality,
    ) -> None:
        self.research_service = research_service
        self.promotion_gate_service = promotion_gate_service
        self.market_data_service = market_data_service
        self.quality_inspector = quality_inspector

    def run(
        self,
        request: dict[str, Any],
        *,
        progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        base_request = self._base_request(request)
        symbol = str(base_request["symbol"]).upper()
        research_interval = str(base_request["interval"])
        target_intervals = self._target_intervals(request, research_interval)
        blockers: list[str] = []
        recommendations: list[str] = []

        self._progress(
            progress_callback,
            stage="data_integrity",
            message="checking BTC multi-timeframe data integrity",
            progress=8,
        )
        data_integrity = self._run_data_integrity(
            request=request,
            base_request=base_request,
            target_intervals=target_intervals,
        )
        data_integrity["audit"] = self._data_integrity_audit(data_integrity, research_interval)
        blockers.extend(data_integrity["blockers"])
        if data_integrity["status"] != "pass":
            self._progress(
                progress_callback,
                stage="blocked",
                message="BTC data integrity gate blocked closure",
                progress=100,
            )
            return self._blocked_result(
                base_request=base_request,
                target_intervals=target_intervals,
                data_integrity=data_integrity,
                blockers=blockers,
                recommendations=[
                    "先修复 BTC 多周期数据完整性；候选筛选和回测不会在数据失败时继续执行。",
                ],
            )

        self._progress(
            progress_callback,
            stage="candidate_screen",
            message="screening BTC strategy families",
            progress=28,
        )
        candidate_screen = self._screen_candidates(request=request, base_request=base_request)
        blockers.extend(candidate_screen["blockers"])
        preliminary_candidates = list(candidate_screen.get("candidates", []) or [])
        if not preliminary_candidates:
            self._progress(
                progress_callback,
                stage="blocked",
                message="BTC candidate screen produced no candidates",
                progress=100,
            )
            return self._blocked_result(
                base_request=base_request,
                target_intervals=target_intervals,
                data_integrity=data_integrity,
                candidate_screen=candidate_screen,
                blockers=blockers,
                recommendations=[
                    "没有可用策略候选；先缩小策略列表或检查候选参数网格。",
                ],
            )

        requested_scenarios = request.get("max_scenarios")
        scenario_count = (
            len(default_crypto_cost_stress_scenarios())
            if requested_scenarios in (None, "")
            else int(requested_scenarios)
        )
        validation_count = max(
            1,
            min(
                int(request.get("validation_candidate_count", request.get("max_validation_candidates", 3))),
                len(preliminary_candidates),
            ),
        )
        candidates_to_validate = preliminary_candidates[:validation_count]
        validated_candidates: list[dict[str, Any]] = []
        event_by_candidate: dict[str, dict[str, Any]] = {}
        cost_by_candidate: dict[str, dict[str, Any]] = {}
        walk_by_candidate: dict[str, dict[str, Any]] = {}
        selected_request_by_candidate: dict[str, dict[str, Any]] = {}

        for index, candidate in enumerate(candidates_to_validate, start=1):
            candidate_key = self._candidate_key(candidate)
            self._progress(
                progress_callback,
                stage="candidate_validation",
                message=f"strict-validating BTC candidate {index}/{validation_count}: {candidate_key}",
                progress=42 + int(42 * (index - 1) / max(1, validation_count)),
            )
            evaluated = self._evaluate_candidate(
                request=request,
                base_request=base_request,
                data_integrity=data_integrity,
                candidate=candidate,
                strategy_candidates=[
                    row for row in preliminary_candidates
                    if row.get("strategy_id") == candidate.get("strategy_id")
                ],
                scenario_count=scenario_count,
                symbol=symbol,
            )
            validated_candidates.append(evaluated["candidate"])
            key = self._candidate_key(evaluated["candidate"])
            selected_request_by_candidate[key] = evaluated["selected_request"]
            event_by_candidate[key] = evaluated["event_backtest"]
            cost_by_candidate[key] = evaluated["cost_stress"]
            walk_by_candidate[key] = evaluated["walk_forward"]
            blockers.extend(self._event_backtest_blockers(evaluated["event_backtest"]))

        qualification = qualify_crypto_candidates(
            validated_candidates,
            cost_stress_by_candidate=cost_by_candidate,
            walk_forward_by_candidate=walk_by_candidate,
            event_backtest_by_candidate=event_by_candidate,
            max_selected=max(1, min(int(request.get("max_selected_candidates", 3)), 3)),
        )
        qualification = self._apply_statistical_validation_gate(
            qualification,
            max_selected=max(1, min(int(request.get("max_selected_candidates", 3)), 3)),
        )
        candidate_screen["qualification"] = qualification
        candidate_screen["validated_candidate_count"] = len(validated_candidates)
        candidate_screen["validated_candidates"] = validated_candidates
        candidate_screen["candidates"] = qualification.get("candidates", validated_candidates)
        strict_selected_candidates = [
            dict(row)
            for row in qualification.get("selected_candidates", [])
        ]
        strict_selected = (
            strict_selected_candidates[0]
            if qualification.get("selected_candidates")
            else None
        )
        candidate_screen["selected_candidate"] = strict_selected
        candidate_screen["selected_candidates"] = strict_selected_candidates
        if not strict_selected:
            blockers.append("no BTC candidate passed cost stress, walk-forward, CPCV/DSR/PBO gates")
            blockers.extend(str(item) for item in qualification.get("blockers", []))

        representative = strict_selected or (validated_candidates[0] if validated_candidates else preliminary_candidates[0])
        representative_key = self._candidate_key(representative)
        selected_request = selected_request_by_candidate.get(representative_key, {})
        event_payload = event_by_candidate.get(representative_key, {})
        cost_stress = cost_by_candidate.get(representative_key, {})
        walk_forward = walk_by_candidate.get(representative_key, {})
        audit_context = dict(representative.get("audit", {}))
        candidate_screen["audit"] = audit_context
        closure_evidence_paths = [
            str((row.get("audit") or {}).get("candidate_evidence_path", ""))
            for row in validated_candidates
            if str((row.get("audit") or {}).get("candidate_evidence_path", "")).strip()
        ]
        self._progress(
            progress_callback,
            stage="promotion_gate",
            message="evaluating BTC closure promotion boundary",
            progress=90,
        )
        promotion_gate = {
            "status": "skipped",
            "decision": "fail",
            "next_stage": "blocked",
            "gates": [],
            "recommendations": [
                "No service-layer promotion gate was run because no BTC candidate passed strict cost, walk-forward, and CPCV/DSR/PBO validation."
            ],
        }
        if strict_selected and selected_request:
            promotion_gate = self.promotion_gate_service.evaluate(
                {
                    **selected_request,
                    "mode": "single",
                    "skip_deep_checks": False,
                    "persist_manifest": bool(request.get("persist_manifest", True)),
                    "register_experiment": bool(request.get("register_experiment", True)),
                    "experiment_name": str(request.get("experiment_name") or f"{symbol.lower()}_closure_gate"),
                    "notes": str(request.get("notes") or "Generated by BTC closure pipeline."),
                    "max_scenarios": min(max(1, scenario_count), len(default_crypto_cost_stress_scenarios())),
                    "windows": min(int(request.get("windows", 2)), 8),
                    "max_candidates": 1,
                    "symbols": [symbol],
                }
            )
        promotion_gate["closure_audit"] = {
            "data_version": audit_context.get("data_version", ""),
            "strategy_version": audit_context.get("strategy_version", ""),
            "run_id_prefix": audit_context.get("run_id_prefix", ""),
            "event_run_id": audit_context.get("event_run_id", ""),
            "selected_manifest_path": audit_context.get("data_manifest_path", ""),
            "candidate_key": representative_key,
        }

        if promotion_gate:
            blockers.extend(self._validation_blockers(cost_stress, walk_forward, promotion_gate))
        blockers = self._stable_unique_strings(blockers)
        gate_decision = str(promotion_gate.get("decision", "fail"))
        decision = "fail" if blockers else gate_decision
        next_stage = "blocked" if blockers else str(promotion_gate.get("next_stage", "blocked"))
        if blockers:
            recommendations.append("BTC 闭环已经跑完，但仍存在阻断项；保持 paper/live 关闭。")
        else:
            recommendations.append("BTC 闭环无显式阻断；下一步仍需人工复核 evidence pack 后再考虑 paper review。")
        recommendations.extend(promotion_gate.get("recommendations", []))
        recommendations = self._stable_unique_strings(recommendations)
        self._progress(
            progress_callback,
            stage="completed",
            message="BTC closure finished",
            progress=100,
        )

        return {
            "status": "completed",
            "selected_priority": "BTC 数据 -> 策略 -> 回测 -> 风控 -> gate 闭环",
            "symbol": symbol,
            "source": base_request["source"],
            "interval": research_interval,
            "target_intervals": target_intervals,
            "data_integrity": data_integrity,
            "candidate_screen": candidate_screen,
            "selected_candidate": strict_selected,
            "selected_candidates": strict_selected_candidates,
            "event_backtest": event_payload,
            "cost_stress": cost_stress,
            "walk_forward": walk_forward,
            "promotion_gate": promotion_gate,
            "closure_evidence_paths": closure_evidence_paths,
            "decision": decision,
            "next_stage": next_stage,
            "blockers": blockers,
            "recommendations": recommendations,
        }

    def _base_request(self, request: dict[str, Any]) -> dict[str, Any]:
        target_weight = min(0.98, max(0.0, float(request.get("target_weight", 0.85))))
        min_cash_buffer_pct = round(max(0.02, 1.0 - target_weight, float(request.get("min_cash_buffer_pct", 0.0))), 8)
        return {
            "source": "sqlite",
            "asset_class": "crypto",
            "symbol": str(request.get("symbol") or "BTCUSDT").upper(),
            "interval": str(request.get("interval") or "1h"),
            "start": _as_utc_datetime(request["start"]),
            "end": _as_utc_datetime(request["end"]),
            "capital": float(request.get("capital", 100_000.0)),
            "commission_rate": float(request.get("commission_rate", 0.0004)),
            "slippage": float(request.get("slippage", 4.0)),
            "leverage": min(1.0, float(request.get("leverage", 1.0))),
            "position_basis": str(request.get("position_basis", "equity")),
            "target_weight": target_weight,
            "min_cash_buffer_pct": min_cash_buffer_pct,
            "min_trade_notional": float(request.get("min_trade_notional", 25.0)),
            "rebalance_buffer_pct": float(request.get("rebalance_buffer_pct", 0.05)),
            "min_holding_bars": int(request.get("min_holding_bars", 24)),
            "cost_aware_filter": bool(request.get("cost_aware_filter", True)),
            "max_annual_turnover_pct": float(request.get("max_annual_turnover_pct", 1500.0)),
            "long_only": True,
            "data_db_path": str(request.get("data_db_path", "")),
        }

    def _target_intervals(self, request: dict[str, Any], research_interval: str) -> list[str]:
        requested = request.get("target_intervals") or DEFAULT_CRYPTO_TARGET_INTERVALS
        intervals: list[str] = []
        for interval in [*requested, research_interval]:
            text = str(interval)
            if text == "1m":
                continue
            if text not in intervals:
                intervals.append(text)
        return intervals

    def _run_data_integrity(
        self,
        *,
        request: dict[str, Any],
        base_request: dict[str, Any],
        target_intervals: list[str],
    ) -> dict[str, Any]:
        resample_results: list[dict[str, Any]] = []
        quality_results: list[dict[str, Any]] = []
        blockers: list[str] = []
        start = base_request["start"]
        end = base_request["end"]
        min_bars_by_interval = self._min_bars_by_interval(request)
        resample_end_by_interval: dict[str, Any] = {}

        for interval in target_intervals:
            try:
                result = self.market_data_service.resample_crypto_klines(
                    CryptoResampleSpec(
                        exchange="binance_spot",
                        symbol=str(base_request["symbol"]),
                        source_interval="1m",
                        target_interval=interval,
                        start=start,
                        end=end,
                        db_path=str(base_request.get("data_db_path", "")),
                        persist_manifest=bool(request.get("persist_data_manifest", True)),
                    )
                )
                payload = asdict(result)
                resample_results.append(payload)
                if payload.get("end") is not None:
                    resample_end_by_interval[interval] = payload["end"]
                if float(payload.get("coverage_pct", 0.0)) < 99.0:
                    blockers.append(f"{interval} resample coverage {payload.get('coverage_pct')}% < 99%")
                if float(payload.get("quality_score", 0.0)) < 95.0:
                    blockers.append(f"{interval} resample quality_score {payload.get('quality_score')} < 95")
            except Exception as exc:
                resample_results.append({"target_interval": interval, "status": "failed", "error": str(exc)})
                blockers.append(f"{interval} resample failed: {exc}")

        for interval in ["1m", *target_intervals]:
            try:
                quality_end = _as_utc_datetime(resample_end_by_interval.get(interval, end))
                quality = self.quality_inspector(
                    source="sqlite",
                    symbol=str(base_request["symbol"]),
                    interval=interval,
                    start=start,
                    end=quality_end,
                    db_path=str(base_request.get("data_db_path", "")),
                )
                quality_results.append(quality)
                if not bool(quality.get("is_usable", False)):
                    blockers.append(f"{interval} data quality unusable")
                if float(quality.get("coverage_pct", 0.0)) < 95.0:
                    blockers.append(f"{interval} coverage {quality.get('coverage_pct')}% < 95%")
                if int(quality.get("missing_bars", 0)) > 0:
                    blockers.append(f"{interval} missing bars: {quality.get('missing_bars')}")
            except Exception as exc:
                quality_results.append({"interval": interval, "status": "failed", "error": str(exc)})
                blockers.append(f"{interval} quality failed: {exc}")

        validation_summary = summarize_crypto_interval_validation(
            target_intervals=target_intervals,
            quality_results=quality_results,
            resample_results=resample_results,
            coverage_floor_pct=float(request.get("coverage_floor_pct", 99.0)),
            quality_score_floor=float(request.get("quality_score_floor", 95.0)),
            min_bars_by_interval=min_bars_by_interval,
        )
        blockers.extend(str(item) for item in validation_summary.get("blockers", []))

        return {
            "status": "pass" if not blockers else "fail",
            "source_interval": "1m",
            "target_intervals": target_intervals,
            "resample_results": resample_results,
            "quality_results": quality_results,
            "validation_summary": validation_summary,
            "long_sample": {
                "status": validation_summary.get("status"),
                "intervals": validation_summary.get("intervals", []),
                "min_bars_by_interval": min_bars_by_interval,
            },
            "blockers": blockers,
        }

    def _screen_candidates(self, *, request: dict[str, Any], base_request: dict[str, Any]) -> dict[str, Any]:
        strategy_ids = [str(item) for item in (request.get("strategy_ids") or DEFAULT_CRYPTO_STRATEGIES)]
        max_candidates = max(1, min(int(request.get("max_candidates_per_strategy", 4)), 12))
        candidates: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        blockers: list[str] = []

        for strategy_id in strategy_ids:
            try:
                result = self.research_service.optimize_strategy(
                    {
                        **base_request,
                        "strategy_id": strategy_id,
                        "max_candidates": max_candidates,
                    }
                )
                best = result.get("best")
                if str(result.get("status", "completed")) != "completed" or not isinstance(best, dict) or not best:
                    errors.append({"strategy_id": strategy_id, "error": "optimizer returned no best candidate"})
                    continue
                optimizer_rows = result.get("candidates", [])
                if not isinstance(optimizer_rows, list) or not optimizer_rows:
                    optimizer_rows = [best]
                appended_before = len(candidates)
                for optimizer_row in optimizer_rows[:max_candidates]:
                    if not isinstance(optimizer_row, dict):
                        continue
                    validation = optimizer_row.get("validation")
                    if not isinstance(validation, dict) or not validation:
                        errors.append({"strategy_id": strategy_id, "error": "optimizer candidate missing validation"})
                        continue
                    candidates.append(
                        {
                            "strategy_id": strategy_id,
                            "parameters": dict(optimizer_row.get("parameters") or {}),
                            "score": float(optimizer_row.get("score", 0.0)),
                            "validation": validation,
                            "train": optimizer_row.get("train") or {},
                            "overfit_gap": float(optimizer_row.get("overfit_gap", 0.0)),
                            "candidate_count": len(result.get("candidates", [])),
                            "optimizer_rank": optimizer_row.get("rank"),
                            "metrics": dict(optimizer_row.get("metrics") or {}),
                            "turnover": dict(optimizer_row.get("turnover") or {}),
                            "holding_period": dict(optimizer_row.get("holding_period") or {}),
                            "research_metadata": dict(optimizer_row.get("research_metadata") or {}),
                            "recommendations": result.get("recommendations", []),
                        }
                    )
                if len(candidates) == appended_before:
                    validation = best.get("validation")
                    if not isinstance(validation, dict) or not validation:
                        errors.append({"strategy_id": strategy_id, "error": "optimizer best candidate missing validation"})
                        continue
                    candidates.append(
                        {
                            "strategy_id": strategy_id,
                            "parameters": dict(best.get("parameters") or {}),
                            "score": float(best.get("score", 0.0)),
                            "validation": validation,
                            "train": best.get("train") or {},
                            "overfit_gap": float(best.get("overfit_gap", 0.0)),
                            "candidate_count": len(result.get("candidates", [])),
                            "optimizer_rank": best.get("rank"),
                            "metrics": dict(best.get("metrics") or {}),
                            "turnover": dict(best.get("turnover") or {}),
                            "holding_period": dict(best.get("holding_period") or {}),
                            "research_metadata": dict(best.get("research_metadata") or {}),
                            "recommendations": result.get("recommendations", []),
                        }
                    )
            except Exception as exc:
                errors.append({"strategy_id": strategy_id, "error": str(exc)})

        candidates.sort(key=self._candidate_sort_key, reverse=True)
        for rank, candidate in enumerate(candidates, start=1):
            candidate["rank"] = rank

        if not candidates:
            blockers.append("candidate_screen produced no candidates")
        return {
            "status": "completed" if candidates else "blocked",
            "strategy_ids": strategy_ids,
            "candidate_count": len(candidates),
            "candidates": candidates[: max(1, min(int(request.get("max_ranked_candidates", 8)), 20))],
            "selected_candidate": candidates[0] if candidates else None,
            "errors": errors,
            "blockers": blockers,
        }

    def _candidate_sort_key(self, candidate: dict[str, Any]) -> tuple[float, float, float]:
        validation = candidate.get("validation") or {}
        score = float(candidate.get("score", 0.0))
        sharpe = float(validation.get("sharpe_ratio", 0.0))
        drawdown = float(validation.get("max_drawdown_pct", 0.0))
        return score, sharpe, drawdown

    def _candidate_key(self, candidate: dict[str, Any]) -> str:
        strategy_id = str(candidate.get("strategy_id", "unknown"))
        params = candidate.get("parameters") or candidate.get("params") or {}
        if not isinstance(params, dict) or not params:
            return strategy_id
        parts = ",".join(f"{key}={params[key]}" for key in sorted(params))
        return f"{strategy_id}|{parts}"

    def _evaluate_candidate(
        self,
        *,
        request: dict[str, Any],
        base_request: dict[str, Any],
        data_integrity: dict[str, Any],
        candidate: dict[str, Any],
        strategy_candidates: list[dict[str, Any]],
        scenario_count: int,
        symbol: str,
    ) -> dict[str, Any]:
        candidate = dict(candidate)
        audit_context = self._build_audit_context(
            request=request,
            base_request=base_request,
            data_integrity=data_integrity,
            candidate=candidate,
        )
        selected_request = {
            **base_request,
            "strategy_id": candidate["strategy_id"],
            "strategy_params": dict(candidate.get("parameters") or {}),
            "data_version": audit_context["data_version"],
            "strategy_version": audit_context["strategy_version"],
            "manifest_root": audit_context["manifest_root"],
            "run_id": audit_context["event_run_id"],
            "run_id_prefix": audit_context["run_id_prefix"],
            "data_root": audit_context["data_root"],
        }
        event_backtest = self.research_service.run_crypto_event(selected_request)
        event_payload = {
            "status": "completed",
            "mode": event_backtest.mode,
            "summary": event_backtest.summary,
            "strategy_details": event_backtest.strategy_details,
            "latest_weights": event_backtest.latest_weights,
            "diagnostics": event_backtest.diagnostics,
            "audit": {
                "run_id": event_backtest.diagnostics.get("run_id", audit_context["event_run_id"]),
                "manifest_id": event_backtest.diagnostics.get("manifest_id", ""),
                "manifest_path": event_backtest.diagnostics.get("manifest_path", ""),
                "ledger_artifact_path": event_backtest.diagnostics.get("ledger_artifact_path", ""),
                "data_version": event_backtest.diagnostics.get("data_version", audit_context["data_version"]),
                "strategy_version": event_backtest.diagnostics.get("strategy_version", audit_context["strategy_version"]),
            },
        }
        max_scenarios = min(max(1, scenario_count), len(default_crypto_cost_stress_scenarios()))
        cost_stress = self.research_service.run_event_driven_cost_stress(
            {
                **selected_request,
                "max_scenarios": max_scenarios,
            }
        )
        walk_forward = self.research_service.run_walk_forward(
            {
                **selected_request,
                "windows": min(int(request.get("windows", 4)), 8),
                "max_candidates": 1,
                "symbols": [symbol],
            }
        )
        cpcv = self.research_service.run_cpcv_validation(
            {
                **selected_request,
                "candidate_params": [
                    dict(row.get("parameters") or {})
                    for row in strategy_candidates
                    if row.get("strategy_id") == candidate.get("strategy_id")
                ],
                "cpcv_splits": int(request.get("cpcv_splits", 5)),
                "cpcv_test_splits": int(request.get("cpcv_test_splits", 2)),
                "cpcv_max_paths": int(request.get("cpcv_max_paths", 10)),
                "cpcv_max_configs": int(request.get("cpcv_max_configs", 6)),
                "purge_bars": int(request.get("purge_bars", 1)),
                "embargo_bars": int(request.get("embargo_bars", 1)),
            }
        )
        cost_stress["audit"] = {
            "data_version": cost_stress.get("data_version", audit_context["data_version"]),
            "strategy_version": cost_stress.get("strategy_version", audit_context["strategy_version"]),
            "run_id_prefix": cost_stress.get("run_id_prefix", audit_context["run_id_prefix"]),
            "scenario_manifests_complete": bool(cost_stress.get("scenario_manifests_complete", False)),
            "missing_manifest_scenarios": cost_stress.get("missing_manifest_scenarios", []),
        }
        walk_forward["audit"] = {
            **dict(walk_forward.get("audit", {})),
            "data_version": walk_forward.get("audit", {}).get("data_version", audit_context["data_version"]),
            "strategy_version": walk_forward.get("audit", {}).get("strategy_version", audit_context["strategy_version"]),
            "run_id_prefix": walk_forward.get("audit", {}).get("run_id_prefix", audit_context["run_id_prefix"]),
        }
        metrics = {
            **dict(candidate.get("validation", {}) or {}),
            "bar_count": int(cpcv.get("bar_count", 0) or 0),
            "return_observation_count": int(cpcv.get("return_observation_count", 0) or 0),
            "validation_method": "cpcv",
            "cv_method": "cpcv",
            "purged": True,
            "purge_bars": int(cpcv.get("purge_bars", 1) or 1),
            "embargoed": True,
            "embargo_bars": int(cpcv.get("embargo_bars", 1) or 1),
            "n_splits": int(cpcv.get("n_splits", 0) or 0),
            "test_splits": int(cpcv.get("test_splits", 0) or 0),
            "combination_count": int(cpcv.get("combination_count", 0) or 0),
            "trial_count": int(cpcv.get("trial_count", 0) or 0),
            "independent_trial_count": int(cpcv.get("trial_count", 0) or 0),
            "lookahead_guard": str(cpcv.get("lookahead_guard", "")),
            "wf_fold_sharpes": list(cpcv.get("fold_sharpes", []) or []),
            "wf_fold_drawdowns": list(cpcv.get("fold_drawdowns", []) or []),
            "pbo_trials": list(cpcv.get("pbo_trials", []) or []),
            "return_series": list(cpcv.get("fold_returns", []) or []),
            "cost_stress_levels": self._cost_stress_levels(cost_stress),
        }
        validation_statistics = summarize_candidate_validation(
            candidate_id=self._candidate_key(candidate),
            metrics=metrics,
            walk_forward_artifact=cpcv,
            cost_stress_artifact={"levels": metrics["cost_stress_levels"]},
            experiment_data={
                "validation_method": "cpcv",
                "lookahead_guard": str(cpcv.get("lookahead_guard", "")),
                "param_grid": {"candidate_configs": list(range(max(1, int(cpcv.get("config_count", 0) or 0))))},
            },
        )
        candidate["audit"] = audit_context
        candidate["event_backtest_summary"] = event_payload.get("summary", {})
        candidate["cost_stress_summary"] = {
            "survival_rate_pct": cost_stress.get("survival_rate_pct", 0.0),
            "ledger_consistency_pct": cost_stress.get("ledger_consistency_pct", 0.0),
            "scenario_count": cost_stress.get("scenario_count", 0),
        }
        candidate["walk_forward_summary"] = walk_forward.get("stability", {})
        candidate["cpcv_summary"] = {
            "status": cpcv.get("status"),
            "path_count": cpcv.get("path_count", 0),
            "trial_count": cpcv.get("trial_count", 0),
            "fold_sharpes": cpcv.get("fold_sharpes", []),
        }
        candidate["validation_statistics"] = validation_statistics
        candidate["statistical_validation_blockers"] = self._statistical_validation_blockers(candidate)
        candidate["audit"]["candidate_evidence_path"] = self._persist_candidate_evidence(
            request=request,
            audit_context=audit_context,
            candidate=candidate,
            selected_request=selected_request,
            event_backtest=event_payload,
            cost_stress=cost_stress,
            walk_forward=walk_forward,
            cpcv=cpcv,
        )
        return {
            "candidate": candidate,
            "selected_request": selected_request,
            "event_backtest": event_payload,
            "cost_stress": cost_stress,
            "walk_forward": walk_forward,
            "cpcv": cpcv,
        }

    def _apply_statistical_validation_gate(
        self,
        qualification: dict[str, Any],
        *,
        max_selected: int,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for raw_row in qualification.get("candidates", []) or []:
            row = dict(raw_row)
            blockers = list(row.get("qualification_blockers", []) or [])
            blockers.extend(self._statistical_validation_blockers(row))
            row["qualification_blockers"] = self._stable_unique_strings(blockers)
            row["qualified"] = not row["qualification_blockers"]
            row["selected"] = False
            rows.append(row)
        selected_remaining = max(0, int(max_selected))
        for row in rows:
            if selected_remaining <= 0:
                break
            if row["qualified"]:
                row["selected"] = True
                selected_remaining -= 1
        return {
            **qualification,
            "qualified_count": sum(1 for row in rows if row["qualified"]),
            "selected_count": sum(1 for row in rows if row["selected"]),
            "candidates": rows,
            "selected_candidates": [row for row in rows if row["selected"]],
            "blockers": [
                f"{row['candidate_key']}: {blocker}"
                for row in rows
                for blocker in row.get("qualification_blockers", [])
            ],
        }

    def _statistical_validation_blockers(self, candidate: dict[str, Any]) -> list[str]:
        stats = candidate.get("validation_statistics") or {}
        if not isinstance(stats, dict) or not stats:
            return ["missing CPCV/DSR/PBO validation statistics"]
        contract = stats.get("promotion_gate_contract") or {}
        blockers: list[str] = []
        if contract.get("status") != "passed":
            blockers.append("CPCV/DSR/PBO promotion contract blocked")
        dsr = (stats.get("deflated_sharpe_ratio") or {}).get("dsr")
        if dsr is None or float(dsr) < 0.10:
            blockers.append("DSR below promotion threshold")
        pbo = (stats.get("pbo") or {}).get("pbo")
        if pbo is None or float(pbo) > 0.50:
            blockers.append("PBO above promotion threshold or missing")
        multiple = stats.get("multiple_testing") or {}
        if multiple.get("passed") is not True:
            blockers.append("multiple testing control did not pass")
        return self._stable_unique_strings(blockers)

    def _cost_stress_levels(self, cost_stress: dict[str, Any]) -> list[dict[str, Any]]:
        levels: list[dict[str, Any]] = []
        for scenario in cost_stress.get("scenarios", []) or []:
            if not isinstance(scenario, dict):
                continue
            summary = scenario.get("summary", {}) if isinstance(scenario.get("summary"), dict) else {}
            levels.append(
                {
                    "name": scenario.get("name", ""),
                    "cost_multiplier": max(
                        float(scenario.get("commission_multiplier", 1.0) or 1.0),
                        float(scenario.get("slippage_multiplier", 1.0) or 1.0),
                    ),
                    "total_return_pct": summary.get("total_return_pct", 0.0),
                    "sharpe_ratio": summary.get("sharpe_ratio", 0.0),
                    "max_drawdown_pct": summary.get("max_drawdown_pct", 0.0),
                    "survives": bool(scenario.get("survives", False)),
                }
            )
        return levels

    def _persist_candidate_evidence(
        self,
        *,
        request: dict[str, Any],
        audit_context: dict[str, str],
        candidate: dict[str, Any],
        selected_request: dict[str, Any],
        event_backtest: dict[str, Any],
        cost_stress: dict[str, Any],
        walk_forward: dict[str, Any],
        cpcv: dict[str, Any],
    ) -> str:
        if request.get("persist_closure_evidence") is False:
            return ""
        data_root = Path(audit_context.get("data_root") or request.get("data_root", "data"))
        output_dir = data_root / "research" / "btc_closure_runs"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{audit_context['run_id_prefix']}_strict_evidence.json"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "btc_closure_candidate_strict_validation",
            "status": "research_only",
            "live_enabled": False,
            "candidate_key": self._candidate_key(candidate),
            "candidate": candidate,
            "selected_request": {
                key: str(value) if isinstance(value, datetime) else value
                for key, value in selected_request.items()
                if key not in {"chart"}
            },
            "event_backtest": {
                "summary": event_backtest.get("summary", {}),
                "diagnostics": event_backtest.get("diagnostics", {}),
                "audit": event_backtest.get("audit", {}),
            },
            "cost_stress": self._compact_cost_stress(cost_stress),
            "walk_forward": self._compact_walk_forward(walk_forward),
            "cpcv": self._compact_cpcv(cpcv),
            "validation_statistics": candidate.get("validation_statistics", {}),
            "statistical_validation_blockers": candidate.get("statistical_validation_blockers", []),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return str(path)

    def _compact_cost_stress(self, cost_stress: dict[str, Any]) -> dict[str, Any]:
        return {
            "engine": cost_stress.get("engine", ""),
            "survival_rate_pct": cost_stress.get("survival_rate_pct", 0.0),
            "ledger_consistency_pct": cost_stress.get("ledger_consistency_pct", 0.0),
            "scenario_count": cost_stress.get("scenario_count", 0),
            "scenario_manifests_complete": bool(cost_stress.get("scenario_manifests_complete", False)),
            "missing_manifest_scenarios": cost_stress.get("missing_manifest_scenarios", []),
            "scenarios": [
                {
                    "name": row.get("name", ""),
                    "survives": bool(row.get("survives", False)),
                    "commission_multiplier": row.get("commission_multiplier", 1.0),
                    "slippage_multiplier": row.get("slippage_multiplier", 1.0),
                    "summary": row.get("summary", {}),
                }
                for row in cost_stress.get("scenarios", []) or []
                if isinstance(row, dict)
            ],
            "audit": cost_stress.get("audit", {}),
        }

    def _compact_walk_forward(self, walk_forward: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": walk_forward.get("status", ""),
            "stability": walk_forward.get("stability", {}),
            "audit": walk_forward.get("audit", {}),
            "recommendations": walk_forward.get("recommendations", []),
        }

    def _compact_cpcv(self, cpcv: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": cpcv.get("status", ""),
            "validation_method": cpcv.get("validation_method", "cpcv"),
            "cv_method": cpcv.get("cv_method", "cpcv"),
            "n_splits": cpcv.get("n_splits", 0),
            "test_splits": cpcv.get("test_splits", 0),
            "path_count": cpcv.get("path_count", 0),
            "trial_count": cpcv.get("trial_count", 0),
            "purged": bool(cpcv.get("purged", False)),
            "embargoed": bool(cpcv.get("embargoed", False)),
            "lookahead_guard": cpcv.get("lookahead_guard", ""),
            "fold_sharpes": cpcv.get("fold_sharpes", []),
            "fold_drawdowns": cpcv.get("fold_drawdowns", []),
            "pbo_trials": cpcv.get("pbo_trials", []),
        }

    def _min_bars_by_interval(self, request: dict[str, Any]) -> dict[str, int] | None:
        raw = request.get("min_bars_by_interval") or request.get("long_sample_min_bars_by_interval")
        if not isinstance(raw, dict):
            return None
        result: dict[str, int] = {}
        for interval, value in raw.items():
            try:
                result[str(interval)] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        return result or None

    def _event_backtest_blockers(self, event_backtest: dict[str, Any]) -> list[str]:
        diagnostics = event_backtest.get("diagnostics") or {}
        blockers: list[str] = []
        if str(event_backtest.get("mode", "")) != "crypto_event":
            blockers.append(f"event_backtest mode={event_backtest.get('mode')} is not crypto_event")
        if str(diagnostics.get("engine", "")) != "event_driven":
            blockers.append("event_backtest engine is not event_driven")
        if str(diagnostics.get("pnl_source", "")) != "ledger_fills":
            blockers.append("event_backtest PnL is not ledger_fills")
        if diagnostics.get("ledger_equity_consistent") is not True:
            blockers.append(f"event_backtest ledger inconsistent: {diagnostics.get('ledger_consistency_msg', '')}")
        if not str(diagnostics.get("manifest_path", "")).strip():
            blockers.append("event_backtest manifest_path is missing")
        return blockers

    def _validation_blockers(
        self,
        cost_stress: dict[str, Any],
        walk_forward: dict[str, Any],
        promotion_gate: dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        if str(cost_stress.get("engine", "")) != "event_driven":
            blockers.append("cost_stress engine is not event_driven")
        if float(cost_stress.get("survival_rate_pct", 0.0)) < 60.0:
            blockers.append(f"cost_stress survival_rate {cost_stress.get('survival_rate_pct')}% < 60%")
        if float(cost_stress.get("ledger_consistency_pct", 0.0)) < 100.0:
            blockers.append(f"cost_stress ledger consistency {cost_stress.get('ledger_consistency_pct')}% < 100%")
        if not bool(cost_stress.get("scenario_manifests_complete", False)):
            blockers.append(
                f"cost_stress missing manifests: {', '.join(cost_stress.get('missing_manifest_scenarios', []))}"
            )
        baseline_execution = cost_stress.get("baseline", {}).get("execution", {})
        if baseline_execution and str(baseline_execution.get("pnl_source", "")) != "ledger_fills":
            blockers.append("cost_stress baseline PnL is not ledger_fills")

        stability = walk_forward.get("stability", {})
        if float(stability.get("fold_pass_rate_pct") or stability.get("pass_rate_pct", 0.0)) < 60.0:
            blockers.append(f"walk_forward pass_rate {stability.get('fold_pass_rate_pct', stability.get('pass_rate_pct', 0.0))}% < 60%")
        if float(stability.get("ledger_consistency_pct", 0.0)) < 100.0:
            blockers.append(f"walk_forward ledger consistency {stability.get('ledger_consistency_pct')}% < 100%")
        aggregate_manifest_path = str(
            (walk_forward.get("audit") or {}).get("aggregate_manifest_path") or stability.get("manifest_path", "")
        )
        if not aggregate_manifest_path.strip():
            blockers.append("walk_forward manifest_path is missing")

        if promotion_gate.get("decision") != "pass":
            blockers.append(f"promotion_gate decision={promotion_gate.get('decision')} next_stage={promotion_gate.get('next_stage')}")
        return blockers

    def _blocked_result(
        self,
        *,
        base_request: dict[str, Any],
        target_intervals: list[str],
        data_integrity: dict[str, Any],
        blockers: list[str],
        recommendations: list[str],
        candidate_screen: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blockers = self._stable_unique_strings(blockers)
        recommendations = self._stable_unique_strings(recommendations)
        return {
            "status": "blocked",
            "selected_priority": "BTC 数据 -> 策略 -> 回测 -> 风控 -> gate 闭环",
            "symbol": base_request["symbol"],
            "source": base_request["source"],
            "interval": base_request["interval"],
            "target_intervals": target_intervals,
            "data_integrity": data_integrity,
            "candidate_screen": candidate_screen or {},
            "selected_candidate": None,
            "event_backtest": {},
            "cost_stress": {},
            "walk_forward": {},
            "promotion_gate": {},
            "decision": "blocked",
            "next_stage": "blocked",
            "blockers": blockers,
            "recommendations": recommendations,
        }

    def _data_integrity_audit(self, data_integrity: dict[str, Any], research_interval: str) -> dict[str, Any]:
        selected = self._select_interval_evidence(data_integrity, research_interval)
        return {
            "research_interval": research_interval,
            "data_version": selected.get("data_version", ""),
            "manifest_path": selected.get("manifest_path", ""),
            "fingerprint": selected.get("fingerprint", ""),
        }

    def _build_audit_context(
        self,
        *,
        request: dict[str, Any],
        base_request: dict[str, Any],
        data_integrity: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, str]:
        selected = self._select_interval_evidence(data_integrity, str(base_request["interval"]))
        strategy_id = str(candidate.get("strategy_id", "unknown"))
        params = dict(candidate.get("parameters") or {})
        hash_payload = {
            "symbol": str(base_request["symbol"]).upper(),
            "interval": str(base_request["interval"]),
            "start": base_request["start"].isoformat(),
            "end": base_request["end"].isoformat(),
            "strategy_id": strategy_id,
            "params": params,
            "data_version": selected.get("data_version", ""),
        }
        fingerprint = hashlib.sha1(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:12]
        run_id_prefix = f"btc_closure_{str(base_request['symbol']).lower()}_{str(base_request['interval'])}_{fingerprint}"
        data_root = Path(str(request.get("data_root", "data")))
        return {
            "data_version": str(selected.get("data_version", "")),
            "data_manifest_path": str(selected.get("manifest_path", "")),
            "data_fingerprint": str(selected.get("fingerprint", "")),
            "strategy_version": str(request.get("strategy_version") or f"{strategy_id}:registry_signal_replay_v1"),
            "run_id_prefix": run_id_prefix,
            "event_run_id": f"{run_id_prefix}_event",
            "manifest_root": str(data_root / "manifests"),
            "data_root": str(data_root),
        }

    def _select_interval_evidence(self, data_integrity: dict[str, Any], interval: str) -> dict[str, Any]:
        quality_map = {
            str(row.get("interval") or row.get("target_interval")): row
            for row in data_integrity.get("quality_results", [])
        }
        resample_map = {
            str(row.get("target_interval") or row.get("interval")): row
            for row in data_integrity.get("resample_results", [])
        }
        validation_map = {
            str(row.get("interval")): row
            for row in (data_integrity.get("validation_summary") or {}).get("intervals", [])
        }
        quality = dict(quality_map.get(interval, {}))
        resample = dict(resample_map.get(interval, {}))
        validation = dict(validation_map.get(interval, {}))
        return {
            "data_version": validation.get("data_version") or resample.get("data_version") or quality.get("data_version", ""),
            "manifest_path": resample.get("manifest_path", ""),
            "fingerprint": validation.get("fingerprint") or resample.get("fingerprint") or quality.get("fingerprint", ""),
        }

    def _stable_unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    def _progress(
        self,
        progress_callback: Callable[..., None] | None,
        *,
        stage: str,
        message: str,
        progress: int,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(stage=stage, message=message, progress=progress)
