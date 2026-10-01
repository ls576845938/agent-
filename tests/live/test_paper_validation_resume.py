from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Fill, Order, PortfolioSnapshot
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from quant_us.reports.paper_validation import check_paper_validation_preflight
from scripts.run_paper_validation import save_report

UTC = timezone.utc


def _broker_state_recovery_artifact(ledger_root: Path) -> dict[str, object]:
    return json.loads(
        (ledger_root / "audit" / "paper_broker_state_recovery.json").read_text(encoding="utf-8")
    )


def _write_preflight_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path
    ledger_root = data_root / "paper_ledger"
    market_data_dir = (
        data_root
        / "raw"
        / "vendor=yfinance"
        / "asset_class=equity"
        / "bar_size=1d"
        / "symbol=AAPL"
    )
    market_data_dir.mkdir(parents=True, exist_ok=True)
    (market_data_dir / "date=2026-05-08.parquet").write_bytes(b"fixture")

    state_path = data_root / "reports" / "paper_production" / "validation_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "symbols": ["AAPL"],
                "data_root": str(data_root),
                "source": "yfinance",
                "bar_size": "1d",
                "days_required": 30,
                "days_completed": 30,
                "consecutive_clean_days": 30,
                "daily_results": [{"date": "2026-05-08", "errors": [], "recon": "PASS"}],
            }
        ),
        encoding="utf-8",
    )

    daily_report_dir = ledger_root / "daily_reports"
    daily_report_dir.mkdir(parents=True, exist_ok=True)
    (daily_report_dir / "daily_report_2026-05-08.json").write_text(
        json.dumps(
            {
                "report_date": "2026-05-08",
                "orders_submitted": 0,
                "orders_filled": 0,
                "reconciliation_status": "clean",
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    audit_dir = ledger_root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "paper_session_manifest.json").write_text(
        json.dumps(
            {
                "session_id": "sess_001",
                "mode": "paper",
                "paper_broker": "simulated",
                "broker_backend": "simulated",
                "submit_orders": False,
                "no_real_order_submission_proof": {
                    "status": "PASS",
                    "real_order_submission": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (audit_dir / "paper_broker_adapter_startup_sync.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "no_submit_proof": {
                    "submit_call_count_available": True,
                    "submit_order_invoked": False,
                    "write_method_invoked": False,
                    "submit_call_count_delta": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (audit_dir / "paper_broker_state_recovery.json").write_text(
        json.dumps(
            {
                "status": "verified",
                "resume_detected": False,
                "operationally_complete": True,
                "broker_state_restored": False,
                "broker_state_verified": True,
            }
        ),
        encoding="utf-8",
    )

    recon_dir = ledger_root / "reconciliation"
    recon_dir.mkdir(parents=True, exist_ok=True)
    (recon_dir / "recon_20260508_210000.json").write_text(
        json.dumps(
            {
                "status": "clean",
                "cash_diff": 0.0,
                "position_diffs": {},
                "order_diffs": {},
                "fill_diffs": {},
                "halt_new_orders": False,
            }
        ),
        encoding="utf-8",
    )
    (recon_dir / "ledger_recon_artifact_aaaaaaaaaaaaaaaa.json").write_text(
        json.dumps(
            {
                "artifact_hash": "aaaaaaaaaaaaaaaa",
                "fills": {"duplicate_fill_count": 0, "conflict_fill_count": 0},
                "hashes": {"fills_hash": "bbbbbbbbbbbbbbbb"},
                "pnl": {"net_pnl": 0.0},
            }
        ),
        encoding="utf-8",
    )
    return data_root, state_path


def test_paper_validation_report_stays_incomplete_when_recovery_is_not_operational(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "validation_report.json"
    state = {
        "days_required": 30,
        "days_completed": 30,
        "consecutive_clean_days": 30,
        "daily_results": [],
        "recovery_summary": {
            "required": True,
            "status": "failed",
            "operationally_complete": False,
            "resume_restores_broker_state": False,
            "resume_restores_validation_counters": True,
        },
    }

    save_report(state, report_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "BLOCKED"
    assert report["passed"] is False


def test_paper_validation_report_stays_incomplete_when_recovery_artifact_path_is_missing(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "validation_report.json"
    state = {
        "days_required": 30,
        "days_completed": 30,
        "consecutive_clean_days": 30,
        "daily_results": [],
        "recovery_summary": {
            "required": False,
            "status": "restored",
            "operationally_complete": True,
            "resume_restores_broker_state": True,
            "resume_restores_validation_counters": True,
        },
        "evidence": {},
    }

    save_report(state, report_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "BLOCKED"
    assert report["passed"] is False


def test_paper_validation_preflight_passes_when_evidence_contract_is_complete(tmp_path: Path) -> None:
    data_root, state_path = _write_preflight_artifacts(tmp_path)

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=data_root / "paper_ledger",
        validation_state_path=state_path,
    )

    assert preflight.status == "PASS"
    assert preflight.blocking_reasons == []
    assert [check.name for check in preflight.checks] == [
        "market_data",
        "validation_state_path",
        "daily_report_dir",
        "startup_sync",
        "broker_state_recovery",
        "ledger_reconciliation",
        "read_only_no_submit",
    ]


def test_paper_validation_preflight_blocks_when_recovery_artifact_is_missing(tmp_path: Path) -> None:
    data_root, state_path = _write_preflight_artifacts(tmp_path)
    (data_root / "paper_ledger" / "audit" / "paper_broker_state_recovery.json").unlink()

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=data_root / "paper_ledger",
        validation_state_path=state_path,
    )

    assert preflight.status == "BLOCKED"
    assert "broker_state_recovery_missing" in preflight.blocking_reasons


def test_paper_validation_preflight_blocks_when_startup_sync_is_missing(tmp_path: Path) -> None:
    data_root, state_path = _write_preflight_artifacts(tmp_path)
    (data_root / "paper_ledger" / "audit" / "paper_broker_adapter_startup_sync.json").unlink()

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=data_root / "paper_ledger",
        validation_state_path=state_path,
    )

    assert preflight.status == "BLOCKED"
    assert "startup_sync_missing" in preflight.blocking_reasons


def test_paper_validation_preflight_blocks_when_ledger_recon_artifact_is_missing(tmp_path: Path) -> None:
    data_root, state_path = _write_preflight_artifacts(tmp_path)
    (
        data_root
        / "paper_ledger"
        / "reconciliation"
        / "ledger_recon_artifact_aaaaaaaaaaaaaaaa.json"
    ).unlink()

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=data_root / "paper_ledger",
        validation_state_path=state_path,
    )

    assert preflight.status == "BLOCKED"
    assert "ledger_reconciliation_artifact_missing" in preflight.blocking_reasons


def test_paper_validation_preflight_blocks_when_validation_days_are_incomplete(tmp_path: Path) -> None:
    data_root, state_path = _write_preflight_artifacts(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["days_completed"] = 12
    state["consecutive_clean_days"] = 12
    state_path.write_text(json.dumps(state), encoding="utf-8")

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=data_root / "paper_ledger",
        validation_state_path=state_path,
    )

    assert preflight.status == "BLOCKED"
    assert "validation_days_incomplete" in preflight.blocking_reasons


def _write_runtime_validation_state(data_root: Path) -> Path:
    market_data_dir = (
        data_root
        / "raw"
        / "vendor=yfinance"
        / "asset_class=equity"
        / "bar_size=1m"
        / "symbol=SPY"
    )
    market_data_dir.mkdir(parents=True, exist_ok=True)
    (market_data_dir / "date=2026-05-08.parquet").write_bytes(b"fixture")

    state_path = data_root / "reports" / "paper_production" / "validation_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "symbols": ["SPY"],
                "data_root": str(data_root),
                "source": "yfinance",
                "bar_size": "1m",
                "days_required": 30,
                "days_completed": 30,
                "consecutive_clean_days": 30,
                "daily_results": [],
            }
        ),
        encoding="utf-8",
    )
    return state_path


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_validation_preflight_passes_with_runtime_generated_evidence(
    _mock_loop: object,
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    ledger_root = data_root / "paper_ledger"
    state_path = _write_runtime_validation_state(data_root)
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            data_root=str(data_root),
            ledger_root=str(ledger_root),
            bar_size="1m",
            reconcile_on_start=True,
            reconcile_on_close=True,
            submit_orders=False,
        )
    )

    runtime.bootstrap()
    runtime.on_session_close()

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=ledger_root,
        validation_state_path=state_path,
        source="yfinance",
        bar_size="1m",
    )
    startup = json.loads(
        (ledger_root / "audit" / "paper_broker_adapter_startup_sync.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (ledger_root / "audit" / "paper_session_manifest.json").read_text(encoding="utf-8")
    )
    recon_artifacts = list((ledger_root / "reconciliation").glob("ledger_recon_artifact_*.json"))

    assert preflight.status == "PASS"
    assert preflight.blocking_reasons == []
    assert startup["status"] == "ok"
    assert startup["required"] is False
    assert startup["no_submit_proof"]["submit_order_invoked"] is False
    assert manifest["submit_orders"] is False
    assert manifest["no_real_order_submission_proof"]["status"] == "PASS"
    assert manifest["market_data_symbols_evidence"]["symbols"] == ["SPY"]
    assert recon_artifacts
    assert json.loads(recon_artifacts[-1].read_text(encoding="utf-8"))["artifact_hash"]


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_validation_preflight_blocks_when_runtime_startup_evidence_is_missing(
    _mock_loop: object,
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    ledger_root = data_root / "paper_ledger"
    state_path = _write_runtime_validation_state(data_root)
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            data_root=str(data_root),
            ledger_root=str(ledger_root),
            bar_size="1m",
            reconcile_on_start=True,
            reconcile_on_close=True,
            submit_orders=False,
        )
    )

    runtime.bootstrap()
    runtime.on_session_close()
    (ledger_root / "audit" / "paper_broker_adapter_startup_sync.json").unlink()

    preflight = check_paper_validation_preflight(
        data_root,
        ledger_root=ledger_root,
        validation_state_path=state_path,
        source="yfinance",
        bar_size="1m",
    )

    assert preflight.status == "BLOCKED"
    assert "startup_sync_missing" in preflight.blocking_reasons


def test_paper_trading_loop_restores_state_from_ledger_on_resume(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    ledger = JsonlLedgerStore(ledger_root)
    ledger.append_order(
        Order(
            timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
            strategy_id="resume_fixture",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=5.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="resume_client_001",
            order_id="resume_order_001",
            status=OrderStatus.FILLED,
        )
    )
    ledger.append_fill(
        Fill(
            order_id="resume_order_001",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=5.0,
            price=200.0,
            commission=1.0,
            filled_at=datetime(2026, 5, 4, 14, 31, tzinfo=UTC),
            broker="paper",
            fill_id="resume_fill_001",
        )
    )
    ledger.append_snapshot(
        PortfolioSnapshot(
            timestamp_utc=datetime(2026, 5, 4, 20, 0, tzinfo=UTC),
            equity=100_100.0,
            cash=98_999.0,
            gross_exposure=1_100.0,
            net_exposure=1_100.0,
            daily_pnl=100.0,
            drawdown=0.0,
        )
    )

    loop = PaperTradingLoop(
        config=PaperTradingConfig(
            initial_cash=100_000.0,
            ledger_root=str(ledger_root),
        )
    )

    assert loop.broker.cash == 98_999.0
    assert "AAPL" in loop.broker.positions
    assert loop.broker.positions["AAPL"].quantity == 5.0
    assert len(loop.broker.orders) == 1
    assert len(loop.broker.fills) == 1
    assert loop.is_healthy() is True

    artifact = _broker_state_recovery_artifact(ledger_root)
    assert artifact["status"] == "restored"
    assert artifact["resume_detected"] is True
    assert artifact["operationally_complete"] is True
    assert artifact["broker_state_restored"] is True
