from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from quant_us.cli import main


def _run_cli(argv: list[str]) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        main(argv)
    return out.getvalue()


def _paper_evidence(state: str = "PASS") -> SimpleNamespace:
    return SimpleNamespace(
        readiness_state=state,
        validation_state_path="data/reports/paper_production/validation_state.json",
        gaps=[] if state == "PASS" else ["validation_state_missing"],
    )


def _review(entry_allowed: bool = True, manual_pending: bool = False) -> dict[str, object]:
    return {
        "registry_state": "PASS",
        "entry_allowed": entry_allowed,
        "manual_pending": manual_pending,
        "summary": "approved paper-review evidence" if entry_allowed else "paper review missing",
    }


def test_pre_live_paper_submit_preflight_blocks_external_requirements_without_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    out = io.StringIO()
    with (
        redirect_stdout(out),
        patch("quant_us.cli._paper_review_overview", return_value=_review(entry_allowed=False)),
        patch("quant_us.reports.paper_validation.inspect_paper_validation_evidence", return_value=_paper_evidence()),
        patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent,
        pytest.raises(SystemExit) as raised,
    ):
        main(
            [
                "pre-live",
                "paper-submit-preflight",
                "--as-of",
                "2026-05-10T14:00:00+00:00",
            ]
        )
    output = out.getvalue()

    assert raised.value.code == 1
    assert "Paper Submit Preflight" in output
    assert "submit_order_path: DISABLED" in output
    assert "market_hours: BLOCKED" in output
    assert "paper_credentials: BLOCKED" in output
    assert "paper_review_evidence: BLOCKED" in output
    assert "RESULT: BLOCKED" in output
    assert "blocking_reasons: market_hours, paper_credentials, paper_review_evidence" in output
    handle_intent.assert_not_called()


def test_pre_live_paper_submit_preflight_passes_only_as_review_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key-1234")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret-1234")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    with (
        patch("quant_us.cli._paper_review_overview", return_value=_review()),
        patch("quant_us.reports.paper_validation.inspect_paper_validation_evidence", return_value=_paper_evidence()),
        patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent,
    ):
        output = _run_cli(
            [
                "pre-live",
                "paper-submit-preflight",
                "--as-of",
                "2026-05-11T14:00:00+00:00",
            ]
        )

    assert "market_hours: PASS" in output
    assert "paper_credentials: PASS" in output
    assert "paper_review_evidence: PASS" in output
    assert "RESULT: PASS" in output
    assert "No broker client or runtime submit path is created." in output
    handle_intent.assert_not_called()


def test_pre_live_next_step_prints_review_only_next_action_without_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    report = SimpleNamespace(
        checks=[SimpleNamespace(name="simulated_gate", passed=True, warn=False)],
        is_ready=lambda: True,
    )

    with (
        patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls,
        patch("quant_us.cli._paper_review_overview", return_value=_review()),
        patch("quant_us.reports.paper_validation.inspect_paper_validation_evidence", return_value=_paper_evidence()),
        patch("quant_us.execution.oms.OrderManagementSystem.handle_intent") as handle_intent,
    ):
        gate_cls.return_value.check_all.return_value = report
        output = _run_cli(["pre-live", "next-step", "--as-of", "2026-05-11T14:00:00+00:00"])

    assert "Pre-Live Next Step" in output
    assert "scope:       review-only, no execution" in output
    assert "live_state:   FROZEN" in output
    assert "paper_credentials: MISSING" in output
    assert "next_action:" in output
    assert "readiness --profile paper" in output
    handle_intent.assert_not_called()
