from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quant_us.cli import main
from quant_us.reports.portfolio_observability import inspect_portfolio_observability


def _run_cli(argv: list[str]) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        main(argv)
    return out.getvalue()


def _write_daily_report(data_root: Path) -> None:
    report_dir = data_root / "paper_ledger" / "daily_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "daily_report_2026-05-09.json").write_text(
        json.dumps(
            {
                "report_date": "2026-05-09",
                "generated_at": "2026-05-09T21:00:00+00:00",
                "ending_equity": 100000.0,
                "daily_pnl": 0.0,
                "orders_submitted": 0,
                "orders_filled": 0,
                "reconciliation_status": "clean",
                "kill_switch_triggered": False,
            }
        ),
        encoding="utf-8",
    )


def _write_portfolio_observability(data_root: Path) -> None:
    report_dir = data_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "portfolio_observability.json").write_text(
        json.dumps(
            {
                "multi_strategy": {
                    "status": "PASS",
                    "strategies": ["trend_macd", "reversion_rsi"],
                },
                "multi_timeframe": {
                    "status": "PASS",
                    "timeframes": ["1d", "1h"],
                },
                "pnl_attribution": {
                    "status": "PASS",
                    "rows": [
                        {"strategy_id": "trend_macd", "pnl": 12.5},
                        {"strategy_id": "reversion_rsi", "pnl": -2.0},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def test_live_start_readiness_pass_still_does_not_start_live_loop(tmp_path: Path) -> None:
    with (
        patch("quant_us.live.runtime.LiveReadinessGate") as gate_cls,
        patch("quant_us.cli._start_live_production_loop") as start_live_loop,
        patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent,
    ):
        gate_cls.return_value.check_all.return_value.is_ready.return_value = True
        with pytest.raises(SystemExit) as raised:
            _run_cli(
                [
                    "live",
                    "--data-root",
                    str(tmp_path),
                    "start",
                    "--symbols",
                    "SPY",
                    "--allow-live-orders",
                    "--confirm-live",
                ]
            )

    assert raised.value.code == 1
    start_live_loop.assert_not_called()
    handle_intent.assert_not_called()


def test_top_level_readiness_report_does_not_submit_orders(tmp_path: Path) -> None:
    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(["readiness", "--profile", "live", "--data-root", str(tmp_path)])

    assert "report only, no execution" in output
    handle_intent.assert_not_called()


def test_paper_validation_report_does_not_submit_orders(tmp_path: Path) -> None:
    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(["report", "paper-validation", "--data-root", str(tmp_path)])

    assert "Review evidence only" in output
    assert "minute_data_quality:" in output
    handle_intent.assert_not_called()


def test_daily_paper_report_does_not_submit_orders(tmp_path: Path) -> None:
    _write_daily_report(tmp_path)

    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(["report", "daily", "--latest", "--data-root", str(tmp_path)])

    assert "Reporting only" in output
    handle_intent.assert_not_called()


def test_shadow_live_report_does_not_submit_orders(tmp_path: Path) -> None:
    report_dir = tmp_path / "shadow_ledger"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "daily_shadow_report_2026-05-09.json").write_text(
        json.dumps(
            {
                "run_id": "shadow-report-test",
                "generated_at": "2026-05-09T21:00:00+00:00",
                "shadow_order_count": 1,
                "shadow_fill_count": 0,
                "real_submit_count": 0,
                "no_real_order_submitted": True,
            }
        ),
        encoding="utf-8",
    )

    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(["shadow-live", "report", "--latest", "--data-root", str(tmp_path)])

    assert "Real Submit Count" in output
    assert "**0**" in output
    handle_intent.assert_not_called()


def test_overview_distinguishes_simulated_paper_and_live_without_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_portfolio_observability(tmp_path)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    report = SimpleNamespace(
        checks=[SimpleNamespace(name="simulated_gate", passed=True, warn=False)],
        is_ready=lambda: True,
    )
    with (
        patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls,
        patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent,
    ):
        gate_cls.return_value.check_all.return_value = report
        output = _run_cli(["overview", "--data-root", str(tmp_path), "--strategy", "etf_rotation"])

    assert "minute_data_quality:" in output
    assert "simulated: READY" in output
    assert "paper:     BLOCKED_CREDENTIALS" in output
    assert "live:      FROZEN" in output
    assert "multi_strategy:      PASS (strategies=2)" in output
    assert "multi_timeframe:     PASS (timeframes=2)" in output
    assert "pnl_attribution:     PASS (rows=2)" in output
    assert "paper_submit_gates:  BLOCKED_BY_DEFAULT" in output
    assert "next_paper_command:  python -m quant_us.cli paper" in output
    assert "next_action:" in output
    handle_intent.assert_not_called()


def test_paper_validation_report_shows_portfolio_observability_without_submit(tmp_path: Path) -> None:
    _write_portfolio_observability(tmp_path)

    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(["report", "paper-validation", "--data-root", str(tmp_path)])

    assert "minute_data_quality:" in output
    assert "portfolio_observability:" in output
    assert "multi_strategy: PASS (strategies=2)" in output
    assert "multi_timeframe: PASS (timeframes=2)" in output
    assert "pnl_attribution: PASS (rows=2)" in output
    assert "live_state: FROZEN" in output
    assert "paper_submit_gates: BLOCKED_BY_DEFAULT" in output
    assert "next_paper_command: python -m quant_us.cli paper" in output
    handle_intent.assert_not_called()


def test_minute_quality_report_does_not_submit_orders(tmp_path: Path) -> None:
    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(["report", "minute-quality", "--data-root", str(tmp_path)])

    assert "Minute Data Quality Report" in output
    assert "report only, no execution" in output
    handle_intent.assert_not_called()


def test_paper_readiness_accepts_portfolio_strategy_without_submit(tmp_path: Path) -> None:
    with patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent:
        output = _run_cli(
            [
                "paper",
                "--data-root",
                str(tmp_path),
                "--strategy",
                "portfolio",
                "--broker",
                "simulated",
            ]
        )

    assert "Paper trading readiness: strategy=portfolio, broker=simulated" in output
    assert "submit-orders:  False" in output
    handle_intent.assert_not_called()


def test_portfolio_observability_derives_from_paper_manifest_and_attribution(tmp_path: Path) -> None:
    audit_dir = tmp_path / "paper_ledger" / "audit"
    report_dir = tmp_path / "paper_ledger" / "daily_reports"
    audit_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (audit_dir / "paper_session_manifest.json").write_text(
        json.dumps(
            {
                "strategies": [
                    {"strategy_id": "trend_momentum", "timeframe": "1d"},
                    {"strategy_id": "short_reversion", "timeframe": "15m"},
                ],
                "strategy_ids": ["portfolio", "trend_momentum", "short_reversion"],
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "strategy_attribution_2026-05-10.json").write_text(
        json.dumps(
            {
                "by_strategy": {
                    "trend_momentum": {"filled_notional": 1000.0},
                    "short_reversion": {"filled_notional": 500.0},
                }
            }
        ),
        encoding="utf-8",
    )

    status = inspect_portfolio_observability(tmp_path).to_dict()

    assert status["multi_strategy"]["status"] == "PASS"
    assert status["multi_strategy"]["strategy_count"] == 2
    assert status["multi_timeframe"]["status"] == "PASS"
    assert status["multi_timeframe"]["timeframe_count"] == 2
    assert status["pnl_attribution"]["status"] == "PASS"
    assert status["pnl_attribution"]["row_count"] == 2


def test_overview_reports_paper_review_block_when_credentials_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "paper_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper_secret")

    report = SimpleNamespace(
        checks=[SimpleNamespace(name="simulated_gate", passed=True, warn=False)],
        is_ready=lambda: True,
    )
    with patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls:
        gate_cls.return_value.check_all.return_value = report
        output = _run_cli(["overview", "--data-root", str(tmp_path)])

    assert "paper:     BLOCKED_REVIEW" in output
    assert "credentials: PRESENT" in output
    assert "review:      BLOCKED_REGISTRY_MISSING" in output
