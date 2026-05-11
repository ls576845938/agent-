from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

import pandas as pd

from integrations.pypfopt_adapter.build_covariance import build_covariance
from integrations.pypfopt_adapter.build_expected_returns import build_expected_returns
from integrations.pypfopt_adapter.import_target_weights import import_target_weights
from integrations.pypfopt_adapter.optimize_weights import optimize_weights
from integrations.pypfopt_adapter.schemas import (
    PortfolioAdapterConfig,
    load_portfolio_config,
    read_run_manifest,
)
from integrations.qlib_adapter.compile_qlib_strategy_manifest import (
    compile_qlib_strategy_manifest,
)
from integrations.qlib_adapter.import_pred_score import import_pred_score
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
from quant_us.backtest.walk_forward import (
    UnifiedWalkForwardResult,
    WalkForwardConfig,
    WalkForwardWindow,
    aggregate_walk_forward,
    build_walk_forward_windows,
)
from quant_us.core.clock import utc_now
from quant_us.core.events import RiskEvent
from quant_us.core.types import Bar, TargetPosition, new_id
from quant_us.data.storage.data_manifest import DataManifestStore
from quant_us.data.storage.parquet_store import ParquetBarStore
from quant_us.risk.pre_trade import PreTradeRiskConfig


DEFAULT_COST_STRESS_MULTIPLIERS = (
    (1.0, 1.0, "1x baseline"),
    (2.0, 2.0, "2x cost stress"),
    (5.0, 5.0, "5x cost stress"),
    (10.0, 10.0, "10x cost stress"),
)


@dataclass(frozen=True)
class ResearchExecutionPipelineConfig:
    qlib_run_id: str
    qlib_config_path: str | Path
    portfolio_config_path: str | Path
    pipeline_run_id: str = field(default_factory=lambda: new_id("rpipe"))
    portfolio_run_id: str = ""
    strategy_id: str = ""
    qlib_runs_root: Path = field(default_factory=lambda: Path("artifacts/qlib_runs"))
    portfolio_runs_root: Path = field(default_factory=lambda: Path("artifacts/portfolio_runs"))
    pipeline_runs_root: Path = field(default_factory=lambda: Path("artifacts/research_execution_runs"))
    initial_cash: float = 100_000.0
    commission_rate: float = 0.0001
    slippage_bps: float = 1.0
    fill_ratio: float = 1.0
    volume_participation_cap_pct: float = 5.0
    max_daily_turnover_pct: float = 200.0
    risk_max_symbol_weight: float | None = None
    risk_max_gross_exposure: float = 1.0
    risk_max_order_notional_pct: float = 0.10
    risk_min_cash_buffer_pct: float | None = None
    risk_long_only: bool = True
    walk_forward_train_bars: int = 252
    walk_forward_test_bars: int = 63
    walk_forward_step_bars: int = 63
    cost_stress_multipliers: tuple[tuple[float, float, str], ...] = DEFAULT_COST_STRESS_MULTIPLIERS


@dataclass(frozen=True)
class ResearchExecutionPipelineResult:
    pipeline_run_id: str
    status: str
    fail_closed: bool
    manifest_path: str
    evidence_pack_path: str
    portfolio_run_id: str
    qlib_run_id: str
    error: str = ""


def run_research_execution_pipeline(
    config: ResearchExecutionPipelineConfig,
) -> ResearchExecutionPipelineResult:
    loaded_portfolio_config = load_portfolio_config(config.portfolio_config_path)
    portfolio_config = PortfolioAdapterConfig(
        **{
            **asdict(loaded_portfolio_config),
            "score_runs_root": Path(config.qlib_runs_root),
            "portfolio_runs_root": Path(config.portfolio_runs_root),
        }
    )
    resolved_portfolio_run_id = config.portfolio_run_id or portfolio_config.portfolio_run_id or new_id("pfrun")
    portfolio_config = portfolio_config.with_overrides(portfolio_run_id=resolved_portfolio_run_id)

    pipeline_root = config.pipeline_runs_root / config.pipeline_run_id
    manifest_path = pipeline_root / "pipeline_result_manifest.json"
    evidence_pack_path = pipeline_root / "evidence_pack.json"
    cost_stress_path = pipeline_root / "cost_stress_report.json"
    walk_forward_path = pipeline_root / "walk_forward_report.json"

    evidence_pack: dict[str, Any] = {
        "schema_version": "research_execution_evidence_pack_v1",
        "pipeline_run_id": config.pipeline_run_id,
        "generated_at": utc_now().isoformat(),
        "status": "failed",
        "fail_closed": True,
        "lineage": {},
        "stage_status": {},
        "artifacts": {
            "manifest_path": str(manifest_path),
            "evidence_pack_path": str(evidence_pack_path),
            "cost_stress_report_path": str(cost_stress_path),
            "walk_forward_report_path": str(walk_forward_path),
        },
        "risk_gate": {
            "enforced": True,
            "path": "TargetPosition -> OrderIntent -> OMS pre-trade risk -> Order -> Fill -> Ledger",
        },
        "gate_blockers": [],
    }

    manifest: dict[str, Any] = {
        "schema_version": "research_execution_pipeline_result_v1",
        "pipeline_run_id": config.pipeline_run_id,
        "generated_at": evidence_pack["generated_at"],
        "status": "failed",
        "fail_closed": True,
        "qlib_run_id": config.qlib_run_id,
        "portfolio_run_id": resolved_portfolio_run_id,
        "manifest_path": str(manifest_path),
        "evidence_pack_path": str(evidence_pack_path),
    }

    blockers: list[str] = []
    error_message = ""

    try:
        imported_scores_result = import_pred_score(
            run_id=config.qlib_run_id,
            artifacts_root=config.qlib_runs_root,
        )
        _record_stage(
            evidence_pack,
            "import_pred_score",
            status=imported_scores_result.status,
            artifact_path=imported_scores_result.research_model_scores_path,
            details=asdict(imported_scores_result),
        )
        if imported_scores_result.status != "completed":
            raise RuntimeError(imported_scores_result.error or "Qlib pred_score import failed.")

        qlib_manifest_path = compile_qlib_strategy_manifest(
            run_id=config.qlib_run_id,
            config_path=config.qlib_config_path,
            artifacts_root=config.qlib_runs_root,
        )
        qlib_manifest = _read_json(qlib_manifest_path)
        _record_stage(
            evidence_pack,
            "compile_qlib_strategy_manifest",
            status="completed",
            artifact_path=qlib_manifest_path,
            details={
                "strategy_version": qlib_manifest.get("strategy_version", ""),
                "model_id": qlib_manifest.get("model_id", ""),
                "data_versions": qlib_manifest.get("data_versions", []),
            },
        )

        expected_returns_frame, expected_returns_output_path = build_expected_returns(
            score_run_id=config.qlib_run_id,
            config=portfolio_config,
            portfolio_run_id=resolved_portfolio_run_id,
        )
        _record_stage(
            evidence_pack,
            "build_expected_returns",
            status="completed",
            artifact_path=expected_returns_output_path,
            details={"rows": int(len(expected_returns_frame))},
        )

        covariance_frame, covariance_output_path = build_covariance(
            score_run_id=config.qlib_run_id,
            config=portfolio_config,
            portfolio_run_id=resolved_portfolio_run_id,
        )
        _record_stage(
            evidence_pack,
            "build_covariance",
            status="completed",
            artifact_path=covariance_output_path,
            details={"rows": int(len(covariance_frame))},
        )

        target_weights_frame, target_weights_output_path, fallback_used = optimize_weights(
            score_run_id=config.qlib_run_id,
            config=portfolio_config,
            portfolio_run_id=resolved_portfolio_run_id,
        )
        _record_stage(
            evidence_pack,
            "optimize_weights",
            status="completed",
            artifact_path=target_weights_output_path,
            details={
                "rows": int(len(target_weights_frame)),
                "fallback_used": bool(fallback_used),
            },
        )

        target_positions_frame, target_positions_parquet_path, target_positions_json_path = import_target_weights(
            portfolio_run_id=resolved_portfolio_run_id,
            config=portfolio_config,
            strategy_id=config.strategy_id or None,
        )
        target_positions = _target_positions_from_frame(target_positions_frame)
        _record_stage(
            evidence_pack,
            "import_target_weights",
            status="completed",
            artifact_path=target_positions_parquet_path,
            details={
                "rows": int(len(target_positions_frame)),
                "target_positions_json_path": str(target_positions_json_path),
            },
        )
        if not target_positions:
            blockers.append("no_target_positions_generated")

        imported_scores_frame = pd.read_parquet(imported_scores_result.research_model_scores_path)
        symbol_lineage, lineage_blockers = _collect_symbol_lineage(
            portfolio_config=portfolio_config,
            imported_scores_frame=imported_scores_frame,
        )
        blockers.extend(lineage_blockers)

        portfolio_run_manifest = read_run_manifest(portfolio_config, resolved_portfolio_run_id)
        lineage = _build_lineage(
            qlib_manifest=qlib_manifest,
            portfolio_run_manifest=portfolio_run_manifest,
            symbol_lineage=symbol_lineage,
            pipeline_config=config,
        )
        evidence_pack["lineage"] = lineage

        bars = _load_backtest_bars(
            portfolio_config=portfolio_config,
            target_positions=target_positions,
        )
        if not bars:
            blockers.append("no_market_bars_loaded_for_backtest")

        risk_config = _build_risk_config(config, portfolio_config)
        unified_result = _run_target_position_backtest(
            pipeline_run_id=config.pipeline_run_id,
            bars=bars,
            target_positions=target_positions,
            risk_config=risk_config,
            data_root=portfolio_config.data_root,
            initial_cash=config.initial_cash,
            commission_rate=config.commission_rate,
            slippage_bps=config.slippage_bps,
            fill_ratio=config.fill_ratio,
            volume_participation_cap_pct=config.volume_participation_cap_pct,
            max_daily_turnover_pct=config.max_daily_turnover_pct,
            data_version=str(lineage.get("primary_data_version", "")),
            strategy_version=str(lineage.get("strategy_version", "")),
        )
        backtest_gate = _evaluate_backtest_gate(
            unified_result=unified_result,
            target_positions=target_positions,
        )
        blockers.extend(backtest_gate["blockers"])
        evidence_pack["risk_gate"].update(backtest_gate["risk_gate"])
        _record_stage(
            evidence_pack,
            "event_driven_backtest",
            status="completed" if not backtest_gate["blockers"] else "failed",
            artifact_path=unified_result.manifest_path,
            details={
                "summary": dict(unified_result.summary),
                "evidence": unified_result.evidence,
                "equity_consistent": unified_result.equity_consistent,
            },
        )

        cost_stress_report = _run_cost_stress_for_targets(
            base_pipeline_run_id=config.pipeline_run_id,
            bars=bars,
            target_positions=target_positions,
            risk_config=risk_config,
            data_root=portfolio_config.data_root,
            initial_cash=config.initial_cash,
            commission_rate=config.commission_rate,
            slippage_bps=config.slippage_bps,
            fill_ratio=config.fill_ratio,
            volume_participation_cap_pct=config.volume_participation_cap_pct,
            max_daily_turnover_pct=config.max_daily_turnover_pct,
            data_version=str(lineage.get("primary_data_version", "")),
            strategy_version=str(lineage.get("strategy_version", "")),
            multipliers=config.cost_stress_multipliers,
            strategy_id=str(config.strategy_id or portfolio_config.strategy_id),
        )
        _write_json(cost_stress_path, cost_stress_report)
        _record_stage(
            evidence_pack,
            "cost_stress",
            status="completed",
            artifact_path=cost_stress_path,
            details=cost_stress_report,
        )

        walk_forward_report = _run_walk_forward_for_targets(
            base_pipeline_run_id=config.pipeline_run_id,
            bars=bars,
            target_positions=target_positions,
            risk_config=risk_config,
            data_root=portfolio_config.data_root,
            initial_cash=config.initial_cash,
            commission_rate=config.commission_rate,
            slippage_bps=config.slippage_bps,
            fill_ratio=config.fill_ratio,
            volume_participation_cap_pct=config.volume_participation_cap_pct,
            max_daily_turnover_pct=config.max_daily_turnover_pct,
            data_version=str(lineage.get("primary_data_version", "")),
            strategy_version=str(lineage.get("strategy_version", "")),
            config=WalkForwardConfig(
                train_bars=config.walk_forward_train_bars,
                test_bars=config.walk_forward_test_bars,
                step_bars=config.walk_forward_step_bars,
                symbols=sorted({target.symbol for target in target_positions}),
                strategy_id=str(config.strategy_id or portfolio_config.strategy_id),
                params={
                    "portfolio_run_id": resolved_portfolio_run_id,
                    "qlib_run_id": config.qlib_run_id,
                },
                data_version=str(lineage.get("primary_data_version", "")),
            ),
        )
        _write_json(walk_forward_path, walk_forward_report)
        _record_stage(
            evidence_pack,
            "walk_forward",
            status="completed" if walk_forward_report["aggregate"]["total_windows"] > 0 else "failed",
            artifact_path=walk_forward_path,
            details=walk_forward_report,
        )
        if int(walk_forward_report["aggregate"]["total_windows"]) <= 0:
            blockers.append("walk_forward_produced_no_windows")

        evidence_pack["artifacts"].update(
            {
                "qlib_strategy_manifest_path": str(qlib_manifest_path),
                "portfolio_run_manifest_path": str(portfolio_config.portfolio_runs_root / resolved_portfolio_run_id / "run_manifest.json"),
                "expected_returns_path": str(expected_returns_output_path),
                "covariance_path": str(covariance_output_path),
                "target_weights_path": str(target_weights_output_path),
                "target_positions_parquet_path": str(target_positions_parquet_path),
                "target_positions_json_path": str(target_positions_json_path),
                "backtest_manifest_path": str(unified_result.manifest_path),
                "backtest_ledger_artifact_path": str(unified_result.evidence.get("ledger_artifact_path", "")),
            }
        )
        evidence_pack["summary"] = {
            "backtest": dict(unified_result.summary),
            "cost_stress": {
                "survival_rate_pct": cost_stress_report["survival_rate_pct"],
                "worst_case_label": cost_stress_report["worst_case_label"],
            },
            "walk_forward": walk_forward_report["aggregate"],
        }
    except Exception as exc:
        error_message = str(exc)
        blockers.append(f"pipeline_exception:{type(exc).__name__}:{exc}")
    finally:
        evidence_pack["gate_blockers"] = list(dict.fromkeys(str(item) for item in blockers if str(item)))
        evidence_pack["status"] = "completed" if not evidence_pack["gate_blockers"] and not error_message else "failed"
        evidence_pack["error"] = error_message

        manifest.update(
            {
                "status": evidence_pack["status"],
                "error": error_message,
                "lineage": evidence_pack.get("lineage", {}),
                "stage_status": evidence_pack.get("stage_status", {}),
                "artifacts": evidence_pack.get("artifacts", {}),
                "risk_gate": evidence_pack.get("risk_gate", {}),
                "gate_blockers": evidence_pack.get("gate_blockers", []),
                "summary": evidence_pack.get("summary", {}),
            }
        )
        _write_json(evidence_pack_path, evidence_pack)
        _write_json(manifest_path, manifest)

    return ResearchExecutionPipelineResult(
        pipeline_run_id=config.pipeline_run_id,
        status=str(evidence_pack["status"]),
        fail_closed=True,
        manifest_path=str(manifest_path),
        evidence_pack_path=str(evidence_pack_path),
        portfolio_run_id=resolved_portfolio_run_id,
        qlib_run_id=config.qlib_run_id,
        error=error_message,
    )


def _build_risk_config(
    pipeline_config: ResearchExecutionPipelineConfig,
    portfolio_config: PortfolioAdapterConfig,
) -> PreTradeRiskConfig:
    return PreTradeRiskConfig(
        max_symbol_weight=(
            pipeline_config.risk_max_symbol_weight
            if pipeline_config.risk_max_symbol_weight is not None
            else portfolio_config.max_weight
        ),
        max_gross_exposure=pipeline_config.risk_max_gross_exposure,
        max_order_notional_pct=pipeline_config.risk_max_order_notional_pct,
        min_cash_buffer_pct=(
            pipeline_config.risk_min_cash_buffer_pct
            if pipeline_config.risk_min_cash_buffer_pct is not None
            else portfolio_config.cash_buffer
        ),
        long_only=pipeline_config.risk_long_only,
        skip_session_check=True,
    )


def _collect_symbol_lineage(
    *,
    portfolio_config: PortfolioAdapterConfig,
    imported_scores_frame: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[str]]:
    manifest_store = DataManifestStore(portfolio_config.data_root / "manifests")
    working = imported_scores_frame.copy()
    if working.empty:
        return [], ["imported_scores_empty"]
    working["symbol"] = working["symbol"].astype(str).str.upper()

    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for symbol in sorted(working["symbol"].drop_duplicates().tolist()):
        score_versions = sorted(
            {
                str(value)
                for value in working.loc[working["symbol"] == symbol, "data_version"].dropna().tolist()
                if str(value)
            }
        )
        manifest = manifest_store.read_latest(portfolio_config.vendor, symbol, portfolio_config.bar_size)
        if manifest is None:
            blockers.append(f"missing_cleaned_data_manifest:{symbol}")
            rows.append(
                {
                    "symbol": symbol,
                    "score_data_versions": score_versions,
                    "manifest_found": False,
                }
            )
            continue

        version_match = not score_versions or manifest.data_version in score_versions
        if not version_match:
            blockers.append(
                f"data_version_mismatch:{symbol}:score={','.join(score_versions)}:cleaned={manifest.data_version}"
            )
        rows.append(
            {
                "symbol": symbol,
                "score_data_versions": score_versions,
                "manifest_found": True,
                "manifest_id": manifest.manifest_id,
                "data_version": manifest.data_version,
                "path": str((portfolio_config.data_root / 'manifests' / f'{manifest.data_version}.json').resolve()),
                "checksum": manifest.effective_checksum,
                "fingerprint": manifest.fingerprint,
                "coverage_pct": manifest.coverage_pct,
                "quality_score": manifest.quality_score,
                "version_match": version_match,
            }
        )
    return rows, blockers


def _build_lineage(
    *,
    qlib_manifest: dict[str, Any],
    portfolio_run_manifest: dict[str, Any],
    symbol_lineage: list[dict[str, Any]],
    pipeline_config: ResearchExecutionPipelineConfig,
) -> dict[str, Any]:
    data_versions = list(
        dict.fromkeys(
            str(item.get("data_version", ""))
            for item in symbol_lineage
            if str(item.get("data_version", ""))
        )
    )
    return {
        "qlib_run_id": pipeline_config.qlib_run_id,
        "portfolio_run_id": portfolio_run_manifest.get("portfolio_run_id", ""),
        "primary_data_version": data_versions[0] if len(data_versions) == 1 else "",
        "data_versions": data_versions,
        "strategy_version": str(qlib_manifest.get("strategy_version", "")),
        "strategy_id": str(qlib_manifest.get("strategy_id", qlib_manifest.get("strategy_version", ""))),
        "params": {
            "qlib": dict(qlib_manifest.get("params", {})),
            "portfolio": dict(portfolio_run_manifest.get("config", {})),
            "walk_forward": {
                "train_bars": pipeline_config.walk_forward_train_bars,
                "test_bars": pipeline_config.walk_forward_test_bars,
                "step_bars": pipeline_config.walk_forward_step_bars,
            },
            "risk": {
                "max_symbol_weight": pipeline_config.risk_max_symbol_weight,
                "max_gross_exposure": pipeline_config.risk_max_gross_exposure,
                "max_order_notional_pct": pipeline_config.risk_max_order_notional_pct,
                "min_cash_buffer_pct": pipeline_config.risk_min_cash_buffer_pct,
                "long_only": pipeline_config.risk_long_only,
            },
        },
        "cost_model": dict(qlib_manifest.get("cost_model", {})),
        "slippage_model": dict(qlib_manifest.get("slippage_model", {})),
        "commit_hash": str(qlib_manifest.get("commit_hash", "")),
        "symbol_manifests": symbol_lineage,
    }


def _load_backtest_bars(
    *,
    portfolio_config: PortfolioAdapterConfig,
    target_positions: list[TargetPosition],
) -> list[Bar]:
    if not target_positions:
        return []
    store = ParquetBarStore(portfolio_config.data_root / "cleaned")
    symbols = sorted({target.symbol for target in target_positions})
    min_timestamp = min(target.timestamp_utc for target in target_positions)
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        frame = store.read_bars(
            vendor=portfolio_config.vendor,
            asset_class=portfolio_config.asset_class,
            bar_size=portfolio_config.bar_size,
            symbol=symbol,
            start=pd.Timestamp(min_timestamp).to_pydatetime(),
            end=utc_now(),
        )
        if frame.empty:
            continue
        working = frame.copy()
        working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        working["symbol"] = working["symbol"].astype(str).str.upper()
        frames.append(working)
    if not frames:
        return []
    combined = pd.concat(frames, ignore_index=True)
    return _bars_from_frame(combined)


def _run_target_position_backtest(
    *,
    pipeline_run_id: str,
    bars: list[Bar],
    target_positions: list[TargetPosition],
    risk_config: PreTradeRiskConfig,
    data_root: Path,
    initial_cash: float,
    commission_rate: float,
    slippage_bps: float,
    fill_ratio: float,
    volume_participation_cap_pct: float,
    max_daily_turnover_pct: float,
    data_version: str,
    strategy_version: str,
):
    runner = UnifiedBacktestRunner(
        config=UnifiedBacktestConfig(
            run_id=f"{pipeline_run_id}_backtest",
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
            fill_ratio=fill_ratio,
            volume_participation_cap_pct=volume_participation_cap_pct,
            max_daily_turnover_pct=max_daily_turnover_pct,
        )
    )
    runner.manifest_store = DataManifestStore(data_root / "manifests")
    return runner.run(
        strategies=[],
        bars_override=bars,
        data_version=data_version,
        strategy_version=strategy_version,
        frame=None,
        features_frame=None,
    ) if not target_positions else _run_with_external_targets(
        runner=runner,
        bars=bars,
        target_positions=target_positions,
        risk_config=risk_config,
        data_version=data_version,
        strategy_version=strategy_version,
    )


def _run_with_external_targets(
    *,
    runner: UnifiedBacktestRunner,
    bars: list[Bar],
    target_positions: list[TargetPosition],
    risk_config: PreTradeRiskConfig,
    data_version: str,
    strategy_version: str,
):
    runner.config = UnifiedBacktestConfig(
        initial_cash=runner.config.initial_cash,
        commission_rate=runner.config.commission_rate,
        slippage_bps=runner.config.slippage_bps,
        fill_ratio=runner.config.fill_ratio,
        volume_participation_cap_pct=runner.config.volume_participation_cap_pct,
        max_daily_turnover_pct=runner.config.max_daily_turnover_pct,
        run_id=runner.config.run_id,
    )
    from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
    from quant_us.backtest.ledger_pnl import (
        build_ledger_reconciliation_artifact_from_records,
        build_reconciliation_report,
        derive_equity_from_fills,
    )
    from quant_us.backtest.turnover import compute_turnover
    from quant_us.backtest.unified_runner import (
        _build_promotion_evidence,
        _git_commit_hash,
        _write_ledger_reconciliation_artifact,
        _write_run_manifest,
    )

    engine = EventDrivenBacktestEngine(
        strategies=[],
        config=BacktestConfig(
            initial_cash=runner.config.initial_cash,
            commission_rate=runner.config.commission_rate,
            slippage_bps=runner.config.slippage_bps,
            run_id=runner.config.run_id,
            risk=risk_config,
            target_positions=tuple(target_positions),
        ),
        calendar=runner.calendar,
        broker=runner._build_broker(),
    )
    event_result = engine.run(bars)

    bar_ref_prices: dict[Any, dict[str, float]] = {}
    for bar in bars:
        bar_ref_prices.setdefault(bar.timestamp_utc, {})[bar.symbol] = bar.close

    running_ref: dict[str, float] = {}
    all_bar_prices: dict[Any, dict[str, float]] = {}
    for timestamp in sorted({bar.timestamp_utc for bar in bars}):
        running_ref.update(bar_ref_prices.get(timestamp, {}))
        all_bar_prices[timestamp] = dict(running_ref)

    ledger_curve = derive_equity_from_fills(
        fills=event_result.fills,
        initial_cash=runner.config.initial_cash,
        market_prices_by_time=all_bar_prices,
    )
    reconciliation_report = build_reconciliation_report(
        event_result.snapshots,
        ledger_curve,
        fills=event_result.fills,
        market_prices_by_time=all_bar_prices,
    )
    ledger_artifact = build_ledger_reconciliation_artifact_from_records(
        order_records=event_result.orders,
        fills=event_result.fills,
        initial_cash=runner.config.initial_cash,
        market_prices_by_time=all_bar_prices,
        snapshots=event_result.snapshots,
    )
    commit_hash = _git_commit_hash()
    evidence = _build_promotion_evidence(
        run_id=runner.config.run_id,
        event_result=event_result,
        ledger_curve=ledger_curve,
        reconciliation_report=reconciliation_report,
        equity_consistent=reconciliation_report.passed,
        equity_consistency_msg=reconciliation_report.message,
        initial_cash=runner.config.initial_cash,
        all_bar_prices=all_bar_prices,
        strategies=[],
        data_version=data_version,
        strategy_version=strategy_version,
        config=runner.config,
        ledger_artifact=ledger_artifact,
        commit_hash=commit_hash,
        manifest_store=runner.manifest_store,
    )
    ledger_artifact_path = _write_ledger_reconciliation_artifact(runner.manifest_store.root, ledger_artifact)
    evidence["ledger_artifact_path"] = str(ledger_artifact_path)
    evidence["completeness"]["ledger_artifact_file_written"] = True

    run_manifest = {
        "manifest_schema_version": "backtest_run_v2",
        "engine": "event_driven",
        "canonical_for_promotion": True,
        "execution_semantics": event_result.metadata.get("execution_semantics", ""),
        "run_id": runner.config.run_id,
        "generated_at": evidence["generated_at"],
        "data_version": data_version,
        "strategy_version": strategy_version,
        "strategy_params": [],
        "commit_hash": commit_hash,
        "ledger_artifact_hash": evidence["ledger_artifact_hash"],
        "ledger_artifact_path": evidence["ledger_artifact_path"],
        "ledger_hash": evidence["ledger_hash"],
        "fills_hash": evidence["fills_hash"],
        "config": {
            "initial_cash": runner.config.initial_cash,
            "commission_rate": runner.config.commission_rate,
            "slippage_bps": runner.config.slippage_bps,
            "fill_ratio": runner.config.fill_ratio,
            "volume_participation_cap_pct": runner.config.volume_participation_cap_pct,
            "max_daily_turnover_pct": runner.config.max_daily_turnover_pct,
            "risk": asdict(risk_config),
            "external_target_position_count": len(target_positions),
        },
        "cost_model": evidence["costs"],
        "commission_model": evidence["commission"],
        "slippage_model": evidence["slippage"],
        "data_manifest_exists": evidence["data_manifest_exists"],
        "missing_data_manifest": evidence["missing_data_manifest"],
        "data_manifest": evidence["data_manifest"],
        "reconciliation": evidence["reconciliation"]["summary"],
        "ledger_artifact": evidence["ledger_artifact"],
        "corporate_actions": evidence["corporate_actions"]["digest"],
        "evidence": evidence,
    }
    manifest_path = _write_run_manifest(runner.manifest_store.root, runner.config.run_id, run_manifest)
    turnover_report = compute_turnover(
        fills=event_result.fills,
        equity_curve=ledger_curve.equity_series,
        max_daily_turnover_pct=runner.config.max_daily_turnover_pct,
    )
    from quant_us.backtest.unified_runner import UnifiedBacktestResult

    return UnifiedBacktestResult(
        run_id=runner.config.run_id,
        event_driven=event_result,
        ledger_curve=ledger_curve,
        equity_consistent=reconciliation_report.passed,
        equity_consistency_msg=reconciliation_report.message,
        data_version=data_version,
        strategy_version=strategy_version,
        manifest_id=runner.config.run_id,
        turnover_report=turnover_report,
        determinism_verified=False,
        determinism_details=None,
        evidence=evidence,
        manifest_path=str(manifest_path),
    )


def _evaluate_backtest_gate(
    *,
    unified_result,
    target_positions: list[TargetPosition],
) -> dict[str, Any]:
    event_metadata = dict(unified_result.event_driven.metadata)
    risk = dict(unified_result.evidence.get("risk", {}))
    blockers: list[str] = []
    if int(risk.get("risk_check_count", 0)) <= 0:
        blockers.append("no_risk_checks_observed")
    if int(risk.get("rejected", 0)) > 0:
        blockers.append(f"risk_gate_rejections:{int(risk['rejected'])}")
    if not bool(unified_result.evidence.get("orders", {}).get("all_orders_have_risk_check_id", False)):
        blockers.append("orders_missing_risk_check_id")
    if int(event_metadata.get("external_target_positions_consumed", 0)) != len(target_positions):
        blockers.append(
            f"external_target_positions_not_fully_consumed:{event_metadata.get('external_target_positions_consumed', 0)}/{len(target_positions)}"
        )
    if int(event_metadata.get("pending_intent_count", 0)) > 0:
        blockers.append(f"pending_order_intents:{int(event_metadata['pending_intent_count'])}")
    if not unified_result.equity_consistent:
        blockers.append("ledger_equity_inconsistent")

    risk_events = [
        event
        for event in unified_result.event_driven.events
        if isinstance(event, RiskEvent)
    ]
    return {
        "blockers": blockers,
        "risk_gate": {
            "risk_check_count": int(risk.get("risk_check_count", 0)),
            "approved": int(risk.get("approved", 0)),
            "rejected": int(risk.get("rejected", 0)),
            "rejection_reasons": dict(risk.get("rejection_reasons", {})),
            "all_orders_have_risk_check_id": bool(
                unified_result.evidence.get("orders", {}).get("all_orders_have_risk_check_id", False)
            ),
            "external_target_positions_consumed": int(
                event_metadata.get("external_target_positions_consumed", 0)
            ),
            "external_target_position_count": len(target_positions),
            "pending_intent_count": int(event_metadata.get("pending_intent_count", 0)),
            "risk_event_count": len(risk_events),
        },
    }


def _run_cost_stress_for_targets(
    *,
    base_pipeline_run_id: str,
    bars: list[Bar],
    target_positions: list[TargetPosition],
    risk_config: PreTradeRiskConfig,
    data_root: Path,
    initial_cash: float,
    commission_rate: float,
    slippage_bps: float,
    fill_ratio: float,
    volume_participation_cap_pct: float,
    max_daily_turnover_pct: float,
    data_version: str,
    strategy_version: str,
    multipliers: tuple[tuple[float, float, str], ...],
    strategy_id: str,
) -> dict[str, Any]:
    levels: list[dict[str, Any]] = []
    survived = 0
    baseline_return = 0.0
    baseline_sharpe = 0.0

    for index, (commission_mult, slippage_mult, label) in enumerate(multipliers):
        result = _run_target_position_backtest(
            pipeline_run_id=f"{base_pipeline_run_id}_cost_{index}",
            bars=bars,
            target_positions=target_positions,
            risk_config=risk_config,
            data_root=data_root,
            initial_cash=initial_cash,
            commission_rate=commission_rate * commission_mult,
            slippage_bps=slippage_bps * slippage_mult,
            fill_ratio=fill_ratio,
            volume_participation_cap_pct=volume_participation_cap_pct,
            max_daily_turnover_pct=max_daily_turnover_pct,
            data_version=data_version,
            strategy_version=strategy_version,
        )
        risk = dict(result.evidence.get("risk", {}))
        level = {
            "label": label,
            "commission_multiplier": commission_mult,
            "slippage_multiplier": slippage_mult,
            "commission_rate": commission_rate * commission_mult,
            "slippage_bps": slippage_bps * slippage_mult,
            "total_return_pct": float(result.summary.get("total_return_pct", 0.0)),
            "sharpe_ratio": float(result.summary.get("sharpe_ratio", 0.0)),
            "max_drawdown_pct": float(result.summary.get("max_drawdown_pct", 0.0)),
            "trade_count": int(result.summary.get("trade_count", 0)),
            "equity_consistent": bool(result.equity_consistent),
            "risk_rejected": int(risk.get("rejected", 0)),
            "pending_intent_count": int(result.event_driven.metadata.get("pending_intent_count", 0)),
            "manifest_path": result.manifest_path,
        }
        if index == 0:
            baseline_return = level["total_return_pct"]
            baseline_sharpe = level["sharpe_ratio"]

        level["return_decay_pct"] = round(
            ((baseline_return - level["total_return_pct"]) / abs(baseline_return) * 100.0)
            if abs(baseline_return) > 1e-9
            else 0.0,
            4,
        )
        level["sharpe_decay"] = round(baseline_sharpe - level["sharpe_ratio"], 4)
        level["survives"] = (
            level["equity_consistent"]
            and level["risk_rejected"] == 0
            and level["pending_intent_count"] == 0
        )
        if level["survives"]:
            survived += 1
        levels.append(level)

    return {
        "strategy_id": strategy_id,
        "engine": "event_driven",
        "risk_gate_enforced": True,
        "levels": levels,
        "baseline": levels[0] if levels else {},
        "survival_rate_pct": round(survived / len(levels) * 100.0, 2) if levels else 0.0,
        "worst_case_label": levels[-1]["label"] if levels else "",
    }


def _run_walk_forward_for_targets(
    *,
    base_pipeline_run_id: str,
    bars: list[Bar],
    target_positions: list[TargetPosition],
    risk_config: PreTradeRiskConfig,
    data_root: Path,
    initial_cash: float,
    commission_rate: float,
    slippage_bps: float,
    fill_ratio: float,
    volume_participation_cap_pct: float,
    max_daily_turnover_pct: float,
    data_version: str,
    strategy_version: str,
    config: WalkForwardConfig,
) -> dict[str, Any]:
    windows = build_walk_forward_windows(bars, config)
    timestamps = sorted({bar.timestamp_utc for bar in bars})
    results: list[UnifiedWalkForwardResult] = []

    for index, window in enumerate(windows):
        window_targets = [
            target
            for target in target_positions
            if window.test_start <= target.timestamp_utc <= window.test_end
        ]
        if not window_targets:
            continue
        execution_end = _execution_buffer_end(window, timestamps)
        window_bars = [
            bar
            for bar in bars
            if window.test_start <= bar.timestamp_utc <= execution_end
        ]
        if not window_bars:
            continue
        unified = _run_target_position_backtest(
            pipeline_run_id=f"{base_pipeline_run_id}_wf_{index}",
            bars=window_bars,
            target_positions=window_targets,
            risk_config=risk_config,
            data_root=data_root,
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
            fill_ratio=fill_ratio,
            volume_participation_cap_pct=volume_participation_cap_pct,
            max_daily_turnover_pct=max_daily_turnover_pct,
            data_version=data_version,
            strategy_version=strategy_version,
        )
        results.append(UnifiedWalkForwardResult(window=window, unified=unified))

    aggregate = aggregate_walk_forward(results, symbols=config.symbols)
    return {
        "config": asdict(config),
        "aggregate": {
            "total_windows": aggregate.total_windows,
            "windows_consistent": aggregate.windows_consistent,
            "all_trustworthy": aggregate.all_trustworthy,
            "oos_total_return_pct": aggregate.oos_total_return_pct,
            "oos_avg_sharpe": aggregate.oos_avg_sharpe,
            "oos_avg_max_dd": aggregate.oos_avg_max_dd,
            "oos_win_rate": aggregate.oos_win_rate,
            "oos_avg_turnover_pct": aggregate.oos_avg_turnover_pct,
            "fold_pass_rate_pct": aggregate.fold_pass_rate_pct,
            "symbol_coverage_pct": aggregate.symbol_coverage_pct,
            "symbols_tested": aggregate.symbols_tested,
            "insufficient_data": aggregate.insufficient_data,
        },
        "windows": [
            {
                "train_start": item.window.train_start.isoformat(),
                "train_end": item.window.train_end.isoformat(),
                "test_start": item.window.test_start.isoformat(),
                "test_end": item.window.test_end.isoformat(),
                "manifest_path": item.unified.manifest_path,
                "equity_consistent": item.unified.equity_consistent,
                "summary": dict(item.unified.summary),
            }
            for item in results
        ],
    }


def _execution_buffer_end(window: WalkForwardWindow, timestamps: list[Any]):
    for timestamp in timestamps:
        if timestamp > window.test_end:
            return timestamp
    return window.test_end


def _target_positions_from_frame(frame: pd.DataFrame) -> list[TargetPosition]:
    if frame.empty:
        return []
    working = frame.copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
    rows: list[TargetPosition] = []
    for row in working.to_dict(orient="records"):
        metadata = _parse_metadata_json(row.get("metadata_json", ""))
        rows.append(
            TargetPosition(
                timestamp_utc=pd.Timestamp(row["timestamp_utc"]).to_pydatetime(),
                strategy_id=str(row["strategy_id"]),
                symbol=str(row["symbol"]),
                target_weight=float(row["target_weight"]),
                target_quantity=(
                    None
                    if pd.isna(row.get("target_quantity"))
                    else float(row["target_quantity"])
                ),
                signal_id=str(row.get("signal_id", "")),
                metadata=metadata,
                target_position_id=str(row["target_position_id"]),
            )
        )
    return rows


def _bars_from_frame(frame: pd.DataFrame) -> list[Bar]:
    working = frame.copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
    working = working.sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)
    return [
        Bar(
            timestamp_utc=pd.Timestamp(row["timestamp_utc"]).to_pydatetime(),
            symbol=str(row["symbol"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0)),
            source=str(row.get("source", "")),
            bar_size=str(row.get("bar_size", "")),
        )
        for row in working.to_dict(orient="records")
    ]


def _parse_metadata_json(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    text = str(value).strip()
    if not text:
        return {}
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _record_stage(
    evidence_pack: dict[str, Any],
    name: str,
    *,
    status: str,
    artifact_path: str | Path,
    details: dict[str, Any],
) -> None:
    evidence_pack["stage_status"][name] = {
        "status": status,
        "artifact_path": str(artifact_path),
        "details": details,
    }


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chain Qlib score import, PyPortfolioOpt target weights, risk-gated backtest, cost stress, walk-forward, and evidence packaging."
    )
    parser.add_argument("--qlib-run-id", required=True, help="Qlib run id under artifacts/qlib_runs/<run_id>/")
    parser.add_argument("--qlib-config", required=True, help="Qlib workflow config used to compile lineage manifest.")
    parser.add_argument("--portfolio-config", required=True, help="PyPortfolioOpt portfolio config yaml path.")
    parser.add_argument("--pipeline-run-id", default="", help="Optional explicit pipeline run id.")
    parser.add_argument("--portfolio-run-id", default="", help="Optional explicit portfolio run id.")
    parser.add_argument("--strategy-id", default="", help="Optional strategy id override for imported target positions.")
    parser.add_argument("--qlib-runs-root", default="artifacts/qlib_runs", help="Qlib runs root.")
    parser.add_argument("--portfolio-runs-root", default="artifacts/portfolio_runs", help="Portfolio runs root.")
    parser.add_argument("--pipeline-runs-root", default="artifacts/research_execution_runs", help="Pipeline runs root.")
    parser.add_argument("--initial-cash", type=float, default=100_000.0, help="Backtest initial cash.")
    parser.add_argument("--commission-rate", type=float, default=0.0001, help="Baseline commission rate.")
    parser.add_argument("--slippage-bps", type=float, default=1.0, help="Baseline slippage in bps.")
    parser.add_argument("--fill-ratio", type=float, default=1.0, help="Simulated fill ratio.")
    parser.add_argument(
        "--volume-participation-cap-pct",
        type=float,
        default=5.0,
        help="Simulated volume participation cap percent.",
    )
    parser.add_argument(
        "--max-daily-turnover-pct",
        type=float,
        default=200.0,
        help="Backtest turnover alert threshold percent.",
    )
    parser.add_argument("--risk-max-symbol-weight", type=float, default=None, help="Optional pre-trade risk symbol weight cap.")
    parser.add_argument("--risk-max-gross-exposure", type=float, default=1.0, help="Pre-trade risk gross exposure cap.")
    parser.add_argument("--risk-max-order-notional-pct", type=float, default=0.10, help="Pre-trade max order notional as equity percent.")
    parser.add_argument("--risk-min-cash-buffer-pct", type=float, default=None, help="Optional pre-trade cash buffer percent.")
    parser.add_argument("--wf-train-bars", type=int, default=252, help="Walk-forward train window size in unique bars.")
    parser.add_argument("--wf-test-bars", type=int, default=63, help="Walk-forward test window size in unique bars.")
    parser.add_argument("--wf-step-bars", type=int, default=63, help="Walk-forward step size in unique bars.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_research_execution_pipeline(
        ResearchExecutionPipelineConfig(
            qlib_run_id=args.qlib_run_id,
            qlib_config_path=args.qlib_config,
            portfolio_config_path=args.portfolio_config,
            pipeline_run_id=args.pipeline_run_id or new_id("rpipe"),
            portfolio_run_id=args.portfolio_run_id,
            strategy_id=args.strategy_id,
            qlib_runs_root=Path(args.qlib_runs_root),
            portfolio_runs_root=Path(args.portfolio_runs_root),
            pipeline_runs_root=Path(args.pipeline_runs_root),
            initial_cash=args.initial_cash,
            commission_rate=args.commission_rate,
            slippage_bps=args.slippage_bps,
            fill_ratio=args.fill_ratio,
            volume_participation_cap_pct=args.volume_participation_cap_pct,
            max_daily_turnover_pct=args.max_daily_turnover_pct,
            risk_max_symbol_weight=args.risk_max_symbol_weight,
            risk_max_gross_exposure=args.risk_max_gross_exposure,
            risk_max_order_notional_pct=args.risk_max_order_notional_pct,
            risk_min_cash_buffer_pct=args.risk_min_cash_buffer_pct,
            walk_forward_train_bars=args.wf_train_bars,
            walk_forward_test_bars=args.wf_test_bars,
            walk_forward_step_bars=args.wf_step_bars,
        )
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
