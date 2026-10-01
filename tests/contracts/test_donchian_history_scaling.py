"""Offline cache must retain the authoritative replay result and rejection codes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from quant_crypto.oms.account_risk_facts import AccountRiskFactError, replay_account_ledger_uows
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.application.donchian_offline_history_cache import OfflineLedgerHistoryCache


START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def uow(hour):
    fills = [{"fill_id": "open", "timestamp_ms": str(int((START + timedelta(hours=1)).timestamp() * 1000)),
              "side": "buy", "size": "0.1", "price": "100", "fee": "-0.01", "fee_currency": "USDT"},
             {"fill_id": "close", "timestamp_ms": str(int((START + timedelta(hours=2)).timestamp() * 1000)),
              "side": "sell", "size": "0.1", "price": "110", "fee": "-0.01", "fee_currency": "USDT"}]
    return {"risk_context": {"venue_rules": {"contract_value_btc": "0.01"}}, "fill_ledger": fills,
            "funding_ledger": {"bills": [{"bill_id": f"bill-{i}", "timestamp_ms": str(int((START + timedelta(hours=i)).timestamp() * 1000)),
                "balance_change_observed": True, "balance_change": "0.0001", "currency": "USDT"} for i in range(8, hour + 1, 8)]}}


def kwargs(hour):
    return {"baseline_equity_usdt": "5000", "baseline_observed_at_utc": START,
            "final_observed_at_utc": START + timedelta(hours=hour), "currency": "USDT",
            "final_exchange_snapshot": {"mark": {"mark_price": "110"}, "positions": [],
                "balance": {"equity_usdt": str(Decimal("4999.99") + Decimal(hour // 8) * Decimal("0.0001"))}}}


def append(store, payload, index):
    store.append(event_type="ledger_uow_committed", payload=payload, state_after={},
                 idempotency_key=str(index), timestamp_utc=START.isoformat(), run_id="cache-test",
                 safety={"live_enabled": False})


def call(cache, store, candidate, hour, **overrides):
    return cache.replay(recovery=store.recover(), baseline_sequence=0, account_identity="account-a",
                        candidate_uow=candidate, **{**kwargs(hour), **overrides})


def test_history_inputs_not_expanded_again_and_economics_match(tmp_path, monkeypatch):
    from quant_crypto.application import donchian_offline_history_cache as module
    cache, store, past, volumes = OfflineLedgerHistoryCache(), BTCRuntimeStore(tmp_path, verified_prefix_cache=True), [], []
    def measured(**options):
        volumes.append(sum(len(p.get("fill_ledger", [])) + len(p.get("funding_ledger", {}).get("bills", [])) for p in options["uow_payloads"]))
        return replay_account_ledger_uows(**options)
    monkeypatch.setattr(module, "replay_account_ledger_uows", measured)
    for hour in range(8, 129, 8):
        candidate = uow(hour)
        actual = call(cache, store, candidate, hour)
        assert actual == replay_account_ledger_uows(uow_payloads=[*past, candidate], **kwargs(hour))
        append(store, candidate, hour)
        past.append(candidate)
    assert volumes[-1] <= 3 * (2 + 128 // 8)  # compact history + newly committed + candidate
    # Detached cache: mutating a caller's input or result cannot alter old rows.
    candidate["fill_ledger"][0]["price"] = "999"
    actual["final_equity_usdt"] = "999"
    assert call(cache, store, uow(128), 128) == replay_account_ledger_uows(uow_payloads=[*past[:-1], uow(128)], **kwargs(128))


@pytest.mark.parametrize("defect", ["fill_conflict", "bill_conflict", "ctval", "bad_time", "future", "bad_bill_time", "future_bill", "bad_row", "fee_currency", "unknown_funding", "position", "equity", "numeric_type_conflict"])
def test_new_rows_and_candidates_keep_original_rejections(tmp_path, defect):
    cache, store = OfflineLedgerHistoryCache(), BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    past = uow(16)
    append(store, past, 1)
    call(cache, store, uow(16), 16)
    candidate, options = uow(24), kwargs(24)
    if defect == "fill_conflict": candidate["fill_ledger"][0]["price"] = "101"
    elif defect == "bill_conflict": candidate["funding_ledger"]["bills"][0]["balance_change"] = "1"
    elif defect == "ctval": candidate["risk_context"]["venue_rules"]["contract_value_btc"] = "1"
    elif defect == "bad_time": candidate["fill_ledger"][0]["timestamp_ms"] = "bad"
    elif defect == "future": candidate["fill_ledger"][0]["timestamp_ms"] = str(int((START + timedelta(days=3)).timestamp() * 1000))
    elif defect == "bad_bill_time": candidate["funding_ledger"]["bills"][0]["timestamp_ms"] = "bad"
    elif defect == "future_bill": candidate["funding_ledger"]["bills"][0]["timestamp_ms"] = str(int((START + timedelta(days=3)).timestamp() * 1000))
    elif defect == "bad_row": candidate["fill_ledger"].append(None)
    elif defect == "fee_currency": candidate["fill_ledger"].append({**candidate["fill_ledger"][0], "fill_id": "extra", "fee_currency": "BTC"})
    elif defect == "unknown_funding": candidate["funding_ledger"]["bills"][-1]["balance_change_observed"] = False
    elif defect == "position": options["final_exchange_snapshot"]["positions"] = [{"contracts": "1", "position_side": "long"}]
    elif defect == "equity": options["final_exchange_snapshot"]["balance"]["equity_usdt"] = "5001"
    else: candidate["fill_ledger"][0]["price"] = 100.0
    with pytest.raises((AccountRiskFactError, ValueError, TypeError)) as expected:
        replay_account_ledger_uows(uow_payloads=[past, candidate], **options)
    with pytest.raises(type(expected.value)) as observed:
        cache.replay(recovery=store.recover(), baseline_sequence=0, account_identity="account-a", candidate_uow=candidate, **options)
    assert str(observed.value) == str(expected.value)


def test_uncommitted_candidate_never_enters_history(tmp_path):
    cache, store = OfflineLedgerHistoryCache(), BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    call(cache, store, uow(24), 24)  # simulate crash / commit failure after replay success
    candidate = uow(24)
    candidate["fill_ledger"][0]["price"] = "101"
    options = kwargs(24)
    options["final_exchange_snapshot"]["balance"]["equity_usdt"] = "4999.9893"
    assert call(cache, store, candidate, 24, **options) == replay_account_ledger_uows(uow_payloads=[candidate], **options)


@pytest.mark.parametrize("change", ["restart", "time_back", "baseline", "account", "replacement", "blocked"])
def test_cache_invalidates_on_recovery_context_change(tmp_path, change):
    cache, store = OfflineLedgerHistoryCache(), BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    append(store, uow(24), 1)
    call(cache, store, uow(24), 24)
    options, sequence, account = kwargs(32), 0, "account-a"
    if change == "restart": cache = OfflineLedgerHistoryCache()
    elif change == "time_back": options = kwargs(16)
    elif change == "baseline": sequence = 1
    elif change == "account": account = "account-b"
    elif change == "blocked":
        raw = store.events_path.read_bytes()
        stamp = store.events_path.stat()
        store.events_path.write_bytes(raw.replace(b'"price":"100"', b'"price":"999"', 1))
        os.utime(store.events_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with pytest.raises(AccountRiskFactError, match="runtime_event_recovery_blocked"):
            call(cache, store, uow(32), 32)
        return
    else:
        # A fully valid, different hash chain at the same path is not the cached prefix.
        replacement = BTCRuntimeStore(tmp_path / "replacement")
        append(replacement, uow(16), 1)
        store.events_path.write_bytes(replacement.events_path.read_bytes())
    recovered = store.recover()
    prior = [e["payload"] for e in recovered.events if e["sequence"] > sequence]
    candidate = uow(32)
    try:
        expected = replay_account_ledger_uows(uow_payloads=[*prior, candidate], **options)
    except AccountRiskFactError as exc:
        with pytest.raises(AccountRiskFactError, match=str(exc)):
            cache.replay(recovery=recovered, baseline_sequence=sequence, account_identity=account, candidate_uow=candidate, **options)
    else:
        assert cache.replay(recovery=recovered, baseline_sequence=sequence, account_identity=account, candidate_uow=candidate, **options) == expected


def test_prefix_recovery_reads_bounded_chunks_not_whole_log(tmp_path, monkeypatch):
    store = BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    for i in range(12):
        append(store, {**uow(16), "padding": "x" * 200000}, i)
    store.checkpoint({})
    expected = BTCRuntimeStore(tmp_path).recover()
    store.recover()
    original = type(store.events_path).read_bytes
    def no_whole_read(path):
        assert path != store.events_path, "verified prefix must not be recopied in one giant allocation"
        return original(path)
    monkeypatch.setattr(type(store.events_path), "read_bytes", no_whole_read)
    assert store.recover() == expected
    assert max(size for size, _ in store._verified_prefix_chunks) <= 1024 * 1024
    assert sum(len(data) for _, data in store._verified_prefix_chunks) < store.events_path.stat().st_size / 10


@pytest.mark.parametrize("defect", ["ctval", "timestamp", "conflict"])
def test_newly_committed_uows_cannot_hide_behind_valid_candidate(tmp_path, defect):
    cache, store = OfflineLedgerHistoryCache(), BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    append(store, uow(16), 1)
    call(cache, store, uow(16), 16)
    bad = uow(24)
    if defect == "ctval": bad["risk_context"]["venue_rules"]["contract_value_btc"] = "0.1"
    elif defect == "timestamp": bad["funding_ledger"]["bills"][0]["timestamp_ms"] = "invalid"
    else: bad["fill_ledger"][0]["price"] = "999"
    append(store, bad, 2)
    with pytest.raises(AccountRiskFactError) as expected:
        replay_account_ledger_uows(uow_payloads=[uow(16), bad, uow(32)], **kwargs(32))
    with pytest.raises(AccountRiskFactError) as actual:
        call(cache, store, uow(32), 32)
    assert str(actual.value) == str(expected.value)


def test_baseline_old_rows_checked_before_they_can_be_excluded(tmp_path):
    cache, store = OfflineLedgerHistoryCache(), BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    old = uow(16)
    for row in old["fill_ledger"]:
        row["timestamp_ms"] = str(int(START.timestamp() * 1000))
        row.pop("fill_id")  # ignored before baseline by the original contract
    candidate = uow(24)
    append(store, old, 1)
    assert call(cache, store, candidate, 24) == replay_account_ledger_uows(uow_payloads=[old, candidate], **kwargs(24))
    assert call(cache, store, candidate, 24) == replay_account_ledger_uows(uow_payloads=[old, candidate], **kwargs(24))
    malformed = deepcopy(old)
    malformed["fill_ledger"][0]["timestamp_ms"] = "invalid"
    append(store, malformed, 2)
    with pytest.raises(AccountRiskFactError, match="fill_timestamp_invalid"):
        call(cache, store, candidate, 24)


@pytest.mark.parametrize("ending", [b"\r", b"\r\n", b"\n", b""])
def test_offline_stream_parser_preserves_legacy_line_endings(tmp_path, ending):
    store = BTCRuntimeStore(tmp_path)
    for i in range(3): append(store, uow(16), i)
    original = store.events_path.read_bytes().splitlines()
    separator = ending or b"\n"
    store.events_path.write_bytes(separator.join(original) + ending)
    fast = BTCRuntimeStore(tmp_path, verified_prefix_cache=True)
    assert fast.recover() == store.recover()
    assert fast.recover() == store.recover()


def test_production_default_ledger_seam_still_uses_full_authority(tmp_path, monkeypatch):
    from quant_crypto.oms import okx_demo_paper_runtime as runtime
    controller = object.__new__(runtime.OkxDemoPaperRuntimeController)
    store = BTCRuntimeStore(tmp_path)
    append(store, uow(16), 1)
    seen = []
    def authority(**options):
        seen.append(options["uow_payloads"])
        return replay_account_ledger_uows(**options)
    monkeypatch.setattr(runtime, "replay_account_ledger_uows", authority)
    result = controller._replay_reconciled_ledger(recovery=store.recover(), baseline_sequence=0,
        account_identity="account-a", candidate_uow=uow(24), **kwargs(24))
    assert result["reconciled"] and seen == [[uow(16), uow(24)]]


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
def test_exclusive_session_blocks_competing_writes_and_releases(tmp_path):
    root = tmp_path / "session"
    store = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        append(store, uow(16), 1)
        assert not store.recover().blockers
        # Cross-process checks, not just a cooperative Python lock.
        probe = """
from pathlib import Path
import sys
p = Path(sys.argv[1])
assert p.read_bytes()
for action in (lambda: p.open('r+b'), lambda: p.open('wb'),
               lambda: p.unlink(), lambda: p.rename(p.with_suffix('.moved'))):
    try:
        result = action()
    except OSError:
        continue
    if hasattr(result, 'close'): result.close()
    raise AssertionError('competing mutation was allowed')
"""
        subprocess.run([sys.executable, "-c", probe, str(store.events_path)], check=True)
        assert store.recover() == BTCRuntimeStore(root).recover()
    finally:
        store.close()
    with store.events_path.open("r+b"):
        pass


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
def test_session_warm_recovery_reads_only_own_tail_and_rechecks_checkpoint(tmp_path, monkeypatch):
    from quant_crypto.oms import runtime_store as module
    store = BTCRuntimeStore(tmp_path / "session", offline_journal_session=True)
    try:
        for i in range(5): append(store, uow(16), i)
        store.checkpoint({"value": 5})
        original = store.recover()
        calls = []
        digest = module._digest
        def traced(value):
            calls.append(value)
            return digest(value)
        monkeypatch.setattr(module, "_digest", traced)
        # No raw-prefix compression/decompression in a held lease.
        monkeypatch.setattr(module._PrefixChunks, "__init__", lambda *a, **k: pytest.fail("full prefix scan"))
        assert store.recover() == original
        assert len(calls) == 1  # checkpoint remains independently revalidated
        append(store, uow(24), 5)
        calls.clear()
        assert store.recover().last_sequence == 6
        assert len(calls) == 2  # checkpoint + new event, never old events
        store.checkpoint_path.write_bytes(b'{}')
        assert "btc_runtime_checkpoint_invalid" in store.recover().blockers
        with pytest.raises(module.BTCRuntimeStoreError): append(store, uow(24), 6)
    finally:
        store.close()


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
def test_session_restart_revalidates_tampering_and_missing_log(tmp_path):
    from quant_crypto.oms.runtime_store import BTCRuntimeStoreError
    root = tmp_path / "session"
    store = BTCRuntimeStore(root, offline_journal_session=True)
    append(store, uow(16), 1)
    store.checkpoint({})
    assert not store.recover().blockers
    store.close()
    raw, stamp = store.events_path.read_bytes(), store.events_path.stat()
    store.events_path.write_bytes(raw.replace(b'"price":"100"', b'"price":"999"', 1))
    os.utime(store.events_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    restarted = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert "btc_runtime_event_chain_invalid" in restarted.recover().blockers
        with pytest.raises(BTCRuntimeStoreError): append(restarted, uow(24), 2)
    finally:
        restarted.close()
    store.events_path.unlink()
    missing = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert missing.recover().blockers
        assert not store.events_path.exists()  # never OPEN_ALWAYS on recovery
    finally:
        missing.close()


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
@pytest.mark.parametrize("defect", ["lost_handle", "fsync", "short_write"])
def test_session_io_failure_cannot_ack_or_continue(tmp_path, monkeypatch, defect):
    from quant_crypto.oms.runtime_store import BTCRuntimeStoreError
    store = BTCRuntimeStore(tmp_path / "session", offline_journal_session=True)
    append(store, uow(16), 1)
    assert not store.recover().blockers
    if defect == "lost_handle":
        store._journal_session.handle.close()
    elif defect == "fsync":
        monkeypatch.setattr(os, "fsync", lambda *_a: (_ for _ in ()).throw(OSError("injected fsync")))
    else:
        original = os.write
        monkeypatch.setattr(os, "write", lambda fd, raw: original(fd, raw[:10]))
    try:
        with pytest.raises(BTCRuntimeStoreError): append(store, uow(24), 2)
        assert store._sequence == 1
        assert store.recover().blockers
        with pytest.raises(BTCRuntimeStoreError): append(store, uow(24), 2)
    finally:
        store.close()


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
@pytest.mark.parametrize("keep_mapping_handle", [True, False])
def test_live_writable_mapping_prevents_exclusive_session(tmp_path, keep_mapping_handle):
    import ctypes
    from ctypes import wintypes
    import msvcrt
    root = tmp_path / "existing"
    plain = BTCRuntimeStore(root)
    append(plain, uow(16), 1)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileMappingW.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                        wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR)
    kernel.CreateFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
    kernel.MapViewOfFile.restype = wintypes.LPVOID
    kernel.UnmapViewOfFile.argtypes = (wintypes.LPCVOID,)
    kernel.UnmapViewOfFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    with plain.events_path.open("r+b") as writable:
        mapping = kernel.CreateFileMappingW(msvcrt.get_osfhandle(writable.fileno()), None, 4, 0, 0, None)
        assert mapping
        view = kernel.MapViewOfFile(mapping, 2, 0, 0, 0)
        assert view
    if not keep_mapping_handle:
        assert kernel.CloseHandle(mapping)
        mapping = None
    session = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert session.recover().blockers, "fast path unsafe: surviving writable view coexists"
    finally:
        session.close()
        assert kernel.UnmapViewOfFile(view)
        if mapping: assert kernel.CloseHandle(mapping)
    session = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert session.recover() == plain.recover()
        assert not os.get_inheritable(session._journal_session.handle.fileno())
    finally:
        session.close()


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
def test_preexisting_writer_and_hardlink_fail_closed(tmp_path):
    root = tmp_path / "existing"
    plain = BTCRuntimeStore(root)
    append(plain, uow(16), 1)
    with plain.events_path.open("r+b"):
        session = BTCRuntimeStore(root, offline_journal_session=True)
        try:
            assert session.recover().blockers
        finally:
            session.close()
    alias = tmp_path / "alias.jsonl"
    os.link(plain.events_path, alias)
    session = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert session.recover().blockers
    finally:
        session.close()


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
def test_restart_after_durable_append_without_checkpoint_and_duplicate(tmp_path):
    from quant_crypto.oms.runtime_store import BTCRuntimeStoreError
    root = tmp_path / "session"
    first = BTCRuntimeStore(root, offline_journal_session=True)
    append(first, uow(16), 1)
    first.close()  # durable log, no checkpoint: normal crash recovery authority
    resumed = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert resumed.recover() == BTCRuntimeStore(root).recover()
        append(resumed, uow(16), 1)
        assert resumed.recover().last_sequence == 1
        with pytest.raises(BTCRuntimeStoreError): append(resumed, uow(24), 1)
        assert resumed.recover().blockers
    finally:
        resumed.close()


def test_default_and_unsupported_platform_do_not_trust_exclusive_prefix(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from quant_crypto.oms import runtime_store as module
    assert not BTCRuntimeStore(tmp_path)._offline_session_enabled
    assert not BTCRuntimeStore(tmp_path).verified_prefix_cache
    monkeypatch.setattr(module, "os", SimpleNamespace(**{**vars(os), "name": "posix"}))
    store = BTCRuntimeStore(tmp_path / "fallback", offline_journal_session=True)
    append(store, uow(16), 1)
    assert not store._offline_session_enabled and not store.recover().blockers
    raw = store.events_path.read_bytes()
    store.events_path.write_bytes(raw.replace(b'"price":"100"', b'"price":"999"', 1))
    assert "btc_runtime_event_chain_invalid" in store.recover().blockers


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
def test_session_parent_rebinding_is_rejected_or_os_denied(tmp_path):
    root = tmp_path / "session"
    store = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        append(store, uow(16), 1)
        assert not store.recover().blockers
        try:
            root.rename(tmp_path / "renamed")
        except OSError:
            return  # OS already protects this path binding
        assert store.recover().blockers
    finally:
        store.close()


def test_controller_constructor_failure_releases_store_and_guardian(tmp_path, monkeypatch):
    from quant_crypto.application import donchian_offline_replay as replay
    supervisors, stores, closed = [], [], []
    original_supervisor = replay.RuntimeRiskGuardianSupervisor
    def supervisor(*args, **kwargs):
        result = original_supervisor(*args, **kwargs)
        supervisors.append(result)
        original_close = result.close
        def close():
            closed.append(result)
            original_close()
        result.close = close
        return result
    def fail_after_store_created(controller):
        stores.append(controller._runtime_store)
        assert not controller._runtime_store.recover().blockers
        raise RuntimeError("injected_controller_constructor_failure")
    monkeypatch.setattr(replay, "RuntimeRiskGuardianSupervisor", supervisor)
    monkeypatch.setattr(replay._OfflineSignalMemoController, "_recover_previous_state", fail_after_store_created)
    with pytest.raises(RuntimeError, match="injected_controller_constructor_failure"):
        replay.DonchianOfflineReplay(replay.DonchianOfflineReplayConfig(
            repo_root=Path(__file__).resolve().parents[2], state_dir=tmp_path / "state",
            run_id="constructor-failure", decision_time_utc=START, data_version="fixture",
        ))
    assert closed == supervisors and len(closed) == 1
    assert len(stores) == 1 and stores[0]._journal_closed
    with stores[0].events_path.open("r+b"):
        pass


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_interrupt_after_durable_readback_cannot_reuse_old_sequence(tmp_path, monkeypatch, error):
    from quant_crypto.oms.runtime_store import BTCRuntimeStoreError
    root = tmp_path / "session"
    store = BTCRuntimeStore(root, offline_journal_session=True)
    append(store, uow(16), 1)
    original = store._journal_session.write
    def interrupted(raw):
        original(raw)
        raise error("after_readback_before_memory_ack")
    monkeypatch.setattr(store._journal_session, "write", interrupted)
    try:
        with pytest.raises(error): append(store, uow(24), 2)
        assert store._sequence == 1 and not store._journal_proof_ready
        with pytest.raises(BTCRuntimeStoreError): append(store, uow(24), 2)
    finally:
        store.close()
    restarted = BTCRuntimeStore(root, offline_journal_session=True)
    try:
        assert restarted.recover().last_sequence == 2
        append(restarted, uow(24), 2)
        recovered = restarted.recover()
        assert recovered.last_sequence == 2 and not recovered.blockers
    finally:
        restarted.close()


@pytest.mark.skipif(os.name != "nt", reason="mandatory Windows file sharing contract")
@pytest.mark.parametrize("fault", ["readback", "checkpoint_fsync"])
def test_readback_or_checkpoint_failure_invalidates_session(tmp_path, monkeypatch, fault):
    from quant_crypto.oms.runtime_store import BTCRuntimeStoreError
    store = BTCRuntimeStore(tmp_path / "session", offline_journal_session=True)
    append(store, uow(16), 1)
    try:
        if fault == "readback":
            monkeypatch.setattr(store._journal_session.handle, "read", lambda *_: b"wrong")
            with pytest.raises(BTCRuntimeStoreError, match="readback_mismatch"):
                append(store, uow(24), 2)
            assert store._sequence == 1
        else:
            monkeypatch.setattr(os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("checkpoint fsync")))
            with pytest.raises(BTCRuntimeStoreError): store.checkpoint({})
        assert not store._journal_proof_ready and store.recover().blockers
        with pytest.raises(BTCRuntimeStoreError): append(store, uow(24), 2)
    finally:
        store.close()
