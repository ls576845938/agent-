"""Test Paper Production Orchestrator, Run Journal, Strategy Whitelist, and Recovery."""

import json
import os
import tempfile
from pathlib import Path

import pytest


class TestStrategyWhitelist:
    """Strategy whitelist must block unapproved strategies and symbols."""

    def test_etf_rotation_whitelisted(self):
        from quant_us.live.paper_orchestrator import validate_strategy_whitelist
        result = validate_strategy_whitelist("etf_rotation", ["SPY", "QQQ"])
        assert result == {}

    def test_trend_momentum_whitelisted(self):
        from quant_us.live.paper_orchestrator import validate_strategy_whitelist
        result = validate_strategy_whitelist("trend_momentum", ["SPY", "QQQ", "IWM", "DIA"])
        assert result == {}

    def test_unknown_strategy_blocked(self):
        from quant_us.live.paper_orchestrator import validate_strategy_whitelist
        result = validate_strategy_whitelist("unknown_strategy", ["SPY"])
        assert "error" in result
        assert "not in paper whitelist" in result["error"]

    def test_disallowed_symbols_blocked(self):
        from quant_us.live.paper_orchestrator import validate_strategy_whitelist
        result = validate_strategy_whitelist("etf_rotation", ["SPY", "TSLA"])
        assert "error" in result
        assert "TSLA" in result["error"]


class TestPaperRunJournal:
    """Run journal must support append, read, and latest."""

    def test_append_and_read(self):
        from quant_us.live.paper_orchestrator import PaperRunJournal, JournalEntry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            journal = PaperRunJournal(path)
            journal.append(JournalEntry(run_id="r1", entry_type="run_start", data={"a": 1}))
            journal.append(JournalEntry(run_id="r1", entry_type="run_end", data={"b": 2}))

            entries = journal.read_all()
            assert len(entries) == 2
            assert entries[0]["entry_type"] == "run_start"
            assert entries[1]["entry_type"] == "run_end"

    def test_filter_by_run_id(self):
        from quant_us.live.paper_orchestrator import PaperRunJournal, JournalEntry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            journal = PaperRunJournal(path)
            journal.append(JournalEntry(run_id="r1", entry_type="run_start"))
            journal.append(JournalEntry(run_id="r2", entry_type="run_start"))

            r1 = journal.read_all(run_id="r1")
            assert len(r1) == 1
            assert r1[0]["run_id"] == "r1"

    def test_latest_run_status(self):
        from quant_us.live.paper_orchestrator import PaperRunJournal, JournalEntry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            journal = PaperRunJournal(path)
            journal.append(JournalEntry(run_id="r1", entry_type="run_start"))
            journal.append(JournalEntry(run_id="r1", entry_type="run_end", data={"status": "complete"}))

            latest = journal.latest_run_status()
            assert latest is not None
            assert latest["data"]["status"] == "complete"


class TestPaperRunState:
    """Run state must serialize, deserialize, and support recovery flags."""

    def test_roundtrip(self):
        from quant_us.live.paper_orchestrator import PaperRunState

        state = PaperRunState(run_id="test-123", trading_day=5, last_step="reconcile",
                              submitted_order_intent_ids=["i1", "i2"],
                              kill_switch_triggered=False, recovery_required=False)
        d = state.to_dict()
        restored = PaperRunState.from_dict(d)
        assert restored.run_id == "test-123"
        assert restored.trading_day == 5
        assert restored.submitted_order_intent_ids == ["i1", "i2"]

    def test_save_and_load(self):
        from quant_us.live.paper_orchestrator import PaperRunState, PaperRunStateStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = PaperRunStateStore(path)
            state = PaperRunState(run_id="r99", trading_day=10, recovery_required=True)
            store.save(state)

            loaded = store.load()
            assert loaded is not None
            assert loaded.run_id == "r99"
            assert loaded.recovery_required is True

    def test_load_nonexistent(self):
        from quant_us.live.paper_orchestrator import PaperRunStateStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.json"
            store = PaperRunStateStore(path)
            assert store.load() is None

    def test_load_corrupted(self):
        from quant_us.live.paper_orchestrator import PaperRunStateStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.json"
            path.write_text("not json")
            store = PaperRunStateStore(path)
            assert store.load() is None


class TestOrchestratorGates:
    """Orchestrator must block on missing credentials and whitelist violations."""

    def test_blocked_on_missing_credentials(self):
        from quant_us.live.paper_orchestrator import PaperProductionOrchestrator

        old_key = os.environ.pop("APCA_API_KEY_ID", None)
        old_secret = os.environ.pop("APCA_API_SECRET_KEY", None)
        try:
            orch = PaperProductionOrchestrator(symbols=["SPY"], strategy_id="etf_rotation")
            result = orch.run()
            assert result["status"] == "BLOCKED"
            assert result["gate"] == "credentials"
        finally:
            if old_key: os.environ["APCA_API_KEY_ID"] = old_key
            if old_secret: os.environ["APCA_API_SECRET_KEY"] = old_secret

    def test_blocked_on_unknown_strategy(self):
        from quant_us.live.paper_orchestrator import PaperProductionOrchestrator

        oa, os.environ["APCA_API_KEY_ID"] = os.environ.get("APCA_API_KEY_ID"), "test"
        os.environ["APCA_API_SECRET_KEY"] = "test"
        try:
            orch = PaperProductionOrchestrator(symbols=["SPY"], strategy_id="bogus_strategy")
            result = orch.run()
            assert result["status"] == "BLOCKED"
            assert "whitelist" in result["gate"]
        finally:
            os.environ.pop("APCA_API_KEY_ID", None)
            os.environ.pop("APCA_API_SECRET_KEY", None)
            if oa: os.environ["APCA_API_KEY_ID"] = oa

    def test_dry_run_does_not_submit(self):
        from quant_us.live.paper_orchestrator import PaperProductionOrchestrator

        oa, os.environ["APCA_API_KEY_ID"] = os.environ.get("APCA_API_KEY_ID"), "test"
        os.environ["APCA_API_SECRET_KEY"] = "test"
        try:
            orch = PaperProductionOrchestrator(symbols=["SPY"], strategy_id="etf_rotation",
                                                enable_paper_orders=False)
            result = orch.run()
            assert "dry_run" in str(result.get("status", "")) or result["status"] == "BLOCKED"
        finally:
            os.environ.pop("APCA_API_KEY_ID", None)
            os.environ.pop("APCA_API_SECRET_KEY", None)
            if oa: os.environ["APCA_API_KEY_ID"] = oa
