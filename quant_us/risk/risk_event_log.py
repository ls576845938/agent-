"""Persistent risk event audit log.

Writes structured risk events (rejections, kill-switch triggers, broker failures,
reconciliation breaks, etc.) to a JSONL file for later query and audit.

Usage:
    log = RiskEventLog("data/risk_events.jsonl")
    log.record("risk_rejected", {"rule": "symbol_weight_limit", "symbol": "AAPL"})
    events = log.query(event_type="risk_rejected")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now


class RiskEventLog:
    """Append-only audit log for risk events persisted to a JSONL file."""

    EVENT_TYPES: frozenset[str] = frozenset({
        "risk_rejected",
        "kill_switch_triggered",
        "broker_timeout",
        "broker_disconnect",
        "reconciliation_break",
        "data_staleness",
        "slippage_exceeded",
    })

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        event_type: str,
        details: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Append a risk event entry to the JSONL log.

        Args:
            event_type: One of RiskEventLog.EVENT_TYPES (custom allowed).
            details: Arbitrary structured data describing the event.
            timestamp: Explicit timestamp (defaults to utc_now).
        """
        entry: dict[str, Any] = {
            "timestamp_utc": (timestamp or utc_now()).isoformat(),
            "event_type": event_type,
            "details": details or {},
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def query(
        self,
        since: datetime | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read and filter events from the JSONL log.

        Args:
            since: Return only events at or after this timestamp.
            event_type: Return only events of this type.

        Returns:
            List of event dicts sorted by file order (insertion order).
        """
        if not self.path.exists():
            return []
        results: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").strip().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry: dict[str, Any] = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if event_type is not None and entry.get("event_type") != event_type:
                continue
            if since is not None:
                try:
                    entry_time = datetime.fromisoformat(entry["timestamp_utc"])
                except (ValueError, TypeError):
                    continue
                if entry_time < since:
                    continue
            results.append(entry)
        return results

    def count(self, event_type: str | None = None) -> int:
        """Return the number of matching events (cheaper than loading all)."""
        if not self.path.exists():
            return 0
        count = 0
        for line in self.path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type is None or entry.get("event_type") == event_type:
                count += 1
        return count

    def clear(self) -> None:
        """Delete the log file (useful in tests)."""
        if self.path.exists():
            self.path.unlink()
