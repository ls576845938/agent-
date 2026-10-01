from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.application.btc_strategy_registry import (
    BTCStrategyIdentityError,
    btc_strategy_registry,
)
from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
from quant_crypto.oms.paper_runtime_replay_session import (
    build_btc_paper_runtime_replay_oms_session as _build_oms_session,
)
from quant_crypto.research.btc_nonflat_evidence_autocapture import (
    build_btc_nonflat_evidence_autocapture,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path
from quant_crypto.risk.liquidation import (
    BTCLiquidationPolicy,
    BTCPerpPositionState,
    BTCReferencePriceState,
    evaluate_btc_perp_liquidation_risk,
)


SCHEMA_VERSION = "btc_perpetual_paper_runtime_replay_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_report.json"
DEFAULT_ROWS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_rows.csv"
DEFAULT_EVENT_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_event_ledger.csv"
DEFAULT_ORDER_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_order_ledger.csv"
DEFAULT_FILL_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fill_ledger.csv"
DEFAULT_OMS_SESSION_RECONCILIATION_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_oms_session_reconciliation_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_safety_status.json"
DEFAULT_DRILL_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_report.json"
DEFAULT_DRILL_ROWS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_rows.csv"
DEFAULT_DRILL_EVENT_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_event_ledger.csv"
DEFAULT_DRILL_ORDER_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_order_ledger.csv"
DEFAULT_DRILL_FILL_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_fill_ledger.csv"
DEFAULT_DRILL_OMS_SESSION_RECONCILIATION_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_oms_session_reconciliation_report.json"
DEFAULT_DRILL_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_summary_cn.md"
DEFAULT_DRILL_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_drill_safety_status.json"
DEFAULT_FIXTURE_DRILL_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_report.json"
DEFAULT_FIXTURE_DRILL_ROWS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_rows.csv"
DEFAULT_FIXTURE_DRILL_EVENT_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_event_ledger.csv"
DEFAULT_FIXTURE_DRILL_ORDER_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_order_ledger.csv"
DEFAULT_FIXTURE_DRILL_FILL_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_fill_ledger.csv"
DEFAULT_FIXTURE_DRILL_OMS_SESSION_RECONCILIATION_PATH = (
    DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_oms_session_reconciliation_report.json"
)
DEFAULT_FIXTURE_DRILL_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_summary_cn.md"
DEFAULT_FIXTURE_DRILL_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_replay_fixture_drill_safety_status.json"

DEFAULT_CONFIG_PATH = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_LONG_SHORT_OBSERVATIONS = Path(
    "artifacts/btc_long_short_top5_forward_observer/latest/btc_long_short_top5_forward_observations_latest.csv"
)
DEFAULT_ATTACK_OBSERVATIONS = Path(
    "artifacts/btc_bankroll_attack_forward_observer/latest/btc_bankroll_attack_forward_observations_latest.csv"
)
DEFAULT_HIGH_YIELD_OBSERVATIONS = Path(
    "artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_daily_observation_latest.csv"
)
DEFAULT_COST_MODEL_REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_PERPETUAL_EVIDENCE_REPORT = Path(
    "artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"
)
DEFAULT_BAR_REPLAY_ROWS = Path(
    "artifacts/btc_strategy_bar_replay_visibility/latest/btc_strategy_bar_replay_visibility_rows.csv"
)

REQUIRED_OBSERVATION_LINES = (
    "long_short_donchian_top5",
    "high_octane_attack_sleeve_v2",
    "high_yield_donchian_v2",
)

CAPTURE_BLOCKING_EXECUTION_EVIDENCE_KEYWORDS = (
    "private_endpoint",
    "order_endpoint",
    "broker",
    "live_order",
    "real_order",
    "safety_violation",
)

DEFAULT_ACCOUNT_EQUITY_USDT = 10_000.0
DEFAULT_MAX_LEVERAGE = 10.0
DEFAULT_MIN_LIQUIDATION_BUFFER_BPS = 800.0
DEFAULT_MAINTENANCE_MARGIN_RATE = 0.005
DEFAULT_CONTRACT_VALUE_BTC = "0.01"
DEFAULT_LOT_SIZE_CONTRACTS = "0.01"

BAR_REPLAY_DRILL_LINE_MAP = {
    "long_short_top5": "long_short_donchian_top5",
    "high_octane_v2": "high_octane_attack_sleeve_v2",
    "high_yield_v2": "high_yield_donchian_v2",
}


def build_btc_perpetual_paper_runtime_replay_report(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    long_short_observations_path: Path = DEFAULT_LONG_SHORT_OBSERVATIONS,
    attack_observations_path: Path = DEFAULT_ATTACK_OBSERVATIONS,
    high_yield_observations_path: Path = DEFAULT_HIGH_YIELD_OBSERVATIONS,
    cost_model_report_path: Path = DEFAULT_COST_MODEL_REPORT,
    perpetual_evidence_report_path: Path = DEFAULT_PERPETUAL_EVIDENCE_REPORT,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))

    bundle_dir = selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    market_rows = _read_table(bundle_dir / "klines_1h.csv" if bundle_dir else None)
    mark_rows = _read_table(bundle_dir / "mark_price_klines_1h.csv" if bundle_dir else None)
    premium_rows = _read_table(bundle_dir / "premium_index_klines_1h.csv" if bundle_dir else None)
    funding_rows = _read_table(bundle_dir / "funding_rate.csv" if bundle_dir else None)
    exchange_info = _read_json(bundle_dir / "exchange_info.json") if bundle_dir else {}
    exchange_order_rules = _exchange_order_rules(exchange_info)
    cost_model = _read_json(_resolve(root, cost_model_report_path))
    perpetual_evidence = _read_json(_resolve(root, perpetual_evidence_report_path))
    evidence_blockers = [str(item) for item in perpetual_evidence.get("blockers", []) if str(item)]

    observations = _load_observations(
        root=root,
        long_short_path=long_short_observations_path,
        attack_path=attack_observations_path,
        high_yield_path=high_yield_observations_path,
    )
    strategy_identities, strategy_identity_blockers = _bind_observation_strategy_identities(observations)
    replay_rows = [
        _replay_observation(
            row,
            market_rows=market_rows,
            mark_rows=mark_rows,
            premium_rows=premium_rows,
            funding_rows=funding_rows,
            cost_model=cost_model,
            evidence_blockers=evidence_blockers,
            exchange_order_rules=exchange_order_rules,
        )
        for row in observations
    ]
    event_rows = _build_event_ledger(
        replay_rows,
        ledger_scope="current_observe_only_paper_runtime_replay",
        diagnostic_drill_only=False,
    )
    oms_session = _build_oms_session(
        replay_rows=replay_rows,
        event_rows=event_rows,
        session_id="current_observe_only_paper_runtime_replay",
        generated_at_utc=generated,
    )
    blockers = _blockers(
        observations=observations,
        replay_rows=replay_rows,
        event_rows=event_rows,
        oms_session=oms_session,
        bundle_dir=bundle_dir,
        mark_rows=mark_rows,
        premium_rows=premium_rows,
        funding_rows=funding_rows,
        evidence_blockers=evidence_blockers,
    )
    blockers = sorted(set([*blockers, *strategy_identity_blockers]))
    summary = _summary(replay_rows=replay_rows, event_rows=event_rows, blockers=blockers, oms_session=oms_session)
    code_commit = _git_commit()
    nonflat_autocapture = build_btc_nonflat_evidence_autocapture(
        replay_rows=replay_rows,
        oms_session=oms_session,
        run_id=aggregation_batch_id or f"btc-observe-{generated.strftime('%Y%m%dT%H%M%SZ')}",
        strategy_version=_strategy_version_binding(strategy_identities),
        data_version=bundle_dir.name if bundle_dir else "immutable_data_version_unavailable",
        source_head=code_commit,
        sample_origin="current_natural_observation",
        private_ws_observed=False,
        funding_cashflow_observed=False,
    )
    gate_evidence_ready = (
        not blockers
        and summary.get("current_non_flat_sample_capture_status") == "gate_eligible_non_flat_capture_ready"
        and int(summary.get("gate_eligible_current_capture_count") or 0) > 0
    )
    current_flat_pending = (
        not blockers
        and summary.get("current_non_flat_sample_capture_status") == "flat_waiting_no_false_positive"
        and summary.get("trade_execution_evidence_available") is False
    )
    report_path = output / DEFAULT_REPORT_PATH.name
    rows_path = output / DEFAULT_ROWS_CSV_PATH.name
    event_ledger_path = output / DEFAULT_EVENT_LEDGER_PATH.name
    order_ledger_path = output / DEFAULT_ORDER_LEDGER_PATH.name
    fill_ledger_path = output / DEFAULT_FILL_LEDGER_PATH.name
    oms_reconciliation_path = output / DEFAULT_OMS_SESSION_RECONCILIATION_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": (
            "complete_research_only"
            if gate_evidence_ready
            else ("pending_research_only" if current_flat_pending else "incomplete_research_only")
        ),
        "decision": (
            "paper_runtime_replay_ready_for_manual_review"
            if gate_evidence_ready
            else (
                "perpetual_paper_runtime_replay_current_gate_evidence_pending_no_paper_no_live"
                if current_flat_pending
                else "perpetual_paper_runtime_replay_incomplete_fail_closed_no_paper_no_live"
            )
        ),
        "scope": "btc_current_perpetual_route_observe_only_paper_runtime_replay_no_order_no_broker",
        "code_commit": code_commit,
        "input": {
            "config_path": _portable_path(config_path),
            "selected_bundle_dir": _portable_path(bundle_dir) if bundle_dir else None,
            "long_short_observations_path": _portable_path(long_short_observations_path),
            "attack_observations_path": _portable_path(attack_observations_path),
            "high_yield_observations_path": _portable_path(high_yield_observations_path),
            "cost_model_report_path": _portable_path(cost_model_report_path),
            "perpetual_evidence_report_path": _portable_path(perpetual_evidence_report_path),
        },
        "simulation_policy": {
            "mode": "observe_only_paper_runtime_replay",
            "account_equity_usdt": DEFAULT_ACCOUNT_EQUITY_USDT,
            "fill_rule": "theoretical market order fills at first visible completed 1h mark close after decision_time",
            "funding_rule": "nearest visible funding row at or before simulated fill time; diagnostic only",
            "risk_policy": {
                "max_leverage": DEFAULT_MAX_LEVERAGE,
                "maintenance_margin_rate": DEFAULT_MAINTENANCE_MARGIN_RATE,
                "min_liquidation_buffer_bps": DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
            },
            "exchange_order_rules": exchange_order_rules,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
        "source_coverage": {
            "observation_row_count": len(observations),
            "market_row_count": len(market_rows),
            "mark_row_count": len(mark_rows),
            "premium_row_count": len(premium_rows),
            "funding_row_count": len(funding_rows),
            "exchange_info_present": bool(exchange_info),
            "perpetual_evidence_status": perpetual_evidence.get("status"),
            "perpetual_evidence_blockers": evidence_blockers,
            "observation_line_counts": _line_counts(observations),
        },
        "strategy_identities": strategy_identities,
        "strategy_identity_blockers": strategy_identity_blockers,
        "summary": summary,
        "nonflat_evidence_autocapture": nonflat_autocapture,
        "replay_rows": replay_rows,
        "event_ledger_preview": event_rows[:50],
        "oms_session": _oms_session_report_summary(oms_session),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": blockers,
        "warnings": _warnings(replay_rows=replay_rows, blockers=blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "rows_csv": _portable_path(rows_path),
            "event_ledger_csv": _portable_path(event_ledger_path),
            "order_ledger_csv": _portable_path(order_ledger_path),
            "fill_ledger_csv": _portable_path(fill_ledger_path),
            "oms_session_reconciliation_json": _portable_path(oms_reconciliation_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_rows_csv(rows_path, replay_rows)
    _write_event_ledger_csv(event_ledger_path, event_rows)
    _write_order_ledger_csv(order_ledger_path, oms_session["order_records"])
    _write_fill_ledger_csv(fill_ledger_path, oms_session["fill_records"])
    _write_json(oms_reconciliation_path, oms_session["reconciliation_report"])
    _write_text(markdown_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _strategy_version_binding(strategy_identities: Sequence[Mapping[str, Any]]) -> str:
    versions = sorted(
        {
            str(item.get("strategy_version") or item.get("version") or "")
            for item in strategy_identities
            if str(item.get("strategy_version") or item.get("version") or "")
        }
    )
    if versions:
        return "+".join(versions)
    payload = json.dumps(list(strategy_identities), ensure_ascii=False, sort_keys=True, default=str)
    return "registry-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_btc_perpetual_paper_runtime_replay_drill_report(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    bar_replay_rows_path: Path = DEFAULT_BAR_REPLAY_ROWS,
    cost_model_report_path: Path = DEFAULT_COST_MODEL_REPORT,
    perpetual_evidence_report_path: Path = DEFAULT_PERPETUAL_EVIDENCE_REPORT,
    sample_per_line: int = 8,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))

    bundle_dir = selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    market_rows = _read_table(bundle_dir / "klines_1h.csv" if bundle_dir else None)
    mark_rows = _read_table(bundle_dir / "mark_price_klines_1h.csv" if bundle_dir else None)
    premium_rows = _read_table(bundle_dir / "premium_index_klines_1h.csv" if bundle_dir else None)
    funding_rows = _read_table(bundle_dir / "funding_rate.csv" if bundle_dir else None)
    exchange_info = _read_json(bundle_dir / "exchange_info.json") if bundle_dir else {}
    exchange_order_rules = _exchange_order_rules(exchange_info)
    cost_model = _read_json(_resolve(root, cost_model_report_path))
    perpetual_evidence = _read_json(_resolve(root, perpetual_evidence_report_path))
    evidence_blockers = [str(item) for item in perpetual_evidence.get("blockers", []) if str(item)]

    observations = _load_bar_replay_drill_observations(
        root=root,
        bar_replay_rows_path=bar_replay_rows_path,
        mark_rows=mark_rows,
        sample_per_line=sample_per_line,
    )
    replay_rows = [
        _replay_drill_observation(
            row,
            market_rows=market_rows,
            mark_rows=mark_rows,
            premium_rows=premium_rows,
            funding_rows=funding_rows,
            cost_model=cost_model,
            ignored_evidence_blockers=evidence_blockers,
            exchange_order_rules=exchange_order_rules,
        )
        for row in observations
    ]
    event_rows = _build_event_ledger(
        replay_rows,
        ledger_scope="historical_bar_replay_execution_drill",
        diagnostic_drill_only=True,
    )
    oms_session = _build_oms_session(
        replay_rows=replay_rows,
        event_rows=event_rows,
        session_id="historical_bar_replay_execution_drill",
        generated_at_utc=generated,
    )
    blockers = _drill_blockers(
        observations=observations,
        replay_rows=replay_rows,
        bundle_dir=bundle_dir,
        mark_rows=mark_rows,
        premium_rows=premium_rows,
        funding_rows=funding_rows,
    )
    report_path = output / DEFAULT_DRILL_REPORT_PATH.name
    rows_path = output / DEFAULT_DRILL_ROWS_CSV_PATH.name
    event_ledger_path = output / DEFAULT_DRILL_EVENT_LEDGER_PATH.name
    order_ledger_path = output / DEFAULT_DRILL_ORDER_LEDGER_PATH.name
    fill_ledger_path = output / DEFAULT_DRILL_FILL_LEDGER_PATH.name
    oms_reconciliation_path = output / DEFAULT_DRILL_OMS_SESSION_RECONCILIATION_PATH.name
    markdown_path = output / DEFAULT_DRILL_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_DRILL_SAFETY_PATH.name
    report = {
        "schema_version": "btc_perpetual_paper_runtime_replay_drill_v1",
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "complete_research_only" if not blockers else "incomplete_research_only",
        "decision": (
            "perpetual_paper_runtime_replay_drill_complete_not_gate_evidence_no_paper_no_live"
            if not blockers
            else "perpetual_paper_runtime_replay_drill_incomplete_no_paper_no_live"
        ),
        "scope": "btc_historical_bar_replay_to_perpetual_execution_drill_diagnostic_only_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "config_path": _portable_path(config_path),
            "selected_bundle_dir": _portable_path(bundle_dir) if bundle_dir else None,
            "bar_replay_rows_path": _portable_path(bar_replay_rows_path),
            "cost_model_report_path": _portable_path(cost_model_report_path),
            "perpetual_evidence_report_path": _portable_path(perpetual_evidence_report_path),
            "sample_per_line": sample_per_line,
        },
        "drill_policy": {
            "mode": "historical_execution_replay_drill_only",
            "selection_rule": "latest visible non-flat bar-replay rows with a fillable selected-bundle mark row, capped per strategy line",
            "fill_rule": "theoretical market order fills at first visible completed 1h mark close after decision_time",
            "exchange_order_rules": exchange_order_rules,
            "ignored_current_execution_evidence_blockers": evidence_blockers,
            "paper_runtime_gate_eligible": False,
            "reason_not_gate_evidence": (
                "This drill intentionally replays historical bar-replay rows and ignores current execution-evidence blockers "
                "to exercise local fill/funding/liquidation fields. It cannot prove current paper readiness."
            ),
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
        "source_coverage": {
            "observation_row_count": len(observations),
            "observation_line_counts": _line_counts(observations),
            "market_row_count": len(market_rows),
            "mark_row_count": len(mark_rows),
            "premium_row_count": len(premium_rows),
            "funding_row_count": len(funding_rows),
            "exchange_info_present": bool(exchange_info),
            "perpetual_evidence_status": perpetual_evidence.get("status"),
            "perpetual_evidence_blockers": evidence_blockers,
        },
        "summary": _drill_summary(replay_rows=replay_rows, event_rows=event_rows, blockers=blockers, oms_session=oms_session),
        "replay_rows": replay_rows,
        "event_ledger_preview": event_rows[:50],
        "oms_session": _oms_session_report_summary(oms_session),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": blockers,
        "warnings": _drill_warnings(replay_rows=replay_rows, blockers=blockers, ignored_evidence_blockers=evidence_blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "rows_csv": _portable_path(rows_path),
            "event_ledger_csv": _portable_path(event_ledger_path),
            "order_ledger_csv": _portable_path(order_ledger_path),
            "fill_ledger_csv": _portable_path(fill_ledger_path),
            "oms_session_reconciliation_json": _portable_path(oms_reconciliation_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_drill_rows_csv(rows_path, replay_rows)
    _write_event_ledger_csv(event_ledger_path, event_rows)
    _write_order_ledger_csv(order_ledger_path, oms_session["order_records"])
    _write_fill_ledger_csv(fill_ledger_path, oms_session["fill_records"])
    _write_json(oms_reconciliation_path, oms_session["reconciliation_report"])
    _write_text(markdown_path, render_drill_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def build_btc_perpetual_paper_runtime_replay_fixture_drill_report(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))

    observations = _fixture_drill_observations()
    market_rows = _fixture_market_rows()
    mark_rows = _fixture_mark_rows()
    premium_rows = _fixture_premium_rows()
    funding_rows = _fixture_funding_rows()
    exchange_order_rules = _exchange_order_rules(_fixture_exchange_info())
    cost_model = {"fee_model": {"taker_fee_bps": 5.0}}
    replay_rows = [
        _replay_fixture_drill_observation(
            row,
            market_rows=market_rows,
            mark_rows=mark_rows,
            premium_rows=premium_rows,
            funding_rows=funding_rows,
            cost_model=cost_model,
            exchange_order_rules=exchange_order_rules,
        )
        for row in observations
    ]
    event_rows = _build_event_ledger(
        replay_rows,
        ledger_scope="deterministic_fixture_execution_drill",
        diagnostic_drill_only=True,
    )
    oms_session = _build_oms_session(
        replay_rows=replay_rows,
        event_rows=event_rows,
        session_id="deterministic_fixture_execution_drill",
        generated_at_utc=generated,
    )
    blockers = _fixture_drill_blockers(replay_rows=replay_rows, event_rows=event_rows, oms_session=oms_session)
    report_path = output / DEFAULT_FIXTURE_DRILL_REPORT_PATH.name
    rows_path = output / DEFAULT_FIXTURE_DRILL_ROWS_CSV_PATH.name
    event_ledger_path = output / DEFAULT_FIXTURE_DRILL_EVENT_LEDGER_PATH.name
    order_ledger_path = output / DEFAULT_FIXTURE_DRILL_ORDER_LEDGER_PATH.name
    fill_ledger_path = output / DEFAULT_FIXTURE_DRILL_FILL_LEDGER_PATH.name
    oms_reconciliation_path = output / DEFAULT_FIXTURE_DRILL_OMS_SESSION_RECONCILIATION_PATH.name
    markdown_path = output / DEFAULT_FIXTURE_DRILL_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_FIXTURE_DRILL_SAFETY_PATH.name
    report = {
        "schema_version": "btc_perpetual_paper_runtime_replay_fixture_drill_v1",
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "complete_research_only" if not blockers else "incomplete_research_only",
        "decision": (
            "perpetual_paper_runtime_replay_fixture_drill_complete_not_gate_evidence_no_paper_no_live"
            if not blockers
            else "perpetual_paper_runtime_replay_fixture_drill_incomplete_no_paper_no_live"
        ),
        "scope": "btc_deterministic_fixture_paper_runtime_replay_drill_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "fixture_source": "embedded_deterministic_fixture_rows",
            "external_market_data_used": False,
            "observe_only_stream_used": False,
            "config_path_used": False,
            "paper_runtime_gate_evidence": False,
        },
        "fixture_policy": {
            "mode": "deterministic_fixture_drill_only",
            "fixture_version": "btc_perpetual_paper_runtime_replay_fixture_v1",
            "scenario_count": len(observations),
            "scenario_ids": [str(row.get("fixture_scenario_id")) for row in observations],
            "fill_rule": "theoretical market order fills at first fixture completed 1h mark close after decision_time",
            "funding_rule": "nearest fixture funding row at or before simulated fill time",
            "reference_price_rule": "fixture mark/index rows are explicit and UTC timestamped",
            "paper_runtime_gate_eligible": False,
            "reason_not_gate_evidence": (
                "This fixture is deterministic and synthetic. It validates local order/fill/fee/funding/"
                "liquidation-buffer plumbing but cannot prove current paper readiness."
            ),
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
        "source_coverage": {
            "observation_row_count": len(observations),
            "observation_line_counts": _line_counts(observations),
            "market_row_count": len(market_rows),
            "mark_row_count": len(mark_rows),
            "premium_row_count": len(premium_rows),
            "funding_row_count": len(funding_rows),
            "exchange_info_present": True,
        },
        "summary": _fixture_drill_summary(replay_rows=replay_rows, event_rows=event_rows, blockers=blockers, oms_session=oms_session),
        "replay_rows": replay_rows,
        "event_ledger_preview": event_rows[:50],
        "oms_session": _oms_session_report_summary(oms_session),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": blockers,
        "warnings": _fixture_drill_warnings(replay_rows=replay_rows, blockers=blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "rows_csv": _portable_path(rows_path),
            "event_ledger_csv": _portable_path(event_ledger_path),
            "order_ledger_csv": _portable_path(order_ledger_path),
            "fill_ledger_csv": _portable_path(fill_ledger_path),
            "oms_session_reconciliation_json": _portable_path(oms_reconciliation_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_drill_rows_csv(rows_path, replay_rows)
    _write_event_ledger_csv(event_ledger_path, event_rows)
    _write_order_ledger_csv(order_ledger_path, oms_session["order_records"])
    _write_fill_ledger_csv(fill_ledger_path, oms_session["fill_records"])
    _write_json(oms_reconciliation_path, oms_session["reconciliation_report"])
    _write_text(markdown_path, render_fixture_drill_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC 永续 paper runtime observe-only 回放",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 观察行数：`{summary.get('observation_row_count')}`",
        f"- 观察线覆盖：`{summary.get('observation_line_counts')}`",
        f"- 理论订单数：`{summary.get('theoretical_order_count')}`",
        f"- 模拟成交数：`{summary.get('simulated_fill_count')}`",
        f"- 事件账本行数：`{summary.get('event_ledger_row_count')}`",
        f"- 风控拒绝数：`{summary.get('risk_rejected_count')}`",
        f"- 熔断触发数：`{summary.get('circuit_breaker_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 当前结论",
        "",
    ]
    if report.get("blockers"):
        lines.append("当前永续 paper runtime 回放还不够，继续 fail-closed。阻断项：")
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    else:
        lines.append("当前永续 paper runtime 回放字段完整，可进入人工复核，但仍不会自动写 paper 队列或解锁 live。")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本报告只把 observe-only 理论信号转成模拟订单/成交/资金费率/强平缓冲检查。",
            "- 它不使用 API key，不访问 private/order endpoint，不连接 broker/OMS，不真实下单。",
            "- 如果当前信号为空仓，报告会记录 heartbeat，但不会把“无成交”包装成 paper runtime 已通过。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_drill_summary_cn(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC 永续 paper runtime 历史执行重放演练",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 演练观察行数：`{summary.get('observation_row_count')}`",
        f"- 观察线覆盖：`{summary.get('observation_line_counts')}`",
        f"- 理论订单数：`{summary.get('theoretical_order_count')}`",
        f"- 模拟成交数：`{summary.get('simulated_fill_count')}`",
        f"- 事件账本行数：`{summary.get('event_ledger_row_count')}`",
        f"- 风控通过数：`{summary.get('risk_approved_count')}`",
        f"- 风控拒绝数：`{summary.get('risk_rejected_count')}`",
        f"- 资金费率合计：`{summary.get('funding_amount_total_usdt')}` USDT",
        f"- 手续费合计：`{summary.get('fee_amount_total_usdt')}` USDT",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论边界",
        "",
        "这个文件只证明本地 paper runtime 的模拟成交、资金费率、手续费和强平缓冲字段链路能在历史非空仓样本上跑通。",
        "它不是当前 paper 盘通过证据，也不会消除永续真实执行证据、L2 覆盖、当前空仓和无模拟成交等 blocker。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 演练阻断项", ""])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def render_fixture_drill_summary_cn(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC 永续 paper runtime deterministic fixture drill",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- fixture 场景数：`{summary.get('fixture_scenario_count')}`",
        f"- 理论订单数：`{summary.get('theoretical_order_count')}`",
        f"- 模拟成交数：`{summary.get('simulated_fill_count')}`",
        f"- funding cashflow 数：`{summary.get('funding_cashflow_event_count')}`",
        f"- mark/index 可见：`{summary.get('mark_index_price_visible')}`",
        f"- 强平 buffer 可见：`{summary.get('liquidation_buffer_visible_in_replay')}`",
        f"- chaos drill 覆盖：`{_mapping(summary.get('chaos_drill_coverage')).get('all_required_checks_passed')}`",
        f"- 事件账本行数：`{summary.get('event_ledger_row_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论边界",
        "",
        "这个 fixture drill 只证明本地 paper runtime 链路可以稳定产出 theoretical order、simulated fill、partial/cancel/reject/retry、reduce-only/cancel-only、WS gapfill、fee/funding cashflow、mark/index price 和 liquidation buffer。",
        "它使用内置 deterministic fixture，不读取真实 observe-only 流，不连接 broker/OMS/order，不是 paper promotion 证据。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## Drill 阻断项", ""])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _bind_observation_strategy_identities(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    identities: list[dict[str, Any]] = []
    blockers: list[str] = []
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        strategy_line = str(observation.get("strategy_line") or "")
        candidate_id = str(observation.get("candidate_id") or "")
        key = (strategy_line, candidate_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            spec = btc_strategy_registry.get(strategy_line, candidate_id)
        except BTCStrategyIdentityError:
            blockers.append(f"btc_paper_runtime_strategy_identity_unregistered:{strategy_line}:{candidate_id}")
            continue
        identities.append(
            {
                **spec.identity(),
                "source": "current_observe_only_observation",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return identities, sorted(set(blockers))


def _load_observations(
    *,
    root: Path,
    long_short_path: Path,
    attack_path: Path,
    high_yield_path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in _read_table(_resolve(root, long_short_path)):
        rank = _int(raw.get("rank"))
        if rank and rank > 5:
            continue
        exposure = _json_dict(raw.get("theoretical_exposure"))
        signal = _json_dict(raw.get("decision_signal"))
        rows.append(
            {
                "strategy_line": "long_short_donchian_top5",
                "candidate_id": raw.get("candidate_id") or raw.get("variant_id"),
                "decision_time": raw.get("decision_time"),
                "side": exposure.get("side") or signal.get("side") or "flat",
                "target_exposure": _float(exposure.get("value", signal.get("value", 0.0))),
                "signal": signal,
                "forecast": {
                    "signed_exposure_forecast": _float(exposure.get("value", signal.get("value", 0.0))),
                    "source_field": "decision_signal_and_theoretical_exposure",
                },
                "source_row": raw,
            }
        )
    for raw in _read_table(_resolve(root, high_yield_path)):
        raw_side = str(raw.get("theoretical_side") or "").strip().lower()
        raw_exposure = _float(raw.get("theoretical_exposure"))
        if raw_side == "flat":
            signed_exposure = 0.0
        elif raw_side == "long":
            signed_exposure = abs(raw_exposure)
        elif raw_side == "short":
            signed_exposure = -abs(raw_exposure)
        else:
            signed_exposure = raw_exposure
            raw_side = "long" if raw_exposure > 0.0 else ("short" if raw_exposure < 0.0 else "flat")
        rows.append(
            {
                "strategy_line": "high_yield_donchian_v2",
                "candidate_id": raw.get("variant_id") or "high_yield_v2",
                "decision_time": raw.get("decision_time"),
                "side": raw_side,
                "target_exposure": signed_exposure,
                "signal": {"side": raw_side, "raw_signal": raw.get("raw_signal")},
                "forecast": {
                    "signed_exposure_forecast": signed_exposure,
                    "source_field": "theoretical_exposure",
                },
                "source_row": raw,
            }
        )
    for raw in _read_table(_resolve(root, attack_path)):
        side = str(raw.get("daily_signal.side") or "flat")
        gross = _float(raw.get("theoretical_sleeve_exposure.gross_leverage_sum"))
        signed = 0.0 if side == "flat" else (gross if side == "long" else -gross)
        rows.append(
            {
                "strategy_line": "high_octane_attack_sleeve_v2",
                "candidate_id": raw.get("top_scenario_id") or "high_octane_attack",
                "decision_time": raw.get("decision_time"),
                "side": side,
                "target_exposure": signed,
                "signal": {"side": side, "source_field": "daily_signal.side"},
                "forecast": {
                    "signed_exposure_forecast": signed,
                    "source_field": "theoretical_sleeve_exposure.gross_leverage_sum",
                },
                "source_row": raw,
            }
        )
    return rows


def _load_bar_replay_drill_observations(
    *,
    root: Path,
    bar_replay_rows_path: Path,
    mark_rows: Sequence[Mapping[str, Any]],
    sample_per_line: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    raw_rows = _read_table(_resolve(root, bar_replay_rows_path))
    raw_rows.sort(key=lambda row: _timestamp_or_none(row.get("decision_time")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for raw in raw_rows:
        source_line = str(raw.get("line") or "")
        strategy_line = BAR_REPLAY_DRILL_LINE_MAP.get(source_line)
        if not strategy_line:
            continue
        if counts.get(strategy_line, 0) >= max(0, sample_per_line):
            continue
        decision_time = _timestamp_or_none(raw.get("decision_time"))
        if decision_time is None or not _first_visible_after(mark_rows, decision_time):
            continue
        exposure = _bar_replay_drill_target_exposure(raw)
        if exposure == 0.0:
            continue
        selected.append(
            {
                "strategy_line": strategy_line,
                "candidate_id": raw.get("candidate_id") or strategy_line,
                "decision_time": raw.get("decision_time"),
                "side": "long" if exposure > 0.0 else "short",
                "target_exposure": exposure,
                "source_line": source_line,
                "source_decision_time": raw.get("decision_time"),
                "source_rank": raw.get("rank"),
                "source_model_boundary_flag": _bool(raw.get("model_boundary_flag")),
                "source_execution_replay_required_before_paper": _bool(raw.get("execution_replay_required_before_paper")),
                "source_row": raw,
            }
        )
        counts[strategy_line] = counts.get(strategy_line, 0) + 1
    return selected


def _bar_replay_drill_target_exposure(row: Mapping[str, Any]) -> float:
    source_line = str(row.get("line") or "")
    if source_line in {"long_short_top5", "high_yield_v2"}:
        for field in ("next_bar_exposure", "current_bar_exposure", "raw_signal"):
            value = _float(row.get(field))
            if value != 0.0:
                return value
        return 0.0
    if source_line == "high_octane_v2":
        for field in ("current_bar_exposure", "raw_signal"):
            value = _float(row.get(field))
            if value != 0.0:
                return value
    return 0.0


def _fixture_drill_observations() -> list[dict[str, Any]]:
    base_rows = [
        {
            "strategy_line": "fixture_long_runtime_chain",
            "candidate_id": "fixture_long_1x",
            "decision_time": "2026-07-01T00:00:00+00:00",
            "target_exposure": 1.0,
            "fixture_scenario_id": "long_1x_positive_funding",
            "fixture_lifecycle_scenario": "full_fill",
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T00:00:00+00:00",
            "source_rank": 1,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
        {
            "strategy_line": "fixture_short_runtime_chain",
            "candidate_id": "fixture_short_0p75x",
            "decision_time": "2026-07-01T01:00:00+00:00",
            "target_exposure": -0.75,
            "fixture_scenario_id": "short_0p75x_negative_funding",
            "fixture_lifecycle_scenario": "full_fill",
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T01:00:00+00:00",
            "source_rank": 2,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
        {
            "strategy_line": "fixture_partial_cancel_runtime_chain",
            "candidate_id": "fixture_partial_cancel_reduce_only",
            "decision_time": "2026-07-01T02:00:00+00:00",
            "target_exposure": 0.6,
            "fixture_scenario_id": "partial_fill_then_cancel_reduce_only",
            "fixture_lifecycle_scenario": "partial_cancel",
            "reduce_only": True,
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T02:00:00+00:00",
            "source_rank": 3,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
        {
            "strategy_line": "fixture_reject_runtime_chain",
            "candidate_id": "fixture_exchange_reject",
            "decision_time": "2026-07-01T03:00:00+00:00",
            "target_exposure": 0.5,
            "fixture_scenario_id": "accepted_then_exchange_reject",
            "fixture_lifecycle_scenario": "exchange_reject",
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T03:00:00+00:00",
            "source_rank": 4,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
        {
            "strategy_line": "fixture_retry_runtime_chain",
            "candidate_id": "fixture_submit_unknown_retry_fill",
            "decision_time": "2026-07-01T04:00:00+00:00",
            "target_exposure": -0.5,
            "fixture_scenario_id": "submit_unknown_query_retry_fill",
            "fixture_lifecycle_scenario": "submit_unknown_retry_fill",
            "retry_required": True,
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T04:00:00+00:00",
            "source_rank": 5,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
        {
            "strategy_line": "fixture_cancel_only_runtime_chain",
            "candidate_id": "fixture_cancel_only_reject",
            "decision_time": "2026-07-01T05:00:00+00:00",
            "target_exposure": 0.5,
            "fixture_scenario_id": "cancel_only_blocks_new_order",
            "fixture_lifecycle_scenario": "cancel_only_reject",
            "cancel_only_mode": True,
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T05:00:00+00:00",
            "source_rank": 6,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
        {
            "strategy_line": "fixture_ws_gap_runtime_chain",
            "candidate_id": "fixture_ws_gapfill_fill",
            "decision_time": "2026-07-01T06:00:00+00:00",
            "target_exposure": 0.4,
            "fixture_scenario_id": "ws_sequence_gap_gapfill_then_fill",
            "fixture_lifecycle_scenario": "ws_gapfill_full_fill",
            "ws_sequence_gap_detected": True,
            "gapfill_replay_applied": True,
            "source_line": "embedded_fixture",
            "source_decision_time": "2026-07-01T06:00:00+00:00",
            "source_rank": 7,
            "source_model_boundary_flag": False,
            "source_execution_replay_required_before_paper": True,
        },
    ]
    return base_rows


def _fixture_market_rows() -> list[dict[str, Any]]:
    return _fixture_hourly_price_rows(price_field="close")


def _fixture_mark_rows() -> list[dict[str, Any]]:
    return _fixture_hourly_price_rows(price_field="close")


def _fixture_premium_rows() -> list[dict[str, Any]]:
    rows = []
    for item in _fixture_hourly_price_rows(price_field="close"):
        close = _float(item["close"])
        rows.append(
            {
                "timestamp": item["timestamp"],
                "event_time": item["event_time"],
                "available_time": item["available_time"],
                "mark_close": f"{close:.2f}",
                "index_close": f"{close + (20.0 if close >= 60000 else -20.0):.2f}",
            }
        )
    return rows


def _fixture_funding_rows() -> list[dict[str, Any]]:
    rates = [0.00010, -0.00005, 0.00008, -0.00003, 0.00006, -0.00004, 0.00002, 0.00001, -0.00002]
    rows = []
    prices = _fixture_hourly_price_rows(price_field="close")
    for idx, item in enumerate(prices):
        rows.append(
            {
                "timestamp": item["available_time"],
                "event_time": item["available_time"],
                "available_time": item["available_time"],
                "fundingRate": f"{rates[idx % len(rates)]:.8f}",
                "markPrice": item["close"],
            }
        )
    return rows


def _fixture_hourly_price_rows(*, price_field: str) -> list[dict[str, Any]]:
    prices = [60000, 59800, 60120, 60300, 59950, 60220, 60480, 60600, 60520]
    rows = []
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for idx, price in enumerate(prices):
        event_time = base + timedelta(hours=idx)
        available_time = event_time + timedelta(hours=1)
        rows.append(
            {
                "timestamp": event_time.isoformat().replace("+00:00", "Z"),
                "event_time": event_time.isoformat().replace("+00:00", "Z"),
                "available_time": available_time.isoformat().replace("+00:00", "Z"),
                price_field: str(price),
            }
        )
    return rows


def _fixture_exchange_info() -> dict[str, Any]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "api_key_used": False,
        "raw_symbol_info": {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "state": "live",
            "ctVal": "0.01",
            "tickSz": "0.1",
            "lotSz": "0.01",
            "minSz": "0.01",
            "maxMktSz": "35000",
        },
    }


def _exchange_order_rules(exchange_info: Mapping[str, Any]) -> dict[str, Any]:
    symbol_info = _mapping(exchange_info.get("raw_symbol_info"))
    contract_value = _decimal(symbol_info.get("ctVal")) or _decimal(DEFAULT_CONTRACT_VALUE_BTC)
    lot_size = _decimal(symbol_info.get("lotSz")) or _decimal(DEFAULT_LOT_SIZE_CONTRACTS)
    min_size = _decimal(symbol_info.get("minSz")) or lot_size
    max_market = _decimal(symbol_info.get("maxMktSz"))
    return {
        "venue": "OKX",
        "venue_symbol": symbol_info.get("instId") or exchange_info.get("venue_symbol"),
        "instrument_id": symbol_info.get("instId") or exchange_info.get("venue_symbol"),
        "instrument_state": symbol_info.get("state"),
        "instrument_type": symbol_info.get("instType"),
        "account_id": exchange_info.get("account_id") or "observe_only_no_private_account",
        "account_mode": exchange_info.get("account_mode") or "unknown_or_unattested",
        "position_mode": exchange_info.get("position_mode") or "unknown_or_unattested",
        "margin_mode": exchange_info.get("margin_mode") or "unknown_or_unattested",
        "margin_asset": symbol_info.get("settleCcy") or exchange_info.get("margin_asset") or "USDT",
        "metadata_version": f"okx:{symbol_info.get('instId') or exchange_info.get('venue_symbol') or 'BTC-USDT-SWAP'}:{symbol_info.get('instType') or 'SWAP'}",
        "contract_value_btc": str(contract_value),
        "lot_size_contracts": str(lot_size),
        "min_size_contracts": str(min_size),
        "max_market_size_contracts": str(max_market),
        "tick_size": str(_decimal(symbol_info.get("tickSz"))),
        "exchange_info_present": bool(exchange_info),
        "private_endpoint_used": bool(exchange_info.get("private_endpoint_used")),
        "order_endpoint_used": bool(exchange_info.get("order_endpoint_used")),
    }


def _exchange_lot_sizing(
    *,
    target_exposure: float,
    execution_price: float,
    exchange_order_rules: Mapping[str, Any],
) -> dict[str, Any]:
    sign = Decimal("1") if target_exposure > 0 else Decimal("-1")
    target_notional = abs(_decimal(target_exposure)) * _decimal(DEFAULT_ACCOUNT_EQUITY_USDT)
    price = _decimal(execution_price)
    contract_value = _decimal(exchange_order_rules.get("contract_value_btc"))
    lot_size = _decimal(exchange_order_rules.get("lot_size_contracts"))
    min_size = _decimal(exchange_order_rules.get("min_size_contracts"))
    max_market = _decimal(exchange_order_rules.get("max_market_size_contracts"))
    blockers: list[str] = []
    if price <= 0 or contract_value <= 0 or lot_size <= 0:
        blockers.append("btc_perpetual_order_exchange_metadata_missing_or_invalid")
        return {
            "blockers": blockers,
            "quantity_btc": Decimal("0"),
            "actual_exposure": Decimal("0"),
            "notional_usdt": Decimal("0"),
            "row_fields": {
                "target_notional_usdt": _float_decimal(target_notional),
                "requested_quantity_btc": 0.0,
                "requested_contracts": 0.0,
                "rounded_contracts": 0.0,
                "actual_exposure": 0.0,
                "notional_usdt": 0.0,
                "quantity_btc": 0.0,
                "sizing_status": "exchange_metadata_invalid",
            },
        }
    requested_quantity_btc_abs = target_notional / price
    requested_contracts = requested_quantity_btc_abs / contract_value
    rounded_contracts = _round_down_to_step(requested_contracts, lot_size)
    if rounded_contracts <= 0:
        blockers.append("btc_perpetual_order_size_rounds_to_zero")
    if min_size > 0 and rounded_contracts < min_size:
        blockers.append("btc_perpetual_order_size_below_exchange_min_size")
    if max_market > 0 and rounded_contracts > max_market:
        blockers.append("btc_perpetual_order_size_above_exchange_max_market_size")
    quantity_btc_abs = rounded_contracts * contract_value
    notional = quantity_btc_abs * price
    actual_exposure = sign * notional / _decimal(DEFAULT_ACCOUNT_EQUITY_USDT)
    requested_notional_remainder = target_notional - notional
    sizing_status = "exact_lot_aligned" if requested_contracts == rounded_contracts else "rounded_down_to_exchange_lot"
    if blockers:
        sizing_status = "blocked_by_exchange_order_filter"
    return {
        "blockers": blockers,
        "quantity_btc": sign * quantity_btc_abs,
        "actual_exposure": actual_exposure,
        "notional_usdt": notional,
        "row_fields": {
            "target_notional_usdt": _float_decimal(target_notional),
            "requested_quantity_btc": _float_decimal(sign * requested_quantity_btc_abs),
            "requested_contracts": _float_decimal(requested_contracts),
            "rounded_contracts": _float_decimal(rounded_contracts),
            "contract_value_btc": str(contract_value),
            "lot_size_contracts": str(lot_size),
            "actual_exposure": _float_decimal(actual_exposure),
            "notional_usdt": _float_decimal(notional),
            "quantity_btc": _float_decimal(sign * quantity_btc_abs),
            "sizing_status": sizing_status,
            "sizing_remainder_notional_usdt": _float_decimal(requested_notional_remainder),
        },
    }


def _round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if value <= 0 or step <= 0:
        return Decimal("0")
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _replay_observation(
    observation: Mapping[str, Any],
    *,
    market_rows: Sequence[Mapping[str, Any]],
    mark_rows: Sequence[Mapping[str, Any]],
    premium_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    cost_model: Mapping[str, Any],
    evidence_blockers: Sequence[str],
    exchange_order_rules: Mapping[str, Any],
) -> dict[str, Any]:
    decision_time = _timestamp_or_none(observation.get("decision_time"))
    exposure = _float(observation.get("target_exposure"))
    side = "flat" if exposure == 0.0 else ("long" if exposure > 0.0 else "short")
    row: dict[str, Any] = {
        "strategy_line": observation.get("strategy_line"),
        "candidate_id": observation.get("candidate_id"),
        "decision_time": None if decision_time is None else decision_time.isoformat(),
        "side": side,
        "venue": exchange_order_rules.get("venue") or "OKX",
        "venue_symbol": exchange_order_rules.get("venue_symbol") or "BTC-USDT-SWAP",
        "instrument_id": exchange_order_rules.get("instrument_id") or exchange_order_rules.get("venue_symbol") or "BTC-USDT-SWAP",
        "instrument_type": exchange_order_rules.get("instrument_type") or "SWAP",
        "account_id": exchange_order_rules.get("account_id") or "observe_only_no_private_account",
        "account_mode": exchange_order_rules.get("account_mode") or "unknown_or_unattested",
        "position_mode": exchange_order_rules.get("position_mode") or "unknown_or_unattested",
        "margin_mode": exchange_order_rules.get("margin_mode") or "unknown_or_unattested",
        "margin_asset": exchange_order_rules.get("margin_asset") or "USDT",
        "exchange_metadata_version": exchange_order_rules.get("metadata_version") or "",
        "order_type": "market" if exposure != 0.0 else "none",
        "time_in_force": "ioc" if exposure != 0.0 else "none",
        "reduce_only": False,
        "post_only": False,
        "cancel_only_mode": False,
        "fee_side": "taker" if exposure != 0.0 else "none",
        "target_exposure": exposure,
        "signal": observation.get("signal"),
        "forecast": observation.get("forecast"),
        "actual_exposure": 0.0,
        "order_intent": "none_flat" if exposure == 0.0 else "market_rebalance",
        "theoretical_order_created": exposure != 0.0,
        "simulated_fill_created": False,
        "fill_time": None,
        "execution_price": 0.0,
        "mark_price": 0.0,
        "index_price": 0.0,
        "liquidation_price": None,
        "liquidation_buffer_bps": None,
        "risk_approved": False,
        "risk_action": "hold_flat" if exposure == 0.0 else "not_evaluated",
        "risk_decision": "hold_flat" if exposure == 0.0 else "not_evaluated",
        "risk_decision_detail": {},
        "risk_blockers": [],
        "circuit_breakers": [],
        "fee_amount_usdt": 0.0,
        "modeled_slippage_bps": 0.0,
        "funding_amount_usdt": 0.0,
        "target_notional_usdt": 0.0,
        "requested_quantity_btc": 0.0,
        "requested_contracts": 0.0,
        "rounded_contracts": 0.0,
        "contract_value_btc": exchange_order_rules.get("contract_value_btc"),
        "lot_size_contracts": exchange_order_rules.get("lot_size_contracts"),
        "sizing_status": "not_applicable_flat" if exposure == 0.0 else "not_evaluated",
        "sizing_remainder_notional_usdt": 0.0,
        "paper_runtime_gate_eligible": False,
        "paper_promotion_blockers": [],
        "capture_only_warning_flags": [],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    if decision_time is None:
        row["risk_blockers"] = ["btc_perpetual_paper_runtime_decision_time_missing"]
        return row
    if exposure == 0.0:
        return row

    fill_mark = _first_visible_after(mark_rows, decision_time)
    if not fill_mark:
        row["risk_blockers"] = ["btc_perpetual_paper_runtime_mark_fill_row_missing"]
        row["risk_action"] = "blocked_by_missing_mark_fill_row"
        row["risk_decision"] = "blocked_by_missing_mark_fill_row"
        return row
    fill_time = _timestamp_or_none(fill_mark.get("available_time") or fill_mark.get("timestamp"))
    premium = _nearest_visible_at_or_before(premium_rows, fill_time or decision_time)
    funding = _nearest_visible_at_or_before(funding_rows, fill_time or decision_time)
    market = _nearest_visible_at_or_before(market_rows, fill_time or decision_time)
    execution_price = _float(fill_mark.get("close"))
    index_price = _float(premium.get("index_close"))
    mark_price = _float(fill_mark.get("close"))
    signal_price = _float(market.get("close")) or execution_price
    row.update(
        {
            "fill_time": None if fill_time is None else fill_time.isoformat(),
            "execution_price": round(execution_price, 8),
            "mark_price": round(mark_price, 8),
            "index_price": round(index_price, 8),
        }
    )
    if execution_price <= 0.0:
        row["risk_blockers"] = ["btc_perpetual_paper_runtime_execution_price_missing"]
        row["risk_action"] = "blocked_by_missing_execution_price"
        row["risk_decision"] = "blocked_by_missing_execution_price"
        return row
    sizing = _exchange_lot_sizing(
        target_exposure=exposure,
        execution_price=execution_price,
        exchange_order_rules=exchange_order_rules,
    )
    row.update(sizing["row_fields"])
    if sizing["blockers"]:
        row["risk_blockers"] = sizing["blockers"]
        row["risk_action"] = "blocked_by_exchange_order_filter"
        row["risk_decision"] = "blocked_by_exchange_order_filter"
        return row
    proposed_qty = _float(sizing["quantity_btc"])
    actual_exposure = _float(sizing["actual_exposure"])
    notional = _float(sizing["notional_usdt"])
    risk = evaluate_btc_perp_liquidation_risk(
        reference_prices=BTCReferencePriceState(
            observed_at_utc=fill_time or decision_time,
            signal_price=signal_price,
            execution_price=execution_price,
            mark_price=mark_price if mark_price > 0.0 else None,
            index_price=index_price if index_price > 0.0 else None,
            current_mark_price=mark_price if mark_price > 0.0 else None,
            spread_bps=None,
            cross_venue_deviation_bps=None,
            data_age_ms=0,
            source="selected_perpetual_bundle_mark_price_1h",
        ),
        position=BTCPerpPositionState(
            current_quantity=0.0,
            proposed_quantity=proposed_qty,
            account_equity=DEFAULT_ACCOUNT_EQUITY_USDT,
            side=side,
        ),
        policy=BTCLiquidationPolicy(
            max_leverage=DEFAULT_MAX_LEVERAGE,
            maintenance_margin_rate=DEFAULT_MAINTENANCE_MARGIN_RATE,
            min_liquidation_buffer_bps=DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
            max_reference_price_age_ms=int(timedelta(hours=8).total_seconds() * 1000),
            max_cross_venue_deviation_bps=200.0,
            max_spread_bps=50.0,
        ),
    )
    fee_bps = _float(_mapping(cost_model.get("fee_model")).get("taker_fee_bps")) or 5.0
    funding_rate = _float(funding.get("fundingRate", funding.get("funding_rate")))
    risk_blockers = list(risk.blockers)
    risk_approved = bool(risk.approved)
    risk_action = risk.action
    risk_decision = "approved" if risk.approved else "rejected"
    simulated_fill_created = bool(risk.approved)
    circuit_breakers: list[str] = []
    if evidence_blockers:
        circuit_breakers.append("paper_promotion_blocked_by_execution_evidence")
        if _execution_evidence_blocks_capture(evidence_blockers):
            circuit_breakers.append("execution_evidence_safety_violation_blocks_capture")
            risk_blockers = _dedupe([*risk_blockers, *[str(item) for item in evidence_blockers]])
            risk_approved = False
            risk_action = "blocked_by_execution_evidence_safety_violation"
            risk_decision = "blocked_by_execution_evidence_safety_violation"
            simulated_fill_created = False
    row.update(
        {
            "execution_price": round(execution_price, 8),
            "mark_price": round(mark_price, 8),
            "index_price": round(index_price, 8),
            "notional_usdt": round(notional, 8),
            "quantity_btc": round(proposed_qty, 12),
            "fee_amount_usdt": round(notional * fee_bps / 10_000.0, 8),
            "funding_rate": funding_rate,
            "funding_amount_usdt": round(-actual_exposure * DEFAULT_ACCOUNT_EQUITY_USDT * funding_rate, 8),
            "risk_approved": risk_approved,
            "risk_action": risk_action,
            "risk_decision": risk_decision,
            "risk_decision_detail": risk.to_metadata(),
            "risk_blockers": risk_blockers,
            "circuit_breakers": circuit_breakers,
            "paper_promotion_blockers": [str(item) for item in evidence_blockers],
            "capture_only_warning_flags": (
                ["current_sample_captured_but_paper_promotion_remains_blocked"]
                if evidence_blockers and simulated_fill_created
                else []
            ),
            "liquidation_price": risk.liquidation_price,
            "liquidation_buffer_bps": risk.liquidation_buffer_bps,
            "simulated_fill_created": simulated_fill_created,
        }
    )
    if simulated_fill_created:
        signed_quantity = proposed_qty if side == "long" else -proposed_qty
        row["position_ledger"] = {
            "instrument_id": row["instrument_id"],
            "quantity_btc": round(signed_quantity, 12),
            "mark_price": round(mark_price, 8),
        }
        row["cash_ledger"] = {
            "starting_cash_usdt": DEFAULT_ACCOUNT_EQUITY_USDT,
            "fee_cashflow_usdt": -abs(_float(row["fee_amount_usdt"])),
            "funding_cashflow_usdt": _float(row["funding_amount_usdt"]),
            "ending_cash_usdt": round(
                DEFAULT_ACCOUNT_EQUITY_USDT
                - abs(_float(row["fee_amount_usdt"]))
                + _float(row["funding_amount_usdt"]),
                8,
            ),
        }
    row["paper_runtime_gate_eligible"] = _row_has_complete_current_gate_evidence(row)
    return row


def _execution_evidence_blocks_capture(evidence_blockers: Sequence[str]) -> bool:
    for blocker in evidence_blockers:
        text = str(blocker).lower()
        if any(keyword in text for keyword in CAPTURE_BLOCKING_EXECUTION_EVIDENCE_KEYWORDS):
            return True
    return False


def _row_has_complete_current_gate_evidence(row: Mapping[str, Any]) -> bool:
    if row.get("diagnostic_drill_only") or row.get("deterministic_fixture_drill_only"):
        return False
    if row.get("theoretical_order_created") is not True or row.get("simulated_fill_created") is not True:
        return False
    if row.get("risk_approved") is not True or str(row.get("risk_decision") or "") != "approved":
        return False
    execution_price = _float(row.get("execution_price"))
    mark_price = _float(row.get("mark_price"))
    index_price = _float(row.get("index_price"))
    notional = _float(row.get("notional_usdt"))
    quantity = _float(row.get("quantity_btc"))
    liquidation_price = _float(row.get("liquidation_price"))
    liquidation_buffer = _float(row.get("liquidation_buffer_bps"))
    if execution_price is None or execution_price <= 0.0:
        return False
    if mark_price is None or mark_price <= 0.0 or index_price is None or index_price <= 0.0:
        return False
    if notional is None or notional <= 0.0 or quantity is None or quantity == 0.0:
        return False
    if liquidation_price is None or liquidation_price <= 0.0 or liquidation_buffer is None:
        return False
    if row.get("fill_time") in {None, ""}:
        return False
    if row.get("funding_rate") in {None, ""} or row.get("funding_amount_usdt") in {None, ""}:
        return False
    return True


def _replay_drill_observation(
    observation: Mapping[str, Any],
    *,
    market_rows: Sequence[Mapping[str, Any]],
    mark_rows: Sequence[Mapping[str, Any]],
    premium_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    cost_model: Mapping[str, Any],
    ignored_evidence_blockers: Sequence[str],
    exchange_order_rules: Mapping[str, Any],
) -> dict[str, Any]:
    row = _replay_observation(
        observation,
        market_rows=market_rows,
        mark_rows=mark_rows,
        premium_rows=premium_rows,
        funding_rows=funding_rows,
        cost_model=cost_model,
        evidence_blockers=[],
        exchange_order_rules=exchange_order_rules,
    )
    row.update(
        {
            "diagnostic_drill_only": True,
            "paper_runtime_gate_eligible": False,
            "ignored_current_execution_evidence_blockers": list(ignored_evidence_blockers),
            "source_line": observation.get("source_line"),
            "source_decision_time": observation.get("source_decision_time"),
            "source_rank": observation.get("source_rank"),
            "source_model_boundary_flag": observation.get("source_model_boundary_flag"),
            "source_execution_replay_required_before_paper": observation.get("source_execution_replay_required_before_paper"),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    )
    return row


def _replay_fixture_drill_observation(
    observation: Mapping[str, Any],
    *,
    market_rows: Sequence[Mapping[str, Any]],
    mark_rows: Sequence[Mapping[str, Any]],
    premium_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    cost_model: Mapping[str, Any],
    exchange_order_rules: Mapping[str, Any],
) -> dict[str, Any]:
    row = _replay_observation(
        observation,
        market_rows=market_rows,
        mark_rows=mark_rows,
        premium_rows=premium_rows,
        funding_rows=funding_rows,
        cost_model=cost_model,
        evidence_blockers=[],
        exchange_order_rules=exchange_order_rules,
    )
    lifecycle_scenario = str(observation.get("fixture_lifecycle_scenario") or "full_fill")
    if lifecycle_scenario == "partial_cancel" and row.get("simulated_fill_created"):
        row["simulated_filled_quantity_btc"] = round(abs(_float(row.get("quantity_btc"))) * 0.5, 12)
    if lifecycle_scenario == "exchange_reject" and row.get("theoretical_order_created"):
        row.update(
            {
                "simulated_fill_created": False,
                "capture_only_warning_flags": _dedupe(
                    [*list(row.get("capture_only_warning_flags", [])), "fixture_exchange_reject_diagnostic_no_fill"]
                ),
            }
        )
    if lifecycle_scenario == "cancel_only_reject" and row.get("theoretical_order_created"):
        row.update(
            {
                "risk_approved": False,
                "risk_action": "blocked_by_cancel_only_mode",
                "risk_decision": "blocked_by_cancel_only_mode",
                "risk_blockers": _dedupe([*list(row.get("risk_blockers", [])), "fixture_cancel_only_mode_blocks_new_order"]),
                "simulated_fill_created": False,
                "capture_only_warning_flags": _dedupe(
                    [*list(row.get("capture_only_warning_flags", [])), "fixture_cancel_only_reject_diagnostic"]
                ),
            }
        )
    row.update(
        {
            "diagnostic_drill_only": True,
            "deterministic_fixture_drill_only": True,
            "fixture_scenario_id": observation.get("fixture_scenario_id"),
            "fixture_lifecycle_scenario": lifecycle_scenario,
            "reduce_only": bool(observation.get("reduce_only")),
            "cancel_only_mode": bool(observation.get("cancel_only_mode")),
            "retry_required": bool(observation.get("retry_required")),
            "ws_sequence_gap_detected": bool(observation.get("ws_sequence_gap_detected")),
            "gapfill_replay_applied": bool(observation.get("gapfill_replay_applied")),
            "paper_runtime_gate_eligible": False,
            "ignored_current_execution_evidence_blockers": [],
            "source_line": observation.get("source_line"),
            "source_decision_time": observation.get("source_decision_time"),
            "source_rank": observation.get("source_rank"),
            "source_model_boundary_flag": observation.get("source_model_boundary_flag"),
            "source_execution_replay_required_before_paper": observation.get("source_execution_replay_required_before_paper"),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    )
    return row


def _build_event_ledger(
    replay_rows: Sequence[Mapping[str, Any]],
    *,
    ledger_scope: str,
    diagnostic_drill_only: bool,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, row in enumerate(replay_rows):
        common = _event_common(row, ledger_scope=ledger_scope, diagnostic_drill_only=diagnostic_drill_only)
        if not row.get("theoretical_order_created"):
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="flat_heartbeat",
                    event_time=row.get("decision_time"),
                    event_state="held_flat",
                    amount_usdt=0.0,
                )
            )
            continue
        if row.get("reduce_only"):
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="reduce_only_intent_validated",
                    event_time=row.get("decision_time"),
                    event_state="diagnostic_reduce_only",
                    amount_usdt=0.0,
                )
            )
        if row.get("cancel_only_mode"):
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="cancel_only_guard_checked",
                    event_time=row.get("decision_time"),
                    event_state="new_order_blocked_diagnostic",
                    amount_usdt=0.0,
                )
            )
        if row.get("retry_required"):
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="retry_state_checked",
                    event_time=row.get("decision_time"),
                    event_state="query_status_before_retry",
                    amount_usdt=0.0,
                )
            )
        if row.get("ws_sequence_gap_detected"):
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="ws_sequence_gap_detected",
                    event_time=row.get("decision_time"),
                    event_state="gap_detected",
                    amount_usdt=0.0,
                )
            )
            if row.get("gapfill_replay_applied"):
                events.append(
                    _event_row(
                        common,
                        index=index,
                        event_type="ws_gapfill_replay_completed",
                        event_time=row.get("fill_time"),
                        event_state="gapfilled_before_fill",
                        amount_usdt=0.0,
                    )
                )
        events.append(
            _event_row(
                common,
                index=index,
                event_type="order_intent_created",
                event_time=row.get("decision_time"),
                event_state="created",
                amount_usdt=_float(row.get("notional_usdt")),
            )
        )
        risk_state = "approved" if row.get("risk_approved") else "rejected"
        events.append(
            _event_row(
                common,
                index=index,
                event_type="risk_checked",
                event_time=row.get("decision_time"),
                event_state=risk_state,
                amount_usdt=0.0,
            )
        )
        for breaker in row.get("circuit_breakers", []):
            event = _event_row(
                common,
                index=index,
                event_type="circuit_breaker_triggered",
                event_time=row.get("decision_time"),
                event_state=str(breaker),
                amount_usdt=0.0,
            )
            event["risk_blockers"] = _csv_value(row.get("risk_blockers", []))
            events.append(event)
        if not row.get("simulated_fill_created"):
            continue
        events.append(
            _event_row(
                common,
                index=index,
                event_type="simulated_fill",
                event_time=row.get("fill_time"),
                event_state="filled",
                amount_usdt=_float(row.get("notional_usdt")),
            )
        )
        if _float(row.get("fee_amount_usdt")) != 0.0:
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="fee_cashflow",
                    event_time=row.get("fill_time"),
                    event_state="settled",
                    amount_usdt=-abs(_float(row.get("fee_amount_usdt"))),
                )
            )
        if row.get("funding_rate") not in {None, ""}:
            events.append(
                _event_row(
                    common,
                    index=index,
                    event_type="funding_cashflow",
                    event_time=row.get("fill_time"),
                    event_state="diagnostic_nearest_visible_funding",
                    amount_usdt=_float(row.get("funding_amount_usdt")),
                )
            )
    return events


def _oms_session_report_summary(oms_session: Mapping[str, Any]) -> dict[str, Any]:
    reconciliation = _mapping(oms_session.get("reconciliation_report"))
    return {
        "session_id": oms_session.get("session_id"),
        "ledger_hash": oms_session.get("ledger_hash"),
        "order_ledger_row_count": len(oms_session.get("order_records", [])),
        "fill_ledger_row_count": len(oms_session.get("fill_records", [])),
        "reconciliation_status": reconciliation.get("status"),
        "reconciliation_decision": reconciliation.get("decision"),
        "unreconciled_count": reconciliation.get("unreconciled_order_count", oms_session.get("unreconciled_count")),
        "unreconciled_client_order_ids": reconciliation.get("unreconciled_client_order_ids", []),
        "missing_fill_client_order_ids": reconciliation.get("missing_fill_client_order_ids", []),
        "unknown_fill_client_order_ids": reconciliation.get("unknown_fill_client_order_ids", []),
        "blocker_count": len(reconciliation.get("blockers", [])),
        "blockers": list(reconciliation.get("blockers", [])),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _event_common(row: Mapping[str, Any], *, ledger_scope: str, diagnostic_drill_only: bool) -> dict[str, Any]:
    return {
        "ledger_scope": ledger_scope,
        "strategy_line": row.get("strategy_line"),
        "candidate_id": row.get("candidate_id"),
        "decision_time": row.get("decision_time"),
        "side": row.get("side"),
        "venue": row.get("venue"),
        "venue_symbol": row.get("venue_symbol"),
        "instrument_id": row.get("instrument_id"),
        "instrument_type": row.get("instrument_type"),
        "account_id": row.get("account_id"),
        "account_mode": row.get("account_mode"),
        "position_mode": row.get("position_mode"),
        "margin_mode": row.get("margin_mode"),
        "margin_asset": row.get("margin_asset"),
        "target_exposure": row.get("target_exposure"),
        "actual_exposure": row.get("actual_exposure"),
        "notional_usdt": row.get("notional_usdt", 0.0),
        "quantity_btc": row.get("quantity_btc", 0.0),
        "execution_price": row.get("execution_price"),
        "mark_price": row.get("mark_price"),
        "index_price": row.get("index_price"),
        "liquidation_price": row.get("liquidation_price"),
        "liquidation_buffer_bps": row.get("liquidation_buffer_bps"),
        "risk_action": row.get("risk_action"),
        "risk_decision": row.get("risk_decision"),
        "risk_approved": row.get("risk_approved"),
        "risk_blockers": _csv_value(row.get("risk_blockers", [])),
        "diagnostic_drill_only": diagnostic_drill_only or bool(row.get("diagnostic_drill_only")),
        "paper_runtime_gate_eligible": bool(row.get("paper_runtime_gate_eligible", False)),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _event_row(
    common: Mapping[str, Any],
    *,
    index: int,
    event_type: str,
    event_time: Any,
    event_state: str,
    amount_usdt: float,
) -> dict[str, Any]:
    event_id = f"{common.get('ledger_scope')}:{common.get('candidate_id')}:{common.get('decision_time')}:{index}:{event_type}"
    row = dict(common)
    row.update(
        {
            "event_id": event_id,
            "event_type": event_type,
            "event_time": event_time,
            "event_state": event_state,
            "amount_usdt": round(amount_usdt, 8),
        }
    )
    return row


def _blockers(
    *,
    observations: Sequence[Mapping[str, Any]],
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    oms_session: Mapping[str, Any],
    bundle_dir: Path | None,
    mark_rows: Sequence[Mapping[str, Any]],
    premium_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    evidence_blockers: Sequence[str],
) -> list[str]:
    blockers: list[str] = []
    if not observations:
        blockers.append("btc_perpetual_paper_runtime_replay_observations_missing")
    line_counts = _line_counts(observations)
    for line in REQUIRED_OBSERVATION_LINES:
        if line_counts.get(line, 0) == 0:
            blockers.append(f"btc_perpetual_paper_runtime_replay_{line}_observations_missing")
    if bundle_dir is None:
        blockers.append("btc_perpetual_paper_runtime_replay_selected_bundle_missing")
    if not mark_rows:
        blockers.append("btc_perpetual_paper_runtime_replay_mark_rows_missing")
    if not premium_rows:
        blockers.append("btc_perpetual_paper_runtime_replay_index_rows_missing")
    if not funding_rows:
        blockers.append("btc_perpetual_paper_runtime_replay_funding_rows_missing")
    event_type_counts = _event_type_counts(event_rows)
    current_flat_heartbeat_healthy = _current_flat_heartbeat_healthy(
        replay_rows=replay_rows,
        event_rows=event_rows,
        event_type_counts=event_type_counts,
    )
    theoretical_order_count = sum(1 for row in replay_rows if row.get("theoretical_order_created"))
    simulated_fill_count = sum(1 for row in replay_rows if row.get("simulated_fill_created"))
    if evidence_blockers and theoretical_order_count > 0:
        blockers.append("btc_perpetual_paper_runtime_replay_execution_evidence_blocked")
    if simulated_fill_count == 0 and not current_flat_heartbeat_healthy:
        blockers.append("btc_perpetual_paper_runtime_replay_no_simulated_fills")
    liquidation_evidence = _liquidation_buffer_evidence(replay_rows)
    if liquidation_evidence["theoretical_order_count"] > 0 and not liquidation_evidence["visible_in_replay"]:
        blockers.append("btc_perpetual_paper_runtime_replay_liquidation_risk_fields_missing")
    capture_contract = _current_non_flat_capture_contract(
        replay_rows=replay_rows,
        event_rows=event_rows,
        event_type_counts=event_type_counts,
        oms_session=oms_session,
        current_flat_heartbeat_healthy=current_flat_heartbeat_healthy,
    )
    if capture_contract["theoretical_order_count"] > 0 and capture_contract["status"] != "gate_eligible_non_flat_capture_ready":
        blockers.append("btc_perpetual_paper_runtime_replay_current_non_flat_capture_contract_incomplete")
        blockers.extend(str(item) for item in capture_contract.get("contract_blockers", []))
    if capture_contract["flat_false_positive"]:
        blockers.append("btc_perpetual_paper_runtime_replay_flat_false_positive_order_or_fill")
    for row in replay_rows:
        for item in row.get("risk_blockers", []):
            if item not in evidence_blockers:
                blockers.append(str(item))
        for item in row.get("circuit_breakers", []):
            blockers.append(str(item))
    return _dedupe(blockers)


def _summary(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    oms_session: Mapping[str, Any],
) -> dict[str, Any]:
    event_type_counts = _event_type_counts(event_rows)
    theoretical_order_count = sum(1 for row in replay_rows if row.get("theoretical_order_created"))
    simulated_fill_count = sum(1 for row in replay_rows if row.get("simulated_fill_created"))
    flat_heartbeat_count = sum(1 for row in replay_rows if not row.get("theoretical_order_created"))
    current_flat_heartbeat_healthy = _current_flat_heartbeat_healthy(
        replay_rows=replay_rows,
        event_rows=event_rows,
        event_type_counts=event_type_counts,
    )
    trade_execution_evidence_available = theoretical_order_count > 0 and simulated_fill_count > 0
    liquidation_buffer_evidence = _liquidation_buffer_evidence(replay_rows)
    current_non_flat_capture = _current_non_flat_capture_contract(
        replay_rows=replay_rows,
        event_rows=event_rows,
        event_type_counts=event_type_counts,
        oms_session=oms_session,
        current_flat_heartbeat_healthy=current_flat_heartbeat_healthy,
    )
    current_gate_evidence_ready = (
        not blockers
        and current_non_flat_capture["status"] == "gate_eligible_non_flat_capture_ready"
        and current_non_flat_capture["gate_eligible_fill_count"] > 0
    )
    current_gate_evidence_state = (
        "passed"
        if current_gate_evidence_ready
        else ("pending" if current_flat_heartbeat_healthy and not trade_execution_evidence_available else "failed")
    )
    return {
        "observation_row_count": len(replay_rows),
        "observation_line_counts": _line_counts(replay_rows),
        "theoretical_order_count": theoretical_order_count,
        "simulated_fill_count": simulated_fill_count,
        "gate_eligible_current_capture_count": current_non_flat_capture["gate_eligible_fill_count"],
        "risk_rejected_count": sum(1 for row in replay_rows if row.get("theoretical_order_created") and not row.get("risk_approved")),
        "flat_heartbeat_count": flat_heartbeat_count,
        "current_flat_heartbeat_healthy": current_flat_heartbeat_healthy,
        "trade_execution_evidence_available": trade_execution_evidence_available,
        "current_non_flat_sample_capture_status": current_non_flat_capture["status"],
        "current_non_flat_sample_capture_contract": current_non_flat_capture,
        "evidence_layers": _runtime_evidence_layers(
            fixture_capability_passed=False,
            historical_drill_passed=False,
            current_observe_only_gate_evidence_state=current_gate_evidence_state,
            current_observe_only_gate_evidence_passed=current_gate_evidence_ready,
        ),
        "current_observe_only_gate_evidence_state": current_gate_evidence_state,
        "current_observe_only_gate_evidence_passed": current_gate_evidence_ready,
        "flat_no_gate_eligible_trade": current_flat_heartbeat_healthy and not trade_execution_evidence_available,
        "liquidation_buffer_evidence": liquidation_buffer_evidence,
        "liquidation_buffer_visible_in_replay": liquidation_buffer_evidence["visible_in_replay"],
        "trade_execution_evidence_pending_reason": _trade_execution_evidence_pending_reason(
            current_flat_heartbeat_healthy=current_flat_heartbeat_healthy,
            theoretical_order_count=theoretical_order_count,
            simulated_fill_count=simulated_fill_count,
        ),
        "paper_runtime_health_status": _paper_runtime_health_status(
            current_flat_heartbeat_healthy=current_flat_heartbeat_healthy,
            trade_execution_evidence_available=trade_execution_evidence_available,
            blockers=blockers,
        ),
        "non_blocking_pending_conditions": _non_blocking_pending_conditions(
            current_flat_heartbeat_healthy=current_flat_heartbeat_healthy,
            trade_execution_evidence_available=trade_execution_evidence_available,
        ),
        "circuit_breaker_count": sum(len(row.get("circuit_breakers", [])) for row in replay_rows),
        "funding_amount_total_usdt": round(sum(_float(row.get("funding_amount_usdt")) for row in replay_rows), 8),
        "fee_amount_total_usdt": round(sum(_float(row.get("fee_amount_usdt")) for row in replay_rows), 8),
        "event_ledger_row_count": len(event_rows),
        "event_type_counts": event_type_counts,
        "order_ledger_row_count": len(oms_session.get("order_records", [])),
        "fill_ledger_row_count": len(oms_session.get("fill_records", [])),
        "oms_session_reconciliation_status": _nested_reconciliation(oms_session, "status"),
        "oms_session_unreconciled_count": oms_session.get("unreconciled_count", 0),
        "oms_session_reconciliation_blocker_count": len(_nested_reconciliation(oms_session, "blockers") or []),
        "fill_ledger_event_count": event_type_counts.get("simulated_fill", 0),
        "funding_cashflow_event_count": event_type_counts.get("funding_cashflow", 0),
        "circuit_breaker_event_count": event_type_counts.get("circuit_breaker_triggered", 0),
        "paper_runtime_replay_ready": current_gate_evidence_ready,
        "paper_runtime_gate_evidence": current_gate_evidence_ready,
        "blocker_count": len(blockers),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _current_flat_heartbeat_healthy(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    event_type_counts: Mapping[str, int],
) -> bool:
    if not replay_rows:
        return False
    if any(row.get("theoretical_order_created") for row in replay_rows):
        return False
    if len(event_rows) != len(replay_rows):
        return False
    return dict(event_type_counts) == {"flat_heartbeat": len(replay_rows)}


def _trade_execution_evidence_pending_reason(
    *,
    current_flat_heartbeat_healthy: bool,
    theoretical_order_count: int,
    simulated_fill_count: int,
) -> str | None:
    if theoretical_order_count > 0 and simulated_fill_count > 0:
        return None
    if current_flat_heartbeat_healthy:
        return "waiting_for_current_gate_eligible_non_flat_fill"
    if theoretical_order_count == 0:
        return "theoretical_order_sample_missing"
    return "simulated_fill_sample_missing"


def _paper_runtime_health_status(
    *,
    current_flat_heartbeat_healthy: bool,
    trade_execution_evidence_available: bool,
    blockers: Sequence[str],
) -> str:
    if trade_execution_evidence_available and not blockers:
        return "trade_execution_sample_present"
    if current_flat_heartbeat_healthy:
        return "current_flat_heartbeat_healthy_waiting_for_trade_sample"
    return "incomplete"


def _non_blocking_pending_conditions(
    *,
    current_flat_heartbeat_healthy: bool,
    trade_execution_evidence_available: bool,
) -> list[str]:
    if current_flat_heartbeat_healthy and not trade_execution_evidence_available:
        return [
            "flat_no_gate_eligible_trade",
            "waiting_for_current_gate_eligible_non_flat_fill",
        ]
    return []


def _runtime_evidence_layers(
    *,
    fixture_capability_passed: bool,
    historical_drill_passed: bool,
    current_observe_only_gate_evidence_state: str,
    current_observe_only_gate_evidence_passed: bool,
) -> dict[str, Any]:
    return {
        "fixture_capability_passed": bool(fixture_capability_passed),
        "historical_drill_passed": bool(historical_drill_passed),
        "current_observe_only_gate_evidence_state": current_observe_only_gate_evidence_state,
        "current_observe_only_gate_evidence_passed": bool(current_observe_only_gate_evidence_passed),
        "current_observe_only_gate_evidence_pending": current_observe_only_gate_evidence_state == "pending",
        "fixture_or_drill_can_clear_paper_gate": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _current_non_flat_capture_contract(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    event_type_counts: Mapping[str, int],
    oms_session: Mapping[str, Any],
    current_flat_heartbeat_healthy: bool,
) -> dict[str, Any]:
    theoretical_rows = [row for row in replay_rows if row.get("theoretical_order_created")]
    gate_rows = [row for row in theoretical_rows if row.get("paper_runtime_gate_eligible") is True]
    simulated_rows = [row for row in theoretical_rows if row.get("simulated_fill_created") is True]
    flat_false_positive = (
        not theoretical_rows
        and (
            bool(simulated_rows)
            or event_type_counts.get("simulated_fill", 0) > 0
            or len(oms_session.get("order_records", [])) > 0
            or len(oms_session.get("fill_records", [])) > 0
        )
    )
    risk_decision_recorded = bool(theoretical_rows) and all(
        str(row.get("risk_decision") or "") not in {"", "not_evaluated"} for row in theoretical_rows
    )
    liquidation_buffer_recorded = bool(simulated_rows) and all(
        _float(row.get("mark_price")) and _float(row.get("index_price")) and _float(row.get("liquidation_buffer_bps")) is not None
        for row in simulated_rows
    )
    mark_index_price_recorded = bool(simulated_rows) and all(
        _float(row.get("mark_price")) > 0.0 and _float(row.get("index_price")) > 0.0 for row in simulated_rows
    )
    depth_mapping_required_fields = [
        "strategy_line",
        "candidate_id",
        "decision_time",
        "fill_time",
        "side",
        "notional_usdt",
        "quantity_btc",
        "execution_price",
        "mark_price",
        "index_price",
        "liquidation_buffer_bps",
        "risk_decision",
        "paper_runtime_gate_eligible",
    ]
    depth_mapping_rows_exported = bool(gate_rows) and all(
        all(row.get(field) not in {None, ""} for field in depth_mapping_required_fields) for row in gate_rows
    )
    if not gate_rows:
        depth_mapping_state = "no_gate_eligible_fill"
    elif not depth_mapping_rows_exported:
        depth_mapping_state = "mapping_logic_failed"
    else:
        depth_mapping_state = "current_gate_fill_mapped"
    requirements = {
        "flat_does_not_create_order_or_fill": current_flat_heartbeat_healthy or bool(theoretical_rows),
        "theoretical_order_recorded": bool(theoretical_rows),
        "risk_decision_recorded": risk_decision_recorded,
        "simulated_fill_recorded": bool(simulated_rows),
        "oms_lifecycle_recorded": bool(oms_session.get("order_records")) and _nested_reconciliation(oms_session, "status") == "complete",
        "funding_cashflow_recorded": event_type_counts.get("funding_cashflow", 0) > 0,
        "mark_index_price_recorded": mark_index_price_recorded,
        "liquidation_buffer_recorded": liquidation_buffer_recorded,
        "depth_fill_mapping_ready_for_downstream": depth_mapping_rows_exported,
    }
    contract_blockers = [
        f"current_non_flat_capture_missing:{name}"
        for name, passed in requirements.items()
        if theoretical_rows and not passed
    ]
    if flat_false_positive:
        status = "flat_false_positive_violation"
    elif not theoretical_rows and current_flat_heartbeat_healthy:
        status = "flat_waiting_no_false_positive"
    elif gate_rows and all(requirements.values()):
        status = "gate_eligible_non_flat_capture_ready"
    elif theoretical_rows and not simulated_rows:
        status = "non_flat_seen_but_simulated_fill_not_captured"
    else:
        status = "non_flat_capture_incomplete"
    return {
        "schema_version": "btc_current_non_flat_sample_capture_contract_v1",
        "status": status,
        "flat_false_positive": flat_false_positive,
        "theoretical_order_count": len(theoretical_rows),
        "simulated_fill_count": len(simulated_rows),
        "gate_eligible_fill_count": len(gate_rows),
        "order_ledger_row_count": len(oms_session.get("order_records", [])),
        "fill_ledger_row_count": len(oms_session.get("fill_records", [])),
        "funding_cashflow_event_count": event_type_counts.get("funding_cashflow", 0),
        "oms_session_reconciliation_status": _nested_reconciliation(oms_session, "status"),
        "oms_session_unreconciled_count": oms_session.get("unreconciled_count", 0),
        "required_capture_fields": [
            "theoretical_order",
            "risk_decision",
            "oms_lifecycle",
            "simulated_fill",
            "funding_cashflow",
            "mark_price",
            "index_price",
            "liquidation_buffer",
            "depth_fill_mapping_row",
        ],
        "requirements": requirements,
        "contract_blockers": contract_blockers,
        "depth_fill_mapping_contract": {
            "producer": "btc_perpetual_paper_runtime_replay_rows_csv",
            "consumer": "btc_depth_slippage_fill_mapping",
            "required_row_fields": depth_mapping_required_fields,
            "state_catalog": [
                "no_gate_eligible_fill",
                "depth_not_visible",
                "mapping_logic_failed",
                "current_gate_fill_mapped",
            ],
            "current_state": depth_mapping_state,
            "no_gate_eligible_fill": depth_mapping_state == "no_gate_eligible_fill",
            "depth_not_visible": False,
            "mapping_logic_failed": depth_mapping_state == "mapping_logic_failed",
            "gate_eligible_row_count": len(gate_rows),
            "rows_exported": depth_mapping_rows_exported,
            "fixture_or_drill_cannot_clear_gate": True,
        },
        "depth_fill_mapping_status": (
            "downstream_fill_mapping_can_consume_current_gate_eligible_fill"
            if depth_mapping_rows_exported
            else depth_mapping_state
        ),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _drill_blockers(
    *,
    observations: Sequence[Mapping[str, Any]],
    replay_rows: Sequence[Mapping[str, Any]],
    bundle_dir: Path | None,
    mark_rows: Sequence[Mapping[str, Any]],
    premium_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    if not observations:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_observations_missing")
    if bundle_dir is None:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_selected_bundle_missing")
    if not mark_rows:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_mark_rows_missing")
    if not premium_rows:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_index_rows_missing")
    if not funding_rows:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_funding_rows_missing")
    if sum(1 for row in replay_rows if row.get("theoretical_order_created")) == 0:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_no_theoretical_orders")
    if sum(1 for row in replay_rows if row.get("simulated_fill_created")) == 0:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_no_simulated_fills")
    liquidation_evidence = _liquidation_buffer_evidence(replay_rows)
    if liquidation_evidence["theoretical_order_count"] > 0 and not liquidation_evidence["visible_in_replay"]:
        blockers.append("btc_perpetual_paper_runtime_replay_drill_liquidation_risk_fields_missing")
    return _dedupe(blockers)


def _drill_summary(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    oms_session: Mapping[str, Any],
) -> dict[str, Any]:
    event_type_counts = _event_type_counts(event_rows)
    liquidation_buffer_evidence = _liquidation_buffer_evidence(replay_rows)
    return {
        "observation_row_count": len(replay_rows),
        "observation_line_counts": _line_counts(replay_rows),
        "theoretical_order_count": sum(1 for row in replay_rows if row.get("theoretical_order_created")),
        "simulated_fill_count": sum(1 for row in replay_rows if row.get("simulated_fill_created")),
        "risk_approved_count": sum(1 for row in replay_rows if row.get("risk_approved")),
        "risk_rejected_count": sum(1 for row in replay_rows if row.get("theoretical_order_created") and not row.get("risk_approved")),
        "diagnostic_drill_only_count": sum(1 for row in replay_rows if row.get("diagnostic_drill_only")),
        "gate_eligible_count": sum(1 for row in replay_rows if row.get("paper_runtime_gate_eligible")),
        "source_model_boundary_count": sum(1 for row in replay_rows if row.get("source_model_boundary_flag")),
        "funding_amount_total_usdt": round(sum(_float(row.get("funding_amount_usdt")) for row in replay_rows), 8),
        "fee_amount_total_usdt": round(sum(_float(row.get("fee_amount_usdt")) for row in replay_rows), 8),
        "event_ledger_row_count": len(event_rows),
        "event_type_counts": event_type_counts,
        "order_ledger_row_count": len(oms_session.get("order_records", [])),
        "fill_ledger_row_count": len(oms_session.get("fill_records", [])),
        "oms_session_reconciliation_status": _nested_reconciliation(oms_session, "status"),
        "oms_session_unreconciled_count": oms_session.get("unreconciled_count", 0),
        "oms_session_reconciliation_blocker_count": len(_nested_reconciliation(oms_session, "blockers") or []),
        "fill_ledger_event_count": event_type_counts.get("simulated_fill", 0),
        "funding_cashflow_event_count": event_type_counts.get("funding_cashflow", 0),
        "circuit_breaker_event_count": event_type_counts.get("circuit_breaker_triggered", 0),
        "liquidation_buffer_evidence": liquidation_buffer_evidence,
        "liquidation_buffer_visible_in_replay": liquidation_buffer_evidence["visible_in_replay"],
        "paper_runtime_drill_ready": not blockers,
        "paper_runtime_gate_evidence": False,
        "evidence_layers": _runtime_evidence_layers(
            fixture_capability_passed=False,
            historical_drill_passed=not bool(blockers),
            current_observe_only_gate_evidence_state="not_applicable_diagnostic_historical_drill",
            current_observe_only_gate_evidence_passed=False,
        ),
        "blocker_count": len(blockers),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _fixture_drill_blockers(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    oms_session: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    event_type_counts = _event_type_counts(event_rows)
    coverage = _fixture_chaos_drill_coverage(replay_rows=replay_rows, event_rows=event_rows, oms_session=oms_session)
    if not replay_rows:
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_rows_missing")
    if sum(1 for row in replay_rows if row.get("theoretical_order_created")) == 0:
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_no_theoretical_orders")
    if sum(1 for row in replay_rows if row.get("simulated_fill_created")) == 0:
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_no_simulated_fills")
    if event_type_counts.get("funding_cashflow", 0) == 0:
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_no_funding_cashflow")
    if any(_float(row.get("mark_price")) <= 0.0 or _float(row.get("index_price")) <= 0.0 for row in replay_rows):
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_mark_or_index_price_missing")
    if not _liquidation_buffer_evidence(replay_rows)["visible_in_replay"]:
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_liquidation_risk_fields_missing")
    if any(row.get("paper_queue_write_allowed") is True or row.get("live_unlock_allowed") is True for row in replay_rows):
        blockers.append("btc_perpetual_paper_runtime_fixture_drill_safety_flag_true")
    for key, passed in coverage.get("required_checks", {}).items():
        if passed is not True:
            blockers.append(f"btc_perpetual_paper_runtime_fixture_drill_chaos_coverage_missing:{key}")
    return _dedupe(blockers)


def _fixture_drill_summary(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    oms_session: Mapping[str, Any],
) -> dict[str, Any]:
    summary = _drill_summary(replay_rows=replay_rows, event_rows=event_rows, blockers=blockers, oms_session=oms_session)
    mark_index_price_visible = bool(replay_rows) and all(
        _float(row.get("mark_price")) > 0.0 and _float(row.get("index_price")) > 0.0 for row in replay_rows
    )
    fixture_ids = [str(row.get("fixture_scenario_id")) for row in replay_rows if row.get("fixture_scenario_id")]
    coverage = _fixture_chaos_drill_coverage(replay_rows=replay_rows, event_rows=event_rows, oms_session=oms_session)
    summary.update(
        {
            "deterministic_fixture_drill": True,
            "fixture_scenario_count": len(fixture_ids),
            "fixture_scenario_ids": fixture_ids,
            "fixture_lifecycle_scenarios": sorted(
                {str(row.get("fixture_lifecycle_scenario")) for row in replay_rows if row.get("fixture_lifecycle_scenario")}
            ),
            "chaos_drill_coverage": coverage,
            "mark_index_price_visible": mark_index_price_visible,
            "mark_price_row_count": sum(1 for row in replay_rows if _float(row.get("mark_price")) > 0.0),
            "index_price_row_count": sum(1 for row in replay_rows if _float(row.get("index_price")) > 0.0),
            "theoretical_order_created": summary["theoretical_order_count"] > 0,
            "simulated_fill_created": summary["simulated_fill_count"] > 0,
            "funding_cashflow_created": summary["funding_cashflow_event_count"] > 0,
            "paper_runtime_fixture_drill_ready": not blockers,
            "paper_runtime_gate_evidence": False,
            "evidence_layers": _runtime_evidence_layers(
                fixture_capability_passed=not bool(blockers),
                historical_drill_passed=False,
                current_observe_only_gate_evidence_state="not_applicable_diagnostic_fixture",
                current_observe_only_gate_evidence_passed=False,
            ),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    )
    return summary


def _fixture_chaos_drill_coverage(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    oms_session: Mapping[str, Any],
) -> dict[str, Any]:
    event_type_counts = _event_type_counts(event_rows)
    lifecycle_statuses = _oms_lifecycle_status_counts(oms_session)
    reconciliation = _mapping(oms_session.get("reconciliation_report"))
    required_checks = {
        "partial_fill": lifecycle_statuses.get("partially_filled", 0) > 0,
        "cancel": lifecycle_statuses.get("cancel_requested", 0) > 0 and lifecycle_statuses.get("cancelled", 0) > 0,
        "reject": lifecycle_statuses.get("rejected", 0) > 0,
        "retry": lifecycle_statuses.get("unknown", 0) > 0 and event_type_counts.get("retry_state_checked", 0) > 0,
        "reduce_only": any(row.get("reduce_only") is True for row in replay_rows),
        "cancel_only": any(row.get("cancel_only_mode") is True for row in replay_rows)
        and event_type_counts.get("cancel_only_guard_checked", 0) > 0,
        "funding_cashflow": event_type_counts.get("funding_cashflow", 0) > 0,
        "liquidation_buffer": _liquidation_buffer_evidence(replay_rows)["visible_in_replay"],
        "ws_gapfill_replay": event_type_counts.get("ws_sequence_gap_detected", 0) > 0
        and event_type_counts.get("ws_gapfill_replay_completed", 0) > 0,
        "oms_reconciliation": reconciliation.get("status") == "complete"
        and _int(reconciliation.get("unreconciled_order_count")) == 0,
    }
    return {
        "scope": "diagnostic_fixture_only_not_current_gate_evidence",
        "required_checks": required_checks,
        "all_required_checks_passed": all(required_checks.values()),
        "lifecycle_status_counts": lifecycle_statuses,
        "event_type_counts": event_type_counts,
        "paper_runtime_gate_evidence": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _oms_lifecycle_status_counts(oms_session: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for order in oms_session.get("order_records", []):
        for event in _list(order.get("events")):
            status = str(_mapping(event).get("status") or "")
            if status:
                counts[status] = counts.get(status, 0) + 1
    return counts


def _liquidation_buffer_evidence(replay_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in replay_rows if row.get("theoretical_order_created")]
    fill_rows = [row for row in replay_rows if row.get("simulated_fill_created")]
    buffers = [_float(row.get("liquidation_buffer_bps")) for row in rows]
    buffers = [value for value in buffers if value > 0.0]
    mark_rows = [row for row in rows if _float(row.get("mark_price")) > 0.0]
    index_rows = [row for row in rows if _float(row.get("index_price")) > 0.0]
    risk_decision_rows = [row for row in rows if str(row.get("risk_decision") or "").strip()]
    complete_rows = [
        row
        for row in rows
        if _float(row.get("mark_price")) > 0.0
        and _float(row.get("index_price")) > 0.0
        and _float(row.get("liquidation_buffer_bps")) > 0.0
        and str(row.get("risk_decision") or "").strip()
    ]
    return {
        "visible_in_replay": bool(rows) and len(complete_rows) == len(rows),
        "theoretical_order_count": len(rows),
        "simulated_fill_count": len(fill_rows),
        "required_row_count": len(rows),
        "complete_row_count": len(complete_rows),
        "buffer_row_count": len(buffers),
        "missing_mark_price_count": len(rows) - len(mark_rows),
        "missing_index_price_count": len(rows) - len(index_rows),
        "missing_liquidation_buffer_count": len(rows) - len(buffers),
        "missing_risk_decision_count": len(rows) - len(risk_decision_rows),
        "min_liquidation_buffer_bps": round(min(buffers), 6) if buffers else None,
        "max_liquidation_buffer_bps": round(max(buffers), 6) if buffers else None,
        "mark_price_row_count": len(mark_rows),
        "index_price_row_count": len(index_rows),
        "uses_mark_price_reference": bool(rows) and len(mark_rows) == len(rows),
    }


def _warnings(*, replay_rows: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_perpetual_paper_runtime_replay_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("perpetual_paper_runtime_replay_incomplete_fail_closed")
    if replay_rows and all(not row.get("theoretical_order_created") for row in replay_rows):
        warnings.append("current_observe_only_signal_is_flat_no_fill_evidence")
    return warnings


def _drill_warnings(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    ignored_evidence_blockers: Sequence[str],
) -> list[str]:
    warnings = ["btc_perpetual_paper_runtime_replay_drill_diagnostic_only_no_paper_no_live"]
    if blockers:
        warnings.append("perpetual_paper_runtime_replay_drill_incomplete")
    if ignored_evidence_blockers:
        warnings.append("current_execution_evidence_blockers_intentionally_ignored_for_diagnostic_drill")
    if any(row.get("simulated_fill_created") for row in replay_rows):
        warnings.append("simulated_fills_are_historical_drill_not_current_paper_evidence")
    return warnings


def _fixture_drill_warnings(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
) -> list[str]:
    warnings = ["btc_perpetual_paper_runtime_replay_fixture_drill_diagnostic_only_no_paper_no_live"]
    if blockers:
        warnings.append("perpetual_paper_runtime_replay_fixture_drill_incomplete")
    if any(row.get("simulated_fill_created") for row in replay_rows):
        warnings.append("simulated_fills_are_deterministic_fixture_not_current_paper_evidence")
    warnings.append("fixture_drill_must_not_clear_observe_only_or_execution_gate_blockers")
    return warnings


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(report.get("summary"))
    return {
        "schema_version": "btc_perpetual_paper_runtime_replay_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_runtime_replay_ready": summary.get("paper_runtime_replay_ready", False),
        "paper_runtime_drill_ready": summary.get("paper_runtime_drill_ready", False),
        "paper_runtime_fixture_drill_ready": summary.get("paper_runtime_fixture_drill_ready", False),
        "paper_runtime_gate_evidence": summary.get("paper_runtime_gate_evidence", False),
        "oms_session_unreconciled_count": summary.get("oms_session_unreconciled_count", 0),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _first_visible_after(rows: Sequence[Mapping[str, Any]], decision_time: datetime) -> Mapping[str, Any]:
    candidates = []
    upper = decision_time + timedelta(hours=8)
    for row in rows:
        ts = _timestamp_or_none(row.get("available_time") or row.get("timestamp"))
        if ts and decision_time < ts <= upper:
            candidates.append((ts, row))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else {}


def _nearest_visible_at_or_before(rows: Sequence[Mapping[str, Any]], as_of: datetime) -> Mapping[str, Any]:
    candidates = []
    for row in rows:
        ts = _timestamp_or_none(row.get("available_time") or row.get("timestamp"))
        if ts and ts <= as_of:
            candidates.append((ts, row))
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1] if candidates else {}


def _read_table(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "strategy_line",
        "candidate_id",
        "decision_time",
        "side",
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "exchange_metadata_version",
        "order_type",
        "time_in_force",
        "reduce_only",
        "post_only",
        "cancel_only_mode",
        "fee_side",
        "target_exposure",
        "actual_exposure",
        "order_intent",
        "theoretical_order_created",
        "simulated_fill_created",
        "fill_time",
        "execution_price",
        "mark_price",
        "index_price",
        "notional_usdt",
        "quantity_btc",
        "simulated_filled_quantity_btc",
        "target_notional_usdt",
        "requested_quantity_btc",
        "requested_contracts",
        "rounded_contracts",
        "contract_value_btc",
        "lot_size_contracts",
        "sizing_status",
        "sizing_remainder_notional_usdt",
        "fee_amount_usdt",
        "modeled_slippage_bps",
        "funding_rate",
        "funding_amount_usdt",
        "risk_approved",
        "risk_action",
        "risk_decision",
        "risk_decision_detail",
        "risk_blockers",
        "liquidation_price",
        "liquidation_buffer_bps",
        "circuit_breakers",
        "paper_runtime_gate_eligible",
        "paper_promotion_blockers",
        "capture_only_warning_flags",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _write_drill_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "strategy_line",
        "candidate_id",
        "decision_time",
        "side",
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "exchange_metadata_version",
        "order_type",
        "time_in_force",
        "reduce_only",
        "post_only",
        "cancel_only_mode",
        "fee_side",
        "target_exposure",
        "actual_exposure",
        "order_intent",
        "theoretical_order_created",
        "simulated_fill_created",
        "fill_time",
        "execution_price",
        "mark_price",
        "index_price",
        "notional_usdt",
        "quantity_btc",
        "target_notional_usdt",
        "requested_quantity_btc",
        "requested_contracts",
        "rounded_contracts",
        "contract_value_btc",
        "lot_size_contracts",
        "sizing_status",
        "sizing_remainder_notional_usdt",
        "fee_amount_usdt",
        "modeled_slippage_bps",
        "funding_rate",
        "funding_amount_usdt",
        "risk_approved",
        "risk_action",
        "risk_decision",
        "risk_decision_detail",
        "risk_blockers",
        "liquidation_price",
        "liquidation_buffer_bps",
        "diagnostic_drill_only",
        "paper_runtime_gate_eligible",
        "ignored_current_execution_evidence_blockers",
        "source_line",
        "source_decision_time",
        "source_rank",
        "source_model_boundary_flag",
        "source_execution_replay_required_before_paper",
        "fixture_scenario_id",
        "fixture_lifecycle_scenario",
        "reduce_only",
        "cancel_only_mode",
        "retry_required",
        "ws_sequence_gap_detected",
        "gapfill_replay_applied",
        "deterministic_fixture_drill_only",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _write_event_ledger_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "event_id",
        "ledger_scope",
        "event_type",
        "event_time",
        "event_state",
        "strategy_line",
        "candidate_id",
        "decision_time",
        "side",
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "target_exposure",
        "actual_exposure",
        "notional_usdt",
        "quantity_btc",
        "requested_contracts",
        "rounded_contracts",
        "sizing_status",
        "execution_price",
        "mark_price",
        "index_price",
        "liquidation_price",
        "liquidation_buffer_bps",
        "risk_action",
        "risk_decision",
        "risk_approved",
        "risk_blockers",
        "amount_usdt",
        "diagnostic_drill_only",
        "paper_runtime_gate_eligible",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _write_order_ledger_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "session_id",
        "lifecycle_version",
        "order_id",
        "order_intent_id",
        "client_order_id",
        "broker_order_id",
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "exchange_metadata_version",
        "strategy_id",
        "symbol",
        "side",
        "quantity",
        "order_type",
        "time_in_force",
        "reduce_only",
        "post_only",
        "cancel_only_mode",
        "fee_side",
        "arrival_price",
        "benchmark_price",
        "mark_price",
        "index_price",
        "liquidation_price",
        "liquidation_buffer_bps",
        "risk_decision",
        "paper_runtime_gate_eligible",
        "status",
        "filled_quantity",
        "remaining_quantity",
        "event_count",
        "events",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _write_fill_ledger_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "session_id",
        "client_order_id",
        "fill_id",
        "venue",
        "venue_symbol",
        "instrument_id",
        "instrument_type",
        "account_id",
        "account_mode",
        "position_mode",
        "margin_mode",
        "margin_asset",
        "strategy_id",
        "symbol",
        "side",
        "filled_quantity",
        "arrival_price",
        "fill_price",
        "benchmark_price",
        "slippage_bps",
        "fee_side",
        "mark_price",
        "index_price",
        "liquidation_price",
        "liquidation_buffer_bps",
        "risk_decision",
        "paper_runtime_gate_eligible",
        "submitted_at_utc",
        "filled_at_utc",
        "latency_ms",
        "implementation_shortfall",
        "fee",
        "spread_cost",
        "market_impact_cost",
        "delay_cost",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp_or_none(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value in {None, ""}:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _nested_reconciliation(oms_session: Mapping[str, Any], key: str) -> Any:
    return _mapping(oms_session.get("reconciliation_report")).get(key)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _decimal(value: Any) -> Decimal:
    try:
        if value in {None, ""}:
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _float_decimal(value: Decimal) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _line_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        line = str(row.get("strategy_line") or "")
        if line:
            counts[line] = counts.get(line, 0) + 1
    return counts


def _event_type_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        event_type = str(row.get("event_type") or "")
        if event_type:
            counts[event_type] = counts.get(event_type, 0) + 1
    return counts
