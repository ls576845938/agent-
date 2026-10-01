from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import multiprocessing as mp
import time

import pytest

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill
import quant_us.execution.ledger as ledger_module
from quant_us.execution.fill_idempotency import (
    FillIdempotencyIndex,
    append_fill_idempotent,
    fill_key,
)
from quant_us.execution.ledger import JsonlLedgerStore


FILLED_AT = datetime(2026, 5, 4, 14, 30, tzinfo=timezone.utc)


def make_fill(**overrides: object) -> Fill:
    values = {
        "order_id": "ord_001",
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "quantity": 100.0,
        "price": 150.0,
        "commission": 0.25,
        "filled_at": FILLED_AT,
        "broker": "paper",
        "broker_order_id": "broker_ord_001",
        "fill_id": "fill_001",
    }
    values.update(overrides)
    return Fill(**values)  # type: ignore[arg-type]


def _append_fill_worker(
    root: str,
    fill: Fill,
    ready_queue: object,
    release_event: object,
    result_queue: object,
) -> None:
    try:
        ready_queue.put("ready")
        if not release_event.wait(10):
            result_queue.put(("error", "timed out waiting for release"))
            return
        result = append_fill_idempotent(JsonlLedgerStore(root), fill)
        result_queue.put((result.status, result.key))
    except BaseException as exc:
        result_queue.put(("error", repr(exc)))


def test_duplicate_fill_is_not_written_twice(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = make_fill()

    first = append_fill_idempotent(ledger, fill)
    duplicate = append_fill_idempotent(ledger, fill)

    assert first.appended is True
    assert duplicate.duplicate is True
    assert len(ledger.read_records("fills.jsonl")) == 1


def test_same_identity_different_fingerprint_conflicts_without_write(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = make_fill(fill_id="fill_conflict")
    conflict_fill = replace(fill, price=151.0)

    first = append_fill_idempotent(ledger, fill)
    conflict = append_fill_idempotent(ledger, conflict_fill)

    records = ledger.read_records("fills.jsonl")
    assert first.appended is True
    assert conflict.conflict is True
    assert conflict.key == "fill_id:fill_conflict"
    assert conflict.conflict_existing != conflict.conflict_incoming
    assert len(records) == 1
    assert records[0]["price"] == 150.0


def test_historical_ledger_prewarm_dedupes_and_blocks_conflict(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = make_fill(fill_id="fill_historical")
    ledger.append_fill(fill)

    reopened = JsonlLedgerStore(tmp_path)
    index = FillIdempotencyIndex.from_ledger(reopened)
    duplicate = append_fill_idempotent(reopened, fill, index=index)
    conflict = append_fill_idempotent(reopened, replace(fill, quantity=99.0), index=index)

    assert duplicate.duplicate is True
    assert conflict.conflict is True
    assert len(reopened.read_records("fills.jsonl")) == 1


def test_missing_fill_id_fallback_key_is_stable_and_dedupes(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = make_fill(fill_id="")

    first = append_fill_idempotent(ledger, fill)
    duplicate = append_fill_idempotent(ledger, fill)
    record = ledger.read_records("fills.jsonl")[0]

    assert first.appended is True
    assert duplicate.duplicate is True
    assert first.key == fill_key(fill)
    assert fill_key(record) == fill_key(fill)
    assert len(ledger.read_records("fills.jsonl")) == 1


def test_missing_fill_id_same_fallback_identity_different_payload_conflicts(tmp_path) -> None:
    ledger = JsonlLedgerStore(tmp_path)
    fill = make_fill(fill_id="")
    conflict_fill = replace(fill, price=151.0)

    first = append_fill_idempotent(ledger, fill)
    conflict = append_fill_idempotent(ledger, conflict_fill)

    records = ledger.read_records("fills.jsonl")
    assert first.appended is True
    assert conflict.conflict is True
    assert conflict.key == fill_key(fill)
    assert len(records) == 1
    assert records[0]["price"] == 150.0


def test_jsonl_idempotent_append_is_guarded_against_concurrent_duplicates(tmp_path) -> None:
    class SlowAppendLedger(JsonlLedgerStore):
        def append_fill(self, fill: object) -> None:
            time.sleep(0.01)
            super().append_fill(fill)

    ledger = SlowAppendLedger(tmp_path)
    fill = make_fill(fill_id="fill_concurrent")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: append_fill_idempotent(ledger, fill), range(8)))

    assert sum(result.appended for result in results) == 1
    assert sum(result.duplicate for result in results) == 7
    assert all(not result.conflict for result in results)
    assert len(ledger.read_records("fills.jsonl")) == 1


def test_jsonl_idempotent_append_is_guarded_across_store_instances(tmp_path) -> None:
    ledgers = [JsonlLedgerStore(tmp_path) for _ in range(8)]
    fill = make_fill(fill_id="fill_concurrent_instances")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda ledger: append_fill_idempotent(ledger, fill), ledgers))

    assert sum(result.appended for result in results) == 1
    assert sum(result.duplicate for result in results) == 7
    assert all(not result.conflict for result in results)
    assert len(JsonlLedgerStore(tmp_path).read_records("fills.jsonl")) == 1


def test_stale_index_is_refreshed_under_lock_before_append(tmp_path) -> None:
    fill = make_fill(fill_id="fill_stale_index")
    stale_index = FillIdempotencyIndex.from_ledger(JsonlLedgerStore(tmp_path))

    first = append_fill_idempotent(JsonlLedgerStore(tmp_path), fill)
    duplicate = append_fill_idempotent(JsonlLedgerStore(tmp_path), fill, index=stale_index)

    assert first.appended is True
    assert duplicate.duplicate is True
    assert len(JsonlLedgerStore(tmp_path).read_records("fills.jsonl")) == 1


def test_conflict_across_store_instances_does_not_write(tmp_path) -> None:
    fill = make_fill(fill_id="fill_instance_conflict")

    first = append_fill_idempotent(JsonlLedgerStore(tmp_path), fill)
    conflict = append_fill_idempotent(JsonlLedgerStore(tmp_path), replace(fill, price=151.0))

    records = JsonlLedgerStore(tmp_path).read_records("fills.jsonl")
    assert first.appended is True
    assert conflict.conflict is True
    assert len(records) == 1
    assert records[0]["price"] == 150.0


@pytest.mark.skipif(
    ledger_module._fcntl is None,
    reason="fcntl.flock is unavailable; fallback is process-local only",
)
def test_jsonl_idempotent_append_is_guarded_across_processes(tmp_path) -> None:
    if "fork" not in mp.get_all_start_methods():
        pytest.skip("fork start method is unavailable")

    context = mp.get_context("fork")
    ready_queue = context.Queue()
    result_queue = context.Queue()
    release_event = context.Event()
    fill = make_fill(fill_id="fill_cross_process")
    processes = [
        context.Process(
            target=_append_fill_worker,
            args=(str(tmp_path), fill, ready_queue, release_event, result_queue),
        )
        for _ in range(4)
    ]

    for process in processes:
        process.start()
    for _ in processes:
        assert ready_queue.get(timeout=5) == "ready"

    release_event.set()
    for process in processes:
        process.join(10)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join()
            pytest.fail("worker process did not exit")
        assert process.exitcode == 0

    statuses = [result_queue.get(timeout=5) for _ in processes]
    assert [status for status, _key in statuses].count("appended") == 1
    assert [status for status, _key in statuses].count("duplicate") == 3
    assert all(status != "error" for status, _key in statuses)
    assert len(JsonlLedgerStore(tmp_path).read_records("fills.jsonl")) == 1


def test_fill_idempotency_lock_falls_back_to_process_lock_when_fcntl_is_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ledger_module, "_fcntl", None)
    ledger = JsonlLedgerStore(tmp_path)

    with ledger.fill_idempotency_lock():
        ledger.append_fill(make_fill(fill_id="fill_process_only_fallback"))

    assert not (tmp_path / ".fill_idempotency.lock").exists()
    assert len(ledger.read_records("fills.jsonl")) == 1
