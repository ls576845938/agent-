"""Process-local, verified input compaction for offline ledger reconciliation.

No PnL, position, fee or funding arithmetic lives here. The original authority
still validates every newly committed UOW and candidate and recomputes the
entire unique economic history against the current independent snapshot.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

from quant_crypto.oms.account_risk_facts import AccountRiskFactError, replay_account_ledger_uows
from quant_crypto.oms.runtime_store import BTCRuntimeRecovery


class OfflineLedgerHistoryCache:
    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._context: tuple[Any, ...] | None = None
        self._sequence = 0
        self._hash = ""
        self._final_time: datetime | None = None
        self._contract_value: Any = None
        self._fills: dict[str, dict[str, Any]] = {}
        self._bills: dict[str, dict[str, Any]] = {}

    def replay(self, *, recovery: BTCRuntimeRecovery, baseline_sequence: int,
               account_identity: str, candidate_uow: Mapping[str, Any], **options: Any) -> dict[str, Any]:
        if recovery.blockers:
            self._reset()
            raise AccountRiskFactError("runtime_event_recovery_blocked:" + ",".join(recovery.blockers))
        context = (account_identity, baseline_sequence, str(options["baseline_equity_usdt"]),
                   str(options["baseline_observed_at_utc"]), options["currency"])
        try:
            final_time = datetime.fromisoformat(str(options["final_observed_at_utc"]).replace("Z", "+00:00"))
            monotonic = self._final_time is None or final_time >= self._final_time
        except (TypeError, ValueError):
            monotonic = False  # the original function reports malformed time
        prefix_same = (self._sequence <= recovery.last_sequence and
                       (not self._sequence or recovery.events[self._sequence - 1]["event_hash"] == self._hash))
        # recover() has re-read and exactly compared the bytes, checked the
        # complete chain and checkpoint. Its last hash binds all prior events.
        if context != self._context or not prefix_same or not monotonic:
            self._reset()
        new_uows = [event["payload"] for event in recovery.events[self._sequence:]
                    if event.get("event_type") == "ledger_uow_committed"
                    and int(event.get("sequence") or 0) > baseline_sequence]
        compact = [] if self._contract_value is None else [{
            "risk_context": {"venue_rules": {"contract_value_btc": self._contract_value}},
            "fill_ledger": list(self._fills.values()), "funding_ledger": {"bills": list(self._bills.values())}}]
        try:
            result = replay_account_ledger_uows(uow_payloads=[*compact, *new_uows, candidate_uow], **options)
        except Exception:
            self._reset()
            raise
        # Only successfully checked COMMITTED rows become history. A candidate
        # never advances this cursor, even if its replay succeeds but commit
        # later fails. Baseline-old rows were validated above, then excluded by
        # the unchanged (baseline, final] authority. Monotonic time and context
        # binding are required before that exclusion can be reused.
        baseline_ms = int(datetime.fromisoformat(result["baseline_observed_at_utc"].replace("Z", "+00:00")).timestamp() * 1000)
        for raw in new_uows:
            payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
            if self._contract_value is None:
                self._contract_value = deepcopy(payload["risk_context"]["venue_rules"]["contract_value_btc"])
            funding = payload.get("funding_ledger")
            bills = funding.get("bills", []) if isinstance(funding, Mapping) else []
            for rows, target, key in ((payload.get("fill_ledger", []), self._fills, "fill_id"), (bills, self._bills, "bill_id")):
                for row in rows:
                    if int(str(row["timestamp_ms"]).strip()) > baseline_ms:
                        # Conflict and exact JSON equality were checked by the
                        # original replay. Preserve first insertion order (in
                        # particular Decimal funding addition order).
                        target[str(row[key])] = deepcopy(dict(row))
        self._context = context
        self._sequence = recovery.last_sequence
        self._hash = recovery.last_event_hash
        self._final_time = datetime.fromisoformat(result["final_observed_at_utc"].replace("Z", "+00:00"))
        return result
