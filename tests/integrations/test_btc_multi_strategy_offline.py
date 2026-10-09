from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_crypto.application.btc_multi_strategy_offline import (
    OfflineMultiStrategyContextError,
    execute_offline_multi_strategy_order,
    issue_offline_multi_strategy_context,
    prepare_offline_multi_strategy_order,
)
from quant_crypto.application.donchian_offline_replay import (
    DonchianOfflineReplay,
    DonchianOfflineReplayConfig,
)
from quant_crypto.application.btc_demo_production_composition import (
    canonical_ledger_snapshot_sha256,
)
from quant_crypto.application.hosted_protection_facts import (
    normalize_hosted_protection_facts,
)
from quant_crypto.portfolio.multi_strategy import (
    ExplicitBudgetPolicy,
    MemberDecision,
    build_two_member_cohort_plan,
)
from quant_crypto.oms.strategy_allocations import allocate_raw_fill
from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeError
from quant_crypto.trading_contracts import Signal, SignalDirection, TargetPosition


NOW = datetime(2026, 10, 4, 1, tzinfo=timezone.utc)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            getattr(value, "__dict__", value),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _proposal(
    *,
    member_id: str,
    strategy_id: str,
    quantity: str,
    unit: str,
    direction: str = "long",
) -> tuple[MemberDecision, dict[str, object]]:
    signal = Signal(
        timestamp_utc=NOW,
        strategy_id=strategy_id,
        symbol="BTC-USDT-SWAP",
        direction=(
            SignalDirection.LONG
            if direction == "long"
            else SignalDirection.SHORT
            if direction == "short"
            else SignalDirection.FLAT
        ),
        strength=1,
        horizon="bounded_fixture",
        metadata={"reviewed_fixture": True},
    )
    target = TargetPosition(
        timestamp_utc=NOW,
        strategy_id=strategy_id,
        symbol=signal.symbol,
        target_weight=0,
        target_quantity=float(Decimal(quantity)),
        signal_id=signal.signal_id,
        metadata={
            "frozen_params_sha256": member_id * 16,
            "quantity_unit": unit,
        },
    )
    decision = MemberDecision(
        member_id=member_id,
        strategy_id=strategy_id,
        strategy_version="fixture-only-v1",
        source_object_sha256=_digest(target),
        target_position_id=target.target_position_id,
        direction=direction,
        target_quantity=Decimal(quantity),
        quantity_unit=unit,
        contract_value_btc=Decimal("0.01"),
        lot_size_contracts=Decimal("0.01"),
        protection_policy_sha256="p" * 64,
    )
    return decision, {"signal": signal, "target": target}


def test_short_cohort_is_rejected_before_any_original_oms_order(
    tmp_path: Path,
) -> None:
    replay = DonchianOfflineReplay(
        DonchianOfflineReplayConfig(
            repo_root=Path.cwd(),
            state_dir=tmp_path / "short-runtime",
            run_id="multi-short-fixture-run-001",
            decision_time_utc=NOW,
            data_version="bounded-fixture-v1",
            max_notional_usdt=Decimal("50"),
        )
    )
    try:
        don, _ = _proposal(
            member_id="don",
            strategy_id="donchian-rule",
            quantity="0.01",
            unit="contracts",
            direction="short",
        )
        qlib, _ = _proposal(
            member_id="qlib",
            strategy_id="qlib-learning",
            quantity="0.0001",
            unit="btc",
            direction="short",
        )
        plan = build_two_member_cohort_plan(
            members=(don, qlib),
            budgets=ExplicitBudgetPolicy(
                member_max_notional_usdt={
                    "don": Decimal("20"),
                    "qlib": Decimal("20"),
                },
                member_max_loss_usdt={
                    "don": Decimal("4"),
                    "qlib": Decimal("4"),
                },
                account_max_notional_usdt=Decimal("50"),
                account_max_loss_usdt=Decimal("10"),
            ),
            mark_price_usdt=Decimal("60000"),
        )
        snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        before_uows = [
            event
            for event in replay.controller._runtime_store.recover().events
            if event["event_type"] == "ledger_uow_committed"
        ]

        with pytest.raises(
            OfflineMultiStrategyContextError,
            match="short_cohort_unsupported",
        ):
            prepare_offline_multi_strategy_order(
                controller=replay.controller,
                snapshot=snapshot,
                plan=plan,
            )

        after_uows = [
            event
            for event in replay.controller._runtime_store.recover().events
            if event["event_type"] == "ledger_uow_committed"
        ]
        assert len(after_uows) == len(before_uows)
        assert replay.venue.state["orders"] == []
        assert replay.venue.state["fills"] == []
        assert replay.venue.state["position"] == "0"
    finally:
        replay.close()


def test_runtime_rejects_forged_and_stale_allocation_before_economic_effects(
    tmp_path: Path,
) -> None:
    replay = DonchianOfflineReplay(
        DonchianOfflineReplayConfig(
            repo_root=Path.cwd(),
            state_dir=tmp_path / "multi-runtime-allocation-seal",
            run_id="multi-fixture-allocation-seal-001",
            decision_time_utc=NOW,
            data_version="bounded-fixture-v1",
            max_notional_usdt=Decimal("50"),
        )
    )
    try:
        don, don_objects = _proposal(
            member_id="don",
            strategy_id="donchian-rule",
            quantity="0.01",
            unit="contracts",
        )
        qlib, qlib_objects = _proposal(
            member_id="qlib",
            strategy_id="qlib-learning",
            quantity="0.0001",
            unit="btc",
        )
        budgets = ExplicitBudgetPolicy(
            member_max_notional_usdt={"don": Decimal("20"), "qlib": Decimal("20")},
            member_max_loss_usdt={"don": Decimal("4"), "qlib": Decimal("4")},
            account_max_notional_usdt=Decimal("50"),
            account_max_loss_usdt=Decimal("10"),
        )
        opening_plan = build_two_member_cohort_plan(
            members=(don, qlib), budgets=budgets, mark_price_usdt=Decimal("60000")
        )
        opening_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        opening_order_plan = prepare_offline_multi_strategy_order(
            controller=replay.controller,
            snapshot=opening_snapshot,
            plan=opening_plan,
        )
        opening_context = issue_offline_multi_strategy_context(
            plan=opening_plan,
            member_strategy_objects={"don": don_objects, "qlib": qlib_objects},
            timestamp_utc=replay.venue.now,
            run_id=replay.config.run_id,
            client_order_id=str(opening_order_plan["client_order_id"]),
            limit_price=Decimal(str(opening_order_plan["limit_price"])),
        )
        execute_offline_multi_strategy_order(
            controller=replay.controller,
            client=replay.venue,
            snapshot=opening_snapshot,
            order_plan=opening_order_plan,
            context=opening_context,
        )

        flat_don, flat_don_objects = _proposal(
            member_id="don",
            strategy_id="donchian-rule",
            quantity="0",
            unit="contracts",
            direction="flat",
        )
        hold_qlib, hold_qlib_objects = _proposal(
            member_id="qlib",
            strategy_id="qlib-learning",
            quantity="0.0001",
            unit="btc",
        )
        exit_plan = build_two_member_cohort_plan(
            members=(flat_don, hold_qlib),
            budgets=budgets,
            mark_price_usdt=Decimal("60000"),
            current_member_contracts={
                "don": Decimal("0.01"),
                "qlib": Decimal("0.01"),
            },
        )
        exit_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        exit_order_plan = prepare_offline_multi_strategy_order(
            controller=replay.controller,
            snapshot=exit_snapshot,
            plan=exit_plan,
        )
        current_allocation = json.loads(
            json.dumps(replay.controller._state["strategy_allocations"])
        )
        forged_allocation = json.loads(json.dumps(current_allocation))
        forged_allocation["funding_allocations"]["forged-bill"] = {
            "raw_bill_sha256": "forged",
            "raw_amount": "-1",
            "currency": "USDT",
            "members": {"don": "-0.5", "qlib": "-0.5"},
        }
        forged_context = issue_offline_multi_strategy_context(
            plan=exit_plan,
            member_strategy_objects={
                "don": flat_don_objects,
                "qlib": hold_qlib_objects,
            },
            timestamp_utc=replay.venue.now,
            run_id=replay.config.run_id,
            client_order_id=str(exit_order_plan["client_order_id"]),
            limit_price=Decimal(str(exit_order_plan["limit_price"])),
            prior_allocation_state=forged_allocation,
        )
        before_forged = {
            "orders": len(replay.venue.state["orders"]),
            "fills": len(replay.venue.state["fills"]),
            "uows": len(replay.controller._runtime_store.recover().events),
            "allocation": json.loads(
                json.dumps(replay.controller._state["strategy_allocations"])
            ),
            "risk": json.loads(json.dumps(replay.controller._state["risk_control"])),
        }
        with pytest.raises(
            OkxDemoPaperRuntimeError,
            match="prior_allocation_runtime_mismatch",
        ):
            execute_offline_multi_strategy_order(
                controller=replay.controller,
                client=replay.venue,
                snapshot=exit_snapshot,
                order_plan=exit_order_plan,
                context=forged_context,
            )
        assert len(replay.venue.state["orders"]) == before_forged["orders"]
        assert len(replay.venue.state["fills"]) == before_forged["fills"]
        assert len(replay.controller._runtime_store.recover().events) == before_forged["uows"]
        assert replay.controller._state["strategy_allocations"] == before_forged["allocation"]
        assert replay.controller._state["risk_control"] == before_forged["risk"]

        stale_context = issue_offline_multi_strategy_context(
            plan=exit_plan,
            member_strategy_objects={
                "don": flat_don_objects,
                "qlib": hold_qlib_objects,
            },
            timestamp_utc=replay.venue.now,
            run_id=replay.config.run_id,
            client_order_id=str(exit_order_plan["client_order_id"]),
            limit_price=Decimal(str(exit_order_plan["limit_price"])),
            prior_allocation_state=current_allocation,
        )
        replay.venue.now += timedelta(milliseconds=10)
        replay.venue.observe_funding_bill(
            bill_id="funding-invalidates-issued-context",
            balance_change_usdt=Decimal("-0.02"),
        )
        funding_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        replay.controller._apply_snapshot(funding_snapshot)
        replay.controller._commit_ledger_reconciliation(
            snapshot=funding_snapshot,
            trigger="multi_strategy_context_staleness_funding",
        )
        before_stale = {
            "orders": len(replay.venue.state["orders"]),
            "fills": len(replay.venue.state["fills"]),
            "uows": len(replay.controller._runtime_store.recover().events),
            "allocation": json.loads(
                json.dumps(replay.controller._state["strategy_allocations"])
            ),
            "risk": json.loads(json.dumps(replay.controller._state["risk_control"])),
        }
        with pytest.raises(
            OkxDemoPaperRuntimeError,
            match="prior_allocation_runtime_mismatch",
        ):
            execute_offline_multi_strategy_order(
                controller=replay.controller,
                client=replay.venue,
                snapshot=funding_snapshot,
                order_plan=exit_order_plan,
                context=stale_context,
            )
        assert len(replay.venue.state["orders"]) == before_stale["orders"]
        assert len(replay.venue.state["fills"]) == before_stale["fills"]
        assert len(replay.controller._runtime_store.recover().events) == before_stale["uows"]
        assert replay.controller._state["strategy_allocations"] == before_stale["allocation"]
        assert replay.controller._state["risk_control"] == before_stale["risk"]

        fresh_context = issue_offline_multi_strategy_context(
            plan=exit_plan,
            member_strategy_objects={
                "don": flat_don_objects,
                "qlib": hold_qlib_objects,
            },
            timestamp_utc=replay.venue.now,
            run_id=replay.config.run_id,
            client_order_id=str(exit_order_plan["client_order_id"]),
            limit_price=Decimal(str(exit_order_plan["limit_price"])),
            prior_allocation_state=replay.controller._state["strategy_allocations"],
        )
        fresh_result = execute_offline_multi_strategy_order(
            controller=replay.controller,
            client=replay.venue,
            snapshot=funding_snapshot,
            order_plan=exit_order_plan,
            context=fresh_context,
        )
        assert fresh_result["filled_contracts"] == "0.01"
        assert replay.venue.state["position"] == "0.01"
    finally:
        replay.close()


def test_two_member_cohort_uses_original_oms_venue_and_ledger_uow(
    tmp_path: Path,
) -> None:
    replay = DonchianOfflineReplay(
        DonchianOfflineReplayConfig(
            repo_root=Path.cwd(),
            state_dir=tmp_path / "multi-runtime",
            run_id="multi-fixture-run-001",
            decision_time_utc=NOW,
            data_version="bounded-fixture-v1",
            max_notional_usdt=Decimal("50"),
        )
    )
    try:
        don, don_objects = _proposal(
            member_id="don", strategy_id="donchian-rule", quantity="0.01", unit="contracts"
        )
        qlib, qlib_objects = _proposal(
            member_id="qlib", strategy_id="qlib-learning", quantity="0.0001", unit="btc"
        )
        plan = build_two_member_cohort_plan(
            members=(don, qlib),
            budgets=ExplicitBudgetPolicy(
                member_max_notional_usdt={"don": Decimal("20"), "qlib": Decimal("20")},
                member_max_loss_usdt={"don": Decimal("4"), "qlib": Decimal("4")},
                account_max_notional_usdt=Decimal("50"),
                account_max_loss_usdt=Decimal("10"),
            ),
            mark_price_usdt=Decimal("60000"),
        )
        snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        order_plan = prepare_offline_multi_strategy_order(
            controller=replay.controller, snapshot=snapshot, plan=plan
        )
        context = issue_offline_multi_strategy_context(
            plan=plan,
            member_strategy_objects={"don": don_objects, "qlib": qlib_objects},
            timestamp_utc=replay.venue.now,
            run_id=replay.config.run_id,
            client_order_id=str(order_plan["client_order_id"]),
            limit_price=Decimal(str(order_plan["limit_price"])),
        )
        result = execute_offline_multi_strategy_order(
            controller=replay.controller,
            client=replay.venue,
            snapshot=snapshot,
            order_plan=order_plan,
            context=context,
        )

        assert result["filled_contracts"] == "0.02"
        assert replay.venue.state["position"] == "0.02"
        assert replay.venue.state["orders"][-1]["ordType"] == "fok"
        assert replay.venue.state["orders"][-1]["sz"] == "0.02"
        assert len(replay.venue.state["fills"]) == 1
        recovered = replay.controller._runtime_store.recover()
        ledger_uows = [
            event
            for event in recovered.events
            if event["event_type"] == "ledger_uow_committed"
        ]
        terminal = ledger_uows[-1]
        allocation = terminal["payload"]["strategy_allocation"]
        assert allocation["member_contracts"] == {"don": "0.01", "qlib": "0.01"}
        assert allocation["reconciliation"]["reconciled"] is True
        assert terminal["state_after"]["strategy_allocations"] == allocation
        assert terminal["payload"]["risk_context"]["account_ledger_replay"]["reconciled"] is True
        safety = replay.controller._state["safety"]
        assert safety["demo_environment_only"] is True
        assert all(
            safety[key] is False
            for key in (
                "formal_paper_runtime_started",
                "live_order_allowed",
                "real_money_order_allowed",
                "transfer_allowed",
                "withdraw_allowed",
                "permission_upgrade_allowed",
            )
        )

        opening_fill_ts = int(replay.venue.state["fills"][0]["ts"])
        replay.venue.now += timedelta(milliseconds=10)
        advanced_snapshot = replay.controller._collect_exchange_snapshot(
            replay.venue
        )
        replay.controller._apply_snapshot(advanced_snapshot)
        replay.controller._commit_ledger_reconciliation(
            snapshot=advanced_snapshot,
            trigger="multi_strategy_fixture_clock_advance",
        )

        flat_don, flat_don_objects = _proposal(
            member_id="don",
            strategy_id="donchian-rule",
            quantity="0",
            unit="contracts",
            direction="flat",
        )
        hold_qlib, hold_qlib_objects = _proposal(
            member_id="qlib",
            strategy_id="qlib-learning",
            quantity="0.0001",
            unit="btc",
        )
        exit_plan = build_two_member_cohort_plan(
            members=(flat_don, hold_qlib),
            budgets=ExplicitBudgetPolicy(
                member_max_notional_usdt={"don": Decimal("20"), "qlib": Decimal("20")},
                member_max_loss_usdt={"don": Decimal("4"), "qlib": Decimal("4")},
                account_max_notional_usdt=Decimal("50"),
                account_max_loss_usdt=Decimal("10"),
            ),
            mark_price_usdt=Decimal("60000"),
            current_member_contracts={"don": Decimal("0.01"), "qlib": Decimal("0.01")},
        )
        exit_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        exit_order_plan = prepare_offline_multi_strategy_order(
            controller=replay.controller, snapshot=exit_snapshot, plan=exit_plan
        )
        exit_context = issue_offline_multi_strategy_context(
            plan=exit_plan,
            member_strategy_objects={
                "don": flat_don_objects,
                "qlib": hold_qlib_objects,
            },
            timestamp_utc=replay.venue.now,
            run_id=replay.config.run_id,
            client_order_id=str(exit_order_plan["client_order_id"]),
            limit_price=Decimal(str(exit_order_plan["limit_price"])),
            prior_allocation_state=allocation,
        )
        exit_result = execute_offline_multi_strategy_order(
            controller=replay.controller,
            client=replay.venue,
            snapshot=exit_snapshot,
            order_plan=exit_order_plan,
            context=exit_context,
        )
        assert exit_result["filled_contracts"] == "0.01"
        assert replay.venue.state["position"] == "0.01"
        assert replay.venue.state["orders"][-1]["ordType"] == "ioc"
        assert replay.venue.state["algos"][0]["sz"] == "0.01"
        assert len(replay.venue.state["orders"]) == 2
        assert len(replay.venue.state["fills"]) == 2
        recovered_after_exit = replay.controller._runtime_store.recover()
        exit_uow = [
            event
            for event in recovered_after_exit.events
            if event["event_type"] == "ledger_uow_committed"
        ][-1]
        exit_allocation = exit_uow["payload"]["strategy_allocation"]
        assert exit_allocation["member_contracts"] == {"don": "0", "qlib": "0.01"}
        assert exit_allocation["reconciliation"]["reconciled"] is True
        revision = exit_uow["payload"]["order_ledger"]["terminal_order"][
            "offline_residual_protection_revision"
        ]
        assert revision["exited_member_id"] == "don"
        assert revision["residual_member_ids"] == ["qlib"]
        assert revision["residual_contracts"] == "0.01"
        assert revision["exit_fill"]["fill_id"] == "offline-fill-2"
        assert revision["prior_protection"]["prior_algo_id"] == "offline-algo-1"
        assert revision["replacement_protection"]["algo_id"] == "offline-residual-algo-1"
        post_exit_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        normalized_residual = normalize_hosted_protection_facts(
            pending_algo_orders=post_exit_snapshot["pending_algo_orders"],
            positions=post_exit_snapshot["positions"],
            account=post_exit_snapshot["account"],
            runtime_facts={
                **replay.controller._state["runtime"],
                "runtime_identity": replay.controller._runtime_identity,
                "strategy_id": replay.controller._state["strategy"]["strategy_id"],
                "strategy_version": replay.controller._state["strategy"]["strategy_version"],
            },
            ownership_facts=replay.controller._hosted_protection_fact_projection(
                post_exit_snapshot
            ),
            snapshot_sha256=canonical_ledger_snapshot_sha256(post_exit_snapshot),
            snapshot_captured_at_utc=post_exit_snapshot["captured_at_utc"],
        )
        assert normalized_residual["blockers"] == []
        assert normalized_residual["rows"][0]["owned_by_runtime"] is True
        assert normalized_residual["rows"][0]["ownership_evidence"][
            "revision_sha256"
        ] == revision["revision_sha256"]

        # This bill settled while both members owned the position but is first
        # observed after the exit.  Its venue time, not current holdings,
        # controls attribution through the original funding-only UOW.
        exit_fill_ts = int(replay.venue.state["fills"][1]["ts"])
        late_bill_ts = opening_fill_ts + 5
        assert opening_fill_ts < late_bill_ts < exit_fill_ts
        replay.venue.state["bills"].append(
            {
                "billId": "funding-before-exit-late-observation",
                "instId": "BTC-USDT-SWAP",
                "ccy": "USDT",
                "type": "8",
                "subType": "173",
                "balChg": "-0.10",
                "ts": str(late_bill_ts),
            }
        )
        replay.venue.state["equity"] = format(
            Decimal(replay.venue.state["equity"]) - Decimal("0.10"),
            "f",
        )
        replay.venue._persist()
        late_bill_snapshot = replay.controller._collect_exchange_snapshot(
            replay.venue
        )
        replay.controller._apply_snapshot(late_bill_snapshot)
        replay.controller._commit_ledger_reconciliation(
            snapshot=late_bill_snapshot,
            trigger="multi_strategy_funding_only_observation",
        )
        late_bill_uow = [
            event
            for event in replay.controller._runtime_store.recover().events
            if event["event_type"] == "ledger_uow_committed"
        ][-1]
        late_bill_allocation = late_bill_uow["payload"]["strategy_allocation"]
        assert late_bill_allocation["funding_allocations"][
            "funding-before-exit-late-observation"
        ]["members"] == {"don": "-0.05", "qlib": "-0.05"}
        assert late_bill_allocation["member_contracts"] == {
            "don": "0",
            "qlib": "0.01",
        }

        replay.venue.observe_funding_bill(
            bill_id="funding-after-exit-1",
            balance_change_usdt=Decimal("-0.03"),
        )
        funding_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        replay.controller._apply_snapshot(funding_snapshot)
        replay.controller._commit_ledger_reconciliation(
            snapshot=funding_snapshot,
            trigger="multi_strategy_funding_only_observation",
        )
        funding_recovery = replay.controller._runtime_store.recover()
        funding_uows = [
            event
            for event in funding_recovery.events
            if event["event_type"] == "ledger_uow_committed"
        ]
        funding_uow = funding_uows[-1]
        funded_allocation = funding_uow["payload"]["strategy_allocation"]
        assert funding_uow["payload"]["funding_ledger"]["cashflow"] == "-0.13"
        assert funded_allocation["funding_allocations"]["funding-after-exit-1"][
            "members"
        ] == {"qlib": "-0.03"}
        assert funding_uow["state_after"]["strategy_allocations"] == funded_allocation
        assert funding_uow["payload"]["risk_context"]["account_ledger_replay"][
            "reconciled"
        ] is True
        # Exact venue observation and UOW retry are idempotent: no new bill,
        # fee, order, or ledger event is created.
        replay.venue.observe_funding_bill(
            bill_id="funding-after-exit-1",
            balance_change_usdt=Decimal("-0.03"),
        )
        repeated_snapshot = replay.controller._collect_exchange_snapshot(replay.venue)
        replay.controller._apply_snapshot(repeated_snapshot)
        replay.controller._commit_ledger_reconciliation(
            snapshot=repeated_snapshot,
            trigger="multi_strategy_funding_only_observation",
        )
        repeated_uows = [
            event
            for event in replay.controller._runtime_store.recover().events
            if event["event_type"] == "ledger_uow_committed"
        ]
        assert len(repeated_uows) == len(funding_uows)
        assert repeated_uows[-1]["event_hash"] == funding_uow["event_hash"]

        before_restart = {
            "orders": len(replay.venue.state["orders"]),
            "fills": len(replay.venue.state["fills"]),
            "equity": replay.venue.state["equity"],
            "account_identity": post_exit_snapshot["account"]["identity"]["hash"],
            "funding_bill_ts": next(
                row["ts"]
                for row in replay.venue.state["bills"]
                if row["billId"] == "funding-after-exit-1"
            ),
        }
        repeated_fill = exit_uow["payload"]["order_ledger"]["terminal_order"][
            "fills"
        ][0]
        replay.close()
        recovered_replay = DonchianOfflineReplay(replay.config)
        try:
            recovered_allocation = recovered_replay.controller._state[
                "strategy_allocations"
            ]
            assert recovered_allocation == funded_allocation
            assert allocate_raw_fill(
                state=recovered_allocation,
                allocation_plan=exit_plan.to_mapping(),
                raw_fill=repeated_fill,
            ) == recovered_allocation
            assert len(recovered_replay.venue.state["orders"]) == before_restart["orders"] == 2
            assert len(recovered_replay.venue.state["fills"]) == before_restart["fills"] == 2
            assert recovered_replay.venue.state["equity"] == before_restart["equity"]
            recovered_replay.venue.now = datetime.fromtimestamp(
                float(
                    Decimal(before_restart["funding_bill_ts"])
                    / Decimal("1000")
                ),
                tz=timezone.utc,
            )
            recovered_snapshot = (
                recovered_replay.controller._collect_exchange_snapshot(
                    recovered_replay.venue
                )
            )
            assert recovered_snapshot["account"]["identity"]["hash"] == before_restart[
                "account_identity"
            ]
            assert recovered_replay.controller._state["risk_control"][
                "offline_residual_protection_revision"
            ]["revision_sha256"] == revision["revision_sha256"]
            assert recovered_replay.venue.state["position"] == "0.01"
            assert recovered_replay.venue.state["algos"][0]["sz"] == "0.01"

            before_duplicate_uows = [
                event
                for event in recovered_replay.controller._runtime_store.recover().events
                if event["event_type"] == "ledger_uow_committed"
            ]
            # A duplicate bill after process/controller reconstruction goes
            # through the original funding-only ledger UOW path and remains
            # an exact semantic retry, not a second cashflow.
            recovered_replay.venue.observe_funding_bill(
                bill_id="funding-after-exit-1",
                balance_change_usdt=Decimal("-0.03"),
            )
            repeated_after_restart = (
                recovered_replay.controller._collect_exchange_snapshot(
                    recovered_replay.venue
                )
            )
            recovered_replay.controller._apply_snapshot(repeated_after_restart)
            recovered_replay.controller._commit_ledger_reconciliation(
                snapshot=repeated_after_restart,
                trigger="multi_strategy_funding_only_observation",
            )
            after_restart_funding_uows = [
                event
                for event in recovered_replay.controller._runtime_store.recover().events
                if event["event_type"] == "ledger_uow_committed"
            ]
            assert len(after_restart_funding_uows) == len(before_duplicate_uows)
            assert after_restart_funding_uows[-1]["event_hash"] == (
                before_duplicate_uows[-1]["event_hash"]
            )
            assert recovered_replay.controller._state["strategy_allocations"] == (
                funded_allocation
            )
            assert recovered_replay.venue.state["equity"] == before_restart["equity"]

            # Re-issue the exact persisted member proposal/context on a new
            # controller.  The original OMS must reject the already-terminal
            # clOrdId before any new economic event instead of replaying it.
            recovered_context = issue_offline_multi_strategy_context(
                plan=exit_plan,
                member_strategy_objects={
                    "don": flat_don_objects,
                    "qlib": hold_qlib_objects,
                },
                timestamp_utc=recovered_replay.venue.now,
                run_id=recovered_replay.config.run_id,
                client_order_id=str(exit_order_plan["client_order_id"]),
                limit_price=Decimal(str(exit_order_plan["limit_price"])),
                prior_allocation_state=allocation,
            )
            with pytest.raises(OkxDemoPaperRuntimeError):
                execute_offline_multi_strategy_order(
                    controller=recovered_replay.controller,
                    client=recovered_replay.venue,
                    snapshot=repeated_after_restart,
                    order_plan=exit_order_plan,
                    context=recovered_context,
                )
            after_duplicate_order_uows = [
                event
                for event in recovered_replay.controller._runtime_store.recover().events
                if event["event_type"] == "ledger_uow_committed"
            ]
            assert len(after_duplicate_order_uows) == len(before_duplicate_uows)
            assert after_duplicate_order_uows[-1]["event_hash"] == (
                before_duplicate_uows[-1]["event_hash"]
            )
            assert len(recovered_replay.venue.state["orders"]) == 2
            assert len(recovered_replay.venue.state["fills"]) == 2
            assert recovered_replay.venue.state["equity"] == before_restart["equity"]
        finally:
            recovered_replay.close()
    finally:
        replay.close()
