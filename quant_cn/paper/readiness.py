"""Deterministic, offline-only drills for CN paper-readiness closure.

The module proves only that injected synthetic/recorded fixtures can exercise
the domain contracts.  It contains no broker, SDK, account, network, paper
queue, or order-endpoint surface and can never authorize paper trading.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Mapping

from quant_cn.application.market_semantics_preflight import (
    MarketSemanticsPreflight,
)
from quant_cn.execution.models import OrderIntent
from quant_cn.execution.oms import OfflineOMS
from quant_cn.execution.qmt_adapter_contract import QMT_REQUIRED_BLOCKERS
from quant_cn.execution.simulator import SimulationSnapshot, simulate
from quant_cn.ledger import (
    InMemoryLedgerStore,
    derive_account_state,
    post_fill,
    post_opening_cash,
    reconcile,
)
from quant_cn.market.rules import BoardLotPolicy, FeeComponent, FeePolicy
from quant_cn.portfolio import (
    RiskInputs,
    TargetPosition,
    build_order_intent,
    evaluate_target,
)
from quant_cn.replay import ReplayInput, run_replay


DRILL_SCHEMA_VERSION = "cn_equity_offline_paper_drill_v1"
PAPER_SAFETY_FLAGS: Mapping[str, bool] = {
    "broker_access_allowed": False,
    "demo_allowed": False,
    "live_allowed": False,
    "network_allowed": False,
    "order_endpoint_allowed": False,
    "paper_allowed": False,
    "paper_queue_allowed": False,
    "paper_start_authorized": False,
    "private_endpoint_allowed": False,
    "promotion_eligible": False,
    "qmt_sdk_allowed": False,
    "real_order_submitted": False,
    "secret_access_allowed": False,
    "withdraw_allowed": False,
}
_SOURCE_KINDS = frozenset({"synthetic_fixture", "recorded_fixture"})
_RUNTIME_ACTIONS = (
    "account_read",
    "broker_connected",
    "network_accessed",
    "order_endpoint_called",
    "paper_queue_written",
    "private_endpoint_called",
    "qmt_sdk_imported",
    "real_order_submitted",
    "secret_accessed",
)
_RULE_VERSIONS = (
    ("board_lot", "cn-paper-fixture-board-lot-v1"),
    ("fee_schedule", "cn-paper-fixture-fee-v1"),
    ("price_limit", "cn-paper-fixture-limit-v1"),
    ("sellability", "cn-paper-fixture-t1-v1"),
    ("session", "cn-paper-fixture-session-v1"),
    ("settlement", "cn-paper-fixture-settlement-v1"),
)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"paper_drill_datetime_required:{field_name}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"paper_drill_datetime_naive:{field_name}")
    return value.astimezone(timezone.utc)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class OfflinePaperFixture:
    """Already-injected fixture metadata; runtime capabilities are all false."""

    fixture_id: str
    source_kind: str
    source_version: str
    available_at: datetime
    fixed_clock: datetime
    seed: int
    opening_cash: Decimal
    runtime_actions: tuple[tuple[str, bool], ...]

    def __post_init__(self) -> None:
        for name in ("fixture_id", "source_kind", "source_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"paper_drill_field_missing:{name}")
            object.__setattr__(self, name, value.strip())
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError("paper_drill_source_kind_unknown")
        available_at = _aware_utc(self.available_at, "available_at")
        fixed_clock = _aware_utc(self.fixed_clock, "fixed_clock")
        if available_at > fixed_clock:
            raise ValueError("paper_drill_fixture_not_available")
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "fixed_clock", fixed_clock)
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TypeError("paper_drill_seed_must_be_integer")
        if (
            not isinstance(self.opening_cash, Decimal)
            or not self.opening_cash.is_finite()
            or self.opening_cash <= 0
        ):
            raise ValueError("paper_drill_opening_cash_invalid")
        actions = tuple(sorted(self.runtime_actions))
        if tuple(name for name, _ in actions) != _RUNTIME_ACTIONS:
            raise ValueError("paper_drill_runtime_action_set_invalid")
        if any(type(value) is not bool or value for _, value in actions):
            raise ValueError("paper_drill_runtime_action_attestation_invalid")
        object.__setattr__(self, "runtime_actions", actions)

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(
            {
                "available_at": self.available_at.isoformat(),
                "fixture_id": self.fixture_id,
                "fixed_clock": self.fixed_clock.isoformat(),
                "opening_cash": str(self.opening_cash),
                "runtime_actions": self.runtime_actions,
                "seed": self.seed,
                "source_kind": self.source_kind,
                "source_version": self.source_version,
            }
        )


def build_offline_fixture(
    source_kind: str,
    *,
    fixed_clock: datetime,
) -> OfflinePaperFixture:
    normalized = str(source_kind).strip()
    return OfflinePaperFixture(
        fixture_id=f"cn-paper-{normalized}-v1",
        source_kind=normalized,
        source_version=f"cn-paper-{normalized}-source-v1",
        available_at=_aware_utc(fixed_clock, "fixed_clock"),
        fixed_clock=_aware_utc(fixed_clock, "fixed_clock"),
        seed=7 if normalized == "synthetic_fixture" else 11,
        opening_cash=Decimal("5000"),
        runtime_actions=tuple((name, False) for name in _RUNTIME_ACTIONS),
    )


@dataclass(frozen=True)
class OfflineKillSwitch:
    active: bool = False
    activated_at: datetime | None = None
    reason: str | None = None

    def activate(self, *, activated_at: datetime, reason: str) -> OfflineKillSwitch:
        timestamp = _aware_utc(activated_at, "kill_switch.activated_at")
        normalized = str(reason).strip()
        if not normalized:
            raise ValueError("paper_kill_switch_reason_required")
        return replace(
            self,
            active=True,
            activated_at=timestamp,
            reason=normalized,
        )

    def assert_can_admit(self, intent: OrderIntent) -> None:
        if not isinstance(intent, OrderIntent):
            raise TypeError("paper_order_intent_required")
        if self.active:
            raise RuntimeError("paper_kill_switch_active")


@dataclass(frozen=True)
class PaperDrillResult:
    fixture_id: str
    source_kind: str
    fixture_sha256: str
    status: str
    decision: str
    checks: tuple[tuple[str, bool], ...]
    blockers: tuple[str, ...]
    lifecycle: tuple[str, ...]
    reconciliation_status: str
    replay_status: str
    replay_sha256: str
    audit_sha256: str
    evidence_sha256: str
    runtime_eligible: bool
    paper_start_authorized: bool
    promotion_eligible: bool
    safety_flags: tuple[tuple[str, bool], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DRILL_SCHEMA_VERSION,
            "fixture_id": self.fixture_id,
            "source_kind": self.source_kind,
            "fixture_sha256": self.fixture_sha256,
            "status": self.status,
            "decision": self.decision,
            "checks": dict(self.checks),
            "blockers": list(self.blockers),
            "lifecycle": list(self.lifecycle),
            "reconciliation_status": self.reconciliation_status,
            "replay_status": self.replay_status,
            "replay_sha256": self.replay_sha256,
            "audit_sha256": self.audit_sha256,
            "evidence_sha256": self.evidence_sha256,
            "runtime_eligible": self.runtime_eligible,
            "paper_start_authorized": self.paper_start_authorized,
            "promotion_eligible": self.promotion_eligible,
            "safety_flags": dict(self.safety_flags),
        }


def _preflight() -> MarketSemanticsPreflight:
    return MarketSemanticsPreflight(
        status="pass",
        decision="research_only",
        blockers=(),
        versions=_RULE_VERSIONS,
        sources=tuple(
            (name, f"fixture://cn-paper/{name}") for name, _ in _RULE_VERSIONS
        ),
    )


def _board_lot_policy() -> BoardLotPolicy:
    return BoardLotPolicy(
        buy_lot_size=100,
        sell_lot_size=100,
        odd_lot_sell_allowed=True,
        odd_lot_sell_mode="full_remainder_only",
    )


def _fee_policy() -> FeePolicy:
    commission = FeeComponent(
        name="commission",
        rate=Decimal("0.001"),
        minimum_amount=Decimal("0"),
        fixed_amount=Decimal("0"),
        rounding_quantum=Decimal("0.01"),
        rounding_mode="half_up",
    )
    tax = FeeComponent(
        name="sell_tax",
        rate=Decimal("0.001"),
        minimum_amount=Decimal("0"),
        fixed_amount=Decimal("0"),
        rounding_quantum=Decimal("0.01"),
        rounding_mode="half_up",
    )
    return FeePolicy(buy=(commission,), sell=(commission, tax))


def _risk_inputs(
    *,
    available_cash: Decimal,
) -> RiskInputs:
    return RiskInputs(
        preflight=_preflight(),
        board_lot_policy=_board_lot_policy(),
        rule_versions=_RULE_VERSIONS,
        limit_price=Decimal("10.00"),
        available_cash=available_cash,
        sellable_quantity=1000,
        estimated_fee=Decimal("1.00"),
        max_order_notional=Decimal("50000"),
        session_sequence=42,
    )


def _build_intent(fixture: OfflinePaperFixture) -> tuple[OrderIntent, tuple[str, ...]]:
    decision_time = fixture.fixed_clock - timedelta(minutes=10)
    target = TargetPosition(
        target_id=f"target:{fixture.fixture_id}",
        run_id=f"run:{fixture.fixture_id}",
        stable_security_id="CN:600000",
        target_quantity=200,
        current_quantity=0,
        decision_time=decision_time,
        evidence_hash=fixture.fingerprint,
    )
    inputs = _risk_inputs(available_cash=fixture.opening_cash)
    decision = evaluate_target(
        target,
        inputs,
        decision_id=f"risk:{fixture.fixture_id}",
    )
    if not decision.approved:
        raise RuntimeError("paper_drill_pre_trade_risk_unexpected_block")
    rejected = evaluate_target(
        replace(target, target_id=f"target-reject:{fixture.fixture_id}"),
        _risk_inputs(available_cash=Decimal("10")),
        decision_id=f"risk-reject:{fixture.fixture_id}",
    )
    if rejected.approved or "cash_insufficient" not in rejected.blockers:
        raise RuntimeError("paper_drill_pre_trade_rejection_missing")
    intent = build_order_intent(
        target,
        decision,
        inputs,
        order_id=f"order:{fixture.fixture_id}",
        client_order_id=f"client:{fixture.fixture_id}",
        created_at=decision_time,
    )
    return intent, rejected.blockers


def _state_material(oms: OfflineOMS) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            state.intent.order_id,
            state.status,
            state.filled_quantity,
            state.remaining_quantity,
            tuple(fill.fingerprint for fill in state.fills),
            state.audit_events,
        )
        for state in oms.states()
    )


def run_offline_paper_drill(fixture: OfflinePaperFixture) -> PaperDrillResult:
    """Run one deterministic fixture drill without granting runtime capability."""

    if not isinstance(fixture, OfflinePaperFixture):
        raise TypeError("offline_paper_fixture_required")

    intent, rejected_blockers = _build_intent(fixture)
    kill_switch = OfflineKillSwitch()
    kill_switch.assert_can_admit(intent)
    snapshot = SimulationSnapshot(
        snapshot_id=f"snapshot:{fixture.fixture_id}",
        as_of=fixture.fixed_clock - timedelta(minutes=5),
        phase="continuous",
        accepts_orders=True,
        suspended=False,
        lower_limit_price=Decimal("9.00"),
        upper_limit_price=Decimal("11.00"),
        tick_size=Decimal("0.01"),
        available_liquidity=100,
        available_cash=fixture.opening_cash,
        current_position=0,
        sellable_quantity=0,
        execution_price=Decimal("10.00"),
        rule_source_versions=_RULE_VERSIONS,
    )
    simulated = simulate(
        intent,
        preflight=_preflight(),
        snapshot=snapshot,
        board_lot_policy=_board_lot_policy(),
        fee_policy=_fee_policy(),
        fill_id=f"fill:{fixture.fixture_id}",
        received_at=fixture.fixed_clock - timedelta(minutes=4),
    )
    if simulated.status != "partially_filled" or len(simulated.fills) != 1:
        raise RuntimeError("paper_drill_partial_fill_missing")
    fill = simulated.fills[0]

    oms = OfflineOMS()
    oms.submit(intent)
    oms.submit(intent)
    oms.apply_fill(fill)
    oms.apply_fill(fill)
    kill_switch = kill_switch.activate(
        activated_at=fixture.fixed_clock - timedelta(minutes=3),
        reason="offline_drill",
    )
    admission_blocked = False
    try:
        kill_switch.assert_can_admit(intent)
    except RuntimeError as error:
        admission_blocked = str(error) == "paper_kill_switch_active"
    oms.request_cancel(
        intent.order_id,
        requested_at=fixture.fixed_clock - timedelta(minutes=2),
    )
    final_state = oms.confirm_cancel(
        intent.order_id,
        confirmed_at=fixture.fixed_clock - timedelta(minutes=1),
    )

    ledger = InMemoryLedgerStore()
    post_opening_cash(
        ledger,
        record_id=f"opening:{fixture.fixture_id}",
        amount=fixture.opening_cash,
        occurred_at=intent.created_at,
        source_hash=fixture.fingerprint,
    )
    post_fill(ledger, fill)
    post_fill(ledger, fill)
    reconciliation = reconcile(
        orders=oms.states(),
        ledger=ledger,
        opening_cash=fixture.opening_cash,
    )

    restarted = OfflineOMS()
    restarted.submit(intent)
    restarted.apply_fill(fill)
    restarted.request_cancel(
        intent.order_id,
        requested_at=fixture.fixed_clock - timedelta(minutes=2),
    )
    restarted.confirm_cancel(
        intent.order_id,
        confirmed_at=fixture.fixed_clock - timedelta(minutes=1),
    )
    restart_matches = _state_material(oms) == _state_material(restarted)
    restart_reconciliation = reconcile(
        orders=restarted.states(),
        ledger=ledger,
        opening_cash=fixture.opening_cash,
    )

    account = derive_account_state(ledger)
    replay = run_replay(
        ReplayInput(
            replay_id=f"replay:{fixture.fixture_id}",
            source_mode="injected_history",
            source_ref=f"immutable-fixture:{fixture.fixture_id}",
            fixed_clock=fixture.fixed_clock,
            seed=fixture.seed,
            opening_cash=fixture.opening_cash,
            orders=(intent,),
            fills=(fill, fill),
            expected_cash=account.cash,
            expected_positions=account.positions,
        )
    )

    audit = (
        ("fixture", fixture.fingerprint),
        ("signal", f"fixture-signal:{fixture.fixture_id}"),
        ("forecast", f"fixture-forecast:{fixture.fixture_id}"),
        ("target", intent.target_id),
        ("risk", intent.risk_decision_id),
        ("risk_rejection", ",".join(rejected_blockers)),
        ("order_intent", intent.fingerprint),
        ("fill", fill.fingerprint),
        ("ledger_cash", str(account.cash)),
        ("reconciliation", reconciliation.status),
        ("restart_reconciliation", restart_reconciliation.status),
        ("replay", replay.replay_hash),
        ("kill_switch", str(kill_switch.active).lower()),
    )
    audit_sha256 = _canonical_sha256(audit)
    checks = tuple(
        sorted(
            {
                "audit_complete": len(audit) == 13,
                "duplicate_fill_idempotent": len(final_state.fills) == 1,
                "kill_switch_blocks_admission": admission_blocked,
                "lifecycle_cancelled": final_state.status == "cancelled",
                "offline_runtime_actions_false": not any(
                    value for _, value in fixture.runtime_actions
                ),
                "partial_fill_observed": final_state.filled_quantity == 100
                and final_state.remaining_quantity == 100,
                "pre_trade_risk_approved": intent.quantity == 200,
                "pre_trade_risk_rejection_observed": (
                    "cash_insufficient" in rejected_blockers
                ),
                "reconciliation_clean": reconciliation.status == "reconciled",
                "replay_reconciled": replay.status == "reconciled",
                "restart_state_equal": restart_matches,
                "restart_reconciliation_clean": (
                    restart_reconciliation.status == "reconciled"
                ),
            }.items()
        )
    )
    failed = tuple(name for name, passed in checks if not passed)
    blockers = tuple(
        sorted(
            set(
                (
                    "cn_paper_offline_fixture_only",
                    *QMT_REQUIRED_BLOCKERS,
                    *(f"cn_paper_drill_check_failed:{name}" for name in failed),
                )
            )
        )
    )
    status = "quality_checked" if not failed else "blocked"
    decision = (
        "quality_checked_offline_only" if not failed else "blocked_fail_closed"
    )
    evidence_material = {
        "audit_sha256": audit_sha256,
        "blockers": blockers,
        "checks": checks,
        "fixture_sha256": fixture.fingerprint,
        "lifecycle": final_state.audit_events,
        "reconciliation": reconciliation.status,
        "replay_sha256": replay.replay_hash,
        "restart_reconciliation": restart_reconciliation.status,
        "safety_flags": PAPER_SAFETY_FLAGS,
    }
    return PaperDrillResult(
        fixture_id=fixture.fixture_id,
        source_kind=fixture.source_kind,
        fixture_sha256=fixture.fingerprint,
        status=status,
        decision=decision,
        checks=checks,
        blockers=blockers,
        lifecycle=final_state.audit_events,
        reconciliation_status=reconciliation.status,
        replay_status=replay.status,
        replay_sha256=replay.replay_hash,
        audit_sha256=audit_sha256,
        evidence_sha256=_canonical_sha256(evidence_material),
        runtime_eligible=False,
        paper_start_authorized=False,
        promotion_eligible=False,
        safety_flags=tuple(sorted(PAPER_SAFETY_FLAGS.items())),
    )
