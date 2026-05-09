from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.domain.strategy_registry import strategy_registry
from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.market_data import inspect_market_data_quality
from quant_us.data.storage.data_manifest import (
    build_manifest_from_quality,
    validate_manifest_for_promotion,
)
from quant_us.research.experiments import ArtifactRef, ExperimentRegistry, ExperimentSpec


DATA_MANIFEST_ADVISORY_WARNINGS = {
    "universe_id_missing",
    "universe_source_missing",
    "survivorship_bias_risk_unmarked",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _gate_status(failed: bool, warned: bool = False) -> str:
    if failed:
        return "fail"
    if warned:
        return "warn"
    return "pass"


def _gate(
    name: str,
    status: str,
    message: str,
    metrics: dict[str, Any],
    threshold: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "metrics": metrics,
        "threshold": threshold,
    }


def _promotion_framework() -> list[dict[str, Any]]:
    return [
        {
            "priority": 1,
            "title": "数据质量与版本治理",
            "status": "completed",
            "reason": "先确认数据覆盖率、异常和稳定指纹，否则任何回测结论都不可晋级。",
        },
        {
            "priority": 2,
            "title": "核心回测生存性",
            "status": "completed",
            "reason": "用同一套策略和组合代码检查收益、回撤、交易边际和执行成本。",
        },
        {
            "priority": 3,
            "title": "深度稳健性验证",
            "status": "next",
            "reason": "按需调用成本压力、Walk-forward 或组合相关性验证。",
        },
        {
            "priority": 4,
            "title": "研究晋级决策",
            "status": "selected",
            "reason": "把各层检查汇总为 pass/warn/fail，并生成可复现 manifest。",
        },
        {
            "priority": 5,
            "title": "后续 paper / ML 准备",
            "status": "later",
            "reason": "只有通过准入门的配置才进入 paper trading、机器学习特征训练或更大样本研究。",
        },
    ]


class ResearchPromotionGateService:
    def __init__(
        self,
        research_service: ResearchBacktestService | None = None,
        manifest_root: str | Path | None = None,
        experiment_root: str | Path | None = None,
        experiment_registry: ExperimentRegistry | None = None,
    ) -> None:
        self.research_service = research_service or ResearchBacktestService()
        self.manifest_root = Path(manifest_root) if manifest_root is not None else settings.reports_dir / "research_gates"
        self.experiment_root = Path(experiment_root) if experiment_root is not None else settings.repo_root / "data" / "experiments"
        self.experiment_registry = experiment_registry

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        mode = str(request.get("mode", "portfolio"))
        if mode not in {"single", "portfolio"}:
            raise ValueError("mode must be one of ['single', 'portfolio']")

        base_request = self._base_backtest_request(request)
        quality = inspect_market_data_quality(
            source=base_request["source"],
            symbol=base_request["symbol"],
            interval=base_request["interval"],
            start=base_request["start"],
            end=base_request["end"],
            db_path=base_request.get("data_db_path", ""),
        )
        data_manifest = build_manifest_from_quality(
            quality=quality,
            source=base_request["source"],
            symbol=base_request["symbol"],
            interval=base_request["interval"],
            asset_class=str(request.get("asset_class") or self._asset_class(base_request["symbol"])),
        )
        data_manifest_validation = validate_manifest_for_promotion(data_manifest)

        if mode == "single":
            strategy_id = request.get("strategy_id") or "trend_macd"
            backtest_request = {
                **base_request,
                "strategy_id": strategy_id,
                "strategy_params": dict(request.get("strategy_params", {}) or {}),
            }
            artifacts = self.research_service.run_single(backtest_request)
        else:
            backtest_request = {
                **base_request,
                "weights": self._weights(request),
            }
            artifacts = self.research_service.run_portfolio(backtest_request)

        gates = [
            self._data_quality_gate(quality),
            self._data_manifest_gate(data_manifest_validation),
            self._evidence_scope_gate(quality, base_request, request),
            self._backtest_survival_gate(artifacts.summary, interval=base_request.get("interval", "1d"), mode=mode),
            self._execution_gate(artifacts.diagnostics.get("execution", {}), artifacts.summary),
            self._risk_gate(artifacts.summary, artifacts.diagnostics.get("exposure", {})),
        ]

        deep_checks: dict[str, Any] = {}
        skip_deep = request.get("skip_deep_checks", False)
        if not skip_deep:
            if mode == "single":
                deep_checks = self._single_deep_checks(request, base_request)
            else:
                deep_checks = self._portfolio_deep_checks(request, base_request)
            gates.extend(deep_checks.get("gates", []))
        else:
            gates.append(
                _gate(
                    name="deep_validation",
                    status="fail",
                    message="深度验证被跳过；成本压力测试和 Walk-forward 是晋级 paper trading 的硬性前提。",
                    metrics={"skip_deep_checks": True},
                    threshold="成本压力 + walk-forward 全部通过 = paper candidate",
                )
            )

        decision = self._decision(gates)
        next_stage = self._next_stage(decision, bool(request.get("skip_deep_checks", False)))
        strategy_version = self._strategy_version(mode, request)
        created_at = _now()
        manifest = {
            "gate_version": "2.0.0",
            "created_at": created_at.isoformat(),
            "generated_at": created_at.isoformat(),
            "mode": mode,
            "request": _jsonable(request),
            "strategy_version": strategy_version,
            "data_version": quality["data_version"],
            "data_fingerprint": quality["fingerprint"],
            "config_version": _fingerprint({k: request.get(k) for k in ["rebalance_buffer_pct", "min_holding_bars", "cost_aware_filter", "max_annual_turnover_pct"] if k in request})[:16],
            "data_manifest": asdict(data_manifest),
            "data_manifest_validation": {
                "ok": data_manifest_validation.ok,
                "reasons": data_manifest_validation.reasons,
                "warnings": data_manifest_validation.warnings,
                "metrics": data_manifest_validation.metrics,
            },
            "summary": artifacts.summary,
            "gates": gates,
            "decision": decision,
            "next_stage": next_stage,
            "promotion_authority": self._promotion_authority(next_stage),
            "canonical_validation": self._canonical_validation(mode, deep_checks, skip_deep),
            "deep_checks": {key: value for key, value in deep_checks.items() if key != "gates"},
        }
        manifest_id = _fingerprint(manifest)[:24]
        manifest["manifest_id"] = manifest_id
        manifest_path = ""
        register_experiment = bool(request.get("register_experiment", False))
        if bool(request.get("persist_manifest", True)) or register_experiment:
            manifest_path = str(self._write_manifest(manifest_id, manifest))
        experiment_record = {}
        if register_experiment:
            experiment_record = self._register_experiment(
                request=request,
                base_request=base_request,
                manifest_id=manifest_id,
                manifest_path=manifest_path,
                strategy_version=strategy_version,
                decision=decision,
                next_stage=next_stage,
                quality=quality,
                summary=artifacts.summary,
                gates=gates,
            )

        return {
            "status": "completed",
            "selected_priority": "研究准入与实验晋级门",
            "framework": _promotion_framework(),
            "decision": decision,
            "next_stage": next_stage,
            "promotion_authority": manifest["promotion_authority"],
            "manifest_id": manifest_id,
            "manifest_path": manifest_path,
            "strategy_version": strategy_version,
            "experiment_record": experiment_record,
            "data_quality": quality,
            "data_manifest": asdict(data_manifest),
            "data_manifest_validation": {
                "ok": data_manifest_validation.ok,
                "reasons": data_manifest_validation.reasons,
                "warnings": data_manifest_validation.warnings,
                "metrics": data_manifest_validation.metrics,
            },
            "backtest_summary": artifacts.summary,
            "gates": gates,
            "canonical_validation": manifest["canonical_validation"],
            "recommendations": self._recommendations(gates, decision),
        }

    def _base_backtest_request(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": request.get("source", settings.default_data_source),
            "symbol": request.get("symbol", settings.default_symbol),
            "interval": request.get("interval", settings.default_interval),
            "start": request["start"],
            "end": request["end"],
            "capital": float(request.get("capital", settings.default_capital)),
            "commission_rate": float(request.get("commission_rate", settings.default_commission_rate)),
            "slippage": float(request.get("slippage", settings.default_slippage)),
            "leverage": float(request.get("leverage", settings.default_leverage)),
            "position_basis": str(request.get("position_basis", "equity")),
            "data_db_path": str(request.get("data_db_path", "")),
        }

    def _weights(self, request: dict[str, Any]) -> list[dict[str, float | str]]:
        weights = [
            {"strategy_id": item["strategy_id"], "weight": float(item["weight"])}
            for item in request.get("weights", [])
            if float(item.get("weight", 0.0)) > 0
        ]
        if weights:
            return weights
        return []

    def _strategy_version(self, mode: str, request: dict[str, Any]) -> str:
        if mode == "single":
            strategy_ids = [str(request.get("strategy_id") or "trend_macd")]
        else:
            strategy_ids = [str(item["strategy_id"]) for item in self._weights(request)]
        strategies: list[dict[str, Any]] = []
        for strategy_id in sorted(set(strategy_ids)):
            descriptor = strategy_registry.get(strategy_id).descriptor
            strategies.append(
                {
                    "id": descriptor.id,
                    "category": descriptor.category,
                    "default_weight": descriptor.default_weight,
                    "default_params": descriptor.default_params,
                }
            )
        payload = {
            "mode": mode,
            "strategies": strategies,
            "strategy_params": request.get("strategy_params", {}),
            "weights": sorted(self._weights(request), key=lambda item: str(item["strategy_id"])),
        }
        return f"strategy_{_fingerprint(payload)[:16]}"

    def _data_quality_gate(self, quality: dict[str, Any]) -> dict[str, Any]:
        status = _gate_status(
            failed=not bool(quality["is_usable"]) or float(quality["coverage_pct"]) < 85.0,
            warned=float(quality["quality_score"]) < 95.0 or int(quality["missing_bars"]) > 0 or float(quality["coverage_pct"]) < 95.0,
        )
        return _gate(
            name="data_quality",
            status=status,
            message="数据可用性、覆盖率和异常检查。",
            metrics={
                "quality_score": quality["quality_score"],
                "coverage_pct": quality["coverage_pct"],
                "missing_bars": quality["missing_bars"],
                "data_version": quality["data_version"],
            },
            threshold="usable=true, coverage>=95%, score>=95 for pass; coverage<85% = fail",
        )

    def _data_manifest_gate(self, validation) -> dict[str, Any]:
        failed = not validation.ok
        decision_warnings = [
            warning
            for warning in validation.warnings
            if warning not in DATA_MANIFEST_ADVISORY_WARNINGS
        ]
        warned = bool(decision_warnings)
        if failed:
            message = "数据 manifest 不满足 paper candidate 级别的数据谱系与完整性要求。"
        elif warned:
            message = "数据 manifest 可用，但存在缺失 K 线等需要记录的非阻断警告。"
        else:
            message = "数据 manifest schema、来源、校验和、时区与质量指标满足晋级要求。"
        return _gate(
            name="data_manifest",
            status=_gate_status(failed=failed, warned=warned),
            message=message,
            metrics={
                **validation.metrics,
                "reasons": validation.reasons,
                "warnings": validation.warnings,
            },
            threshold="source in {yfinance, alpaca, sqlite}; equity only; UTC; checksum/fingerprint present; coverage>=90%; quality>=80%; no duplicate/invalid/non-positive bars or future timestamps",
        )

    def _evidence_scope_gate(
        self,
        quality: dict[str, Any],
        base_request: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        requested_source = str(base_request.get("source", "")).lower()
        actual_source = str(quality.get("actual_source") or quality.get("source") or requested_source).lower()
        symbol = str(base_request.get("symbol", "")).upper()
        asset_class = str(request.get("asset_class") or self._asset_class(symbol)).lower()
        allowed_sources = {"yfinance", "alpaca", "sqlite"}
        fixture_used = requested_source == "fixture" or actual_source == "fixture"
        failed = fixture_used or asset_class != "equity" or actual_source not in allowed_sources
        warned = not failed and (requested_source == "auto" or actual_source == "sqlite")
        if fixture_used:
            message = "晋级证据不能来自 fixture 数据；fixture 只允许用于本地测试或演示。"
        elif asset_class != "equity":
            message = "晋级证据必须限定在美股 equity 范围，crypto/非 equity 标的不得进入 paper candidate。"
        elif actual_source not in allowed_sources:
            message = "晋级证据来源不在受支持的数据谱系中。"
        elif warned:
            message = "数据来源可研究使用，但进入 paper candidate 前需要显式的 yfinance/Alpaca 或受治理 SQLite 证据确认。"
        else:
            message = "晋级证据限定在 US equity 数据谱系内，且未使用 fixture。"
        return _gate(
            name="evidence_scope",
            status=_gate_status(failed=failed, warned=warned),
            message=message,
            metrics={
                "requested_source": requested_source,
                "actual_source": actual_source,
                "symbol": symbol,
                "asset_class": asset_class,
                "fixture_used": fixture_used,
                "allowed_actual_sources": sorted(allowed_sources),
            },
            threshold="paper candidate requires US equity evidence and no fixture fallback; auto/sqlite evidence stays research_iteration until explicitly governed",
        )

    def _backtest_survival_gate(self, summary: dict[str, float | int], interval: str = "1d", mode: str = "single") -> dict[str, Any]:
        sharpe = float(summary["sharpe_ratio"])
        profit_factor = float(summary["profit_factor"])
        total_return = float(summary["total_return_pct"])
        max_drawdown = float(summary["max_drawdown_pct"])
        trade_count = int(summary.get("trade_count", 0))
        signal_count = int(summary.get("signal_count", trade_count))
        is_low_frequency = interval in ("1d", "4h", "1w") or mode == "portfolio"
        if is_low_frequency:
            failed = total_return <= 0 or max_drawdown <= -25 or sharpe < 0 or profit_factor < 0.5 or trade_count < 3
            warned = sharpe < 0.5 or profit_factor < 1.2 or max_drawdown <= -15 or trade_count < 5
            criteria = f"low_frequency_profile: return>0,sharpe>=0,pf>=0.5,mdd>-25%,trades>=3 (interval={interval})"
        else:
            failed = total_return <= 0 or max_drawdown <= -25 or sharpe < 0 or profit_factor < 0.5 or trade_count < 10
            warned = sharpe < 0.5 or profit_factor < 1.2 or max_drawdown <= -15 or trade_count < 30
            criteria = f"standard_profile: return>0,sharpe>=0,pf>=0.5,mdd>-25%,trades>=10 (interval={interval})"
        return _gate(
            name="backtest_survival",
            status=_gate_status(failed=failed, warned=warned),
            message="基础收益质量、交易边际、最大回撤和最小交易次数检查。",
            metrics={
                "total_return_pct": total_return,
                "sharpe_ratio": sharpe,
                "profit_factor": profit_factor,
                "max_drawdown_pct": max_drawdown,
                "trade_count": trade_count,
                "signal_count": signal_count,
                "frequency_profile": "low_frequency" if is_low_frequency else "standard",
            },
            threshold=criteria,
        )

    def _execution_gate(self, execution: dict[str, Any], summary: dict[str, float | int]) -> dict[str, Any]:
        cost_drag = float(execution.get("cost_drag_pct", 0.0))
        annual_turnover = float(execution.get("annual_turnover_pct", 0.0))
        total_return = abs(float(summary["total_return_pct"]))
        failed = (
            cost_drag > max(2.0, total_return * 0.5)
            or annual_turnover > 5000.0
            or (cost_drag > total_return and total_return > 0)
        )
        warned = (
            cost_drag > max(0.5, total_return * 0.15)
            or annual_turnover > 1500.0
        )
        return _gate(
            name="execution_cost",
            status=_gate_status(failed=failed, warned=warned),
            message="交易成本拖累和换手率检查。",
            metrics={
                "cost_drag_pct": cost_drag,
                "annual_turnover_pct": annual_turnover,
                "orders": int(execution.get("orders", 0)),
            },
            threshold="cost drag <= max(2%, 50% of |return|), turnover <= 5000% for pass; cost drag must not exceed total return",
        )

    def _risk_gate(self, summary: dict[str, float | int], exposure: dict[str, Any]) -> dict[str, Any]:
        max_drawdown = float(summary["max_drawdown_pct"])
        max_exposure = float(exposure.get("max_gross_exposure_pct", 0.0))
        failed = max_drawdown <= -20 or max_exposure > 300
        warned = max_drawdown <= -12 or max_exposure > 200
        return _gate(
            name="portfolio_risk",
            status=_gate_status(failed=failed, warned=warned),
            message="回撤和最大总敞口检查。",
            metrics={
                "max_drawdown_pct": max_drawdown,
                "max_gross_exposure_pct": max_exposure,
            },
            threshold="mdd>-20%, max gross exposure<=300%; pass wants mdd>-12%, exposure<=200%",
        )

    def _single_deep_checks(self, request: dict[str, Any], base_request: dict[str, Any]) -> dict[str, Any]:
        strategy_id = request.get("strategy_id") or "trend_macd"
        strategy_params = dict(request.get("strategy_params", {}) or {})
        cost = self.research_service.run_event_driven_cost_stress(
            {
                **base_request,
                "strategy_id": strategy_id,
                "strategy_params": strategy_params,
                "max_scenarios": min(int(request.get("max_scenarios", 2)), 3),
            }
        )
        walk = self.research_service.run_walk_forward(
            {
                **base_request,
                "strategy_id": strategy_id,
                "strategy_params": strategy_params,
                "windows": min(int(request.get("windows", 2)), 3),
                "max_candidates": min(int(request.get("max_candidates", 1)), 3),
                "symbols": request.get("symbols") or ["SPY", "QQQ", "IWM", "DIA"],
            }
        )
        # Safely extract stability metrics; walk-forward may return error/insufficient data
        walk_stability = walk.get("stability", {})
        # Use fold_pass_rate_pct (multi-symbol) or pass_rate_pct (legacy single-symbol)
        walk_pass_rate = float(
            walk_stability.get("fold_pass_rate_pct") or walk_stability.get("pass_rate_pct", 0.0)
        ) if walk_stability else 0.0
        is_insufficient = walk.get("status") == "insufficient_data"
        cost_engine = str(cost.get("engine", "unknown"))
        cost_ledger_consistency_pct = float(cost.get("ledger_consistency_pct", 0.0))
        cost_metrics = {
            "engine": cost_engine,
            "survival_rate_pct": cost["survival_rate_pct"],
            "ledger_consistency_pct": cost_ledger_consistency_pct,
            "ledger_equity_consistent_scenarios": int(cost.get("ledger_equity_consistent_scenarios", 0)),
            "baseline_fill_count": int(cost.get("baseline_fill_count", 0)),
            "baseline_order_count": int(cost.get("baseline_order_count", 0)),
            "total_fill_count": int(cost.get("total_fill_count", 0)),
            "total_order_count": int(cost.get("total_order_count", 0)),
        }
        cost_metrics["has_ledger_trade_metadata"] = all(
            int(cost_metrics[key]) > 0
            for key in ("baseline_fill_count", "baseline_order_count", "total_fill_count", "total_order_count")
        )
        return {
            "cost_stress": cost,
            "walk_forward": walk,
            "gates": [
                _gate(
                    name="cost_stress",
                    status=_gate_status(
                        failed=(
                            cost_engine != "event_driven"
                            or float(cost["survival_rate_pct"]) < 60.0
                            or cost_ledger_consistency_pct < 100.0
                            or not bool(cost_metrics["has_ledger_trade_metadata"])
                        ),
                        warned=float(cost["survival_rate_pct"]) < 100.0,
                    ),
                    message="事件驱动成本压力场景存活率与 ledger 一致性检查。",
                    metrics=cost_metrics,
                    threshold="event_driven required; pass=100% survival and 100% ledger consistency, warn survival>=60%, fail survival<60% or ledger mismatch",
                ),
                _gate(
                    name="walk_forward",
                    status=_gate_status(
                        failed=walk_pass_rate < 60.0 and not is_insufficient,
                        warned=(walk_pass_rate < 100.0 and not is_insufficient) or is_insufficient,
                    ),
                    message="Walk-forward 多标的样本外窗口通过率检查。",
                    metrics=walk_stability,
                    threshold="pass=100%, warn>=60% or insufficient data, fail<60%",
                ),
            ],
        }

    def _portfolio_deep_checks(self, request: dict[str, Any], base_request: dict[str, Any]) -> dict[str, Any]:
        result = self.research_service.optimize_portfolio(
            {
                **base_request,
                "weights": self._weights(request),
                "max_single_weight": float(request.get("max_single_weight", 0.35)),
                "correlation_penalty": float(request.get("correlation_penalty", 0.75)),
                "cash_reserve_pct": float(request.get("cash_reserve_pct", 5.0)),
            }
        )
        max_corr = float(result["risk_budget"].get("max_pair_abs_correlation", 0.0))
        sharpe_delta = float(result["improvement"].get("sharpe_delta", 0.0))
        return {
            "portfolio_optimization": result,
            "gates": [
                _gate(
                    name="portfolio_allocation",
                    status=_gate_status(failed=max_corr >= 0.95, warned=max_corr >= 0.75 or sharpe_delta < -0.2),
                    message="组合相关性、风险预算和优化权重检查。",
                    metrics={
                        "max_pair_abs_correlation": max_corr,
                        "sharpe_delta": sharpe_delta,
                        "active_gross_pct": result["risk_budget"].get("active_gross_pct", 0.0),
                    },
                    threshold="max pair abs correlation<0.75 for pass, <0.95 for warn",
                )
            ],
        }

    def _canonical_validation(
        self,
        mode: str,
        deep_checks: dict[str, Any],
        skip_deep_checks: bool,
    ) -> dict[str, Any]:
        if skip_deep_checks:
            return {
                "engine": "not_validated",
                "ledger_verified": False,
                "reason": "deep validation skipped",
            }
        if mode != "single":
            return {
                "engine": "portfolio_optimization",
                "ledger_verified": False,
                "reason": "portfolio gate requires separate allocation validation before paper review",
            }
        cost = deep_checks.get("cost_stress", {})
        ledger_consistency_pct = float(cost.get("ledger_consistency_pct", 0.0))
        return {
            "engine": cost.get("engine", "event_driven"),
            "ledger_verified": ledger_consistency_pct >= 100.0,
            "ledger_consistency_pct": ledger_consistency_pct,
            "baseline_fill_count": int(cost.get("baseline_fill_count", 0)),
            "baseline_order_count": int(cost.get("baseline_order_count", 0)),
            "total_fill_count": int(cost.get("total_fill_count", 0)),
            "total_order_count": int(cost.get("total_order_count", 0)),
        }

    def _decision(self, gates: list[dict[str, Any]]) -> str:
        statuses = {gate["status"] for gate in gates}
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    def _next_stage(self, decision: str, skip_deep_checks: bool) -> str:
        if decision == "pass" and not skip_deep_checks:
            return "paper_candidate"
        if decision == "pass":
            return "deep_validation"
        if decision == "warn":
            return "research_iteration"
        return "blocked"

    def _promotion_authority(self, next_stage: str) -> dict[str, Any]:
        return {
            "service_layer_stage": next_stage,
            "paper_candidate": next_stage == "paper_candidate",
            "service_layer_only": True,
            "automation_gate_required": True,
            "paper_review_required": True,
            "paper_runtime_approved": False,
            "message": (
                "research_gate 只输出服务层研究评估结果；"
                "paper_candidate/next_stage 不等于 paper runtime approval。"
            ),
        }

    def _recommendations(self, gates: list[dict[str, Any]], decision: str) -> list[str]:
        if decision == "pass":
            return [
                "核心准入门通过；当前结果仅表示服务层 paper_candidate 候选，仍需 automation promotion gate 最终裁决后才能进入人工 paper review。"
            ]
        failed = [gate for gate in gates if gate["status"] == "fail"]
        warned = [gate for gate in gates if gate["status"] == "warn"]
        recommendations: list[str] = []
        if failed:
            recommendations.append(f"存在阻断项：{', '.join(gate['name'] for gate in failed)}，不要晋级到 paper trading。")
        if warned:
            recommendations.append(f"存在警告项：{', '.join(gate['name'] for gate in warned)}，需要补充深度验证或收紧风险参数。")
        return recommendations or ["继续扩大样本并登记实验 manifest。"]

    def _write_manifest(self, manifest_id: str, manifest: dict[str, Any]) -> Path:
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        path = self.manifest_root / f"{manifest_id}.json"
        path.write_text(json.dumps(_jsonable(manifest), indent=2, sort_keys=True), encoding="utf-8")
        return path

    def _register_experiment(
        self,
        request: dict[str, Any],
        base_request: dict[str, Any],
        manifest_id: str,
        manifest_path: str,
        strategy_version: str,
        decision: str,
        next_stage: str,
        quality: dict[str, Any],
        summary: dict[str, float | int],
        gates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        registry = self.experiment_registry or ExperimentRegistry(self.experiment_root)
        experiment_name = str(request.get("experiment_name") or self._default_experiment_name(request, base_request))
        metrics = self._experiment_metrics(summary, quality, gates)
        artifacts = [
            ArtifactRef(
                name="promotion_manifest",
                path=manifest_path,
                artifact_type="json",
                metadata={
                    "manifest_id": manifest_id,
                    "decision": decision,
                    "next_stage": next_stage,
                    "data_version": quality["data_version"],
                },
            )
        ]
        mode = str(request.get("mode", "portfolio"))
        spec = ExperimentSpec(
            experiment_name=experiment_name,
            run_type="research_promotion_gate",
            symbols=[str(base_request["symbol"]).upper()],
            start=_as_utc(base_request["start"]),
            end=_as_utc(base_request["end"]),
            strategy_id=str((request.get("strategy_id") or "trend_macd") if mode == "single" else "portfolio"),
            strategy_version=strategy_version,
            data_vendor=str(base_request["source"]),
            asset_class=str(request.get("asset_class") or self._asset_class(base_request["symbol"])),
            bar_size=str(base_request["interval"]),
            data_version=str(quality["data_version"]),
            promotion_decision=decision,
            promotion_stage=next_stage,
            promotion_manifest_id=manifest_id,
            parameters={
                "mode": mode,
                "strategy_params": request.get("strategy_params", {}),
                "weights": self._weights(request),
                "capital": base_request["capital"],
                "commission_rate": base_request["commission_rate"],
                "slippage": base_request["slippage"],
                "leverage": base_request["leverage"],
                "position_basis": base_request["position_basis"],
                "skip_deep_checks": bool(request.get("skip_deep_checks", False)),
            },
            tags=["promotion_gate", mode, decision],
            notes=str(request.get("notes", "")),
        )
        run_id = f"gate_{manifest_id}"
        record = registry.create_record(
            run_id=run_id,
            spec=spec,
            metrics=metrics,
            artifacts=artifacts,
            status="completed",
        )
        registry_path = registry.register(record)
        return {
            "experiment_name": experiment_name,
            "experiment_id": record.experiment_id,
            "run_id": run_id,
            "registry_path": str(registry_path),
            "index_path": str(registry.index_path),
            "strategy_version": strategy_version,
            "data_version": quality["data_version"],
            "decision": decision,
            "next_stage": next_stage,
        }

    def _experiment_metrics(
        self,
        summary: dict[str, float | int],
        quality: dict[str, Any],
        gates: list[dict[str, Any]],
    ) -> dict[str, float | int]:
        fail_count = sum(1 for gate in gates if gate["status"] == "fail")
        warn_count = sum(1 for gate in gates if gate["status"] == "warn")
        pass_count = sum(1 for gate in gates if gate["status"] == "pass")
        promotion_score = max(0.0, 100.0 - fail_count * 40.0 - warn_count * 12.5)
        numeric_summary = {key: value for key, value in summary.items() if isinstance(value, int | float)}
        return {
            **numeric_summary,
            "data_quality_score": float(quality.get("quality_score", 0.0)),
            "data_coverage_pct": float(quality.get("coverage_pct", 0.0)),
            "promotion_score": promotion_score,
            "gate_pass_count": pass_count,
            "gate_warn_count": warn_count,
            "gate_fail_count": fail_count,
        }

    def _default_experiment_name(self, request: dict[str, Any], base_request: dict[str, Any]) -> str:
        symbol = str(base_request["symbol"]).lower().replace("/", "_").replace("-", "_")
        mode = str(request.get("mode", "portfolio"))
        return f"{symbol}_{mode}_promotion_gate"

    def _asset_class(self, symbol: Any) -> str:
        normalized = str(symbol).upper()
        if normalized.endswith(("USDT", "USD", "BTC", "ETH")):
            return "crypto"
        return "equity"
