"""Tests for DailyTradingReport generation, formatting, and persistence."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.monitoring.daily_report import (
    DailyTradingReport,
    format_report_json,
    format_report_text,
    generate_daily_report,
    save_report,
)
from quant_us.monitoring.paper_review_status import (
    build_paper_review_evidence_index,
    inspect_paper_review_status,
)
from quant_us.research.evidence_registry import inspect_evidence_registry
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig


# ---------------------------------------------------------------------------
# Stub broker for testing
# ---------------------------------------------------------------------------

_SAMPLE_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT"]


class StubBroker(BrokerBase):
    """Minimal broker stub that returns canned account / positions / orders."""

    broker_name = "stub"

    def __init__(self) -> None:
        self._account = AccountState(
            timestamp_utc=datetime(2026, 5, 3, 20, 0, tzinfo=timezone.utc),
            account_id="test_acct",
            cash=50_000.0,
            buying_power=110_000.0,
            equity=110_000.0,
            positions={
                "SPY": Position("SPY", quantity=100.0, avg_price=500.0, market_price=505.0, unrealized_pnl=500.0),
                "QQQ": Position("QQQ", quantity=50.0, avg_price=400.0, market_price=410.0, unrealized_pnl=500.0),
            },
        )
        self._orders: list[Order] = [
            Order(
                timestamp_utc=datetime(2026, 5, 3, 14, 30, tzinfo=timezone.utc),
                strategy_id="test_strat",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                client_order_id="coid_001",
                status=OrderStatus.FILLED,
            ),
            Order(
                timestamp_utc=datetime(2026, 5, 3, 14, 31, tzinfo=timezone.utc),
                strategy_id="test_strat",
                symbol="QQQ",
                side=OrderSide.BUY,
                quantity=50.0,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                client_order_id="coid_002",
                status=OrderStatus.FILLED,
            ),
            Order(
                timestamp_utc=datetime(2026, 5, 3, 14, 32, tzinfo=timezone.utc),
                strategy_id="test_strat",
                symbol="AAPL",
                side=OrderSide.SELL,
                quantity=10.0,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                client_order_id="coid_003",
                status=OrderStatus.REJECTED,
            ),
            Order(
                timestamp_utc=datetime(2026, 5, 3, 14, 33, tzinfo=timezone.utc),
                strategy_id="test_strat",
                symbol="MSFT",
                side=OrderSide.BUY,
                quantity=5.0,
                order_type=OrderType.LIMIT,
                limit_price=300.0,
                time_in_force=TimeInForce.DAY,
                client_order_id="coid_004",
                status=OrderStatus.SUBMITTED,
            ),
        ]
        self._fills: list[Fill] = [
            Fill(
                order_id="ord_001",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                price=502.0,
                commission=5.02,
                filled_at=datetime(2026, 5, 3, 14, 30, 30, tzinfo=timezone.utc),
                broker="stub",
                fill_id="fill_001",
            ),
            Fill(
                order_id="ord_002",
                symbol="QQQ",
                side=OrderSide.BUY,
                quantity=50.0,
                price=408.0,
                commission=2.04,
                filled_at=datetime(2026, 5, 3, 14, 31, 30, tzinfo=timezone.utc),
                broker="stub",
                fill_id="fill_002",
            ),
        ]

    def get_account(self) -> AccountState:
        return self._account

    def get_positions(self) -> dict[str, Position]:
        return dict(self._account.positions)

    def get_orders(self) -> list[Order]:
        return list(self._orders)

    def submit_order(self, order: Order) -> Order:
        return order

    def cancel_order(self, order_id: str) -> Order:
        return Order(
            timestamp_utc=datetime(2026, 5, 3, 20, 0, tzinfo=timezone.utc),
            strategy_id="stub",
            symbol="",
            side=OrderSide.BUY,
            quantity=0.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="",
            status=OrderStatus.CANCELLED,
        )

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        if order_id is None:
            return list(self._fills)
        return [f for f in self._fills if f.order_id == order_id]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def ledger(tmp_root: Path) -> JsonlLedgerStore:
    return JsonlLedgerStore(str(tmp_root / "ledger"))


@pytest.fixture
def broker() -> StubBroker:
    return StubBroker()


@pytest.fixture
def kill_switch() -> KillSwitch:
    ks = KillSwitch(config=KillSwitchConfig())
    ks.update_equity(100_000.0)
    ks.reset_daily(100_000.0)
    return ks


def _stub_recon_report(ledger: JsonlLedgerStore, status: str = "clean") -> None:
    """Write a stub reconciliation report into the ledger directory."""
    recon_dir = Path(ledger.root) / "reconciliation"
    recon_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": "2026-05-03T20:05:00+00:00",
        "status": status,
        "cash_diff": 0.0,
        "position_diffs": {} if status == "clean" else {"SPY": {"local_quantity": 95.0, "broker_quantity": 100.0}},
        "order_diffs": {},
        "fill_diffs": {},
        "halt_new_orders": status == "breaks_detected",
    }
    (recon_dir / "recon_20260503_200500.json").write_text(json.dumps(report))


def _stub_fills(ledger: JsonlLedgerStore) -> None:
    """Write stub fill records to the ledger fills.jsonl."""
    fills_path = Path(ledger.root) / "fills.jsonl"
    fills_path.write_text(
        json.dumps({
            "order_id": "ord_001",
            "symbol": "SPY",
            "side": "buy",
            "quantity": 100.0,
            "price": 502.0,
            "commission": 5.02,
            "filled_at": "2026-05-03T14:30:30+00:00",
            "broker": "stub",
            "fill_id": "fill_001",
        }) + "\n" +
        json.dumps({
            "order_id": "ord_002",
            "symbol": "QQQ",
            "side": "buy",
            "quantity": 50.0,
            "price": 408.0,
            "commission": 2.04,
            "filled_at": "2026-05-03T14:31:30+00:00",
            "broker": "stub",
            "fill_id": "fill_002",
        }) + "\n"
    )


def _stub_orders(ledger: JsonlLedgerStore) -> None:
    """Write stub order records to the ledger orders.jsonl."""
    orders_path = Path(ledger.root) / "orders.jsonl"
    orders_path.write_text(
        json.dumps({
            "order_id": "ord_001", "symbol": "SPY", "side": "buy",
            "quantity": 100.0, "status": "filled",
        }) + "\n" +
        json.dumps({
            "order_id": "ord_002", "symbol": "QQQ", "side": "buy",
            "quantity": 50.0, "status": "filled",
        }) + "\n" +
        json.dumps({
            "order_id": "ord_003", "symbol": "AAPL", "side": "sell",
            "quantity": 10.0, "status": "rejected",
        }) + "\n"
    )


def _stub_snapshot(ledger: JsonlLedgerStore, equity: float = 100_000.0) -> None:
    """Append a stub portfolio snapshot (yesterday's close = today's open)."""
    snap = {
        "timestamp_utc": "2026-05-02T20:00:00+00:00",
        "equity": equity,
        "cash": 50_000.0,
        "gross_exposure": 50_000.0,
        "net_exposure": 50_000.0,
        "daily_pnl": 500.0,
        "drawdown": 0.0,
    }
    (Path(ledger.root) / "portfolio_snapshots.jsonl").write_text(
        json.dumps(snap) + "\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDailyTradingReport:
    """Tests for DailyTradingReport dataclass and generate_daily_report()."""

    def test_generate_all_fields_populated(
        self, ledger: JsonlLedgerStore, broker: StubBroker, kill_switch: KillSwitch
    ) -> None:
        """After a trading day, report should have all fields populated."""
        _stub_fills(ledger)
        _stub_orders(ledger)
        _stub_snapshot(ledger, equity=100_000.0)
        _stub_recon_report(ledger, status="clean")

        report = generate_daily_report(date(2026, 5, 3), ledger, broker, kill_switch)

        # -- Account summary --
        assert report.report_date == date(2026, 5, 3)
        assert report.starting_equity == 100_000.0
        assert report.ending_equity == 110_000.0
        assert report.daily_pnl == 10_000.0
        assert report.daily_return_pct == 10.0
        assert report.total_fees == 7.06  # 5.02 + 2.04

        # -- Order stats --
        assert report.orders_submitted == 4
        assert report.orders_filled == 2
        assert report.orders_rejected == 1
        assert report.orders_cancelled == 0
        assert report.orders_pending == 1

        # -- Position summary --
        assert "SPY" in report.positions
        assert "QQQ" in report.positions
        assert report.positions["SPY"]["quantity"] == 100.0
        assert report.positions["SPY"]["market_value"] == 50500.0

        # -- Risk events --
        assert report.kill_switch_triggered is False
        assert report.risk_rejection_count == 1  # one order rejected

        # -- Reconciliation --
        assert report.reconciliation_status == "clean"
        assert report.reconciliation_diff_count == 0
        assert report.reconciliation_halt is False

        # -- Data quality defaults --
        assert report.stale_bars == 0
        assert report.missing_bars == []

        # -- generated_at is populated --
        assert report.generated_at is not None
        assert isinstance(report.generated_at, datetime)

    def test_generate_with_recon_breaks(
        self, ledger: JsonlLedgerStore, broker: StubBroker, kill_switch: KillSwitch
    ) -> None:
        """When reconciliation has breaks, the report reflects them."""
        _stub_snapshot(ledger, equity=100_000.0)
        _stub_recon_report(ledger, status="breaks_detected")

        report = generate_daily_report(date(2026, 5, 3), ledger, broker, kill_switch)
        assert report.reconciliation_status == "breaks_detected"
        assert report.reconciliation_diff_count == 1
        assert report.reconciliation_halt is True

    def test_generate_with_kill_switch_triggered(
        self, ledger: JsonlLedgerStore, broker: StubBroker
    ) -> None:
        """Kill switch triggered state is reflected."""
        ks = KillSwitch(config=KillSwitchConfig())
        ks._trigger("daily_loss_limit")
        _stub_snapshot(ledger, equity=100_000.0)
        _stub_recon_report(ledger, status="clean")

        report = generate_daily_report(date(2026, 5, 3), ledger, broker, ks)
        assert report.kill_switch_triggered is True
        assert report.kill_switch_reason == "daily_loss_limit"

    def test_generate_no_prior_snapshot(
        self, ledger: JsonlLedgerStore, broker: StubBroker, kill_switch: KillSwitch
    ) -> None:
        """When no prior snapshot exists, starting equity falls back to
        broker's current equity (so daily_pnl == 0)."""
        # No stub snapshot written
        _stub_recon_report(ledger, status="clean")

        report = generate_daily_report(date(2026, 5, 3), ledger, broker, kill_switch)
        # Broker equity is 110k, and since no prior snapshot, starting is also 110k
        assert report.starting_equity == 110_000.0
        assert report.daily_pnl == 0.0

    def test_generate_empty_ledger(
        self, tmp_root: Path, broker: StubBroker, kill_switch: KillSwitch
    ) -> None:
        """Empty ledger (no fills, no recon) should still produce a report."""
        empty_ledger = JsonlLedgerStore(str(tmp_root / "empty_ledger"))
        report = generate_daily_report(date(2026, 5, 3), empty_ledger, broker, kill_switch)
        assert report.starting_equity == 110_000.0  # falls back to broker
        assert report.total_fees == 0.0
        assert report.reconciliation_status == "unknown"
        assert report.reconciliation_diff_count == 0


class TestFormatReportText:
    """Tests for format_report_text()."""

    def test_text_contains_key_fields(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            starting_equity=100_000.0,
            ending_equity=110_000.0,
            daily_pnl=10_000.0,
            daily_return_pct=10.0,
            total_fees=7.06,
            orders_submitted=4,
            orders_filled=2,
            orders_rejected=1,
            orders_cancelled=0,
            orders_pending=1,
            positions={
                "SPY": {
                    "quantity": 100.0,
                    "market_price": 505.0,
                    "market_value": 50500.0,
                    "avg_price": 500.0,
                    "unrealized_pnl": 500.0,
                },
            },
            kill_switch_triggered=False,
            reconciliation_status="clean",
            reconciliation_diff_count=0,
            stale_bars=0,
        )
        text = format_report_text(report)

        # Should contain section headers
        assert "DAILY TRADING REPORT" in text
        assert "2026-05-03" in text

        assert "Starting Equity" in text
        assert "Ending Equity" in text
        assert "Daily Return" in text
        assert "10.0000" in text or "10.00" in text

        # Order statistics
        assert "Submitted" in text
        assert "Filled" in text
        assert "Rejected" in text

        # Position summary
        assert "SPY" in text
        assert "50,500" in text or "50500" in text

        # Risk
        assert "not triggered" in text

        # Reconciliation
        assert "clean" in text

        # Data quality
        assert "Stale" in text or "stale" in text

    def test_text_with_kill_switch(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            kill_switch_triggered=True,
            kill_switch_reason="daily_loss_limit",
        )
        text = format_report_text(report)
        assert "KILL SWITCH TRIGGERED" in text
        assert "daily_loss_limit" in text

    def test_text_with_errors(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            errors=["connection_timeout", "accounting_mismatch"],
        )
        text = format_report_text(report)
        assert "Errors" in text
        assert "connection_timeout" in text
        assert "accounting_mismatch" in text

    def test_text_with_missing_bars(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            missing_bars=["SPY"],
        )
        text = format_report_text(report)
        assert "SPY" in text

    def test_text_reconciliation_breaks(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            reconciliation_status="breaks_detected",
            reconciliation_diff_count=2,
            reconciliation_halt=True,
        )
        text = format_report_text(report)
        assert "breaks_detected" in text
        assert "Halt" in text
        assert "YES" in text


class TestFormatReportJson:
    """Tests for format_report_json()."""

    def test_json_valid_and_contains_fields(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            starting_equity=100_000.0,
            ending_equity=110_000.0,
            daily_pnl=10_000.0,
            orders_submitted=4,
        )
        raw = format_report_json(report)
        data = json.loads(raw)

        assert data["report_date"] == "2026-05-03"
        assert data["starting_equity"] == 100_000.0
        assert data["ending_equity"] == 110_000.0
        assert data["daily_pnl"] == 10_000.0
        assert data["orders_submitted"] == 4
        assert "generated_at" in data
        assert isinstance(data["generated_at"], str)

    def test_json_round_trip(self) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            starting_equity=100_000.0,
            ending_equity=110_000.0,
            daily_pnl=10_000.0,
            daily_return_pct=10.0,
            total_fees=7.06,
            orders_submitted=4,
            orders_filled=2,
            orders_rejected=1,
            orders_cancelled=0,
            orders_pending=1,
            positions={
                "SPY": {
                    "quantity": 100.0,
                    "market_price": 505.0,
                    "market_value": 50500.0,
                    "avg_price": 500.0,
                    "unrealized_pnl": 500.0,
                },
            },
            kill_switch_triggered=False,
            reconciliation_status="clean",
            reconciliation_diff_count=0,
            stale_bars=3,
        )
        raw = format_report_json(report)
        data = json.loads(raw)

        # Round-trip the fields
        assert data["report_date"] == "2026-05-03"
        assert data["starting_equity"] == 100_000.0
        assert data["stale_bars"] == 3
        assert data["reconciliation_status"] == "clean"
        assert data["positions"]["SPY"]["market_value"] == 50500.0

    def test_json_includes_even_zero_fields(self) -> None:
        """Zero-valued fields must still appear in JSON (not omitted)."""
        report = DailyTradingReport(report_date=date(2026, 5, 3))
        raw = format_report_json(report)
        data = json.loads(raw)
        assert "total_fees" in data
        assert data["total_fees"] == 0.0
        assert "orders_cancelled" in data
        assert data["orders_cancelled"] == 0
        assert "stale_bars" in data
        assert data["stale_bars"] == 0


class TestSaveReport:
    """Tests for save_report()."""

    def test_save_creates_files(self, tmp_path: Path) -> None:
        report = DailyTradingReport(
            report_date=date(2026, 5, 3),
            starting_equity=100_000.0,
            ending_equity=110_000.0,
        )
        output_dir = tmp_path / "reports"
        json_path = save_report(report, str(output_dir))

        # Check JSON file
        assert json_path.exists()
        assert json_path.name == "daily_report_2026-05-03.json"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["report_date"] == "2026-05-03"

        # Check text file
        text_path = output_dir / "daily_report_2026-05-03.txt"
        assert text_path.exists()
        text = text_path.read_text(encoding="utf-8")
        assert "DAILY TRADING REPORT" in text
        assert "2026-05-03" in text

    def test_save_returns_json_path(self, tmp_path: Path) -> None:
        report = DailyTradingReport(report_date=date(2026, 5, 3))
        json_path = save_report(report, str(tmp_path))
        assert str(json_path).endswith("daily_report_2026-05-03.json")

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """save_report should create the directory if it doesn't exist."""
        report = DailyTradingReport(report_date=date(2026, 5, 3))
        deep_dir = tmp_path / "a" / "b" / "c" / "reports"
        assert not deep_dir.exists()
        save_report(report, str(deep_dir))
        assert deep_dir.exists()
        assert (deep_dir / "daily_report_2026-05-03.json").exists()

    def test_save_multiple_dates(self, tmp_path: Path) -> None:
        """Reports for different dates should coexist."""
        report_a = DailyTradingReport(report_date=date(2026, 5, 3))
        report_b = DailyTradingReport(report_date=date(2026, 5, 4))
        out = tmp_path / "reports"
        save_report(report_a, str(out))
        save_report(report_b, str(out))
        assert (out / "daily_report_2026-05-03.json").exists()
        assert (out / "daily_report_2026-05-04.json").exists()
        assert (out / "daily_report_2026-05-03.txt").exists()
        assert (out / "daily_report_2026-05-04.txt").exists()


class TestFullIntegration:
    """End-to-end integration-style tests."""

    def test_generate_text_json_save(
        self, tmp_root: Path, broker: StubBroker, kill_switch: KillSwitch
    ) -> None:
        """Generate, format text, format JSON, and save — all in sequence."""
        ledger = JsonlLedgerStore(str(tmp_root / "ledger"))
        _stub_fills(ledger)
        _stub_orders(ledger)
        _stub_snapshot(ledger, equity=100_000.0)
        _stub_recon_report(ledger, status="clean")

        report = generate_daily_report(date(2026, 5, 3), ledger, broker, kill_switch)
        report.stale_bars = 2  # simulate runtime data

        # Format text
        text = format_report_text(report)
        assert isinstance(text, str)
        assert "DAILY TRADING REPORT" in text
        assert "stale" in text or "Stale" in text

        # Format JSON
        raw_json = format_report_json(report)
        parsed = json.loads(raw_json)
        assert parsed["report_date"] == "2026-05-03"
        assert parsed["stale_bars"] == 2

        # Save
        report_dir = tmp_root / "daily_reports"
        path = save_report(report, str(report_dir))
        assert path.exists()
        assert (report_dir / "daily_report_2026-05-03.txt").exists()

        # Verify saved JSON round-trips
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["stale_bars"] == 2
        assert saved["starting_equity"] == 100_000.0
        assert saved["ending_equity"] == 110_000.0

    def test_report_with_only_pending_orders(
        self, tmp_root: Path, kill_switch: KillSwitch
    ) -> None:
        """All pending orders, no fills yet."""
        broker = StubBroker()
        broker._orders = [
            Order(
                timestamp_utc=datetime(2026, 5, 3, 14, 30, tzinfo=timezone.utc),
                strategy_id="test",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                order_type=OrderType.LIMIT,
                limit_price=500.0,
                time_in_force=TimeInForce.DAY,
                client_order_id="coid_pending",
                status=OrderStatus.SUBMITTED,
            ),
        ]
        broker._fills = []
        broker._account = AccountState(
            timestamp_utc=datetime(2026, 5, 3, 20, 0, tzinfo=timezone.utc),
            account_id="test_acct",
            cash=100_000.0,
            buying_power=100_000.0,
            equity=100_000.0,
            positions={},
        )
        ledger = JsonlLedgerStore(str(tmp_root / "ledger"))
        _stub_snapshot(ledger, equity=100_000.0)
        _stub_recon_report(ledger, status="clean")

        report = generate_daily_report(date(2026, 5, 3), ledger, broker, kill_switch)
        assert report.orders_submitted == 1
        assert report.orders_pending == 1
        assert report.orders_filled == 0
        assert report.positions == {}


class TestPaperReviewStatus:
    """Tests for read-only paper review status inspection."""

    def test_inspect_pending_review(self, tmp_path: Path) -> None:
        review_dir = tmp_path / "research" / "paper_reviews" / "prev_001"
        review_dir.mkdir(parents=True)
        review_path = review_dir / "review.json"
        review_path.write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "strategy_manifest_id": "sman_001",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": "2026-05-08T12:00:00+00:00",
                    "evidence_pack_path": str(tmp_path / "research" / "evidence_packs" / "pack_001.json"),
                }
            ),
            encoding="utf-8",
        )

        build_paper_review_evidence_index(tmp_path)
        status = inspect_paper_review_status(tmp_path)

        assert status.status == "PENDING_HUMAN_REVIEW"
        assert status.paper_review_entry_allowed is True
        assert status.manual_review_pending is True
        assert status.review_path == str(review_path)

    def test_inspect_approved_review_requires_reviewer_and_pack(self, tmp_path: Path) -> None:
        review_dir = tmp_path / "research" / "paper_reviews" / "prev_001"
        review_dir.mkdir(parents=True)
        review_path = review_dir / "review.json"
        review_path.write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "strategy_manifest_id": "sman_001",
                    "status": "APPROVED_FOR_PAPER_ONLY",
                    "created_at": "2026-05-08T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        build_paper_review_evidence_index(tmp_path)

        status = inspect_paper_review_status(tmp_path)

        assert status.status == "PAPER_REVIEW_EVIDENCE_INVALID"
        assert status.paper_review_entry_allowed is False
        assert status.manual_review_pending is False
        assert "paper_review_reviewer_missing" in status.summary
        assert status.review_path == str(review_path)

    def test_inspect_manifest_without_review(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / "research" / "manifests" / "sman_001"
        manifest_dir.mkdir(parents=True)
        manifest_path = manifest_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "strategy_candidate_id": "sman_001",
                    "source_candidate_id": "cand_001",
                    "source_experiment_id": "exp_001",
                    "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                    "created_at": "2026-05-08T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        build_paper_review_evidence_index(tmp_path)
        status = inspect_paper_review_status(tmp_path)

        assert status.status == "ELIGIBLE_FOR_PAPER_REVIEW"
        assert status.paper_review_entry_allowed is True
        assert status.manual_review_pending is False
        assert status.manifest_path == str(manifest_path)

    def test_inspect_no_evidence(self, tmp_path: Path) -> None:
        build_paper_review_evidence_index(tmp_path)
        status = inspect_paper_review_status(tmp_path)

        assert status.status == "NO_PAPER_REVIEW_EVIDENCE"
        assert status.paper_review_entry_allowed is False
        assert status.manual_review_pending is False
        assert status.evidence_path == ""

    def test_build_index_and_inspect_blocks_stale_registry(self, tmp_path: Path) -> None:
        review_dir = tmp_path / "research" / "paper_reviews" / "prev_001"
        review_dir.mkdir(parents=True)
        indexed_review = review_dir / "review.json"
        indexed_review.write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": "2026-05-08T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        index = build_paper_review_evidence_index(tmp_path)
        assert index["latest_review_path"] == str(indexed_review)
        assert index["review_count"] == 1
        assert (tmp_path / "research" / "paper_review_index.json").exists()

        newer_review_dir = tmp_path / "research" / "paper_reviews" / "prev_002"
        newer_review_dir.mkdir(parents=True)
        (newer_review_dir / "review.json").write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_002",
                    "status": "REJECTED",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        indexed_status = inspect_paper_review_status(tmp_path)
        scanned_status = inspect_paper_review_status(tmp_path, use_index=False)

        assert indexed_status.status == "REGISTRY_STALE"
        assert indexed_status.paper_review_entry_allowed is False
        assert indexed_status.review_path == ""
        assert scanned_status.status == "REGISTRY_STALE"
        assert scanned_status.paper_review_entry_allowed is False

    def test_rebuild_registry_writes_full_registry_and_legacy_index(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / "research" / "manifests" / "sman_001"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": "sman_001",
                    "source_candidate_id": "cand_001",
                    "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                    "created_at": "2026-05-08T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        index = build_paper_review_evidence_index(tmp_path)

        assert index["manifest_count"] == 1
        assert (tmp_path / "research" / "paper_review_index.json").exists()
        registry_path = tmp_path / "research" / "evidence_registry.json"
        assert registry_path.exists()
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        assert registry["schema_version"] == "evidence_registry_v1"
        assert registry["counts"]["strategy_manifest_count"] == 1

    def test_inspect_registry_rebuilds_when_missing(self, tmp_path: Path) -> None:
        registry = inspect_evidence_registry(tmp_path, use_saved=True, rebuild_if_missing=True)

        assert registry["registry_status"] == "rebuilt"
        assert (tmp_path / "research" / "evidence_registry.json").exists()

    def test_inspect_registry_marks_saved_index_stale_when_new_evidence_arrives(self, tmp_path: Path) -> None:
        build_paper_review_evidence_index(tmp_path)

        review_dir = tmp_path / "research" / "paper_reviews" / "prev_001"
        review_dir.mkdir(parents=True)
        (review_dir / "review.json").write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "strategy_manifest_id": "sman_001",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        registry = inspect_evidence_registry(tmp_path, use_saved=True, rebuild_if_missing=False)

        assert registry["registry_status"] == "stale"

    def test_inspect_registry_marks_saved_index_stale_when_evidence_is_deleted(self, tmp_path: Path) -> None:
        review_dir = tmp_path / "research" / "paper_reviews" / "prev_001"
        review_dir.mkdir(parents=True)
        review_path = review_dir / "review.json"
        review_path.write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": "2026-05-09T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        build_paper_review_evidence_index(tmp_path)

        review_path.unlink()

        registry = inspect_evidence_registry(tmp_path, use_saved=True, rebuild_if_missing=False)
        status = inspect_paper_review_status(tmp_path)

        assert registry["registry_status"] == "stale"
        assert any(note.startswith("missing_artifact:") for note in registry["registry_notes"])
        assert status.status == "REGISTRY_STALE"
        assert status.paper_review_entry_allowed is False
        assert status.review_path == ""

    def test_inspect_registry_marks_saved_index_changed_when_review_content_changes_in_place(self, tmp_path: Path) -> None:
        review_dir = tmp_path / "research" / "paper_reviews" / "prev_001"
        review_dir.mkdir(parents=True)
        review_path = review_dir / "review.json"
        created_at = "2026-05-09T12:00:00+00:00"
        review_path.write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "strategy_manifest_id": "sman_001",
                    "status": "PENDING_HUMAN_REVIEW",
                    "created_at": created_at,
                }
            ),
            encoding="utf-8",
        )

        build_paper_review_evidence_index(tmp_path)
        original_registry = inspect_evidence_registry(tmp_path, use_saved=True, rebuild_if_missing=False)
        original_review = original_registry["evidence"]["paper_reviews"][0]

        review_path.write_text(
            json.dumps(
                {
                    "paper_review_id": "prev_001",
                    "strategy_manifest_id": "sman_001",
                    "status": "APPROVED_FOR_PAPER_ONLY",
                    "created_at": created_at,
                }
            ),
            encoding="utf-8",
        )

        changed_registry = inspect_evidence_registry(tmp_path, use_saved=True, rebuild_if_missing=False)
        status = inspect_paper_review_status(tmp_path)
        live_registry = inspect_evidence_registry(tmp_path, use_saved=False, rebuild_if_missing=False)
        live_review = live_registry["evidence"]["paper_reviews"][0]

        assert changed_registry["registry_status"] == "changed"
        assert any(note.startswith("content_changed:") for note in changed_registry["registry_notes"])
        assert changed_registry["evidence"]["paper_reviews"][0]["status"] == "present"
        assert status.status == "REGISTRY_CHANGED"
        assert status.paper_review_entry_allowed is False
        assert live_review["details"]["status"] == "APPROVED_FOR_PAPER_ONLY"
        assert live_review["created_at"] == created_at
        assert live_review["sha256"] != original_review["sha256"]
        assert live_review["size_bytes"] != 0
        assert live_review["mtime_ns"] >= original_review["mtime_ns"]
