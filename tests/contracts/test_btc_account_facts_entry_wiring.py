from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.application.btc_demo_production_composition import (
    canonical_ledger_snapshot_sha256,
)
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
    AccountRiskFactError,
    build_okx_account_cashflow_evidence,
    load_reviewed_account_facts_approval,
    replay_account_ledger_uows,
    reviewed_account_facts_approval_digest,
    validate_account_cashflow_evidence,
)
from quant_crypto.oms.okx_demo import OkxDemoResponse
from quant_crypto.oms.okx_demo_paper_runtime import (
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
    collect_okx_account_cashflow_evidence,
)
from quant_crypto.oms.runtime_store import BTCRuntimeStore


UTC = timezone.utc
T0 = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
ACCOUNT = "a" * 64
SOURCE_HEAD = "b" * 40
RUNTIME_IDENTITY = "btc-demo-runtime:account-facts-entry-test"


def _snapshot(
    *,
    observed_at: datetime = T0,
    equity: str = "100",
    positions: list[dict] | None = None,
    pending_orders: list[dict] | None = None,
    pending_algos: list[dict] | None = None,
    fills: list[dict] | None = None,
    bills: list[dict] | None = None,
) -> dict:
    return {
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
        "pending_orders": list(pending_orders or []),
        "pending_algo_orders": list(pending_algos or []),
        "orders": [],
        "fills": list(fills or []),
        "bills": list(bills or []),
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "60000"},
        "instrument": {
            "instrument_id": "BTC-USDT-SWAP",
            "contract_value_btc": "0.01",
        },
    }


def _approval(snapshot: dict, *, approval_id: str = "approval-20260913-001") -> dict:
    snapshot_sha256 = canonical_ledger_snapshot_sha256(snapshot)
    record = {
        "schema_version": "btc_account_facts_approval_v1",
        "approval_id": approval_id,
        "status": "approved",
        "reviewer_identity": "human-reviewer-1",
        "approval_ticket": "BTC-ACCOUNT-FACTS-BASELINE-20260913",
        "reviewed_at_utc": T0.isoformat(),
        "account_identity_hash": ACCOUNT,
        "account_scope": "dedicated_demo_account",
        "currency": "USDT",
        "source_head": SOURCE_HEAD,
        "runtime_identity": RUNTIME_IDENTITY,
        "snapshot_sha256": snapshot_sha256,
        "observed_at_utc": snapshot["captured_at_utc"],
        "equity_usdt": snapshot["balance"]["equity_usdt"],
        "history_complete": False,
        "baseline_authority": ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
        "flatness_evidence": {
            "schema_version": "btc_reviewed_account_flatness_v1",
            "scope": "dedicated_trading_account_account_wide",
            "positions_complete": True,
            "pending_orders_complete": True,
            "pending_algo_orders_complete": True,
            "pending_intents_complete": True,
            "snapshot_sha256": snapshot_sha256,
        },
        "drawdown_policy": {
            "schema_version": "btc_reviewed_drawdown_policy_v1",
            "value": "10",
            "unit": "usdt",
        },
    }
    record["approval_digest"] = reviewed_account_facts_approval_digest(record)
    return record


def _write_registry(path: Path, record: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_account_facts_approval_registry_v1",
                "records": [record],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _controller(
    tmp_path: Path,
    *,
    resolver=None,
    approval_id: str = "approval-20260913-001",
    snapshot: dict | None = None,
) -> OkxDemoPaperRuntimeController:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    # Production uses git HEAD; the test owns an exact, injected equivalent.
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=repo,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path / "runtime",
            runtime_identity=RUNTIME_IDENTITY,
            account_facts_approval_resolver=resolver,
            account_facts_approval_id=approval_id if resolver is not None else "",
        ),
        credential_loader=lambda _service: (_ for _ in ()).throw(
            AssertionError("credential_loader_not_allowed")
        ),
        clock=lambda: T0,
        start_worker=False,
    )
    controller._source_head_for_account_facts = lambda: SOURCE_HEAD  # type: ignore[method-assign]
    if snapshot is not None:
        controller._set_authoritative_account_identity(  # type: ignore[attr-defined]
            snapshot["account"]["identity"]
        )
    return controller


def _resolver(record: dict):
    return lambda approval_id: dict(record) if approval_id == record["approval_id"] else None


def test_registration_requires_server_owned_resolver_and_rejects_body_self_approval(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    with pytest.raises(AccountRiskFactError, match="approval_resolver_missing"):
        _controller(tmp_path).register_reviewed_account_drawdown_baseline(
            approval_id="self-approved",
            snapshot={
                **snapshot,
                "authority": ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
                "approved": True,
                "complete": True,
            },
        )

    record = _approval(snapshot)
    controller = _controller(tmp_path / "bound", resolver=_resolver(record))
    with pytest.raises(AccountRiskFactError, match="snapshot_self_approval_forbidden"):
        controller.register_reviewed_account_drawdown_baseline(
            approval_id=record["approval_id"],
            snapshot={**snapshot, "approved": True},
        )


def test_registration_rejects_unreviewed_account_scope_and_stale_snapshot(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    missing_scope = _approval(snapshot)
    missing_scope["flatness_evidence"] = {
        **missing_scope["flatness_evidence"],
        "positions_complete": False,
    }
    missing_scope["approval_digest"] = reviewed_account_facts_approval_digest(
        missing_scope
    )
    with pytest.raises(
        AccountRiskFactError,
        match="approval_account_wide_flatness_unproven",
    ):
        _controller(
            tmp_path / "scope",
            resolver=_resolver(missing_scope),
        ).register_reviewed_account_drawdown_baseline(
            approval_id=missing_scope["approval_id"],
            snapshot=snapshot,
        )

    stale_snapshot = _snapshot(observed_at=T0 - timedelta(seconds=31))
    stale_approval = _approval(stale_snapshot)
    with pytest.raises(AccountRiskFactError, match="baseline_observation_stale"):
        _controller(
            tmp_path / "stale",
            resolver=_resolver(stale_approval),
        ).register_reviewed_account_drawdown_baseline(
            approval_id=stale_approval["approval_id"],
            snapshot=stale_snapshot,
        )

@pytest.mark.parametrize(
    "snapshot_change, pending_intent, error",
    [
        ({"positions": [{"position_side": "long", "contracts": "0.01"}]}, False, "baseline_account_not_flat"),
        (
            {
                "positions": [
                    {"position_side": "long", "contracts": "0.01"},
                    {"position_side": "short", "contracts": "0.01"},
                ]
            },
            False,
            "baseline_account_not_flat",
        ),
        (
            {"pending_orders": [{"order_id": "order-1"}]},
            False,
            "baseline_pending_orders_present",
        ),
        (
            {"pending_algos": [{"algo_id": "algo-1"}]},
            False,
            "baseline_pending_algo_orders_present",
        ),
        ({}, True, "baseline_pending_order_intents_present"),
    ],
)
def test_registration_rejects_nonflat_pending_and_old_intents(
    tmp_path: Path,
    snapshot_change: dict,
    pending_intent: bool,
    error: str,
) -> None:
    snapshot = _snapshot(**snapshot_change)
    record = _approval(snapshot)
    controller = _controller(tmp_path, resolver=_resolver(record))
    if pending_intent:
        controller._state["risk_control"]["pending_order_intents"] = {"old": {"status": "pending"}}
    with pytest.raises(AccountRiskFactError, match=error):
        controller.register_reviewed_account_drawdown_baseline(
            approval_id=record["approval_id"], snapshot=snapshot
        )


def test_registration_binds_exact_identity_snapshot_time_source_and_runtime(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    base = _approval(snapshot)
    changes = {
        "account_identity_hash": "c" * 64,
        "currency": "USD",
        "source_head": "d" * 40,
        "runtime_identity": "another-runtime",
        "snapshot_sha256": "e" * 64,
        "observed_at_utc": (T0 + timedelta(minutes=1)).isoformat(),
    }
    for field, value in changes.items():
        record = {**base, field: value}
        record["approval_digest"] = reviewed_account_facts_approval_digest(record)
        controller = _controller(tmp_path / field, resolver=_resolver(record))
        with pytest.raises(AccountRiskFactError, match="approval_"):
            controller.register_reviewed_account_drawdown_baseline(
                approval_id=record["approval_id"], snapshot=snapshot
            )


def test_formal_registration_is_append_only_recoverable_idempotent_and_no_reset(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    record = _approval(snapshot)
    controller = _controller(tmp_path, resolver=_resolver(record))
    before = controller.status()
    first = controller.register_reviewed_account_drawdown_baseline(
        approval_id=record["approval_id"], snapshot=snapshot
    )
    second = controller.register_reviewed_account_drawdown_baseline(
        approval_id=record["approval_id"], snapshot=snapshot
    )
    assert second["status"] == "already_registered"
    assert second["account_drawdown_fact"] == first["account_drawdown_fact"]
    assert second["reviewed_approval"] == first["reviewed_approval"]
    assert first["account_drawdown_fact"]["status"] == "known_since_explicit_baseline"
    assert first["account_drawdown_fact"]["history_complete"] is False
    recovered = BTCRuntimeStore(tmp_path / "runtime").recover()
    assert recovered.blockers == ()
    assert recovered.state["account_risk_facts"] == first["account_drawdown_fact"]
    assert recovered.events[-1]["payload"]["account_drawdown_fact"] == recovered.state["account_risk_facts"]
    assert recovered.events[-1]["payload"]["reviewed_approval"] == recovered.state["account_facts_approval"]
    assert len(recovered.events) == 1
    restarted = _controller(tmp_path, resolver=_resolver(record))
    assert restarted.status()["account_risk_facts"] == first["account_drawdown_fact"]
    assert restarted.status()["account_facts_approval"] == first["reviewed_approval"]
    after = controller.status()
    assert after["runtime"]["opening_allowed"] == before["runtime"]["opening_allowed"] is False
    assert after["risk_control"]["mode"] == before["risk_control"]["mode"]
    assert after["safety"] == before["safety"]

    newer = _snapshot(observed_at=T0, equity="101")
    replacement = _approval(newer, approval_id="approval-20260913-002")
    controller.config = OkxDemoPaperRuntimeConfig(
        repo_root=controller.config.repo_root,
        data_db_path=controller.config.data_db_path,
        output_dir=controller.config.output_dir,
        runtime_identity=RUNTIME_IDENTITY,
        account_facts_approval_resolver=_resolver(replacement),
        account_facts_approval_id=replacement["approval_id"],
    )
    with pytest.raises(AccountRiskFactError, match="baseline_already_registered"):
        controller.register_reviewed_account_drawdown_baseline(
            approval_id=replacement["approval_id"], snapshot=newer
        )


def test_formal_baseline_excludes_prebaseline_economics_on_commit_retry_and_restart(
    tmp_path: Path,
) -> None:
    before = T0 - timedelta(minutes=1)
    before_ms = str(int(before.timestamp() * 1000))
    snapshot = _snapshot(
        fills=[
            {
                "fill_id": "historical-open",
                "order_id": "historical-open-order",
                "side": "buy",
                "price": "60000",
                "size": "0.01",
                "fee": "-0.1",
                "fee_currency": "USDT",
                "timestamp_ms": before_ms,
            },
            {
                "fill_id": "historical-close",
                "order_id": "historical-close-order",
                "side": "sell",
                "price": "60000",
                "size": "0.01",
                "fee": "-0.1",
                "fee_currency": "USDT",
                "timestamp_ms": before_ms,
            },
        ],
        bills=[
            {
                "bill_id": "historical-funding",
                "type": "8",
                "sub_type": "173",
                "balance_change": "-0.05",
                "balance_change_observed": True,
                "currency": "USDT",
                "timestamp_ms": before_ms,
            }
        ],
    )
    record = _approval(snapshot)
    controller = _controller(tmp_path, resolver=_resolver(record))
    controller.register_reviewed_account_drawdown_baseline(
        approval_id=record["approval_id"],
        snapshot=snapshot,
    )
    snapshot_hash = canonical_ledger_snapshot_sha256(snapshot)
    snapshot["account_cashflow_evidence"] = build_okx_account_cashflow_evidence(
        pages=[
            {
                "request": {
                    "begin": str(int(T0.timestamp() * 1000)),
                    "end": str(int(T0.timestamp() * 1000)),
                    "limit": "100",
                },
                "rows": [],
            }
        ],
        account_identity_hash=ACCOUNT,
        snapshot_sha256=snapshot_hash,
        coverage_start_utc=T0,
        coverage_end_utc=T0,
        reference_time_utc=T0,
    )
    controller._apply_snapshot(snapshot)  # type: ignore[attr-defined]
    controller._commit_ledger_reconciliation(  # type: ignore[attr-defined]
        snapshot=snapshot,
        trigger="reviewed_baseline_first_snapshot",
    )
    first = controller.status()
    assert first["account_risk_facts"]["risk_eligible"] is True
    assert first["account_risk_facts"]["equity_usdt"] == "100"
    assert first["ledger_reconciliation"]["account_ledger_replay"]["fill_count"] == 0
    assert first["ledger_reconciliation"]["account_ledger_replay"]["funding_bill_count"] == 0
    assert first["ledger_reconciliation"]["account_ledger_replay"]["final_equity_usdt"] == "100"

    controller._commit_ledger_reconciliation(  # type: ignore[attr-defined]
        snapshot=snapshot,
        trigger="reviewed_baseline_first_snapshot",
    )
    restarted = _controller(tmp_path, resolver=_resolver(record))
    recovered = restarted.status()
    assert recovered["account_risk_facts"]["risk_eligible"] is True
    assert recovered["ledger_reconciliation"]["account_ledger_replay"]["final_equity_usdt"] == "100"


@pytest.mark.parametrize("timestamp_ms", ["", str(int((T0 + timedelta(seconds=1)).timestamp() * 1000))])
def test_ledger_replay_rejects_missing_or_future_economic_timestamp(
    timestamp_ms: str,
) -> None:
    payload = {
        "fill_ledger": [
            {
                "fill_id": "unbounded-fill",
                "side": "buy",
                "price": "60000",
                "size": "0.01",
                "fee": "0",
                "fee_currency": "USDT",
                "timestamp_ms": timestamp_ms,
            }
        ],
        "funding_ledger": {"bills": []},
        "risk_context": {
            "venue_rules": {"contract_value_btc": "0.01"},
        },
    }
    expected = "fill_timestamp_invalid" if not timestamp_ms else "fill_timestamp_after_observation"
    with pytest.raises(AccountRiskFactError, match=expected):
        replay_account_ledger_uows(
            uow_payloads=[payload],
            baseline_equity_usdt="100",
            baseline_observed_at_utc=T0 - timedelta(minutes=1),
            final_observed_at_utc=T0,
            final_exchange_snapshot={
                "balance": {"equity_usdt": "100"},
                "positions": [],
                "mark": {"mark_price": "60000"},
            },
            currency="USDT",
        )


def _bill(
    bill_id: int,
    *,
    ts: datetime,
    bill_type: str = "8",
    subtype: str = "173",
    change: str = "0",
) -> dict:
    return {
        "billId": str(bill_id),
        "type": bill_type,
        "subType": subtype,
        "ts": str(int(ts.timestamp() * 1000)),
        "balChg": change,
        "ccy": "USDT",
    }


def _page(rows: list[dict], *, after: str = "", begin: datetime = T0, end: datetime | None = None) -> dict:
    finish = end or (T0 + timedelta(hours=1))
    request = {
        "begin": str(int(begin.timestamp() * 1000)),
        "end": str(int(finish.timestamp() * 1000)),
        "limit": "100",
    }
    if after:
        request["after"] = after
    return {
        "request": request,
        "rows": rows,
    }


def test_cashflow_coverage_rejects_offsetting_transfers_and_unknown_rows() -> None:
    end = T0 + timedelta(hours=1)
    offsetting = build_okx_account_cashflow_evidence(
        pages=[
            _page(
                [
                    _bill(2, ts=end, bill_type="1", subtype="11", change="100"),
                    _bill(1, ts=T0, bill_type="1", subtype="12", change="-100"),
                ]
            )
        ],
        account_identity_hash=ACCOUNT,
        snapshot_sha256="f" * 64,
        coverage_start_utc=T0,
        coverage_end_utc=end,
        reference_time_utc=end,
    )
    assert offsetting["complete"] is False
    assert "external_cashflow_activity_detected" in offsetting["blockers"]

    for row in (
        _bill(1, ts=T0, bill_type="999", subtype="999"),
        {"billId": "1", "type": "8", "subType": "", "ts": str(int(T0.timestamp() * 1000)), "balChg": "0", "ccy": "USDT"},
    ):
        unknown = build_okx_account_cashflow_evidence(
            pages=[_page([row])],
            account_identity_hash=ACCOUNT,
            snapshot_sha256="f" * 64,
            coverage_start_utc=T0,
            coverage_end_utc=end,
            reference_time_utc=end,
        )
        assert unknown["complete"] is False
        assert "account_bill_type_unknown" in unknown["blockers"]


def test_cashflow_complete_flag_without_integrity_digest_is_rejected() -> None:
    end = T0 + timedelta(hours=1)
    forged = {
        "schema_version": "btc_account_cashflow_evidence_v1",
        "status": "complete_zero_external_cashflow",
        "complete": True,
        "account_identity_hash": ACCOUNT,
        "account_scope": "dedicated_demo_account",
        "currency": "USDT",
        "snapshot_sha256": "f" * 64,
        "coverage_start_utc": T0.isoformat(),
        "coverage_end_utc": end.isoformat(),
        "amount_usdt": "0",
        "blockers": [],
    }
    with pytest.raises(
        AccountRiskFactError,
        match="account_cashflow_evidence_digest_mismatch",
    ):
        validate_account_cashflow_evidence(
            forged,
            expected_account_identity_hash=ACCOUNT,
            expected_snapshot_sha256="f" * 64,
            expected_coverage_start_utc=T0,
            expected_coverage_end_utc=end,
        )


def test_cashflow_pagination_requires_terminal_page_cursor_progress_and_retention() -> None:
    end = T0 + timedelta(hours=1)
    full = [
        _bill(200 - index, ts=end - timedelta(seconds=index))
        for index in range(100)
    ]
    missing_terminal = build_okx_account_cashflow_evidence(
        pages=[_page(full)],
        account_identity_hash=ACCOUNT,
        snapshot_sha256="f" * 64,
        coverage_start_utc=T0,
        coverage_end_utc=end,
        reference_time_utc=end,
    )
    assert "account_cashflow_terminal_page_missing" in missing_terminal["blockers"]

    complete = build_okx_account_cashflow_evidence(
        pages=[_page(full), _page([], after=full[-1]["billId"])],
        account_identity_hash=ACCOUNT,
        snapshot_sha256="f" * 64,
        coverage_start_utc=T0,
        coverage_end_utc=end,
        reference_time_utc=end,
    )
    assert complete["complete"] is True
    assert complete["amount_usdt"] == "0"

    duplicate = build_okx_account_cashflow_evidence(
        pages=[_page(full), _page([full[-1]], after=full[-1]["billId"])],
        account_identity_hash=ACCOUNT,
        snapshot_sha256="f" * 64,
        coverage_start_utc=T0,
        coverage_end_utc=end,
        reference_time_utc=end,
    )
    assert "account_bill_duplicate" in duplicate["blockers"]

    stale = build_okx_account_cashflow_evidence(
        pages=[_page([], begin=T0 - timedelta(days=8))],
        account_identity_hash=ACCOUNT,
        snapshot_sha256="f" * 64,
        coverage_start_utc=T0 - timedelta(days=8),
        coverage_end_utc=end,
        reference_time_utc=end,
    )
    assert "account_cashflow_coverage_exceeds_okx_7d_window" in stale["blockers"]


class _BillsClient:
    def __init__(self, pages: list[list[dict]]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, dict]] = []

    def private_get(self, path: str, params: dict) -> OkxDemoResponse:
        self.calls.append((path, dict(params)))
        return OkxDemoResponse(
            method="GET",
            path=path,
            http_status=200,
            code="0",
            message="",
            data=tuple(self.pages.pop(0)),
        )


def test_bounded_collector_uses_unfiltered_newest_first_after_pagination() -> None:
    end = T0 + timedelta(hours=1)
    full = [
        _bill(200 - index, ts=end - timedelta(seconds=index))
        for index in range(100)
    ]
    client = _BillsClient([full, []])
    evidence = collect_okx_account_cashflow_evidence(
        client=client,
        account_identity_hash=ACCOUNT,
        snapshot_sha256="f" * 64,
        coverage_start_utc=T0,
        coverage_end_utc=end,
        reference_time_utc=end,
    )
    assert evidence["complete"] is True
    assert client.calls == [
        (
            "/api/v5/account/bills",
            {
                "begin": str(int(T0.timestamp() * 1000)),
                "end": str(int(end.timestamp() * 1000)),
                "limit": "100",
            },
        ),
        (
            "/api/v5/account/bills",
            {
                "begin": str(int(T0.timestamp() * 1000)),
                "end": str(int(end.timestamp() * 1000)),
                "after": full[-1]["billId"],
                "limit": "100",
            },
        ),
    ]
    assert all("instId" not in params and "type" not in params for _, params in client.calls)


def test_registry_must_be_external_and_digest_valid(tmp_path: Path) -> None:
    snapshot = _snapshot()
    record = _approval(snapshot)
    repo = tmp_path / "repo"
    repo.mkdir()
    inside = repo / "approval.json"
    _write_registry(inside, record)
    with pytest.raises(AccountRiskFactError, match="approval_registry_must_be_external"):
        load_reviewed_account_facts_approval(
            registry_path=inside, approval_id=record["approval_id"], repo_root=repo
        )

    outside = tmp_path / "approval.json"
    _write_registry(outside, record)
    assert load_reviewed_account_facts_approval(
        registry_path=outside, approval_id=record["approval_id"], repo_root=repo
    )["approval_digest"] == record["approval_digest"]
    tampered = {**record, "equity_usdt": "101"}
    _write_registry(outside, tampered)
    with pytest.raises(AccountRiskFactError, match="approval_digest_mismatch"):
        load_reviewed_account_facts_approval(
            registry_path=outside, approval_id=record["approval_id"], repo_root=repo
        )
