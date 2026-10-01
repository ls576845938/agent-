from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quant_crypto.application.runtime_risk_guardian import (
    GuardianConfig,
    GuardianObservation,
    GuardianStatus,
    RuntimeRiskGuardian,
)
from quant_crypto.application.btc_demo_production_composition import (
    canonical_ledger_snapshot_sha256,
)
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION,
    AccountRiskFactError,
    advance_account_drawdown_fact,
    build_okx_account_cashflow_evidence,
    build_explicit_account_drawdown_baseline,
    build_unknown_account_drawdown_fact,
    replay_account_ledger_uows,
)
from quant_crypto.oms.runtime_store import BTCRuntimeStore, BTCRuntimeStoreError
from quant_crypto.oms.okx_demo_paper_runtime import (
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
ACCOUNT = "a" * 64
OTHER_ACCOUNT = "b" * 64
SNAPSHOT_0 = "1" * 64
SNAPSHOT_1 = "2" * 64
SNAPSHOT_2 = "3" * 64
SAFETY = {
    "promotion": False,
    "paper": False,
    "live": False,
    "private": False,
    "order": False,
    "real_order": False,
    "transfer": False,
    "withdraw": False,
}


def _baseline(equity: object = "100") -> dict:
    return build_explicit_account_drawdown_baseline(
        authority="explicit_reviewed_account_baseline_v1",
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=SNAPSHOT_0,
        observed_at_utc=T0,
        equity_usdt=equity,
        history_complete=False,
    )


def _advance(previous: dict, *, equity: object, snapshot: str, minutes: int) -> dict:
    return advance_account_drawdown_fact(
        previous=previous,
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=snapshot,
        observed_at_utc=T0 + timedelta(minutes=minutes),
        reference_time_utc=T0 + timedelta(minutes=minutes),
        equity_usdt=equity,
        external_cashflow_complete=True,
        external_cashflow_usdt="0",
    )


def test_drawdown_fact_tracks_amount_ratio_and_high_watermark_across_restart() -> None:
    baseline = _baseline()
    down = _advance(baseline, equity="90", snapshot=SNAPSHOT_1, minutes=1)
    assert down["schema_version"] == ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION
    assert down["drawdown_amount_usdt"] == "10"
    assert down["drawdown_ratio"] == "0.1"
    assert down["peak_equity_usdt"] == "100"

    new_peak = _advance(baseline, equity="110", snapshot=SNAPSHOT_1, minutes=1)
    assert new_peak["peak_equity_usdt"] == "110"
    assert new_peak["drawdown_amount_usdt"] == "0"
    recovered = json.loads(json.dumps(new_peak))
    after_restart = _advance(
        recovered,
        equity="99",
        snapshot=SNAPSHOT_2,
        minutes=2,
    )
    assert after_restart["peak_equity_usdt"] == "110"
    assert after_restart["drawdown_amount_usdt"] == "11"
    assert after_restart["drawdown_ratio"] == "0.1"
    assert after_restart["coverage_start_utc"] == baseline["coverage_start_utc"]
    assert after_restart["history_complete"] is False
    assert after_restart["risk_eligible"] is True


@pytest.mark.parametrize("equity", [None, "NaN", "Infinity", "0", "-1"])
def test_nonfinite_or_nonpositive_equity_never_creates_authoritative_baseline(
    equity: object,
) -> None:
    with pytest.raises(AccountRiskFactError):
        _baseline(equity)


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"account_identity_hash": OTHER_ACCOUNT}, "account_identity_mismatch"),
        ({"account_scope": "strategy"}, "account_scope_mismatch"),
        ({"currency": "USD"}, "currency_mismatch"),
        ({"observed_at_utc": T0 - timedelta(seconds=1)}, "observation_out_of_order"),
        (
            {
                "observed_at_utc": T0 + timedelta(minutes=2),
                "reference_time_utc": T0 + timedelta(minutes=1),
            },
            "observation_from_future",
        ),
        (
            {
                "observed_at_utc": T0 + timedelta(minutes=1),
                "reference_time_utc": T0 + timedelta(minutes=3),
            },
            "observation_stale",
        ),
        ({"external_cashflow_complete": False}, "external_cashflow_unknown"),
        ({"external_cashflow_usdt": "1"}, "external_cashflow_nonzero"),
    ],
)
def test_identity_time_scope_and_cashflow_anomalies_stay_unknown(
    overrides: dict,
    blocker: str,
) -> None:
    values = {
        "previous": _baseline(),
        "account_identity_hash": ACCOUNT,
        "account_scope": "dedicated_demo_account",
        "currency": "USDT",
        "snapshot_sha256": SNAPSHOT_1,
        "observed_at_utc": T0 + timedelta(minutes=1),
        "reference_time_utc": T0 + timedelta(minutes=1),
        "equity_usdt": "99",
        "external_cashflow_complete": True,
        "external_cashflow_usdt": "0",
        "freshness_ttl_seconds": 60,
    }
    values.update(overrides)
    fact = advance_account_drawdown_fact(**values)
    assert fact["risk_eligible"] is False
    assert blocker in fact["blockers"]
    assert fact["drawdown_amount_usdt"] is None
    assert fact["drawdown_ratio"] is None


def test_same_snapshot_is_idempotent_but_conflicting_reuse_is_rejected() -> None:
    current = _advance(_baseline(), equity="99", snapshot=SNAPSHOT_1, minutes=1)
    same = advance_account_drawdown_fact(
        previous=current,
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=SNAPSHOT_1,
        observed_at_utc=T0 + timedelta(minutes=1),
        reference_time_utc=T0 + timedelta(minutes=1),
        equity_usdt="99",
        external_cashflow_complete=True,
        external_cashflow_usdt="0",
    )
    assert same == current
    conflict = advance_account_drawdown_fact(
        previous=current,
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=SNAPSHOT_1,
        observed_at_utc=T0 + timedelta(minutes=1),
        reference_time_utc=T0 + timedelta(minutes=1),
        equity_usdt="98",
        external_cashflow_complete=True,
        external_cashflow_usdt="0",
    )
    assert conflict["risk_eligible"] is False
    assert "snapshot_idempotency_conflict" in conflict["blockers"]


def test_first_runtime_snapshot_is_not_silently_authorized_as_baseline() -> None:
    fact = build_unknown_account_drawdown_fact(
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=SNAPSHOT_0,
        observed_at_utc=T0,
        equity_usdt="100",
        blockers=("explicit_baseline_required", "external_cashflow_unknown"),
    )
    assert fact["risk_eligible"] is False
    assert fact["baseline_authority"] == ""
    assert fact["peak_equity_usdt"] is None
    assert fact["history_complete"] is False


def _commit(store: BTCRuntimeStore, *, key: str, equity: str, fact: dict) -> dict:
    state = {
        "runtime": {"opening_allowed": False},
        "account_risk_facts": fact,
    }
    return store.commit_ledger_uow(
        idempotency_key=key,
        timestamp_utc="2026-09-13T00:00:00Z",
        run_id="fixture-account-facts",
        order={"orders": []},
        fills=[],
        position={"positions": [], "signed_contracts": "0"},
        cash={"equity_usdt": equity},
        funding={"bills": [], "cashflow": "0", "cashflow_reconciled": True},
        risk_context={
            "mark_price": "60000",
            "index_price": "60000",
            "liquidation_buffer_bps": "not_applicable_flat_position",
            "venue_rules": {
                "instrument_id": "BTC-USDT-SWAP",
                "contract_value_btc": "0.01",
            },
        },
        account_drawdown_fact=fact,
        state_after=state,
        safety=SAFETY,
    )


def _commit_with_fact_presence(
    store: BTCRuntimeStore,
    *,
    state_fact: dict | None,
    payload_fact: dict | None,
    include_payload_field: bool,
) -> dict:
    state = {"runtime": {"opening_allowed": False}}
    if state_fact is not None:
        state["account_risk_facts"] = state_fact
    kwargs = {
        "idempotency_key": "ledger-presence",
        "timestamp_utc": "2026-09-13T00:00:00Z",
        "run_id": "fixture-account-facts",
        "order": {"orders": []},
        "fills": [],
        "position": {"positions": [], "signed_contracts": "0"},
        "cash": {"equity_usdt": "100"},
        "funding": {"bills": [], "cashflow": "0", "cashflow_reconciled": True},
        "risk_context": {
            "mark_price": "60000",
            "index_price": "60000",
            "liquidation_buffer_bps": "not_applicable_flat_position",
            "venue_rules": {
                "instrument_id": "BTC-USDT-SWAP",
                "contract_value_btc": "0.01",
            },
        },
        "state_after": state,
        "safety": SAFETY,
    }
    if include_payload_field:
        kwargs["account_drawdown_fact"] = payload_fact
    return store.commit_ledger_uow(**kwargs)


def test_ledger_uow_requires_bidirectional_payload_state_fact_parity(
    tmp_path,
) -> None:
    store = BTCRuntimeStore(tmp_path)
    first = _commit(store, key="ledger-1", equity="100", fact=_baseline())
    assert first["payload"]["account_drawdown_fact"] == _baseline()
    assert first["state_after"]["account_risk_facts"] == _baseline()
    assert BTCRuntimeStore(tmp_path).recover().state["account_risk_facts"] == _baseline()

    changed = _advance(_baseline(), equity="90", snapshot=SNAPSHOT_1, minutes=1)
    with pytest.raises(BTCRuntimeStoreError, match="idempotency_conflict"):
        _commit(store, key="ledger-1", equity="100", fact=changed)

    state_only = BTCRuntimeStore(tmp_path / "state-only")
    with pytest.raises(
        BTCRuntimeStoreError,
        match="btc_runtime_account_drawdown_fact_state_mismatch",
    ):
        _commit_with_fact_presence(
            state_only,
            state_fact=_baseline(),
            payload_fact=None,
            include_payload_field=False,
        )
    state_only_recovery = BTCRuntimeStore(tmp_path / "state-only").recover()
    assert state_only_recovery.events == ()
    assert "account_risk_facts" not in state_only_recovery.state

    payload_only = BTCRuntimeStore(tmp_path / "payload-only")
    with pytest.raises(
        BTCRuntimeStoreError,
        match="btc_runtime_account_drawdown_fact_state_mismatch",
    ):
        _commit_with_fact_presence(
            payload_only,
            state_fact=None,
            payload_fact=_baseline(),
            include_payload_field=True,
        )

    legacy = BTCRuntimeStore(tmp_path / "legacy")
    legacy_event = _commit_with_fact_presence(
        legacy,
        state_fact=None,
        payload_fact=None,
        include_payload_field=False,
    )
    assert "account_drawdown_fact" not in legacy_event["payload"]
    assert "account_risk_facts" not in legacy_event["state_after"]


def test_checkpoint_behind_and_truncated_tail_restore_last_complete_fact_fail_closed(
    tmp_path,
) -> None:
    store = BTCRuntimeStore(tmp_path)
    baseline = _baseline()
    _commit(store, key="ledger-1", equity="100", fact=baseline)
    store.checkpoint({"account_risk_facts": baseline})
    down = _advance(baseline, equity="90", snapshot=SNAPSHOT_1, minutes=1)
    _commit(store, key="ledger-2", equity="90", fact=down)
    recovered = BTCRuntimeStore(tmp_path).recover()
    assert recovered.blockers == ()
    assert recovered.state["account_risk_facts"] == down

    with store.events_path.open("ab") as handle:
        handle.write(b'{"sequence":3')
    truncated = BTCRuntimeStore(tmp_path).recover()
    assert truncated.state["account_risk_facts"] == down
    assert "btc_runtime_event_log_truncated_tail" in truncated.blockers


def _runtime_snapshot(
    *,
    equity: str,
    observed_at: datetime,
    positions: list[dict] | None = None,
    fills: list[dict] | None = None,
    bills: list[dict] | None = None,
    cashflow_coverage_start: datetime | None = None,
) -> dict:
    snapshot = {
        "captured_at_utc": observed_at.isoformat(),
        "account": {
            "identity": {
                "hash": ACCOUNT,
                "source": "okx_demo_account_config_uid_main_uid",
                "captured_at_utc": observed_at.isoformat(),
            }
        },
        "balance": {
            "equity_usdt": equity,
            "unrealized_pnl_usdt": "0",
            "unrealized_pnl_observed": True,
        },
        "positions": list(positions or []),
        "pending_orders": [],
        "pending_algo_orders": [],
        "orders": [],
        "fills": list(fills or []),
        "bills": list(bills or []),
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "60000"},
        "instrument": {
            "instrument_id": "BTC-USDT-SWAP",
            "contract_value_btc": "0.01",
            "tick_size": "0.1",
            "lot_size": "0.01",
            "minimum_size": "0.01",
        },
    }
    snapshot_hash = canonical_ledger_snapshot_sha256(snapshot)
    snapshot["account_cashflow_evidence"] = build_okx_account_cashflow_evidence(
        pages=[
            {
                "request": {
                    "begin": str(
                        int(
                            (cashflow_coverage_start or observed_at).timestamp()
                            * 1000
                        )
                    ),
                    "end": str(int(observed_at.timestamp() * 1000)),
                    "limit": "100",
                },
                "rows": [],
            }
        ],
        account_identity_hash=ACCOUNT,
        snapshot_sha256=snapshot_hash,
        coverage_start_utc=cashflow_coverage_start or observed_at,
        coverage_end_utc=observed_at,
        reference_time_utc=observed_at,
    )
    return snapshot


def _runtime_controller(tmp_path, now: list[datetime]) -> OkxDemoPaperRuntimeController:
    return OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "runtime",
        ),
        credential_loader=lambda _service: (_ for _ in ()).throw(
            AssertionError("credential_loader_not_allowed")
        ),
        clock=lambda: now[0],
        start_worker=False,
    )


def test_actual_runtime_uow_persists_recovers_and_blocks_forged_economic_state(
    tmp_path,
) -> None:
    now = [T0]
    controller = _runtime_controller(tmp_path, now)
    baseline_snapshot = _runtime_snapshot(equity="100", observed_at=T0)
    baseline = build_explicit_account_drawdown_baseline(
        authority="explicit_reviewed_account_baseline_v1",
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=canonical_ledger_snapshot_sha256(baseline_snapshot),
        observed_at_utc=T0,
        equity_usdt="100",
        history_complete=False,
        baseline_event_sequence=0,
    )
    controller._state["account_risk_facts"] = baseline
    controller._state["account_risk_last_valid_fact"] = baseline
    controller._apply_snapshot(baseline_snapshot)
    controller._commit_ledger_reconciliation(
        snapshot=baseline_snapshot,
        trigger="engineering_baseline",
    )
    assert controller.status()["account_risk_facts"]["risk_eligible"] is True
    recovered = BTCRuntimeStore(tmp_path / "runtime").recover()
    assert recovered.blockers == ()
    assert recovered.state["account_risk_facts"]["peak_equity_usdt"] == "100"
    assert recovered.events[-1]["payload"]["account_drawdown_fact"] == baseline

    restarted = _runtime_controller(tmp_path, now)
    assert restarted.status()["account_risk_facts"]["peak_equity_usdt"] == "100"
    now[0] = T0 + timedelta(minutes=1)
    forged = _runtime_snapshot(
        equity="90",
        observed_at=now[0],
        cashflow_coverage_start=T0,
    )
    restarted._apply_snapshot(forged)
    restarted._commit_ledger_reconciliation(
        snapshot=forged,
        trigger="engineering_forged_snapshot",
    )
    status = restarted.status()
    assert status["ledger_reconciliation"]["status"] == "mismatch"
    assert status["ledger_reconciliation"]["account_ledger_replay"]["reconciled"] is False
    assert status["account_risk_facts"]["risk_eligible"] is False
    assert status["account_risk_last_valid_fact"]["equity_usdt"] == "100"
    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True

    position_root = tmp_path / "wrong-position"
    position_now = [T0]
    position_controller = _runtime_controller(position_root, position_now)
    flat_snapshot = _runtime_snapshot(equity="100", observed_at=T0)
    position_baseline = build_explicit_account_drawdown_baseline(
        authority="explicit_reviewed_account_baseline_v1",
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=canonical_ledger_snapshot_sha256(flat_snapshot),
        observed_at_utc=T0,
        equity_usdt="100",
        history_complete=False,
        baseline_event_sequence=0,
    )
    position_controller._state["account_risk_facts"] = position_baseline
    position_controller._state["account_risk_last_valid_fact"] = position_baseline
    position_controller._apply_snapshot(flat_snapshot)
    position_controller._commit_ledger_reconciliation(
        snapshot=flat_snapshot,
        trigger="engineering_position_baseline",
    )
    position_now[0] = T0 + timedelta(minutes=1)
    forged_position = _runtime_snapshot(
        equity="100",
        observed_at=position_now[0],
        cashflow_coverage_start=T0,
        positions=[
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
                "liquidation_price": "30000",
                "unrealized_pnl": "0",
                "realized_pnl": "0",
            }
        ],
    )
    position_controller._apply_snapshot(forged_position)
    position_controller._commit_ledger_reconciliation(
        snapshot=forged_position,
        trigger="engineering_forged_position_snapshot",
    )
    position_status = position_controller.status()
    assert position_status["ledger_reconciliation"]["status"] == "mismatch"
    assert (
        "account_ledger_replay_failed:position_reconciliation_mismatch"
        in position_status["ledger_reconciliation"]["account_ledger_replay"]["blockers"]
    )
    assert position_status["runtime"]["opening_allowed"] is False
    assert position_status["runtime"]["cancel_only"] is True
    assert position_status["account_risk_facts"]["risk_eligible"] is False
    assert position_status["account_risk_last_valid_fact"]["equity_usdt"] == "100"


def test_runtime_records_later_identical_economics_and_retry_is_idempotent(
    tmp_path,
) -> None:
    now = [T0 - timedelta(minutes=1)]
    controller = _runtime_controller(tmp_path, now)
    baseline_snapshot = _runtime_snapshot(
        equity="100",
        observed_at=now[0],
    )
    baseline = build_explicit_account_drawdown_baseline(
        authority="explicit_reviewed_account_baseline_v1",
        account_identity_hash=ACCOUNT,
        account_scope="dedicated_demo_account",
        currency="USDT",
        snapshot_sha256=canonical_ledger_snapshot_sha256(baseline_snapshot),
        observed_at_utc=now[0],
        equity_usdt="100",
        history_complete=False,
        baseline_event_sequence=0,
    )
    controller._state["account_risk_facts"] = baseline
    controller._state["account_risk_last_valid_fact"] = baseline
    controller._apply_snapshot(baseline_snapshot)
    controller._commit_ledger_reconciliation(
        snapshot=baseline_snapshot,
        trigger="engineering_poll_baseline",
    )

    fills = [
        {
            "fill_id": "fill-open",
            "order_id": "order-open",
            "side": "buy",
            "price": "60000",
            "size": "0.01",
            "fee": "-0.003",
            "fee_currency": "USDT",
            "timestamp_ms": str(
                int((T0 - timedelta(seconds=30)).timestamp() * 1000)
            ),
        },
        {
            "fill_id": "fill-close",
            "order_id": "order-close",
            "side": "sell",
            "price": "61000",
            "size": "0.01",
            "fee": "-0.00305",
            "fee_currency": "USDT",
            "timestamp_ms": str(
                int((T0 - timedelta(seconds=15)).timestamp() * 1000)
            ),
        },
    ]
    bills = [
        {
            "bill_id": "funding-1",
            "instrument_id": "BTC-USDT-SWAP",
            "type": "8",
            "sub_type": "173",
            "balance_change": "-0.001",
            "balance_change_observed": True,
            "currency": "USDT",
            "timestamp_ms": str(
                int((T0 - timedelta(seconds=10)).timestamp() * 1000)
            ),
        }
    ]
    now[0] = T0
    first_poll = _runtime_snapshot(
        equity="100.09295",
        observed_at=now[0],
        fills=fills,
        bills=bills,
        cashflow_coverage_start=T0 - timedelta(minutes=1),
    )
    controller._apply_snapshot(first_poll)
    controller._commit_ledger_reconciliation(
        snapshot=first_poll,
        trigger="engineering_identical_economics_poll",
    )

    now[0] = T0 + timedelta(minutes=1)
    later_poll = _runtime_snapshot(
        equity="100.09295",
        observed_at=now[0],
        fills=fills,
        bills=bills,
        cashflow_coverage_start=T0,
    )
    assert canonical_ledger_snapshot_sha256(later_poll) == canonical_ledger_snapshot_sha256(first_poll)
    controller._apply_snapshot(later_poll)
    controller._commit_ledger_reconciliation(
        snapshot=later_poll,
        trigger="engineering_identical_economics_poll",
    )
    status = controller.status()
    assert status["account_risk_facts"]["observed_at_utc"] == "2026-09-13T00:01:00Z"
    assert status["ledger_reconciliation"]["account_ledger_replay"]["fill_count"] == 2
    assert status["ledger_reconciliation"]["account_ledger_replay"]["funding_bill_count"] == 1
    assert status["ledger_reconciliation"]["account_ledger_replay"]["final_equity_usdt"] == "100.09295"

    controller._commit_ledger_reconciliation(
        snapshot=later_poll,
        trigger="engineering_identical_economics_poll",
    )
    recovered = BTCRuntimeStore(tmp_path / "runtime").recover()
    assert recovered.blockers == ()
    assert len(recovered.events) == 3
    assert recovered.events[-2]["idempotency_key"] != recovered.events[-1]["idempotency_key"]


def _guardian_observation(
    fact: dict,
    *,
    observed_at: datetime | None = None,
) -> GuardianObservation:
    now = observed_at or T0 + timedelta(minutes=1)
    return GuardianObservation(
        source_head="c" * 40,
        account_identity=ACCOUNT,
        account_snapshot_sha256=SNAPSHOT_1,
        session_id="fixture-session",
        key_namespace="fixture-key",
        client_order_namespace="fixture-order",
        owner_identity="fixture-owner",
        epoch=1,
        observed_at_utc=now,
        reference_time_utc=now,
        heartbeat_at_utc=now,
        heartbeat_healthy=True,
        broker_truth={"fresh": True},
        broker_truth_fresh=True,
        facts_fresh=True,
        reconciliation={"passed": True},
        reconciliation_passed=True,
        ledger_reconciled=True,
        snapshot_match=True,
        funding_reconciled=True,
        positions={"total": 0, "consistent": True},
        cash={"equity": 99, "consistent": True},
        pnl={"daily": 0, "consistent": True},
        exposure={"total": 0, "consistent": True},
        open_orders=[],
        protection_facts={"consistent": True},
        account_facts={"account_drawdown": fact},
        positions_consistent=True,
        cash_consistent=True,
        pnl_consistent=True,
        exposure_consistent=True,
        open_orders_consistent=True,
        protection_consistent=True,
        account_equity=99,
        total_exposure=0,
        daily_pnl=0,
        drawdown=0,
        open_order_count=0,
        evidence_identity="btc_account_fact_fixture",
    )


def test_guardian_requires_explicit_drawdown_unit_and_ignores_legacy_bare_value() -> None:
    fact = _advance(_baseline(), equity="90", snapshot=SNAPSHOT_1, minutes=1)
    unknown = RuntimeRiskGuardian(
        GuardianConfig(
            max_abs_exposure=1,
            max_daily_loss=1,
            max_drawdown=1,
            max_open_orders=0,
        )
    ).evaluate(_guardian_observation(fact))
    assert unknown.status is GuardianStatus.TRIPPED
    assert "max_drawdown_unit_unknown" in unknown.reason_codes

    amount = RuntimeRiskGuardian(
        GuardianConfig(
            max_abs_exposure=1,
            max_daily_loss=1,
            max_drawdown=9,
            max_drawdown_unit="usdt",
            max_open_orders=0,
        )
    ).evaluate(_guardian_observation(fact))
    assert "max_drawdown_breach" in amount.reason_codes
    ratio = RuntimeRiskGuardian(
        GuardianConfig(
            max_abs_exposure=1,
            max_daily_loss=1,
            max_drawdown=0.11,
            max_drawdown_unit="ratio",
            max_open_orders=0,
        )
    ).evaluate(_guardian_observation(fact))
    assert ratio.status is GuardianStatus.PASS


def test_guardian_rejects_old_fact_when_same_snapshot_hash_is_reobserved_later() -> None:
    old_fact = _advance(
        _baseline(),
        equity="99",
        snapshot=SNAPSHOT_1,
        minutes=1,
    )
    decision = RuntimeRiskGuardian(
        GuardianConfig(
            max_abs_exposure=1,
            max_daily_loss=1,
            max_drawdown=20,
            max_drawdown_unit="usdt",
            max_open_orders=0,
        )
    ).evaluate(
        _guardian_observation(
            old_fact,
            observed_at=T0 + timedelta(minutes=2),
        )
    )
    assert decision.status is GuardianStatus.TRIPPED
    assert "drawdown_fact_observation_mismatch" in decision.reason_codes
    assert "drawdown_unknown" in decision.reason_codes


def _ledger_event_payload(
    *,
    fill_id: str,
    side: str,
    price: str,
    fee: str,
    bill_id: str = "",
    funding: str = "0",
) -> dict:
    bills = (
        [
            {
                "bill_id": bill_id,
                "balance_change": funding,
                "balance_change_observed": True,
                "currency": "USDT",
                "timestamp_ms": "1789257600000",
            }
        ]
        if bill_id
        else []
    )
    return {
        "fill_ledger": [
            {
                "fill_id": fill_id,
                "side": side,
                "price": price,
                "size": "0.01",
                "fee": fee,
                "fee_currency": "USDT",
                "timestamp_ms": "1789257600000",
            }
        ],
        "funding_ledger": {"bills": bills},
        "risk_context": {
            "mark_price": "61000",
            "venue_rules": {"contract_value_btc": "0.01"},
        },
    }


def test_independent_ledger_replay_dedupes_uow_rows_and_rejects_self_consistent_forgery() -> None:
    open_payload = _ledger_event_payload(
        fill_id="fill-open", side="buy", price="60000", fee="-0.003"
    )
    close_payload = _ledger_event_payload(
        fill_id="fill-close",
        side="sell",
        price="61000",
        fee="-0.00305",
        bill_id="funding-1",
        funding="-0.001",
    )
    uows = [open_payload, open_payload, close_payload]
    expected_equity = Decimal("100.09295")
    final_snapshot = {
        "balance": {"equity_usdt": str(expected_equity)},
        "positions": [],
        "mark": {"mark_price": "61000"},
    }
    replay = replay_account_ledger_uows(
        uow_payloads=uows,
        baseline_equity_usdt="100",
        baseline_observed_at_utc=T0 - timedelta(minutes=1),
        final_observed_at_utc=T0,
        final_exchange_snapshot=final_snapshot,
        currency="USDT",
    )
    assert replay["reconciled"] is True
    assert replay["fill_count"] == 2
    assert replay["funding_bill_count"] == 1
    assert replay["position_contracts"] == "0"
    assert replay["final_equity_usdt"] == str(expected_equity)

    forged = json.loads(json.dumps(final_snapshot))
    forged["balance"]["equity_usdt"] = "101"
    with pytest.raises(AccountRiskFactError, match="equity_reconciliation_mismatch"):
        replay_account_ledger_uows(
            uow_payloads=uows,
            baseline_equity_usdt="100",
            baseline_observed_at_utc=T0 - timedelta(minutes=1),
            final_observed_at_utc=T0,
            final_exchange_snapshot=forged,
            currency="USDT",
        )
