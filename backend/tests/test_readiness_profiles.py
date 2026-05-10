"""Test readiness profiles: simulated, paper, live."""

import os
import io
import json
from pathlib import Path
import pytest
from unittest.mock import patch


class TestSimulatedProfile:
    """Simulated profile: broker and telegram are WARN, not FAIL."""

    def test_broker_credentials_warn_in_simulated(self):
        """Missing broker credentials in simulated profile → WARN, not FAIL."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        check = LiveReadinessGate._check_broker_credentials(profile="simulated")
        assert check.passed is True, "simulated profile should WARN not FAIL for broker"
        assert check.warn is True

    def test_broker_credentials_fail_in_live(self):
        """Missing broker credentials in live profile → FAIL."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        old_key = os.environ.pop("APCA_API_KEY_ID", None)
        old_secret = os.environ.pop("APCA_API_SECRET_KEY", None)
        try:
            check = LiveReadinessGate._check_broker_credentials(profile="live")
            assert check.passed is False, "live profile should FAIL for missing broker"
        finally:
            if old_key:
                os.environ["APCA_API_KEY_ID"] = old_key
            if old_secret:
                os.environ["APCA_API_SECRET_KEY"] = old_secret

    def test_broker_credentials_fail_in_paper(self):
        """Missing broker credentials in paper profile → FAIL."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        with patch.dict(os.environ, {}, clear=True):
            check = LiveReadinessGate._check_broker_credentials(profile="paper")

        assert check.passed is False, "paper profile should FAIL for missing broker credentials"
        assert check.warn is False
        assert "APCA_API_KEY_ID" in check.detail

    def test_broker_connectivity_fail_in_paper_even_when_env_is_set(self):
        """Paper profile requires a reachable paper broker, not just env vars."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        with (
            patch.dict(
                os.environ,
                {
                    "APCA_API_KEY_ID": "paper_key",
                    "APCA_API_SECRET_KEY": "paper_secret",
                },
                clear=True,
            ),
            patch("quant_us.execution.alpaca_broker.AlpacaBroker") as broker_cls,
        ):
            broker_cls.return_value.get_account.side_effect = RuntimeError("paper adapter unavailable")
            check = LiveReadinessGate._check_broker_credentials(profile="paper")

        assert check.passed is False
        assert check.warn is False
        assert "paper adapter unavailable" in check.detail

    def test_telegram_warn_in_simulated(self):
        """Missing Telegram in simulated profile → WARN, not FAIL."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        old_token = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        old_chat = os.environ.pop("TELEGRAM_CHAT_ID", None)
        try:
            check = LiveReadinessGate._check_telegram_connectivity(profile="simulated")
            assert check.passed is True, "simulated should WARN not FAIL for telegram"
            assert check.warn is True
        finally:
            if old_token:
                os.environ["TELEGRAM_BOT_TOKEN"] = old_token
            if old_chat:
                os.environ["TELEGRAM_CHAT_ID"] = old_chat

    def test_paper_30_day_warn_in_simulated(self):
        """Missing validation_state in simulated → WARN."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        check = LiveReadinessGate._check_paper_30_day_clean(None, profile="simulated")
        assert check.passed is True, "simulated should WARN for missing validation_state"
        assert check.warn is True

    def test_paper_30_day_fail_in_live(self):
        """Missing validation_state in live → FAIL."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        check = LiveReadinessGate._check_paper_30_day_clean(None, profile="live")
        assert check.passed is False, "live should FAIL for missing validation_state"

    def test_paper_30_day_fail_when_broker_state_recovery_missing(self, tmp_path: Path):
        """Completed validation still blocks when broker-state recovery evidence is absent."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        state_dir = tmp_path / "reports" / "paper_production"
        state_dir.mkdir(parents=True)
        validation_state = state_dir / "validation_state.json"
        validation_state.write_text(
            json.dumps(
                {
                    "days_required": 30,
                    "days_completed": 30,
                    "consecutive_clean_days": 30,
                    "daily_results": [],
                }
            ),
            encoding="utf-8",
        )

        check = LiveReadinessGate._check_paper_30_day_clean(validation_state, profile="paper")
        assert check.passed is False
        assert "Broker state recovery artifact missing" in check.detail

    def test_paper_30_day_fail_when_broker_state_recovery_incomplete(self, tmp_path: Path):
        """Completed validation still blocks when broker-state recovery is not operationally complete."""
        from quant_us.reports.live_readiness import LiveReadinessGate

        state_dir = tmp_path / "reports" / "paper_production"
        state_dir.mkdir(parents=True)
        validation_state = state_dir / "validation_state.json"
        validation_state.write_text(
            json.dumps(
                {
                    "days_required": 30,
                    "days_completed": 30,
                    "consecutive_clean_days": 30,
                    "daily_results": [],
                }
            ),
            encoding="utf-8",
        )
        audit_dir = tmp_path / "paper_ledger" / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "paper_broker_state_recovery.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "resume_detected": True,
                    "operationally_complete": False,
                    "broker_state_restored": False,
                }
            ),
            encoding="utf-8",
        )

        check = LiveReadinessGate._check_paper_30_day_clean(validation_state, profile="paper")
        assert check.passed is False
        assert "Broker state recovery incomplete (failed)" in check.detail

    def test_cli_simulated_ready_does_not_claim_live_ready(self):
        """Simulated readiness output must be explicit and not say live trading is ready."""
        from quant_us.cli import main
        from quant_us.reports.live_readiness import LiveReadinessReport, ReadinessCheck

        report = LiveReadinessReport(checks=[ReadinessCheck(name="simulated_profile", passed=True)])
        with (
            patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            gate_cls.return_value.check_all.return_value = report
            main(["readiness", "--profile", "simulated"])

        text = stdout.getvalue()
        assert "RESULT: SIMULATED READY." in text
        assert "READY for live trading" not in text

    def test_cli_paper_ready_does_not_claim_live_ready(self):
        """Paper readiness output must be paper-specific."""
        from quant_us.cli import main
        from quant_us.reports.live_readiness import LiveReadinessReport, ReadinessCheck

        report = LiveReadinessReport(checks=[ReadinessCheck(name="paper_profile", passed=True)])
        with (
            patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            gate_cls.return_value.check_all.return_value = report
            main(["readiness", "--profile", "paper"])

        text = stdout.getvalue()
        assert "profile:      paper" in text
        assert "scope:       review-only, no execution" in text
        assert "RESULT: READINESS CHECKS PASSED for paper-stage evaluation only." in text
        assert "READY for live trading" not in text

    def test_cli_small_live_ready_is_readiness_only(self):
        """Small-live readiness output must not look like execution approval."""
        from quant_us.cli import main
        from quant_us.reports.live_readiness import LiveReadinessReport, ReadinessCheck

        checks = [
            ReadinessCheck(name=name, passed=True, detail="ok")
            for name in [
                "paper_30_day_clean",
                "oms_idempotency",
                "kill_switch_coverage",
                "recon_hard_gate",
                "fill_traceability",
                "order_recovery",
                "daily_report",
                "monitoring",
            ]
        ]
        report = LiveReadinessReport(checks=checks)
        with (
            patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            gate_cls.return_value.check_all.return_value = report
            main(["readiness", "--small-live", "--validation-state", "state.json"])

        text = stdout.getvalue()
        assert "RESULT: READINESS EVIDENCE PASSED for small-live manual review only." in text
        assert "scope:  report only, no execution" in text
        assert "GO for small-live trading" not in text

    def test_cli_micro_live_readiness_is_review_only_entry(self, tmp_path):
        """Micro-live readiness has a separate review-only command boundary."""
        from quant_us.cli import main
        from quant_us.reports.live_readiness import LiveReadinessReport, ReadinessCheck

        validation_state = tmp_path / "validation_state.json"
        validation_state.write_text(
            '{"days_required":30,"days_completed":30,"consecutive_clean_days":30,"daily_results":[]}',
            encoding="utf-8",
        )
        report = LiveReadinessReport(
            checks=[ReadinessCheck(name="paper_30_day_clean", passed=True, detail="30/30")]
        )
        with (
            patch("quant_us.reports.live_readiness.LiveReadinessGate") as gate_cls,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            gate_cls.return_value.check_all.return_value = report
            main(["micro-live-readiness", "--validation-state", str(validation_state), "--data-root", str(tmp_path)])

        text = stdout.getvalue()
        assert "Micro-Live Readiness Review" in text
        assert "independent review entry; no start/run/submit action" in text
        assert "manual review only" in text
        assert "cannot start paper or live trading" in text


class TestReadinessCheckWarn:
    """Verify warn field on ReadinessCheck."""

    def test_warn_check_still_passes(self):
        """A WARN check passes but warns."""
        from quant_us.reports.live_readiness import ReadinessCheck
        c = ReadinessCheck(name="test", passed=True, warn=True)
        assert c.passed is True
        assert c.warn is True

    def test_is_ready_skips_warnings(self):
        """is_ready() skips warn-only failures."""
        from quant_us.reports.live_readiness import LiveReadinessReport, ReadinessCheck

        report = LiveReadinessReport()
        report.checks.append(ReadinessCheck(name="a", passed=True, warn=False))
        report.checks.append(ReadinessCheck(name="b", passed=True, warn=True))
        report.checks.append(ReadinessCheck(name="c", passed=False, warn=True))
        assert report.is_ready(), "WARN failures should not block readiness"

    def test_hard_fail_blocks(self):
        """A non-warn FAIL blocks readiness."""
        from quant_us.reports.live_readiness import LiveReadinessReport, ReadinessCheck

        report = LiveReadinessReport()
        report.checks.append(ReadinessCheck(name="a", passed=True, warn=False))
        report.checks.append(ReadinessCheck(name="b", passed=False, warn=False))
        assert not report.is_ready(), "Hard FAIL should block readiness"
