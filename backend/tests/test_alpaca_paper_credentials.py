"""Test Alpaca Paper credential check and endpoint guard."""

import os
import pytest


class TestAlpacaBrokerEndpointGuard:
    """AlpacaBrokerConfig must reject mismatched paper/base_url."""

    def test_paper_default_is_safe(self):
        """Default config points to paper endpoint."""
        from quant_us.execution.alpaca_broker import AlpacaBrokerConfig, PAPER_BASE_URL

        c = AlpacaBrokerConfig(api_key="test", api_secret="test")
        assert c.paper is True
        assert PAPER_BASE_URL in c.base_url

    def test_paper_with_live_url_raises(self):
        """paper=True with live URL must raise ValueError."""
        from quant_us.execution.alpaca_broker import AlpacaBrokerConfig

        with pytest.raises(ValueError, match="paper.*endpoint"):
            AlpacaBrokerConfig(api_key="test", api_secret="test", paper=True,
                               base_url="https://api.alpaca.markets")

    def test_live_with_paper_url_raises(self):
        """paper=False with paper URL must raise ValueError."""
        from quant_us.execution.alpaca_broker import AlpacaBrokerConfig

        with pytest.raises(ValueError, match="live.*endpoint"):
            AlpacaBrokerConfig(api_key="test", api_secret="test", paper=False)

    def test_explicit_paper_url_ok(self):
        """Explicit paper URL with paper=True is fine."""
        from quant_us.execution.alpaca_broker import AlpacaBrokerConfig

        c = AlpacaBrokerConfig(api_key="test", api_secret="test", paper=True,
                               base_url="https://paper-api.alpaca.markets")
        assert c.paper is True


class TestSecretMasking:
    """Secret masking must only show last 4 characters."""

    def test_mask_short_key(self):
        from quant_us.cli import _mask_key

        assert _mask_key("ab") == "****"

    def test_mask_normal_key(self):
        from quant_us.cli import _mask_key

        masked = _mask_key("PKABCDEFGHIJKLMNOP")
        assert masked.endswith("MNOP")
        assert "ABCD" not in masked

    def test_mask_empty(self):
        from quant_us.cli import _mask_key

        assert _mask_key("") == "****"


class TestCredentialCheck:
    """Credential check must not submit orders, must handle missing keys."""

    def test_credential_check_missing_keys(self, capsys):
        """Missing credentials should print BLOCKED, not raise."""
        from quant_us.cli import _check_alpaca_credentials

        old_key = os.environ.pop("APCA_API_KEY_ID", None)
        old_secret = os.environ.pop("APCA_API_SECRET_KEY", None)
        try:
            _check_alpaca_credentials("paper")
            captured = capsys.readouterr()
            assert "BLOCKED" in captured.out
            assert "not set" in captured.out
        finally:
            if old_key: os.environ["APCA_API_KEY_ID"] = old_key
            if old_secret: os.environ["APCA_API_SECRET_KEY"] = old_secret

    def test_key_not_leaked_in_output(self, capsys):
        """Masked key must not appear in output."""
        from quant_us.cli import _mask_key

        key = "PK_MY_SECRET_KEY_1234"
        masked = _mask_key(key)
        assert "MY_SECRET" not in masked
        assert masked.endswith("1234")


class TestPaperCommandsParse:
    """Verify paper smoke-test and start commands parse correctly."""

    def test_smoke_test_parses(self):
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["paper", "smoke-test", "--symbols", "SPY,QQQ"])
        assert args.paper_command == "smoke-test"
        assert args.symbols == "SPY,QQQ"

    def test_paper_start_parses(self):
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["paper", "start", "--enable-paper-orders"])
        assert args.paper_command == "start"
        assert args.enable_paper_orders is True

    def test_paper_start_default_no_orders(self):
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["paper", "start"])
        assert args.enable_paper_orders is False
