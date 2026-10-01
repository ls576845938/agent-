"""Candidate-specific local OMS/execution evidence for the frozen ETF26 strategy.

The service is deliberately local-only.  It consumes immutable Goal 4 evidence,
uses deterministic fixture orders and the existing paper-ledger UoW, and never
touches a broker, paper queue, private endpoint, or live/order endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from quant_us.live.paper_ledger_uow import PaperLedgerCommitError, commit_paper_ledger_cycle


SCHEMA_VERSION = "us_etf_26_candidate_execution_envelope_report_v1"
MANIFEST_SCHEMA_VERSION = "us_etf_26_candidate_execution_envelope_manifest_v1"
ARTIFACT_FILES = (
    "execution_drill.json",
    "order_lifecycle.jsonl",
    "orders.jsonl",
    "fills.jsonl",
    "position_ledger.jsonl",
    "cash_ledger.jsonl",
    "reconciliation.json",
    "execution_quality.json",
    "paper_ledger_uow.json",
    "broker_credential_metadata_contract.json",
    "paper_simulation_readiness_envelope.json",
    "report.json",
    "report.md",
)
FALSE_GUARDRAILS = (
    "promotion_credit_allowed",
    "promotion_unlock_allowed",
    "paper_or_live_unlock_allowed",
    "paper_order_allowed",
    "paper_runner_allowed",
    "paper_queue_write_allowed",
    "broker_access_allowed",
    "live_order_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "paper_endpoint_used",
    "live_endpoint_used",
    "broker_endpoint_used",
    "network_used",
    "secret_read",
    "real_order_submitted",
)


@dataclass(frozen=True)
class CandidateExecutionEnvelopeResult:
    run_id: str
    run_dir: Path
    latest_pointer: Path
    report: dict[str, Any]
    manifest: dict[str, Any]
    manifest_sha256: str


_ALLOWED_LOCAL_TRANSITIONS = {
    None: {"created"},
    "created": {"risk_approved", "risk_rejected"},
    "risk_approved": {"submitted_local"},
    "submitted_local": {"accepted_local", "submit_timeout"},
    "accepted_local": {"filled", "partially_filled"},
    "partially_filled": {"cancel_requested"},
    "cancel_requested": {"cancelled"},
    "submit_timeout": {"recovered_accepted"},
    "recovered_accepted": {"filled"},
    "filled": {"reconciled"},
    "cancelled": {"reconciled"},
    "risk_rejected": {"reconciled"},
    "reconciled": set(),
}


@dataclass
class _LocalFixtureOms:
    """In-memory OMS used only to produce behavior evidence without endpoints."""

    order_states: dict[str, str] = field(default_factory=dict)
    order_history: dict[str, list[str]] = field(default_factory=dict)
    client_order_ids: dict[str, str] = field(default_factory=dict)
    fill_ids: set[str] = field(default_factory=set)
    accepted_fill_quantity: float = 0.0
    kill_switch: bool = False
    cancel_only: bool = False
    reduce_only: bool = False
    no_new_risk: bool = False
    data_fresh: bool = True
    broker_available: bool = True

    def transition(self, order_id: str, state: str) -> bool:
        current = self.order_states.get(order_id)
        if state not in _ALLOWED_LOCAL_TRANSITIONS.get(current, set()):
            return False
        self.order_states[order_id] = state
        self.order_history.setdefault(order_id, []).append(state)
        return True

    def register_submit(self, client_order_id: str, order_id: str) -> str:
        if client_order_id in self.client_order_ids:
            return "duplicate_existing"
        if self.kill_switch or self.cancel_only or self.no_new_risk or not self.data_fresh:
            return "blocked_no_new_risk"
        self.client_order_ids[client_order_id] = order_id
        if not self.broker_available:
            return "timeout_unknown_persisted"
        return "accepted_local"

    def accept_fill(self, fill_id: str, quantity: float) -> str:
        if fill_id in self.fill_ids:
            return "duplicate_ignored"
        self.fill_ids.add(fill_id)
        self.accepted_fill_quantity += quantity
        return "accepted"

    def cancel(self, client_order_id: str) -> str:
        return "cancelled_local" if client_order_id in self.client_order_ids else "unknown_order"

    def authorize_position_change(self, *, current: float, delta: float) -> str:
        if self.kill_switch or self.cancel_only or self.no_new_risk or not self.data_fresh:
            return "blocked_no_new_risk"
        if not self.reduce_only:
            return "allowed"
        resulting = current + delta
        if abs(resulting) <= abs(current) and current * resulting >= 0:
            return "allowed_reduce_only"
        return "blocked_reduce_only"

    def snapshot(self) -> dict[str, Any]:
        return {
            "order_states": dict(self.order_states),
            "order_history": {key: list(value) for key, value in self.order_history.items()},
            "client_order_ids": dict(self.client_order_ids),
            "fill_ids": sorted(self.fill_ids),
            "accepted_fill_quantity": self.accepted_fill_quantity,
        }

    @classmethod
    def restore(cls, snapshot: Mapping[str, Any]) -> "_LocalFixtureOms":
        instance = cls()
        instance.order_states = {str(key): str(value) for key, value in dict(snapshot["order_states"]).items()}
        instance.order_history = {
            str(key): [str(item) for item in value]
            for key, value in dict(snapshot["order_history"]).items()
        }
        instance.client_order_ids = {
            str(key): str(value) for key, value in dict(snapshot["client_order_ids"]).items()
        }
        instance.fill_ids = {str(value) for value in snapshot["fill_ids"]}
        instance.accepted_fill_quantity = float(snapshot["accepted_fill_quantity"])
        return instance


def build_candidate_execution_envelope(
    *,
    repo_root: Path,
    config_path: Path,
    code_commit: str,
    code_tree_hash: str,
    generated_at: str,
    artifact_root_override: Path | None = None,
) -> CandidateExecutionEnvelopeResult:
    root = repo_root.resolve()
    config_abs = _resolve(root, config_path)
    config = _read_json(config_abs)
    dependency = _load_portfolio_dependency(root, config, expected_code_commit=code_commit)
    evidence = analyze_candidate_execution_envelope(
        config=config,
        portfolio_pointer=dependency["pointer"],
        portfolio_report=dependency["report"],
        code_commit=code_commit,
        code_tree_hash=code_tree_hash,
        generated_at=generated_at,
        config_sha256=_sha256_file(config_abs),
        portfolio_pointer_sha256=dependency["pointer_sha256"],
    )
    artifact_root = (
        artifact_root_override.resolve()
        if artifact_root_override is not None
        else _resolve(root, Path(str(config["artifact_root"])))
    )
    return _write_immutable_run(root=root, artifact_root=artifact_root, evidence=evidence)


def analyze_candidate_execution_envelope(
    *,
    config: Mapping[str, Any],
    portfolio_pointer: Mapping[str, Any],
    portfolio_report: Mapping[str, Any],
    code_commit: str,
    code_tree_hash: str,
    generated_at: str,
    config_sha256: str,
    portfolio_pointer_sha256: str,
) -> dict[str, Any]:
    candidate_id = str(config["candidate_id"])
    strategy_id = str(config["strategy_id"])
    initial_cash = float(config["initial_cash"])
    orders = _fixture_orders(candidate_id, strategy_id)
    fills = _fixture_fills(orders)
    lifecycle = _lifecycle_events(orders, fills, candidate_id, strategy_id)
    positions, cash = _derive_ledgers(fills, initial_cash)
    reconciliation = _reconcile(orders, fills, positions, cash, initial_cash, lifecycle)
    quality = _execution_quality(orders, fills)
    uow = _run_paper_uow_drill(generated_at)
    behavior = _run_local_fake_oms_behavior_drill(
        orders=orders,
        fills=fills,
        lifecycle=lifecycle,
        reconciliation=reconciliation,
        uow=uow,
        config=config,
    )
    scenarios = behavior["scenarios"]
    engineering_passed = all(row["status"] == "pass_local_fixture" for row in scenarios)

    credential_contract = {
        "schema_version": "us_equity_broker_credential_metadata_contract_v1",
        "status": "blocked_missing_human_review",
        "allowed_metadata_fields": [
            "broker_name",
            "account_hash",
            "reviewer",
            "review_time",
            "approval_ticket",
            "funding_source_external_confirmation",
            "permission_conclusion",
        ],
        "metadata": {
            "broker_name": None,
            "account_hash": None,
            "reviewer": None,
            "review_time": None,
            "approval_ticket": None,
            "funding_source_external_confirmation": None,
            "permission_conclusion": None,
        },
        "human_review_proven": False,
        "sample_metadata_treated_as_proven": False,
        "secret_value_present": False,
        "secret_path_present": False,
        "can_unlock_paper_or_live": False,
        "blockers": ["manual_broker_credential_review_missing"],
    }
    blockers = _dedupe(
        [
            "manual_broker_credential_review_missing",
            "manual_paper_approval_ticket_missing",
            "production_pit_intake_blocked_external_data",
            "independent_confirmation_window_not_complete:0_of_252",
            "portfolio_promotion_evidence_blocked",
            "broker_state_reconciliation_unproven",
            "paper_state_reconciliation_blocked_unproven",
            "production_market_calendar_coverage_not_proven",
            "paper_runner_disabled",
            "paper_queue_write_disabled",
            "broker_access_disabled",
            "order_submission_disabled",
        ]
        + [
            str(item)
            for item in portfolio_report.get("blockers", [])
            if str(item).startswith("production_pit_bundle_missing:")
        ]
    )
    readiness = {
        "status": "paper_simulation_blocked_fail_closed",
        "engineering_execution_drill_passed": engineering_passed,
        "local_simulator_only": True,
        "fixture_only": True,
        "fixture_can_prove_plumbing_only": True,
        "paper_runner_status": "blocked",
        "paper_queue_status": "blocked",
        "broker_access_status": "blocked",
        "order_submission_status": "blocked",
        "promotion_credit_allowed": False,
        "paper_order_allowed": False,
        "blockers": blockers,
    }
    run_inputs = {
        "candidate_id": candidate_id,
        "portfolio_run_id": portfolio_pointer["run_id"],
        "portfolio_manifest_sha256": portfolio_pointer["manifest_sha256"],
        "portfolio_report_sha256": portfolio_pointer["report_sha256"],
        "portfolio_pointer_sha256": portfolio_pointer_sha256,
        "config_sha256": config_sha256,
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
    }
    run_id = f"us-etf26-execution-{_stable_hash(run_inputs)[:16]}"
    guardrails = {name: False for name in FALSE_GUARDRAILS}
    guardrails.update(
        {
            "research_only": True,
            "fail_closed": True,
            "fixture_only": True,
            "local_simulator_used": True,
            "old_latest_artifact_consumed": False,
            "source_portfolio_artifact_modified": False,
        }
    )
    common = {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "candidate_id": candidate_id,
        "data_version": portfolio_report["data"]["data_version"],
    }
    for rows in (orders, fills, lifecycle, positions, cash):
        for row in rows:
            row.update({key: value for key, value in common.items() if key not in row})
    drill = {
        "status": "engineering_execution_drill_pass" if engineering_passed else "engineering_execution_drill_blocked",
        "scenario_count": len(scenarios),
        "passed_count": sum(row["status"] == "pass_local_fixture" for row in scenarios),
        "blocked_count": sum(row["status"] != "pass_local_fixture" for row in scenarios),
        "scenarios": scenarios,
        "append_only_lifecycle": behavior["append_only_lifecycle"],
        "deterministic_client_order_ids": behavior["deterministic_client_order_ids"],
        "fill_idempotency": behavior["fill_idempotency"],
        "behavior_source": "local_fixture_oms_observed_state_transitions",
        "local_fixture_state_hash": behavior["local_fixture_state_hash"],
        "broker_calls_used": False,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "status": "engineering_execution_complete_paper_blocked",
        "decision": "local_execution_plumbing_pass_paper_fail_closed",
        "code_commit": code_commit,
        "code_tree_hash": code_tree_hash,
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "portfolio_dependency": {
            "run_id": portfolio_pointer["run_id"],
            "code_commit": portfolio_pointer["code_commit"],
            "manifest_sha256": portfolio_pointer["manifest_sha256"],
            "report_sha256": portfolio_pointer["report_sha256"],
            "pointer_sha256": portfolio_pointer_sha256,
            "status": portfolio_pointer["status"],
            "promotion_credit_allowed": False,
        },
        "execution_drill": drill,
        "reconciliation": reconciliation,
        "execution_quality": quality,
        "paper_ledger_uow": uow,
        "broker_credential_metadata_contract": credential_contract,
        "paper_simulation_readiness": readiness,
        "counts": {
            "scenario_count": len(scenarios),
            "order_count": len(orders),
            "fill_count": len(fills),
            "lifecycle_event_count": len(lifecycle),
            "position_ledger_count": len(positions),
            "cash_ledger_count": len(cash),
        },
        "hashes": {
            "run_inputs_hash": _stable_hash(run_inputs),
            "orders_hash": _stable_hash(orders),
            "fills_hash": _stable_hash(fills),
            "lifecycle_hash": _stable_hash(lifecycle),
            "position_ledger_hash": _stable_hash(positions),
            "cash_ledger_hash": _stable_hash(cash),
            "scenario_matrix_hash": _stable_hash(scenarios),
        },
        "blockers": blockers,
        "guardrails": guardrails,
        "artifacts": list(ARTIFACT_FILES),
    }
    return {
        "run_id": run_id,
        "report": report,
        "execution_drill": drill,
        "orders": orders,
        "fills": fills,
        "lifecycle": lifecycle,
        "positions": positions,
        "cash": cash,
        "reconciliation": reconciliation,
        "execution_quality": quality,
        "paper_ledger_uow": uow,
        "credential_contract": credential_contract,
        "readiness": readiness,
    }


def _fixture_orders(candidate_id: str, strategy_id: str) -> list[dict[str, Any]]:
    specs = [
        ("2026-07-06T13:30:00Z", "BUY", 10.0, 99.95, 100.00, "filled", None),
        ("2026-07-07T13:30:00Z", "BUY", 10.0, 101.00, 101.10, "partially_filled_then_cancelled", None),
        ("2026-07-08T13:30:00Z", "BUY", 5.0, 102.00, 102.05, "rejected", "fixture_risk_reject"),
        ("2026-07-09T13:30:00Z", "BUY", 2.0, 99.90, 100.00, "filled_after_timeout_recovery", "submit_timeout_recovered"),
    ]
    rows: list[dict[str, Any]] = []
    for index, (decision_time, side, quantity, decision_price, arrival_mid, status, error_code) in enumerate(specs, 1):
        client_id = _deterministic_id("coid", candidate_id, decision_time, str(index))
        rows.append(
            {
                "order_id": f"ord-{index:03d}-{client_id[-8:]}",
                "client_order_id": client_id,
                "decision_time": decision_time,
                "signal": {"direction": "long", "strength": 1.0},
                "forecast": {"value": 1.0, "unit": "binary_long_state"},
                "target_position": {"symbol": "QQQ", "target_direction": "increase_long"},
                "risk_decision": {"approved_for_fixture_execution": status != "rejected", "mode": "local_fixture_only"},
                "symbol": "QQQ",
                "side": side,
                "quantity": quantity,
                "decision_price": decision_price,
                "arrival_mid": arrival_mid,
                "status": status,
                "error_code": error_code,
                "broker_submit_attempted": False,
                "strategy_id": strategy_id,
            }
        )
    return rows


def _fixture_fills(orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    specs = [(0, 10.0, 100.05, 0.10), (1, 4.0, 101.12, 0.05), (3, 2.0, 99.99, 0.02)]
    rows: list[dict[str, Any]] = []
    for index, (order_index, quantity, price, commission) in enumerate(specs, 1):
        order = orders[order_index]
        rows.append(
            {
                "fill_id": _deterministic_id("fill", str(order["client_order_id"]), str(index)),
                "order_id": order["order_id"],
                "client_order_id": order["client_order_id"],
                "decision_time": order["decision_time"],
                "fill_time": str(order["decision_time"]).replace("13:30:00", "13:30:05"),
                "symbol": "QQQ",
                "side": "BUY",
                "quantity": quantity,
                "price": price,
                "commission": commission,
                "error_code": order["error_code"],
                "duplicate_callback_ignored": index == 1,
            }
        )
    return rows


def _lifecycle_events(
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    candidate_id: str,
    strategy_id: str,
) -> list[dict[str, Any]]:
    fill_by_order = {str(row["order_id"]): row for row in fills}
    transitions = {
        "filled": ["created", "risk_approved", "submitted_local", "accepted_local", "filled", "reconciled"],
        "partially_filled_then_cancelled": ["created", "risk_approved", "submitted_local", "accepted_local", "partially_filled", "cancel_requested", "cancelled", "reconciled"],
        "rejected": ["created", "risk_rejected", "reconciled"],
        "filled_after_timeout_recovery": ["created", "risk_approved", "submitted_local", "submit_timeout", "recovered_accepted", "filled", "reconciled"],
    }
    rows: list[dict[str, Any]] = []
    sequence = 0
    for order in orders:
        for state in transitions[str(order["status"])]:
            sequence += 1
            fill = fill_by_order.get(str(order["order_id"])) if state in {"filled", "partially_filled", "reconciled"} else None
            rows.append(
                {
                    "event_id": _deterministic_id("evt", str(order["client_order_id"]), str(sequence), state),
                    "sequence": sequence,
                    "event_type": state,
                    "decision_time": order["decision_time"],
                    "signal": order["signal"],
                    "forecast": order["forecast"],
                    "target_position": order["target_position"],
                    "risk_decision": order["risk_decision"],
                    "order_id": order["order_id"],
                    "client_order_id": order["client_order_id"],
                    "fill_id": None if fill is None else fill["fill_id"],
                    "error_code": order["error_code"],
                    "candidate_id": candidate_id,
                    "strategy_id": strategy_id,
                }
            )
    return rows


def _derive_ledgers(
    fills: Sequence[Mapping[str, Any]], initial_cash: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quantity = 0.0
    cash_value = initial_cash
    positions: list[dict[str, Any]] = []
    cash = [{"sequence": 0, "entry_type": "opening_balance", "amount": initial_cash, "balance": initial_cash, "fill_id": None}]
    for sequence, fill in enumerate(fills, 1):
        quantity += float(fill["quantity"])
        cash_delta = -(float(fill["quantity"]) * float(fill["price"]) + float(fill["commission"]))
        cash_value += cash_delta
        positions.append(
            {
                "sequence": sequence,
                "symbol": fill["symbol"],
                "quantity": round(quantity, 8),
                "fill_id": fill["fill_id"],
                "decision_time": fill["decision_time"],
                "error_code": fill["error_code"],
            }
        )
        cash.append(
            {
                "sequence": sequence,
                "entry_type": "fill_and_commission",
                "amount": round(cash_delta, 8),
                "balance": round(cash_value, 8),
                "fill_id": fill["fill_id"],
                "decision_time": fill["decision_time"],
                "error_code": fill["error_code"],
            }
        )
    return positions, cash


def _reconcile(
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
    cash: Sequence[Mapping[str, Any]],
    initial_cash: float,
    lifecycle: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    fill_ids = [str(row["fill_id"]) for row in fills]
    expected_qty = sum(float(row["quantity"]) for row in fills)
    expected_cash = initial_cash - sum(
        float(row["quantity"]) * float(row["price"]) + float(row["commission"]) for row in fills
    )
    order_fills: dict[str, float] = {}
    for fill in fills:
        order_fills[str(fill["order_id"])] = order_fills.get(str(fill["order_id"]), 0.0) + float(fill["quantity"])
    order_qty_delta = 0.0
    expected_by_status = {"filled": 10.0, "partially_filled_then_cancelled": 4.0, "rejected": 0.0, "filled_after_timeout_recovery": 2.0}
    for order in orders:
        order_qty_delta += order_fills.get(str(order["order_id"]), 0.0) - expected_by_status[str(order["status"])]
    position_delta = (float(positions[-1]["quantity"]) if positions else 0.0) - expected_qty
    cash_delta = float(cash[-1]["balance"]) - expected_cash
    position_chain_max_delta = 0.0
    running_quantity = 0.0
    for fill, position in zip(fills, positions):
        running_quantity += float(fill["quantity"])
        position_chain_max_delta = max(
            position_chain_max_delta,
            abs(float(position["quantity"]) - running_quantity),
        )
    cash_chain_max_delta = 0.0
    running_cash = initial_cash
    for fill, entry in zip(fills, cash[1:]):
        running_cash -= float(fill["quantity"]) * float(fill["price"]) + float(fill["commission"])
        cash_chain_max_delta = max(
            cash_chain_max_delta,
            abs(float(entry["balance"]) - running_cash),
        )
    position_fill_ids = {str(row.get("fill_id")) for row in positions if row.get("fill_id")}
    cash_fill_ids = {str(row.get("fill_id")) for row in cash if row.get("fill_id")}
    orphan_fill_count = sum(
        str(row["order_id"]) not in {str(item["order_id"]) for item in orders}
        for row in fills
    )
    missing_position_fill_count = sum(fill_id not in position_fill_ids for fill_id in fill_ids)
    missing_cash_fill_count = sum(fill_id not in cash_fill_ids for fill_id in fill_ids)
    replayed = [dict(row) for row in sorted(lifecycle, key=lambda item: int(item["sequence"]))]
    replay_hash_match = _stable_hash(list(lifecycle)) == _stable_hash(replayed)
    passed = (
        len(fill_ids) == len(set(fill_ids))
        and abs(order_qty_delta) <= 1e-8
        and abs(position_delta) <= 1e-8
        and abs(cash_delta) <= 1e-8
        and position_chain_max_delta <= 1e-8
        and cash_chain_max_delta <= 1e-8
        and len(positions) == len(fills)
        and len(cash) == len(fills) + 1
        and orphan_fill_count == 0
        and missing_position_fill_count == 0
        and missing_cash_fill_count == 0
        and replay_hash_match
    )
    return {
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "order_fill_quantity_delta": round(order_qty_delta, 8),
        "fill_position_quantity_delta": round(position_delta, 8),
        "fill_cash_balance_delta": round(cash_delta, 8),
        "duplicate_fill_id_count": len(fill_ids) - len(set(fill_ids)),
        "orphan_fill_count": orphan_fill_count,
        "position_chain_max_delta": round(position_chain_max_delta, 8),
        "cash_chain_max_delta": round(cash_chain_max_delta, 8),
        "missing_position_fill_count": missing_position_fill_count,
        "missing_cash_fill_count": missing_cash_fill_count,
        "deterministic_replay_hash_match": replay_hash_match,
        "local_fixture_state_reconciliation": "passed" if passed else "failed",
        "local_fixture_state_reconciliation_passed": passed,
        "broker_state_reconciliation": "unproven",
        "paper_state_reconciliation": "blocked_unproven",
        "final_position_quantity": round(expected_qty, 8),
        "final_cash": round(expected_cash, 8),
    }


def _execution_quality(
    orders: Sequence[Mapping[str, Any]], fills: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    order_by_id = {str(row["order_id"]): row for row in orders}
    requested_qty = sum(float(row["quantity"]) for row in orders)
    filled_qty = sum(float(row["quantity"]) for row in fills)
    shortfall = 0.0
    spread_numerator = 0.0
    for fill in fills:
        order = order_by_id[str(fill["order_id"])]
        qty = float(fill["quantity"])
        price = float(fill["price"])
        shortfall += (price - float(order["decision_price"])) * qty + float(fill["commission"])
        spread_numerator += (2.0 * (price - float(order["arrival_mid"])) / float(order["arrival_mid"]) * 10_000.0) * qty
    return {
        "status": "pass_local_fixture",
        "requested_quantity": requested_qty,
        "filled_quantity": filled_qty,
        "fill_rate": round(filled_qty / requested_qty, 8),
        "implementation_shortfall_usd": round(shortfall, 8),
        "implementation_shortfall_bps_of_filled_notional": round(shortfall / sum(float(row["quantity"]) * float(row["price"]) for row in fills) * 10_000.0, 8),
        "quantity_weighted_effective_spread_bps": round(spread_numerator / filled_qty, 8),
        "commission_usd": round(sum(float(row["commission"]) for row in fills), 8),
        "partial_fill_count": 1,
        "reject_count": 1,
        "cancel_count": 1,
        "timeout_recovery_count": 1,
        "promotion_credit_allowed": False,
    }


def _run_paper_uow_drill(generated_at: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="us-etf26-paper-uow-") as temp:
        root = Path(temp)
        success_root = root / "success"
        success = commit_paper_ledger_cycle(
            ledger_root=success_root,
            timestamp="2026-07-09",
            generated_at=generated_at,
            jsonl_rows={
                "orders.jsonl": [{"id": "order-1"}],
                "fills.jsonl": [{"id": "fill-1"}],
                "positions.jsonl": [{"id": "position-1"}],
                "cash_ledger.jsonl": [{"id": "cash-1"}],
                "audit.jsonl": [{"id": "audit-1"}],
            },
            json_documents={"validation_state.json": {"status": "local_fixture"}, "reconciliation.json": {"passed": True}},
        )
        rollback_root = root / "rollback"
        rollback_root.mkdir(parents=True)
        original = b'{"id":"original"}\n'
        (rollback_root / "orders.jsonl").write_bytes(original)
        replace_count = 0

        def fail_second_replace(source: object, destination: object) -> None:
            nonlocal replace_count
            replace_count += 1
            if replace_count == 2:
                raise OSError("fixture_interruption")
            os.replace(source, destination)

        rollback_succeeded = False
        rollback_status = "not_exercised"
        try:
            commit_paper_ledger_cycle(
                ledger_root=rollback_root,
                timestamp="2026-07-09",
                generated_at=generated_at,
                jsonl_rows={"orders.jsonl": [{"id": "new"}], "fills.jsonl": [{"id": "fill"}]},
                json_documents={"reconciliation.json": {"passed": True}},
                apply_replace=fail_second_replace,
            )
        except PaperLedgerCommitError as exc:
            rollback_succeeded = exc.rollback_succeeded
            rollback_status = "ROLLED_BACK" if exc.rollback_succeeded else "ROLLBACK_FAILED"
        original_restored = (rollback_root / "orders.jsonl").read_bytes() == original
        return {
            "status": "pass" if success["status"] == "COMMITTED" and rollback_succeeded and original_restored else "blocked",
            "commit_status": success["status"],
            "commit_operation_count": success["operation_count"],
            "recovery_status_before_commit": success["recovery_status_before_commit"],
            "forced_atomic_failure_exercised": True,
            "rollback_status": rollback_status,
            "rollback_succeeded": rollback_succeeded,
            "original_state_restored": original_restored,
            "temporary_fixture_removed_after_drill": True,
            "broker_calls_used": False,
        }


def _run_local_fake_oms_behavior_drill(
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    lifecycle: Sequence[Mapping[str, Any]],
    reconciliation: Mapping[str, Any],
    uow: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    replay = _LocalFixtureOms()
    transition_results = [
        replay.transition(str(row["order_id"]), str(row["event_type"])) for row in lifecycle
    ]
    transitions_valid = all(transition_results)
    sequences = [int(row["sequence"]) for row in lifecycle]
    event_ids = [str(row["event_id"]) for row in lifecycle]
    append_only_observed = (
        transitions_valid
        and sequences == list(range(1, len(sequences) + 1))
        and len(event_ids) == len(set(event_ids))
    )
    history = replay.order_history
    order_by_status = {str(row["status"]): row for row in orders}
    partial_order = order_by_status["partially_filled_then_cancelled"]
    rejected_order = order_by_status["rejected"]
    timeout_order = order_by_status["filled_after_timeout_recovery"]
    partial_history = history.get(str(partial_order["order_id"]), [])
    rejected_history = history.get(str(rejected_order["order_id"]), [])
    timeout_history = history.get(str(timeout_order["order_id"]), [])

    idempotency = _LocalFixtureOms()
    first_fill_results = [idempotency.accept_fill(str(row["fill_id"]), float(row["quantity"])) for row in fills]
    quantity_before_duplicate = idempotency.accepted_fill_quantity
    duplicate_fill_result = idempotency.accept_fill(str(fills[0]["fill_id"]), float(fills[0]["quantity"]))
    duplicate_fill_observed = (
        all(result == "accepted" for result in first_fill_results)
        and duplicate_fill_result == "duplicate_ignored"
        and idempotency.accepted_fill_quantity == quantity_before_duplicate
    )

    duplicate_submit_oms = _LocalFixtureOms()
    duplicate_order = orders[0]
    first_submit = duplicate_submit_oms.register_submit(
        str(duplicate_order["client_order_id"]), str(duplicate_order["order_id"])
    )
    second_submit = duplicate_submit_oms.register_submit(
        str(duplicate_order["client_order_id"]), "should-not-replace"
    )
    duplicate_submit_observed = (
        first_submit == "accepted_local"
        and second_submit == "duplicate_existing"
        and len(duplicate_submit_oms.client_order_ids) == 1
    )
    restart_snapshot = duplicate_submit_oms.snapshot()
    restarted = _LocalFixtureOms.restore(restart_snapshot)
    restart_duplicate = restarted.register_submit(
        str(duplicate_order["client_order_id"]), "should-not-submit-after-restart"
    )
    restart_observed = restart_duplicate == "duplicate_existing" and restarted.snapshot() == restart_snapshot

    outage = _LocalFixtureOms(broker_available=False)
    outage_client_id = "coid-outage"
    outage_first = outage.register_submit(outage_client_id, "order-outage")
    outage.broker_available = True
    outage_retry = outage.register_submit(outage_client_id, "order-outage-retry")
    outage_observed = outage_first == "timeout_unknown_persisted" and outage_retry == "duplicate_existing"

    kill = _LocalFixtureOms(kill_switch=True)
    kill_result = kill.authorize_position_change(current=10.0, delta=1.0)
    cancel_only = _LocalFixtureOms(cancel_only=True, client_order_ids={"existing": "order-existing"})
    cancel_only_submit = cancel_only.register_submit("new", "order-new")
    cancel_only_cancel = cancel_only.cancel("existing")
    reduce_only = _LocalFixtureOms(reduce_only=True)
    reduce_allowed = reduce_only.authorize_position_change(current=10.0, delta=-4.0)
    reduce_increase = reduce_only.authorize_position_change(current=10.0, delta=1.0)
    reduce_reversal = reduce_only.authorize_position_change(current=10.0, delta=-11.0)
    no_new = _LocalFixtureOms(no_new_risk=True)
    no_new_result = no_new.authorize_position_change(current=10.0, delta=1.0)
    stale = _LocalFixtureOms(data_fresh=False)
    stale_result = stale.authorize_position_change(current=10.0, delta=1.0)

    regular_open = _fixture_market_open("2026-07-06T13:30:00Z", config)
    early_close_open = _fixture_market_open("2026-07-03T16:59:00Z", config)
    early_close_closed = not _fixture_market_open("2026-07-03T17:01:00Z", config)
    weekend_closed = not _fixture_market_open("2026-07-04T14:00:00Z", config)
    deterministic_ids = [row["client_order_id"] for row in orders] == [
        row["client_order_id"] for row in _fixture_orders(str(orders[0].get("candidate_id", "us-etf26-complete-return-qqq-1d-v1")), str(orders[0]["strategy_id"]))
    ]
    checks = [
        ("append_only_order_lifecycle", append_only_observed, {"transition_count": len(lifecycle), "sequences_contiguous": sequences == list(range(1, len(sequences) + 1)), "event_ids_unique": len(event_ids) == len(set(event_ids))}),
        ("deterministic_client_order_id", deterministic_ids, {"order_count": len(orders), "recomputed_ids_match": deterministic_ids}),
        ("fill_idempotency", duplicate_fill_observed and reconciliation["duplicate_fill_id_count"] == 0, {"first_accept_count": len(first_fill_results), "duplicate_result": duplicate_fill_result, "quantity_unchanged": idempotency.accepted_fill_quantity == quantity_before_duplicate}),
        ("partial_fill", "partially_filled" in partial_history and "cancelled" in partial_history, {"observed_history": partial_history}),
        ("reject", "risk_rejected" in rejected_history and str(rejected_order["order_id"]) not in {str(row["order_id"]) for row in fills}, {"observed_history": rejected_history, "fill_created": False}),
        ("cancel", partial_history[-2:] == ["cancelled", "reconciled"], {"observed_history": partial_history}),
        ("timeout_unknown_outcome", "submit_timeout" in timeout_history and "recovered_accepted" in timeout_history, {"observed_history": timeout_history}),
        ("duplicate_callback", duplicate_fill_observed, {"duplicate_result": duplicate_fill_result, "accepted_fill_quantity": idempotency.accepted_fill_quantity}),
        ("duplicate_submit", duplicate_submit_observed, {"first_result": first_submit, "second_result": second_submit, "stored_order_count": len(duplicate_submit_oms.client_order_ids)}),
        ("restart_recovery", restart_observed, {"post_restart_submit_result": restart_duplicate, "state_hash_match": restarted.snapshot() == restart_snapshot}),
        ("local_fixture_state_reconciliation", reconciliation["local_fixture_state_reconciliation_passed"], {"order_fill_quantity_delta": reconciliation["order_fill_quantity_delta"], "fill_position_quantity_delta": reconciliation["fill_position_quantity_delta"], "fill_cash_balance_delta": reconciliation["fill_cash_balance_delta"]}),
        ("market_calendar_session_boundary", regular_open and early_close_open and early_close_closed and weekend_closed, {"regular_open": regular_open, "early_close_open": early_close_open, "early_close_closed": early_close_closed, "weekend_closed": weekend_closed}),
        ("market_closed", weekend_closed, {"weekend_order_accepted": not weekend_closed}),
        ("stale_data", stale_result == "blocked_no_new_risk", {"authorization_result": stale_result}),
        ("broker_outage", outage_observed, {"first_submit_result": outage_first, "retry_result": outage_retry, "stored_order_count": len(outage.client_order_ids)}),
        ("kill_switch", kill_result == "blocked_no_new_risk", {"authorization_result": kill_result}),
        ("cancel_only", cancel_only_submit == "blocked_no_new_risk" and cancel_only_cancel == "cancelled_local", {"submit_result": cancel_only_submit, "cancel_result": cancel_only_cancel}),
        ("reduce_only", reduce_allowed == "allowed_reduce_only" and reduce_increase == "blocked_reduce_only" and reduce_reversal == "blocked_reduce_only", {"reduce_result": reduce_allowed, "increase_result": reduce_increase, "reversal_result": reduce_reversal}),
        ("no_new_risk", no_new_result == "blocked_no_new_risk", {"authorization_result": no_new_result}),
        ("paper_ledger_uow_atomic_rollback", uow["status"] == "pass" and uow["rollback_succeeded"] is True and uow["original_state_restored"] is True, {"commit_status": uow["commit_status"], "rollback_status": uow["rollback_status"], "original_state_restored": uow["original_state_restored"]}),
    ]
    scenarios = [
        {
            "scenario_id": scenario_id,
            "status": "pass_local_fixture" if passed else "blocked",
            "observations": observations,
            "behavior_assertion_passed": passed,
            "fixture_only": True,
            "broker_submit_attempted": False,
            "private_or_order_endpoint_used": False,
        }
        for scenario_id, passed, observations in checks
    ]
    return {
        "scenarios": scenarios,
        "deterministic_client_order_ids": deterministic_ids,
        "append_only_lifecycle": append_only_observed,
        "fill_idempotency": duplicate_fill_observed,
        "local_fixture_state_hash": _stable_hash(
            {"replay": replay.snapshot(), "idempotency": idempotency.snapshot(), "restart": restart_snapshot}
        ),
    }


def _fixture_market_open(timestamp: str, config: Mapping[str, Any]) -> bool:
    calendar = dict(config["fixture_market_calendar"])
    instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    if instant.weekday() >= 5:
        return not bool(calendar["weekend_closed"])
    # The fixture dates are in US daylight time. Keep this deterministic and local-only.
    local_clock = (instant.hour - 4) % 24
    local_time = time(local_clock, instant.minute)
    close_time = time(13, 0) if instant.date().isoformat() == "2026-07-03" else time(16, 0)
    return time(9, 30) <= local_time <= close_time


def _load_portfolio_dependency(
    root: Path,
    config: Mapping[str, Any],
    *,
    expected_code_commit: str,
) -> dict[str, Any]:
    pointer_path = _resolve(root, Path(str(config["portfolio_latest_pointer"])))
    pointer = _read_json(pointer_path)
    if pointer.get("code_commit") != expected_code_commit:
        raise ValueError("portfolio_dependency_mismatch:code_commit")
    if pointer.get("promotion_credit_allowed") is not False:
        raise ValueError("portfolio_dependency_must_remain_promotion_blocked")
    manifest_path = _resolve(root, Path(str(pointer["manifest"])))
    report_path = _resolve(root, Path(str(pointer["report"])))
    if _sha256_file(manifest_path) != pointer["manifest_sha256"]:
        raise ValueError("portfolio_manifest_hash_mismatch")
    if _sha256_file(report_path) != pointer["report_sha256"]:
        raise ValueError("portfolio_report_hash_mismatch")
    report = _read_json(report_path)
    if report.get("candidate", {}).get("candidate_id") != config["candidate_id"]:
        raise ValueError("portfolio_dependency_mismatch:candidate_id")
    if report.get("promotion_evidence", {}).get("promotion_credit_allowed") is not False:
        raise ValueError("portfolio_report_promotion_credit_not_false")
    return {"pointer": pointer, "report": report, "pointer_sha256": _sha256_file(pointer_path)}


def _write_immutable_run(
    *, root: Path, artifact_root: Path, evidence: Mapping[str, Any]
) -> CandidateExecutionEnvelopeResult:
    run_id = str(evidence["run_id"])
    run_dir = artifact_root / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"immutable_candidate_execution_run_exists:{run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    payloads: dict[str, Any] = {
        "execution_drill.json": evidence["execution_drill"],
        "order_lifecycle.jsonl": evidence["lifecycle"],
        "orders.jsonl": evidence["orders"],
        "fills.jsonl": evidence["fills"],
        "position_ledger.jsonl": evidence["positions"],
        "cash_ledger.jsonl": evidence["cash"],
        "reconciliation.json": evidence["reconciliation"],
        "execution_quality.json": evidence["execution_quality"],
        "paper_ledger_uow.json": evidence["paper_ledger_uow"],
        "broker_credential_metadata_contract.json": evidence["credential_contract"],
        "paper_simulation_readiness_envelope.json": evidence["readiness"],
        "report.json": evidence["report"],
        "report.md": _markdown(evidence["report"]),
    }
    for name, payload in payloads.items():
        path = run_dir / name
        if name.endswith(".jsonl"):
            path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in payload), encoding="utf-8")
        elif name.endswith(".json"):
            path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")
    files = {
        name: {"sha256": _sha256_file(run_dir / name), "bytes": (run_dir / name).stat().st_size}
        for name in ARTIFACT_FILES
    }
    report = evidence["report"]
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "code_commit": report["code_commit"],
        "code_tree_hash": report["code_tree_hash"],
        "status": report["status"],
        "files": files,
        "promotion_credit_allowed": False,
        "paper_order_allowed": False,
        "real_order_submitted": False,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha256 = _sha256_file(manifest_path)
    pointer = {
        "schema_version": "us_etf_26_candidate_execution_envelope_latest_pointer_v1",
        "run_id": run_id,
        "run_dir": _repo_rel(root, run_dir),
        "manifest": _repo_rel(root, manifest_path),
        "manifest_sha256": manifest_sha256,
        "report": _repo_rel(root, run_dir / "report.json"),
        "report_sha256": files["report.json"]["sha256"],
        "code_commit": report["code_commit"],
        "status": report["status"],
        "promotion_credit_allowed": False,
        "paper_order_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }
    artifact_root.mkdir(parents=True, exist_ok=True)
    latest = artifact_root / "latest_pointer.json"
    latest.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return CandidateExecutionEnvelopeResult(run_id, run_dir, latest, dict(report), manifest, manifest_sha256)


def _markdown(report: Mapping[str, Any]) -> str:
    recon = report["reconciliation"]
    quality = report["execution_quality"]
    return (
        "# US ETF26 Candidate Execution Envelope\n\n"
        f"- Run: `{report['run_id']}`\n"
        f"- Status: `{report['status']}`\n"
        f"- Scenarios: `{report['counts']['scenario_count']}`\n"
        f"- Orders / fills: `{report['counts']['order_count']}` / `{report['counts']['fill_count']}`\n"
        f"- Reconciliation deltas: order `{recon['order_fill_quantity_delta']}`, position `{recon['fill_position_quantity_delta']}`, cash `{recon['fill_cash_balance_delta']}`\n"
        f"- Fill rate: `{quality['fill_rate']}`\n"
        f"- Implementation shortfall USD: `{quality['implementation_shortfall_usd']}`\n"
        "- Paper/live/promotion: `blocked`\n\n"
        "This packet is fixture-only local engineering evidence and cannot unlock paper or live trading.\n"
    )


def _deterministic_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:24]}"


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_json_object:{path}")
    return value


def _resolve(root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _repo_rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _dedupe(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))
