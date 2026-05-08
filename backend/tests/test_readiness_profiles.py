"""Test readiness profiles: simulated, paper, live."""

import os
import pytest


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
