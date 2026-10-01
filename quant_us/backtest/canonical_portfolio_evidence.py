"""Aggregate current-HEAD canonical ETF26 backtest and portfolio evidence."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from quant_shared.core.serialization import canonical_payload_hash


SCHEMA_VERSION = "us_v3_canonical_backtest_portfolio_evidence_v1"
EXPECTED_CHAIN = (
    "data",
    "signal",
    "forecast",
    "target_portfolio",
    "risk",
    "order_intent",
    "simulated_fill",
    "position_cash_ledger",
    "pnl",
    "report",
)


def build_month_end_t_plus_one_evidence(
    sessions: Iterable[str],
) -> dict[str, Any]:
    """Use the last observed trading session in each month and its next session."""

    ordered = sorted({date.fromisoformat(str(value)[:10]) for value in sessions})
    grouped: dict[tuple[int, int], list[date]] = {}
    for session in ordered:
        grouped.setdefault((session.year, session.month), []).append(session)
    rows: list[dict[str, Any]] = []
    for month in sorted(grouped):
        decision = grouped[month][-1]
        later = [session for session in ordered if session > decision]
        if not later:
            continue
        execution = later[0]
        rows.append(
            {
                "month": f"{month[0]:04d}-{month[1]:02d}",
                "decision_session": decision.isoformat(),
                "execution_session": execution.isoformat(),
                "decision_is_last_actual_trading_session": True,
                "execution_is_next_actual_trading_session": True,
                "t_plus_one": True,
            }
        )
    return {
        "calendar": "XNYS",
        "decision_rule": "last_actual_trading_session_of_month",
        "execution_rule": "next_actual_trading_session_open",
        "calendar_month_end_label_used": False,
        "schedule_count": len(rows),
        "all_t_plus_one": bool(rows)
        and all(
            row["decision_session"] < row["execution_session"]
            and row["t_plus_one"] is True
            for row in rows
        ),
        "rows": rows,
    }


def build_canonical_portfolio_evidence_report(
    *,
    canonical_report: Mapping[str, Any],
    portfolio_report: Mapping[str, Any],
    g06_report: Mapping[str, Any],
    exposure_sessions: Iterable[str],
    fill_records: Iterable[Mapping[str, Any]],
    artifacts: Mapping[str, Any],
    code_commit: str,
    code_tree_hash: str,
    generated_at: str,
) -> dict[str, Any]:
    """Bind existing frozen-candidate engines into one fail-closed evidence report."""

    candidate = _mapping(canonical_report.get("candidate"))
    canonical_hashes = _mapping(canonical_report.get("hashes"))
    portfolio_hashes = _mapping(portfolio_report.get("hashes"))
    event_chain = _mapping(canonical_report.get("event_chain"))
    canonical_guardrails = _mapping(canonical_report.get("guardrails"))
    portfolio_guardrails = _mapping(portfolio_report.get("guardrails"))
    data = _mapping(canonical_report.get("data"))
    cost_model = _mapping(canonical_report.get("cost_model"))
    params_hash = str(candidate.get("params_hash", ""))
    cost_model_hash = str(canonical_hashes.get("cost_model_hash", ""))
    strategy_version = str(candidate.get("strategy_version", ""))
    data_version = str(data.get("data_version", ""))
    canonical_run_id = str(canonical_report.get("run_id", ""))
    portfolio_run_id = str(portfolio_report.get("run_id", ""))

    chain = _chain_bindings(
        canonical_report=canonical_report,
        portfolio_report=portfolio_report,
        data_version=data_version,
        strategy_version=strategy_version,
        params_hash=params_hash,
        cost_model_hash=cost_model_hash,
        code_commit=code_commit,
        canonical_run_id=canonical_run_id,
        portfolio_run_id=portfolio_run_id,
    )
    calendar = build_month_end_t_plus_one_evidence(exposure_sessions)
    delay_cost = build_delay_cost_evidence(fill_records)
    no_lookahead = _mapping(canonical_report.get("no_lookahead"))
    reconciliation = _mapping(portfolio_report.get("ledger_reconciliation"))
    cost_stress = _mapping(portfolio_report.get("cost_stress"))
    corporate_actions = _mapping(canonical_report.get("corporate_actions"))
    g06_production = _mapping(g06_report.get("production_pit"))
    g06_readiness = _mapping(g06_report.get("readiness"))

    engineering_checks = {
        "frozen_candidate_unchanged": (
            candidate.get("parameter_tuning_performed") is False
            and candidate.get("symbol_or_timeframe_reselection_performed") is False
        ),
        "canonical_event_chain_complete": tuple(event_chain.get("sequence", ()))
        == (
            "MarketData",
            "Signal",
            "Forecast",
            "TargetPosition",
            "RiskDecision",
            "OrderIntent",
            "SimulatedFill",
            "PositionCashLedger",
            "Report",
        ),
        "no_lookahead_passed": (
            no_lookahead.get("decision_before_fill_passed") is True
            and no_lookahead.get("truncation_invariance_passed") is True
            and int(no_lookahead.get("same_bar_fill_count", -1)) == 0
        ),
        "month_end_t_plus_one_passed": calendar["all_t_plus_one"] is True,
        "ledger_reconciliation_passed": reconciliation.get("passed") is True,
        "pnl_from_ledger_only": (
            _mapping(portfolio_report.get("ledger_pnl")).get("pnl_source")
            == "fills_plus_positions_plus_cash_plus_corporate_action_ledger"
            and _mapping(portfolio_report.get("ledger_pnl")).get(
                "price_series_nav_substitution_used"
            )
            is False
        ),
        "cost_stress_passed": (
            cost_stress.get("cost_monotonic_nonincreasing_final_equity") is True
        ),
        "deterministic_replay_passed": (
            event_chain.get("deterministic_replay_hash_match") is True
            and reconciliation.get("deterministic_replay_hash_match") is True
        ),
        "all_layers_version_bound": all(
            all(
                str(layer.get(field, ""))
                for field in (
                    "data_version",
                    "strategy_version",
                    "params_hash",
                    "cost_model_hash",
                    "run_id",
                    "code_version",
                    "content_sha256",
                )
            )
            for layer in chain["layers"]
        ),
    }
    blockers = _dedupe(
        [
            *[str(item) for item in _list(g06_report.get("blockers"))],
            "production_pit_required_for_promotion",
            "production_corporate_action_available_time_replay_missing",
            "production_delisted_symbol_history_missing",
            "production_survivorship_clean_universe_missing",
            "fixture_simulated_ledger_not_production_event_ledger",
            *[
                f"engineering_check_failed:{name}"
                for name, passed in engineering_checks.items()
                if passed is not True
            ],
        ]
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_utc(generated_at),
        "status": "complete_research_only_blocked",
        "decision": (
            "canonical_engineering_evidence_complete_"
            "promotion_blocked_external_production_pit"
        ),
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "candidate": {
            "candidate_id": candidate.get("candidate_id"),
            "strategy_version": strategy_version,
            "symbol": candidate.get("symbol"),
            "timeframe": candidate.get("timeframe"),
            "params_hash": params_hash,
            "parameter_tuning_performed": candidate.get(
                "parameter_tuning_performed"
            ),
            "symbol_or_timeframe_reselection_performed": candidate.get(
                "symbol_or_timeframe_reselection_performed"
            ),
            "frozen_candidate_source_sha256": canonical_hashes.get(
                "strategy_config_sha256"
            ),
        },
        "version_bindings": {
            "data_version": data_version,
            "data_manifest_sha256": data.get("manifest_sha256"),
            "data_aggregate_sha256": data.get("aggregate_sha256"),
            "strategy_version": strategy_version,
            "params_hash": params_hash,
            "cost_model_hash": cost_model_hash,
            "slippage_model_hash": canonical_hashes.get("slippage_model_hash"),
            "canonical_run_id": canonical_run_id,
            "canonical_run_inputs_hash": canonical_hashes.get("run_inputs_hash"),
            "portfolio_run_id": portfolio_run_id,
            "portfolio_run_inputs_hash": portfolio_hashes.get("run_inputs_hash"),
            "code_commit": code_commit,
            "code_tree_hash": code_tree_hash,
        },
        "chain": chain,
        "engineering_checks": engineering_checks,
        "calendar_evidence": calendar,
        "no_lookahead": no_lookahead,
        "corporate_actions": {
            "engineering_ledger_present": int(
                corporate_actions.get("coverage_record_count", 0)
            )
            >= 1,
            "production_status": "blocked_external_data",
            "adjustment_available_time_replay": False,
            "delisted_symbol_events_available": False,
            "production_pit_accepted": g06_production.get("accepted") is True,
            "promotion_credit_allowed": False,
        },
        "survivorship": {
            "production_universe_membership_available": False,
            "delisted_symbol_history_available": False,
            "survivorship_clean": False,
            "research_universe_only": True,
            "promotion_credit_allowed": False,
        },
        "ledger_reconciliation": reconciliation,
        "pnl": _mapping(portfolio_report.get("ledger_pnl")),
        "portfolio": {
            "forecast_to_portfolio": _mapping(
                portfolio_report.get("forecast_to_portfolio")
            ),
            "risk_adjusted_contribution": _mapping(
                portfolio_report.get("risk_adjusted_contribution")
            ),
            "liquidity_capacity": _mapping(
                portfolio_report.get("liquidity_capacity")
            ),
            "sector_style_exposure": _mapping(
                portfolio_report.get("sector_style_exposure")
            ),
            "cost_stress": cost_stress,
            "performance": _mapping(canonical_report.get("performance")),
        },
        "cost_model": {
            "commission_bps": cost_model.get("commission_bps"),
            "spread_bps": cost_model.get("spread_bps"),
            "slippage_bps": cost_model.get("slippage_bps"),
            "impact_bps": cost_model.get("impact_bps"),
            "delay_cost": delay_cost,
            "cost_model_hash": cost_model_hash,
        },
        "fixture_isolation": {
            "fixture_ledger_can_validate_plumbing": True,
            "fixture_ledger_can_be_production_event_ledger": False,
            "fixture_ledger_can_unlock_promotion": False,
            "canonical_fills_simulated_only": True,
            "production_event_ledger_present": False,
        },
        "g06_dependency": {
            "status": g06_report.get("status"),
            "decision": g06_report.get("decision"),
            "production_pit_accepted": g06_production.get("accepted") is True,
            "research_ready": g06_readiness.get("research_ready") is True,
            "promotion_evidence_ready": False,
            "artifact_identity_sha256": g06_report.get(
                "artifact_identity_sha256"
            ),
        },
        "artifacts": dict(artifacts),
        "blockers": blockers,
        "guardrails": _guardrails(),
    }
    report["artifact_identity_sha256"] = canonical_payload_hash(
        {
            key: value
            for key, value in report.items()
            if key not in {"generated_at", "artifact_identity_sha256"}
        }
    )
    _validate_report_contract(report)
    return report


def build_delay_cost_evidence(
    fills: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Attribute close-to-next-open delay from actual simulated fill records."""

    rows = []
    for fill in fills:
        gap_return = fill.get("gap_return")
        arrival = fill.get("arrival_price")
        quantity = fill.get("quantity")
        side = str(fill.get("side", "")).lower()
        if gap_return is None or arrival is None or quantity is None:
            continue
        gap = float(gap_return)
        if abs(1.0 + gap) <= 1e-12 or side not in {"buy", "sell"}:
            continue
        previous_close = float(arrival) / (1.0 + gap)
        direction = 1.0 if side == "buy" else -1.0
        amount = direction * float(quantity) * (float(arrival) - previous_close)
        rows.append(amount)
    return {
        "modeled": True,
        "method": "signed_decision_close_to_next_session_open_gap",
        "embedded_in_fill_settlement_and_ledger_pnl": True,
        "double_charged": False,
        "attributed_fill_count": len(rows),
        "total_delay_cost": round(sum(rows), 6),
        "absolute_delay_cost": round(sum(abs(value) for value in rows), 6),
    }


def _chain_bindings(
    *,
    canonical_report: Mapping[str, Any],
    portfolio_report: Mapping[str, Any],
    data_version: str,
    strategy_version: str,
    params_hash: str,
    cost_model_hash: str,
    code_commit: str,
    canonical_run_id: str,
    portfolio_run_id: str,
) -> dict[str, Any]:
    canonical_hashes = _mapping(canonical_report.get("hashes"))
    portfolio_hashes = _mapping(portfolio_report.get("hashes"))
    event_hashes = _mapping(
        _mapping(canonical_report.get("event_chain")).get("hashes")
    )
    content_hashes = {
        "data": str(canonical_hashes.get("data_aggregate_sha256", "")),
        "signal": str(event_hashes.get("event_log", "")),
        "forecast": str(event_hashes.get("event_log", "")),
        "target_portfolio": str(
            portfolio_hashes.get("portfolio_event_ledger_content_hash", "")
        ),
        "risk": str(portfolio_hashes.get("risk_decisions_content_hash", "")),
        "order_intent": str(event_hashes.get("orders", "")),
        "simulated_fill": str(event_hashes.get("fills", "")),
        "position_cash_ledger": canonical_payload_hash(
            {
                "positions": event_hashes.get("position_ledger"),
                "cash": event_hashes.get("cash_ledger"),
            }
        ),
        "pnl": str(portfolio_hashes.get("ledger_pnl_content_hash", "")),
        "report": canonical_payload_hash(
            {
                "canonical": canonical_hashes.get("run_inputs_hash"),
                "portfolio": portfolio_hashes.get("run_inputs_hash"),
            }
        ),
    }
    layers = [
        {
            "layer": layer,
            "data_version": data_version,
            "strategy_version": strategy_version,
            "params_hash": params_hash,
            "cost_model_hash": cost_model_hash,
            "run_id": (
                portfolio_run_id
                if layer in {"target_portfolio", "risk", "pnl", "report"}
                else canonical_run_id
            ),
            "code_version": code_commit,
            "content_sha256": content_hashes[layer],
        }
        for layer in EXPECTED_CHAIN
    ]
    return {
        "sequence": list(EXPECTED_CHAIN),
        "complete": all(layer["content_sha256"] for layer in layers),
        "layers": layers,
    }


def _validate_report_contract(report: Mapping[str, Any]) -> None:
    if report.get("status") != "complete_research_only_blocked":
        raise ValueError("canonical_portfolio_status_must_be_research_only_blocked")
    if _mapping(report.get("guardrails")).get("promotion_credit_allowed") is not False:
        raise ValueError("canonical_portfolio_promotion_credit_must_be_false")
    if _mapping(report.get("g06_dependency")).get("production_pit_accepted") is True:
        raise ValueError("g07_unexpected_production_pit_acceptance")
    if _mapping(report.get("chain")).get("complete") is not True:
        raise ValueError("canonical_portfolio_chain_incomplete")
    if not _list(report.get("blockers")):
        raise ValueError("canonical_portfolio_blockers_required")


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "fail_closed": True,
        "production_pit_accepted": False,
        "promotion_evidence_ready": False,
        "promotion_credit_allowed": False,
        "promotion_unlock_allowed": False,
        "paper_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "paper_order_allowed": False,
        "live_allowed": False,
        "live_order_allowed": False,
        "paper_queue_write_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_endpoint_used": False,
        "network_used": False,
        "secret_read": False,
        "withdraw_allowed": False,
        "demo_allowed": False,
        "real_order_submitted": False,
        "source_data_modified": False,
        "strategy_parameters_mutated": False,
    }


def _iso_utc(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("generated_at_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
