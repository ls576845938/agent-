"""Registered two-member BTC cohort on one offline economic authority.

The module deliberately does not expose an arbitrary signal/quantity API.  It
loads the exact registered Donchian rule member and registered Qlib member,
derives their immutable decision objects from the bound inputs, and sends only
the resulting account delta through the existing Donchian offline controller,
Risk, OMS, venue and ledger UOW.

The caller owns orchestration persistence.  A prepared decision is safe to
persist before execution, but member state/cursor may be committed only after
``committed_projection`` proves the original ledger UOW (or for a delta-zero
decision, for which no execution context is issued).
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_shared.strategy_delivery.models import DeliveryError, digest
from quant_crypto.application.btc_multi_strategy_offline import (
    execute_offline_multi_strategy_order,
    issue_offline_multi_strategy_context,
    prepare_offline_multi_strategy_order,
)
from quant_crypto.application.donchian_offline_replay import (
    DonchianOfflineReplay,
    DonchianOfflineReplayConfig,
)
from quant_crypto.application.qlib_offline_replay import _QlibOfflineVenue
from quant_crypto.portfolio.multi_strategy import (
    ExplicitBudgetPolicy,
    MemberDecision,
    build_two_member_cohort_plan,
)
from quant_crypto.trading_contracts import Signal, SignalDirection, TargetPosition


COHORT_RUNTIME_SCHEMA = "delivery_offline_runtime_v3"
COHORT_ADAPTER_ID = "btc_registered_two_member_cohort_v1"
COHORT_DECISION_SCHEMA = "btc_registered_cohort_prepared_decision_v1"
COHORT_PROJECTION_SCHEMA = "btc_registered_cohort_projection_v1"
MEMBER_STATE_SCHEMA = "btc_registered_cohort_member_state_v1"
DONCHIAN_ADAPTER = "btc_donchian_history_offline_v1"
QLIB_ADAPTER = "factory_lgbm_ast_v1"
EXPECTED_ADAPTERS = (DONCHIAN_ADAPTER, QLIB_ADAPTER)


def cohort_data_version(*, donchian_input_digest: str, qlib_input_digest: str) -> str:
    """Return the one adapter-keyed identity used by open and recovery."""
    if not donchian_input_digest or not qlib_input_digest:
        raise DeliveryError("cohort_input_digest_missing")
    return digest({
        "donchian": str(donchian_input_digest),
        "qlib": str(qlib_input_digest),
    })


def _object_payload(value: Any) -> dict[str, Any]:
    payload = dict(getattr(value, "__dict__", {}))
    for key, item in tuple(payload.items()):
        if isinstance(item, datetime):
            payload[key] = item.astimezone(timezone.utc).isoformat()
        elif hasattr(item, "value"):
            payload[key] = item.value
    return json.loads(json.dumps(payload, default=str))


def _direction(value: str) -> SignalDirection:
    normalized = str(value or "").lower()
    if normalized == "long":
        return SignalDirection.LONG
    if normalized == "short":
        return SignalDirection.SHORT
    if normalized == "flat":
        return SignalDirection.FLAT
    raise DeliveryError("cohort_member_direction_invalid")


def _decimal_text(value: Any) -> str:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise DeliveryError("cohort_numeric_fact_invalid")
    rendered = format(parsed.normalize(), "f")
    return "0" if rendered in {"", "-0"} else rendered


@dataclass(frozen=True)
class CohortMemberSource:
    member_id: str
    registration_id: str
    content_digest: str
    binding_digest: str
    adapter_id: str
    input_revision_id: str
    input_digest: str
    input_head: str
    input_evidence_kind: str
    strategy_id: str
    strategy_version: str
    protection_policy_sha256: str

    def evidence(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class PreparedCohortDecision:
    cursor: int
    event_time_utc: str
    decision_time_utc: str
    plan: Any
    member_objects: Mapping[str, Mapping[str, Any]]
    next_member_states: Mapping[str, Mapping[str, Any]]
    common_market_facts: Mapping[str, Any]
    order_plan: Mapping[str, Any] | None
    context: Any | None
    binding: Mapping[str, Any]

    def durable(self) -> dict[str, Any]:
        value = {
            "schema_version": COHORT_DECISION_SCHEMA,
            "cursor": self.cursor,
            "event_time_utc": self.event_time_utc,
            "decision_time_utc": self.decision_time_utc,
            "allocation_plan": self.plan.to_mapping(),
            "member_objects": {
                member: {
                    name + "_sha256": digest(_object_payload(obj))
                    for name, obj in objects.items()
                    if obj is not None
                }
                for member, objects in self.member_objects.items()
            },
            "next_member_states": deepcopy(dict(self.next_member_states)),
            "common_market_facts": deepcopy(dict(self.common_market_facts)),
            "order_plan": None if self.order_plan is None else deepcopy(dict(self.order_plan)),
            "execution_context_issued": self.context is not None,
            "binding": deepcopy(dict(self.binding)),
        }
        value["sha256"] = digest(value)
        return value


def validate_common_runtime(runtime: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version", "simulation_namespace", "account_ref",
        "state_directory_sha256", "run_id", "adapter_ids",
        "initial_equity_usdt", "currency", "equity_unit",
        "simulated_venue_identity_hash", "venue_adapter", "contract_digest",
    }
    unsigned = {key: value for key, value in runtime.items() if key != "contract_digest"}
    if (
        set(runtime) != fields
        or runtime.get("schema_version") != COHORT_RUNTIME_SCHEMA
        or tuple(runtime.get("adapter_ids") or ()) != EXPECTED_ADAPTERS
        or runtime.get("initial_equity_usdt") != 5000
        or runtime.get("currency") != "USDT"
        or runtime.get("equity_unit") != "USDT"
        or runtime.get("venue_adapter") != "donchian_controller_qlib_observed_venue_v1"
        or runtime.get("contract_digest") != digest(unsigned)
    ):
        raise DeliveryError("cohort_account_runtime_contract_invalid")
    return dict(runtime)


def canonical_members(rows: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if len(rows) != 2:
        raise DeliveryError("cohort_exactly_two_members_required")
    ordered = tuple(sorted(rows, key=lambda value: str(value.get("registration_id") or value.get("id") or "")))
    ids = [str(value.get("registration_id") or value.get("id") or "") for value in ordered]
    adapters = tuple(sorted(str(value.get("adapter_id") or value.get("package", {}).get("adapter_id") or "") for value in ordered))
    if len(set(ids)) != 2 or adapters != tuple(sorted(EXPECTED_ADAPTERS)):
        raise DeliveryError("cohort_member_identity_or_adapter_set_invalid")
    return ordered  # type: ignore[return-value]


def validate_member_execution_policy(rows: Sequence[Mapping[str, Any]]) -> None:
    adapters={str(row.get("adapter_id") or row.get("package",{}).get("adapter_id") or "") for row in rows}
    # Registered Donchian executes on the t+1 decision observation. The
    # frozen Qlib package executes at the t+2 delayed open with signed costs.
    # One common order cannot preserve both contracts.
    if adapters==set(EXPECTED_ADAPTERS):
        raise DeliveryError("cohort_member_execution_policy_incompatible")


def _initial_member_state(member: CohortMemberSource) -> dict[str, Any]:
    value = {
        "schema_version": MEMBER_STATE_SCHEMA,
        "member_id": member.member_id,
        "registration_id": member.registration_id,
        "adapter_id": member.adapter_id,
        "revision": 0,
        "last_cursor": 0,
        "last_decision": None,
        "exit_state": None,
    }
    value["sha256"] = digest(value)
    return value


def validate_member_state(value: Mapping[str, Any] | None, member: CohortMemberSource) -> dict[str, Any]:
    if value is None:
        return _initial_member_state(member)
    actual = dict(value)
    expected_sha = actual.pop("sha256", None)
    if (
        expected_sha != digest(actual)
        or actual.get("schema_version") != MEMBER_STATE_SCHEMA
        or actual.get("member_id") != member.member_id
        or actual.get("registration_id") != member.registration_id
        or actual.get("adapter_id") != member.adapter_id
        or type(actual.get("revision")) is not int
        or type(actual.get("last_cursor")) is not int
    ):
        raise DeliveryError("cohort_member_state_invalid")
    actual["sha256"] = expected_sha
    return actual


class RegisteredCohortReplay:
    """One controller/venue/UOW serving two independently versioned members."""

    @classmethod
    def open_projection_recovery(
        cls,
        *,
        runtime_binding: Mapping[str, Any],
        state_dir: Path,
        repo_root: Path,
        decision_time_utc: str,
        data_version: str,
    ) -> "RegisteredCohortReplay":
        """Open only the sealed economic authority needed to repair projection.

        This path deliberately does not re-evaluate either strategy and cannot
        prepare a new decision.  Expired/revoked mutable management records may
        therefore not strand an already committed ledger UOW.
        """
        self = cls.__new__(cls)
        self.runtime_binding = validate_common_runtime(runtime_binding)
        self.state_dir = Path(state_dir).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.recovery_only = True
        decision_time = datetime.fromisoformat(str(decision_time_utc).replace("Z", "+00:00")).astimezone(timezone.utc)

        def venue_factory(path: Path, now: datetime) -> _QlibOfflineVenue:
            return _QlibOfflineVenue(path, now=now, initial_equity_usdt=5000.0)

        self.replay = DonchianOfflineReplay(DonchianOfflineReplayConfig(
            repo_root=self.repo_root,
            state_dir=self.state_dir,
            run_id=str(self.runtime_binding["run_id"]),
            decision_time_utc=decision_time,
            data_version=str(data_version),
            venue_factory=venue_factory,
            decision_time_provider=lambda completed, _ordinal, _phase: completed.astimezone(timezone.utc),
            max_notional_usdt=Decimal("50"),
        ))
        return self

    def __init__(
        self,
        *,
        service: Any,
        members: Sequence[Mapping[str, Any]],
        runtime_binding: Mapping[str, Any],
        state_dir: Path,
        repo_root: Path,
        donchian_input: Mapping[str, Any],
        qlib_input: Mapping[str, Any],
        budgets: Mapping[str, Any],
        recovery_only: bool = False,
    ) -> None:
        self.service = service
        self.runtime_binding = validate_common_runtime(runtime_binding)
        self.state_dir = Path(state_dir).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.budgets = deepcopy(dict(budgets))
        self.recovery_only = bool(recovery_only)
        ordered = canonical_members(members)
        validate_member_execution_policy(ordered)
        self.member_rows = {str(row["id"]): dict(row) for row in ordered}

        self.don_row = next(row for row in ordered if row["package"]["adapter_id"] == DONCHIAN_ADAPTER)
        self.qlib_row = next(row for row in ordered if row["package"]["adapter_id"] == QLIB_ADAPTER)
        self.don_input = dict(donchian_input)
        self.qlib_input = dict(qlib_input)
        self.historical_input = self.don_input["historical_input"]
        self.history_spec = self.don_input["history_spec"]
        self.verified_qlib = self.qlib_input["verified_inputs"]
        from quant_crypto.application.btc_registered_donchian import verify_registered_donchian_cohort_member
        verify_registered_donchian_cohort_member(service,self.don_row["id"],
            content_digest=self.don_row["content_digest"],
            account_identity_hash=self.don_row["binding"]["identity_hash"],common_runtime=self.runtime_binding,
            spec=self.history_spec,historical_input=self.historical_input,recovery_only=recovery_only)
        if self.verified_qlib.manifest.get("initial_equity_usdt") != 5000:
            raise DeliveryError("cohort_initial_equity_mismatch")
        self.observations = tuple(self.verified_qlib.observations)
        if not self.observations:
            raise DeliveryError("cohort_common_event_clock_missing")
        self._verify_common_sources()

        first_forecast = self.verified_qlib.forecast(0)
        first_observation = self.observations[0]

        def venue_factory(path: Path, now: datetime) -> _QlibOfflineVenue:
            venue = _QlibOfflineVenue(path, now=now, initial_equity_usdt=5000.0)
            venue.set_market(
                now=first_forecast.timestamp_utc,
                mark_price=first_observation.mark_price,
                index_price=first_observation.index_price,
                fill_price=first_observation.close_price,
            )
            return venue

        self.replay = DonchianOfflineReplay(
            DonchianOfflineReplayConfig(
                repo_root=self.repo_root,
                state_dir=self.state_dir,
                run_id=str(self.runtime_binding["run_id"]),
                decision_time_utc=first_forecast.timestamp_utc,
                data_version=cohort_data_version(
                    donchian_input_digest=self.don_input["input_ref"]["content_digest"],
                    qlib_input_digest=self.qlib_input["input_ref"]["content_digest"],
                ),
                venue_factory=venue_factory,
                decision_time_provider=lambda completed, _ordinal, _phase: max(
                    completed.astimezone(timezone.utc), self.replay.venue.now
                ),
                max_notional_usdt=Decimal("50"),
            )
        )

    @property
    def total(self) -> int:
        return len(self.observations)

    def _verify_common_sources(self) -> None:
        """Qlib V2 observations are the sole common mark/index/funding clock.

        Donchian source bars which overlap that clock must agree exactly.  A
        mismatch is rejected; neither member gets to choose the account fact.
        """
        manifest = self.verified_qlib.manifest
        if manifest.get("schema_version") != "registered_offline_market_v2":
            raise DeliveryError("cohort_common_market_source_requires_verified_v2")
        qlib_by_event = {pd.Timestamp(row.event_time_utc): row for row in self.observations}
        if len(qlib_by_event) != len(self.observations):
            raise DeliveryError("cohort_common_event_clock_ambiguous")
        overlaps = 0
        for row in self.historical_input.signal_rows.itertuples(index=False):
            event = pd.Timestamp(row.event_time)
            observed = qlib_by_event.get(event)
            if observed is None:
                continue
            overlaps += 1
            mark = self.historical_input.mark_by_event.get(event.to_pydatetime())
            if (
                Decimal(str(row.close)) != Decimal(str(observed.close_price))
                or mark is None
                or Decimal(str(mark.get("close"))) != Decimal(str(observed.mark_price))
            ):
                raise DeliveryError("cohort_common_price_source_conflict")
        if overlaps != len(self.observations):
            raise DeliveryError("cohort_member_clocks_do_not_match")
        qlib_funding={fact.event_time_utc:(Decimal(str(fact.rate)),Decimal(str(observation.mark_price)))
            for observation in self.observations for fact in observation.funding_settlements}
        for fact in self.historical_input.funding_events:
            shared=qlib_funding.get(fact.settlement_time_utc)
            if shared is not None and shared!=(Decimal(str(fact.rate)),Decimal(str(fact.mark_price))):
                raise DeliveryError("cohort_common_funding_source_conflict")

    def _common_market(self, index: int) -> tuple[Any, Any, dict[str, Any]]:
        observation = self.observations[index]
        forecast = self.verified_qlib.forecast(index)
        if forecast.timestamp_utc != observation.event_time_utc + pd.Timedelta(hours=1):
            raise DeliveryError("cohort_common_event_clock_mismatch")
        facts = {
            "schema_version": "btc_registered_cohort_market_facts_v1",
            "source_registration_id": self.qlib_row["id"],
            "source_input_revision_id": self.qlib_input["input_ref"]["input_revision_id"],
            "event_time_utc": observation.event_time_utc.isoformat(),
            "decision_time_utc": forecast.timestamp_utc.isoformat(),
            "close_price": _decimal_text(observation.close_price),
            "mark_price": _decimal_text(observation.mark_price),
            "index_price": _decimal_text(observation.index_price),
            "funding_rate": _decimal_text(observation.funding_rate),
            "funding_events": [
                {
                    "event_id": fact.event_id,
                    "event_time_utc": fact.event_time_utc.isoformat(),
                    "rate": _decimal_text(fact.rate),
                    "source_sha256": fact.source_sha256,
                }
                for fact in observation.funding_settlements
            ],
        }
        facts["sha256"] = digest(facts)
        return observation, forecast, facts

    def _apply_common_market(self, observation: Any, forecast: Any) -> None:
        venue = self.replay.venue
        visible_facts=[fact for fact in observation.maintenance_facts
            if fact.observed_at_utc<=forecast.timestamp_utc]
        decision_mark=visible_facts[-1].mark_price if visible_facts else observation.mark_price
        decision_index=visible_facts[-1].index_price if visible_facts else observation.index_price
        self._guard_hosted_protection(decision_mark)
        venue.set_market(
            now=forecast.timestamp_utc,
            mark_price=decision_mark,
            index_price=decision_index,
            fill_price=observation.close_price,
        )
        for fact in observation.funding_settlements:
            if fact.event_time_utc>forecast.timestamp_utc:
                raise DeliveryError("cohort_common_funding_event_from_future")
            venue.apply_verified_funding_event(
                fact=fact,
                mark_price=decision_mark,
                contract_value_btc=Decimal("0.01"),
            )
        if observation.funding_cashflow_usdt:
            venue.apply_funding(
                amount_usdt=observation.funding_cashflow_usdt,
                timestamp_utc=forecast.timestamp_utc,
            )
        self._reconcile_common_market("registered_cohort_common_decision_market")

    def _guard_hosted_protection(self, mark_price: Any) -> None:
        venue = self.replay.venue
        position=Decimal(str(venue.state.get("position") or 0))
        if position:
            algos=list(venue.state.get("algos") or [])
            if len(algos)!=1 or algos[0].get("state")!="live":
                raise DeliveryError("cohort_protection_evidence_incomplete")
            algo=algos[0]
            if any(algo.get(key) in {None,""} for key in ("slTriggerPx","tpTriggerPx")):
                raise DeliveryError("cohort_protection_evidence_incomplete")
            sl=Decimal(str(algo["slTriggerPx"]));tp=Decimal(str(algo["tpTriggerPx"]))
            mark=Decimal(str(mark_price))
            if (position>0 and (mark<=sl or mark>=tp)) or (position<0 and (mark>=sl or mark<=tp)):
                # Existing ledger attribution can safely allocate ordinary
                # parent fills. A hosted protection fill lacks a trusted
                # per-member attribution receipt in this V1 cohort seam.
                raise DeliveryError("cohort_unattributed_hosted_protection_fill")

    def _reconcile_common_market(self, trigger: str) -> None:
        venue=self.replay.venue
        snapshot = self.replay.controller._collect_exchange_snapshot(venue)
        self.replay.controller._apply_snapshot(snapshot)
        ledger = self.replay.controller._state.get("ledger_reconciliation", {})
        from quant_crypto.application.btc_demo_production_composition import canonical_ledger_snapshot_sha256
        if ledger.get("exchange_snapshot_sha256") != canonical_ledger_snapshot_sha256(snapshot):
            self.replay.controller._commit_ledger_reconciliation(
                snapshot=snapshot, trigger=trigger
            )
        self.replay._assert_ledger_current(snapshot)

    def _donchian_objects(
        self,
        decision_time: datetime,
        *,
        member_contracts: Decimal = Decimal("0"),
        member_state: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        visible = self.historical_input.frame.loc[:pd.Timestamp(decision_time)]
        # The original evaluator remains authoritative, while its entry-only
        # policy sees this member's persisted ownership instead of the shared
        # account total.  The read view is never installed on the controller or
        # venue and therefore cannot mutate common economic authority.
        if all(hasattr(self.replay, name) for name in ("_canonical_frame_cache", "controller", "spec")):
            self.replay._frame, _ = self.replay._canonical_frame_cache(visible)
            preview = dict(self.replay.controller._signal_decision(
                self.replay.spec.identity(),
                client=SimpleNamespace(state={"position": _decimal_text(member_contracts)}),
            ))
        else:  # Narrow compatibility for decision-only test seams.
            preview = dict(self.replay.evaluate_frame(visible, visible_until=decision_time))
        direction = _direction(str(preview.get("direction") or "flat"))
        quantity = Decimal(str(preview.get("target_contracts") or "0"))
        if quantity < 0:
            raise DeliveryError("cohort_short_member_unsupported_v1")
        identity = {
            "schema_version": "btc_registered_cohort_donchian_object_identity_v1",
            "registration_id": str(self.don_row.get("id") or ""),
            "content_digest": str(self.don_row.get("content_digest") or ""),
            "decision_time_utc": decision_time.astimezone(timezone.utc).isoformat(),
            "member_contracts": _decimal_text(member_contracts),
            "member_state_sha256": str((member_state or {}).get("sha256") or ""),
            "preview_sha256": digest(preview),
        }
        signal_id = "sig_" + digest(identity)[:16]
        signal = Signal(
            timestamp_utc=decision_time,
            strategy_id=self.don_row["package"]["strategy_id"],
            symbol="BTC-USDT-SWAP",
            direction=direction,
            strength=abs(float(preview.get("raw_signal") or 0)),
            horizon="registered_donchian_original_signal",
            reason="original_registered_donchian_signal_preview",
            metadata={"registered_source": True, "preview_sha256": digest(preview),
                "member_contracts": _decimal_text(member_contracts)},
            signal_id=signal_id,
        )
        target = TargetPosition(
            timestamp_utc=decision_time,
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            target_weight=0.0,
            target_quantity=float(quantity),
            signal_id=signal.signal_id,
            target_position_id="tgt_" + digest({**identity, "signal_id": signal.signal_id})[:16],
            metadata={"source_kind": "signal", "quantity_unit": "contracts", "registered_source": True},
        )
        return {"signal": signal, "forecast": None, "target": target}, preview

    def _qlib_objects(
        self,
        *,
        index: int,
        member_contracts: Decimal,
        member_state: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from quant_crypto.application.btc_registered_candidate import registered_candidate_cohort_decision
        return registered_candidate_cohort_decision(
            verified=self.verified_qlib,
            index=index,
            controller=self.replay.controller,
            venue=self.replay.venue,
            member_contracts=member_contracts,
            member_state=member_state,
        )

    def prepare(
        self,
        *,
        cursor: int,
        member_states: Mapping[str, Mapping[str, Any] | None],
    ) -> PreparedCohortDecision:
        if self.recovery_only:
            raise DeliveryError("cohort_recovery_forbids_new_decisions")
        if cursor < 0 or cursor >= self.total:
            raise DeliveryError("cohort_cursor_invalid")
        observation, forecast, common = self._common_market(cursor)
        self._apply_common_market(observation, forecast)
        allocations = self.replay.controller._state.get("strategy_allocations") or {}
        current = allocations.get("member_contracts") or {
            self.don_row["id"]: "0", self.qlib_row["id"]: "0"
        }
        if set(current) != {self.don_row["id"], self.qlib_row["id"]}:
            raise DeliveryError("cohort_member_allocation_identity_mismatch")
        don_state = validate_member_state(member_states.get(self.don_row["id"]), self._member_source(self.don_row, self.don_input))
        qlib_state = validate_member_state(member_states.get(self.qlib_row["id"]), self._member_source(self.qlib_row, self.qlib_input))
        don_objects, don_preview = self._donchian_objects(
            forecast.timestamp_utc,
            member_contracts=Decimal(str(current[self.don_row["id"]])),
            member_state=don_state,
        )
        qlib_objects, qlib_next = self._qlib_objects(
            index=cursor,
            member_contracts=Decimal(str(current[self.qlib_row["id"]])),
            member_state=qlib_state,
        )
        objects = {self.don_row["id"]: don_objects, self.qlib_row["id"]: qlib_objects}
        decisions = []
        for row, source, item, unit in (
            (self.don_row, self._member_source(self.don_row, self.don_input), don_objects, "contracts"),
            (self.qlib_row, self._member_source(self.qlib_row, self.qlib_input), qlib_objects, "btc"),
        ):
            target = item["target"]
            direction = str(getattr(item["signal"].direction, "value", item["signal"].direction)).lower()
            if Decimal(str(target.target_quantity or 0)) < 0:
                raise DeliveryError("cohort_short_member_unsupported_v1")
            decisions.append(MemberDecision(
                member_id=row["id"], strategy_id=source.strategy_id,
                strategy_version=source.strategy_version,
                source_object_sha256=digest(_object_payload(target)),
                target_position_id=target.target_position_id,
                direction=direction,
                target_quantity=Decimal(str(target.target_quantity or 0)),
                quantity_unit=unit, contract_value_btc=Decimal("0.01"),
                lot_size_contracts=Decimal("0.01"),
                protection_policy_sha256=source.protection_policy_sha256,
            ))
        plan = build_two_member_cohort_plan(
            members=tuple(decisions),  # type: ignore[arg-type]
            budgets=ExplicitBudgetPolicy(
                member_max_notional_usdt={key: Decimal(str(value)) for key, value in self.budgets["member_max_notional_usdt"].items()},
                member_max_loss_usdt={key: Decimal(str(value)) for key, value in self.budgets["member_max_loss_usdt"].items()},
                account_max_notional_usdt=Decimal(str(self.budgets["account_max_notional_usdt"])),
                account_max_loss_usdt=Decimal(str(self.budgets["account_max_loss_usdt"])),
            ),
            mark_price_usdt=Decimal(common["mark_price"]),
            current_member_contracts={key: Decimal(str(value)) for key, value in current.items()},
        )
        next_states = {
            self.don_row["id"]: self._next_state(don_state, cursor, {"preview": don_preview, "target": _object_payload(don_objects["target"])}),
            self.qlib_row["id"]: self._next_state(qlib_state, cursor, qlib_next),
        }
        binding = {
            "schema_version": "btc_registered_cohort_decision_binding_v1",
            "cursor": cursor + 1,
            "common_market_sha256": common["sha256"],
            "allocation_plan_sha256": plan.allocation_plan_sha256,
            "member_state_before_sha256": {self.don_row["id"]: don_state["sha256"], self.qlib_row["id"]: qlib_state["sha256"]},
            "member_state_after_sha256": {key: value["sha256"] for key, value in next_states.items()},
        }
        if plan.order_delta_contracts == 0:
            order_plan = None
            context = None
        else:
            snapshot = self.replay.controller._collect_exchange_snapshot(self.replay.venue)
            order_plan = prepare_offline_multi_strategy_order(
                controller=self.replay.controller, snapshot=snapshot, plan=plan
            )
            context = issue_offline_multi_strategy_context(
                plan=plan, member_strategy_objects=objects,
                timestamp_utc=forecast.timestamp_utc,
                run_id=self.replay.config.run_id,
                client_order_id=str(order_plan["client_order_id"]),
                limit_price=Decimal(str(order_plan["limit_price"])),
                prior_allocation_state=(allocations or None),
            )
        return PreparedCohortDecision(
            cursor=cursor + 1,
            event_time_utc=observation.event_time_utc.isoformat(),
            decision_time_utc=forecast.timestamp_utc.isoformat(),
            plan=plan, member_objects=objects, next_member_states=next_states,
            common_market_facts=common, order_plan=order_plan, context=context,
            binding=binding,
        )

    @staticmethod
    def _next_state(prior: Mapping[str, Any], cursor: int, decision: Mapping[str, Any]) -> dict[str, Any]:
        value = {
            **{key: deepcopy(item) for key, item in prior.items() if key != "sha256"},
            "revision": int(prior["revision"]) + 1,
            "last_cursor": cursor + 1,
            "last_decision": deepcopy(dict(decision)),
        }
        if "exit_state" in decision:
            value["exit_state"] = deepcopy(decision["exit_state"])
        value["sha256"] = digest(value)
        return value

    def _member_source(self, row: Mapping[str, Any], data: Mapping[str, Any]) -> CohortMemberSource:
        package = row["package"]
        if package["adapter_id"] == DONCHIAN_ADAPTER:
            policy_sha256 = self.replay.controller._protection_policy.policy_sha256
        else:
            from quant_crypto.application.btc_registered_candidate import registered_protection_policy
            policy_sha256 = registered_protection_policy(package).policy_sha256
        return CohortMemberSource(
            member_id=row["id"], registration_id=row["id"],
            content_digest=row["content_digest"], binding_digest=row["binding_digest"],
            adapter_id=package["adapter_id"],
            input_revision_id=data["input_ref"]["input_revision_id"],
            input_digest=data["input_ref"]["content_digest"],
            input_head=data["input_ref"]["input_head"],
            input_evidence_kind=data["input_ref"]["evidence_kind"],
            strategy_id=package["strategy_id"], strategy_version=package["strategy_version"],
            protection_policy_sha256=policy_sha256,
        )

    def execute(self, prepared: PreparedCohortDecision) -> dict[str, Any]:
        if prepared.context is None or prepared.order_plan is None:
            return self.committed_projection(prepared)
        snapshot = self.replay.controller._collect_exchange_snapshot(self.replay.venue)
        execute_offline_multi_strategy_order(
            controller=self.replay.controller, client=self.replay.venue,
            snapshot=snapshot, order_plan=prepared.order_plan,
            context=prepared.context,
        )
        return self.committed_projection(prepared)

    @staticmethod
    def _matching_committed_event(durable: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        order_plan = durable.get("order_plan")
        client_id = "" if not isinstance(order_plan, Mapping) else str(order_plan.get("client_order_id") or "")
        if not client_id:
            raise DeliveryError("cohort_committed_ledger_authority_missing_or_ambiguous")
        plan = durable.get("allocation_plan")
        if not isinstance(plan, Mapping):
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")
        if not plan.get("member_list_sha256") or not plan.get("allocation_plan_sha256"):
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")
        expected_plan = str(plan["allocation_plan_sha256"])
        desired = plan.get("desired_member_contracts")
        deltas = plan.get("member_delta_contracts")
        if not isinstance(desired, Mapping) or not isinstance(deltas, Mapping):
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")
        normalized = lambda values: {str(key): _decimal_text(value) for key, value in values.items()}
        try:
            expected_before = {
                str(member): Decimal(str(desired[member])) - Decimal(str(delta))
                for member, delta in deltas.items()
            }
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise DeliveryError("cohort_committed_allocation_identity_mismatch") from exc
        if set(expected_before) != {str(member) for member in desired}:
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")
        supplied_before = plan.get("current_member_contracts")
        if isinstance(supplied_before, Mapping) and normalized(supplied_before) != normalized(expected_before):
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")

        def _ledger_rows(payload: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
            order_ledger = payload.get("order_ledger")
            orders = order_ledger.get("orders") if isinstance(order_ledger, Mapping) else None
            fill_ledger = payload.get("fill_ledger")
            if isinstance(fill_ledger, Mapping):
                fill_ledger = fill_ledger.get("fills")
            return (
                [row for row in orders if isinstance(row, Mapping)] if isinstance(orders, list) else [],
                [row for row in fill_ledger if isinstance(row, Mapping)] if isinstance(fill_ledger, list) else [],
            )

        prior_payload: Mapping[str, Any] | None = None
        candidates: list[Mapping[str, Any]] = []
        decision_ms = int(datetime.fromisoformat(str(durable["decision_time_utc"]).replace("Z", "+00:00")).timestamp() * 1000)
        for event in events:
            if event.get("event_type") != "ledger_uow_committed":
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                prior_payload = None
                continue
            orders, fills = _ledger_rows(payload)
            matching_orders = [row for row in orders
                if str(row.get("client_order_id") or row.get("clOrdId") or "") == client_id]
            if not matching_orders:
                prior_payload = payload
                continue
            order_ids = {str(row.get("order_id") or row.get("ordId") or "") for row in matching_orders}
            order_ids.discard("")
            matching_fills = [row for row in fills if (
                str(row.get("client_order_id") or row.get("clOrdId") or "") == client_id
                or str(row.get("order_id") or row.get("ordId") or "") in order_ids)]
            fill_ids = {str(row.get("fill_id") or row.get("tradeId") or "") for row in matching_fills}
            fill_ids.discard("")
            allocation = payload.get("strategy_allocation")
            if not isinstance(allocation, Mapping):
                raise DeliveryError("cohort_committed_allocation_identity_mismatch")
            fill_allocations = allocation.get("fill_allocations")
            matching_allocations = {
                str(fill_id): row
                for fill_id, row in (fill_allocations.items() if isinstance(fill_allocations, Mapping) else ())
                if isinstance(row, Mapping)
                and str(row.get("allocation_plan_sha256") or "") == expected_plan
            }

            prior_orders: list[Mapping[str, Any]] = []
            prior_fills: list[Mapping[str, Any]] = []
            prior_allocation: Mapping[str, Any] | None = None
            if prior_payload is not None:
                prior_orders, prior_fills = _ledger_rows(prior_payload)
                candidate_prior_allocation = prior_payload.get("strategy_allocation")
                if isinstance(candidate_prior_allocation, Mapping):
                    prior_allocation = candidate_prior_allocation
            prior_order_ids = {
                str(row.get("order_id") or row.get("ordId") or "")
                for row in prior_orders
                if str(row.get("client_order_id") or row.get("clOrdId") or "") == client_id
            }
            prior_order_ids.discard("")
            prior_fill_ids = {
                str(row.get("fill_id") or row.get("tradeId") or "")
                for row in prior_fills
                if str(row.get("client_order_id") or row.get("clOrdId") or "") == client_id
                or str(row.get("order_id") or row.get("ordId") or "") in (order_ids | prior_order_ids)
            }
            prior_fill_ids.discard("")
            prior_fill_allocations = (
                prior_allocation.get("fill_allocations")
                if isinstance(prior_allocation, Mapping) else None
            )
            prior_plan_fill_ids = {
                str(fill_id)
                for fill_id, row in (
                    prior_fill_allocations.items()
                    if isinstance(prior_fill_allocations, Mapping) else ()
                )
                if isinstance(row, Mapping)
                and str(row.get("allocation_plan_sha256") or "") == expected_plan
            }

            newly_filled = fill_ids - prior_fill_ids
            newly_allocated = set(matching_allocations) - prior_plan_fill_ids
            if not newly_filled and not newly_allocated:
                # A later reconciliation UOW repeats cumulative order/fill and
                # allocation facts.  It is evidence of the same prior commit,
                # not a second economic transition.
                prior_payload = payload
                continue
            if (
                len(matching_orders) != 1
                or len(order_ids) != 1
                or not fill_ids
                or fill_ids != set(matching_allocations)
                or newly_filled != fill_ids
                or newly_allocated != fill_ids
            ):
                raise DeliveryError("cohort_committed_order_fill_proof_mismatch")

            if (
                allocation.get("member_list_sha256") != plan.get("member_list_sha256")
                or normalized(allocation.get("member_contracts") or {}) != normalized(desired)
            ):
                raise DeliveryError("cohort_committed_allocation_identity_mismatch")
            if prior_allocation is None:
                if any(value != 0 for value in expected_before.values()):
                    raise DeliveryError("cohort_committed_allocation_transition_unproven")
            elif (
                prior_allocation.get("member_list_sha256") != plan.get("member_list_sha256")
                or normalized(prior_allocation.get("member_contracts") or {}) != normalized(expected_before)
            ):
                raise DeliveryError("cohort_committed_allocation_transition_unproven")

            attributed = {str(member): Decimal("0") for member in deltas}
            expected_order_id = next(iter(order_ids))
            for row in matching_allocations.values():
                allocation_order_id = str(row.get("order_id") or "")
                if allocation_order_id and allocation_order_id != expected_order_id:
                    raise DeliveryError("cohort_committed_order_fill_proof_mismatch")
                members = row.get("members")
                if not isinstance(members, Mapping) or set(members) != set(attributed):
                    raise DeliveryError("cohort_committed_order_fill_proof_mismatch")
                for member, member_row in members.items():
                    if not isinstance(member_row, Mapping):
                        raise DeliveryError("cohort_committed_order_fill_proof_mismatch")
                    attributed[str(member)] += Decimal(str(member_row.get("signed_contracts")))
            if normalized(attributed) != normalized(deltas):
                raise DeliveryError("cohort_committed_order_fill_proof_mismatch")
            for row in matching_fills:
                raw_time = row.get("timestamp_ms", row.get("ts"))
                try: fill_ms = int(str(raw_time))
                except (TypeError, ValueError) as exc:
                    raise DeliveryError("cohort_committed_event_time_proof_mismatch") from exc
                if fill_ms < decision_ms or fill_ms > decision_ms + 60_000:
                    raise DeliveryError("cohort_committed_event_time_proof_mismatch")
            candidates.append(event)
            prior_payload = payload

        if len(candidates) != 1:
            raise DeliveryError("cohort_committed_ledger_authority_missing_or_ambiguous")
        return candidates[0]

    def committed_projection(self, prepared: PreparedCohortDecision) -> dict[str, Any]:
        recovered = self.replay.controller._runtime_store.recover()
        if recovered.blockers or recovered.truncated_tail:
            raise DeliveryError("cohort_runtime_recovery_blocked")
        ledger_event = None
        client_id = "" if prepared.order_plan is None else str(prepared.order_plan["client_order_id"])
        if client_id:
            ledger_event = self._matching_committed_event(prepared.durable(), recovered.events)
        state = self.replay.controller._state
        allocation = deepcopy(state.get("strategy_allocations") or {})
        if client_id and allocation.get("member_list_sha256") != prepared.plan.member_list_sha256:
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")
        value = {
            "schema_version": COHORT_PROJECTION_SCHEMA,
            "cursor": prepared.cursor,
            "event_time_utc": prepared.event_time_utc,
            "decision_time_utc": prepared.decision_time_utc,
            "decision_sha256": prepared.durable()["sha256"],
            "economic_action": "none_delta_zero" if not client_id else "ledger_uow_committed",
            "client_order_id": client_id or None,
            "ledger_event_hash": None if ledger_event is None else ledger_event["event_hash"],
            "position_contracts": str(self.replay.venue.state["position"]),
            "order_count": len(self.replay.venue.state["orders"]),
            "fill_count": len(self.replay.venue.state["fills"]),
            "strategy_allocations": allocation,
            "member_states": deepcopy(dict(prepared.next_member_states)),
            "common_market_facts": deepcopy(dict(prepared.common_market_facts)),
        }
        value["sha256"] = digest(value)
        return value

    def repair_committed(self, pending: Mapping[str, Any]) -> dict[str, Any] | None:
        """Project an already committed ledger UOW without issuing another order."""
        durable = pending.get("prepared") if isinstance(pending, Mapping) else None
        if (not isinstance(durable, Mapping) or durable.get("schema_version") != COHORT_DECISION_SCHEMA
            or durable.get("sha256") != digest({key:value for key,value in durable.items() if key!="sha256"})):
            raise DeliveryError("cohort_pending_decision_invalid")
        order_plan = durable.get("order_plan")
        client_id = "" if order_plan is None else str(order_plan.get("client_order_id") or "")
        if not client_id:
            return None
        recovered = self.replay.controller._runtime_store.recover()
        if recovered.blockers or recovered.truncated_tail:
            raise DeliveryError("cohort_runtime_recovery_blocked")
        candidates = [event for event in recovered.events if event.get("event_type") == "ledger_uow_committed"
            and any(str(order.get("client_order_id") or order.get("clOrdId") or "") == client_id
                    for order in event.get("payload", {}).get("order_ledger", {}).get("orders", []))]
        if not candidates: return None
        committed_event = self._matching_committed_event(durable, recovered.events)
        allocation = deepcopy(self.replay.controller._state.get("strategy_allocations") or {})
        plan = durable["allocation_plan"]
        if allocation.get("member_list_sha256") != plan.get("member_list_sha256"):
            raise DeliveryError("cohort_committed_allocation_identity_mismatch")
        value = {"schema_version":COHORT_PROJECTION_SCHEMA,"cursor":durable["cursor"],
            "event_time_utc":durable["event_time_utc"],"decision_time_utc":durable["decision_time_utc"],
            "decision_sha256":durable["sha256"],"economic_action":"ledger_uow_committed",
            "client_order_id":client_id,"ledger_event_hash":committed_event["event_hash"],
            "position_contracts":str(self.replay.venue.state["position"]),
            "order_count":len(self.replay.venue.state["orders"]),"fill_count":len(self.replay.venue.state["fills"]),
            "strategy_allocations":allocation,"member_states":deepcopy(durable["next_member_states"]),
            "common_market_facts":deepcopy(durable["common_market_facts"])}
        value["sha256"]=digest(value)
        return value

    def close(self) -> None:
        self.replay.close()


__all__ = [
    "COHORT_ADAPTER_ID", "COHORT_RUNTIME_SCHEMA", "RegisteredCohortReplay",
    "PreparedCohortDecision", "canonical_members", "validate_common_runtime",
    "validate_member_state", "validate_member_execution_policy", "cohort_data_version",
]
