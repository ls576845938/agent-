"""Telegram Bot alert integration for trading events.

Sends alerts for: daily PnL, kill switch triggers, order failures,
broker disconnections, reconciliation mismatches, data delays.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib import request
from urllib.error import URLError


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False
    retry_attempts: int = 2
    retry_delay_seconds: float = 1.0


@dataclass
class AlertPriority:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def load_telegram_config_from_env() -> TelegramConfig | None:
    """Read TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.

    Returns a configured TelegramConfig with enabled=True if both are set.
    Returns None if neither env var is set.
    Returns a disabled TelegramConfig (enabled=False) if only one is set.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token and not chat_id:
        return None

    enabled = bool(bot_token and chat_id)
    return TelegramConfig(
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=enabled,
    )


class TelegramAlertService:
    """Send trading alerts via Telegram Bot API.

    Uses the Bot API directly (no third-party library dependency).
    Tokens and chat IDs come from environment variables or config.
    """

    def __init__(self, config: TelegramConfig | None = None) -> None:
        self.config = config or TelegramConfig()

    def send(self, message: str, priority: str = AlertPriority.MEDIUM) -> bool:
        if not self.config.enabled or not self.config.bot_token or not self.config.chat_id:
            return False

        emoji = {"critical": "\U0001f534", "high": "\U0001f7e0", "medium": "\U0001f7e1", "low": "\U0001f7e2"}
        prefix = emoji.get(priority, "")
        full_message = f"{prefix} *QuantStation Alert* [{priority.upper()}]\n\n{message}"

        for attempt in range(self.config.retry_attempts + 1):
            try:
                return self._send_api(full_message)
            except Exception:
                if attempt < self.config.retry_attempts:
                    import time
                    time.sleep(self.config.retry_delay_seconds)
        return False

    def _send_api(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        resp = request.urlopen(req, timeout=10)
        return resp.status == 200

    # --- Pre-defined alert templates ---

    def daily_report(self, date_str: str, equity: float, daily_pnl: float, daily_return_pct: float, positions: int, orders: int) -> bool:
        sign = "+" if daily_pnl >= 0 else ""
        return self.send(
            f"*Daily Report* — {date_str}\n\n"
            f"Equity: ${equity:,.2f}\n"
            f"Daily PnL: {sign}${daily_pnl:,.2f} ({sign}{daily_return_pct:.2f}%)\n"
            f"Open Positions: {positions}\n"
            f"Orders Today: {orders}",
            priority=AlertPriority.LOW,
        )

    def kill_switch_triggered(self, reason: str, equity: float, drawdown_pct: float) -> bool:
        return self.send(
            f"*KILL SWITCH TRIGGERED*\n\n"
            f"Reason: {reason}\n"
            f"Current Equity: ${equity:,.2f}\n"
            f"Drawdown: {drawdown_pct:.2f}%\n\n"
            f"All new orders blocked. Manual intervention required.",
            priority=AlertPriority.CRITICAL,
        )

    def order_failure(self, symbol: str, side: str, quantity: float, reason: str, consecutive: int) -> bool:
        return self.send(
            f"*Order Failure*\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side}\n"
            f"Quantity: {quantity:.4f}\n"
            f"Reason: {reason}\n"
            f"Consecutive Failures: {consecutive}",
            priority=AlertPriority.HIGH,
        )

    def broker_disconnect(self, broker_name: str, downtime_seconds: float) -> bool:
        return self.send(
            f"*Broker Disconnected*\n\n"
            f"Broker: {broker_name}\n"
            f"Downtime: {downtime_seconds:.0f}s\n\n"
            f"System entered protection mode.",
            priority=AlertPriority.CRITICAL,
        )

    def reconciliation_mismatch(self, symbol: str, local_qty: float, broker_qty: float, diff: float) -> bool:
        return self.send(
            f"*Reconciliation Mismatch*\n\n"
            f"Symbol: {symbol}\n"
            f"Local Position: {local_qty:.4f}\n"
            f"Broker Position: {broker_qty:.4f}\n"
            f"Difference: {diff:.4f}\n\n"
            f"Trading halted until resolved.",
            priority=AlertPriority.CRITICAL,
        )

    def data_delay(self, delay_seconds: float, threshold_seconds: float) -> bool:
        return self.send(
            f"*Data Delay*\n\n"
            f"Current Delay: {delay_seconds:.0f}s\n"
            f"Threshold: {threshold_seconds:.0f}s\n\n"
            f"Orders paused until data recovers.",
            priority=AlertPriority.HIGH,
        )

    def daily_loss_limit(self, loss_pct: float, limit_pct: float) -> bool:
        return self.send(
            f"*Daily Loss Limit*\n\n"
            f"Current Loss: {loss_pct:.2f}%\n"
            f"Limit: {limit_pct:.2f}%\n\n"
            f"No new positions allowed for rest of day.",
            priority=AlertPriority.HIGH,
        )
