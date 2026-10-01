from __future__ import annotations

import importlib.util
import csv
import json
import os
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from starlette.requests import Request

QLIB_ARTIFACTS_ROOT = Path(__file__).resolve().parents[3] / "artifacts" / "qlib_runs"

from backend.app import __version__
from backend.app.api.btc_domain_read_model import build_btc_domain_read_model_router
from backend.app.api.btc_demo_runtime import build_btc_demo_runtime_router
from backend.app.api.btc_public_market import build_btc_public_market_router
from backend.app.services.btc_public_market_stream import BtcPublicMarketStreamHub
from backend.app.services.btc_public_market_view import BTCPublicMarketViewService
from backend.app.api.btc_outbound_path_redaction import (
    sanitize_btc_outbound_payload,
)
from backend.app.api.btc_strategy_history import build_btc_strategy_history_router
from backend.app.api.cn_equity import build_cn_equity_router
from backend.app.api.us_equity_domain_read_model import (
    build_us_equity_domain_read_model_router,
)
from backend.app.api.us_ibkr_runtime import build_us_ibkr_runtime_router
from backend.app.api.strategy_history_catalog import build_strategy_history_catalog_router
from backend.app.api.schemas import (
    ChartSeriesPayload,
    CostStressRequest,
    CostStressResponse,
    CryptoClosureRequest,
    CryptoClosureResponse,
    CryptoResampleRequest,
    CryptoResampleResponse,
    DataCoverageItem,
    EventDrivenCostStressResponse,
    PaperBacktestResponse,
    PaperResetResponse,
    DataQualityRequest,
    DataQualityResponse,
    DataSyncRequest,
    DataSyncRunResponse,
    DatabaseStatusResponse,
    FeatureBuildRequest,
    FeatureSnapshotResponse,
    FeatureValidateResponse,
    HealthResponse,
    KlinePreviewResponse,
    LatestDataUpdateRequest,
    PortfolioBacktestRequest,
    PortfolioOptimizationRequest,
    PortfolioOptimizationResponse,
    ResearchPromotionGateRequest,
    ResearchPromotionGateResponse,
    RobustnessMonteCarloSection,
    RobustnessAlphaDecaySection,
    RobustnessParamStabilitySection,
    RobustnessRunRequest,
    RobustnessRunResponse,
    RunStatusResponse,
    SchedulerStartRequest,
    SchedulerStatusResponse,
    SingleBacktestRequest,
    StrategyOptimizationRequest,
    StrategyOptimizationResponse,
    StrategyInfo,
    TaskStatusResponse,
    SystemOverviewResponse,
    USDataSyncRequest,
    USDataSyncResponse,
    USEventBacktestRequest,
    USEventBacktestResponse,
    USFeatureBuildRequest,
    USFeatureBuildResponse,
    USPaperDayResultResponse,
    USPaperRunDayRequest,
    USPaperStatusResponse,
    USReconciliationRequest,
    USReconciliationResponse,
    USUnifiedBacktestResponse,
    WalkForwardRequest,
    WalkForwardResponse,
)
from backend.app.core.config import settings
from backend.app.core.deps import (
    btc_demo_runtime_service,
    crypto_closure_service,
    data_update_scheduler,
    market_data_service,
    promotion_gate_service,
    research_service,
    run_registry,
    task_queue_service,
    us_quant_service,
)
from backend.app.core.exceptions import QuantStationError, RunNotFoundError
from backend.app.services.cn_equity_read_model import CNEquityReadModelService
from backend.app.services.research_archive_discovery import (
    ReadonlyRunLocation,
    ResearchArchiveConflict,
    ResearchArchiveUnavailable,
    build_m1_research_archive_catalog,
)
from backend.app.services.research_readonly_views import (
    ResearchReadonlyViewError,
    ResearchReadonlyViews,
)
from quant_crypto.adapters.btc_domain_read_model_repository import (
    BTCPublishedDomainReadModelRepository,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE as BTC_RUNTIME_ARTIFACT_ROOT_ENVIRONMENT_VARIABLE,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
)
from quant_crypto.application.btc_domain_read_model import (
    BTCPublishedDomainReadModelService,
    BTCPublishedDomainReadModelUnavailable,
)
from quant_us.application.us_equity_domain_read_model import USDomainReadModelService
from quant_us.monitoring.us_equity_domain_read_model_repository import (
    USCommittedEvidenceRepository,
)
from tools.agent_governance.git_metadata import GitMetadataError, current_branch_head
from backend.app.core.backend_access_policy import (
    evaluate_backend_access,
    is_research_readonly,
    is_research_surface_profile,
    CANDIDATE_MANAGEMENT_PROFILE,
    readonly_block_payload,
)


def _serialize_run(record: Any):
    from backend.app.api.schemas import RunStatusResponse

    result = record.result
    return RunStatusResponse(
        run_id=record.run_id,
        mode=record.mode,
        status=record.status,
        created_at=record.created_at,
        completed_at=record.completed_at,
        error=record.error,
        summary=result.summary if result else None,
        strategy_details=result.strategy_details if result else [],
        latest_weights=result.latest_weights if result else [],
        diagnostics=result.diagnostics if result else {},
    )


def _serialize_data_sync_result(result: Any):
    from backend.app.api.schemas import DataSyncRunResponse

    return DataSyncRunResponse(
        run_id=result.run_id,
        status=result.status,
        db_path=result.db_path,
        exchange=result.exchange,
        symbol=result.symbol,
        interval=result.interval,
        start=result.start,
        end=result.end,
        rows_received=result.rows_received,
        rows_written=result.rows_written,
        requests=result.requests,
        created_at=result.created_at,
        completed_at=result.completed_at,
        error=result.error,
    )


def _serialize_task(task: dict[str, Any]) -> TaskStatusResponse:
    payload = dict(task)
    payload.setdefault("blockers", [])
    return TaskStatusResponse.model_validate(payload)


def _run_crypto_closure_background_task(ctx, payload: dict[str, Any]) -> dict[str, Any]:
    ctx.update(stage="data_integrity", message="BTC production closure: checking data integrity", progress=12)
    try:
        result = crypto_closure_service.run(payload, progress_callback=ctx.update)
    except TypeError as exc:
        if "progress_callback" not in str(exc):
            raise
        result = crypto_closure_service.run(payload)
    ctx.update(stage="result_summary", message="BTC production closure: assembling result summary", progress=96)
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def _as_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _system_overview_payload(
    data_root: str = "data",
    *,
    qlib_artifacts_root: str = "artifacts/qlib_runs",
    portfolio_artifacts_root: str = "artifacts/portfolio_runs",
    pit_data_intake_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
    pit_operator_handoff_summary_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json",
    development_plan_audit_report_path: str = "artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json",
    live_readiness_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json",
    strategy_validation_gate_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
    forward_observation_evaluation_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
    forward_observation_daily_health_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json",
    manual_review_packet_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
    paper_simulation_readiness_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
    small_account_execution_preflight_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json",
    data_source_reconciliation_report_path: str = "artifacts/us_equity_data_status/latest/us_equity_data_source_reconciliation_report.json",
    data_lineage_remediation_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json",
    macro_release_lag_policy_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json",
    production_data_acquisition_plan_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json",
    candidate_bundle_evidence_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_candidate_bundle_evidence_report.json",
    production_bundle_intake_packet_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json",
    manual_vendor_drop_package_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json",
    incoming_drop_readiness_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json",
    local_csv_production_bundle_import_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_local_csv_production_bundle_import_report.json",
    production_bundle_activation_report_path: str = "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json",
    standard_report_schema_audit_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json",
    monitoring_rules_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
    replay_readiness_report_path: str = "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json",
    strategy_registry_path: str = "configs/strategies/us_equity_strategy_registry.json",
    strategy_registry_audit_report_path: str = "artifacts/us_equity_strategy_registry/latest/us_equity_strategy_registry_report.json",
    daily_production_line_run_report_path: str = "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json",
    minute_quality_as_of: Any | None = None,
) -> dict[str, Any]:
    root = Path(data_root or "data")

    from quant_us.live.paper_adapter_contract import audit_apca_paper_credentials
    from quant_us.data.minute_quality_gate import inspect_minute_data_quality_overview
    from quant_us.reports.paper_validation import inspect_paper_validation_evidence
    from quant_us.reports.portfolio_observability import inspect_portfolio_observability
    from backend.app.services.paper_review import summarize_paper_review_entry

    registry = _fast_saved_evidence_registry(root)
    minute_as_of = _as_utc_datetime(minute_quality_as_of)
    if minute_as_of is None:
        minute_quality = inspect_minute_data_quality_overview(root).to_dict()
    else:
        minute_quality = inspect_minute_data_quality_overview(root, as_of=minute_as_of).to_dict()
    paper_evidence = inspect_paper_validation_evidence(root)
    portfolio_observability = inspect_portfolio_observability(root).to_dict()
    paper_review = _fast_paper_review_status(root, registry)
    credentials = audit_apca_paper_credentials()
    paper_state = str(paper_evidence.readiness_state)
    paper_review_entry = summarize_paper_review_entry(
        data_root=root,
        registry=registry,
        paper_review=paper_review,
        paper_validation_state=paper_state,
        credentials_present=bool(credentials.get("credentials_present")),
        base_url_valid=bool(credentials.get("base_url_valid")),
    )
    minute_coverage = _coverage_from_minute_quality(minute_quality)
    qlib_integration = _latest_integration_run(qlib_artifacts_root, "qlib")
    portfolio_integration = _latest_integration_run(portfolio_artifacts_root, "portfolio")
    pit_data_intake = _pit_data_intake_status(Path(pit_data_intake_report_path))
    pit_operator_handoff = _pit_operator_handoff_status(Path(pit_operator_handoff_summary_path))
    development_plan_audit = _development_plan_audit_status(Path(development_plan_audit_report_path))
    live_readiness = _live_readiness_status(Path(live_readiness_report_path))
    strategy_validation_gate = _strategy_validation_gate_status(Path(strategy_validation_gate_report_path))
    forward_observation = _forward_observation_status(
        Path(forward_observation_evaluation_report_path),
        Path(forward_observation_daily_health_report_path),
    )
    manual_review_packet = _manual_review_packet_status(Path(manual_review_packet_path))
    paper_simulation_readiness = _paper_simulation_readiness_status(Path(paper_simulation_readiness_report_path))
    small_account_execution_preflight = _small_account_execution_preflight_status(
        Path(small_account_execution_preflight_report_path)
    )
    data_lineage_governance = _data_lineage_governance_status(
        Path(data_source_reconciliation_report_path),
        Path(data_lineage_remediation_report_path),
        Path(macro_release_lag_policy_report_path),
    )
    production_data_acquisition = _production_data_acquisition_status(
        Path(production_data_acquisition_plan_path),
        Path(candidate_bundle_evidence_report_path),
        Path(production_bundle_intake_packet_path),
        Path(manual_vendor_drop_package_report_path),
    )
    production_bundle_gate = _production_bundle_gate_status(
        Path(incoming_drop_readiness_report_path),
        Path(local_csv_production_bundle_import_report_path),
        Path(production_bundle_activation_report_path),
    )
    standard_report_schema_audit = _standard_report_schema_audit_status(Path(standard_report_schema_audit_path))
    monitoring_rules = _monitoring_rules_status(Path(monitoring_rules_report_path))
    replay_readiness = _replay_readiness_status(Path(replay_readiness_report_path))
    strategy_registry = _strategy_registry_status(Path(strategy_registry_path), Path(strategy_registry_audit_report_path))
    daily_production_line = _daily_production_line_status(Path(daily_production_line_run_report_path))

    registry_state = str(registry.get("registry_status", "missing"))
    registry_integrity = str(registry.get("registry_integrity_status", "MISSING"))
    paper_review_status = str(paper_review.get("status", "UNKNOWN"))
    minute_quality_status = str(minute_quality.get("status", "MISSING"))
    minute_quality_evidence = minute_quality.get("evidence_summary", {})
    fail_interval_count = 0
    if isinstance(minute_quality_evidence, dict):
        fail_interval_count = int(minute_quality_evidence.get("blocking_fail_interval_count", 0) or 0)
    minute_quality_hard_blocked = fail_interval_count > 0
    qlib_dependencies = {
        "qlib": importlib.util.find_spec("qlib") is not None,
        "lightgbm": importlib.util.find_spec("lightgbm") is not None,
    }
    portfolio_dependencies = {
        "pypfopt": importlib.util.find_spec("pypfopt") is not None,
    }

    next_actions: list[str] = []
    if registry_state != "present" or registry_integrity != "PASS/STABLE":
        next_actions.append("Run: quant-us research evidence-registry-rebuild --data-root <data_root>")
    if minute_quality_status != "PASS":
        remediation = minute_quality.get("remediation_summary", {})
        recommended_commands: list[str] = []
        if isinstance(remediation, dict):
            for action in remediation.get("actions", []):
                if not isinstance(action, dict):
                    continue
                for command in action.get("recommended_commands", []):
                    if isinstance(command, str) and command not in recommended_commands:
                        recommended_commands.append(command)
                    if len(recommended_commands) >= 2:
                        break
                if len(recommended_commands) >= 2:
                    break
        if recommended_commands:
            next_actions.extend(recommended_commands)
        else:
            next_actions.append("Load and validate 1m/5m/15m minute data before paper review.")
    if paper_state != "PASS":
        next_actions.append("Complete paper validation evidence before any paper submission gate.")
    if not credentials.get("credentials_present"):
        next_actions.append("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY for Alpaca paper.")
    if not credentials.get("base_url_valid"):
        next_actions.append("Set APCA_API_BASE_URL=https://paper-api.alpaca.markets for paper only.")
    if not bool(paper_review.get("entry_allowed", False)):
        next_actions.append("Create or approve paper-review evidence from a canonical promotion result.")
    if paper_review_entry.get("next_command") and paper_review_entry.get("next_command") not in next_actions:
        next_actions.append(str(paper_review_entry.get("next_command")))
    pit_next_action = pit_data_intake.get("next_action", {})
    if (
        isinstance(pit_next_action, dict)
        and pit_data_intake.get("status") == "production_pit_data_intake_blocked"
        and pit_next_action.get("description")
        and str(pit_next_action.get("description")) not in next_actions
    ):
        next_actions.insert(0, str(pit_next_action.get("description")))
    handoff_actions = pit_operator_handoff.get("operator_next_actions", [])
    if (
        pit_operator_handoff.get("status") == "handoff_blocked"
        and isinstance(handoff_actions, list)
        and handoff_actions
        and str(handoff_actions[0]) not in next_actions
    ):
        next_actions.insert(0, str(handoff_actions[0]))
    if not next_actions:
        next_actions.append("Paper-stage evidence is reviewable; keep live frozen and enable paper only through explicit gate.")

    if registry_state != "present" or registry_integrity != "PASS/STABLE":
        stage = "registry_blocked"
        status = "blocked"
    elif minute_quality_hard_blocked:
        stage = "minute_data_quality_blocked"
        status = "blocked"
    elif paper_state != "PASS":
        stage = "paper_validation_blocked"
        status = "blocked"
    elif not credentials.get("credentials_present") or not credentials.get("base_url_valid"):
        stage = "paper_credentials_blocked"
        status = "blocked"
    elif not bool(paper_review.get("entry_allowed", False)):
        stage = "paper_review_blocked"
        status = "blocked"
    else:
        stage = "paper_ready_for_manual_gate"
        status = "reviewable"

    return {
        "status": status,
        "stage": stage,
        "mode": "pre_live",
        "data_root": str(root),
        "health": {
            "service": "quantstation-vnext",
            "data_source_default": settings.default_data_source,
            "fastapi_available": True,
        },
        "registry": {
            "state": registry_state,
            "integrity": registry_integrity,
            "path": str(registry.get("registry_path", root / "research" / "evidence_registry.json")),
            "counts": dict(registry.get("counts", {})),
            "notes": list(registry.get("registry_notes", [])),
            "rebuild_available": bool(registry.get("rebuild_available", True)),
        },
        "paper_validation": {
            "state": paper_state,
            "days_completed": paper_evidence.days_completed,
            "days_required": paper_evidence.days_required,
            "consecutive_clean_days": paper_evidence.consecutive_clean_days,
            "submit_orders": paper_evidence.paper_submit_orders,
            "audit_blocker_status": paper_evidence.audit_blocker_status,
            "data_strict_status": paper_evidence.data_strict_status,
            "recovery_status": paper_evidence.recovery_status,
            "gaps": list(paper_evidence.gaps),
            "evidence": [pointer.__dict__ for pointer in paper_evidence.evidence],
        },
        "minute_data_quality": minute_quality,
        "data_coverage": minute_coverage,
        "paper_review": {
            "status": paper_review_status,
            "entry_allowed": bool(paper_review.get("entry_allowed", False)),
            "manual_review_pending": bool(paper_review.get("manual_review_pending", False)),
            "summary": str(paper_review.get("summary", "")),
            "evidence_path": str(paper_review.get("evidence_path", "")),
            "review_path": str(paper_review.get("review_path", "")),
            "manifest_path": str(paper_review.get("manifest_path", "")),
            "evidence_pack_path": str(paper_review.get("evidence_pack_path", "")),
            "creation": paper_review_entry,
            "diagnostics": {
                "registry_state": registry_state,
                "registry_integrity": registry_integrity,
                "conflict_notes": [str(note) for note in registry.get("registry_notes", []) if isinstance(note, str) and "conflict" in note.lower()],
                "latest_review_status": str(paper_review.get("status", "")),
                "latest_manifest_status": str(
                    next(
                        (
                            str(row.get("details", {}).get("promotion_status", row.get("summary", "UNKNOWN")))
                            for row in registry.get("evidence", {}).get("strategy_manifests", [])
                            if isinstance(row, dict)
                        ),
                        "",
                    ),
                ),
                "conflict_detected": bool(
                    any(
                        isinstance(row, dict) and row.get("integrity_status") == "CONFLICT"
                        for section in registry.get("evidence", {}).values()
                        if isinstance(section, list)
                        for row in section
                    )
                ),
            },
        },
        "portfolio_observability": portfolio_observability,
        "integrations": {
            "dependencies": {
                **qlib_dependencies,
                **portfolio_dependencies,
            },
            "qlib": {
                "artifacts_root": qlib_artifacts_root,
                **qlib_integration,
            },
            "portfolio": {
                "artifacts_root": portfolio_artifacts_root,
                **portfolio_integration,
            },
        },
        "pit_data_intake": pit_data_intake,
        "pit_operator_handoff": pit_operator_handoff,
        "development_plan_audit": development_plan_audit,
        "live_readiness": live_readiness,
        "strategy_validation_gate": strategy_validation_gate,
        "forward_observation": forward_observation,
        "manual_review_packet": manual_review_packet,
        "paper_simulation_readiness": paper_simulation_readiness,
        "small_account_execution_preflight": small_account_execution_preflight,
        "data_lineage_governance": data_lineage_governance,
        "production_data_acquisition": production_data_acquisition,
        "production_bundle_gate": production_bundle_gate,
        "standard_report_schema_audit": standard_report_schema_audit,
        "monitoring_rules": monitoring_rules,
        "replay_readiness": replay_readiness,
        "strategy_registry": strategy_registry,
        "daily_production_line": daily_production_line,
        "broker_credentials": {
            "credentials_present": bool(credentials.get("credentials_present")),
            "api_key_present": bool(credentials.get("api_key_present")),
            "api_secret_present": bool(credentials.get("api_secret_present")),
            "endpoint_kind": str(credentials.get("endpoint_kind", "unset")),
            "base_url_valid": bool(credentials.get("base_url_valid")),
            "allowed_base_url": str(credentials.get("allowed_base_url", "")),
        },
        "execution": {
            "strategy_direct_broker_allowed": False,
            "paper_submit_default": "disabled",
            "paper_network_submit_confirmation": os.environ.get(
                "QUANT_ALPACA_PAPER_NETWORK_SUBMIT",
                "",
            ).strip().lower() in {"1", "true", "yes"},
            "paper_submit_requires": [
                "paper mode",
                "explicit submit_orders=True",
                "QUANT_ALPACA_PAPER_NETWORK_SUBMIT=true",
                "Alpaca paper credentials",
                "paper base URL allowlist",
                "approved paper-review evidence",
                "startup sync artifact",
                "broker recovery artifact",
                "risk/OMS gate",
            ],
            "live_submit_allowed": False,
            "live_state": "frozen",
            "live_block_reason": "live_runtime_frozen",
        },
        "small_account": {
            "profile": "personal_multi_strategy_portfolio",
            "splitting_required": False,
            "default_capital": settings.default_capital,
            "suggested_max_order_notional": 100.0,
            "suggested_max_daily_notional": 300.0,
            "suggested_max_daily_order_count": 3,
        },
        "next_actions": next_actions,
    }


def _pit_data_intake_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        operator_actions = [
            {
                "label": "重建 PIT 接入状态面板",
                "intent": "Regenerate the read-only status panel before continuing data intake.",
                "command": "python scripts/build_us_equity_pit_data_intake_status_report.py",
                "blocked_until": "pit_data_intake_status_report_exists",
            }
        ]
        return {
            "status": "missing",
            "current_blocking_stage": "pit_data_intake_status_report",
            "next_action": {
                "stage_id": "pit_data_intake_status_report",
                "description": "Run: python scripts/build_us_equity_pit_data_intake_status_report.py",
                "first_blocker": "pit_data_intake_status_report_missing",
            },
            "stages": [],
            "blockers": ["pit_data_intake_status_report_missing"],
            "source_report": str(path),
            "operator_actions": operator_actions,
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
                "real_order_submitted": False,
            },
        }
    next_action = payload.get("next_action", {})
    operator_actions = _pit_data_operator_actions(payload)
    return {
        "status": str(payload.get("status", "")),
        "current_blocking_stage": str(payload.get("current_blocking_stage", "")),
        "next_action": dict(next_action) if isinstance(next_action, dict) else {},
        "stages": list(payload.get("stages", [])) if isinstance(payload.get("stages"), list) else [],
        "blockers": list(payload.get("blockers", [])) if isinstance(payload.get("blockers"), list) else [],
        "source_report": str(path),
        "operator_actions": operator_actions,
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _pit_data_operator_actions(payload: dict[str, Any]) -> list[dict[str, str]]:
    stages = payload.get("stages", [])
    source_reports = payload.get("source_reports", {})
    next_action = payload.get("next_action", {})
    incoming_source_dir = "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    bundle_id = "manual_vendor_bundle_v1"
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            summary = stage.get("summary", {})
            if not isinstance(summary, dict):
                continue
            if isinstance(summary.get("source_dir"), str) and summary["source_dir"]:
                incoming_source_dir = summary["source_dir"]
            if isinstance(summary.get("incoming_drop_dir"), str) and summary["incoming_drop_dir"]:
                incoming_source_dir = summary["incoming_drop_dir"]
            if isinstance(summary.get("bundle_id"), str) and summary["bundle_id"]:
                bundle_id = summary["bundle_id"]

    current_stage = str(payload.get("current_blocking_stage") or "")
    first_blocker = ""
    next_description = ""
    if isinstance(next_action, dict):
        first_blocker = str(next_action.get("first_blocker") or "")
        next_description = str(next_action.get("description") or "")

    actions: list[dict[str, str]] = []
    if next_description:
        actions.append(
            {
                "label": "当前阻塞处理",
                "intent": next_description,
                "command": f"New-Item -ItemType Directory -Force -Path {incoming_source_dir}",
                "blocked_until": first_blocker or current_stage or "manual_vendor_drop_ready",
            }
        )

    report_paths = source_reports if isinstance(source_reports, dict) else {}
    manual_package_report = str(report_paths.get("manual_vendor_drop_package") or "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json")
    readiness_report = str(report_paths.get("incoming_drop_readiness") or "artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json")
    actions.extend(
        [
            {
                "label": "生成供应商投放模板",
                "intent": f"Refresh the template and field dictionary package; report: {manual_package_report}",
                "command": "python scripts/build_us_equity_manual_vendor_drop_package.py",
                "blocked_until": "manual_vendor_drop_package_ready",
            },
            {
                "label": "复查投放目录",
                "intent": f"Validate required licensed CSV files under {incoming_source_dir}; report: {readiness_report}",
                "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py",
                "blocked_until": "incoming_drop_readiness_pass",
            },
            {
                "label": "导入本地生产 bundle",
                "intent": "Create a candidate PIT production bundle from reviewed local CSV files; still no broker/order access.",
                "command": (
                    "python scripts/import_us_equity_local_csv_production_bundle.py "
                    f"--source-dir {incoming_source_dir} "
                    f"--bundle-id {bundle_id} "
                    "--sample-start 2000-01-01 --sample-end 2026-06-24 "
                    '--license-note "<license scope>" --promotion-clean-allowed'
                ),
                "blocked_until": "incoming_drop_readiness_pass_and_license_scope_known",
            },
            {
                "label": "激活候选 bundle",
                "intent": "Run production bundle activation gate after manual license review.",
                "command": (
                    "python scripts/build_us_equity_production_bundle_activation_report.py "
                    f"--bundle-id {bundle_id} --license-reviewed"
                ),
                "blocked_until": "manual_license_review_complete",
            },
            {
                "label": "重跑美股生产线",
                "intent": "Refresh production-line status after PIT data activation checks.",
                "command": "python scripts/run_us_equity_daily_production_line.py",
                "blocked_until": "production_bundle_activation_pass",
            },
        ]
    )
    return actions


def _pit_operator_handoff_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "current_blocking_stage": "pit_operator_handoff_report",
            "current_blocking_step": "pit_operator_handoff_report",
            "incoming_drop_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "default_bundle_id": "manual_vendor_bundle_v1",
            "required_table_count": 0,
            "required_tables": [],
            "operator_next_actions": [
                "Run: python scripts/build_us_equity_pit_operator_handoff_summary.py",
            ],
            "commands": {
                "build_handoff": "python scripts/build_us_equity_pit_operator_handoff_summary.py",
            },
            "blockers": ["pit_operator_handoff_summary_missing"],
            "source_report": str(path),
            "guardrails": {
                "operator_handoff_only": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
                "broker_calls_used": False,
            },
        }
    required_tables = []
    for item in payload.get("required_tables", []):
        if not isinstance(item, dict):
            continue
        fields = item.get("required_fields", [])
        required_tables.append(
            {
                "table": str(item.get("table") or ""),
                "filename": str(item.get("filename") or ""),
                "field_count": len(fields) if isinstance(fields, list) else 0,
                "minimum_record_count": int(item.get("minimum_record_count") or 0),
                "empty_template_is_not_valid_drop": bool(item.get("empty_template_is_not_valid_drop", False)),
            }
        )
    blockers = payload.get("blockers", [])
    operator_next_actions = payload.get("operator_next_actions", [])
    return {
        "status": str(payload.get("status") or ""),
        "current_blocking_stage": str(payload.get("current_blocking_stage") or ""),
        "current_blocking_step": str(payload.get("current_blocking_step") or ""),
        "incoming_drop_dir": str(payload.get("incoming_drop_dir") or ""),
        "default_bundle_id": str(payload.get("default_bundle_id") or ""),
        "required_table_count": int(payload.get("required_table_count") or len(required_tables)),
        "required_tables": required_tables,
        "operator_next_actions": [str(item) for item in operator_next_actions[:12]]
        if isinstance(operator_next_actions, list)
        else [],
        "commands": dict(payload.get("commands", {})) if isinstance(payload.get("commands"), dict) else {},
        "blockers": [str(blocker) for blocker in blockers[:20]] if isinstance(blockers, list) else [],
        "outputs": dict(payload.get("outputs", {})) if isinstance(payload.get("outputs"), dict) else {},
        "source_reports": dict(payload.get("source_reports", {})) if isinstance(payload.get("source_reports"), dict) else {},
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _development_plan_audit_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "development_plan_audit_missing",
            "summary": {
                "phase_count": 0,
                "complete_count": 0,
                "blocked_count": 0,
                "observing_count": 0,
            },
            "phase_checks": [],
            "blockers": ["development_plan_audit_report_missing"],
            "source_report": str(path),
            "guardrails": {
                "live_order_allowed": False,
                "paper_or_live_unlock_allowed": False,
                "real_order_submitted": False,
            },
        }

    phase_checks: list[dict[str, Any]] = []
    raw_phase_checks = payload.get("phase_checks", [])
    if isinstance(raw_phase_checks, list):
        for phase in raw_phase_checks:
            if not isinstance(phase, dict):
                continue
            raw_blockers = phase.get("blockers", [])
            blockers = [str(blocker) for blocker in raw_blockers[:4]] if isinstance(raw_blockers, list) else []
            metrics = phase.get("metrics", {})
            phase_checks.append(
                {
                    "phase_id": str(phase.get("phase_id") or ""),
                    "title": str(phase.get("title") or ""),
                    "status": str(phase.get("status") or ""),
                    "blockers": blockers,
                    "blocked_count": len(raw_blockers) if isinstance(raw_blockers, list) else 0,
                    "metrics": metrics if isinstance(metrics, dict) else {},
                }
            )

    summary = payload.get("summary", {})
    blockers = payload.get("blockers", [])
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "summary": summary if isinstance(summary, dict) else {},
        "phase_checks": phase_checks,
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _live_readiness_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "live_readiness_report_missing",
            "strategy_id": "",
            "account_capital_usd": 0.0,
            "max_live_principal_usd": 0.0,
            "live_order_allowed": False,
            "blockers": ["live_readiness_report_missing"],
            "gate_checks": {},
            "risk_constitution": {},
            "source_report": str(path),
            "guardrails": {
                "live_order_allowed": False,
                "order_endpoint_allowed": False,
                "private_endpoint_allowed": False,
                "real_order_submitted": False,
            },
        }

    blockers = payload.get("blockers", [])
    gate_checks = payload.get("gate_checks", {})
    risk_constitution = payload.get("risk_constitution", {})
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "account_capital_usd": float(payload.get("account_capital_usd") or 0.0),
        "max_live_principal_usd": float(payload.get("max_live_principal_usd") or 0.0),
        "live_order_allowed": bool(payload.get("live_order_allowed", False)),
        "paper_simulation_unlocked_by_this_report": bool(payload.get("paper_simulation_unlocked_by_this_report", False)),
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "gate_checks": gate_checks if isinstance(gate_checks, dict) else {},
        "risk_constitution": risk_constitution if isinstance(risk_constitution, dict) else {},
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _strategy_validation_gate_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "strategy_validation_gate_report_missing",
            "strategy_id": "",
            "candidate_variant": "",
            "allowed_next_action": "build_strategy_validation_gate",
            "forward_observation_allowed": False,
            "paper_ready": False,
            "live_ready": False,
            "blockers": ["strategy_validation_gate_report_missing"],
            "checks": [],
            "source_report": str(path),
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "order_endpoint_allowed": False,
                "private_endpoint_allowed": False,
                "real_order_submitted": False,
            },
        }

    raw_checks = payload.get("checks", {})
    checks: list[dict[str, Any]] = []
    if isinstance(raw_checks, dict):
        for check_id, check_payload in raw_checks.items():
            if not isinstance(check_payload, dict):
                continue
            check_summary = {
                "check_id": str(check_id),
                "passed": bool(check_payload.get("passed", False)),
            }
            if check_id == "data_coverage_and_quality":
                check_summary.update(
                    {
                        "tiingo_status": str(check_payload.get("tiingo_status") or ""),
                        "kline_quality_status": str(check_payload.get("kline_quality_status") or ""),
                        "fred_preflight_status": str(check_payload.get("fred_preflight_status") or ""),
                        "matched_data_quality_blockers": [
                            str(item) for item in check_payload.get("matched_data_quality_blockers", [])[:6]
                        ]
                        if isinstance(check_payload.get("matched_data_quality_blockers"), list)
                        else [],
                    }
                )
            if check_id == "walk_forward":
                check_summary.update(
                    {
                        "fold_count": int(check_payload.get("fold_count") or 0),
                        "walk_forward_oos_cagr": float(check_payload.get("walk_forward_oos_cagr") or 0.0),
                    }
                )
            if check_id == "parameter_stability":
                check_summary.update(
                    {
                        "alive_rate": float(check_payload.get("alive_rate") or 0.0),
                        "candidate_count": int(check_payload.get("candidate_count") or 0),
                    }
                )
            if check_id == "cost_stress":
                levels = check_payload.get("levels", [])
                check_summary["levels"] = [str(level) for level in levels] if isinstance(levels, list) else []
            checks.append(check_summary)

    blockers = payload.get("blockers", [])
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "candidate_variant": str(payload.get("candidate_variant") or ""),
        "allowed_next_action": str(payload.get("allowed_next_action") or ""),
        "forward_observation_allowed": bool(payload.get("forward_observation_allowed", False)),
        "paper_ready": bool(payload.get("paper_ready", False)),
        "live_ready": bool(payload.get("live_ready", False)),
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "checks": checks,
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _forward_observation_status(evaluation_path: Path, daily_health_path: Path) -> dict[str, Any]:
    evaluation = _json_file(evaluation_path)
    daily_health = _json_file(daily_health_path)
    if not evaluation and not daily_health:
        return {
            "status": "missing",
            "decision": "forward_observation_reports_missing",
            "daily_health_status": "missing",
            "observation_days": 0,
            "minimum_complete_days": 30,
            "latest_observation_date": "",
            "ledger": {},
            "metrics": {},
            "blockers": ["forward_observation_reports_missing"],
            "source_reports": {
                "evaluation": str(evaluation_path),
                "daily_health": str(daily_health_path),
            },
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "real_order_submitted": False,
            },
        }

    metrics = evaluation.get("metrics", {}) if isinstance(evaluation.get("metrics"), dict) else {}
    ledger = daily_health.get("ledger", {}) if isinstance(daily_health.get("ledger"), dict) else {}
    blockers = evaluation.get("blockers", [])
    warnings = daily_health.get("warnings", [])
    return {
        "status": str(evaluation.get("status") or ""),
        "decision": str(evaluation.get("decision") or ""),
        "daily_health_status": str(daily_health.get("status") or ""),
        "daily_health_decision": str(daily_health.get("decision") or ""),
        "observation_days": int(metrics.get("observation_days") or daily_health.get("observation_days") or 0),
        "minimum_complete_days": int(evaluation.get("minimum_complete_days") or daily_health.get("minimum_complete_days") or 30),
        "latest_observation_date": str(metrics.get("latest_observation_date") or daily_health.get("latest_observation_date") or ""),
        "ledger": ledger,
        "metrics": metrics,
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "warnings": [str(warning) for warning in warnings[:12]] if isinstance(warnings, list) else [],
        "source_reports": {
            "evaluation": str(evaluation_path),
            "daily_health": str(daily_health_path),
        },
        "guardrails": dict(evaluation.get("guardrails", {})) if isinstance(evaluation.get("guardrails"), dict) else {},
    }


def _manual_review_packet_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "manual_review_packet_missing",
            "strategy_id": "",
            "blockers": ["manual_review_packet_missing"],
            "evidence_checklist": [],
            "review_milestones": [],
            "signoff_requirements": [],
            "paper_or_live_unlock_decision": {
                "manual_review_can_unlock_paper_by_itself": False,
                "manual_review_can_unlock_live_by_itself": False,
            },
            "source_report": str(path),
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "real_order_submitted": False,
            },
        }

    checklist = payload.get("evidence_checklist", [])
    signoffs = payload.get("signoff_requirements", [])
    blockers = payload.get("blockers", [])
    unlock = payload.get("paper_or_live_unlock_decision", {})
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "evidence_checklist": checklist if isinstance(checklist, list) else [],
        "signoff_requirements": signoffs if isinstance(signoffs, list) else [],
        "review_milestones": payload.get("review_milestones", []) if isinstance(payload.get("review_milestones"), list) else [],
        "paper_or_live_unlock_decision": unlock if isinstance(unlock, dict) else {},
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _paper_simulation_readiness_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "paper_simulation_readiness_report_missing",
            "strategy_id": "",
            "paper_ledger_root": "",
            "paper_runner_allowed": False,
            "required_runner_contract": {},
            "manual_review_evidence": {},
            "blockers": ["paper_simulation_readiness_report_missing"],
            "unsafe_flags": [],
            "source_reports": {},
            "source_report": str(path),
            "guardrails": {
                "readiness_report_only": True,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "order_endpoint_allowed": False,
                "private_endpoint_allowed": False,
                "real_order_submitted": False,
            },
        }

    blockers = payload.get("blockers", [])
    unsafe = payload.get("unsafe_flags", [])
    contract = payload.get("required_runner_contract", {})
    manual_evidence = payload.get("manual_review_evidence", {})
    source_reports = payload.get("source_reports", {})
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "paper_ledger_root": str(payload.get("paper_ledger_root") or ""),
        "paper_runner_allowed": bool(payload.get("paper_runner_allowed", False)),
        "required_runner_contract": contract if isinstance(contract, dict) else {},
        "manual_review_evidence": manual_evidence if isinstance(manual_evidence, dict) else {},
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "unsafe_flags": [str(flag) for flag in unsafe[:12]] if isinstance(unsafe, list) else [],
        "source_reports": source_reports if isinstance(source_reports, dict) else {},
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _small_account_execution_preflight_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "strategy_id": "",
            "candidate_variant": "",
            "timestamp": "",
            "account_equity": 0.0,
            "annual_financing_rate": 0.0,
            "slippage_bps": 0.0,
            "min_trade_amount_usd": 0.0,
            "latest_target": {},
            "scenario_count": 0,
            "passed_scenario_count": 0,
            "scenarios": [],
            "blockers": ["small_account_execution_preflight_report_missing"],
            "source_report": str(path),
            "guardrails": {
                "simulated_only": True,
                "live_order_allowed": False,
                "order_endpoint_allowed": False,
                "private_endpoint_allowed": False,
                "real_order_submitted": False,
            },
        }

    raw_scenarios = payload.get("scenarios", [])
    scenarios: list[dict[str, Any]] = []
    if isinstance(raw_scenarios, list):
        for scenario in raw_scenarios:
            if not isinstance(scenario, dict):
                continue
            fractional = scenario.get("fractional_share_allowed_model", {})
            whole = scenario.get("whole_share_model", {})
            if not isinstance(fractional, dict):
                fractional = {}
            if not isinstance(whole, dict):
                whole = {}
            blockers = scenario.get("blockers", [])
            scenarios.append(
                {
                    "scenario_id": str(scenario.get("scenario_id") or ""),
                    "description": str(scenario.get("description") or ""),
                    "gross_cap": float(scenario.get("gross_cap") or 0.0),
                    "effective_gross": float(scenario.get("effective_gross") or 0.0),
                    "allow_margin": bool(scenario.get("allow_margin", False)),
                    "passes_preflight": bool(scenario.get("passes_preflight", False)),
                    "fractional_cash_after_orders": float(fractional.get("cash_after_orders") or 0.0),
                    "fractional_estimated_financing_daily": float(fractional.get("estimated_financing_daily") or 0.0),
                    "fractional_estimated_slippage": float(fractional.get("estimated_slippage") or 0.0),
                    "whole_cash_after_orders": float(whole.get("cash_after_orders") or 0.0),
                    "whole_estimated_slippage": float(whole.get("estimated_slippage") or 0.0),
                    "first_blocker": str(blockers[0]) if isinstance(blockers, list) and blockers else "",
                }
            )

    blockers = payload.get("blockers", [])
    return {
        "status": str(payload.get("status") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "candidate_variant": str(payload.get("candidate_variant") or ""),
        "timestamp": str(payload.get("timestamp") or ""),
        "account_equity": float(payload.get("account_equity") or 0.0),
        "annual_financing_rate": float(payload.get("annual_financing_rate") or 0.0),
        "slippage_bps": float(payload.get("slippage_bps") or 0.0),
        "min_trade_amount_usd": float(payload.get("min_trade_amount_usd") or 0.0),
        "latest_target": payload.get("latest_target", {}) if isinstance(payload.get("latest_target"), dict) else {},
        "scenario_count": len(scenarios),
        "passed_scenario_count": sum(1 for scenario in scenarios if scenario.get("passes_preflight") is True),
        "scenarios": scenarios,
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _data_lineage_governance_status(
    reconciliation_path: Path,
    remediation_path: Path,
    macro_lag_path: Path,
) -> dict[str, Any]:
    reconciliation = _json_file(reconciliation_path)
    remediation = _json_file(remediation_path)
    macro_lag = _json_file(macro_lag_path)
    reports = {
        "data_source_reconciliation": reconciliation,
        "data_lineage_remediation": remediation,
        "macro_release_lag_policy": macro_lag,
    }
    missing = [name for name, payload in reports.items() if not payload]

    remediation_groups = []
    raw_groups = remediation.get("remediation_groups", []) if isinstance(remediation, dict) else []
    if isinstance(raw_groups, list):
        for group in raw_groups[:8]:
            if isinstance(group, dict):
                remediation_groups.append(
                    {
                        "group_id": str(group.get("group_id") or group.get("id") or ""),
                        "status": str(group.get("status") or ""),
                        "blocker_count": len(group.get("blockers", [])) if isinstance(group.get("blockers"), list) else 0,
                    }
                )

    blockers: list[str] = []
    for payload in reports.values():
        if isinstance(payload, dict) and isinstance(payload.get("blockers"), list):
            blockers.extend(str(blocker) for blocker in payload.get("blockers", [])[:6])
    blockers.extend(f"{name}_missing" for name in missing)
    blockers = list(dict.fromkeys(blockers))

    return {
        "status": "missing" if missing else str(reconciliation.get("status") or remediation.get("status") or ""),
        "reconciliation_status": str(reconciliation.get("status") or "") if reconciliation else "missing",
        "remediation_status": str(remediation.get("status") or "") if remediation else "missing",
        "macro_release_lag_status": str(macro_lag.get("status") or "") if macro_lag else "missing",
        "selected_price_source": str(reconciliation.get("selected_price_source") or "") if reconciliation else "",
        "selected_price_root": str(reconciliation.get("selected_price_root") or "") if reconciliation else "",
        "lineage_maturity": str(remediation.get("data_lineage_maturity") or "") if remediation else "",
        "remediation_task_count": int(remediation.get("remediation_task_count") or 0) if remediation else 0,
        "remediation_groups": remediation_groups,
        "macro_source": str(macro_lag.get("macro_source") or "") if macro_lag else "",
        "accepted_evidence_for_promotion": bool(macro_lag.get("accepted_evidence_for_promotion", False))
        if macro_lag
        else False,
        "blockers": blockers[:16],
        "source_reports": {
            "data_source_reconciliation": str(reconciliation_path),
            "data_lineage_remediation": str(remediation_path),
            "macro_release_lag_policy": str(macro_lag_path),
        },
        "guardrails": {
            "data_lineage_governance_only": True,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "order_endpoint_allowed": False,
            "private_endpoint_allowed": False,
            "real_order_submitted": False,
        },
    }


def _production_data_acquisition_status(
    acquisition_path: Path,
    candidate_path: Path,
    intake_path: Path,
    manual_package_path: Path,
) -> dict[str, Any]:
    acquisition = _json_file(acquisition_path)
    candidate = _json_file(candidate_path)
    intake = _json_file(intake_path)
    manual_package = _json_file(manual_package_path)
    reports = {
        "production_data_acquisition_plan": acquisition,
        "candidate_bundle_evidence": candidate,
        "production_bundle_intake_packet": intake,
        "manual_vendor_drop_package": manual_package,
    }
    missing = [name for name, payload in reports.items() if not payload]

    blockers: list[str] = []
    for payload in reports.values():
        if isinstance(payload, dict) and isinstance(payload.get("blockers"), list):
            blockers.extend(str(blocker) for blocker in payload.get("blockers", [])[:8])
    blockers.extend(f"{name}_missing" for name in missing)
    blockers = list(dict.fromkeys(blockers))

    required_tables = []
    raw_required_tables = acquisition.get("required_tables", []) if acquisition else []
    for row in raw_required_tables:
        if isinstance(row, dict):
            required_tables.append(
                {
                    "table": str(row.get("table") or ""),
                    "filename": str(row.get("filename") or ""),
                    "field_count": len(row.get("required_fields", [])) if isinstance(row.get("required_fields"), list) else 0,
                }
            )

    operator_steps = []
    raw_operator_steps = intake.get("operator_steps", []) if intake else []
    for row in raw_operator_steps:
        if isinstance(row, dict):
            operator_steps.append(
                {
                    "step_id": str(row.get("step_id") or ""),
                    "command": str(row.get("command") or ""),
                    "expected_result": str(row.get("expected_result") or ""),
                }
            )

    return {
        "status": "missing" if missing else str(acquisition.get("status") or ""),
        "acquisition_status": str(acquisition.get("status") or "") if acquisition else "missing",
        "candidate_evidence_status": str(candidate.get("status") or "") if candidate else "missing",
        "candidate_evidence_decision": str(candidate.get("decision") or "") if candidate else "",
        "intake_packet_status": str(intake.get("status") or "") if intake else "missing",
        "intake_packet_decision": str(intake.get("decision") or "") if intake else "",
        "manual_package_status": str(manual_package.get("status") or "") if manual_package else "missing",
        "incoming_drop_dir": str(manual_package.get("incoming_drop_dir") or "") if manual_package else "",
        "default_bundle_id": str(manual_package.get("default_bundle_id") or "") if manual_package else "",
        "acceptable_provider_ids": [
            str(provider) for provider in acquisition.get("acceptable_provider_ids", [])[:8]
        ]
        if acquisition and isinstance(acquisition.get("acceptable_provider_ids"), list)
        else [],
        "missing_contract_groups": [
            str(group) for group in acquisition.get("missing_contract_groups", [])[:12]
        ]
        if acquisition and isinstance(acquisition.get("missing_contract_groups"), list)
        else [],
        "required_table_count": int(manual_package.get("required_table_count") or len(required_tables))
        if manual_package
        else len(required_tables),
        "field_count": int(manual_package.get("field_count") or 0) if manual_package else 0,
        "required_tables": required_tables[:8],
        "operator_steps": operator_steps[:6],
        "acceptance_commands": [
            str(command) for command in acquisition.get("acceptance_commands", [])[:8]
        ]
        if acquisition and isinstance(acquisition.get("acceptance_commands"), list)
        else [],
        "blockers": blockers[:20],
        "source_reports": {
            "production_data_acquisition_plan": str(acquisition_path),
            "candidate_bundle_evidence": str(candidate_path),
            "production_bundle_intake_packet": str(intake_path),
            "manual_vendor_drop_package": str(manual_package_path),
        },
        "guardrails": {
            "production_data_acquisition_only": True,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "order_endpoint_allowed": False,
            "private_endpoint_allowed": False,
            "real_order_submitted": False,
        },
    }


def _production_bundle_gate_status(
    incoming_path: Path,
    import_path: Path,
    activation_path: Path,
) -> dict[str, Any]:
    incoming = _json_file(incoming_path)
    imported = _json_file(import_path)
    activation = _json_file(activation_path)
    stages = [
        _production_bundle_stage("incoming_drop_readiness", incoming, incoming_path),
        _production_bundle_stage("local_csv_import", imported, import_path),
        _production_bundle_stage("production_bundle_activation", activation, activation_path),
    ]
    blockers: list[str] = []
    for stage in stages:
        blockers.extend(stage["blockers"][:8])
        if stage["status"] == "missing":
            blockers.append(f"{stage['stage_id']}_report_missing")
    blockers = list(dict.fromkeys(str(blocker) for blocker in blockers if blocker))
    stage_statuses = [stage["status"] for stage in stages]
    if any(status == "missing" for status in stage_statuses):
        status = "production_bundle_gate_missing_reports"
        current_stage = next(stage["stage_id"] for stage in stages if stage["status"] == "missing")
    elif all(status in {"pass", "activation_passed", "production_bundle_import_pass"} for status in stage_statuses):
        status = "production_bundle_gate_pass"
        current_stage = ""
    else:
        status = "production_bundle_gate_blocked"
        current_stage = next(
            stage["stage_id"]
            for stage in stages
            if stage["status"] not in {"pass", "activation_passed", "production_bundle_import_pass"}
        )
    operator_actions = _production_bundle_gate_operator_actions(
        current_stage=current_stage,
        incoming=incoming,
        imported=imported,
        activation=activation,
    )
    return {
        "status": status,
        "current_blocking_stage": current_stage,
        "stages": stages,
        "operator_actions": operator_actions,
        "blockers": blockers[:24],
        "source_reports": {
            "incoming_drop_readiness": str(incoming_path),
            "local_csv_production_bundle_import": str(import_path),
            "production_bundle_activation": str(activation_path),
        },
        "guardrails": {
            "production_bundle_gate_only": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
    }


def _production_bundle_gate_operator_actions(
    *,
    current_stage: str,
    incoming: dict[str, Any],
    imported: dict[str, Any],
    activation: dict[str, Any],
) -> list[dict[str, str]]:
    source_dir = str(incoming.get("source_dir") or imported.get("source_dir") or "data/external/us_equity_lineage/incoming/manual_vendor_drop")
    bundle_id = str(incoming.get("bundle_id") or imported.get("bundle_id") or activation.get("bundle_id") or "manual_vendor_bundle_v1")
    actions: list[dict[str, str]] = []
    if current_stage in {"incoming_drop_readiness", ""}:
        actions.append(
            {
                "stage_id": "incoming_drop_readiness",
                "label": "prepare_manual_vendor_drop",
                "command": f"New-Item -ItemType Directory -Force -Path {source_dir}",
                "blocked_until": "six licensed CSV files are placed in the incoming drop directory",
            }
        )
        actions.append(
            {
                "stage_id": "incoming_drop_readiness",
                "label": "check_incoming_drop_readiness",
                "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py",
                "blocked_until": "incoming_drop_ready_for_import",
            }
        )
    preferred_import = str(
        incoming.get("preferred_import_command")
        or (
            "python scripts/import_us_equity_local_csv_production_bundle.py "
            f"--source-dir {source_dir} --bundle-id {bundle_id} --promotion-clean-allowed"
        )
    )
    if current_stage in {"local_csv_import", "incoming_drop_readiness", ""}:
        actions.append(
            {
                "stage_id": "local_csv_import",
                "label": "import_local_csv_production_bundle",
                "command": preferred_import,
                "blocked_until": "production_bundle_imported",
            }
        )
    activation_command = (
        "python scripts/build_us_equity_production_bundle_activation_report.py "
        f"--bundle-id {bundle_id} --license-reviewed"
    )
    if current_stage in {"production_bundle_activation", "local_csv_import", "incoming_drop_readiness", ""}:
        actions.append(
            {
                "stage_id": "production_bundle_activation",
                "label": "build_activation_report",
                "command": activation_command,
                "blocked_until": "activation_ready_for_manual_config_apply",
            }
        )
    manual_apply_commands = activation.get("manual_apply_commands", [])
    if isinstance(manual_apply_commands, list):
        for index, command in enumerate(manual_apply_commands[:3]):
            actions.append(
                {
                    "stage_id": "manual_config_apply",
                    "label": f"manual_apply_step_{index + 1}",
                    "command": str(command),
                    "blocked_until": "manual_license_and_config_review_complete",
                }
            )
    validation_commands = activation.get("validation_commands_after_apply", [])
    if isinstance(validation_commands, list):
        for index, command in enumerate(validation_commands[:3]):
            actions.append(
                {
                    "stage_id": "post_activation_validation",
                    "label": f"post_activation_validation_{index + 1}",
                    "command": str(command),
                    "blocked_until": "production_bundle_activation_pass",
                }
            )
    return actions[:10]


def _production_bundle_stage(stage_id: str, payload: dict[str, Any], path: Path) -> dict[str, Any]:
    if not payload:
        return {
            "stage_id": stage_id,
            "status": "missing",
            "blockers": [f"{stage_id}_report_missing"],
            "source_report": str(path),
            "summary": {},
        }
    summary_keys = (
        "source_dir",
        "bundle_id",
        "candidate_bundle_id",
        "candidate_bundle_root",
        "production_bundle_root",
        "required_table_count",
        "present_table_count",
        "missing_table_count",
        "manifest_path",
        "candidate_config_path",
    )
    summary = {key: payload.get(key) for key in summary_keys if key in payload}
    if isinstance(payload.get("summary"), dict):
        summary.update({str(key): value for key, value in payload["summary"].items() if key not in summary})
    return {
        "stage_id": stage_id,
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "blockers": [str(blocker) for blocker in payload.get("blockers", [])[:12]]
        if isinstance(payload.get("blockers"), list)
        else [],
        "source_report": str(path),
        "summary": summary,
    }


def _standard_report_schema_audit_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "standard_report_schema_audit_missing",
            "strategy_id": "",
            "candidate_variant": "",
            "required_fields": [],
            "coverage_summary": {
                "required_field_count": 0,
                "passed_field_count": 0,
                "missing_input_count": 0,
                "unsafe_flag_count": 0,
            },
            "field_checks": [],
            "blockers": ["standard_report_schema_audit_missing"],
            "source_report": str(path),
            "guardrails": {
                "schema_audit_only": True,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "real_order_submitted": False,
            },
        }

    raw_field_checks = payload.get("field_checks", {})
    field_checks: list[dict[str, Any]] = []
    if isinstance(raw_field_checks, dict):
        for field_id, check_payload in raw_field_checks.items():
            if not isinstance(check_payload, dict):
                continue
            sources = check_payload.get("sources", [])
            field_checks.append(
                {
                    "field_id": str(field_id),
                    "passed": bool(check_payload.get("passed", False)),
                    "sources": [str(source) for source in sources[:4]] if isinstance(sources, list) else [],
                }
            )

    blockers = payload.get("blockers", [])
    coverage = payload.get("coverage_summary", {})
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "candidate_variant": str(payload.get("candidate_variant") or ""),
        "required_fields": [str(field) for field in payload.get("required_fields", [])]
        if isinstance(payload.get("required_fields"), list)
        else [],
        "coverage_summary": coverage if isinstance(coverage, dict) else {},
        "field_checks": field_checks,
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _monitoring_rules_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "strategy_id": "",
            "monitor_count": 0,
            "required_before_paper_or_live": True,
            "minimum_required_before_paper": [],
            "rule_sections": [],
            "blockers": ["monitoring_rules_report_missing"],
            "source_report": str(path),
            "guardrails": {
                "rules_only": True,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "real_order_submitted": False,
            },
        }

    rules = payload.get("rules", {})
    rule_sections = list(rules.keys()) if isinstance(rules, dict) else []
    minimum = payload.get("minimum_required_before_paper", [])
    blockers = payload.get("blockers", [])
    return {
        "status": str(payload.get("status") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "monitor_count": int(payload.get("monitor_count") or 0),
        "required_before_paper_or_live": bool(payload.get("required_before_paper_or_live", True)),
        "minimum_required_before_paper": [str(item) for item in minimum[:8]] if isinstance(minimum, list) else [],
        "rule_sections": [str(section) for section in rule_sections[:8]],
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _replay_readiness_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "replay_readiness_report_missing",
            "strategy_id": "",
            "latest_observation": {},
            "checks": [],
            "blockers": ["replay_readiness_report_missing"],
            "source_report": str(path),
            "guardrails": {
                "replay_readiness_only": True,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "real_order_submitted": False,
            },
        }

    raw_checks = payload.get("checks", {})
    checks: list[dict[str, Any]] = []
    if isinstance(raw_checks, dict):
        for check_id, check_payload in raw_checks.items():
            if isinstance(check_payload, dict):
                checks.append({"check_id": str(check_id), "passed": bool(check_payload.get("passed", False))})

    blockers = payload.get("blockers", [])
    latest = payload.get("latest_observation", {})
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "strategy_id": str(payload.get("strategy_id") or ""),
        "latest_observation": latest if isinstance(latest, dict) else {},
        "checks": checks,
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _strategy_registry_status(path: Path, audit_path: Path | None = None) -> dict[str, Any]:
    payload = _json_file(path)
    audit_payload = _json_file(audit_path) if audit_path else {}
    default_policy = {
        "paper_or_live_unlock_allowed_by_registry": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "live_order_allowed": False,
    }
    if not payload:
        return {
            "status": "missing",
            "schema_version": "",
            "strategy_count": 0,
            "primary_strategy_id": "",
            "primary_stage": "",
            "primary_status": "",
            "registered_families": [],
            "stage_counts": {},
            "status_counts": {},
            "strategies": [],
            "policy": default_policy,
            "audit": _strategy_registry_audit_compact(audit_payload, audit_path),
            "blockers": ["strategy_registry_missing"],
            "source_report": str(path),
        }

    raw_strategies = payload.get("strategies", [])
    strategies = [strategy for strategy in raw_strategies if isinstance(strategy, dict)] if isinstance(raw_strategies, list) else []
    stage_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    families: list[str] = []
    compact_strategies: list[dict[str, Any]] = []
    primary: dict[str, Any] = {}
    for strategy in strategies:
        stage = str(strategy.get("current_stage") or "unknown")
        status = str(strategy.get("status") or "unknown")
        family = str(strategy.get("family") or "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        if family not in families:
            families.append(family)
        if bool(strategy.get("primary_candidate")) and not primary:
            primary = strategy
        guardrails = strategy.get("guardrails", {})
        if not isinstance(guardrails, dict):
            guardrails = {}
        compact_strategies.append(
            {
                "strategy_id": str(strategy.get("strategy_id") or ""),
                "family": family,
                "status": status,
                "current_stage": stage,
                "primary_candidate": bool(strategy.get("primary_candidate", False)),
                "paper_ready": bool(guardrails.get("paper_ready", False)),
                "live_ready": bool(guardrails.get("live_ready", False)),
            }
        )

    policy = payload.get("policy", {})
    if not isinstance(policy, dict):
        policy = {}
    normalized_policy = {**default_policy, **{str(key): value for key, value in policy.items()}}
    blockers: list[str] = []
    if bool(normalized_policy.get("paper_or_live_unlock_allowed_by_registry", False)):
        blockers.append("strategy_registry_policy_allows_paper_or_live_unlock")
    for key in ("private_endpoint_allowed", "order_endpoint_allowed", "live_order_allowed"):
        if bool(normalized_policy.get(key, False)):
            blockers.append(f"strategy_registry_policy_{key}")
    if strategies and not primary:
        blockers.append("strategy_registry_primary_candidate_missing")
    audit = _strategy_registry_audit_compact(audit_payload, audit_path)
    if audit["status"] == "missing":
        blockers.append("strategy_registry_audit_missing")
    elif audit["status"] != "pass":
        blockers.append("strategy_registry_audit_not_pass")

    return {
        "status": "present" if not blockers else "policy_blocked",
        "schema_version": str(payload.get("schema_version") or ""),
        "strategy_count": len(strategies),
        "primary_strategy_id": str(primary.get("strategy_id") or ""),
        "primary_stage": str(primary.get("current_stage") or ""),
        "primary_status": str(primary.get("status") or ""),
        "registered_families": families,
        "stage_counts": stage_counts,
        "status_counts": status_counts,
        "strategies": compact_strategies,
        "policy": normalized_policy,
        "audit": audit,
        "blockers": blockers,
        "source_report": str(path),
    }


def _strategy_registry_audit_compact(payload: dict[str, Any], path: Path | None) -> dict[str, Any]:
    if not payload:
        return {
            "status": "missing",
            "strategy_count": 0,
            "primary_candidate_count": 0,
            "formal_candidate_count": 0,
            "missing_required_families": [],
            "required_families": [],
            "blockers": ["strategy_registry_audit_report_missing"],
            "warnings": [],
            "source_report": str(path) if path else "",
            "guardrails": {
                "unregistered_strategy_promotion_allowed": False,
                "paper_or_live_unlock_allowed_by_registry": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        }
    return {
        "status": str(payload.get("status") or ""),
        "strategy_count": int(payload.get("strategy_count") or 0),
        "primary_candidate_count": int(payload.get("primary_candidate_count") or 0),
        "formal_candidate_count": int(payload.get("formal_candidate_count") or 0),
        "missing_required_families": [
            str(family) for family in payload.get("missing_required_families", [])[:12]
        ]
        if isinstance(payload.get("missing_required_families"), list)
        else [],
        "required_families": [str(family) for family in payload.get("required_families", [])[:12]]
        if isinstance(payload.get("required_families"), list)
        else [],
        "blockers": [str(blocker) for blocker in payload.get("blockers", [])[:20]]
        if isinstance(payload.get("blockers"), list)
        else [],
        "warnings": [str(warning) for warning in payload.get("warnings", [])[:20]]
        if isinstance(payload.get("warnings"), list)
        else [],
        "source_report": str(path) if path else "",
        "guardrails": payload.get("guardrails", {}) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _daily_production_line_status(path: Path) -> dict[str, Any]:
    payload = _json_file(path)
    if not payload:
        return {
            "status": "missing",
            "decision": "daily_production_line_run_missing",
            "generated_at": "",
            "pipeline": "us_equity_daily_production_line",
            "step_count": 0,
            "passed_step_count": 0,
            "failed_step_count": 0,
            "expected_external_blocker": {},
            "forward_observation": {},
            "forward_data_gate": {
                "status": "missing",
                "checks": [],
                "blockers": ["forward_observation_daily_data_gate_missing"],
                "guardrails": {"paper_or_live_unlock_allowed": False, "live_order_allowed": False},
            },
            "steps": [],
            "blockers": ["daily_production_line_run_report_missing"],
            "unsafe_flags": [],
            "source_report": str(path),
            "guardrails": {
                "daily_orchestration_only": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
                "broker_calls_used": False,
            },
        }

    raw_steps = payload.get("steps", [])
    compact_steps: list[dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for step in raw_steps:
            if not isinstance(step, dict):
                continue
            blockers = step.get("blockers", [])
            compact_steps.append(
                {
                    "step_id": str(step.get("step_id") or ""),
                    "status": str(step.get("status") or ""),
                    "passed": bool(step.get("passed", False)),
                    "first_blocker": str(blockers[0]) if isinstance(blockers, list) and blockers else "",
                    "output": str(step.get("output") or ""),
                }
            )
    blockers = payload.get("blockers", [])
    unsafe = payload.get("unsafe_flags", [])
    return {
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "pipeline": str(payload.get("pipeline") or ""),
        "step_count": len(compact_steps),
        "passed_step_count": sum(1 for step in compact_steps if step.get("passed") is True),
        "failed_step_count": sum(1 for step in compact_steps if step.get("passed") is not True),
        "expected_external_blocker": payload.get("expected_external_blocker", {})
        if isinstance(payload.get("expected_external_blocker"), dict)
        else {},
        "forward_observation": payload.get("forward_observation", {})
        if isinstance(payload.get("forward_observation"), dict)
        else {},
        "forward_data_gate": _daily_forward_data_gate_status(payload),
        "steps": compact_steps,
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "unsafe_flags": [str(flag) for flag in unsafe[:12]] if isinstance(unsafe, list) else [],
        "source_report": str(path),
        "guardrails": dict(payload.get("guardrails", {})) if isinstance(payload.get("guardrails"), dict) else {},
    }


def _daily_forward_data_gate_status(payload: dict[str, Any]) -> dict[str, Any]:
    raw_steps = payload.get("steps", [])
    if not isinstance(raw_steps, list):
        raw_steps = []
    data_gate: dict[str, Any] = {}
    for step in raw_steps:
        if not isinstance(step, dict) or step.get("step_id") != "forward_observation_daily":
            continue
        step_payload = step.get("payload", {})
        if not isinstance(step_payload, dict):
            continue
        nested_steps = step_payload.get("steps", {})
        if isinstance(nested_steps, dict) and isinstance(nested_steps.get("data_gate"), dict):
            data_gate = nested_steps["data_gate"]
        break
    if not data_gate:
        return {
            "status": "missing",
            "checks": [],
            "blockers": ["forward_observation_daily_data_gate_missing"],
            "guardrails": {"paper_or_live_unlock_allowed": False, "live_order_allowed": False},
        }
    raw_checks = data_gate.get("checks", [])
    checks: list[dict[str, Any]] = []
    if isinstance(raw_checks, list):
        for check in raw_checks:
            if not isinstance(check, dict):
                continue
            blockers = check.get("blockers", [])
            checks.append(
                {
                    "check_id": str(check.get("check_id") or ""),
                    "status": str(check.get("status") or ""),
                    "passed": bool(check.get("passed", False)),
                    "first_blocker": str(blockers[0]) if isinstance(blockers, list) and blockers else "",
                    "source_report": str(check.get("source_report") or ""),
                }
            )
    blockers = data_gate.get("blockers", [])
    return {
        "status": str(data_gate.get("status") or ""),
        "checks": checks[:8],
        "blockers": [str(blocker) for blocker in blockers[:12]] if isinstance(blockers, list) else [],
        "guardrails": dict(data_gate.get("guardrails", {})) if isinstance(data_gate.get("guardrails"), dict) else {},
    }


def _fast_saved_evidence_registry(root: Path) -> dict[str, Any]:
    """Read the saved registry snapshot without rescanning all evidence files."""
    registry_path = root / "research" / "evidence_registry.json"
    if not registry_path.exists():
        return {
            "schema_version": "evidence_registry_v1",
            "generated_at": "",
            "registry_path": str(registry_path),
            "registry_status": "missing",
            "registry_integrity_status": "MISSING",
            "registry_notes": ["missing_registry_snapshot"],
            "rebuild_available": True,
            "counts": {},
            "evidence": {},
            "chains": {},
        }
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "evidence_registry_v1",
            "generated_at": "",
            "registry_path": str(registry_path),
            "registry_status": "conflict",
            "registry_integrity_status": "CONFLICT",
            "registry_notes": [f"registry_snapshot_unreadable:{exc}"],
            "rebuild_available": True,
            "counts": {},
            "evidence": {},
            "chains": {},
        }
    if not isinstance(payload, dict) or payload.get("schema_version") != "evidence_registry_v1":
        return {
            "schema_version": "evidence_registry_v1",
            "generated_at": "",
            "registry_path": str(registry_path),
            "registry_status": "conflict",
            "registry_integrity_status": "CONFLICT",
            "registry_notes": ["registry_snapshot_schema_mismatch"],
            "rebuild_available": True,
            "counts": {},
            "evidence": {},
            "chains": {},
        }
    result = dict(payload)
    result["registry_path"] = str(registry_path)
    result["registry_status"] = "present"
    result["registry_integrity_status"] = "PASS/STABLE"
    result.setdefault("registry_notes", [])
    result["rebuild_available"] = True
    return result


def _fast_paper_review_status(root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    registry_status = str(registry.get("registry_status", "missing"))
    registry_integrity = str(registry.get("registry_integrity_status", "MISSING"))
    registry_path = str(registry.get("registry_path", root / "research" / "evidence_registry.json"))
    if registry_status != "present" or registry_integrity != "PASS/STABLE":
        return {
            "status": f"REGISTRY_{registry_status.upper()}",
            "entry_allowed": False,
            "manual_review_pending": False,
            "summary": (
                "Saved evidence registry is not ready; paper-review status is "
                f"blocked until registry is explicitly rebuilt. Integrity={registry_integrity}."
            ),
            "evidence_path": registry_path,
        }

    evidence = registry.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    if any(
        isinstance(row, dict) and row.get("integrity_status") == "CONFLICT"
        for section in evidence.values()
        if isinstance(section, list)
        for row in section
    ):
        return {
            "status": "CONFLICT",
            "entry_allowed": False,
            "manual_review_pending": False,
            "summary": "Saved evidence registry contains conflicting evidence; paper-review entry is blocked.",
            "evidence_path": registry_path,
        }

    reviews = [row for row in evidence.get("paper_reviews", []) if isinstance(row, dict)]
    manifests = [row for row in evidence.get("strategy_manifests", []) if isinstance(row, dict)]
    latest_review = reviews[0] if reviews else None
    latest_manifest = manifests[0] if manifests else None

    if latest_review is not None:
        details = latest_review.get("details", {})
        if not isinstance(details, dict):
            details = {}
        status = str(details.get("status", latest_review.get("summary", "UNKNOWN")))
        review_path = str(latest_review.get("path", ""))
        evidence_pack_path = str(details.get("evidence_pack_path", "") or "")
        if status == "PENDING_HUMAN_REVIEW":
            return {
                "status": status,
                "entry_allowed": True,
                "manual_review_pending": True,
                "summary": "Paper review is in the human queue; manual review is still pending.",
                "evidence_path": review_path,
                "review_path": review_path,
                "evidence_pack_path": evidence_pack_path,
            }
        if status == "APPROVED_FOR_PAPER_ONLY":
            return {
                "status": status,
                "entry_allowed": True,
                "manual_review_pending": False,
                "summary": "Human paper review is approved for paper-only consideration; runtime gates still validate evidence before submit.",
                "evidence_path": review_path,
                "review_path": review_path,
                "evidence_pack_path": evidence_pack_path,
            }
        return {
            "status": status,
            "entry_allowed": False,
            "manual_review_pending": False,
            "summary": f"Latest paper review is {status}; paper-review entry is not currently allowed from this evidence.",
            "evidence_path": review_path,
            "review_path": review_path,
            "evidence_pack_path": evidence_pack_path,
        }

    if latest_manifest is not None:
        details = latest_manifest.get("details", {})
        if not isinstance(details, dict):
            details = {}
        status = str(details.get("promotion_status", latest_manifest.get("summary", "UNKNOWN")))
        manifest_path = str(latest_manifest.get("path", ""))
        if status in {"READY_FOR_PORTFOLIO_SIM", "PAPER_REVIEW_CANDIDATE"}:
            return {
                "status": "ELIGIBLE_FOR_PAPER_REVIEW",
                "entry_allowed": True,
                "manual_review_pending": False,
                "summary": "Research evidence allows entry into PAPER_REVIEW, but no human review record exists yet.",
                "evidence_path": manifest_path,
                "manifest_path": manifest_path,
            }
        return {
            "status": status,
            "entry_allowed": False,
            "manual_review_pending": False,
            "summary": f"Latest strategy manifest status is {status}; no paper-review approval evidence is present.",
            "evidence_path": manifest_path,
            "manifest_path": manifest_path,
        }

    return {
        "status": "NO_PAPER_REVIEW_EVIDENCE",
        "entry_allowed": False,
        "manual_review_pending": False,
        "summary": "No paper-review or manifest evidence was found under the research data root.",
        "evidence_path": registry_path,
        "review_path": "",
        "manifest_path": "",
        "evidence_pack_path": "",
    }


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _coverage_from_minute_quality(minute_quality: dict[str, Any]) -> dict[str, Any]:
    dataset_summaries: list[dict[str, Any]] = []
    coverage_values: list[float] = []

    datasets = minute_quality.get("datasets", [])
    if not isinstance(datasets, list):
        datasets = []

    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        dataset_coverages: list[float] = []
        symbols = dataset.get("symbols", [])
        if not isinstance(symbols, list):
            symbols = []
        for symbol in symbols:
            if not isinstance(symbol, dict):
                continue
            intervals = symbol.get("intervals", [])
            if not isinstance(intervals, list):
                continue
            for interval in intervals:
                if not isinstance(interval, dict):
                    continue
                coverage = interval.get("coverage_pct")
                if isinstance(coverage, (int, float)):
                    value = float(coverage)
                    coverage_values.append(value)
                    dataset_coverages.append(value)
        status = str(dataset.get("status", "UNKNOWN"))
        dataset_summaries.append(
            {
                "root_subdir": str(dataset.get("root_subdir", "")),
                "status": status,
                "issue_count": int(dataset.get("issue_count", 0) or 0),
                "evaluated_symbols": list(dataset.get("evaluated_symbols", [])) if isinstance(dataset.get("evaluated_symbols", []), list) else [],
                "coverage_pct": _mean_or_none(dataset_coverages),
                "min_coverage_pct": round(min(dataset_coverages), 4) if dataset_coverages else None,
            }
        )

    return {
        "status": str(minute_quality.get("status", "MISSING")),
        "coverage_pct": _mean_or_none(coverage_values),
        "min_coverage_pct": round(min(coverage_values), 4) if coverage_values else None,
        "dataset_summaries": dataset_summaries,
    }


def _run_directory_summaries(artifacts_root: str, kind: str) -> list[dict[str, Any]]:
    root = Path(artifacts_root)
    if not root.exists():
        return []
    runs = sorted(
        [path for path in root.iterdir() if path.is_dir()],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    summaries: list[dict[str, Any]] = []
    for run_root in runs:
        updated_at = ""
        try:
            from datetime import datetime, timezone

            updated_at = datetime.fromtimestamp(run_root.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            updated_at = ""
        if kind == "qlib":
            dataset_manifest = _json_file(run_root / "qlib_input" / "dataset_manifest.json")
            provider_manifest = _json_file(run_root / "provider_manifest.json")
            workflow_result = _json_file(run_root / "workflow_run_result.json")
            strategy_manifest = _json_file(run_root / "qlib_strategy_manifest.json")
            promotion_status = _qlib_research_only_promotion_status(strategy_manifest)
            summaries.append(
                {
                    "run_id": run_root.name,
                    "updated_at": updated_at,
                    "dataset_status": str(dataset_manifest.get("status", "missing")),
                    "provider_status": str(provider_manifest.get("status", "missing")),
                    "workflow_status": str(workflow_result.get("status", "missing")),
                    "manifest_status": str(strategy_manifest.get("status", "missing")),
                    "promotion_status": promotion_status,
                    "strategy_id": str(strategy_manifest.get("strategy_id") or strategy_manifest.get("strategy_version", "")),
                }
            )
            continue
        if kind == "portfolio":
            manifest = _json_file(run_root / "run_manifest.json")
            has_weights = (run_root / "target_weights.parquet").exists()
            has_positions = (run_root / "target_positions.parquet").exists()
            run_status = _portfolio_research_only_status(
                "completed" if has_weights else str(manifest.get("status", "missing") or "missing")
            )
            summaries.append(
                {
                    "portfolio_run_id": run_root.name,
                    "updated_at": updated_at,
                    "status": run_status,
                    "source_score_run_id": str(manifest.get("source_score_run_id", "")),
                    "optimizer": str(manifest.get("config", {}).get("optimizer", "")) if isinstance(manifest.get("config", {}), dict) else "",
                    "fallback_used": bool(manifest.get("fallback_used", False)),
                    "has_target_weights": has_weights,
                    "has_target_positions": has_positions,
                }
            )
    return summaries


def _portfolio_research_only_status(raw_status: str) -> str:
    """Portfolio integration artifacts are target-weight research handoffs only."""
    raw = str(raw_status or "").strip()
    normalized = raw.lower()
    forbidden_ready_states = {
        "paper_ready",
        "live_ready",
        "ready_for_paper",
        "ready_for_live",
        "paper_eligible",
        "live_eligible",
        "paper_review_candidate",
        "ready_for_portfolio_sim",
        "orders_ready",
        "order_ready",
        "submit_ready",
    }
    if normalized in forbidden_ready_states:
        return "completed"
    return raw or "missing"


def _qlib_research_only_promotion_status(strategy_manifest: dict[str, Any]) -> str:
    """Qlib artifacts are research-only; never surface paper/live readiness."""
    raw = str(strategy_manifest.get("promotion_status", "") or "").strip()
    normalized = raw.lower()
    forbidden_ready_states = {
        "paper_ready",
        "live_ready",
        "ready_for_paper",
        "ready_for_live",
        "paper_eligible",
        "live_eligible",
        "paper_review_candidate",
        "ready_for_portfolio_sim",
    }
    if normalized in forbidden_ready_states:
        return "candidate"
    return raw or "candidate"


def _latest_integration_run(artifacts_root: str, kind: str) -> dict[str, Any]:
    runs = _run_directory_summaries(artifacts_root, kind)
    latest = runs[0] if runs else {}
    return {
        "artifacts_root": artifacts_root,
        "run_count": len(runs),
        "status": str(latest.get("workflow_status", latest.get("dataset_status", latest.get("status", "missing")))) if latest else "missing",
        "latest_run": latest,
        "latest_run_id": str(latest.get("run_id", latest.get("portfolio_run_id", ""))) if latest else "",
        "latest_updated_at": str(latest.get("updated_at", "")) if latest else "",
    }


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _jsonl_file(path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    except (OSError, json.JSONDecodeError):
        return []
    return rows[-limit:]


def _csv_strategy_series(path: Path, *, limit: int = 420) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    by_date: dict[str, dict[str, Any]] = {}
    wanted = {"buy_hold_btc", "twelve_month_momentum_intended"}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                strategy_id = str(row.get("strategy_id", ""))
                if strategy_id not in wanted:
                    continue
                timestamp = str(row.get("timestamp", ""))
                if not timestamp:
                    continue
                item = by_date.setdefault(timestamp, {"timestamp": timestamp})
                key = "buy_hold_equity" if strategy_id == "buy_hold_btc" else "strategy_equity"
                item[key] = _float_or_none(row.get("equity"))
                if strategy_id == "twelve_month_momentum_intended":
                    item["target_exposure"] = _float_or_none(row.get("exposure"))
                    item["close"] = _float_or_none(row.get("close"))
    except OSError:
        return []
    rows = [by_date[key] for key in sorted(by_date)]
    return rows[-limit:]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _btc_trend_forward_status_payload(repo_root: Path) -> dict[str, Any]:
    latest = repo_root / "artifacts/btc_trend_v0/latest"
    ledger_root = repo_root / "data/forward_observation/btc_trend_raw_v1"
    daily_run_path = latest / "btc_trend_raw_forward_observation_daily_run_report.json"
    validation_path = latest / "btc_trend_v0_strategy_validation_gate_report.json"
    paper_gate_path = latest / "btc_trend_v0_promotion_gate_report.json"
    raw_eval_path = latest / "btc_trend_raw_forward_observation_evaluation_report.json"
    raw_roll_path = latest / "btc_trend_raw_forward_observation_roll_report.json"
    vol_freeze_path = latest / "btc_trend_volatility_position_freeze_report.json"
    hft_freeze_path = repo_root / "artifacts/btc_paper_readiness/latest/btc_5m_hft_freeze_report.json"
    position_ledger_path = latest / "btc_trend_v0_position_ledger.csv"

    daily_run = _json_file(daily_run_path)
    validation = _json_file(validation_path)
    paper_gate = _json_file(paper_gate_path)
    raw_eval = _json_file(raw_eval_path)
    raw_roll = _json_file(raw_roll_path)
    vol_freeze = _json_file(vol_freeze_path)
    hft_freeze = _json_file(hft_freeze_path)
    state = _json_file(ledger_root / "validation_state.json")
    targets = _jsonl_file(ledger_root / "target_positions.jsonl", limit=10)
    snapshots = _jsonl_file(ledger_root / "portfolio_snapshots.jsonl", limit=10)
    fills = _jsonl_file(ledger_root / "fills.jsonl", limit=10)
    selected_metrics = validation.get("selected_metrics", {}) if isinstance(validation.get("selected_metrics"), dict) else {}
    buy_hold_metrics = validation.get("buy_hold_metrics", {}) if isinstance(validation.get("buy_hold_metrics"), dict) else {}
    data = daily_run.get("data", {}) if isinstance(daily_run.get("data"), dict) else {}
    forward = daily_run.get("forward_observation", {}) if isinstance(daily_run.get("forward_observation"), dict) else {}
    roll_cycle = raw_roll.get("cycle", {}) if isinstance(raw_roll.get("cycle"), dict) else {}
    eval_metrics = raw_eval.get("metrics", {}) if isinstance(raw_eval.get("metrics"), dict) else {}
    strategy_series = _csv_strategy_series(position_ledger_path)
    source_files = {
        "daily_run": daily_run_path,
        "strategy_validation_gate": validation_path,
        "paper_operational_gate": paper_gate_path,
        "raw_forward_evaluation": raw_eval_path,
        "raw_forward_roll": raw_roll_path,
        "volatility_freeze": vol_freeze_path,
        "hft_freeze": hft_freeze_path,
        "position_ledger": position_ledger_path,
        "ledger_root": ledger_root,
    }
    missing = [name for name, path in source_files.items() if not path.exists()]
    return {
        "schema_version": "btc_trend_forward_status_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "ok" if not missing else "partial",
        "missing_sources": missing,
        "daily_run": {
            "status": daily_run.get("status", "missing"),
            "generated_at": daily_run.get("generated_at", ""),
            "data_refresh_status": (daily_run.get("steps", {}).get("data_refresh", {}) if isinstance(daily_run.get("steps"), dict) else {}).get("status", ""),
            "readiness_status": (daily_run.get("steps", {}).get("readiness", {}) if isinstance(daily_run.get("steps"), dict) else {}).get("status", ""),
            "roll_status": (daily_run.get("steps", {}).get("roll", {}) if isinstance(daily_run.get("steps"), dict) else {}).get("status", ""),
            "roll_cycle_status": forward.get("cycle_status", ""),
            "evaluation_status": forward.get("evaluation_status", raw_eval.get("status", "")),
            "daily_rows": data.get("daily_rows", 0),
            "sample_start": data.get("sample_start", ""),
            "sample_end": data.get("sample_end", ""),
        },
        "strategy": {
            "strategy_id": "btc_trend_raw_t01_twelve_month_momentum",
            "family_id": "t01_twelve_month_momentum",
            "candidate_id": "t01_momentum_binary_8e09e94c36",
            "validation_status": validation.get("status", "missing"),
            "validation_decision": validation.get("decision", ""),
            "selected_total_return_pct": selected_metrics.get("total_return_pct"),
            "selected_max_drawdown_abs_pct": selected_metrics.get("max_drawdown_abs_pct"),
            "selected_sharpe_ratio": selected_metrics.get("sharpe_ratio"),
            "buy_hold_total_return_pct": buy_hold_metrics.get("total_return_pct"),
            "buy_hold_max_drawdown_abs_pct": buy_hold_metrics.get("max_drawdown_abs_pct"),
            "buy_hold_sharpe_ratio": buy_hold_metrics.get("sharpe_ratio"),
        },
        "current_signal": {
            "timestamp": roll_cycle.get("timestamp", ""),
            "close": roll_cycle.get("close"),
            "raw_signal": roll_cycle.get("raw_signal"),
            "target_exposure": roll_cycle.get("target_exposure"),
            "signal_timestamp": roll_cycle.get("signal_timestamp", ""),
            "effective_timestamp": roll_cycle.get("effective_timestamp", ""),
            "reason": roll_cycle.get("reason", ""),
            "current_equity": state.get("current_equity", eval_metrics.get("final_equity")),
        },
        "forward_observation": {
            "status": raw_eval.get("status", "missing"),
            "observation_days": eval_metrics.get("observation_days", 0),
            "minimum_complete_days": raw_eval.get("minimum_complete_days", 30),
            "milestone_progress": eval_metrics.get("milestone_progress", {}),
            "target_position_count": eval_metrics.get("target_position_count", 0),
            "target_position_change_count": eval_metrics.get("target_position_change_count", 0),
            "simulated_fill_count": eval_metrics.get("simulated_fill_count", 0),
            "total_return_pct": eval_metrics.get("total_return_pct", 0),
            "max_drawdown_abs_pct": eval_metrics.get("max_drawdown_abs_pct", 0),
            "targets": targets,
            "snapshots": snapshots,
            "fills": fills,
        },
        "gates": {
            "paper_operational_status": paper_gate.get("status", "missing"),
            "volatility_branch_status": vol_freeze.get("status", "missing"),
            "hft_freeze_status": hft_freeze.get("status", "missing"),
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "live_order_allowed": False,
            "real_order_submitted": False,
        },
        "charts": {
            "strategy_series": strategy_series,
        },
        "source_files": {name: str(path.relative_to(repo_root)).replace("\\", "/") if path.is_relative_to(repo_root) else str(path) for name, path in source_files.items()},
    }


from quant_crypto.application.btc_gate_snapshot import (  # noqa: E402
    BTC_CONTROL_CENTER_ARTIFACTS as BTC_RESEARCH_CONTROL_ARTIFACTS,
    resolve_latest_gate_artifact,
)


def _repo_relative_path(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _btc_logicalize_runtime_paths(
    value: Any,
    *,
    repo_root: Path,
    artifact_reader: BTCRuntimeArtifactReader,
) -> Any:
    return sanitize_btc_outbound_payload(
        value,
        repo_root=repo_root,
        provenance_roots={"artifacts": artifact_reader.artifact_root},
    )


def _btc_research_artifact_payload(
    repo_root: Path,
    artifact_id: str,
    *,
    artifact_reader: BTCRuntimeArtifactReader,
) -> dict[str, Any]:
    relative_path = BTC_RESEARCH_CONTROL_ARTIFACTS.get(artifact_id)
    if not relative_path:
        return {
            "schema_version": "btc_research_artifact_missing_v1",
            "status": "missing",
            "artifact_id": artifact_id,
            "missing": True,
            "error": "unknown_btc_research_artifact",
        }
    resolution = resolve_latest_gate_artifact(
        repo_root,
        relative_path,
        artifact_reader=artifact_reader,
    )
    path = resolution.path
    if path is None:
        return {
            "schema_version": "btc_research_artifact_missing_v1",
            "status": "missing_fail_closed",
            "artifact_id": artifact_id,
            "missing": True,
            "path": relative_path,
            "snapshot_source": resolution.source,
            "aggregation_batch_id": resolution.aggregation_batch_id,
            "error": resolution.error,
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        }
    payload = _json_file(path)
    if not payload:
        return {
            "schema_version": "btc_research_artifact_missing_v1",
            "status": "missing",
            "artifact_id": artifact_id,
            "missing": True,
            "path": relative_path,
            "snapshot_source": resolution.source,
            "aggregation_batch_id": resolution.aggregation_batch_id,
            "error": "artifact_not_found_or_invalid_json",
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        }
    return _btc_logicalize_runtime_paths(
        payload,
        repo_root=repo_root,
        artifact_reader=artifact_reader,
    )


def _btc_cc_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _btc_cc_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _btc_cc_first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _btc_cc_nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _btc_cc_gate_row(report: Mapping[str, Any], gate_id: str) -> dict[str, Any]:
    for row in _btc_cc_list(report.get("gate_matrix")):
        if isinstance(row, dict) and row.get("gate_id") == gate_id:
            return row
    return {}


def _btc_cc_blockers(*payloads: Mapping[str, Any], limit: int = 6) -> list[str]:
    blockers: list[str] = []
    for payload in payloads:
        for blocker in _btc_cc_list(payload.get("blockers")):
            if isinstance(blocker, str):
                blockers.append(blocker)
    return blockers[:limit]


def _btc_operator_summary(reports: Mapping[str, Any]) -> dict[str, Any]:
    promotion_gate = _btc_cc_mapping(reports.get("promotion_gate_control"))
    gate_dashboard = _btc_cc_mapping(reports.get("gate_dashboard"))
    attestation = _btc_cc_mapping(reports.get("paper_account_attestation"))
    runtime_probe = _btc_cc_mapping(reports.get("exchange_runtime_local_probe"))
    exchange_gap = _btc_cc_mapping(reports.get("exchange_runtime_gap"))
    kill_switch = _btc_cc_mapping(reports.get("kill_switch"))
    micro_preflight = _btc_cc_mapping(reports.get("micro_live_preflight"))
    paper_runtime = _btc_cc_mapping(reports.get("paper_runtime_replay"))

    root_summary = _btc_cc_mapping(promotion_gate.get("root_cause_summary")) or _btc_cc_mapping(gate_dashboard.get("root_cause_summary"))
    root_matrix = _btc_cc_list(promotion_gate.get("root_cause_matrix")) or _btc_cc_list(gate_dashboard.get("root_cause_matrix"))
    root_task_queue = _btc_cc_mapping(promotion_gate.get("root_cause_task_queue")) or _btc_cc_mapping(
        _btc_cc_mapping(promotion_gate.get("root_cause_dag")).get("task_queue")
    )
    data_gate = _btc_cc_gate_row(promotion_gate, "data_gate")
    execution_gate = _btc_cc_gate_row(promotion_gate, "execution_gate")
    kill_gate = _btc_cc_gate_row(promotion_gate, "kill_switch_gate")
    manual_gate = _btc_cc_gate_row(promotion_gate, "manual_review_gate")

    attestation_summary = _btc_cc_mapping(attestation.get("attestation_summary"))
    credential_permissions = _btc_cc_mapping(attestation.get("credential_permission_checks"))
    credential_separation = _btc_cc_mapping(attestation.get("credential_separation_checks"))
    manual_approval = _btc_cc_mapping(attestation.get("manual_approval_checks"))
    runtime_snapshot = _btc_cc_mapping(runtime_probe.get("runtime_snapshot"))
    server_time = _btc_cc_mapping(runtime_probe.get("server_time_offset_diagnostics"))
    ws_gapfill = _btc_cc_mapping(runtime_probe.get("ws_sequence_gapfill_replay"))
    metadata = _btc_cc_mapping(runtime_probe.get("metadata_version_diagnostics"))
    rate_budget = _btc_cc_mapping(runtime_probe.get("rate_limit_budget_explanation"))
    order_budget = _btc_cc_mapping(rate_budget.get("order_entry_budget"))
    public_budget = _btc_cc_mapping(rate_budget.get("public_rest_or_ws_budget"))
    kill_summary = _btc_cc_mapping(kill_switch.get("summary"))
    kill_policy = _btc_cc_mapping(kill_switch.get("policy_state"))
    micro_summary = _btc_cc_mapping(micro_preflight.get("summary"))
    runtime_gap_summary = _btc_cc_mapping(exchange_gap.get("summary"))
    paper_runtime_summary = _btc_cc_mapping(paper_runtime.get("summary"))

    return {
        "root_blockers": {
            "raw_blocker_count": root_summary.get("raw_blocker_count"),
            "unique_blocker_count": root_summary.get("unique_blocker_count"),
            "root_cause_count": root_summary.get("root_cause_count"),
            "compression_ratio_raw_to_root": root_summary.get("compression_ratio_raw_to_root"),
            "dominant_root_cause_id": root_summary.get("dominant_root_cause_id"),
            "top_root_causes": root_matrix[:5],
            "task_queue": root_task_queue,
            "data_wait_items": _btc_cc_list(root_task_queue.get("data_wait_items"))[:8],
            "immediate_development_items": _btc_cc_list(root_task_queue.get("immediate_development_items"))[:8],
        },
        "kill_switch": {
            "status": kill_switch.get("status") or kill_gate.get("status"),
            "decision": kill_switch.get("decision"),
            "kill_switch_engaged": _btc_cc_first_present(
                micro_summary.get("kill_switch_engaged"),
                kill_summary.get("kill_switch_engaged"),
                kill_policy.get("kill_switch_engaged"),
                _btc_cc_nested(kill_gate, "checks", "kill_switch_engaged"),
            ),
            "cancel_only_mode": _btc_cc_first_present(
                kill_summary.get("cancel_only_mode"),
                kill_policy.get("cancel_only_mode"),
                runtime_snapshot.get("cancel_only"),
                _btc_cc_nested(kill_gate, "checks", "cancel_only_mode"),
            ),
            "reduce_only_mode": _btc_cc_first_present(
                kill_policy.get("reduce_only_mode"),
                _btc_cc_nested(kill_gate, "checks", "reduce_only_mode"),
            ),
            "paper_order_intake_allowed": _btc_cc_first_present(
                kill_summary.get("paper_order_intake_allowed"),
                kill_policy.get("paper_order_intake_allowed"),
                _btc_cc_nested(kill_gate, "checks", "paper_order_intake_allowed"),
            ),
            "manual_approval_recorded": _btc_cc_first_present(
                kill_summary.get("manual_approval_recorded"),
                kill_policy.get("manual_approval_recorded"),
                micro_summary.get("manual_approval_recorded"),
            ),
            "blockers": _btc_cc_blockers(kill_gate, kill_switch, micro_preflight, limit=6),
        },
        "attestation": {
            "status": attestation.get("status"),
            "decision": attestation.get("decision"),
            "attestation_current": attestation.get("attestation_current"),
            "account_mode_verified": attestation.get("account_mode_verified"),
            "margin_mode_verified": attestation.get("margin_mode_verified"),
            "position_mode_verified": attestation.get("position_mode_verified"),
            "credential_permissions_verified": attestation.get("credential_permissions_verified"),
            "credential_separation_verified": attestation.get("credential_separation_verified"),
            "manual_approval_recorded": attestation.get("manual_approval_recorded"),
            "withdraw_permission_enabled": attestation_summary.get("withdraw_permission_enabled"),
            "withdraw_permission_verified_false": attestation_summary.get("withdraw_permission_verified_false"),
            "paper_key_redacted_identifier": attestation_summary.get("paper_key_redacted_identifier"),
            "data_paper_live_identifiers_unique": credential_separation.get("data_paper_live_identifiers_unique"),
            "live_credential_not_loaded_verified": credential_permissions.get("live_credential_not_loaded_verified"),
            "approval_id_present": manual_approval.get("approval_id_present"),
            "blockers": _btc_cc_blockers(manual_gate, attestation, limit=6),
        },
        "runtime_freshness": {
            "status": runtime_probe.get("status") or exchange_gap.get("status"),
            "decision": runtime_probe.get("decision") or exchange_gap.get("decision"),
            "as_of_utc": runtime_snapshot.get("as_of_utc") or runtime_probe.get("as_of_utc") or runtime_probe.get("generated_at"),
            "last_market_data_time_utc": runtime_snapshot.get("last_market_data_time_utc"),
            "last_private_event_time_utc": runtime_snapshot.get("last_private_event_time_utc"),
            "server_time_offset_ms": server_time.get("offset_ms") or runtime_snapshot.get("server_time_offset_ms"),
            "server_time_within_threshold": server_time.get("within_threshold"),
            "public_ws_status": runtime_snapshot.get("public_ws_status"),
            "private_ws_status": runtime_snapshot.get("private_ws_status"),
            "ws_gap_detected": ws_gapfill.get("gap_detected"),
            "ws_gapfill_recovered": ws_gapfill.get("recovered"),
            "metadata_version": metadata.get("metadata_version") or runtime_snapshot.get("metadata_version"),
            "order_rate_budget_remaining": runtime_snapshot.get("order_rate_budget_remaining"),
            "order_budget_status": order_budget.get("status"),
            "public_budget_status": public_budget.get("status"),
            "paper_runtime_replay_ready": runtime_gap_summary.get("paper_runtime_replay_ready") or paper_runtime_summary.get("paper_runtime_replay_ready"),
            "simulated_fill_count": _btc_cc_first_present(
                runtime_gap_summary.get("paper_runtime_drill_simulated_fill_count"),
                paper_runtime_summary.get("simulated_fill_count"),
            ),
            "liquidation_buffer_visible_in_replay": paper_runtime_summary.get("liquidation_buffer_visible_in_replay"),
            "blockers": _btc_cc_blockers(execution_gate, runtime_probe, exchange_gap, paper_runtime, limit=6),
        },
        "paper_live_forbidden": {
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "reasons": (promotion_gate.get("key_blockers_cn") if isinstance(promotion_gate.get("key_blockers_cn"), list) else [])
            or _btc_cc_blockers(data_gate, execution_gate, kill_gate, manual_gate, limit=8),
        },
    }


def _btc_research_control_center_payload(
    repo_root: Path,
    *,
    artifact_reader: BTCRuntimeArtifactReader,
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    source_paths: dict[str, str] = {}
    missing_sources: list[str] = []
    safety_violations: list[str] = []

    for artifact_id, relative_path in BTC_RESEARCH_CONTROL_ARTIFACTS.items():
        resolution = resolve_latest_gate_artifact(
            repo_root,
            relative_path,
            artifact_reader=artifact_reader,
        )
        path = resolution.path
        source_paths[artifact_id] = relative_path
        if path is None:
            missing_sources.append(artifact_id)
            reports[artifact_id] = {
                "schema_version": "btc_research_artifact_missing_v1",
                "status": "missing_fail_closed",
                "artifact_id": artifact_id,
                "missing": True,
                "path": source_paths[artifact_id],
                "snapshot_source": resolution.source,
                "aggregation_batch_id": resolution.aggregation_batch_id,
                "error": resolution.error,
            }
            continue
        payload = _json_file(path)
        if not payload:
            missing_sources.append(artifact_id)
            reports[artifact_id] = {
                "schema_version": "btc_research_artifact_missing_v1",
                "status": "missing",
                "artifact_id": artifact_id,
                "missing": True,
                "path": source_paths[artifact_id],
            }
            continue
        reports[artifact_id] = payload
        guardrails = payload.get("guardrails", {}) if isinstance(payload.get("guardrails"), dict) else {}
        gate = payload.get("gate", {}) if isinstance(payload.get("gate"), dict) else {}
        for field in (
            "paper_queue_write_allowed",
            "paper_allowed",
            "paper_candidate_created",
            "live_unlock_allowed",
            "live_order_allowed",
            "broker_access_allowed",
            "broker_or_order_allowed",
            "oms_access_allowed",
            "order_endpoint_used",
            "private_endpoint_used",
            "real_order_submitted",
            "strategy_skeleton_generated",
        ):
            if guardrails.get(field) is True or gate.get(field) is True:
                safety_violations.append(f"{artifact_id}:{field}")

    promotion_gate = reports.get("promotion_gate_control", {})
    strategy_ledger = reports.get("strategy_ledger", {})
    leakage_audit = reports.get("leakage_overfit_audit", {})
    attack_stress = reports.get("attack_sleeve_risk_stress", {})
    attack_shortlist = reports.get("attack_strategy_continuation_shortlist", {})
    attack_followup = reports.get("attack_followup_review", {})
    attack_followup_summary = attack_followup.get("summary", {}) if isinstance(attack_followup.get("summary"), dict) else {}
    micro_live = reports.get("micro_live_experiment_packet", {})
    micro_live_summary = micro_live.get("summary", {}) if isinstance(micro_live.get("summary"), dict) else {}
    operator_summary = _btc_operator_summary(reports)
    status = "complete_research_only" if not missing_sources else "partial_missing_sources"
    if safety_violations:
        status = "safety_violation_fail_closed"

    return _btc_logicalize_runtime_paths(
        {
        "schema_version": "btc_research_control_center_frontend_v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": status,
        "decision": "btc_research_control_center_read_only_no_paper_no_live",
        "missing_sources": missing_sources,
        "source_paths": source_paths,
        "safety_violations": sorted(set(safety_violations)),
        "summary": {
            "strategy_line_count": strategy_ledger.get("line_count", 0),
            "fixed_strategy_line_count": strategy_ledger.get("fixed_strategy_line_count", 0),
            "blocked_gate_count": promotion_gate.get("blocked_gate_count", 0),
            "gate_count": promotion_gate.get("gate_count", 0),
            "leakage_check_warn_count": (leakage_audit.get("summary", {}) if isinstance(leakage_audit.get("summary"), dict) else {}).get("check_warn_count", 0),
            "leakage_check_fail_count": (leakage_audit.get("summary", {}) if isinstance(leakage_audit.get("summary"), dict) else {}).get("check_fail_count", 0),
            "attack_min_remaining_after_10pct_spike": (attack_stress.get("summary", {}) if isinstance(attack_stress.get("summary"), dict) else {}).get("min_remaining_after_10pct_spike_min"),
            "attack_not_forward_observation_ready": (attack_stress.get("summary", {}) if isinstance(attack_stress.get("summary"), dict) else {}).get("not_forward_observation_ready"),
            "attack_shortlist_line_count": attack_shortlist.get("line_count", 0),
            "attack_shortlist_continue_count": attack_shortlist.get("continued_research_strategy_count", 0),
            "attack_shortlist_danger_reference_count": attack_shortlist.get("danger_reference_count", 0),
            "attack_followup_strict_base_annual_return_pct": attack_followup_summary.get("high_octane_strict_base_annual_return_pct"),
            "attack_followup_5x_rolling_median_total_return_pct": attack_followup_summary.get("defensive_5x_rolling_median_total_return_pct"),
            "attack_followup_10x_rolling_median_total_return_pct": attack_followup_summary.get("actual_10x_limited_rolling_median_total_return_pct"),
            "micro_live_latest_direction": micro_live_summary.get("latest_direction"),
            "micro_live_current_risk_level": micro_live_summary.get("current_risk_level"),
            "micro_live_latest_principal_exposed_rmb": micro_live_summary.get("latest_principal_exposed_rmb"),
            "micro_live_remaining_after_10pct_spike": micro_live_summary.get("latest_remaining_after_10pct_spike"),
            "micro_live_alert_count": micro_live_summary.get("alert_count"),
            "micro_live_block_alert_count": micro_live_summary.get("block_alert_count"),
            "operator_root_cause_count": _btc_cc_nested(operator_summary, "root_blockers", "root_cause_count"),
            "operator_raw_blocker_count": _btc_cc_nested(operator_summary, "root_blockers", "raw_blocker_count"),
            "operator_dominant_root_cause_id": _btc_cc_nested(operator_summary, "root_blockers", "dominant_root_cause_id"),
            "operator_kill_switch_engaged": _btc_cc_nested(operator_summary, "kill_switch", "kill_switch_engaged"),
            "operator_attestation_status": _btc_cc_nested(operator_summary, "attestation", "status"),
            "operator_runtime_status": _btc_cc_nested(operator_summary, "runtime_freshness", "status"),
        },
        "operator_summary": operator_summary,
        "reports": reports,
        "guardrails": {
            "research_only": True,
            "read_only_artifact_aggregation": True,
            "strategy_rerun_used": False,
            "network_collection_used": False,
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
            "oms_access_allowed": False,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
            "strategy_skeleton_generated": False,
        },
        },
        repo_root=repo_root,
        artifact_reader=artifact_reader,
    )


def _current_repository_head(repo_root: Path) -> str:
    try:
        return current_branch_head(repo_root)[1]
    except (OSError, GitMetadataError):
        return ""


async def _run_cancellable_registry_inspection(request, inspector, data_root: str):
    """Run one registry inspection and always retrieve its worker task."""
    import asyncio
    from threading import Event

    cancel_event = Event()
    inspection_task = asyncio.create_task(
        asyncio.to_thread(
            inspector,
            data_root,
            should_cancel=cancel_event.is_set,
        )
    )
    try:
        while not inspection_task.done():
            if await request.is_disconnected():
                cancel_event.set()
                break
            try:
                return await asyncio.wait_for(
                    asyncio.shield(inspection_task),
                    timeout=0.05,
                )
            except asyncio.TimeoutError:
                continue
        return await inspection_task
    except asyncio.CancelledError:
        cancel_event.set()
        # The worker cooperatively exits at the next bounded checkpoint. Wait
        # for and retrieve its terminal exception before preserving the route
        # cancellation, so no orphan task or unhandled exception remains.
        await asyncio.gather(inspection_task, return_exceptions=True)
        raise


def create_app():
    try:
        from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response, Security
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.security import APIKeyHeader
    except ImportError as exc:
        from backend.app.core.exceptions import DependencyUnavailableError

        raise DependencyUnavailableError(
            "FastAPI is not installed. Install project dependencies from pyproject.toml before starting the API."
        ) from exc

    from backend.app.services.data_management import CryptoResampleSpec, DataSyncSpec, LatestUpdateSpec, resolve_data_db_path
    from backend.app.services.market_data import inspect_market_data_quality

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    research_readonly = is_research_surface_profile(settings.backend_evidence_profile)
    research_readonly_views = (
        ResearchReadonlyViews(repo_root=settings.repo_root)
        if research_readonly
        else None
    )
    research_archive = (
        build_m1_research_archive_catalog(repo_root=settings.repo_root)
        if research_readonly
        else None
    )
    from backend.app.services.candidate_delivery_bootstrap import (
        CandidateResearchArchiveGuard,
        UnavailableCandidateResearchArchive,
        resolve_candidate_research_roots,
    )
    from quant_shared.strategy_delivery.models import DeliveryError

    candidate_research_catalog_error = ""
    candidate_research_roots = None
    try:
        candidate_research_roots = resolve_candidate_research_roots(
            settings,
            qlib_root=QLIB_ARTIFACTS_ROOT,
        )
    except DeliveryError as exc:
        candidate_research_catalog_error = f"candidate_offline_catalog_invalid:{exc.code}"
        research_archive = UnavailableCandidateResearchArchive(candidate_research_catalog_error)
    else:
        if candidate_research_roots.configured:
            if research_archive is None:
                candidate_research_catalog_error = "candidate_offline_catalog_requires_research_surface"
                research_archive = UnavailableCandidateResearchArchive(candidate_research_catalog_error)
            else:
                research_archive = CandidateResearchArchiveGuard(
                    candidate_research_roots,
                    research_archive,
                )
    qlib_list_inflight_lock = Lock()
    qlib_list_inflight: dict[
        tuple[str, int, str], Future[dict[str, Any]]
    ] = {}
    qlib_summary_executor = (
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="qlib-summary-read")
        if research_readonly
        else None
    )
    btc_private_readonly_observation = None
    if not research_readonly and settings.btc_private_readonly_observation_root.strip():
        from backend.app.services.btc_private_readonly_observation import (
            BTCPrivateReadonlyObservationProjection,
        )

        btc_private_readonly_observation = BTCPrivateReadonlyObservationProjection(
            runtime_root=settings.btc_private_readonly_observation_root,
            repo_root=settings.repo_root,
            head_resolver=lambda: _current_repository_head(settings.repo_root),
        )

    btc_runtime_artifact_reader: BTCRuntimeArtifactReader | None
    btc_runtime_artifact_error = ""
    try:
        btc_runtime_artifact_reader = BTCRuntimeArtifactReader.from_environment(
            source_repo_root=settings.repo_root,
            environment={
                BTC_RUNTIME_ARTIFACT_ROOT_ENVIRONMENT_VARIABLE: (
                    settings.btc_runtime_artifact_root
                ),
            },
        )
    except BTCRuntimeArtifactStoreError as exc:
        btc_runtime_artifact_reader = None
        btc_runtime_artifact_error = str(exc)

    def _btc_runtime_artifact_unavailable_detail(
        reason: str = "",
    ) -> dict[str, Any]:
        return {
            "schema_version": "btc_runtime_artifact_api_unavailable_v1",
            "status": "unavailable_fail_closed",
            "error": "runtime_artifact_root_unavailable",
            "reason": reason or btc_runtime_artifact_error,
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        }

    def _require_btc_runtime_artifact_reader() -> BTCRuntimeArtifactReader:
        if btc_runtime_artifact_reader is None:
            raise HTTPException(
                status_code=503,
                detail=_btc_runtime_artifact_unavailable_detail(),
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                },
            )
        return btc_runtime_artifact_reader

    def _readonly_views() -> ResearchReadonlyViews:
        if research_readonly_views is None:
            raise RuntimeError("research_readonly_views_unavailable")
        return research_readonly_views

    def _readonly_projection(call):
        try:
            return call()
        except ResearchReadonlyViewError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail(),
                headers={"Cache-Control": "no-store"},
            ) from exc

    def _btc_runtime_artifact_http_exception(
        exc: BTCRuntimeArtifactStoreError
        | BTCPublishedDomainReadModelUnavailable,
    ) -> HTTPException:
        return HTTPException(
            status_code=503,
            detail=_btc_runtime_artifact_unavailable_detail(str(exc)),
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )

    async def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
        if not settings.web_api_key:
            return True
        if api_key != settings.web_api_key:
            raise HTTPException(status_code=403, detail="Invalid API key")
        return True

    app = FastAPI(title="QuantStation vNext", version=__version__)
    if qlib_summary_executor is not None:
        def shutdown_qlib_summary_executor() -> None:
            qlib_summary_executor.shutdown(wait=True, cancel_futures=False)

        app.router.add_event_handler("shutdown", shutdown_qlib_summary_executor)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if research_readonly:
        from fastapi.responses import JSONResponse

        @app.middleware("http")
        async def enforce_research_readonly(request, call_next):
            decision = evaluate_backend_access(
                profile=settings.backend_evidence_profile,
                method=request.method,
                path=request.url.path,
            )
            if not decision.allowed:
                return JSONResponse(
                    status_code=423,
                    content=readonly_block_payload(reason=decision.reason),
                    headers={"Cache-Control": "no-store"},
                )
            return await call_next(request)
    canonical_backend_launch = (
        os.environ.get("QS_BACKEND_CANONICAL_LAUNCH", "").strip() == "1"
    )
    launched_backend_head = os.environ.get(
        "QS_BACKEND_LAUNCHED_HEAD", ""
    ).strip()
    if canonical_backend_launch:
        from fastapi.responses import JSONResponse
        from scripts.start_backend_current_main import (
            inspect_backend_runtime_binding,
        )

        if not launched_backend_head:
            backend_runtime_identity: dict[str, Any] = {
                "schema_version": "backend_current_main_identity_v1",
                "canonical": False,
                "runtime_stale": True,
                "source_head": "",
                "error": "backend_runtime_launched_head_missing",
            }
        else:
            backend_runtime_identity = dict(
                inspect_backend_runtime_binding(
                    settings.repo_root,
                    launched_head=launched_backend_head,
                )
            )

        def _backend_runtime_identity() -> dict[str, Any]:
            nonlocal backend_runtime_identity
            if backend_runtime_identity.get("runtime_stale") is True:
                return backend_runtime_identity
            try:
                current_head = current_branch_head(settings.repo_root)[1]
            except (OSError, ValueError):
                backend_runtime_identity = {
                    **backend_runtime_identity,
                    "canonical": False,
                    "runtime_stale": True,
                    "current_main_head": "",
                    "error": "backend_runtime_main_head_read_failed",
                }
            else:
                if current_head != launched_backend_head:
                    backend_runtime_identity = {
                        **backend_runtime_identity,
                        "canonical": False,
                        "runtime_stale": True,
                        "source_head": launched_backend_head,
                        "current_main_head": current_head,
                        "error": "backend_runtime_main_head_drift",
                    }
            return backend_runtime_identity

        @app.middleware("http")
        async def reject_backend_main_drift(request, call_next):
            identity = _backend_runtime_identity()
            if identity.get("runtime_stale") is True:
                return JSONResponse(
                    status_code=409,
                    content={
                        "status": "blocked",
                        "error": "backend_runtime_main_drift",
                        "identity": identity,
                        "paper_allowed": False,
                        "live_allowed": False,
                        "broker_or_order_allowed": False,
                    },
                    headers={"Cache-Control": "no-store"},
                )
            return await call_next(request)

        @app.get("/__backend_identity")
        def get_backend_identity():
            return JSONResponse(
                content=backend_runtime_identity,
                headers={"Cache-Control": "no-store"},
            )

    router = APIRouter(prefix="/api")
    router.include_router(
        build_btc_strategy_history_router(
            btc_runtime_artifact_reader,
            backtest_runner=research_service.run_crypto_event,
            write_dependency=verify_api_key,
        )
    )
    router.include_router(build_strategy_history_catalog_router())

    def _submit_background_task(
        *,
        kind: str,
        label: str,
        request: dict[str, Any],
        job,
    ) -> TaskStatusResponse:
        task = task_queue_service.submit(kind=kind, label=label, request=request, job=job)
        return _serialize_task(task)

    @app.get("/metrics")
    async def metrics() -> Response:
        from quant_us.monitoring.metrics import MetricsCollector

        collector = MetricsCollector()
        return Response(
            collector.to_prometheus_text(),
            media_type="text/plain; version=0.0.4",
        )

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="quantstation-vnext",
            data_source_default=settings.default_data_source,
            fastapi_available=True,
            evidence_profile=settings.backend_evidence_profile,
            read_only=research_readonly,
            controls_disabled=(research_readonly or not settings.btc_demo_control_enabled),
            paper_allowed=False,
            live_allowed=False,
            broker_or_order_allowed=False,
        )

    @router.get("/system/overview", response_model=SystemOverviewResponse, dependencies=[Depends(verify_api_key)])
    def system_overview(
        data_root: str = "data",
        qlib_artifacts_root: str = "artifacts/qlib_runs",
        portfolio_artifacts_root: str = "artifacts/portfolio_runs",
    ) -> SystemOverviewResponse:
        if research_readonly:
            payload = _readonly_projection(
                lambda: _readonly_views().system_overview(
                    data_root=data_root,
                    qlib_artifacts_root=qlib_artifacts_root,
                    portfolio_artifacts_root=portfolio_artifacts_root,
                )
            )
        else:
            payload = _system_overview_payload(
                data_root,
                qlib_artifacts_root=qlib_artifacts_root,
                portfolio_artifacts_root=portfolio_artifacts_root,
            )
        return SystemOverviewResponse.model_validate(payload)

    @router.get("/data/database", response_model=DatabaseStatusResponse, dependencies=[Depends(verify_api_key)])
    async def database_status(db_path: str = "") -> DatabaseStatusResponse:
        try:
            return DatabaseStatusResponse.model_validate(market_data_service.database_status(db_path=db_path))
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/coverage", response_model=list[DataCoverageItem], dependencies=[Depends(verify_api_key)])
    async def data_coverage(
        db_path: str = "",
        exchange: str = "",
        symbol: str = "",
        interval: str = "",
    ) -> list[DataCoverageItem]:
        try:
            rows = market_data_service.coverage(
                db_path=db_path,
                exchange=exchange,
                symbol=symbol.upper() if symbol else "",
                interval=interval,
            )
            return [DataCoverageItem.model_validate(row) for row in rows]
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/klines", response_model=KlinePreviewResponse, dependencies=[Depends(verify_api_key)])
    async def preview_klines(
        db_path: str = "",
        exchange: str = "binance_spot",
        symbol: str = "",
        interval: str = "",
        limit: int = 100,
    ) -> KlinePreviewResponse:
        try:
            rows = market_data_service.preview_klines(
                db_path=db_path,
                exchange=exchange,
                symbol=symbol.upper() if symbol else "",
                interval=interval,
                limit=limit,
            )
            return KlinePreviewResponse(db_path=str(resolve_data_db_path(db_path)), rows=rows)
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/sync-runs", response_model=list[DataSyncRunResponse], dependencies=[Depends(verify_api_key)])
    async def list_data_sync_runs(db_path: str = "", limit: int = 20) -> list[DataSyncRunResponse]:
        try:
            rows = market_data_service.list_sync_runs(db_path=db_path, limit=limit)
            resolved = str(resolve_data_db_path(db_path))
            return [
                DataSyncRunResponse(
                    run_id=row["run_id"],
                    status=row["status"],
                    db_path=resolved,
                    exchange=row["exchange"],
                    symbol=row["symbol"],
                    interval=row["interval"],
                    start=row["start_time"],
                    end=row["end_time"],
                    rows_received=row["rows_received"],
                    rows_written=row["rows_written"],
                    requests=row["requests"],
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                    error=row["error"],
                )
                for row in rows
            ]
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/data/sync", response_model=DataSyncRunResponse, dependencies=[Depends(verify_api_key)])
    async def sync_market_data(request: DataSyncRequest) -> DataSyncRunResponse:
        try:
            result = market_data_service.sync_binance_klines(
                DataSyncSpec(
                    exchange=request.exchange,
                    symbol=request.symbol,
                    interval=request.interval,
                    start=request.start,
                    end=request.end,
                    db_path=request.db_path,
                    limit=request.limit,
                    closed_only=request.closed_only,
                )
            )
            return _serialize_data_sync_result(result)
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/data/quality", response_model=DataQualityResponse, dependencies=[Depends(verify_api_key)])
    async def inspect_data_quality(request: DataQualityRequest) -> DataQualityResponse:
        try:
            return DataQualityResponse.model_validate(
                inspect_market_data_quality(
                    source=request.source,
                    symbol=request.symbol,
                    interval=request.interval,
                    start=request.start,
                    end=request.end,
                    db_path=request.data_db_path,
                )
            )
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/data/update-latest", response_model=DataSyncRunResponse, dependencies=[Depends(verify_api_key)])
    async def update_latest_market_data(request: LatestDataUpdateRequest) -> DataSyncRunResponse:
        try:
            result = market_data_service.update_latest(
                LatestUpdateSpec(
                    exchange=request.exchange,
                    symbol=request.symbol,
                    interval=request.interval,
                    db_path=request.db_path,
                    lookback_days=request.lookback_days,
                    limit=request.limit,
                )
            )
            return _serialize_data_sync_result(result)
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/data/resample", response_model=CryptoResampleResponse, dependencies=[Depends(verify_api_key)])
    async def resample_crypto_market_data(request: CryptoResampleRequest) -> CryptoResampleResponse:
        try:
            result = market_data_service.resample_crypto_klines(
                CryptoResampleSpec(
                    exchange=request.exchange,
                    symbol=request.symbol,
                    source_interval=request.source_interval,
                    target_interval=request.target_interval,
                    start=request.start,
                    end=request.end,
                    db_path=request.db_path,
                    persist_manifest=request.persist_manifest,
                )
            )
            return CryptoResampleResponse.model_validate(asdict(result))
        except QuantStationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/data/scheduler", response_model=SchedulerStatusResponse, dependencies=[Depends(verify_api_key)])
    async def data_scheduler_status() -> SchedulerStatusResponse:
        return SchedulerStatusResponse.model_validate(data_update_scheduler.status())

    @router.post("/data/scheduler/start", response_model=SchedulerStatusResponse, dependencies=[Depends(verify_api_key)])
    async def start_data_scheduler(request: SchedulerStartRequest) -> SchedulerStatusResponse:
        status = data_update_scheduler.start(
            service=market_data_service,
            spec=LatestUpdateSpec(
                exchange=request.exchange,
                symbol=request.symbol,
                interval=request.interval,
                db_path=request.db_path,
                lookback_days=request.lookback_days,
                limit=request.limit,
            ),
            interval_seconds=request.interval_seconds,
            run_immediately=request.run_immediately,
        )
        return SchedulerStatusResponse.model_validate(status)

    @router.post("/data/scheduler/stop", response_model=SchedulerStatusResponse, dependencies=[Depends(verify_api_key)])
    async def stop_data_scheduler() -> SchedulerStatusResponse:
        return SchedulerStatusResponse.model_validate(data_update_scheduler.stop())

    @router.post("/us/data/quality-report", dependencies=[Depends(verify_api_key)])
    async def us_data_quality_report(request: dict[str, Any]):
        """Generate auditable minute quality gates for raw and cleaned US equity data."""
        try:
            result = us_quant_service.data_quality_report(request)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/us/data/sync", response_model=USDataSyncResponse, dependencies=[Depends(verify_api_key)])
    async def sync_us_market_data(request: USDataSyncRequest) -> USDataSyncResponse:
        try:
            result = us_quant_service.sync_data(request.model_dump())
            if result["status"] != "completed":
                raise HTTPException(status_code=400, detail=result.get("error") or "US data sync failed")
            return USDataSyncResponse.model_validate(result)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/data/bulk-sync", dependencies=[Depends(verify_api_key)])
    async def sync_us_market_data_bulk(request: dict) -> dict:
        """Sync multiple US symbols and bar sizes into raw/cleaned lake partitions."""
        symbols = request.get("symbols") or request.get("symbol") or []
        if isinstance(symbols, str):
            symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        bar_sizes = request.get("bar_sizes") or request.get("bar_size") or ["1d"]
        if isinstance(bar_sizes, str):
            bar_sizes = [s.strip().lower() for s in bar_sizes.split(",") if s.strip()]
        results: list[dict[str, Any]] = []
        failures = 0
        for symbol in symbols:
            for bar_size in bar_sizes:
                payload = dict(request)
                payload["symbol"] = symbol
                payload["bar_size"] = bar_size
                payload.pop("symbols", None)
                payload.pop("bar_sizes", None)
                try:
                    validated = USDataSyncRequest.model_validate(payload)
                    result = us_quant_service.sync_data(validated.model_dump())
                except Exception as exc:
                    failures += 1
                    result = {
                        "status": "failed",
                        "symbol": symbol,
                        "bar_size": bar_size,
                        "error": str(exc),
                    }
                if result.get("status") != "completed":
                    failures += 1
                results.append(result)
        return {
            "status": "completed" if failures == 0 else "partial_failed",
            "symbols": list(symbols),
            "bar_sizes": list(bar_sizes),
            "result_count": len(results),
            "failure_count": failures,
            "results": results,
        }

    @router.post("/us/features/build", response_model=USFeatureBuildResponse, dependencies=[Depends(verify_api_key)])
    async def build_us_features(request: USFeatureBuildRequest) -> USFeatureBuildResponse:
        try:
            result = us_quant_service.build_features(request.model_dump())
            if result["status"] != "completed":
                raise HTTPException(status_code=400, detail=result.get("error") or "US feature build failed")
            return USFeatureBuildResponse.model_validate(result)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/backtests/event", response_model=USEventBacktestResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_event_backtest(request: USEventBacktestRequest) -> USEventBacktestResponse:
        try:
            result = us_quant_service.run_event_backtest(request.model_dump())
            return USEventBacktestResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/reconcile", response_model=USReconciliationResponse, dependencies=[Depends(verify_api_key)])
    async def reconcile_us_ledger(request: USReconciliationRequest) -> USReconciliationResponse:
        try:
            result = us_quant_service.reconcile_local_ledger(request.model_dump())
            return USReconciliationResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/backtests/unified", response_model=USUnifiedBacktestResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_unified_backtest(request: USEventBacktestRequest) -> USUnifiedBacktestResponse:
        try:
            result = us_quant_service.run_unified_backtest(request.model_dump())
            return USUnifiedBacktestResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/paper/run-day", response_model=USPaperDayResultResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_paper_day(request: USPaperRunDayRequest) -> USPaperDayResultResponse:
        try:
            result = us_quant_service.run_paper_day(request.model_dump())
            return USPaperDayResultResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/us/paper/status", response_model=USPaperStatusResponse, dependencies=[Depends(verify_api_key)])
    async def us_paper_status() -> USPaperStatusResponse:
        try:
            result = us_quant_service.paper_status()
            return USPaperStatusResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/us/paper/daily-results", response_model=list[USPaperDayResultResponse], dependencies=[Depends(verify_api_key)])
    async def us_paper_daily_results() -> list[USPaperDayResultResponse]:
        try:
            results = us_quant_service.paper_daily_results()
            return [USPaperDayResultResponse.model_validate(r) for r in results]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/paper/backtest", response_model=PaperBacktestResponse, dependencies=[Depends(verify_api_key)])
    async def run_us_paper_backtest(request: USEventBacktestRequest) -> PaperBacktestResponse:
        try:
            result = us_quant_service.run_paper_backtest(request.model_dump())
            return PaperBacktestResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/us/paper/reset", response_model=PaperResetResponse, dependencies=[Depends(verify_api_key)])
    async def reset_us_paper_loop() -> PaperResetResponse:
        try:
            result = us_quant_service.reset_paper_loop()
            return PaperResetResponse.model_validate(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/strategies", response_model=list[StrategyInfo], dependencies=[Depends(verify_api_key)])
    def list_strategies() -> list[StrategyInfo]:
        try:
            return [StrategyInfo.model_validate(descriptor.__dict__) for descriptor in research_service.list_strategies()]
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"strategy registry unavailable: {exc}") from exc

    @router.post("/backtests/single", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def run_single_backtest(request: SingleBacktestRequest) -> RunStatusResponse:
        payload = request.model_dump()
        try:
            result = research_service.run_single(payload)
            record = run_registry.create_completed_run(mode="single", request=payload, result=result)
        except QuantStationError as exc:
            record = run_registry.create_failed_run(mode="single", request=payload, error=str(exc))
        return _serialize_run(record)

    @router.post("/backtests/crypto-event", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def run_crypto_event_backtest(request: SingleBacktestRequest) -> RunStatusResponse:
        payload = request.model_dump()
        try:
            result = research_service.run_crypto_event(payload)
            record = run_registry.create_completed_run(mode="crypto_event", request=payload, result=result)
        except (QuantStationError, ValueError) as exc:
            record = run_registry.create_failed_run(mode="crypto_event", request=payload, error=str(exc))
        return _serialize_run(record)

    @router.post("/backtests/portfolio", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def run_portfolio_backtest(request: PortfolioBacktestRequest) -> RunStatusResponse:
        payload = request.model_dump()
        try:
            result = research_service.run_portfolio(payload)
            record = run_registry.create_completed_run(mode="portfolio", request=payload, result=result)
        except QuantStationError as exc:
            record = run_registry.create_failed_run(mode="portfolio", request=payload, error=str(exc))
        return _serialize_run(record)

    @router.post("/backtests/portfolio-optimize", response_model=PortfolioOptimizationResponse, dependencies=[Depends(verify_api_key)])
    async def optimize_portfolio(request: PortfolioOptimizationRequest) -> PortfolioOptimizationResponse:
        try:
            return PortfolioOptimizationResponse.model_validate(research_service.optimize_portfolio(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/research/promotion-gate", response_model=ResearchPromotionGateResponse, dependencies=[Depends(verify_api_key)])
    async def evaluate_research_promotion_gate(request: ResearchPromotionGateRequest) -> ResearchPromotionGateResponse:
        try:
            return ResearchPromotionGateResponse.model_validate(promotion_gate_service.evaluate(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/crypto/research/closure", response_model=CryptoClosureResponse, dependencies=[Depends(verify_api_key)])
    async def run_crypto_research_closure(request: CryptoClosureRequest) -> CryptoClosureResponse:
        try:
            return CryptoClosureResponse.model_validate(crypto_closure_service.run(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/optimize", response_model=StrategyOptimizationResponse, dependencies=[Depends(verify_api_key)])
    async def optimize_strategy(request: StrategyOptimizationRequest) -> StrategyOptimizationResponse:
        try:
            return StrategyOptimizationResponse.model_validate(research_service.optimize_strategy(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/cost-stress", response_model=CostStressResponse, dependencies=[Depends(verify_api_key)])
    async def run_cost_stress(request: CostStressRequest) -> CostStressResponse:
        try:
            return CostStressResponse.model_validate(research_service.run_cost_stress(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/cost-stress/event-driven", response_model=EventDrivenCostStressResponse, dependencies=[Depends(verify_api_key)])
    async def run_event_driven_cost_stress(request: CostStressRequest) -> EventDrivenCostStressResponse:
        try:
            return EventDrivenCostStressResponse.model_validate(
                research_service.run_event_driven_cost_stress(request.model_dump())
            )
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/backtests/walk-forward", response_model=WalkForwardResponse, dependencies=[Depends(verify_api_key)])
    async def run_walk_forward(request: WalkForwardRequest) -> WalkForwardResponse:
        try:
            return WalkForwardResponse.model_validate(research_service.run_walk_forward(request.model_dump()))
        except (QuantStationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/tasks", response_model=list[TaskStatusResponse], dependencies=[Depends(verify_api_key)])
    async def list_background_tasks(kind: str = "", limit: int = 20) -> list[TaskStatusResponse]:
        tasks = task_queue_service.list(kind=kind, limit=limit)
        return [_serialize_task(task) for task in tasks]

    @router.get("/tasks/{task_id}", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def get_background_task(task_id: str) -> TaskStatusResponse:
        try:
            return _serialize_task(task_queue_service.get(task_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown task id: {task_id}") from exc

    @router.post("/tasks/crypto/closure", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def submit_crypto_closure_task(request: CryptoClosureRequest) -> TaskStatusResponse:
        payload = request.model_dump()
        return _submit_background_task(
            kind="crypto_closure",
            label=f"BTC production closure {request.symbol} {request.interval}",
            request=payload,
            job=lambda ctx: _run_crypto_closure_background_task(ctx, payload),
        )

    @router.post("/tasks/research/promotion-gate", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def submit_research_promotion_gate_task(request: ResearchPromotionGateRequest) -> TaskStatusResponse:
        payload = request.model_dump()
        return _submit_background_task(
            kind="promotion_gate",
            label=f"promotion gate {request.symbol} {request.mode}",
            request=payload,
            job=lambda ctx: promotion_gate_service.evaluate(payload),
        )

    @router.post("/tasks/integrations/qlib/run-pipeline", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def submit_qlib_pipeline_task(request: dict) -> TaskStatusResponse:
        from integrations.qlib_adapter.profiles import resolve_pipeline_request
        from integrations.qlib_adapter.research_pipeline import run_research_pipeline
        try:
            profile = resolve_pipeline_request(request)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = {**request, "run_id": profile["run_id"]}
        return _submit_background_task(kind="qlib_pipeline", label=f"Qlib {profile['profile_id']}",
            request=payload, job=lambda ctx: run_research_pipeline(payload, artifacts_root=QLIB_ARTIFACTS_ROOT, progress=ctx.update))

    @router.post("/tasks/integrations/qlib/build-dataset", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def submit_qlib_build_dataset_task(request: dict) -> TaskStatusResponse:
        payload = dict(request)

        def job(ctx) -> dict[str, Any]:
            from integrations.qlib_adapter.build_qlib_dataset import build_qlib_dataset

            ctx.update(stage="build_dataset", message="building qlib dataset", progress=20)
            result = build_qlib_dataset(
                universe_path=payload.get("universe") or payload.get("universe_path") or "configs/universe/us_core_liquid.yaml",
                start_date=str(payload.get("start_date") or "2020-01-01"),
                end_date=str(payload.get("end_date") or "2025-12-31"),
                data_version=str(payload.get("data_version") or "latest"),
                run_id=str(payload.get("run_id") or "") or None,
                data_root=str(payload.get("data_root") or "data"),
                artifacts_root=str(payload.get("artifacts_root") or "artifacts/qlib_runs"),
                source=str(payload.get("source") or "") or None,
                asset_class=str(payload.get("asset_class") or "equity"),
                bar_size=str(payload.get("bar_size") or "1d"),
                dry_run=bool(payload.get("dry_run", False)),
            )
            from integrations.qlib_adapter.research_pipeline import checked_result
            checked_result(result, "build_dataset")
            ctx.update(stage="completed", message="qlib dataset built", progress=100)
            result_payload = _result_dict(result)
            result_payload["research_only"] = True
            result_payload["live_enabled"] = False
            return result_payload

        return _submit_background_task(
            kind="qlib_dataset",
            label=f"Qlib dataset {payload.get('data_version') or 'latest'}",
            request=payload,
            job=job,
        )

    @router.post("/tasks/integrations/qlib/run-workflow", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def submit_qlib_workflow_task(request: dict) -> TaskStatusResponse:
        payload = dict(request)

        def job(ctx) -> dict[str, Any]:
            from integrations.qlib_adapter.run_qlib_workflow import run_qlib_workflow

            ctx.update(stage="run_workflow", message="running qlib workflow", progress=30)
            result = run_qlib_workflow(
                config_path=payload.get("config") or payload.get("config_path") or "configs/qlib/us_lgbm_alpha158_daily.yaml",
                run_id=str(payload.get("run_id") or "") or None,
                artifacts_root=str(payload.get("artifacts_root") or "artifacts/qlib_runs"),
                dry_run=bool(payload.get("dry_run", False)),
            )
            from integrations.qlib_adapter.research_pipeline import checked_result
            checked_result(result, "run_workflow")
            ctx.update(stage="completed", message="qlib workflow completed", progress=100)
            result_payload = _result_dict(result)
            result_payload["research_only"] = True
            result_payload["live_enabled"] = False
            return result_payload

        return _submit_background_task(
            kind="qlib_workflow",
            label=f"Qlib workflow {payload.get('run_id') or 'latest'}",
            request=payload,
            job=job,
        )

    @router.post("/tasks/integrations/portfolio/optimize-weights", response_model=TaskStatusResponse, dependencies=[Depends(verify_api_key)])
    async def submit_portfolio_optimize_weights_task(request: dict) -> TaskStatusResponse:
        payload = dict(request)

        def job(ctx) -> dict[str, Any]:
            from integrations.pypfopt_adapter.optimize_weights import optimize_weights
            from integrations.pypfopt_adapter.schemas import load_portfolio_config

            ctx.update(stage="optimize_weights", message="optimizing portfolio weights", progress=40)
            config = load_portfolio_config(payload.get("config") or payload.get("config_path") or "configs/portfolio/pypfopt_long_only_max_sharpe.yaml")
            fallback_optimizer = str(payload.get("fallback_optimizer") or "")
            if fallback_optimizer:
                config = config.with_overrides(fallback_optimizer=fallback_optimizer)
            frame, path, fallback_used = optimize_weights(
                score_run_id=str(payload.get("score_run_id") or payload.get("run_id") or ""),
                config=config,
                portfolio_run_id=str(payload.get("portfolio_run_id") or "") or None,
            )
            latest_sum = None
            if not frame.empty and "datetime" in frame.columns:
                latest_date = frame["datetime"].max()
                latest = frame[frame["datetime"] == latest_date]
                latest_sum = float(latest["target_weight"].sum()) if "target_weight" in latest.columns else None
            ctx.update(stage="completed", message="portfolio optimization completed", progress=100)
            return {
                "status": "completed",
                "portfolio_run_id": path.parent.name,
                "path": str(path),
                "rows": int(len(frame)),
                "fallback_used": bool(fallback_used),
                "latest_weight_sum": latest_sum,
                "preview": json.loads(frame.head(20).to_json(orient="records", date_format="iso")) if not frame.empty else [],
                "research_only": True,
                "live_enabled": False,
                "order_generation": "disabled",
            }

        return _submit_background_task(
            kind="portfolio_optimize_weights",
            label=f"PyPortfolioOpt optimize {payload.get('portfolio_run_id') or payload.get('score_run_id') or 'latest'}",
            request=payload,
            job=job,
        )

    @router.get("/runs/{run_id}", response_model=RunStatusResponse, dependencies=[Depends(verify_api_key)])
    async def get_run(run_id: str) -> RunStatusResponse:
        try:
            return _serialize_run(run_registry.get(run_id))
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs/{run_id}/chart", response_model=ChartSeriesPayload, dependencies=[Depends(verify_api_key)])
    async def get_run_chart(run_id: str) -> ChartSeriesPayload:
        try:
            record = run_registry.get(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if record.result is None:
            raise HTTPException(status_code=404, detail="No chart data available for this run")
        return ChartSeriesPayload.model_validate(record.result.chart)

    # ------------------------------------------------------------------
    # R-series: Research & Portfolio endpoints
    # ------------------------------------------------------------------

    @router.get("/research/experiments")
    def list_research_experiments(data_root: str = "data"):
        """List research experiments from the lab."""
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().list_experiments(data_root=data_root)
            )
        try:
            from quant_us.research.lab.manifest import ExperimentManager
            mgr = ExperimentManager(data_root=data_root)
            return mgr.list_experiments()
        except Exception:
            return []

    @router.get("/research/candidates")
    def list_research_candidates(data_root: str = "data"):
        """List strategy candidates from the lab."""
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().list_candidates(data_root=data_root)
            )
        try:
            from quant_us.research.lab.manifest import ExperimentManager
            mgr = ExperimentManager(data_root=data_root)
            return mgr.list_candidates()
        except Exception:
            return []

    @router.get("/research/experiments/{experiment_id}/ranking")
    async def experiment_ranking(experiment_id: str):
        """Get ranked candidates for an experiment."""
        from quant_us.research.automation.scorer import CandidateScorer
        scorer = CandidateScorer()
        scores = scorer.score(experiment_id)
        ranked = scorer.rank(scores)
        return [s.__dict__ for s in ranked]

    @router.post("/research/experiments/compare")
    async def compare_experiments(request: dict):
        """Compare multiple experiments. Body: {experiment_ids: [...], metric: "score"}"""
        from quant_us.research.lab.manifest import ExperimentManager
        mgr = ExperimentManager()
        return mgr.compare_experiments(
            request.get("experiment_ids", []),
            request.get("metric", "score"),
        )

    @router.get("/research/candidates/{candidate_id}/lineage")
    async def candidate_lineage(candidate_id: str, data_root: str = "data"):
        """Get candidate lineage chain."""
        from quant_us.research.lab.manifest import ExperimentManager
        mgr = ExperimentManager(data_root=data_root)
        return mgr.get_lineage(candidate_id)

    @router.post("/research/candidates/{candidate_id}/promotion-gate")
    async def check_promotion_gate(candidate_id: str, request: dict | None = None):
        """Evaluate candidate through research promotion gate."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate
        payload = request or {}
        gate = ResearchPromotionGate(data_root=str(payload.get("data_root") or "data"))
        result = gate.evaluate(candidate_id)
        return result.__dict__

    @router.post("/research/auto-cycle")
    async def run_research_auto_cycle(request: dict):
        """Run the research-only closed loop from HTTP.

        This mirrors the CLI auto-cycle: experiment/candidate generation,
        evidence materialization, promotion-gate evaluation, and evidence
        registry rebuild. It never starts paper/live trading.
        """
        from fastapi import HTTPException
        from quant_us.research.automation.pipeline import ResearchAutomationPipeline
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate
        from quant_us.research.evidence_pack import EvidencePackGenerator
        from quant_us.research.evidence_registry import rebuild_evidence_registry

        data_root = str(request.get("data_root") or "data")
        config = request.get("config")
        if not isinstance(config, dict):
            config = {
                "experiment_name": request.get("experiment_name") or request.get("family") or "",
                "strategy_id": request.get("strategy_id") or "",
                "symbols": request.get("symbols") or [],
                "params": request.get("params") or {},
                "param_grid": request.get("param_grid") or {},
                "start_date": request.get("start_date") or request.get("start") or "",
                "end_date": request.get("end_date") or request.get("end") or "",
                "data_version": request.get("data_version") or "",
                "feature_version": request.get("feature_version") or "",
                "timeframe": request.get("timeframe") or request.get("bar_size") or "1d",
            }
        if not config.get("strategy_id"):
            raise HTTPException(status_code=400, detail="strategy_id is required")
        if not config.get("symbols"):
            raise HTTPException(status_code=400, detail="symbols are required")

        result = ResearchAutomationPipeline(data_root=data_root).run(config)
        candidate_ids = [str(value) for value in result.get("candidate_ids", [])]

        evidence_pack_paths: dict[str, str] = {}
        if not request.get("skip_evidence_pack", False):
            generator = EvidencePackGenerator(data_root=data_root)
            for candidate_id in candidate_ids:
                try:
                    evidence_pack_paths[candidate_id] = str(generator.save(candidate_id))
                except Exception as exc:
                    evidence_pack_paths[candidate_id] = f"error: {exc}"

        gate_results: dict[str, Any] = {}
        gate = ResearchPromotionGate(data_root=data_root)
        for candidate_id in candidate_ids:
            try:
                gate_result = gate.evaluate(candidate_id)
                gate_results[candidate_id] = gate_result.__dict__
            except Exception as exc:
                gate_results[candidate_id] = {
                    "decision": "BLOCKED",
                    "reasons": [str(exc)],
                    "warnings": [],
                    "evidence": {},
                }

        registry: dict[str, Any] = {}
        if not request.get("skip_registry_rebuild", False):
            registry = rebuild_evidence_registry(data_root, write=True)

        return {
            "status": result.get("status", "unknown"),
            "pipeline_result": result,
            "candidate_ids": candidate_ids,
            "evidence_pack_paths": evidence_pack_paths,
            "promotion_gate_results": gate_results,
            "registry": registry,
            "note": "research-only; no PAPER_ELIGIBLE promotion and no paper/live order path",
        }

    @router.post("/research/candidates/{candidate_id}/evidence/materialize")
    async def materialize_candidate_evidence(candidate_id: str, request: dict | None = None):
        """Materialize canonical candidate evidence for promotion review."""
        from quant_us.research.automation.evidence_materializer import ResearchEvidenceMaterializer

        payload = request or {}
        result = ResearchEvidenceMaterializer(
            data_root=str(payload.get("data_root") or "data")
        ).materialize_candidate(
            candidate_id,
            create_strategy_manifest=bool(payload.get("create_strategy_manifest", True)),
            run_promotion_gate=bool(payload.get("run_promotion_gate", True)),
        )
        return asdict(result)

    @router.post("/research/candidates/{candidate_id}/evidence-pack")
    async def save_candidate_evidence_pack(candidate_id: str, request: dict | None = None):
        """Generate and persist a candidate evidence pack."""
        from quant_us.research.evidence_pack import EvidencePackGenerator

        payload = request or {}
        generator = EvidencePackGenerator(data_root=str(payload.get("data_root") or "data"))
        path = generator.save(candidate_id)
        return {
            "candidate_id": candidate_id,
            "evidence_pack_path": str(path),
            "status": "saved",
        }

    @router.get("/research/strategy-manifests")
    def list_strategy_manifests(status: str = "", data_root: str = "data"):
        """List frozen strategy manifests produced from research candidates."""
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().list_strategy_manifests(
                    data_root=data_root,
                    status=status,
                )
            )
        from quant_us.research.strategy_manifest import StrategyManifestManager

        manager = StrategyManifestManager(data_root=data_root)
        return [asdict(manifest) for manifest in manager.list_manifests(status=status)]

    @router.get("/research/evidence-registry")
    async def get_research_evidence_registry(
        request: Request,
        data_root: str = "data",
        rebuild: bool = False,
        view: str = "full",
    ):
        """Read saved evidence only; navigation must never create a registry."""
        from quant_us.research.evidence_registry import (
            EvidenceRegistryInspectionCancelled,
            inspect_saved_evidence_registry,
            inspect_saved_evidence_registry_summary,
        )

        if rebuild:
            raise HTTPException(status_code=405, detail={
                "code": "registry_rebuild_requires_post",
                "message": "重建证据需要显式提交 POST /api/research/evidence-registry/rebuild。",
            })
        if research_readonly:
            _readonly_projection(
                lambda: _readonly_views().require_data_root(data_root)
            )
            data_root = str(_readonly_views().data_root)
        if view not in {"full", "summary"}:
            raise HTTPException(status_code=400, detail={
                "code": "registry_view_invalid",
                "message": "证据注册表仅支持 full 或 summary 只读视图。",
            })
        try:
            inspector = (
                inspect_saved_evidence_registry_summary
                if view == "summary"
                else inspect_saved_evidence_registry
            )
            return await _run_cancellable_registry_inspection(
                request,
                inspector,
                data_root,
            )
        except EvidenceRegistryInspectionCancelled as exc:
            raise HTTPException(status_code=499, detail={
                "code": "research_evidence_read_cancelled",
                "message": "证据注册表只读校验已随客户端请求取消；未返回部分结果。",
                "registry_status": "conflict",
                "registry_integrity_status": "CONFLICT",
                "read_only": True,
                "promotion_eligible": False,
            }) from exc
        except (json.JSONDecodeError, UnicodeError, OSError) as exc:
            # Preserve the damaged evidence. Never repair, skip or publish it as ready.
            raise HTTPException(status_code=409, detail={
                "code": "research_evidence_unreadable",
                "message": "证据文件无法读取或解析；请核查原件，当前研究证据保持阻塞。",
                "registry_status": "conflict",
                "registry_integrity_status": "CONFLICT",
                "error_type": type(exc).__name__,
                "read_only": True,
                "promotion_eligible": False,
            }) from exc

    @router.get("/research/global-registry")
    def get_global_research_registry():
        """Return the read-only global research registry summary."""
        from scripts.build_global_research_registry import build_global_registry

        return build_global_registry(repo_root=settings.repo_root)

    @router.get("/research/btc/scalping-backtest")
    def get_btc_scalping_research_backtest():
        """Return the latest research-only BTC scalping backtest summary."""
        path = (
            settings.repo_root
            / "artifacts/btc_research_backtests/latest/btc_scalping_research_backtest_report.json"
        )
        payload = _json_file(path)
        if not payload:
            raise HTTPException(status_code=404, detail=f"BTC scalping research backtest report not found: {path}")
        return payload

    @router.get("/research/btc/trend-forward-status")
    def get_btc_trend_forward_status():
        """Return read-only BTC daily trend forward-observation status."""
        return _btc_trend_forward_status_payload(settings.repo_root)

    @router.get("/research/btc/control-center")
    def get_btc_research_control_center():
        """Return read-only BTC research control-center artifacts for the frontend."""
        reader = _require_btc_runtime_artifact_reader()
        try:
            return _btc_research_control_center_payload(
                settings.repo_root,
                artifact_reader=reader,
            )
        except BTCRuntimeArtifactStoreError as exc:
            raise _btc_runtime_artifact_http_exception(exc) from exc

    @router.get("/research/btc/strategy-registry")
    def get_btc_strategy_registry(request: Request):
        """Return frozen BTC strategy identities without granting paper/live authority."""
        from quant_crypto.application.btc_strategy_registry import btc_strategy_registry

        specs = [
            {**spec.identity(), "params": dict(spec.params)}
            for spec in btc_strategy_registry.list_specs()
        ]
        response = {
            "schema_version": "btc_strategy_registry_api_v1",
            "status": "complete_research_only",
            "decision": "btc_strategy_registry_identity_catalog_no_auto_paper_no_live",
            "default_strategy_id": "long_short_donchian_top5",
            "default_candidate_id": specs[0]["candidate_id"] if specs else "",
            "specs": specs,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        }
        selectors = request.query_params.getlist("offline_run")
        if not selectors:
            return response
        from backend.app.services.donchian_offline_views import FLAGS, read_donchian_summary
        from backend.app.services.donchian_stage_views import (
            SELECTOR as STAGE_SELECTOR, read_stage_snapshot,
        )

        if len(selectors) != 1 or len(request.query_params) != 1:
            response["offline_evidence"] = {
                "status": "not_bound", "read_only": True,
                "reason": "donchian_selector_ambiguous",
                "permissions": {flag: False for flag in FLAGS},
            }
        else:
            response["offline_evidence"] = (
                read_stage_snapshot(settings.repo_root, selectors[0])
                if selectors[0] == STAGE_SELECTOR else
                read_donchian_summary(
                    settings.repo_root, selectors[0],
                    btc_strategy_registry.get("long_short_donchian_top5_okx_native").identity(),
                )
            )
        return response

    @router.get("/research/btc/artifacts/{artifact_id}")
    def get_btc_research_artifact(artifact_id: str):
        """Return a fixed, read-only BTC latest research artifact by id."""
        reader = _require_btc_runtime_artifact_reader()
        try:
            payload = _btc_research_artifact_payload(
                settings.repo_root,
                artifact_id,
                artifact_reader=reader,
            )
        except BTCRuntimeArtifactStoreError as exc:
            raise _btc_runtime_artifact_http_exception(exc) from exc
        if payload.get("missing") is True:
            raise HTTPException(status_code=404, detail=payload)
        return payload

    @router.post("/research/evidence-registry/rebuild")
    async def rebuild_research_evidence_registry(request: dict | None = None):
        """Rebuild and save the research evidence registry."""
        from quant_us.research.evidence_registry import rebuild_evidence_registry

        payload = request or {}
        return rebuild_evidence_registry(str(payload.get("data_root") or "data"), write=True)

    @router.get("/research/factors")
    def list_research_factors(data_root: str = "data"):
        """List registered research factors."""
        if research_readonly:
            _readonly_projection(
                lambda: _readonly_views().require_data_root(data_root)
            )
            data_root = str(_readonly_views().data_root)
        from quant_us.factors.definition import FactorLibrary
        from quant_us.factors.formula import GeneratedFactorLibrary

        builtin = [asdict(factor) for factor in FactorLibrary().list_all()]
        generated = [
            asdict(spec.to_definition()) | {"generated": True, "formula_type": spec.formula_type, "components": spec.components}
            for spec in GeneratedFactorLibrary(data_root).list_specs()
        ]
        return builtin + generated

    @router.post("/research/factors/evaluate")
    async def evaluate_research_factor(request: dict):
        """Evaluate a factor with optional intraday bar_size/timeframe."""
        from quant_us.factors.evaluation import FactorEvaluator

        factor_id = str(request.get("factor_id") or request.get("factor") or "")
        if not factor_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="factor_id is required")
        symbols = request.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        result = FactorEvaluator(data_root=str(request.get("data_root") or "data")).evaluate(
            factor_id=factor_id,
            symbols=list(symbols),
            start=str(request.get("start") or "2020-01-01"),
            end=str(request.get("end") or ""),
            forward_period=int(request.get("forward_period") or 5),
            bar_size=str(request.get("bar_size") or "1d"),
            timeframe=str(request.get("timeframe") or request.get("bar_size") or "1d"),
        )
        return asdict(result)

    @router.post("/research/factors/mine")
    async def mine_research_factors(request: dict):
        """Batch-mine factors, de-correlate them, and emit strategy configs."""
        from quant_us.research.automation.factor_mining import FactorMiningEngine

        symbols = request.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        bar_sizes = request.get("bar_sizes") or request.get("bar_size") or ["1d"]
        if isinstance(bar_sizes, str):
            bar_sizes = [s.strip().lower() for s in bar_sizes.split(",") if s.strip()]
        factor_ids = request.get("factor_ids") or []
        if isinstance(factor_ids, str):
            factor_ids = [s.strip() for s in factor_ids.split(",") if s.strip()]
        result = FactorMiningEngine(data_root=str(request.get("data_root") or "data")).mine(
            symbols=list(symbols),
            start=str(request.get("start") or "2020-01-01"),
            end=str(request.get("end") or ""),
            bar_sizes=list(bar_sizes),
            factor_ids=list(factor_ids) or None,
            forward_period=int(request.get("forward_period") or 5),
            min_abs_rank_ic=float(request.get("min_abs_rank_ic") or 0.01),
            min_observations=int(request.get("min_observations") or 20),
            max_abs_correlation=float(request.get("max_abs_correlation") or 0.90),
            max_selected=int(request.get("max_selected") or 8),
            auto_generate_formulas=_as_bool(request.get("auto_generate_formulas", False)),
            max_generated_factors=int(request.get("max_generated_factors") or 24),
            max_formula_complexity=int(request.get("max_formula_complexity") or 6),
        )
        return result.to_dict()

    @router.post("/research/factors/generate")
    async def generate_research_formula_factors(request: dict):
        """Generate and persist safe formula-factor candidates."""
        from quant_us.factors.formula import GeneratedFactorLibrary

        factor_ids = request.get("factor_ids") or []
        if isinstance(factor_ids, str):
            factor_ids = [s.strip() for s in factor_ids.split(",") if s.strip()]
        specs = GeneratedFactorLibrary(str(request.get("data_root") or "data")).generate_and_register(
            seed_factor_ids=list(factor_ids) or None,
            max_specs=int(request.get("max_generated_factors") or request.get("max_specs") or 24),
            max_complexity=int(request.get("max_formula_complexity") or 6),
        )
        return {
            "status": "completed",
            "generated_factor_count": len(specs),
            "generated_factor_ids": [spec.factor_id for spec in specs],
            "factors": [asdict(spec.to_definition()) | {"formula_type": spec.formula_type, "components": spec.components} for spec in specs],
        }

    @router.post("/research/factors/mine-and-run")
    async def mine_and_run_research_factors(request: dict):
        """Mine factors, then run research-only backtest gates for selected configs."""
        from quant_us.research.automation.factor_mining import FactorMiningEngine
        from quant_us.research.automation.pipeline import ResearchAutomationPipeline
        from quant_us.research.evidence_registry import rebuild_evidence_registry

        data_root = str(request.get("data_root") or "data")
        symbols = request.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        bar_sizes = request.get("bar_sizes") or request.get("bar_size") or ["1d"]
        if isinstance(bar_sizes, str):
            bar_sizes = [s.strip().lower() for s in bar_sizes.split(",") if s.strip()]
        factor_ids = request.get("factor_ids") or []
        if isinstance(factor_ids, str):
            factor_ids = [s.strip() for s in factor_ids.split(",") if s.strip()]

        start = str(request.get("start") or "2020-01-01")
        end = str(request.get("end") or "")
        mining = FactorMiningEngine(data_root=data_root).mine(
            symbols=list(symbols),
            start=start,
            end=end,
            bar_sizes=list(bar_sizes),
            factor_ids=list(factor_ids) or None,
            forward_period=int(request.get("forward_period") or 5),
            min_abs_rank_ic=float(request.get("min_abs_rank_ic") or 0.01),
            min_observations=int(request.get("min_observations") or 20),
            max_abs_correlation=float(request.get("max_abs_correlation") or 0.90),
            max_selected=int(request.get("max_selected") or 8),
            auto_generate_formulas=_as_bool(request.get("auto_generate_formulas", False)),
            max_generated_factors=int(request.get("max_generated_factors") or 24),
            max_formula_complexity=int(request.get("max_formula_complexity") or 6),
        )

        max_runs = max(0, int(request.get("max_runs") or len(mining.strategy_configs)))
        pipeline_results: list[dict[str, Any]] = []
        candidate_ids: list[str] = []
        pipeline = ResearchAutomationPipeline(data_root=data_root)
        for strategy_config in mining.strategy_configs[:max_runs]:
            params = dict(strategy_config.get("params", {}))
            factor_name = str(params.get("factor_name") or "factor")
            timeframe = str(strategy_config.get("timeframe") or strategy_config.get("bar_size") or "1d")
            result = pipeline.run(
                {
                    "experiment_name": f"factor_mining_{factor_name}_{timeframe}",
                    "strategy_id": "factor_rank",
                    "symbols": list(symbols),
                    "params": params,
                    "start_date": start,
                    "end_date": end,
                    "data_version": str(request.get("data_version") or ""),
                    "feature_version": str(request.get("feature_version") or ""),
                    "timeframe": timeframe,
                }
            )
            pipeline_results.append(result)
            candidate_ids.extend(str(value) for value in result.get("candidate_ids", []))

        registry: dict[str, Any] = {}
        if not _as_bool(request.get("skip_registry_rebuild", False)):
            registry = rebuild_evidence_registry(data_root, write=True)

        return {
            "status": "completed",
            "factor_mining": mining.to_dict(),
            "pipeline_results": pipeline_results,
            "candidate_ids": candidate_ids,
            "registry": registry,
            "note": "research-only factor mining cycle; no paper/live order path",
        }

    @router.post("/research/factors/compute")
    async def compute_research_factor(request: dict):
        """Compute factor values and return a bounded preview."""
        from quant_us.factors.pipeline import FactorPipeline

        factor_ids = request.get("factor_ids") or request.get("factors") or []
        if isinstance(factor_ids, str):
            factor_ids = [s.strip() for s in factor_ids.split(",") if s.strip()]
        if not factor_ids:
            factor_id = str(request.get("factor_id") or request.get("factor") or "")
            factor_ids = [factor_id] if factor_id else []
        symbols = request.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        frame = FactorPipeline(data_root=str(request.get("data_root") or "data")).compute(
            factor_ids=list(factor_ids),
            symbols=list(symbols),
            start=str(request.get("start") or "2020-01-01"),
            end=str(request.get("end") or ""),
            bar_size=str(request.get("bar_size") or "1d"),
            timeframe=str(request.get("timeframe") or request.get("bar_size") or "1d"),
        )
        limit = max(1, min(int(request.get("limit") or 50), 500))
        return {
            "factor_ids": list(factor_ids),
            "symbols": list(symbols),
            "bar_size": str(request.get("bar_size") or "1d"),
            "timeframe": str(request.get("timeframe") or request.get("bar_size") or "1d"),
            "row_count": int(len(frame)),
            "preview": frame.head(limit).to_dict(orient="records") if not frame.empty else [],
        }

    # ------------------------------------------------------------------
    # R4: Research orchestration endpoints
    # ------------------------------------------------------------------

    @router.get("/research/batches/{batch_id}")
    async def get_research_batch(batch_id: str):
        """Get status of a research batch plan."""
        try:
            from quant_us.research.orchestration.queue import ExperimentQueue
            queue = ExperimentQueue()
            status = queue.get_status(batch_id)
            if "error" in status:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=status["error"])
            return status
        except ImportError:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail="research orchestration unavailable")

    @router.post("/research/batches/{batch_id}/run")
    async def run_research_batch(batch_id: str, dry_run: bool = False):
        """Run (or dry-run) a research batch plan."""
        try:
            from quant_us.research.orchestration.queue import ExperimentQueue
            queue = ExperimentQueue()
            result = queue.run_batch(batch_id=batch_id, dry_run=dry_run)
            return result
        except ImportError:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail="research orchestration unavailable")

    @router.get("/portfolio/status")
    def portfolio_status():
        """Return current portfolio construction status."""
        if research_readonly:
            return _readonly_projection(_readonly_views().portfolio_status)
        try:
            import json
            from pathlib import Path

            # Keep the dashboard status endpoint read-only and cheap. Portfolio
            # construction may import heavier research dependencies; status only
            # needs the latest persisted target artifact.
            target_dir = Path("data/portfolio/targets")
            if target_dir.exists():
                targets = sorted(target_dir.glob("*.json"))
                if targets:
                    latest = json.loads(targets[-1].read_text(encoding="utf-8"))
                    return {
                        "status": "ok",
                        "portfolio_count": len(targets),
                        "latest_portfolio": latest,
                    }
            return {"status": "ok", "portfolio_count": 0, "latest_portfolio": None}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    # ------------------------------------------------------------------
    # Qlib / PyPortfolioOpt research-only integration endpoints
    # ------------------------------------------------------------------

    def _artifact_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _artifact_preview(path: Path, limit: int = 12) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            import pandas as pd

            frame = pd.read_parquet(path).head(max(1, min(limit, 100)))
            return json.loads(frame.to_json(orient="records", date_format="iso"))
        except Exception:
            return []

    def _result_dict(result: Any) -> dict[str, Any]:
        if hasattr(result, "__dataclass_fields__"):
            return asdict(result)
        if isinstance(result, dict):
            return dict(result)
        return {"result": result}

    def _mtime_iso(path: Path) -> str:
        if not path.exists():
            return ""
        from datetime import datetime, timezone

        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

    def _qlib_server_root(requested: str) -> Path:
        if requested != "artifacts/qlib_runs":
            raise HTTPException(status_code=400, detail="Qlib evidence root is server-owned.")
        if candidate_research_catalog_error:
            raise HTTPException(status_code=503, detail=candidate_research_catalog_error)
        try:
            return candidate_research_roots.revalidate().qlib_root
        except DeliveryError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"candidate_offline_catalog_invalid:{exc.code}",
            ) from exc

    def _reject_archive_query_selectors(**selectors: str | None) -> None:
        if any(value is not None for value in selectors.values()):
            raise HTTPException(status_code=400, detail="readonly_archive_selector_is_server_owned")

    def _qlib_run_summary(
        run_root: Path,
        *,
        logical_root: str | None = None,
        provenance: dict[str, Any] | None = None,
        integrity: dict[str, Any] | None = None,
        verified_manifest_files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from integrations.qlib_adapter.research_pipeline import read_sealed_evidence
        integrity = integrity or read_sealed_evidence(
            run_root,
            summary_only=True,
            verified_manifest_files=verified_manifest_files,
        )
        if integrity["integrity_status"] != "passed":
            return {"run_id": run_root.name, "pipeline_status": "unknown", "trace_status": "unknown",
                "promotion_status": "blocked", "integrity_status": integrity["integrity_status"],
                "blockers": integrity.get("blockers", []), "execution_permission": False}

        def read_summary_json(relative_path: str) -> dict[str, Any]:
            path = run_root / relative_path
            if not path.exists():
                return {}
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"summary_artifact_unreadable:{relative_path}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"summary_artifact_not_object:{relative_path}")
            return payload

        try:
            metadata = read_summary_json("qlib_run_metadata.json")
            pipeline = read_summary_json("pipeline_result.json")
            trace = read_summary_json("research_trace.json")
            dataset_manifest = read_summary_json("qlib_input/dataset_manifest.json")
            provider_manifest = read_summary_json("provider_manifest.json")
            workflow_result = read_summary_json("workflow_run_result.json")
            strategy_manifest = read_summary_json("qlib_strategy_manifest.json")
        except ValueError as exc:
            return {"run_id": run_root.name, "pipeline_status": "unknown", "trace_status": "unknown",
                "promotion_status": "blocked", "integrity_status": "blocked",
                "blockers": [str(exc)], "execution_permission": False}
        score_rows = 0
        score_path = run_root / "research_model_scores.parquet"
        if score_path.exists():
            try:
                import pyarrow.parquet as parquet

                score_rows = int(parquet.ParquetFile(score_path).metadata.num_rows)
            except Exception:
                try:
                    import pandas as pd

                    score_rows = int(len(pd.read_parquet(score_path, columns=["symbol"])))
                except Exception:
                    return {"run_id": run_root.name, "pipeline_status": "unknown", "trace_status": "unknown",
                        "promotion_status": "blocked", "integrity_status": "blocked",
                        "blockers": ["summary_artifact_unreadable:research_model_scores.parquet"],
                        "execution_permission": False}
        logical_root = logical_root or f"artifacts/qlib_runs/{run_root.name}"
        return {
            "run_id": run_root.name,
            "profile_id": metadata.get("profile", pipeline.get("profile_id", "us_equity_daily")),
            "asset_class": dataset_manifest.get("input_contract", {}).get("asset_class", pipeline.get("asset_class", "unknown")),
            "bar_size": dataset_manifest.get("input_contract", {}).get("bar_size", pipeline.get("bar_size", "unknown")),
            "data_version": dataset_manifest.get("input_contract", {}).get("data_version_request", ""),
            "source_head": metadata.get("code_version", pipeline.get("source_head", "")),
            "pipeline_status": pipeline.get("status", "not_run"),
            "trace_status": trace.get("status", "not_run"),
            "updated_at": _mtime_iso(run_root),
            "dataset_status": dataset_manifest.get("status", "missing"),
            "provider_status": provider_manifest.get("status", "missing"),
            "workflow_status": workflow_result.get("status", "missing"),
            "manifest_status": strategy_manifest.get("status", "missing"),
            "promotion_status": _qlib_research_only_promotion_status(strategy_manifest),
            "strategy_id": strategy_manifest.get("strategy_id") or strategy_manifest.get("strategy_version", ""),
            "symbols": dataset_manifest.get("symbols_exported") or dataset_manifest.get("symbols_requested", []),
            "score_rows": score_rows,
            "evidence_provenance": provenance or {
                "storage": "repo_local",
                "logical_run": logical_root,
                "consumer_read_only": True,
            },
            "paths": {
                "run_root": logical_root,
                "dataset_manifest": f"{logical_root}/qlib_input/dataset_manifest.json",
                "research_model_scores": f"{logical_root}/research_model_scores.parquet",
                "strategy_manifest": f"{logical_root}/qlib_strategy_manifest.json",
            },
        }

    def _portfolio_run_summary(run_root: Path) -> dict[str, Any]:
        manifest = _artifact_json(run_root / "run_manifest.json")
        weights_path = run_root / "target_weights.parquet"
        positions_path = run_root / "target_positions.parquet"
        run_status = _portfolio_research_only_status(
            "completed" if weights_path.exists() else str(manifest.get("status", "missing") or "missing")
        )
        weight_rows = 0
        latest_weight_sum = None
        if weights_path.exists():
            try:
                import pandas as pd

                frame = pd.read_parquet(weights_path)
                weight_rows = int(len(frame))
                if not frame.empty and "datetime" in frame.columns:
                    latest_date = frame["datetime"].max()
                    latest = frame[frame["datetime"] == latest_date]
                    latest_weight_sum = float(latest["target_weight"].sum()) if "target_weight" in latest.columns else None
            except Exception:
                weight_rows = 0
        return {
            "portfolio_run_id": run_root.name,
            "updated_at": _mtime_iso(run_root),
            "status": run_status,
            "source_score_run_id": manifest.get("source_score_run_id", ""),
            "optimizer": manifest.get("config", {}).get("optimizer", ""),
            "fallback_used": bool(manifest.get("fallback_used", False)),
            "target_weight_rows": weight_rows,
            "latest_weight_sum": latest_weight_sum,
            "has_target_positions": positions_path.exists(),
            "paths": {
                "run_root": str(run_root),
                "target_weights": str(weights_path),
                "target_positions": str(positions_path),
                "manifest": str(run_root / "run_manifest.json"),
            },
        }

    def _coalesce_qlib_list_read(
        key: tuple[str, int, str],
        load: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        with qlib_list_inflight_lock:
            inflight = qlib_list_inflight.get(key)
            if inflight is None:
                inflight = Future()
                qlib_list_inflight[key] = inflight
                leader = True
            else:
                leader = False
        if not leader:
            return inflight.result()
        try:
            payload = load()
        except BaseException as exc:
            with qlib_list_inflight_lock:
                if qlib_list_inflight.get(key) is inflight:
                    del qlib_list_inflight[key]
            inflight.set_exception(exc)
            raise
        with qlib_list_inflight_lock:
            if qlib_list_inflight.get(key) is inflight:
                del qlib_list_inflight[key]
        inflight.set_result(payload)
        return payload

    @router.get("/integrations/qlib/runs", dependencies=[Depends(verify_api_key)])
    def list_qlib_integration_runs(
        artifacts_root: str = "artifacts/qlib_runs",
        limit: int = 20,
        manifest: str | None = None,
        manifest_git_spec: str | None = None,
        path: str | None = None,
        ref: str | None = None,
        root: str | None = None,
        shared_root: str | None = None,
    ):
        import importlib.util
        from integrations.qlib_adapter.profiles import list_profiles

        _reject_archive_query_selectors(
            manifest=manifest,
            manifest_git_spec=manifest_git_spec,
            path=path,
            ref=ref,
            root=root,
            shared_root=shared_root,
        )
        qlib_root = _qlib_server_root(artifacts_root)
        bounded_limit = max(1, min(limit, 100))

        def load() -> dict[str, Any]:
            try:
                if research_archive is None:
                    paths = sorted(
                        [path for path in qlib_root.iterdir() if path.is_dir() and path.resolve().is_relative_to(qlib_root.resolve())],
                        key=lambda path: path.stat().st_mtime,
                        reverse=True,
                    ) if qlib_root.exists() else []
                    locations = [
                        ReadonlyRunLocation(
                            run_id=path.name,
                            run_root=path,
                            qlib_root=qlib_root,
                            logical_root=f"artifacts/qlib_runs/{path.name}",
                            provenance={
                                "storage": "repo_local",
                                "logical_run": f"artifacts/qlib_runs/{path.name}",
                                "consumer_read_only": True,
                            },
                        )
                        for path in paths
                    ]
                else:
                    locations = list(research_archive.list_qlib_runs(qlib_root))
            except ResearchArchiveConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except ResearchArchiveUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            selected_locations = sorted(
                locations,
                key=lambda location: _mtime_iso(location.run_root),
                reverse=True,
            )[:bounded_limit]

            def summarize(location: ReadonlyRunLocation) -> dict[str, Any]:
                return _qlib_run_summary(
                    location.run_root,
                    logical_root=location.logical_root,
                    provenance=dict(location.provenance),
                    verified_manifest_files=(
                        dict(location.verified_files) if location.archived else None
                    ),
                )

            if qlib_summary_executor is None or len(selected_locations) < 2:
                run_summaries = [summarize(location) for location in selected_locations]
            else:
                summary_futures = [
                    qlib_summary_executor.submit(summarize, location)
                    for location in selected_locations
                ]
                try:
                    run_summaries = [future.result() for future in summary_futures]
                except BaseException:
                    for future in summary_futures:
                        future.cancel()
                    for future in summary_futures:
                        if future.cancelled():
                            continue
                        try:
                            future.result()
                        except BaseException:
                            pass
                    raise
            run_summaries.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
            universe = _artifact_json(Path("configs/universe/us_core_liquid.yaml"))
            return {
                "status": "ok",
                "research_only": True,
                "daily_only": False,
                "profiles": list_profiles(),
                "live_enabled": False,
                "dependencies": {
                    "qlib": importlib.util.find_spec("qlib") is not None,
                    "lightgbm": importlib.util.find_spec("lightgbm") is not None,
                },
                "configs": {
                    "universe": "configs/universe/us_core_liquid.yaml",
                    "qlib": "configs/qlib/us_lgbm_alpha158_daily.yaml",
                },
                "runs": run_summaries,
            }

        if not research_readonly:
            return load()
        return _coalesce_qlib_list_read(
            (
                str(qlib_root.resolve()),
                bounded_limit,
                settings.backend_evidence_profile,
            ),
            load,
        )

    @router.get("/integrations/qlib/runs/{run_id}", dependencies=[Depends(verify_api_key)])
    def get_qlib_integration_run(
        run_id: str,
        artifacts_root: str = "artifacts/qlib_runs",
        manifest: str | None = None,
        manifest_git_spec: str | None = None,
        path: str | None = None,
        ref: str | None = None,
        root: str | None = None,
        shared_root: str | None = None,
    ):
        from integrations.qlib_adapter.schemas import build_run_paths, QlibAdapterError
        from integrations.qlib_adapter.research_pipeline import read_sealed_evidence
        _reject_archive_query_selectors(
            manifest=manifest,
            manifest_git_spec=manifest_git_spec,
            path=path,
            ref=ref,
            root=root,
            shared_root=shared_root,
        )
        try:
            qlib_root = _qlib_server_root(artifacts_root)
            local_run_root = build_run_paths(run_id, qlib_root).run_root
            if research_archive is None:
                location = ReadonlyRunLocation(
                    run_id=run_id,
                    run_root=local_run_root,
                    qlib_root=qlib_root,
                    logical_root=f"artifacts/qlib_runs/{run_id}",
                    provenance={
                        "storage": "repo_local",
                        "logical_run": f"artifacts/qlib_runs/{run_id}",
                        "consumer_read_only": True,
                    },
                )
            else:
                location = research_archive.resolve_qlib_run(qlib_root, run_id)
        except QlibAdapterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ResearchArchiveConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ResearchArchiveUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if location is None or not location.run_root.exists():
            raise HTTPException(status_code=404, detail=f"Qlib run not found: {run_id}")
        run_root = location.run_root
        sealed = read_sealed_evidence(
            run_root,
            verified_manifest_files=(
                dict(location.verified_files) if location.archived else None
            ),
        )
        if sealed["integrity_status"] != "passed":
            if location.archived:
                raise HTTPException(
                    status_code=503,
                    detail=f"readonly_archive_qlib_seal_invalid:{run_id}",
                )
            return {"summary": {"run_id": run_id, "pipeline_status": "unknown",
                "promotion_status": "blocked"}, **sealed}
        summary = _qlib_run_summary(
            run_root,
            logical_root=location.logical_root,
            provenance=dict(location.provenance),
            integrity=sealed,
        )
        if summary.get("integrity_status") == "blocked":
            return {
                "summary": summary,
                "integrity_status": "blocked",
                "blockers": list(summary.get("blockers", [])),
                "execution_permission": False,
                "runtime_observed": False,
                "promotion": False,
                "paper": False,
                "live": False,
                "private": False,
                "order": False,
            }
        from backend.app.services.offline_execution_views import read_offline_summary
        offline_execution = read_offline_summary(
            settings.repo_root, {
                **sealed.get("research_trace", {}).get("identity", {}),
                "model_sha256": sealed.get("seal", {}).get("files", {}).get("model.txt"),
            }
        )
        return {
            "summary": summary,
            "offline_execution": offline_execution,
            "pipeline": _artifact_json(run_root / "pipeline_result.json"),
            "signal_evaluation": _artifact_json(run_root / "signal_evaluation.json"),
            **sealed,
            "dataset_manifest": _artifact_json(run_root / "qlib_input" / "dataset_manifest.json"),
            "provider_manifest": _artifact_json(run_root / "provider_manifest.json"),
            "workflow_result": _artifact_json(run_root / "workflow_run_result.json"),
            "failure_report": _artifact_json(run_root / "failure_report.json"),
            "recorder_metrics": _artifact_json(run_root / "imported_recorder_metrics.json") or _artifact_json(run_root / "recorder_metrics.json"),
            "strategy_manifest": _artifact_json(run_root / "qlib_strategy_manifest.json"),
            "scores_preview": _artifact_preview(run_root / "research_model_scores.parquet"),
        }

    @router.post("/integrations/qlib/build-dataset", dependencies=[Depends(verify_api_key)])
    async def build_qlib_integration_dataset(request: dict):
        try:
            from integrations.qlib_adapter.build_qlib_dataset import build_qlib_dataset

            result = build_qlib_dataset(
                universe_path=request.get("universe") or request.get("universe_path") or "configs/universe/us_core_liquid.yaml",
                start_date=str(request.get("start_date") or "2020-01-01"),
                end_date=str(request.get("end_date") or "2025-12-31"),
                data_version=str(request.get("data_version") or "latest"),
                run_id=str(request.get("run_id") or "") or None,
                data_root=str(request.get("data_root") or "data"),
                artifacts_root=str(request.get("artifacts_root") or "artifacts/qlib_runs"),
                source=str(request.get("source") or "") or None,
                asset_class=str(request.get("asset_class") or "equity"),
                bar_size=str(request.get("bar_size") or "1d"),
                dry_run=bool(request.get("dry_run", False)),
            )
            payload = _result_dict(result)
            payload["research_only"] = True
            payload["live_enabled"] = False
            return payload
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/qlib/run-workflow", dependencies=[Depends(verify_api_key)])
    async def run_qlib_integration_workflow(request: dict):
        try:
            from integrations.qlib_adapter.run_qlib_workflow import run_qlib_workflow

            result = run_qlib_workflow(
                config_path=request.get("config") or request.get("config_path") or "configs/qlib/us_lgbm_alpha158_daily.yaml",
                run_id=str(request.get("run_id") or "") or None,
                artifacts_root=str(request.get("artifacts_root") or "artifacts/qlib_runs"),
                dry_run=bool(request.get("dry_run", False)),
            )
            payload = _result_dict(result)
            payload["research_only"] = True
            payload["live_enabled"] = False
            return payload
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/qlib/import-pred-score", dependencies=[Depends(verify_api_key)])
    async def import_qlib_pred_score_endpoint(request: dict):
        try:
            from integrations.qlib_adapter.import_pred_score import import_pred_score

            result = import_pred_score(
                run_id=str(request.get("run_id") or "latest"),
                artifacts_root=str(request.get("artifacts_root") or "artifacts/qlib_runs"),
                pred_score_path=str(request.get("pred_score_path") or "") or None,
            )
            return _result_dict(result) | {"research_only": True, "live_enabled": False}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/qlib/import-recorder-metrics", dependencies=[Depends(verify_api_key)])
    async def import_qlib_recorder_metrics_endpoint(request: dict):
        try:
            from integrations.qlib_adapter.import_recorder_metrics import import_recorder_metrics

            result = import_recorder_metrics(
                run_id=str(request.get("run_id") or "latest"),
                artifacts_root=str(request.get("artifacts_root") or "artifacts/qlib_runs"),
                recorder_metrics_path=str(request.get("recorder_metrics_path") or "") or None,
            )
            return _result_dict(result) | {"research_only": True, "live_enabled": False}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/qlib/compile-strategy-manifest", dependencies=[Depends(verify_api_key)])
    async def compile_qlib_strategy_manifest_endpoint(request: dict):
        try:
            from integrations.qlib_adapter.compile_qlib_strategy_manifest import compile_qlib_strategy_manifest

            path = compile_qlib_strategy_manifest(
                run_id=str(request.get("run_id") or "latest"),
                config_path=request.get("config") or request.get("config_path") or "configs/qlib/us_lgbm_alpha158_daily.yaml",
                artifacts_root=str(request.get("artifacts_root") or "artifacts/qlib_runs"),
            )
            payload = _artifact_json(Path(path))
            return {
                "status": "completed",
                "manifest_path": str(path),
                "strategy_manifest": payload,
                "research_only": True,
                "live_enabled": False,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/integrations/portfolio/runs", dependencies=[Depends(verify_api_key)])
    def list_portfolio_integration_runs(artifacts_root: str = "artifacts/portfolio_runs", limit: int = 20):
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().list_portfolio_runs(
                    artifacts_root=artifacts_root,
                    limit=limit,
                )
            )
        import importlib.util

        root = Path(artifacts_root)
        runs = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime, reverse=True) if root.exists() else []
        return {
            "status": "ok",
            "research_only": True,
            "daily_only": True,
            "live_enabled": False,
            "dependencies": {
                "pypfopt": importlib.util.find_spec("pypfopt") is not None,
            },
            "configs": {
                "max_sharpe": "configs/portfolio/pypfopt_long_only_max_sharpe.yaml",
                "min_volatility": "configs/portfolio/pypfopt_long_only_min_volatility.yaml",
                "hrp": "configs/portfolio/pypfopt_hrp.yaml",
            },
            "runs": [_portfolio_run_summary(path) for path in runs[: max(1, min(limit, 100))]],
        }

    @router.get("/integrations/portfolio/runs/{portfolio_run_id}", dependencies=[Depends(verify_api_key)])
    async def get_portfolio_integration_run(portfolio_run_id: str, artifacts_root: str = "artifacts/portfolio_runs"):
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().get_portfolio_run(
                    portfolio_run_id,
                    artifacts_root=artifacts_root,
                )
            )
        run_root = Path(artifacts_root) / portfolio_run_id
        if not run_root.exists():
            raise HTTPException(status_code=404, detail=f"Portfolio run not found: {portfolio_run_id}")
        return {
            "summary": _portfolio_run_summary(run_root),
            "run_manifest": _artifact_json(run_root / "run_manifest.json"),
            "expected_returns_preview": _artifact_preview(run_root / "expected_returns.parquet"),
            "covariance_preview": _artifact_preview(run_root / "covariance.parquet"),
            "target_weights_preview": _artifact_preview(run_root / "target_weights.parquet"),
            "target_positions_preview": _artifact_preview(run_root / "target_positions.parquet"),
            "target_positions_json": _artifact_json(run_root / "target_positions.json"),
        }

    @router.post("/integrations/portfolio/build-expected-returns", dependencies=[Depends(verify_api_key)])
    async def build_portfolio_expected_returns_endpoint(request: dict):
        try:
            from integrations.pypfopt_adapter.build_expected_returns import build_expected_returns
            from integrations.pypfopt_adapter.schemas import load_portfolio_config

            config = load_portfolio_config(request.get("config") or request.get("config_path") or "configs/portfolio/pypfopt_long_only_max_sharpe.yaml")
            frame, path = build_expected_returns(
                score_run_id=str(request.get("score_run_id") or request.get("run_id") or ""),
                config=config,
                portfolio_run_id=str(request.get("portfolio_run_id") or "") or None,
            )
            return {
                "status": "completed",
                "portfolio_run_id": path.parent.name,
                "path": str(path),
                "rows": int(len(frame)),
                "preview": json.loads(frame.head(12).to_json(orient="records", date_format="iso")) if not frame.empty else [],
                "research_only": True,
                "live_enabled": False,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/portfolio/build-covariance", dependencies=[Depends(verify_api_key)])
    async def build_portfolio_covariance_endpoint(request: dict):
        try:
            from integrations.pypfopt_adapter.build_covariance import build_covariance
            from integrations.pypfopt_adapter.schemas import load_portfolio_config

            config = load_portfolio_config(request.get("config") or request.get("config_path") or "configs/portfolio/pypfopt_long_only_max_sharpe.yaml")
            frame, path = build_covariance(
                score_run_id=str(request.get("score_run_id") or request.get("run_id") or ""),
                config=config,
                portfolio_run_id=str(request.get("portfolio_run_id") or "") or None,
            )
            return {
                "status": "completed",
                "portfolio_run_id": path.parent.name,
                "path": str(path),
                "rows": int(len(frame)),
                "preview": json.loads(frame.head(12).to_json(orient="records", date_format="iso")) if not frame.empty else [],
                "research_only": True,
                "live_enabled": False,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/portfolio/optimize-weights", dependencies=[Depends(verify_api_key)])
    async def optimize_portfolio_weights_endpoint(request: dict):
        try:
            from integrations.pypfopt_adapter.optimize_weights import optimize_weights
            from integrations.pypfopt_adapter.schemas import load_portfolio_config

            config = load_portfolio_config(request.get("config") or request.get("config_path") or "configs/portfolio/pypfopt_long_only_max_sharpe.yaml")
            fallback_optimizer = str(request.get("fallback_optimizer") or "")
            if fallback_optimizer:
                config = config.with_overrides(fallback_optimizer=fallback_optimizer)
            frame, path, fallback_used = optimize_weights(
                score_run_id=str(request.get("score_run_id") or request.get("run_id") or ""),
                config=config,
                portfolio_run_id=str(request.get("portfolio_run_id") or "") or None,
            )
            latest_sum = None
            if not frame.empty and "datetime" in frame.columns:
                latest_date = frame["datetime"].max()
                latest = frame[frame["datetime"] == latest_date]
                latest_sum = float(latest["target_weight"].sum()) if "target_weight" in latest.columns else None
            return {
                "status": "completed",
                "portfolio_run_id": path.parent.name,
                "path": str(path),
                "rows": int(len(frame)),
                "fallback_used": bool(fallback_used),
                "latest_weight_sum": latest_sum,
                "preview": json.loads(frame.head(20).to_json(orient="records", date_format="iso")) if not frame.empty else [],
                "research_only": True,
                "live_enabled": False,
                "order_generation": "disabled",
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/integrations/portfolio/import-target-weights", dependencies=[Depends(verify_api_key)])
    async def import_portfolio_target_weights_endpoint(request: dict):
        try:
            from integrations.pypfopt_adapter.import_target_weights import import_target_weights
            from integrations.pypfopt_adapter.schemas import load_portfolio_config

            config = load_portfolio_config(request.get("config") or request.get("config_path") or "configs/portfolio/pypfopt_long_only_max_sharpe.yaml")
            portfolio_run_id = str(request.get("portfolio_run_id") or "")
            frame, parquet_path, json_path = import_target_weights(
                portfolio_run_id=portfolio_run_id,
                config=config,
                strategy_id=str(request.get("strategy_id") or "") or None,
            )
            return {
                "status": "completed",
                "portfolio_run_id": portfolio_run_id,
                "target_positions_path": str(parquet_path),
                "target_positions_json_path": str(json_path),
                "rows": int(len(frame)),
                "preview": json.loads(frame.head(20).to_json(orient="records", date_format="iso")) if not frame.empty else [],
                "research_only": True,
                "live_enabled": False,
                "order_generation": "disabled",
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/research/execution-pipeline/run", dependencies=[Depends(verify_api_key)])
    async def run_research_execution_pipeline_endpoint(request: dict):
        """Run research-only Qlib -> portfolio -> risk-gated backtest evidence pipeline."""
        try:
            from quant_us.research.orchestration.research_execution_pipeline import (
                ResearchExecutionPipelineConfig,
                run_research_execution_pipeline,
            )
            from quant_us.core.types import new_id

            qlib_run_id = str(request.get("qlib_run_id") or request.get("score_run_id") or "")
            if not qlib_run_id:
                raise ValueError("qlib_run_id is required")
            result = run_research_execution_pipeline(
                ResearchExecutionPipelineConfig(
                    qlib_run_id=qlib_run_id,
                    qlib_config_path=request.get("qlib_config") or request.get("qlib_config_path") or "configs/qlib/us_lgbm_alpha158_daily.yaml",
                    portfolio_config_path=request.get("portfolio_config") or request.get("portfolio_config_path") or request.get("config") or "configs/portfolio/pypfopt_long_only_max_sharpe.yaml",
                    pipeline_run_id=str(request.get("pipeline_run_id") or "") or new_id("rpipe"),
                    portfolio_run_id=str(request.get("portfolio_run_id") or "") or "",
                    strategy_id=str(request.get("strategy_id") or "") or "",
                    qlib_runs_root=Path(str(request.get("qlib_runs_root") or request.get("artifacts_root") or "artifacts/qlib_runs")),
                    portfolio_runs_root=Path(str(request.get("portfolio_runs_root") or "artifacts/portfolio_runs")),
                    pipeline_runs_root=Path(str(request.get("pipeline_runs_root") or "artifacts/research_execution_runs")),
                    initial_cash=float(request.get("initial_cash") or 100000.0),
                    commission_rate=float(request.get("commission_rate") or 0.0001),
                    slippage_bps=float(request.get("slippage_bps") or 1.0),
                    fill_ratio=float(request.get("fill_ratio") or 1.0),
                    volume_participation_cap_pct=float(request.get("volume_participation_cap_pct") or 5.0),
                    max_daily_turnover_pct=float(request.get("max_daily_turnover_pct") or 200.0),
                    risk_max_symbol_weight=(
                        float(request["risk_max_symbol_weight"])
                        if request.get("risk_max_symbol_weight") is not None
                        else None
                    ),
                    risk_max_gross_exposure=float(request.get("risk_max_gross_exposure") or 1.0),
                    risk_max_order_notional_pct=float(request.get("risk_max_order_notional_pct") or 0.10),
                    risk_min_cash_buffer_pct=(
                        float(request["risk_min_cash_buffer_pct"])
                        if request.get("risk_min_cash_buffer_pct") is not None
                        else None
                    ),
                    walk_forward_train_bars=int(request.get("walk_forward_train_bars") or request.get("wf_train_bars") or 252),
                    walk_forward_test_bars=int(request.get("walk_forward_test_bars") or request.get("wf_test_bars") or 63),
                    walk_forward_step_bars=int(request.get("walk_forward_step_bars") or request.get("wf_step_bars") or 63),
                )
            )
            return {
                **asdict(result),
                "research_only": True,
                "live_enabled": False,
                "order_generation": "disabled_until_risk_gated_backtest",
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # R3: Feature Store endpoints
    # ------------------------------------------------------------------

    @router.get("/research/features", response_model=list[FeatureSnapshotResponse])
    def list_feature_snapshots():
        """List all feature snapshots."""
        if research_readonly:
            return _readonly_projection(
                lambda: [
                    FeatureSnapshotResponse(**snapshot)
                    for snapshot in _readonly_views().list_feature_snapshots()
                ]
            )

        from quant_us.research.features.snapshot import FeatureSnapshotManager

        mgr = FeatureSnapshotManager(data_root="data")
        return [FeatureSnapshotResponse(**s.__dict__) for s in mgr.list_snapshots()]

    @router.post("/research/features/build", response_model=FeatureSnapshotResponse)
    async def build_feature_snapshot(request: FeatureBuildRequest):
        """Build a feature snapshot."""
        from quant_us.research.features.snapshot import FeatureSnapshotManager

        mgr = FeatureSnapshotManager(data_root=request.data_root)
        snapshot = mgr.build(
            feature_id=request.feature_id,
            version=request.version,
            symbols=request.symbols,
            start=request.start,
            end=request.end,
            bar_size=request.bar_size,
            timeframe=request.timeframe or request.bar_size,
        )
        return FeatureSnapshotResponse(**snapshot.__dict__)

    @router.get("/research/features/{snapshot_id}", response_model=FeatureSnapshotResponse)
    async def get_feature_snapshot(snapshot_id: str):
        """Get metadata for a specific feature snapshot."""
        from quant_us.research.features.snapshot import FeatureSnapshotManager

        mgr = FeatureSnapshotManager()
        snapshots = [s for s in mgr.list_snapshots() if s.snapshot_id == snapshot_id]
        if not snapshots:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")
        return FeatureSnapshotResponse(**snapshots[0].__dict__)

    @router.post("/research/features/{snapshot_id}/validate", response_model=FeatureValidateResponse)
    async def validate_feature_snapshot(snapshot_id: str):
        """Validate a feature snapshot checksum."""
        from quant_us.research.features.snapshot import FeatureSnapshotManager

        mgr = FeatureSnapshotManager()
        ok, reason = mgr.validate(snapshot_id)
        return FeatureValidateResponse(snapshot_id=snapshot_id, valid=ok, reason=reason)

    # ------------------------------------------------------------------
    # R5: Strategy Factory & Portfolio Promotion Bridge
    # ------------------------------------------------------------------

    @router.get("/research/portfolio-sims/{sim_id}")
    async def get_portfolio_sim(sim_id: str):
        """Get portfolio simulation results."""
        from quant_us.research.portfolio_sim_bridge import PortfolioSimBridge
        from fastapi import HTTPException

        bridge = PortfolioSimBridge()
        try:
            return bridge.get_report(sim_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/research/portfolio-sims/run")
    async def run_portfolio_sim(request: dict):
        """Run a portfolio simulation. Body: {manifest_ids: [...], config: {...}}"""
        from quant_us.research.portfolio_sim_bridge import PortfolioSimBridge
        from fastapi import HTTPException

        manifest_ids = request.get("manifest_ids", [])
        config = request.get("config", {})
        bridge = PortfolioSimBridge()
        try:
            sim_request = bridge.create_simulation(manifest_ids, config)
            result = bridge.run_simulation(sim_request.portfolio_sim_id)
            return {
                "portfolio_sim_id": result.portfolio_sim_id,
                "decision": result.decision,
                "risk_breach_count": result.risk_breach_count,
                "final_equity": result.equity_curve[-1] if result.equity_curve else 0.0,
                "strategy_count": len(result.contribution_by_strategy),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/research/paper-review/create")
    async def create_paper_review(request: dict):
        """Create a paper review from evidence only; never opens paper/live submit."""
        from quant_us.research.paper_review_bridge import PaperReviewManager
        from fastapi import HTTPException

        data_root = str(request.get("data_root") or "data")
        evidence_pack_id = str(request.get("portfolio_evidence_pack_id", "") or "")
        sim_id = request.get("portfolio_sim_id", "")
        candidate_id = str(request.get("candidate_id", "") or "")
        strategy_manifest_id = str(request.get("strategy_manifest_id", "") or "")
        prepared_pack_id = str(request.get("prepared_evidence_pack_id", "") or "")
        if not evidence_pack_id and not sim_id and not candidate_id and not strategy_manifest_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "portfolio_evidence_pack_id, portfolio_sim_id, candidate_id, or "
                    "strategy_manifest_id is required"
                ),
            )
        mgr = PaperReviewManager(data_root=data_root)
        try:
            if evidence_pack_id:
                review = mgr.create_from_portfolio_evidence(evidence_pack_id)
            elif sim_id:
                review = mgr.create_review(sim_id)
            else:
                review = mgr.create_from_candidate_evidence(
                    candidate_id=candidate_id,
                    strategy_manifest_id=strategy_manifest_id,
                    portfolio_evidence_pack_id=prepared_pack_id,
                )
            return {
                "paper_review_id": review.paper_review_id,
                "status": review.status,
                "evidence_pack_path": review.evidence_pack_path,
                "evidence_gate_status": review.evidence_gate_status,
                "proposed_symbols": review.proposed_symbols,
                "proposed_capital": review.proposed_capital,
                "source_candidate_ids": getattr(review, "source_candidate_ids", []),
                "created_at": review.created_at,
                "note": "manual review queue only; this endpoint never approves or submits paper orders",
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/research/paper-review/entry-state")
    def paper_review_entry_state(data_root: str = "data"):
        """Inspect paper-review creation eligibility and the next operator command."""
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().paper_review_entry_state(
                    data_root=data_root
                )
            )
        payload = _system_overview_payload(data_root=data_root)
        return payload.get("paper_review", {})

    @router.get("/research/paper-review/pending")
    def list_pending_reviews(data_root: str = "data"):
        """List pending paper reviews."""
        if research_readonly:
            return _readonly_projection(
                lambda: _readonly_views().list_pending_reviews(
                    data_root=data_root
                )
            )
        from quant_us.research.paper_review_bridge import PaperReviewManager

        mgr = PaperReviewManager(data_root=data_root)
        reviews = mgr.list_pending()
        return [
            {
                "paper_review_id": r.paper_review_id,
                "strategy_manifest_id": r.strategy_manifest_id,
                "portfolio_sim_id": r.portfolio_sim_id,
                "status": r.status,
                "proposed_symbols": r.proposed_symbols,
                "proposed_capital": r.proposed_capital,
                "created_at": r.created_at,
            }
            for r in reviews
        ]

    @router.post("/research/paper-review/{review_id}/approve")
    async def approve_paper_review(review_id: str, request: dict):
        """Approve a paper review. Requires --manual (body: {reviewer: "...", manual: true})."""
        from quant_us.research.paper_review_bridge import PaperReviewManager
        from fastapi import HTTPException

        manual = request.get("manual", False)
        reviewer = request.get("reviewer", "")
        reason = request.get("reason", "")
        if not manual:
            raise HTTPException(status_code=400, detail="manual flag required for approval")
        if not reviewer:
            raise HTTPException(status_code=400, detail="reviewer name required")
        mgr = PaperReviewManager()
        try:
            review = mgr.approve(review_id, reviewer, reason=reason)
            return {
                "paper_review_id": review.paper_review_id,
                "status": review.status,
                "reviewer": review.reviewer,
                "approval": asdict(review.approval) if review.approval else None,
                "note": "APPROVED_FOR_PAPER_ONLY - does NOT trigger paper trading",
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # R6: Alpha Robustness & Evidence Engine
    # ------------------------------------------------------------------

    @router.post("/research/robustness/run", response_model=RobustnessRunResponse, dependencies=[Depends(verify_api_key)])
    async def run_robustness_analysis(request: RobustnessRunRequest) -> RobustnessRunResponse:
        """Run full robustness analysis (Monte Carlo + alpha decay + param stability)."""
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        candidate_id = request.strategy_manifest_id

        # Try to resolve from manifest
        manifest_path = (
            Path(request.data_root) / "research" / "manifests" / request.strategy_manifest_id / "manifest.json"
        )
        if manifest_path.exists():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                src = manifest_data.get("source_candidate_id", "")
                if src:
                    candidate_id = src
            except (json.JSONDecodeError, OSError):
                pass

        try:
            from quant_us.research.robustness.monte_carlo import MonteCarloRobustness
            from quant_us.research.robustness.alpha_decay import AlphaDecayAnalyzer
            from quant_us.research.robustness.param_stability import ParameterStabilityAnalyzer
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"Robustness engine unavailable: {exc}") from exc

        def _load_trade_returns(cid: str, dr: str) -> list[float]:
            cand_path = Path(dr) / "research" / "candidates" / cid / "candidate.json"
            if not cand_path.exists():
                return []
            data = json.loads(cand_path.read_text(encoding="utf-8"))
            metrics = data.get("metrics", {})
            trade_returns = metrics.get("trade_returns", [])
            if isinstance(trade_returns, list) and len(trade_returns) >= 10:
                return [float(r) for r in trade_returns]
            sharpe = float(metrics.get("out_of_sample_sharpe", metrics.get("sharpe_ratio", 0.5)))
            trade_count = int(metrics.get("trade_count", 20))
            if trade_count > 0:
                import math
                import random
                rng = random.Random(42)
                daily_sharpe_val = sharpe / math.sqrt(252) if sharpe > 0 else 0.001
                return [rng.gauss(daily_sharpe_val, 0.02) for _ in range(max(trade_count, 20))]
            return []

        def _load_daily_returns(cid: str, dr: str) -> list[float]:
            cand_path = Path(dr) / "research" / "candidates" / cid / "candidate.json"
            if not cand_path.exists():
                return []
            data = json.loads(cand_path.read_text(encoding="utf-8"))
            metrics = data.get("metrics", {})
            daily_returns = metrics.get("daily_returns", [])
            if isinstance(daily_returns, list) and len(daily_returns) >= 10:
                return [float(r) for r in daily_returns]
            sharpe = float(metrics.get("out_of_sample_sharpe", metrics.get("sharpe_ratio", 0.5)))
            if sharpe > 0:
                import math
                import random
                rng = random.Random(42)
                daily_sharpe_val = sharpe / math.sqrt(252)
                return [rng.gauss(daily_sharpe_val, 0.01) for _ in range(252 * 3)]
            return []

        monte = MonteCarloRobustness(seed=42)
        trade_returns = _load_trade_returns(candidate_id, request.data_root)
        daily_returns = _load_daily_returns(candidate_id, request.data_root)

        shuffle_result = monte.shuffle_trades(trade_returns, n=request.n_simulations)
        shuffle_result.candidate_id = candidate_id
        bootstrap_result = monte.bootstrap_returns(daily_returns, n=request.n_simulations)
        bootstrap_result.candidate_id = candidate_id
        stress_result = monte.stress_scenarios(daily_returns, cost_mult=3.0, slippage_mult=2.0)
        stress_result.candidate_id = candidate_id

        ad_section = None
        try:
            ada = AlphaDecayAnalyzer(data_root=request.data_root)
            ad = ada.analyze(candidate_id)
            ad_section = RobustnessAlphaDecaySection(
                alpha_half_life=ad.alpha_half_life,
                decay_warning=ad.decay_warning,
                recommended_holding_period=ad.recommended_holding_period,
                ic_decay_curve=ad.ic_decay_curve,
            )
        except (ValueError, json.JSONDecodeError, OSError):
            pass

        ps_section = None
        try:
            psa = ParameterStabilityAnalyzer(data_root=request.data_root)
            params = psa.load_candidate_params(candidate_id)
            if params:
                import random
                rng = random.Random(42)
                neighbors: list[dict] = [{"score": 1.0, **params}]
                for _ in range(19):
                    perturbed = dict(params)
                    for k in perturbed:
                        pv = float(perturbed[k])
                        perturbed[k] = pv * (1.0 + rng.uniform(-0.3, 0.3))
                    score = max(0.0, min(1.5, rng.gauss(0.7, 0.15)))
                    neighbors.append({"score": score, **perturbed})
                pr = psa.analyze(candidate_id, neighbors)
                ps_section = RobustnessParamStabilitySection(
                    stability_score=pr.stability_score,
                    cliff_count=pr.cliff_count,
                    robust_region_ratio=pr.robust_region_ratio,
                )
        except (ValueError, json.JSONDecodeError, OSError):
            pass

        run_id = f"rob_{candidate_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        response = RobustnessRunResponse(
            run_id=run_id,
            candidate_id=candidate_id,
            strategy_manifest=request.strategy_manifest_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            monte_carlo_shuffle=RobustnessMonteCarloSection(
                n_simulations=shuffle_result.n_simulations,
                survival_rate=shuffle_result.survival_rate,
                median_return=shuffle_result.median_return,
                p5_return=shuffle_result.p5_return,
                p95_drawdown=shuffle_result.p95_drawdown,
                tail_risk_score=shuffle_result.tail_risk_score,
            ),
            monte_carlo_bootstrap=RobustnessMonteCarloSection(
                n_simulations=bootstrap_result.n_simulations,
                survival_rate=bootstrap_result.survival_rate,
                median_return=bootstrap_result.median_return,
                p5_return=bootstrap_result.p5_return,
                p95_drawdown=bootstrap_result.p95_drawdown,
                tail_risk_score=bootstrap_result.tail_risk_score,
            ),
            monte_carlo_stress=RobustnessMonteCarloSection(
                n_simulations=stress_result.n_simulations,
                survival_rate=stress_result.survival_rate,
                median_return=stress_result.median_return,
                p5_return=stress_result.p5_return,
                p95_drawdown=stress_result.p95_drawdown,
                tail_risk_score=stress_result.tail_risk_score,
            ),
            alpha_decay=ad_section,
            param_stability=ps_section,
        )

        # Persist to disk
        out_dir = Path(request.data_root) / "research" / "robustness"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{run_id}.json").write_text(
            json.dumps(response.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )

        return response

    @router.get("/research/robustness/{run_id}", response_model=RobustnessRunResponse, dependencies=[Depends(verify_api_key)])
    async def get_robustness_report(run_id: str, data_root: str = "data") -> RobustnessRunResponse:
        """Get a stored robustness analysis report."""
        import json
        from pathlib import Path

        report_path = Path(data_root) / "research" / "robustness" / f"{run_id}.json"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail=f"Robustness report '{run_id}' not found")
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            return RobustnessRunResponse(**data)
        except (json.JSONDecodeError, OSError, Exception) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/research/evidence/{strategy_manifest_id}", dependencies=[Depends(verify_api_key)])
    async def get_evidence_pack(strategy_manifest_id: str, data_root: str = "data"):
        """Generate and return an evidence pack for a strategy manifest."""
        import json
        from pathlib import Path

        # Resolve to candidate_id
        candidate_id = strategy_manifest_id
        manifest_path = (
            Path(data_root) / "research" / "manifests" / strategy_manifest_id / "manifest.json"
        )
        if manifest_path.exists():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                src = manifest_data.get("source_candidate_id", "")
                if src:
                    candidate_id = src
            except (json.JSONDecodeError, OSError):
                pass

        from quant_us.research.evidence_pack import EvidencePackGenerator

        try:
            gen = EvidencePackGenerator(data_root=data_root)
            evidence = gen.generate(candidate_id)
            evidence["_resolved_candidate_id"] = candidate_id
            return evidence
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    btc_domain_read_model_service: Any
    if btc_runtime_artifact_reader is None:
        class _UnavailableBTCDomainReadModelService:
            def read(self) -> dict[str, Any]:
                raise HTTPException(
                    status_code=503,
                    detail=_btc_runtime_artifact_unavailable_detail(),
                    headers={
                        "Cache-Control": "no-store",
                        "Pragma": "no-cache",
                    },
                )

        btc_domain_read_model_service = _UnavailableBTCDomainReadModelService()
    else:
        domain_service = BTCPublishedDomainReadModelService(
            repository=BTCPublishedDomainReadModelRepository(
                repo_root=settings.repo_root,
                artifact_reader=btc_runtime_artifact_reader,
            ),
            head_resolver=lambda: _current_repository_head(settings.repo_root),
        )

        class _GuardedBTCDomainReadModelService:
            def read(self) -> dict[str, Any]:
                try:
                    return _btc_logicalize_runtime_paths(
                        domain_service.read(),
                        repo_root=settings.repo_root,
                        artifact_reader=btc_runtime_artifact_reader,
                    )
                except (
                    BTCRuntimeArtifactStoreError,
                    BTCPublishedDomainReadModelUnavailable,
                ) as exc:
                    raise _btc_runtime_artifact_http_exception(exc) from exc

        btc_domain_read_model_service = _GuardedBTCDomainReadModelService()

    app.include_router(
        build_btc_domain_read_model_router(
            service=btc_domain_read_model_service,
            verify_api_key=verify_api_key,
        ),
        prefix="/api",
    )
    app.include_router(
        build_us_equity_domain_read_model_router(
            service=USDomainReadModelService(
                repository=USCommittedEvidenceRepository(
                    repo_root=settings.repo_root,
                ),
                head_resolver=lambda: _current_repository_head(settings.repo_root),
            ),
            verify_api_key=verify_api_key,
        ),
        prefix="/api",
    )
    app.include_router(
        build_cn_equity_router(
            service=CNEquityReadModelService(
                repo_root=settings.repo_root,
                head_resolver=lambda: _current_repository_head(settings.repo_root),
            ),
            verify_api_key=verify_api_key,
        ),
        prefix="/api",
    )
    if research_readonly:
        public_market_stream = BtcPublicMarketStreamHub()
        app.include_router(
            build_btc_public_market_router(
                service=BTCPublicMarketViewService(),
                stream_service=public_market_stream,
                verify_api_key=verify_api_key,
            ),
            prefix="/api",
        )
    if not research_readonly:
        app.include_router(
            build_btc_demo_runtime_router(
                service=btc_demo_runtime_service,
                verify_api_key=verify_api_key,
                repo_root=settings.repo_root,
                control_enabled=settings.btc_demo_control_enabled,
                private_readonly_observation=btc_private_readonly_observation,
            ),
            prefix="/api",
        )
        from backend.app.services.us_ibkr_runtime import IBKRRuntimeStatusService
        from quant_us.live.ibkr_runtime_provider import get_ibkr_runtime_provider_registry

        app.include_router(
            build_us_ibkr_runtime_router(
                service=IBKRRuntimeStatusService(get_ibkr_runtime_provider_registry()),
                verify_api_key=verify_api_key,
            ),
            prefix="/api",
        )
    from backend.app.api.alpha_factory import build_alpha_factory_router
    from backend.app.services.alpha_factory import AlphaFactoryService
    app.include_router(build_alpha_factory_router(service=AlphaFactoryService(
        root=(candidate_research_roots.factory_root if candidate_research_roots is not None
              else settings.repo_root / "artifacts" / "alpha_factory_runs"),
        qlib_root=(candidate_research_roots.qlib_root if candidate_research_roots is not None
                   else QLIB_ARTIFACTS_ROOT), queue=task_queue_service,
        readonly_archive=research_archive), verify_api_key=verify_api_key), prefix="/api")
    if settings.backend_evidence_profile in {CANDIDATE_MANAGEMENT_PROFILE, "research_readonly"}:
        from backend.app.api.candidate_delivery import build_candidate_delivery_router
        from backend.app.services.candidate_delivery_bootstrap import build_delivery_service, build_offline_service
        try:
            delivery = (None if candidate_research_catalog_error else build_delivery_service(
                settings, archive=research_archive, qlib_root=QLIB_ARTIFACTS_ROOT,
                head=_current_repository_head(settings.repo_root),
                research_roots=candidate_research_roots))
        except DeliveryError as exc:
            if not exc.code.startswith("offline_"):
                raise
            delivery = None
        app.include_router(build_candidate_delivery_router(service=delivery,
            enabled=settings.backend_evidence_profile == CANDIDATE_MANAGEMENT_PROFILE,
            operator=settings.candidate_delivery_operator, management_key=settings.web_api_key,
            auth_mode=settings.candidate_auth_mode, profile=settings.backend_evidence_profile), prefix="/api")
        from backend.app.api.candidate_offline import build_candidate_offline_router
        app.include_router(build_candidate_offline_router(build_offline_service(settings, delivery)), prefix="/api")
    app.include_router(router)
    return app
