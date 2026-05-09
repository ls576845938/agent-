from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Mapping

from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.live.paper_adapter_contract import (
    ALLOWED_ALPACA_PAPER_BASE_URLS,
    REQUIRED_PAPER_ADAPTER_CAPABILITIES,
    audit_apca_paper_credentials,
    normalize_paper_adapter_capabilities,
)


ALPACA_PAPER_ADAPTER_ENABLE_ENV = "QUANT_ENABLE_ALPACA_PAPER_ADAPTER"
ALPACA_PAPER_NETWORK_SUBMIT_ENV = "QUANT_ALPACA_PAPER_NETWORK_SUBMIT"


def _env_true(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class AlpacaPaperAdapterConfig:
    api_key: str
    api_secret: str
    base_url: str = ALLOWED_ALPACA_PAPER_BASE_URLS[0]
    timeout_seconds: float = 20.0
    network_submit_enabled: bool = False


class AlpacaPaperBrokerAdapter:
    """Alpaca paper broker adapter with paper-only endpoint enforcement.

    The adapter is intentionally not auto-wired into PaperRuntime. Construction
    requires explicit credentials and the exact paper endpoint allowlist. Network
    order submission is disabled by default and needs an explicit constructor
    flag plus the ``QUANT_ALPACA_PAPER_NETWORK_SUBMIT`` confirmation flag.
    """

    broker_name = "alpaca_paper"

    def __init__(self, config: AlpacaPaperAdapterConfig, session: Any | None = None) -> None:
        audit = audit_apca_paper_credentials(
            {
                "APCA_API_KEY_ID": config.api_key,
                "APCA_API_SECRET_KEY": config.api_secret,
                "APCA_API_BASE_URL": config.base_url,
            }
        )
        if not audit["credentials_present"]:
            raise RuntimeError("apca_paper_credentials_missing")
        if not audit["base_url_valid"]:
            raise RuntimeError("apca_base_url_not_allowed")

        self.config = config
        self.base_url = str(audit["normalized_base_url"])
        self._session = session
        self._client: Any | None = None

    @classmethod
    def contract_capabilities(cls) -> dict[str, bool]:
        return normalize_paper_adapter_capabilities(
            {name: True for name in REQUIRED_PAPER_ADAPTER_CAPABILITIES}
        )

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        session: Any | None = None,
        network_submit_requested: bool = False,
    ) -> "AlpacaPaperBrokerAdapter":
        audit = audit_apca_paper_credentials(env)
        if not audit["credentials_present"]:
            raise RuntimeError("apca_paper_credentials_missing")
        if not audit["base_url"]:
            raise RuntimeError("apca_base_url_missing")
        if not audit["base_url_valid"]:
            raise RuntimeError("apca_base_url_not_allowed")
        if not _env_true(env, ALPACA_PAPER_ADAPTER_ENABLE_ENV):
            raise RuntimeError("alpaca_paper_adapter_not_explicitly_enabled")
        if session is None and importlib.util.find_spec("requests") is None:
            raise RuntimeError("alpaca_paper_client_dependency_missing")

        submit_enabled = (
            bool(network_submit_requested)
            and _env_true(env, ALPACA_PAPER_NETWORK_SUBMIT_ENV)
        )
        return cls(
            AlpacaPaperAdapterConfig(
                api_key=env["APCA_API_KEY_ID"],
                api_secret=env["APCA_API_SECRET_KEY"],
                base_url=str(audit["normalized_base_url"]),
                network_submit_enabled=submit_enabled,
            ),
            session=session,
        )

    def readiness_report(self) -> dict[str, object]:
        return {
            "adapter": self.broker_name,
            "paper_only": True,
            "base_url": self.base_url,
            "endpoint_kind": "paper",
            "allowed_base_urls": list(ALLOWED_ALPACA_PAPER_BASE_URLS),
            "credentials_present": True,
            "client_dependency_present": self._session is not None
            or importlib.util.find_spec("requests") is not None,
            "network_submit_enabled": self.config.network_submit_enabled,
            "fail_closed_without_submit_confirmation": not self.config.network_submit_enabled,
        }

    def poll_orders(self) -> list[Order]:
        return self.get_orders()

    def sync_fills(self, order_id: str | None = None) -> list[Fill]:
        return self.get_fills(order_id=order_id)

    def sync_account(self) -> AccountState:
        return self.get_account()

    def sync_positions(self) -> dict[str, Position]:
        return self.get_positions()

    def get_account(self) -> AccountState:
        return self._broker().get_account()

    def get_positions(self) -> dict[str, Position]:
        return self._broker().get_positions()

    def get_orders(self) -> list[Order]:
        return self._broker().get_orders()

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        return self._broker().get_fills(order_id=order_id)

    def submit_order(self, order: Order) -> Order:
        if not self.config.network_submit_enabled:
            raise RuntimeError("alpaca_paper_network_submit_disabled_fail_closed")
        return self._broker().submit_order(order)

    def cancel_order(self, order_id: str) -> Order:
        if not self.config.network_submit_enabled:
            raise RuntimeError("alpaca_paper_network_write_disabled_fail_closed")
        return self._broker().cancel_order(order_id)

    def _broker(self) -> Any:
        if self._client is not None:
            return self._client

        from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig

        self._client = AlpacaBroker(
            AlpacaBrokerConfig(
                api_key=self.config.api_key,
                api_secret=self.config.api_secret,
                paper=True,
                base_url=self.base_url,
                timeout_seconds=self.config.timeout_seconds,
            ),
            session=self._session,
        )
        return self._client
