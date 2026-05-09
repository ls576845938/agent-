from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from quant_us.execution.fill_idempotency import (
    FillIdempotencyIndex,
    append_fill_idempotent,
)

if TYPE_CHECKING:
    from quant_us.execution.broker_base import BrokerBase
    from quant_us.execution.ledger import JsonlLedgerStore


@dataclass
class FillSyncResult:
    """Result of a fill sync operation."""

    fills_found: int = 0
    fills_new: int = 0
    fills_duplicate: int = 0
    fills_conflict: int = 0
    errors: list[str] = field(default_factory=list)


class FillSync:
    """Sync fills from broker to local ledger.

    Ensures every broker fill has a corresponding ledger entry.
    Handles partial fills correctly by checking fill_id for deduplication.
    """

    def __init__(
        self,
        broker: BrokerBase,
        ledger: JsonlLedgerStore,
    ) -> None:
        self._broker = broker
        self._ledger = ledger
        self._lock = threading.Lock()
        self._log = logging.getLogger(self.__class__.__name__)
        self._fill_index = FillIdempotencyIndex()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_fills(self, order_id: str | None = None) -> FillSyncResult:
        """Pull fills from broker, write missing ones to ledger.

        Args:
            order_id: If provided, only sync fills for this order.
                       If None, syncs all fills from the broker.

        Returns:
            FillSyncResult with counts of found, new, and duplicate fills.
        """
        self._ensure_seen_fills_loaded()
        result = FillSyncResult()

        try:
            fills = self._broker.get_fills(order_id=order_id)
        except Exception as exc:
            self._log.error("Failed to fetch fills from broker: %s", exc)
            result.errors.append(str(exc))
            return result

        for fill in fills or []:
            result.fills_found += 1

            with self._lock:
                try:
                    appended = append_fill_idempotent(
                        self._ledger,
                        fill,
                        index=self._fill_index,
                        logger=self._log,
                    )
                except Exception as exc:
                    self._log.error(
                        "Failed to write fill %s to ledger: %s",
                        fill.fill_id,
                        exc,
                    )
                    result.errors.append(str(exc))
                    continue

            if appended.appended:
                result.fills_new += 1
                self._log.info(
                    "New fill synced: fill_id=%s order=%s qty=%s price=%s",
                    fill.fill_id,
                    fill.order_id,
                    fill.quantity,
                    fill.price,
                )
            elif appended.duplicate:
                result.fills_duplicate += 1
            elif appended.conflict:
                result.fills_conflict += 1
                result.errors.append(f"fill_conflict({appended.key})")

        return result

    def sync_all_open_orders(self) -> FillSyncResult:
        """Sync fills for all orders known to the ledger.

        Reads existing orders from the ledger and syncs fills for each one.
        Combines results into a single FillSyncResult.

        Returns:
            Aggregate FillSyncResult across all orders.
        """
        combined = FillSyncResult()
        order_ids: set[str] = set()

        for record in self._ledger.read_records("orders.jsonl"):
            oid = record.get("order_id") or record.get("broker_order_id") or ""
            if oid:
                order_ids.add(oid)

        if not order_ids:
            self._log.info("No orders found in ledger to sync fills for")
            return combined

        for oid in sorted(order_ids):
            result = self.sync_fills(order_id=oid)
            combined.fills_found += result.fills_found
            combined.fills_new += result.fills_new
            combined.fills_duplicate += result.fills_duplicate
            combined.fills_conflict += result.fills_conflict
            combined.errors.extend(result.errors)

        self._log.info(
            "Fill sync complete for %d orders: found=%d new=%d dup=%d",
            len(order_ids),
            combined.fills_found,
            combined.fills_new,
            combined.fills_duplicate,
        )

        return combined

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_seen_fills_loaded(self) -> None:
        """Load known fill_ids from ledger into the seen set.

        Safe to call multiple times; only loads once.
        """
        self._fill_index.load_ledger(self._ledger)
        self._log.info("Loaded %d existing fills from ledger", len(self._fill_index))
