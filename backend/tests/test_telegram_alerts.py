"""Tests for Telegram alert service and env config loading.

Covers:
- TelegramAlertService.send() URL and payload construction (mocked HTTP)
- All template methods produce non-empty messages
- Disabled state (alert service with enabled=False skips sends)
- load_telegram_config_from_env() with env vars present/absent/partial
- daily_report() output format
- kill_switch_triggered() output format
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from quant_us.monitoring.telegram_alerts import (
    AlertPriority,
    TelegramAlertService,
    TelegramConfig,
    load_telegram_config_from_env,
)


class TelegramAlertServiceSendTests(unittest.TestCase):
    """Verify TelegramAlertService.send() constructs correct HTTP request."""

    def setUp(self):
        self.config = TelegramConfig(
            bot_token="test_bot_token_123",
            chat_id="test_chat_456",
            enabled=True,
        )
        self.service = TelegramAlertService(self.config)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_send_constructs_correct_url_and_payload(self, mock_urlopen):
        """Verify URL and payload are correctly built."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        result = self.service.send("Hello from test", priority=AlertPriority.LOW)

        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 1)

        call_args, call_kwargs = mock_urlopen.call_args
        req = call_args[0]

        # Verify URL
        expected_url = "https://api.telegram.org/bottest_bot_token_123/sendMessage"
        self.assertEqual(req.full_url, expected_url)

        # Verify payload
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "test_chat_456")
        self.assertIn("Hello from test", payload["text"])
        self.assertEqual(payload["parse_mode"], "Markdown")

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_send_with_critical_priority_includes_emoji(self, mock_urlopen):
        """Verify critical priority prefix appears in message text."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.send("Critical alert!", priority=AlertPriority.CRITICAL)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))

        self.assertIn("CRITICAL", payload["text"])

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_send_retries_on_failure(self, mock_urlopen):
        """Verify send retries when urlopen raises an exception."""
        config = TelegramConfig(
            bot_token="abc",
            chat_id="def",
            enabled=True,
            retry_attempts=2,
            retry_delay_seconds=0.01,
        )
        service = TelegramAlertService(config)

        from urllib.error import URLError

        # First raise URLError, then succeed
        ok_response = MagicMock()
        ok_response.status = 200
        mock_urlopen.side_effect = [URLError("timeout"), ok_response]

        result = service.send("Retry test")

        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 2)


class TelegramAlertDisabledTests(unittest.TestCase):
    """Verify disabled alert service does not send."""

    def setUp(self):
        self.config = TelegramConfig(enabled=False)
        self.service = TelegramAlertService(self.config)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_disabled_service_skips_send(self, mock_urlopen):
        """When enabled=False, send() returns False and does not call urlopen."""
        result = self.service.send("Should not send")
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_template_methods_return_false_when_disabled(self, mock_urlopen):
        """All template methods return False when alerts are disabled (no HTTP calls made)."""
        service = TelegramAlertService(TelegramConfig(enabled=False))
        self.assertFalse(service.daily_report("2024-01-01", 100000.0, 500.0, 0.5, 5, 10))
        self.assertFalse(service.kill_switch_triggered("test", 100000.0, 5.0))
        self.assertFalse(service.order_failure("AAPL", "BUY", 10.0, "no reason", 3))
        self.assertFalse(service.broker_disconnect("paper", 30.0))
        self.assertFalse(service.reconciliation_mismatch("AAPL", 100.0, 99.0, 1.0))
        self.assertFalse(service.data_delay(600.0, 300.0))
        self.assertFalse(service.daily_loss_limit(5.0, 3.0))
        mock_urlopen.assert_not_called()


class TelegramAlertTemplateTests(unittest.TestCase):
    """Verify all template methods produce valid non-empty messages."""

    def setUp(self):
        self.config = TelegramConfig(
            bot_token="t",
            chat_id="c",
            enabled=True,
            retry_attempts=0,
        )
        self.service = TelegramAlertService(self.config)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_daily_report_format(self, mock_urlopen):
        """Verify daily_report builds a message containing expected fields."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.daily_report("2024-06-15", 105000.0, 2500.0, 2.45, 5, 12)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("Daily Report", text)
        self.assertIn("2024-06-15", text)
        self.assertIn("105,000.00", text)
        self.assertIn("+$2,500.00", text)
        self.assertIn("+2.45%", text)
        self.assertIn("5", text)  # positions
        self.assertIn("12", text)  # orders

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_daily_report_negative_pnl(self, mock_urlopen):
        """Verify negative PnL shows minus sign."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.daily_report("2024-06-15", 95000.0, -5000.0, -5.0, 3, 8)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("$-5,000.00", text)
        self.assertIn("-5.00%", text)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_kill_switch_triggered_format(self, mock_urlopen):
        """Verify kill_switch_triggered builds a CRITICAL alert with drawdown info."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.kill_switch_triggered("max_drawdown_exceeded", 85000.0, 15.3)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("KILL SWITCH TRIGGERED", text)
        self.assertIn("max_drawdown_exceeded", text)
        self.assertIn("85,000.00", text)
        self.assertIn("15.30%", text)
        self.assertIn("blocked", text.lower())

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_order_failure_format(self, mock_urlopen):
        """Verify order_failure builds message with order details."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.order_failure("TSLA", "SELL", 50.0, "insufficient_liquidity", 2)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("Order Failure", text)
        self.assertIn("TSLA", text)
        self.assertIn("SELL", text)
        self.assertIn("50.0000", text)
        self.assertIn("insufficient_liquidity", text)
        self.assertIn("2", text)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_broker_disconnect_format(self, mock_urlopen):
        """Verify broker_disconnect builds message with downtime."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.broker_disconnect("ibkr", 120.0)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("Broker Disconnected", text)
        self.assertIn("ibkr", text)
        self.assertIn("120", text)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_reconciliation_mismatch_format(self, mock_urlopen):
        """Verify reconciliation_mismatch builds message with position diff."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.reconciliation_mismatch("AAPL", 100.0, 99.0, 1.0)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("Reconciliation Mismatch", text)
        self.assertIn("100.0000", text)
        self.assertIn("99.0000", text)
        self.assertIn("1.0000", text)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_data_delay_format(self, mock_urlopen):
        """Verify data_delay builds message with delay info."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.data_delay(600.0, 300.0)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("Data Delay", text)
        self.assertIn("600", text)
        self.assertIn("300", text)

    @patch("quant_us.monitoring.telegram_alerts.request.urlopen")
    def test_daily_loss_limit_format(self, mock_urlopen):
        """Verify daily_loss_limit builds message with loss and limit pct."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        self.service.daily_loss_limit(5.5, 3.0)

        call_args, _ = mock_urlopen.call_args
        req = call_args[0]
        payload = json.loads(req.data.decode("utf-8"))
        text = payload["text"]

        self.assertIn("Daily Loss Limit", text)
        self.assertIn("5.50%", text)
        self.assertIn("3.00%", text)


class TelegramLoadConfigFromEnvTests(unittest.TestCase):
    """Verify load_telegram_config_from_env() behavior."""

    def test_returns_none_when_no_env_vars(self):
        """When neither TELEGRAM_BOT_TOKEN nor TELEGRAM_CHAT_ID is set, return None."""
        with patch.dict(os.environ, {}, clear=True):
            result = load_telegram_config_from_env()
        self.assertIsNone(result)

    def test_returns_disabled_config_when_only_bot_token(self):
        """When only TELEGRAM_BOT_TOKEN is set, return disabled TelegramConfig."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "my_token"}, clear=True):
            result = load_telegram_config_from_env()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.bot_token, "my_token")
        self.assertEqual(result.chat_id, "")
        self.assertFalse(result.enabled)

    def test_returns_disabled_config_when_only_chat_id(self):
        """When only TELEGRAM_CHAT_ID is set, return disabled TelegramConfig."""
        with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "my_chat"}, clear=True):
            result = load_telegram_config_from_env()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.bot_token, "")
        self.assertEqual(result.chat_id, "my_chat")
        self.assertFalse(result.enabled)

    def test_returns_enabled_config_when_both_set(self):
        """When both env vars are set, return enabled TelegramConfig."""
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "real_token", "TELEGRAM_CHAT_ID": "real_chat"},
            clear=True,
        ):
            result = load_telegram_config_from_env()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.bot_token, "real_token")
        self.assertEqual(result.chat_id, "real_chat")
        self.assertTrue(result.enabled)


class PaperTradingLoopAlertIntegrationTests(unittest.TestCase):
    """Verify PaperTradingLoop auto-loads alerts from env."""

    def test_alerts_auto_loaded_from_env(self):
        """When TELEGRAM_BOT_TOKEN is set, PaperTradingLoop auto-configures alerts."""
        from quant_us.live.paper_trading_loop import PaperTradingLoop

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "env_token", "TELEGRAM_CHAT_ID": "env_chat"},
            clear=True,
        ):
            loop = PaperTradingLoop()
        self.assertTrue(loop.config.alerts_enabled)
        self.assertIsNotNone(loop.alerts)
        self.assertTrue(loop.alerts.config.enabled)
        self.assertEqual(loop.alerts.config.bot_token, "env_token")
        self.assertEqual(loop.alerts.config.chat_id, "env_chat")

    def test_explicit_alerts_override_env(self):
        """When alerts is explicitly passed, env vars are ignored."""
        from quant_us.live.paper_trading_loop import PaperTradingLoop

        custom_config = TelegramConfig(bot_token="explicit", chat_id="explicit", enabled=True)
        custom_service = TelegramAlertService(custom_config)

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "env_token", "TELEGRAM_CHAT_ID": "env_chat"},
            clear=True,
        ):
            loop = PaperTradingLoop(alerts=custom_service)

        self.assertEqual(loop.alerts.config.bot_token, "explicit")

    def test_explicit_none_alerts_still_checks_env(self):
        """When alerts=None explicitly, env is still checked."""
        from quant_us.live.paper_trading_loop import PaperTradingLoop

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""},
            clear=True,
        ):
            loop = PaperTradingLoop(alerts=None)
        self.assertFalse(loop.config.alerts_enabled)

    def test_backward_compat_no_env(self):
        """When env vars are absent, PaperTradingLoop creates no-op alerts (backward compat)."""
        from quant_us.live.paper_trading_loop import PaperTradingLoop

        with patch.dict(os.environ, {}, clear=True):
            loop = PaperTradingLoop()
        self.assertFalse(loop.config.alerts_enabled)
        self.assertFalse(loop.alerts.config.enabled)


if __name__ == "__main__":
    unittest.main()
