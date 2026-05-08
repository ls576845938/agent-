"""Verify G5 one-shot prevents any second live order."""

from __future__ import annotations

import tempfile, json
from pathlib import Path

import pytest

from quant_us.live.one_shot_executor import (
    SubmitOnceLock, SubmitOnceLockManager, OneShotExecutorConfig
)


class TestSubmitOnceLock:
    def test_lock_creation(self) -> None:
        lock = SubmitOnceLock(lock_id="L1", ticket_id="T1")
        assert lock.is_active is True
        assert lock.status == "ACTIVE"

    def test_manager_not_locked_initially(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SubmitOnceLockManager(lock_path=f"{tmp}/lock.json")
            assert mgr.is_locked() is False

    def test_manager_locks_and_blocks_second(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SubmitOnceLockManager(lock_path=f"{tmp}/lock.json")
            mgr.lock("T1", client_order_id="coid_1", broker_order_id="bid_1")
            assert mgr.is_locked() is True
            with pytest.raises(RuntimeError, match="SUBMIT-ONCE LOCK ACTIVE"):
                mgr.lock("T2")

    def test_manager_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SubmitOnceLockManager(lock_path=f"{tmp}/lock.json")
            mgr.lock("T1")
            lock = mgr.release("admin", "manual_review_complete")
            assert lock.status == "RELEASED_BY_MANUAL_REVIEW"
            assert mgr.is_locked() is False

    def test_status_returns_correct_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SubmitOnceLockManager(lock_path=f"{tmp}/lock.json")
            s = mgr.status()
            assert s["locked"] is False
            mgr.lock("T1")
            s = mgr.status()
            assert s["locked"] is True


class TestOneShotConfig:
    def test_execute_without_real_money_raises(self) -> None:
        with pytest.raises(ValueError, match="i-understand-this-is-real-money"):
            OneShotExecutorConfig(
                execute_one_shot=True, confirm_live=True,
                i_understand_real_money=False,
            )

    def test_execute_without_confirm_raises(self) -> None:
        with pytest.raises(ValueError, match="confirm-live"):
            OneShotExecutorConfig(
                execute_one_shot=True, confirm_live=False,
                i_understand_real_money=True,
            )

    def test_default_dry_run(self) -> None:
        config = OneShotExecutorConfig()
        assert config.is_dry_run is True
        assert config.execute_one_shot is False
