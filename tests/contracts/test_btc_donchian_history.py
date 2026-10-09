from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

import pytest

from quant_crypto.application.donchian_historical_venue import (
    HistoricalBar,
    HistoricalFundingEvent,
    HistoricalOfflineVenue,
    ProtectionTriggerAmbiguous,
    classify_mark_protection_touch,
)
from quant_crypto.application.donchian_offline_replay import DonchianOfflineReplayConfig
from quant_crypto.application.donchian_historical_replay import (
    DonchianHistoricalReplay,
    _terminal_ledger_required,
)


UTC = timezone.utc


@pytest.mark.parametrize(
    "side,mark,stop,take,expected",
    [
        ("long", "93", "94", "108", (True, False)),
        ("long", "109", "94", "108", (False, True)),
        ("short", "107", "106", "92", (True, False)),
        ("short", "91", "106", "92", (False, True)),
    ],
)
def test_sampled_mark_protection_classifier_has_symmetric_long_short_semantics(
    side: str, mark: str, stop: str, take: str, expected: tuple[bool, bool]
) -> None:
    touch = classify_mark_protection_touch(
        position_side=side,
        mark_open=mark,
        mark_high=mark,
        mark_low=mark,
        stop_trigger=stop,
        take_trigger=take,
    )

    assert (touch.stop_hit, touch.take_hit) == expected


def test_protection_classifier_rejects_invalid_mark_range() -> None:
    with pytest.raises(ProtectionTriggerAmbiguous, match="mark_range_invalid"):
        classify_mark_protection_touch(
            position_side="long",
            mark_open="100",
            mark_high="99",
            mark_low="98",
            stop_trigger="94",
            take_trigger="108",
        )


def _bar(
    hour: int,
    *,
    open_: str = "60000",
    high: str = "60100",
    low: str = "59900",
    close: str = "60050",
) -> HistoricalBar:
    event = datetime(2026, 7, 23, hour, tzinfo=UTC)
    return HistoricalBar(
        event_time_utc=event,
        available_time_utc=event.replace(hour=hour + 1),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        mark_open=Decimal(open_),
        mark_high=Decimal(high),
        mark_low=Decimal(low),
        mark_close=Decimal(close),
        index_close=Decimal(close),
    )


def test_historical_venue_uses_next_open_and_never_past_bar_extrema(tmp_path: Path) -> None:
    venue = HistoricalOfflineVenue(tmp_path / "venue.json", now=datetime(2026, 7, 23, 1, tzinfo=UTC))
    completed = _bar(0, high="90000", low="10000")
    venue.advance(completed_bar=completed, next_bar_open=Decimal("61000"))

    response = venue.submit_order(
        {
            "clOrdId": "history-open-1",
            "instId": "BTC-USDT-SWAP",
            "side": "buy",
            "posSide": "long",
            "ordType": "limit",
            "px": "62000",
            "sz": "0.01",
            "attachAlgoOrds": [
                {
                    "attachAlgoClOrdId": "history-protect-1",
                    "tpTriggerPx": "62220",
                    "tpTriggerPxType": "mark",
                    "tpOrdPx": "-1",
                    "slTriggerPx": "60390",
                    "slTriggerPxType": "mark",
                    "slOrdPx": "-1",
                }
            ],
        }
    )

    assert response.code == "0"
    assert venue.state["fills"][0]["fillPx"] == "61003.05"
    assert venue.state["position"] == "0.01"
    assert len(venue.state["algos"]) == 1


def test_funding_is_settled_before_new_fill_and_is_idempotent(tmp_path: Path) -> None:
    venue = HistoricalOfflineVenue(tmp_path / "venue.json", now=datetime(2026, 7, 23, 8, tzinfo=UTC))
    venue.state.update({"position": "0.01", "avg_price": "60000", "cash": "4999.7"})
    venue._persist()
    funding = HistoricalFundingEvent(
        settlement_time_utc=datetime(2026, 7, 23, 8, tzinfo=UTC),
        available_time_utc=datetime(2026, 7, 23, 8, tzinfo=UTC),
        rate=Decimal("0.0001"),
        mark_price=Decimal("61000"),
        source_record_id="funding-20260723-08",
        mark_price_policy="reported_mark_price",
    )

    venue.advance(completed_bar=_bar(7), next_bar_open=Decimal("61000"), funding_events=(funding,))
    first_cash = Decimal(venue.state["cash"])
    venue.advance(completed_bar=_bar(7), next_bar_open=Decimal("61000"), funding_events=(funding,))

    assert Decimal(venue.state["cash"]) == first_cash
    assert len(venue.state["bills"]) == 1
    assert venue.state["bills"][0]["billId"].isdigit()


def test_mark_bar_double_touch_blocks_without_choosing_a_favorable_path(tmp_path: Path) -> None:
    venue = HistoricalOfflineVenue(tmp_path / "venue.json", now=datetime(2026, 7, 23, 2, tzinfo=UTC))
    venue.state.update(
        {
            "position": "0.01",
            "avg_price": "60000",
            "algos": [
                {
                    "algoId": "algo-1",
                    "algoClOrdId": "protect-1",
                    "parentClOrdId": "parent-1",
                    "instId": "BTC-USDT-SWAP",
                    "side": "sell",
                    "posSide": "long",
                    "sz": "0.01",
                    "state": "live",
                    "ordType": "oco",
                    "tpTriggerPx": "61200",
                    "slTriggerPx": "59400",
                    "uTime": str(
                        int(datetime(2026, 7, 23, 0, tzinfo=UTC).timestamp() * 1000)
                    ),
                }
            ],
        }
    )
    venue._persist()

    with pytest.raises(ProtectionTriggerAmbiguous, match="historical_protection_double_touch_ambiguous"):
        venue.advance(
            completed_bar=_bar(1, high="61300", low="59300"),
            next_bar_open=Decimal("60000"),
        )

    assert venue.state["position"] == "0.01"
    assert venue.state["fills"] == []


def test_single_stop_touch_creates_child_order_fill_and_fill_driven_flat(tmp_path: Path) -> None:
    venue = HistoricalOfflineVenue(tmp_path / "venue.json", now=datetime(2026, 7, 23, 1, tzinfo=UTC))
    venue.advance(completed_bar=_bar(0), next_bar_open=Decimal("60000"))
    opened = venue.submit_order(
        {
            "clOrdId": "history-open-2",
            "instId": "BTC-USDT-SWAP",
            "side": "buy",
            "posSide": "long",
            "ordType": "limit",
            "px": "61000",
            "sz": "0.01",
            "attachAlgoOrds": [
                {
                    "attachAlgoClOrdId": "history-protect-2",
                    "tpTriggerPx": "61200",
                    "tpTriggerPxType": "mark",
                    "tpOrdPx": "-1",
                    "slTriggerPx": "59400",
                    "slTriggerPxType": "mark",
                    "slOrdPx": "-1",
                }
            ],
        }
    )
    assert opened.code == "0"
    # The attached OCO is tied to the genuine 01:00 opening fill; changing
    # its receipt timestamp would invalidate its persisted parent evidence.
    venue.now = datetime(2026, 7, 23, 2, tzinfo=UTC)
    venue.advance(
        completed_bar=_bar(1, open_="60000", high="60500", low="59300", close="59500"),
        next_bar_open=Decimal("59500"),
    )

    assert venue.state["position"] == "0"
    assert len(venue.state["orders"]) == 2
    assert len(venue.state["fills"]) == 2
    assert venue.state["fills"][-1]["execType"] == "historical_oco_stop_loss"
    assert venue.state["algo_history"][-1]["state"] == "effective"
    assert venue.state["algos"] == []
    assert Decimal(venue.state["cash"]) == (
        Decimal("5000")
        + Decimal(venue.state["realized_pnl"])
        - Decimal(venue.state["fee_total"])
    )


def test_non_marketable_limit_is_rejected_without_economic_mutation(tmp_path: Path) -> None:
    venue = HistoricalOfflineVenue(tmp_path / "venue.json", now=datetime(2026, 7, 23, 1, tzinfo=UTC))
    venue.advance(completed_bar=_bar(0), next_bar_open=Decimal("60000"))
    rejected = venue.submit_order(
        {
            "clOrdId": "history-reject-1",
            "instId": "BTC-USDT-SWAP",
            "side": "buy",
            "posSide": "long",
            "ordType": "limit",
            "px": "59900",
            "sz": "0.01",
        }
    )
    assert rejected.data[0]["sCode"] == "51008"
    assert venue.state["position"] == "0"
    assert venue.state["orders"] == []
    assert venue.state["fills"] == []


def test_missing_funding_mark_is_never_coerced_to_zero() -> None:
    with pytest.raises(ValueError, match="historical_funding_value_invalid"):
        HistoricalFundingEvent(
            settlement_time_utc=datetime(2026, 7, 23, 8, tzinfo=UTC),
            available_time_utc=datetime(2026, 7, 23, 8, tzinfo=UTC),
            rate=Decimal("0.0001"),
            mark_price=Decimal("NaN"),
            source_record_id="missing-mark",
            mark_price_policy="reported_mark_price",
        )


def test_v1_config_keeps_historical_dependencies_default_closed(tmp_path: Path) -> None:
    config = DonchianOfflineReplayConfig(
        repo_root=Path.cwd(),
        state_dir=tmp_path,
        run_id="v1-default",
        decision_time_utc=datetime(2026, 7, 23, 1, tzinfo=UTC),
        data_version="v1-default-data",
    )
    assert config.venue_factory is None
    assert config.decision_time_provider is None


def test_unregistered_history_replay_rejects_coordination_projection_hook() -> None:
    replay = object.__new__(DonchianHistoricalReplay)
    replay.coordination_projection_enabled = False
    with pytest.raises(
        ValueError, match="historical_coordination_projection_not_enabled"
    ):
        replay.run(after_event=lambda _cursor, _projection: None)


def test_run_id_cannot_escape_output_root_for_status_or_existing_link(tmp_path: Path) -> None:
    output_root = tmp_path / "declared"
    escaped = tmp_path / "escaped-run"
    escaped.mkdir()
    (escaped / "historical_replay.json").write_text(
        json.dumps({"status": "escaped-marker"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="historical_run_id_invalid"):
        DonchianHistoricalReplay.status(
            output_root=output_root,
            run_id="..\\escaped-run",
        )
    with pytest.raises(ValueError, match="historical_run_id_invalid"):
        DonchianHistoricalReplay.status(
            output_root=output_root,
            run_id=str(escaped.resolve()),
        )
    with pytest.raises(ValueError, match="historical_run_id_invalid"):
        DonchianHistoricalReplay(
            repo_root=Path.cwd(),
            output_root=output_root,
            run_id="..\\escaped-run",
        )

    output_root.mkdir()
    linked = output_root / "linked-run"
    try:
        os.symlink(escaped, linked, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory symlink unavailable on this host")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(escaped)],
            capture_output=True,
            check=False,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip("directory symlink and junction unavailable on this host")
    with pytest.raises(ValueError, match="historical_run_root_escape"):
        DonchianHistoricalReplay.status(
            output_root=output_root,
            run_id="linked-run",
        )


@pytest.mark.parametrize("venue_payload", (None, {}))
def test_finalize_and_status_block_when_persisted_venue_facts_are_missing(
    tmp_path: Path,
    venue_payload: dict[str, object] | None,
) -> None:
    replay = object.__new__(DonchianHistoricalReplay)
    replay.output_root = tmp_path
    replay.run_id = "missing-venue"
    replay.run_root = tmp_path / replay.run_id
    replay.run_root.mkdir(parents=True)
    if venue_payload is not None:
        venue_path = replay.run_root / "state" / "offline_venue.json"
        venue_path.parent.mkdir(parents=True)
        venue_path.write_text(json.dumps(venue_payload), encoding="utf-8")
    artifact = {
        "schema_version": "btc_donchian_historical_replay_v1",
        "identity_digest": "a" * 64,
        "events": [
            {"event_time_utc": f"event-{index}", "phases": []}
            for index in range(168)
        ],
        "blockers": [],
        "status": "running",
    }

    finalized = replay._finalize(artifact)
    assert finalized["status"] == "blocked"
    assert "historical_persistent_venue_state_missing_or_invalid" in finalized["blockers"]
    assert finalized["marked_state"] == {"status": "unverified"}

    observed = DonchianHistoricalReplay.status(
        output_root=tmp_path,
        run_id="missing-venue",
    )
    assert observed["status"] == "blocked"
    assert "historical_persistent_venue_state_missing_or_invalid" in observed["blockers"]
    assert observed["marked_state"] == {"status": "unverified"}


def test_gap_stop_precedes_funding_and_restart_is_economically_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "venue.json"
    venue = HistoricalOfflineVenue(
        path, now=datetime(2026, 7, 23, 8, tzinfo=UTC)
    )
    venue.state.update(
        {
            "position": "0.01",
            "avg_price": "60000",
            "cash": "5000",
            "mark_price": "60000",
            "algos": [
                {
                    "algoId": "gap-algo-1",
                    "algoClOrdId": "gap-protection-1",
                    "parentClOrdId": "gap-parent-1",
                    "instId": "BTC-USDT-SWAP",
                    "side": "sell",
                    "posSide": "long",
                    "sz": "0.01",
                    "state": "live",
                    "ordType": "oco",
                    "tpTriggerPx": "61200",
                    "slTriggerPx": "59400",
                    "uTime": str(
                        int(datetime(2026, 7, 23, 6, tzinfo=UTC).timestamp() * 1000)
                    ),
                }
            ],
        }
    )
    venue._persist()
    funding = HistoricalFundingEvent(
        settlement_time_utc=datetime(2026, 7, 23, 8, tzinfo=UTC),
        available_time_utc=datetime(2026, 7, 23, 8, tzinfo=UTC),
        rate=Decimal("0.0001"),
        mark_price=Decimal("61000"),
        source_record_id="gap-funding-08",
        mark_price_policy="reported_mark_price",
    )
    completed = _bar(
        7,
        open_="59300",
        high="59500",
        low="59200",
        close="59450",
    )

    venue.advance(
        completed_bar=completed,
        next_bar_open=Decimal("59450"),
        funding_events=(funding,),
    )
    state_after = json.loads(path.read_text(encoding="utf-8"))
    restarted = HistoricalOfflineVenue(
        path, now=datetime(2026, 7, 23, 8, tzinfo=UTC)
    )
    restarted.advance(
        completed_bar=completed,
        next_bar_open=Decimal("59450"),
        funding_events=(funding,),
    )

    assert venue.state["position"] == "0"
    assert venue.state["funding_total"] == "0"
    assert venue.state["bills"][0]["balChg"] == "0"
    assert venue.state["fills"][0]["fillPx"] == "59300"
    assert venue.state["fills"][0]["effectiveTimePolicy"] == "bar_open_gap"
    assert venue.state["fills"][0]["effectiveAtUtc"] == "2026-07-23T07:00:00+00:00"
    assert venue.state["fills"][0]["observedAtUtc"] == "2026-07-23T08:00:00+00:00"
    assert venue.state == state_after == restarted.state


def test_protection_created_within_bar_cannot_be_backdated_to_mark_extrema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "venue.json"
    venue = HistoricalOfflineVenue(
        path, now=datetime(2026, 7, 23, 8, tzinfo=UTC)
    )
    venue.state.update(
        {
            "position": "0.01",
            "avg_price": "60000",
            "algos": [
                {
                    "algoId": "intrabar-algo-1",
                    "algoClOrdId": "intrabar-protection-1",
                    "parentClOrdId": "intrabar-parent-1",
                    "instId": "BTC-USDT-SWAP",
                    "side": "sell",
                    "posSide": "long",
                    "sz": "0.01",
                    "state": "live",
                    "ordType": "oco",
                    "tpTriggerPx": "61200",
                    "slTriggerPx": "59400",
                    "uTime": str(
                        int(
                            datetime(2026, 7, 23, 7, 0, 1, tzinfo=UTC).timestamp()
                            * 1000
                        )
                    ),
                }
            ],
        }
    )
    venue._persist()

    with pytest.raises(
        ProtectionTriggerAmbiguous,
        match="historical_protection_created_intrabar_trigger_order_ambiguous",
    ):
        venue.advance(
            completed_bar=_bar(
                7,
                open_="60000",
                high="60500",
                low="59300",
                close="59500",
            ),
            next_bar_open=Decimal("59500"),
        )

    assert venue.state["position"] == "0.01"
    assert venue.state["fills"] == []


def test_terminal_economic_mutation_requires_original_ledger_evidence() -> None:
    flat = {
        "position": "0",
        "cash": "5000",
        "avg_price": "0",
        "realized_pnl": "0",
        "fee_total": "0",
        "funding_total": "0",
        "orders": [],
        "fills": [],
        "mark_price": "60000",
        "unrealized_pnl": "0",
        "equity": "5000",
    }
    zero_bill_only = {**flat, "bills": [{"balChg": "0"}]}
    assert not _terminal_ledger_required(flat, zero_bill_only)
    assert _terminal_ledger_required(
        flat, {**flat, "funding_total": "-0.1", "cash": "4999.9"}
    )
    assert _terminal_ledger_required(
        {**flat, "position": "0.01"},
        {**flat, "position": "0.01", "mark_price": "60100", "equity": "5000.01"},
    )
    assert _terminal_ledger_required(
        {**flat, "position": "0.01"},
        {
            **flat,
            "fills": [{"fillId": "terminal-protection-fill"}],
            "orders": [{"ordId": "terminal-protection-order"}],
        },
    )


def _lock_only_replay(root: Path) -> DonchianHistoricalReplay:
    replay = object.__new__(DonchianHistoricalReplay)
    replay.run_root = root / "lease-run"
    return replay


def test_os_writer_lease_excludes_a_second_writer_and_recovers_after_release(
    tmp_path: Path,
) -> None:
    first = _lock_only_replay(tmp_path)
    second = _lock_only_replay(tmp_path)
    descriptor = first._acquire()
    try:
        with pytest.raises(RuntimeError, match="historical_replay_writer_lock_held"):
            second._acquire()
    finally:
        first._release(descriptor)

    recovered = second._acquire()
    second._release(recovered)
    assert second.lock_path.read_text(encoding="ascii").startswith(
        "schema=historical_replay_os_lease_v1\n"
    )


def test_legacy_live_or_unknown_owner_blocks_without_unlink(
    tmp_path: Path, monkeypatch
) -> None:
    replay = _lock_only_replay(tmp_path)
    replay.run_root.mkdir(parents=True)
    replay.lock_path.write_text("pid=12345\n", encoding="ascii")
    monkeypatch.setattr(
        DonchianHistoricalReplay,
        "_process_alive_conservative",
        staticmethod(lambda _pid: True),
    )
    with pytest.raises(
        RuntimeError, match="historical_replay_legacy_writer_lock_held_or_unknown"
    ):
        replay._acquire()
    assert replay.lock_path.read_text(encoding="ascii") == "pid=12345\n"

    replay.lock_path.write_text("legacy-owner-unknown\n", encoding="ascii")
    with pytest.raises(
        RuntimeError, match="historical_replay_legacy_writer_lock_held_or_unknown"
    ):
        replay._acquire()
    assert replay.lock_path.read_text(encoding="ascii") == "legacy-owner-unknown\n"


def test_confirmed_dead_legacy_owner_is_replaced_while_os_lease_is_held(
    tmp_path: Path, monkeypatch
) -> None:
    first = _lock_only_replay(tmp_path)
    second = _lock_only_replay(tmp_path)
    first.run_root.mkdir(parents=True)
    first.lock_path.write_text("pid=12345\n", encoding="ascii")
    monkeypatch.setattr(
        DonchianHistoricalReplay,
        "_process_alive_conservative",
        staticmethod(lambda _pid: False),
    )
    descriptor = first._acquire()
    try:
        with pytest.raises(RuntimeError, match="historical_replay_writer_lock_held"):
            second._acquire()
    finally:
        first._release(descriptor)
    assert first.lock_path.read_text(encoding="ascii").startswith(
        "schema=historical_replay_os_lease_v1\npid="
    )
