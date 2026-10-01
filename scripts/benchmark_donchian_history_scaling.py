"""Committed-source synthetic ledger scaling, not a strategy experiment.

Creates its OWN temporary journal. Never reads the active annual run. Each
history point is verified by BTCRuntimeStore; baseline and compacted inputs
then go through the SAME authoritative ledger function. Timings exclude data
generation, and are not an annual completion-time forecast.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import hashlib
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--hours", type=int, nargs="+", default=[800, 1760, 4000])
    parser.add_argument("--closed-runtime", type=Path,
                        help="Only a confirmed closed journal; read-only copy into this new engineering output")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from quant_crypto.application.donchian_offline_history_cache import OfflineLedgerHistoryCache
    from quant_crypto.oms.account_risk_facts import replay_account_ledger_uows
    from quant_crypto.oms.runtime_store import BTCRuntimeStore

    def deny(*_args, **_kwargs):
        raise AssertionError("benchmark_network_prohibited")
    socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
    if subprocess.check_output(["git", "status", "--porcelain", "--", "quant_crypto", "quant_shared", "scripts/benchmark_donchian_history_scaling.py"], cwd=root, text=True).strip():
        raise ValueError("committed_source_required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    output = args.output_root.resolve()
    if output.exists() or root == output or root in output.parents:
        raise ValueError("new_external_output_required")
    output.mkdir(parents=True)
    if args.closed_runtime is not None:
        source = args.closed_runtime.resolve()
        target = output / "closed-journal-copy-not-a-run"
        target.mkdir()
        def digest(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        hashes = {}
        for name in ("events.jsonl", "state.json"):
            path = source / name
            if name == "state.json" and not path.exists():
                continue
            before = digest(path)
            shutil.copyfile(path, target / name)
            if before != digest(target / name) or before != digest(path):
                raise ValueError("closed_journal_source_changed")
            hashes[name] = before
        store = BTCRuntimeStore(target, offline_journal_session=True)
        try:
            begin = time.perf_counter()
            recovered = store.recover()
            cold = time.perf_counter() - begin
            assert not recovered.blockers, recovered.blockers
            sequence, last_hash = recovered.last_sequence, recovered.last_event_hash
            del recovered
            warm = []
            for _ in range(5):
                begin = time.perf_counter()
                recovered = store.recover()
                warm.append(time.perf_counter() - begin)
                assert not recovered.blockers and recovered.last_sequence == sequence and recovered.last_event_hash == last_hash
                del recovered
        finally:
            store.close()
        assert all(digest(source / name) == value and digest(target / name) == value for name, value in hashes.items())
        report = dict(kind="closed_journal_copy_recovery_only_no_strategy_run", source_head=head,
                      source_hashes=hashes, events=sequence, last_hash=last_hash,
                      cold_recovery_seconds=cold, warm_recovery_seconds=warm,
                      network_accessed=False, trading_authorized=False)
        (output / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        return
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store = BTCRuntimeStore(output / "synthetic-runtime", offline_journal_session=True)
    cache = OfflineLedgerHistoryCache()
    bills, results = [], []
    fills = [dict(fill_id="open", side="buy", size="0.1", price="100", fee="-0.01", fee_currency="USDT", timestamp_ms=str(int((start + timedelta(minutes=1)).timestamp() * 1000))),
             dict(fill_id="close", side="sell", size="0.1", price="110", fee="-0.01", fee_currency="USDT", timestamp_ms=str(int((start + timedelta(minutes=2)).timestamp() * 1000)))]
    for hour in range(1, max(args.hours) + 1):
        when = start + timedelta(hours=hour)
        if hour % 8 == 0:
            bills.append(dict(bill_id=f"funding-{hour}", timestamp_ms=str(int(when.timestamp() * 1000)), currency="USDT", balance_change_observed=True, balance_change="0.0001"))
        payload = {"fill_ledger": fills, "funding_ledger": {"bills": bills}, "risk_context": {"venue_rules": {"contract_value_btc": "0.01"}}}
        store.append(event_type="ledger_uow_committed", payload=payload, state_after={"hour": hour},
                     idempotency_key=f"hour-{hour}", timestamp_utc=when.isoformat(), run_id="synthetic-scaling-only", safety={"live_enabled": False})
        if hour not in args.hours:
            continue
        store.checkpoint({"hour": hour})
        begin = time.perf_counter()
        recovered = store.recover()
        cold_recovery = time.perf_counter() - begin
        assert not recovered.blockers
        options = dict(baseline_equity_usdt="5000", baseline_observed_at_utc=start, final_observed_at_utc=when, currency="USDT",
                       final_exchange_snapshot={"mark": {"mark_price": "110"}, "positions": [], "balance": {"equity_usdt": str(Decimal("4999.99") + len(bills) * Decimal("0.0001"))}})
        begin = time.perf_counter()
        expected = replay_account_ledger_uows(uow_payloads=[e["payload"] for e in recovered.events] + [payload], **options)
        baseline_seconds = time.perf_counter() - begin
        # Discard expanded views before measuring the accelerated caller.
        del recovered
        recovered = store.recover()
        begin = time.perf_counter()
        assert cache.replay(recovery=recovered, baseline_sequence=0, account_identity="synthetic-only", candidate_uow=payload, **options) == expected
        cold_replay = time.perf_counter() - begin
        del recovered
        begin = time.perf_counter()
        recovered = store.recover()
        warm_recovery = time.perf_counter() - begin
        begin = time.perf_counter()
        assert cache.replay(recovery=recovered, baseline_sequence=0, account_identity="synthetic-only", candidate_uow=payload, **options) == expected
        warm_replay = time.perf_counter() - begin
        packed_size = sum(len(chunk) for _, chunk in store._verified_prefix_chunks)
        packed_size += sum(len(value) for snap in store._verified_events_snapshot for value in snap.compounds.values())
        result = dict(hours=hour, journal_bytes=store.events_path.stat().st_size, private_cache_packed_bytes=packed_size,
                      cold_verified_recovery_seconds=cold_recovery, warm_verified_recovery_seconds=warm_recovery,
                      full_history_replay_seconds=baseline_seconds, incremental_catchup_replay_seconds=cold_replay,
                      warm_compacted_replay_seconds=warm_replay, ledger_replay_speedup=baseline_seconds / warm_replay,
                      economic_result=expected)
        results.append(result)
        print(json.dumps(result), flush=True)
        del recovered
    report = dict(kind="synthetic_ledger_scaling_not_strategy_research", source_head=head, results=results,
                  constraints="exclusive Windows session only; cold recovery fully verifies log; unique economics still fully replayed",
                  network_accessed=False, trading_authorized=False)
    store.close()
    (output / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
