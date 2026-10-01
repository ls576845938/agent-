from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_shared.backtest import BacktestEvidence, validate_backtest_evidence
from quant_shared.ledger import LedgerRecord, reconcile_fingerprints
from quant_shared.replay import (
    ReplayEvent,
    ReplayInput,
    ReplaySnapshot,
    validate_replay_input,
)


def test_ledger_records_are_versioned_hashable_and_reconcilable() -> None:
    record = LedgerRecord(
        stream_id="run-1",
        record_id="record-1",
        sequence=0,
        occurred_at_utc=datetime(2026, 7, 23, tzinfo=timezone.utc),
        record_type="cash_delta",
        payload={"unit": "USD", "amount": -10.0},
    )
    assert len(record.fingerprint) == 64
    assert reconcile_fingerprints({"record-1": record.fingerprint}, {"record-1": record.fingerprint}).reconciled
    mismatch = reconcile_fingerprints(
        {"record-1": record.fingerprint, "record-2": "a" * 64},
        {"record-1": "b" * 64, "record-3": "c" * 64},
    )
    assert mismatch.reconciled is False
    assert mismatch.missing == ("record-2",)
    assert mismatch.unexpected == ("record-3",)
    assert mismatch.mismatched == ("record-1",)


def test_replay_accepts_only_injected_deterministically_ordered_history() -> None:
    fixed = datetime(2026, 7, 23, tzinfo=timezone.utc)
    valid = ReplayInput(
        replay_id="replay-1",
        fixed_clock_utc=fixed,
        random_seed=7,
        snapshots=(ReplaySnapshot("snapshot-1", fixed, "data-v1"),),
        events=(
            ReplayEvent("event-1", fixed - timedelta(seconds=2), "input"),
            ReplayEvent("event-2", fixed - timedelta(seconds=1), "decision"),
        ),
    )
    assert validate_replay_input(valid) == ()
    invalid = ReplayInput(
        replay_id="replay-2",
        fixed_clock_utc=fixed,
        random_seed=7,
        snapshots=(ReplaySnapshot("future-snapshot", fixed + timedelta(seconds=1), "data-v1"),),
        events=(
            ReplayEvent("event-2", fixed, "second"),
            ReplayEvent("event-1", fixed - timedelta(seconds=1), "first"),
        ),
    )
    assert validate_replay_input(invalid) == (
        "snapshot_after_fixed_clock:future-snapshot",
        "events_not_deterministically_ordered",
    )
    assert not {"latest", "current", "live"}.intersection(ReplayInput.__dataclass_fields__)


def test_backtest_evidence_fails_closed_without_required_proofs() -> None:
    complete = BacktestEvidence(
        cost_model="commission-v1",
        slippage_model="slippage-v1",
        decision_time_rule="event_time",
        execution_time_rule="next_event",
        candidate_count=1,
        trial_count=1,
        walk_forward_valid=True,
        no_lookahead_valid=True,
        ledger_reconciled=True,
        pnl_source="ledger_derived",
        ledger_hash="a" * 64,
        replay_hash="b" * 64,
        current_head_match=True,
    )
    assert validate_backtest_evidence(complete) == ()
    incomplete = BacktestEvidence(
        cost_model="commission-v1",
        slippage_model="slippage-v1",
        decision_time_rule="event_time",
        execution_time_rule="next_event",
        candidate_count=1,
        trial_count=1,
        walk_forward_valid=False,
        no_lookahead_valid=False,
        ledger_reconciled=False,
        pnl_source="price_series",
        ledger_hash="a" * 64,
        replay_hash="b" * 64,
        current_head_match=False,
    )
    assert validate_backtest_evidence(incomplete) == (
        "walk_forward_not_valid",
        "no_lookahead_not_valid",
        "ledger_not_reconciled",
        "pnl_not_ledger_derived",
        "current_head_mismatch",
    )
