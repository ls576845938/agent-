"""Read-Only Live Broker Proxy for G2 Shadow Live Validation.

Wraps a real AlpacaBroker and blocks ALL write operations while allowing
read-only access to live account data, positions, orders, and market data.

Core invariant: submit_order(), cancel_order(), replace_order(),
close_position(), close_all_positions() ALL raise RuntimeError.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.broker_base import BrokerBase

_logger = logging.getLogger("readonly_live_broker")


class ReadOnlyLiveBrokerProxy(BrokerBase):
    """Wraps a real broker to allow only read-only access.

    Allowed methods:
        - get_account()
        - get_positions()
        - get_open_orders()
        - get_fills()
        - get_fills_readonly()
        - get_latest_bars()
        - get_clock()
        - get_calendar()
        - health_check()

    Forbidden methods (all raise RuntimeError + audit log):
        - submit_order()
        - cancel_order()
        - replace_order()
        - close_position()
        - close_all_positions()
    """

    def __init__(
        self,
        inner: BrokerBase,
        audit_log_path: str = "",
        audit_context: dict[str, Any] | None = None,
    ) -> None:
        self._inner = inner
        self._audit_log_path = audit_log_path
        self._forbidden_call_count: int = 0
        self._audit_context = dict(audit_context or {})

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return f"readonly_live_{self._inner.broker_name}"

    @property
    def is_readonly(self) -> bool:
        return True

    @property
    def forbidden_call_count(self) -> int:
        return self._forbidden_call_count

    # ------------------------------------------------------------------
    # Allowed: read-only account/position/order access
    # ------------------------------------------------------------------

    def get_account(self) -> AccountState:
        return self._inner.get_account()

    def get_positions(self) -> dict[str, Position]:
        return self._inner.get_positions()

    def get_orders(self) -> list[Order]:
        return self._inner.get_orders()

    def get_open_orders(self) -> list[Order]:
        orders = self._inner.get_orders()
        from quant_us.core.enums import OrderStatus

        return [
            o
            for o in orders
            if o.status
            in (
                OrderStatus.SUBMITTED,
                OrderStatus.ACCEPTED,
                OrderStatus.PARTIALLY_FILLED,
            )
        ]

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        return self._inner.get_fills(order_id)

    def get_fills_readonly(self) -> list[Fill]:
        """Explicit read-only fill fetch — identical to get_fills()."""
        return self._inner.get_fills()

    # ------------------------------------------------------------------
    # Allowed: market data and clock (read-only)
    # ------------------------------------------------------------------

    def get_latest_bars(self, symbols: list[str], bar_size: str = "1m") -> Any:
        """Fetch latest bars for given symbols. Read-only market data access."""
        try:
            return self._inner.get_latest_bars(symbols, bar_size)  # type: ignore[attr-defined]
        except AttributeError:
            _logger.warning("Inner broker does not support get_latest_bars; returning None")
            return None

    def get_clock(self) -> dict[str, Any] | None:
        """Get the market clock from the broker."""
        try:
            return self._inner.get_clock()  # type: ignore[attr-defined]
        except AttributeError:
            _logger.warning("Inner broker does not support get_clock")
            return None

    def get_calendar(self, start: str = "", end: str = "") -> list[dict[str, Any]] | None:
        """Get the trading calendar from the broker."""
        try:
            return self._inner.get_calendar(start, end)  # type: ignore[attr-defined]
        except AttributeError:
            _logger.warning("Inner broker does not support get_calendar")
            return None

    def health_check(self) -> dict[str, Any]:
        """Run a health check on the broker connection (read-only)."""
        try:
            account = self.get_account()
            return {
                "status": "ok",
                "account_accessible": True,
                "equity": account.equity,
                "broker": self.broker_name,
                "readonly": True,
            }
        except Exception as exc:
            return {
                "status": "error",
                "account_accessible": False,
                "error": str(exc),
                "broker": self.broker_name,
                "readonly": True,
            }

    # ------------------------------------------------------------------
    # FORBIDDEN: write operations — ALL raise RuntimeError
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        self._forbidden_call_count += 1
        self._audit_forbidden("submit_order", order.symbol)
        raise RuntimeError(
            "SAFETY VIOLATION: ReadOnlyLiveBrokerProxy.submit_order() is FORBIDDEN. "
            "This proxy is for live read-only account queries. "
            "No real orders can be submitted through this path. "
            f"forbidden_call_count={self._forbidden_call_count}"
        )

    def cancel_order(self, order_id: str) -> Order:
        self._forbidden_call_count += 1
        self._audit_forbidden("cancel_order", order_id)
        raise RuntimeError(
            "SAFETY VIOLATION: ReadOnlyLiveBrokerProxy.cancel_order() is FORBIDDEN. "
            "This proxy is for live read-only account queries. "
            "No real orders can be cancelled through this path."
        )

    def replace_order(self, order_id: str, order: Order) -> Order:
        self._forbidden_call_count += 1
        self._audit_forbidden("replace_order", order_id)
        raise RuntimeError(
            "SAFETY VIOLATION: ReadOnlyLiveBrokerProxy.replace_order() is FORBIDDEN."
        )

    def close_position(self, symbol: str) -> Order:
        self._forbidden_call_count += 1
        self._audit_forbidden("close_position", symbol)
        raise RuntimeError(
            "SAFETY VIOLATION: ReadOnlyLiveBrokerProxy.close_position() is FORBIDDEN."
        )

    def close_all_positions(self) -> list[Order]:
        self._forbidden_call_count += 1
        self._audit_forbidden("close_all_positions", "ALL")
        raise RuntimeError(
            "SAFETY VIOLATION: ReadOnlyLiveBrokerProxy.close_all_positions() is FORBIDDEN."
        )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _audit_forbidden(self, method: str, target: str) -> None:
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": "readonly_live_broker_forbidden_call",
            "method": method,
            "target": target,
            "count": self._forbidden_call_count,
            "broker": self.broker_name,
            "real_submit": False,
            "readonly": True,
            "credential_audit": self.credential_audit(),
        }
        if self._audit_context:
            entry["audit_context"] = dict(self._audit_context)
        msg = (
            f"FORBIDDEN_CALL | method={method} | target={target} | "
            f"count={self._forbidden_call_count} | "
            f"broker={self.broker_name}"
        )
        _logger.warning(msg)
        if self._audit_log_path:
            try:
                audit_path = Path(self._audit_log_path)
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                with audit_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
            except OSError:
                _logger.exception("Failed to write readonly live broker audit record")

    def audit_no_real_submit(self) -> dict[str, Any]:
        """Return proof that no real orders were submitted through this proxy."""
        return {
            "broker": self.broker_name,
            "is_readonly": True,
            "forbidden_call_count": self._forbidden_call_count,
            "no_real_order_submitted": self._forbidden_call_count == 0,
            "credential_audit": self.credential_audit(),
            "proof": (
                "All write methods blocked with RuntimeError. "
                "forbidden_call_count == 0 confirms no attempt to even call forbidden methods."
            ),
        }

    def credential_audit(self) -> dict[str, Any]:
        """Return masked credential and endpoint metadata for readonly audits."""
        key = str(self._audit_context.get("api_key", ""))
        secret = str(self._audit_context.get("api_secret", ""))
        base_url = str(self._audit_context.get("base_url", ""))
        endpoint_kind = str(
            self._audit_context.get("endpoint_kind", classify_alpaca_endpoint(base_url))
        )
        return {
            "api_key_present": bool(key),
            "api_secret_present": bool(secret),
            "api_key_masked": mask_secret(key),
            "api_secret_masked": mask_secret(secret),
            "base_url": base_url,
            "endpoint_kind": endpoint_kind,
            "readonly_expected": bool(
                self._audit_context.get("readonly_expected", True)
            ),
        }


class LiveEndpointGuard:
    """Enforce endpoint isolation between paper and live broker connections.

    - Paper profile MUST use paper endpoint.
    - Shadow-live profile CAN use live endpoint but ONLY for readonly methods.
    - Live profile is default-blocked.
    """

    @staticmethod
    def validate_paper_profile(base_url: str) -> bool:
        from quant_us.execution.alpaca_broker import PAPER_BASE_URL

        if PAPER_BASE_URL not in base_url:
            raise ValueError(
                f"SAFETY: Paper profile must use paper endpoint ({PAPER_BASE_URL}), "
                f"got {base_url}"
            )
        return True

    @staticmethod
    def validate_shadow_live_endpoint(base_url: str, allow_live: bool = False) -> bool:
        from quant_us.execution.alpaca_broker import LIVE_BASE_URL

        if not allow_live:
            raise ValueError(
                "SAFETY: Shadow-live cannot connect to live endpoint without "
                "explicit allow_live=True. Use read-only mode."
            )
        if LIVE_BASE_URL not in base_url:
            raise ValueError(
                f"SAFETY: Shadow-live endpoint must be live ({LIVE_BASE_URL}), "
                f"got {base_url}"
            )
        return True

    @staticmethod
    def block_live_profile() -> None:
        raise RuntimeError(
            "SAFETY: Live profile is NOT READY. "
            "Live order submission is default-blocked. "
            "Complete G2 Shadow Live Validation first."
        )

    @staticmethod
    def guard_submit_order(mode: str, allow_live: bool) -> None:
        if mode == "shadow_live":
            raise RuntimeError(
                "SAFETY: submit_order() blocked in shadow_live mode. "
                "Use ShadowOrder (would_submit=True, real_submit=False) instead."
            )
        if not allow_live:
            raise RuntimeError(
                "SAFETY: submit_order() blocked. "
                "allow_live_orders=False, confirm_live=False."
            )


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """Mask a secret/key showing only the last N characters."""
    if not secret or len(secret) <= visible_chars:
        return "****"
    return "*" * (len(secret) - visible_chars) + secret[-visible_chars:]


def mask_account_id(account_id: str) -> str:
    """Mask an account ID showing first 4 and last 4 chars."""
    if len(account_id) <= 8:
        return account_id[:4] + "****"
    return account_id[:4] + "..." + account_id[-4:]


def classify_alpaca_endpoint(base_url: str) -> str:
    """Classify an Alpaca endpoint for audit output."""
    lowered = base_url.lower().strip()
    if not lowered:
        return "unset"
    if "paper-api.alpaca.markets" in lowered or "paper" in lowered:
        return "paper"
    if "api.alpaca.markets" in lowered:
        return "live"
    return "custom"
