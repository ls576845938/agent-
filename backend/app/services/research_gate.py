from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.domain.strategy_registry import strategy_registry
from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.market_data import inspect_market_data_quality
from quant_us.research.experiments import ArtifactRef, ExperimentRegistry, ExperimentSpec


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
            self._backtest_survival_gate(artifacts.summary),
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
            "created_at": created_at.isoformat(),
            "mode": mode,
            "request": _jsonable(request),
            "strategy_version": strategy_version,
            "data_version": quality["data_version"],
            "data_fingerprint": quality["fingerprint"],
            "summary": artifacts.summary,
            "gates": gates,
            "decision": decision,
            "next_stage": next_stage,
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
            "manifest_id": manifest_id,
            "manifest_path": manifest_path,
            "strategy_version": strategy_version,
            "experiment_record": experiment_record,
            "data_quality": quality,
            "backtest_summary": artifacts.summary,
            "gates": gates,
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

    def _backtest_survival_gate(self, summary: dict[str, float | int]) -> dict[str, Any]:
        sharpe = float(summary["sharpe_ratio"])
        profit_factor = float(summary["profit_factor"])
        total_return = float(summary["total_return_pct"])
        max_drawdown = float(summary["max_drawdown_pct"])
        trade_count = int(summary.get("trade_count", 0))
        failed = total_return <= 0 or max_drawdown <= -25 or sharpe < 0 or profit_factor < 0.5 or trade_count < 10
        warned = sharpe < 0.5 or profit_factor < 1.2 or max_drawdown <= -15 or trade_count < 30
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
            },
            threshold="return>0, sharpe>=0, pf>=0.5, mdd>-25%, trades>=10 for survival; pass wants sharpe>=0.5, pf>=1.2, mdd>-15%, trades>=30",
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
        use_event_driven = str(request.get("engine", "")).lower() == "event_driven"
        if use_event_driven:
            cost = self.research_service.run_event_driven_cost_stress(
                {
                    **base_request,
                    "strategy_id": strategy_id,
                    "strategy_params": strategy_params,
                    "max_scenarios": min(int(request.get("max_scenarios", 2)), 3),
                }
            )
        else:
            cost = self.research_service.run_cost_stress(
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
            }
        )
        # Safely extract stability metrics; walk-forward may return error/insufficient data
        walk_stability = walk.get("stability", {})
        walk_pass_rate = float(walk_stability.get("pass_rate_pct", 0.0)) if walk_stability else 0.0
        return {
            "cost_stress": cost,
            "walk_forward": walk,
            "gates": [
                _gate(
                    name="cost_stress",
                    status=_gate_status(failed=float(cost["survival_rate_pct"]) < 60.0, warned=float(cost["survival_rate_pct"]) < 100.0),
                    message="成本压力场景存活率检查。",
                    metrics={"survival_rate_pct": cost["survival_rate_pct"]},
                    threshold="pass=100%, warn>=60%, fail<60%",
                ),
                _gate(
                    name="walk_forward",
                    status=_gate_status(failed=walk_pass_rate < 60.0, warned=walk_pass_rate < 100.0),
                    message="Walk-forward 样本外窗口通过率检查。",
                    metrics=walk_stability,
                    threshold="pass=100%, warn>=60%, fail<60%",
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

    def _recommendations(self, gates: list[dict[str, Any]], decision: str) -> list[str]:
        if decision == "pass":
            return ["核心准入门通过；若深度检查也通过，可以把该配置登记为候选实验。"]
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
