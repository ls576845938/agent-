from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
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


DEFAULT_CRYPTO_TARGET_INTERVALS = ["5m", "15m", "1h", "4h", "1d"]
DEFAULT_CRYPTO_STRATEGIES = [
    "trend_macd",
    "donchian_breakout",
    "reversion_rsi",
    "volatility_squeeze",
    "macro_trend",
    "dynamic_grid",
    "time_window",
]


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

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        base_request = self._base_request(request)
        symbol = str(base_request["symbol"]).upper()
        research_interval = str(base_request["interval"])
        target_intervals = self._target_intervals(request, research_interval)
        blockers: list[str] = []
        recommendations: list[str] = []

        data_integrity = self._run_data_integrity(
            request=request,
            base_request=base_request,
            target_intervals=target_intervals,
        )
        blockers.extend(data_integrity["blockers"])
        if data_integrity["status"] != "pass":
            return self._blocked_result(
                base_request=base_request,
                target_intervals=target_intervals,
                data_integrity=data_integrity,
                blockers=blockers,
                recommendations=[
                    "先修复 BTC 多周期数据完整性；候选筛选和回测不会在数据失败时继续执行。",
                ],
            )

        candidate_screen = self._screen_candidates(request=request, base_request=base_request)
        blockers.extend(candidate_screen["blockers"])
        preliminary_selected = candidate_screen.get("selected_candidate")
        if not preliminary_selected:
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

        selected_request = {
            **base_request,
            "strategy_id": preliminary_selected["strategy_id"],
            "strategy_params": dict(preliminary_selected.get("parameters") or {}),
        }
        event_backtest = self.research_service.run_crypto_event(selected_request)
        event_payload = {
            "status": "completed",
            "mode": event_backtest.mode,
            "summary": event_backtest.summary,
            "strategy_details": event_backtest.strategy_details,
            "latest_weights": event_backtest.latest_weights,
            "diagnostics": event_backtest.diagnostics,
        }
        blockers.extend(self._event_backtest_blockers(event_payload))

        requested_scenarios = request.get("max_scenarios")
        scenario_count = (
            len(default_crypto_cost_stress_scenarios())
            if requested_scenarios in (None, "")
            else int(requested_scenarios)
        )
        cost_stress = self.research_service.run_event_driven_cost_stress(
            {
                **selected_request,
                "max_scenarios": min(max(1, scenario_count), len(default_crypto_cost_stress_scenarios())),
            }
        )
        walk_forward = self.research_service.run_walk_forward(
            {
                **selected_request,
                "windows": min(int(request.get("windows", 2)), 8),
                "max_candidates": 1,
                "symbols": [symbol],
            }
        )
        qualification = qualify_crypto_candidates(
            [preliminary_selected],
            cost_stress_by_candidate={
                str(preliminary_selected["strategy_id"]): cost_stress,
                self._candidate_key(preliminary_selected): cost_stress,
            },
            walk_forward_by_candidate={
                str(preliminary_selected["strategy_id"]): walk_forward,
                self._candidate_key(preliminary_selected): walk_forward,
            },
            event_backtest_by_candidate={
                str(preliminary_selected["strategy_id"]): event_payload,
                self._candidate_key(preliminary_selected): event_payload,
            },
            max_selected=1,
        )
        candidate_screen["qualification"] = qualification
        if qualification.get("candidates"):
            qualified_row = dict(qualification["candidates"][0])
            candidate_screen["evaluated_candidate"] = qualified_row
            candidate_screen["candidates"] = [
                qualified_row if row.get("rank") == preliminary_selected.get("rank") else row
                for row in candidate_screen.get("candidates", [])
            ]
        strict_selected = (
            dict(qualification["selected_candidates"][0])
            if qualification.get("selected_candidates")
            else None
        )
        candidate_screen["selected_candidate"] = strict_selected
        if not strict_selected:
            blockers.extend(str(item) for item in qualification.get("blockers", []))

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

        blockers.extend(self._validation_blockers(cost_stress, walk_forward, promotion_gate))
        gate_decision = str(promotion_gate.get("decision", "fail"))
        decision = "fail" if blockers else gate_decision
        next_stage = "blocked" if blockers else str(promotion_gate.get("next_stage", "blocked"))
        if blockers:
            recommendations.append("BTC 闭环已经跑完，但仍存在阻断项；保持 paper/live 关闭。")
        else:
            recommendations.append("BTC 闭环无显式阻断；下一步仍需人工复核 evidence pack 后再考虑 paper review。")
        recommendations.extend(promotion_gate.get("recommendations", []))

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
            "event_backtest": event_payload,
            "cost_stress": cost_stress,
            "walk_forward": walk_forward,
            "promotion_gate": promotion_gate,
            "decision": decision,
            "next_stage": next_stage,
            "blockers": blockers,
            "recommendations": recommendations,
        }

    def _base_request(self, request: dict[str, Any]) -> dict[str, Any]:
        target_weight = min(0.98, max(0.0, float(request.get("target_weight", 0.90))))
        min_cash_buffer_pct = round(max(0.02, 1.0 - target_weight, float(request.get("min_cash_buffer_pct", 0.0))), 8)
        return {
            "source": "sqlite",
            "asset_class": "crypto",
            "symbol": str(request.get("symbol") or "BTCUSDT").upper(),
            "interval": str(request.get("interval") or "1h"),
            "start": request["start"],
            "end": request["end"],
            "capital": float(request.get("capital", 100_000.0)),
            "commission_rate": float(request.get("commission_rate", 0.0004)),
            "slippage": float(request.get("slippage", 4.0)),
            "leverage": min(1.0, float(request.get("leverage", 1.0))),
            "position_basis": str(request.get("position_basis", "equity")),
            "target_weight": target_weight,
            "min_cash_buffer_pct": min_cash_buffer_pct,
            "min_trade_notional": float(request.get("min_trade_notional", 25.0)),
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
                if float(payload.get("coverage_pct", 0.0)) < 99.0:
                    blockers.append(f"{interval} resample coverage {payload.get('coverage_pct')}% < 99%")
                if float(payload.get("quality_score", 0.0)) < 95.0:
                    blockers.append(f"{interval} resample quality_score {payload.get('quality_score')} < 95")
            except Exception as exc:
                resample_results.append({"target_interval": interval, "status": "failed", "error": str(exc)})
                blockers.append(f"{interval} resample failed: {exc}")

        for interval in ["1m", *target_intervals]:
            try:
                quality = self.quality_inspector(
                    source="sqlite",
                    symbol=str(base_request["symbol"]),
                    interval=interval,
                    start=start,
                    end=end,
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
        if diagnostics.get("ledger_equity_consistent") is False:
            blockers.append(f"event_backtest ledger inconsistent: {diagnostics.get('ledger_consistency_msg', '')}")
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

        stability = walk_forward.get("stability", {})
        if float(stability.get("fold_pass_rate_pct") or stability.get("pass_rate_pct", 0.0)) < 60.0:
            blockers.append(f"walk_forward pass_rate {stability.get('fold_pass_rate_pct', stability.get('pass_rate_pct', 0.0))}% < 60%")
        if float(stability.get("ledger_consistency_pct", 0.0)) < 100.0:
            blockers.append(f"walk_forward ledger consistency {stability.get('ledger_consistency_pct')}% < 100%")

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
