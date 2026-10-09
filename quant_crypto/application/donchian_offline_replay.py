"""One bounded Donchian offline slice through the existing BTC authority chain."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from quant_crypto.application.btc_demo_production_composition import (
    BtcDemoProductionComposition,
    canonical_ledger_snapshot_sha256,
)
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.application.donchian_offline_history_cache import OfflineLedgerHistoryCache
from quant_crypto.application.runtime_risk_guardian import (
    FileGuardianLatchStore,
    GuardianConfig,
    GuardianLatchRecord,
    RuntimeRiskGuardian,
    RuntimeRiskGuardianSupervisor,
)
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
    ACCOUNT_DRAWDOWN_SCOPE,
    build_explicit_account_drawdown_baseline,
    build_okx_account_cashflow_evidence,
)
from quant_crypto.oms.okx_demo import OkxDemoResponse
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
    OkxDemoPaperRuntimeError,
    ServerSideProtectionPolicy,
)
from quant_crypto.runtime.control_plane import (
    BTCDemoExecutionDispatcher,
    BTCEndpointCapability,
    BTCExecutionMode,
)
from quant_shared.strategy_runtime.decision_envelope import (
    DecisionEvidenceEnvelope,
    package_digest,
)
from quant_shared.strategy_runtime.models import (
    StrategyClock,
    StrategyDecisionCapability,
    StrategyDecisionContext,
    StrategyIdentity,
    StrategyRuntimeMode,
)
from quant_shared.strategy_delivery.market_policy_attachment import SAFETY_KEYS
from quant_shared.trend_environment.entry_policy import (
    EntryOnlyPolicyV1,
    evaluate_entry_policy,
)
from quant_shared.trend_environment.model import digest as shared_digest
from quant_shared.trend_environment.state_v2 import MarketStateV2


STRATEGY_ID = "long_short_donchian_top5_okx_native"
INSTRUMENT_ID = "BTC-USDT-SWAP"
IDENTITY_SCHEMA_VERSION = "strategy_v1_offline_identity_v1"
INPUT_SCHEMA_VERSION = "strategy_v1_offline_input_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decimal_text(value: Any) -> str:
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise ValueError("offline_frame_numeric_non_finite")
    text = format(decimal.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_canonical_json(payload), encoding="utf-8")
    temporary.replace(path)


def build_trend_frame(kind: str, *, end: datetime) -> pd.DataFrame:
    if kind not in {"long", "short", "flat"}:
        raise ValueError("trend_kind_invalid")
    end = end.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    times = pd.date_range(end=end, periods=5200, freq="h")
    fn = {
        "long": lambda index: 10000.0 + index * 8.0,
        "short": lambda index: 90000.0 - index * 8.0,
        "flat": lambda _index: 60000.0,
    }[kind]
    values = [fn(index) for index in range(len(times))]
    return pd.DataFrame(
        {
            "open_time": times - pd.Timedelta(hours=1),
            "open": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "close": values,
            "volume": 1.0,
        },
        index=times,
    )


def build_closeout_scenario(*, start: datetime) -> pd.DataFrame:
    """Build one continuous, causal V1 acceptance timeline."""

    start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    warmup = [60000.0] * 5200
    rising = [60000.0 + (index + 1) * 0.1 for index in range(5200)]
    falling = [rising[-1] - (index + 1) * 0.1 for index in range(5200)]
    rebound = [falling[-1] + (index + 1) * 0.1 for index in range(1600)]
    values = warmup + rising + falling + rebound
    times = pd.date_range(start=start, periods=len(values), freq="h")
    return pd.DataFrame(
        {
            "open_time": times - pd.Timedelta(hours=1),
            "open": values,
            "high": [value + 0.01 for value in values],
            "low": [value - 0.01 for value in values],
            "close": values,
            "volume": 1.0,
        },
        index=times,
    )


def _normalize_completed_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("open_time", "open", "high", "low", "close", "volume")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid:empty")
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise OkxDemoPaperRuntimeError(
            "offline_completed_frame_invalid:missing:" + ",".join(missing)
        )
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise OkxDemoPaperRuntimeError(
            "offline_completed_frame_invalid:index_timezone"
        )
    open_time_values = pd.to_datetime(frame["open_time"], errors="coerce")
    if open_time_values.isna().any() or getattr(open_time_values.dt, "tz", None) is None:
        raise OkxDemoPaperRuntimeError(
            "offline_completed_frame_invalid:open_time_timezone"
        )
    normalized = frame.loc[:, required].copy(deep=True)
    index = pd.DatetimeIndex(pd.to_datetime(normalized.index, utc=True))
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid:index")
    normalized.index = index
    open_times = pd.DatetimeIndex(pd.to_datetime(normalized["open_time"], utc=True))
    if not open_times.equals(index - pd.Timedelta(hours=1)):
        raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid:open_time")
    return normalized


def _canonical_rows(normalized: pd.DataFrame) -> list[list[str]]:
    rows: list[list[str]] = []
    for timestamp, open_time, *values in normalized.itertuples(index=True, name=None):
        numeric = [_decimal_text(value) for value in values]
        if Decimal(numeric[1]) < max(Decimal(numeric[0]), Decimal(numeric[3])):
            raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid:high")
        if Decimal(numeric[2]) > min(Decimal(numeric[0]), Decimal(numeric[3])):
            raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid:low")
        rows.append(
            [
                timestamp.isoformat(),
                pd.Timestamp(open_time).isoformat(),
                *numeric,
            ]
        )
    return rows


def _canonical_rows_digest(rows: list[list[str]]) -> str:
    return _sha(
        {
            "schema_version": "canonical_completed_ohlcv_v1",
            "instrument_id": INSTRUMENT_ID,
            "interval": "1h",
            "columns": ["open_time", "open", "high", "low", "close", "volume"],
            "rows": rows,
        }
    )


def _canonical_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    normalized = _normalize_completed_frame(frame)
    return normalized, _canonical_rows_digest(_canonical_rows(normalized))


class _CanonicalFrameCache:
    """Reuse row encoding only after exact prefix equality, not time/length hints.

    The complete canonical digest is still computed on every call. Only the
    private, already validated row representation is reused; callers cannot
    mutate it through a returned frame. No cache crosses a process/restart.
    """

    def __init__(self) -> None:
        self._frame: pd.DataFrame | None = None
        self._rows: list[list[str]] = []

    def __call__(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        normalized = _normalize_completed_frame(frame)
        previous = self._frame
        if (previous is not None and len(normalized) >= len(previous)
                and normalized.iloc[:len(previous)].equals(previous)):
            rows = self._rows + _canonical_rows(normalized.iloc[len(previous):])
        else:
            rows = _canonical_rows(normalized)
        digest = _canonical_rows_digest(rows)
        self._frame = normalized.copy(deep=True)
        self._rows = rows
        return normalized, digest


class _OfflineSignalMemoController(OkxDemoPaperRuntimeController):
    """Memoize the original signal-only read for preview/cycle duplicate calls.

    Never cache risk, account state, targets-to-orders, or runtime outcomes.
    The normal controller/production construction is deliberately unchanged.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._offline_ledger_history = OfflineLedgerHistoryCache()
        try:
            super().__init__(**kwargs)
        except BaseException:
            if hasattr(self, "_runtime_store"):
                self._runtime_store.close()
            raise

    def _create_runtime_store(self) -> BTCRuntimeStore:
        # Initial/restart recovery still verifies the entire hash chain, but
        # streams it instead of materializing all cumulative snapshots at once.
        return BTCRuntimeStore(Path(self.config.output_dir), offline_journal_session=True)

    def _replay_reconciled_ledger(self, **options: Any) -> dict[str, Any]:
        return self._offline_ledger_history.replay(**options)

    def _signal_decision(self, strategy: Mapping[str, Any], *, client: Any = None) -> dict[str, Any]:
        provider = self.config.offline_completed_frame_provider
        frame = provider() if provider is not None else None
        # On malformed/future input the original method remains the authority.
        # With an offline provider the base implementation never consumes the
        # client argument. run_cycle passes the venue; preview does not.
        if (not isinstance(frame, pd.DataFrame) or frame.empty
                or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None
                or frame.index[-1] > pd.Timestamp(self._clock()).floor("h")):
            if getattr(self, "_offline_market_entry_policy", None) is not None:
                raise OkxDemoPaperRuntimeError("offline_market_policy_frame_invalid")
            return super()._signal_decision(strategy, client=client)
        spec = btc_strategy_registry.get(str(strategy.get("strategy_id") or ""), str(strategy.get("candidate_id") or ""))
        identity = (_canonical_json(strategy), _canonical_json(spec.identity()), spec.signal_callable)
        cached = getattr(self, "_offline_signal_memo", None)
        if cached is not None and cached[0] == identity and frame.equals(cached[1]):
            result = deepcopy(cached[2])
        else:
            result = super()._signal_decision(strategy, client=client)
            # Cache only the original strategy result.  Position can change
            # between reversal-close and the same-bar reopen phase, so the
            # entry-only policy must be evaluated for every call.
            self._offline_signal_memo = (
                identity,
                frame.copy(deep=True),
                deepcopy(result),
            )
        return self._apply_offline_market_entry_policy(
            result=result,
            frame=frame,
            client=client,
        )

    def _apply_offline_market_entry_policy(
        self,
        *,
        result: Mapping[str, Any],
        frame: pd.DataFrame,
        client: Any,
    ) -> dict[str, Any]:
        policy = getattr(self, "_offline_market_entry_policy", None)
        provider = getattr(self, "_offline_market_state_provider", None)
        attachment = getattr(self, "_offline_market_policy_attachment", None)
        if policy is None and provider is None and attachment is None:
            return dict(result)
        if (
            not isinstance(policy, EntryOnlyPolicyV1)
            or not callable(provider)
            or not isinstance(attachment, Mapping)
        ):
            raise OkxDemoPaperRuntimeError("offline_market_policy_binding_invalid")

        venue = client if client is not None else getattr(self, "_client", None)
        venue_state = getattr(venue, "state", None)
        if not isinstance(venue_state, Mapping) or "position" not in venue_state:
            raise OkxDemoPaperRuntimeError("offline_market_position_fact_missing")
        try:
            current = Decimal(str(venue_state["position"]))
            original = Decimal(str(result.get("target_contracts")))
        except Exception as exc:
            raise OkxDemoPaperRuntimeError(
                "offline_market_position_or_target_invalid"
            ) from exc
        if not current.is_finite() or not original.is_finite():
            raise OkxDemoPaperRuntimeError(
                "offline_market_position_or_target_invalid"
            )

        state: MarketStateV2 | None = None
        state_unavailable = False
        try:
            observed_state = provider(frame.copy(deep=True))
        except Exception:
            observed_state = None
            state_unavailable = True
        if isinstance(observed_state, MarketStateV2):
            state = observed_state
        else:
            state_unavailable = True

        is_new_entry = policy.enabled and current == 0 and original != 0
        if state is None and is_new_entry:
            raise OkxDemoPaperRuntimeError("offline_market_state_invalid")

        state_binding_matches = False
        if state is not None:
            cutoff = (
                pd.Timestamp(frame.index[-1])
                .to_pydatetime()
                .astimezone(timezone.utc)
            )
            state_binding_matches = (
                state.asset == INSTRUMENT_ID
                and state.cutoff_time.astimezone(timezone.utc) == cutoff
                and state.decision_time.astimezone(timezone.utc) == cutoff
                and state.definition_hash == policy.state_definition_hash
                and state.source_binding_hash == policy.source_binding_hash
            )
        # Binding failures may reject a new entry, but an entry-only policy
        # must never obstruct an existing-position reduction/exit/reversal
        # close or a flat no-op.  The shared evaluator deliberately applies
        # those non-interference branches before inspecting state identity.
        if is_new_entry and not state_binding_matches:
            raise OkxDemoPaperRuntimeError(
                "offline_market_state_binding_mismatch"
            )

        if state is not None:
            decision = evaluate_entry_policy(
                policy=policy,
                state=state,
                current_position=current,
                original_target=original,
            )
            effective_target = decision.effective_target
            applied = decision.applied
            reason = decision.reason
            state_content_hash = decision.state_content_hash
        else:
            effective_target = original
            applied = False
            reason = (
                "policy_disabled"
                if not policy.enabled
                else (
                    "existing_position_not_entry"
                    if current != 0
                    else "no_new_entry"
                )
            )
            state_content_hash = None

        conditioned = dict(result)
        conditioned["target_contracts"] = _decimal_text(effective_target)
        conditioned["market_entry_policy"] = {
            "usage": "research_replay_entry_only",
            "attachment_hash": str(attachment.get("attachment_hash") or ""),
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "policy_hash": policy.policy_hash,
            "state_version": (
                state.definition_version if state is not None else None
            ),
            "state_definition_hash": (
                state.definition_hash if state is not None else None
            ),
            "state_source_binding_hash": (
                state.source_binding_hash if state is not None else None
            ),
            "state_content_hash": state_content_hash,
            "state_input_hash": state.input_hash if state is not None else None,
            "state_status": state.status if state is not None else "unavailable",
            "state_reasons": (
                list(state.reasons)
                if state is not None
                else ["market_state_unavailable"]
            ),
            "state_cutoff_utc": (
                state.cutoff_time.astimezone(timezone.utc).isoformat()
                if state is not None
                else None
            ),
            "state_binding_status": (
                "verified"
                if state_binding_matches
                else (
                    "unavailable_non_entry_passthrough"
                    if state_unavailable
                    else "mismatch_non_entry_passthrough"
                )
            ),
            "original_target_contracts": _decimal_text(original),
            "effective_target_contracts": _decimal_text(effective_target),
            "applied": applied,
            "reason": reason,
            "existing_position_contracts": _decimal_text(current),
        }
        return conditioned


@dataclass(frozen=True)
class DonchianOfflineReplayConfig:
    repo_root: Path
    state_dir: Path
    run_id: str
    decision_time_utc: datetime
    data_version: str
    venue_factory: Callable[[Path, datetime], "_OfflineVenue"] | None = field(
        default=None, repr=False, compare=False
    )
    decision_time_provider: Callable[[datetime, int, str], datetime] | None = field(
        default=None, repr=False, compare=False
    )
    max_notional_usdt: Decimal = Decimal("10")
    market_entry_policy: EntryOnlyPolicyV1 | None = field(
        default=None, repr=False, compare=False
    )
    market_state_provider: Callable[[pd.DataFrame], MarketStateV2] | None = field(
        default=None, repr=False, compare=False
    )
    market_policy_attachment: Mapping[str, Any] | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (not isinstance(self.max_notional_usdt, Decimal)
            or not self.max_notional_usdt.is_finite()
            or self.max_notional_usdt not in (Decimal("10"), Decimal("50"))):
            raise ValueError("offline_notional_limit_must_be_frozen_10_or_50")
        root = Path(self.repo_root).resolve()
        state = Path(self.state_dir).resolve()
        if root == state or root in state.parents:
            raise ValueError("offline_state_must_remain_outside_git")
        when = self.decision_time_utc
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("decision_time_must_be_timezone_aware")
        if len(self.run_id) < 8:
            raise ValueError("offline_run_id_too_short")
        if not str(self.data_version or "").strip():
            raise ValueError("offline_data_version_required")
        if self.venue_factory is not None and not callable(self.venue_factory):
            raise ValueError("offline_venue_factory_invalid")
        if self.decision_time_provider is not None and not callable(
            self.decision_time_provider
        ):
            raise ValueError("offline_decision_time_provider_invalid")
        market_parts = (
            self.market_entry_policy,
            self.market_state_provider,
            self.market_policy_attachment,
        )
        if any(value is not None for value in market_parts):
            if (
                not isinstance(self.market_entry_policy, EntryOnlyPolicyV1)
                or not callable(self.market_state_provider)
                or not isinstance(self.market_policy_attachment, Mapping)
            ):
                raise ValueError("offline_market_policy_binding_incomplete")
            attachment = dict(self.market_policy_attachment)
            unsigned = dict(attachment)
            observed_hash = unsigned.pop("attachment_hash", None)
            policy_contract = attachment.get("entry_policy")
            safety = attachment.get("safety")
            if (
                observed_hash != shared_digest(unsigned)
                or not isinstance(policy_contract, Mapping)
                or policy_contract.get("policy_hash")
                != self.market_entry_policy.policy_hash
                or policy_contract.get("enabled")
                is not self.market_entry_policy.enabled
                or safety != dict.fromkeys(SAFETY_KEYS, False)
            ):
                raise ValueError("offline_market_policy_attachment_invalid")
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "state_dir", state)
        object.__setattr__(self, "decision_time_utc", when.astimezone(timezone.utc))


class _OfflineCapabilityAdapter:
    def capability_for(self, *, action: object, transport_context: object) -> BTCEndpointCapability:
        if not isinstance(transport_context, _OfflineVenue):
            raise ValueError("offline_transport_required")
        return BTCEndpointCapability(
            mode=BTCExecutionMode.DEMO,
            transport_enabled=True,
            submit_new_order=True,
            cancel_order=True,
            reduce_only=True,
            attach_protection=True,
            dead_man=True,
            private_endpoint_allowed=True,
            order_endpoint_allowed=True,
        )


class _OfflineVenue:
    """File-backed deterministic venue simulator; it never creates a socket."""

    def __init__(self, path: Path, *, now: datetime) -> None:
        self.path = path
        self.now = now
        if path.exists():
            self.state = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.state = {
                "position": "0",
                "equity": "5000",
                "orders": [],
                "fills": [],
                "algos": [],
                "algo_history": [],
                "bills": [],
                "submit_count": 0,
                "cancel_algo_count": 0,
            }
            self._persist()
        self.state.setdefault("algo_history", [])
        self.state.setdefault("bills", [])
        self.state.setdefault("cancel_algo_count", 0)

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.path, self.state)

    def observe_offline_liveness(self, *, identity_digest: str) -> Mapping[str, Any]:
        """Explicit simulated receipt on the replay clock; no exchange request.

        Historical input models a healthy local transport at each observation,
        not a real connection or continuous wall-clock heartbeat coverage.
        Fault-injection venues can withhold/reject this receipt.
        """
        return {
            "schema_version": "offline_liveness_observation_v1",
            "identity_digest": identity_digest,
            "observed_at_utc": self.now.isoformat(),
            "acknowledged": True,
            "offline_execution_only": True,
        }

    def public_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        del params
        timestamp = str(int(self.now.timestamp() * 1000))
        rows = {
            "/api/v5/public/instruments": [{"instId": "BTC-USDT-SWAP", "state": "live", "ctVal": "0.01", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"}],
            "/api/v5/market/ticker": [{"bidPx": "60000", "askPx": "60000.1", "ts": timestamp}],
            "/api/v5/public/mark-price": [{"markPx": "60000", "ts": timestamp}],
            "/api/v5/market/index-tickers": [{"idxPx": "60000", "ts": timestamp}],
            "/api/v5/public/price-limit": [{"buyLmt": "70000", "sellLmt": "50000"}],
            "/api/v5/market/books": [{"bids": [["60000", "1"]], "asks": [["60000.1", "1"]], "ts": timestamp}],
            "/api/v5/public/time": [{"ts": timestamp}],
            "/api/v5/public/funding-rate": [{"fundingRate": "0.0001", "fundingTime": timestamp}],
        }
        return OkxDemoResponse("GET", path, 200, "0", "", tuple(rows[path]))

    def _position_rows(self) -> list[dict[str, str]]:
        position = Decimal(self.state["position"])
        if position == 0:
            # An explicit flat account fact is not the same thing as a missing
            # position response.  The production composition deliberately
            # refuses to invent zero PnL when the venue omitted those facts.
            return [{
                "instId": "BTC-USDT-SWAP",
                "posSide": "long",
                "mgnMode": "isolated",
                "pos": "0",
                "avgPx": "60000",
                "markPx": "60000",
                "upl": "0",
                "realizedPnl": "0",
                "liqPx": "",
                "lever": "1",
                "uTime": str(int(self.now.timestamp() * 1000)),
            }]
        return [{
            "instId": "BTC-USDT-SWAP",
            "posSide": "long" if position > 0 else "short",
            "mgnMode": "isolated",
            "pos": format(abs(position), "f"),
            "avgPx": "60000",
            "markPx": "60000",
            "upl": "0",
            "realizedPnl": "0",
            "liqPx": "30000" if position > 0 else "90000",
            "lever": "1",
            "uTime": str(int(self.now.timestamp() * 1000)),
        }]

    def private_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        query = dict(params or {})
        if path == "/api/v5/account/config":
            rows = [{"acctLv": "2", "posMode": "long_short_mode", "perm": "read_only,trade", "uid": "offline-account", "mainUid": "offline-main"}]
        elif path == "/api/v5/account/balance":
            rows = [{"totalEq": self.state["equity"], "details": [{"ccy": "USDT", "eq": self.state["equity"], "upl": "0"}]}]
        elif path == "/api/v5/account/positions":
            rows = self._position_rows()
        elif path == "/api/v5/trade/orders-pending":
            rows = []
        elif path == "/api/v5/trade/orders-algo-pending":
            rows = list(self.state["algos"])
        elif path == "/api/v5/trade/orders-algo-history":
            algo_id = str(query.get("algoId") or "")
            rows = [
                row
                for row in self.state["algo_history"]
                if not algo_id or row["algoId"] == algo_id
            ]
        elif path == "/api/v5/trade/orders-history":
            rows = list(self.state["orders"])
        elif path == "/api/v5/trade/fills":
            order_id = str(query.get("ordId") or "")
            rows = [row for row in self.state["fills"] if not order_id or row["ordId"] == order_id]
        elif path == "/api/v5/account/bills":
            rows = list(self.state["bills"])
        elif path == "/api/v5/account/trade-fee":
            rows = [{"makerU": "-0.0002", "takerU": "-0.0005"}]
        elif path == "/api/v5/account/leverage-info":
            rows = [
                {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "long", "lever": "1"},
                {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "short", "lever": "1"},
            ]
        elif path == "/api/v5/trade/order":
            client_id = str(query.get("clOrdId") or "")
            rows = [row for row in self.state["orders"] if row["clOrdId"] == client_id]
        elif path == "/api/v5/trade/order-algo":
            algo_id = str(query.get("algoId") or "")
            client_id = str(query.get("algoClOrdId") or "")
            rows = [row for row in self.state["algos"] if (algo_id and row["algoId"] == algo_id) or (client_id and row["algoClOrdId"] == client_id)]
        else:
            raise AssertionError(f"offline private path not implemented: {path}")
        return OkxDemoResponse("GET", path, 200, "0", "", tuple(rows))

    def observe_funding_bill(
        self, *, bill_id: str, balance_change_usdt: Decimal
    ) -> dict[str, Any]:
        """Persist one deterministic venue funding observation for fixtures."""

        if not bill_id or not balance_change_usdt.is_finite():
            raise ValueError("offline_funding_bill_invalid")
        existing = [
            row for row in self.state["bills"] if str(row.get("billId") or "") == bill_id
        ]
        expected_amount = format(balance_change_usdt, "f")
        if existing:
            if len(existing) != 1 or str(existing[0].get("balChg") or "") != expected_amount:
                raise ValueError("offline_funding_bill_identity_conflict")
            return dict(existing[0])
        self.now += timedelta(milliseconds=1)
        row = {
            "billId": bill_id,
            "instId": "BTC-USDT-SWAP",
            "ccy": "USDT",
            "type": "8",
            "subType": "173",
            "balChg": expected_amount,
            "ts": str(int(self.now.timestamp() * 1000)),
        }
        self.state["bills"].append(row)
        self.state["equity"] = format(
            Decimal(str(self.state["equity"])) + balance_change_usdt, "f"
        )
        self._persist()
        return dict(row)

    def cancel_algo_orders(
        self, orders: Sequence[Mapping[str, Any]]
    ) -> OkxDemoResponse:
        requested = {str(row.get("algoId") or "") for row in orders}
        matched = [row for row in self.state["algos"] if row["algoId"] in requested]
        if not requested or "" in requested or {row["algoId"] for row in matched} != requested:
            return OkxDemoResponse(
                "POST", "/api/v5/trade/cancel-algos", 200, "1", "identity mismatch", ()
            )
        self.now += timedelta(milliseconds=1)
        self.state["cancel_algo_count"] += len(matched)
        for row in matched:
            self.state["algo_history"].append(
                {
                    **row,
                    "state": "canceled",
                    "cTime": str(int(self.now.timestamp() * 1000)),
                }
            )
        self.state["algos"] = [
            row for row in self.state["algos"] if row["algoId"] not in requested
        ]
        self._persist()
        return OkxDemoResponse(
            "POST",
            "/api/v5/trade/cancel-algos",
            200,
            "0",
            "",
            tuple(
                {"algoId": row["algoId"], "sCode": "0", "sMsg": ""}
                for row in matched
            ),
        )

    def revise_residual_protection(
        self,
        *,
        exit_client_order_id: str,
        exit_order_id: str,
        exit_fill_id: str,
        residual_contracts: Decimal,
        position_side: str,
    ) -> dict[str, Any]:
        """Fixture-only exact OCO revision; never available to a real client.

        The economic exit has already been produced by the original OMS and
        raw fill path.  This method changes only the deterministic venue's
        protection row and returns every identity needed for the independent
        residual-revision proof.
        """

        if (
            len(self.state["algos"]) != 1
            or not exit_client_order_id
            or not exit_order_id
            or not exit_fill_id
            or residual_contracts <= 0
            or Decimal(str(self.state["position"])) != residual_contracts
            or position_side != "long"
        ):
            raise ValueError("offline_residual_protection_revision_facts_invalid")
        prior = dict(self.state["algos"][0])
        if prior.get("posSide") != position_side:
            raise ValueError("offline_residual_protection_prior_side_mismatch")
        revision = int(self.state.get("protection_revision_count") or 0) + 1
        self.state["protection_revision_count"] = revision
        self.now += timedelta(milliseconds=1)
        self.state["algo_history"].append(
            {
                **prior,
                "state": "replaced_for_residual_allocation",
                "uTime": str(int(self.now.timestamp() * 1000)),
            }
        )
        replacement = {
            **prior,
            "algoId": f"offline-residual-algo-{revision}",
            "algoClOrdId": f"{exit_client_order_id}R{revision}",
            "parentClOrdId": exit_client_order_id,
            "sz": format(residual_contracts, "f"),
            "state": "live",
            "uTime": str(int(self.now.timestamp() * 1000)),
        }
        self.state["algos"] = [replacement]
        self._persist()
        return {
            "schema_version": "btc_offline_residual_protection_venue_receipt_v1",
            "prior_algo_id": str(prior["algoId"]),
            "prior_algo_client_order_id": str(prior["algoClOrdId"]),
            "prior_parent_client_order_id": str(prior["parentClOrdId"]),
            "prior_contracts": str(prior["sz"]),
            "exit_client_order_id": exit_client_order_id,
            "exit_order_id": exit_order_id,
            "exit_fill_id": exit_fill_id,
            "algo_id": str(replacement["algoId"]),
            "algo_client_order_id": str(replacement["algoClOrdId"]),
            "parent_client_order_id": exit_client_order_id,
            "instrument_id": "BTC-USDT-SWAP",
            "position_side": position_side,
            "contracts": format(residual_contracts, "f"),
            "status": "exchange_accepted",
            "market_exit": True,
            "tp_trigger_px": str(replacement["tpTriggerPx"]),
            "tp_order_px": str(replacement["tpOrdPx"]),
            "sl_trigger_px": str(replacement["slTriggerPx"]),
            "sl_order_px": str(replacement["slOrdPx"]),
        }

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        order = dict(payload)
        client_id = str(order["clOrdId"])
        existing = next((row for row in self.state["orders"] if row["clOrdId"] == client_id), None)
        if existing is not None:
            return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": existing["ordId"], "clOrdId": client_id, "sCode": "0", "sMsg": ""},))
        # A simulated exchange mutation receives the next deterministic
        # observation timestamp.  This mirrors distinct exchange receipts and
        # prevents changed account facts from sharing an observation identity.
        self.now += timedelta(milliseconds=1)
        self.state["submit_count"] += 1
        order_id = f"offline-order-{self.state['submit_count']}"
        size = Decimal(str(order["sz"]))
        position = Decimal(self.state["position"])
        if order["posSide"] == "long":
            position += size if order["side"] == "buy" else -size
        else:
            position += -size if order["side"] == "sell" else size
        self.state["position"] = format(position, "f")
        fill_id = f"offline-fill-{self.state['submit_count']}"
        fee = -(size * Decimal("0.01") * Decimal("60000") * Decimal("0.0005"))
        self.state["equity"] = format(Decimal(self.state["equity"]) + fee, "f")
        attached = []
        for raw in order.get("attachAlgoOrds", []):
            algo_id = f"offline-algo-{self.state['submit_count']}"
            algo = {
                "algoId": algo_id,
                "algoClOrdId": raw["attachAlgoClOrdId"],
                "parentClOrdId": client_id,
                "instId": "BTC-USDT-SWAP",
                "side": "sell" if order["posSide"] == "long" else "buy",
                "posSide": order["posSide"],
                "sz": order["sz"],
                "state": "live",
                "ordType": "oco",
                "tpTriggerPx": raw["tpTriggerPx"],
                "tpTriggerPxType": raw["tpTriggerPxType"],
                "tpOrdPx": raw["tpOrdPx"],
                "slTriggerPx": raw["slTriggerPx"],
                "slTriggerPxType": raw["slTriggerPxType"],
                "slOrdPx": raw["slOrdPx"],
                "uTime": str(int(self.now.timestamp() * 1000)),
            }
            self.state["algos"] = [algo]
            attached.append({"attachAlgoId": algo_id, "attachAlgoClOrdId": algo["algoClOrdId"], "failCode": "0", "failReason": ""})
        final = {**order, "ordId": order_id, "state": "filled", "accFillSz": order["sz"], "avgPx": "60000", "attachAlgoOrds": attached}
        fill = {"tradeId": fill_id, "ordId": order_id, "clOrdId": client_id, "instId": "BTC-USDT-SWAP", "side": order["side"], "posSide": order["posSide"], "fillPx": "60000", "fillSz": order["sz"], "fee": str(fee), "feeCcy": "USDT", "pnl": "0", "ts": str(int(self.now.timestamp() * 1000))}
        self.state["orders"].append(final)
        self.state["fills"].append(fill)
        # A flat fill does not silently erase exchange-hosted protection.
        # The existing controller cleanup/cancel/readback path must drive the
        # OCO to terminal and update its owned registry.
        self._persist()
        return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": order_id, "clOrdId": client_id, "sCode": "0", "sMsg": ""},))


class DonchianOfflineReplay:
    def __init__(self, config: DonchianOfflineReplayConfig) -> None:
        self.config = config
        self._closed = False
        self._canonical_frame_cache = _CanonicalFrameCache()
        # Reserve the supplied observation time for the first decision phase;
        # bootstrap reconciliation is a distinct, explicit prior observation.
        self._now = config.decision_time_utc - timedelta(seconds=1)
        self.completed_bar_time = config.decision_time_utc.replace(minute=0, second=0, microsecond=0)
        self._frame = build_trend_frame("flat", end=self.completed_bar_time)
        self.source_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=config.repo_root, text=True).strip()
        self.spec = btc_strategy_registry.get(STRATEGY_ID)
        self.package_digest = package_digest(strategy_id=self.spec.strategy_id, strategy_version=self.spec.strategy_version, params_hash=self.spec.params_hash, code_version=self.source_head)
        self.identity = {
            "schema_version": IDENTITY_SCHEMA_VERSION,
            "run_id": config.run_id,
            "strategy_id": self.spec.strategy_id,
            "strategy_version": self.spec.strategy_version,
            "params_hash": self.spec.params_hash,
            "code_version": self.source_head,
            "package_digest": self.package_digest,
            "data_version": config.data_version,
            "instrument_id": INSTRUMENT_ID,
        }
        if config.max_notional_usdt != Decimal("10"):
            self.identity["offline_budget"] = {
                "max_notional_usdt": str(config.max_notional_usdt), "max_loss_usdt": "10",
            }
        if config.market_policy_attachment is not None:
            self.identity["market_entry_policy"] = {
                "usage": "research_replay_entry_only",
                "attachment_hash": str(
                    config.market_policy_attachment.get("attachment_hash") or ""
                ),
                "policy_hash": str(config.market_entry_policy.policy_hash),
                "enabled": bool(config.market_entry_policy.enabled),
            }
        self.identity["identity_digest"] = _sha(self.identity)
        self._bootstrap_required = not any(
            path.exists()
            for path in (
                config.state_dir / "offline_venue.json",
                config.state_dir / "runtime",
                config.state_dir / "boundary",
            )
        )
        self._bind_identity_before_runtime_state()
        self.venue = (
            config.venue_factory(config.state_dir / "offline_venue.json", self._now)
            if config.venue_factory is not None
            else _OfflineVenue(config.state_dir / "offline_venue.json", now=self._now)
        )
        latch_path = (config.state_dir / "guardian_latch.json").resolve()
        if self._bootstrap_required:
            _atomic_json(
                latch_path,
                GuardianLatchRecord(
                    generation=1,
                    tripped=False,
                    owner_id="v1-offline",
                    fence_token="v1-offline",
                ).to_dict(),
            )
        latch = FileGuardianLatchStore(latch_path)
        self.guardian_supervisor = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(GuardianConfig(max_abs_exposure=float(config.max_notional_usdt), max_daily_loss=10, max_drawdown=10, max_drawdown_unit="usdt", max_open_orders=1)), latch, owner_id="v1-offline", fence_token="v1-offline")
        self.composition = BtcDemoProductionComposition(source_head=self.source_head, max_configured_leverage=Decimal("1"), max_notional=config.max_notional_usdt, max_loss_usdt=Decimal("10"), guardian_supervisor_factory=lambda: self.guardian_supervisor)
        dispatcher = BTCDemoExecutionDispatcher(expected_source_head=self.source_head, state_directory=config.state_dir / "boundary", capability_adapter=_OfflineCapabilityAdapter(), credential_service="quant-system.okx-demo.offline", clock=lambda: self.venue.now)
        cashflow_provider = getattr(
            self.venue, "cashflow_evidence", self._cashflow_evidence
        )
        runtime_config = OkxDemoPaperRuntimeConfig(repo_root=config.repo_root, data_db_path=config.state_dir / "never.sqlite", output_dir=config.state_dir / "runtime", credential_service="quant-system.okx-demo.offline", order_poll_interval_seconds=0.001, order_poll_attempts=1, max_configured_leverage=Decimal("1"), risk_profile="baseline_1x", runtime_identity="v1-offline", execution_dispatcher=dispatcher, authoritative_oms_bundle_provider=self.composition.build_order_submission_bundle, offline_completed_frame_provider=lambda: self._frame, account_cashflow_evidence_provider=cashflow_provider)
        try:
            self.controller = _OfflineSignalMemoController(config=runtime_config, credential_loader=lambda _name: (_ for _ in ()).throw(AssertionError("credentials prohibited")), client_factory=lambda _cfg, _creds: self.venue, private_ws_factory=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("private ws prohibited")), clock=lambda: self.venue.now, start_worker=False, start_capability_checker=lambda: {"ready": False, "blockers": ["offline_execution_only"]})
            self.controller._offline_market_entry_policy = (
                config.market_entry_policy
            )
            self.controller._offline_market_state_provider = (
                config.market_state_provider
            )
            self.controller._offline_market_policy_attachment = (
                dict(config.market_policy_attachment)
                if config.market_policy_attachment is not None
                else None
            )
            self._finish_initial_recovery()
        except BaseException:
            try:
                self.guardian_supervisor.close()
            finally:
                if hasattr(self, "controller"):
                    self.controller._runtime_store.close()
            raise

    def _finish_initial_recovery(self) -> None:
        self._attach_transport()
        self._clean_stop_recovery_authorized = self._has_exact_clean_stop(
            self.controller._runtime_store.recover()
        )
        self._clean_stop_projection_digest = (
            self._recovery_authority_digest(
                self.controller._durable_state_snapshot()
            )
            if self._clean_stop_recovery_authorized
            else ""
        )
        self._activate_initial_state()

    def _bind_identity_before_runtime_state(self) -> None:
        binding = self.config.state_dir / "offline_replay_identity.json"
        prior_runtime = any(
            path.exists()
            for path in (
                self.config.state_dir / "offline_venue.json",
                self.config.state_dir / "runtime",
                self.config.state_dir / "boundary",
            )
        )
        if binding.exists():
            observed = json.loads(binding.read_text(encoding="utf-8"))
            if observed != self.identity:
                changed = sorted(
                    name
                    for name in set(observed) | set(self.identity)
                    if observed.get(name) != self.identity.get(name)
                )
                raise ValueError("offline_replay_identity_mismatch:" + ",".join(changed))
            return
        if prior_runtime:
            raise ValueError("offline_replay_identity_binding_missing")
        _atomic_json(binding, self.identity)

    def _attach_transport(self) -> None:
        self.controller._protection_policy = ServerSideProtectionPolicy.from_mapping(
            OKX_DEMO_APPROVED_PROTECTION_POLICY
        )
        self.controller._client = self.venue

    def _cashflow_evidence(self, **kwargs: Any) -> Mapping[str, Any]:
        begin = str(int(pd.Timestamp(kwargs["coverage_start_utc"]).timestamp() * 1000))
        end = str(int(pd.Timestamp(kwargs["coverage_end_utc"]).timestamp() * 1000))
        pages = [{"request": {"begin": begin, "end": end, "limit": "100"}, "rows": []}]
        return build_okx_account_cashflow_evidence(pages=pages, account_identity_hash=kwargs["account_identity_hash"], snapshot_sha256=kwargs["snapshot_sha256"], coverage_start_utc=kwargs["coverage_start_utc"], coverage_end_utc=kwargs["coverage_end_utc"], reference_time_utc=kwargs["reference_time_utc"])

    def _set_explicit_offline_runtime_facts(self, *, active: bool) -> None:
        state = self.controller._state
        state["strategy"] = self.spec.identity()
        state["limits"].update(
            {
                "order_contracts": "0.01",
                "max_net_contracts": "0.01",
                "max_notional_usdt": str(self.config.max_notional_usdt),
                "margin_mode": "isolated",
            }
        )
        if self.config.max_notional_usdt != Decimal("10"):
            state["limits"]["max_loss_usdt"] = "10"
        state["runtime"].update(
            {
                "run_id": self.config.run_id,
                "active": active,
                "status": "offline_execution" if active else "offline_reconciling",
                "opening_allowed": active,
                "cancel_only": not active,
                "source_head": self.source_head,
                "authoritative_liveness_epoch": 1,
                "credential_namespace": "quant-system.okx-demo.offline",
                "last_heartbeat_utc": self._now.isoformat(),
            }
        )
        state["risk_control"].update(
            {
                "mode": "RUNNING" if active else "FROZEN_UNKNOWN",
                "write_path_trusted": active,
            }
        )
        state["risk_control"]["dead_man"].update(
            {"armed": True, "last_ack_utc": self._now.isoformat()}
        )
        state["private_ws"].update(
            {
                "status": "connected" if active else "reconciling",
                "connected": active,
                "listener_alive": active,
                "opening_allowed_after_reconciliation": active,
            }
        )

    def _activate_initial_state(self) -> None:
        recovered = self.controller._runtime_store.recover()
        if recovered.events:
            return
        self._set_explicit_offline_runtime_facts(active=False)
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        baseline_snapshot = _sha(
            {
                "kind": "v1_offline_pre_decision_baseline",
                "run_id": self.config.run_id,
                "observed_at_utc": (self._now - timedelta(seconds=1)).isoformat(),
            }
        )
        baseline = build_explicit_account_drawdown_baseline(
            authority=ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
            account_identity_hash=snapshot["account"]["identity"]["hash"],
            account_scope=ACCOUNT_DRAWDOWN_SCOPE,
            currency="USDT",
            snapshot_sha256=baseline_snapshot,
            observed_at_utc=self._now - timedelta(seconds=1),
            equity_usdt=snapshot["balance"]["equity_usdt"],
            history_complete=False,
            baseline_event_sequence=0,
        )
        self.controller._state["account_risk_facts"] = baseline
        self.controller._state["account_risk_last_valid_fact"] = baseline
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        self.controller._commit_ledger_reconciliation(
            snapshot=snapshot, trigger="offline_activation"
        )
        self._assert_ledger_current(snapshot)
        self._set_explicit_offline_runtime_facts(active=True)
        self.controller._persist_state()

    def _assert_ledger_current(self, snapshot: Mapping[str, Any]) -> None:
        ledger = self.controller._state.get("ledger_reconciliation", {})
        expected = canonical_ledger_snapshot_sha256(snapshot)
        if not (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
            and ledger.get("exchange_snapshot_sha256") == expected
            and ledger.get("funding_cashflow_reconciled") is True
            and self.controller._state.get("account_risk_facts", {}).get("risk_eligible")
            is True
        ):
            raise OkxDemoPaperRuntimeError(
                "offline_replay_ledger_or_drawdown_not_current"
            )

    def _has_exact_clean_stop(self, recovered: Any) -> bool:
        persisted = recovered.state or {}
        persisted_runtime = persisted.get("runtime", {})
        persisted_risk = persisted.get("risk_control", {})
        persisted_private_ws = persisted.get("private_ws", {})
        lifecycle_events = [
            event
            for event in recovered.events
            if event.get("event_type")
            in {
                "offline_replay_clean_stopped",
                "offline_replay_runtime_resumed",
            }
            and event.get("payload", {}).get("identity_digest")
            == self.identity["identity_digest"]
        ]
        latest_lifecycle = lifecycle_events[-1] if lifecycle_events else {}
        return bool(
            latest_lifecycle.get("event_type") == "offline_replay_clean_stopped"
            and persisted_runtime.get("status") == "offline_clean_stopped"
            and persisted_runtime.get("active") is False
            and persisted_runtime.get("opening_allowed") is False
            and persisted_runtime.get("cancel_only") is False
            and persisted_risk.get("mode") == "FROZEN_UNKNOWN"
            and persisted_risk.get("write_path_trusted") is False
            and persisted_private_ws.get("connected") is False
            and persisted_private_ws.get("listener_alive") is False
        )

    @staticmethod
    def _recovery_authority_digest(state: Mapping[str, Any]) -> str:
        runtime = state.get("runtime", {})
        risk = state.get("risk_control", {})
        private_ws = state.get("private_ws", {})
        return _sha(
            {
                "runtime": {
                    name: runtime.get(name)
                    for name in (
                        "run_id",
                        "source_head",
                        "active",
                        "opening_allowed",
                        "cancel_only",
                        "status",
                        "blockers",
                    )
                },
                "risk_control": {
                    name: risk.get(name)
                    for name in (
                        "mode",
                        "write_path_trusted",
                        "reason",
                        "blockers",
                        "pending_order_intents",
                    )
                },
                "private_ws": {
                    name: private_ws.get(name)
                    for name in (
                        "status",
                        "connected",
                        "listener_alive",
                        "opening_allowed_after_reconciliation",
                    )
                },
            }
        )

    def _resume_after_verified_recovery(self) -> None:
        # The deterministic clock advances with each completed-bar checkpoint.
        # Reconcile the persisted ledger to that newly observed account snapshot
        # even when the prior phase stopped cleanly; an old snapshot hash must
        # never be reused as current broker truth.
        clean_stop = (
            self._clean_stop_recovery_authorized
            and self._clean_stop_projection_digest
            == self._recovery_authority_digest(
                self.controller._durable_state_snapshot()
            )
            and self.guardian_supervisor.tripped is False
            and not self.guardian_supervisor.persistence_error
        )

        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        self.controller._commit_ledger_reconciliation(
            snapshot=snapshot, trigger="offline_recovery_reconciliation"
        )
        self._assert_ledger_current(snapshot)
        if clean_stop:
            # Only the adapter's own exact clean-stop checkpoint may restore
            # its simulated healthy facts.  Unclean or externally frozen
            # recovery keeps the controller's fail-closed state untouched.
            self._set_explicit_offline_runtime_facts(active=True)
            self._clean_stop_recovery_authorized = False
        liveness = self._observe_offline_liveness()
        state_after = self.controller._durable_state_snapshot()
        if state_after["runtime"].get("active") is not True:
            self.controller._persist_state()
            return
        self.controller._runtime_store.append(
            event_type="offline_replay_runtime_resumed",
            payload={
                "identity_digest": self.identity["identity_digest"],
                "exchange_snapshot_sha256": canonical_ledger_snapshot_sha256(snapshot),
                "ledger_reconciled": True,
                "offline_execution_only": True,
                "simulated_liveness": liveness,
            },
            state_after=state_after,
            idempotency_key=(
                f"offline-resume:{self.identity['identity_digest']}:{self._now.isoformat()}"
            ),
            timestamp_utc=self._now.isoformat(),
            run_id=self.config.run_id,
            safety=dict(state_after["safety"]),
        )
        self.controller._persist_state()

    def _observe_offline_liveness(self) -> Mapping[str, Any]:
        """Renew only simulated timing after identity/recovery/ledger checks.

        Never restore trust, mode, connection or permissions here. Their
        restoration remains confined to the original exact clean-stop path.
        The production controller's 30-second freshness check is unchanged.
        """
        state = self.controller._state
        runtime, risk, ws = state["runtime"], state["risk_control"], state["private_ws"]
        dead_man = risk["dead_man"]
        if not (
            isinstance(self.venue, _OfflineVenue)
            and self.controller._client is self.venue
            and self.controller.config.offline_completed_frame_provider is not None
            and runtime.get("credential_namespace") == "quant-system.okx-demo.offline"
            and runtime.get("authoritative_liveness_required") is False
            and runtime.get("active") is True
            and runtime.get("opening_allowed") is True
            and runtime.get("cancel_only") is False
            and risk.get("mode") == "RUNNING"
            and risk.get("write_path_trusted") is True
            and dead_man.get("armed") is True
            and ws.get("connected") is True
            and ws.get("listener_alive") is True
            and ws.get("opening_allowed_after_reconciliation") is True
            and self.guardian_supervisor.tripped is False
            and not self.guardian_supervisor.persistence_error
        ):
            reason = "offline_liveness_boundary_unhealthy"
            self.controller._degrade_after_cycle_error(reason, recoverable=False)
            self.controller._persist_state()
            raise OkxDemoPaperRuntimeError(reason)
        try:
            receipt = dict(self.venue.observe_offline_liveness(
                identity_digest=self.identity["identity_digest"]
            ))
            observed = datetime.fromisoformat(receipt["observed_at_utc"])
            if not (
                receipt.get("schema_version") == "offline_liveness_observation_v1"
                and receipt.get("identity_digest") == self.identity["identity_digest"]
                and receipt.get("acknowledged") is True
                and receipt.get("offline_execution_only") is True
                and observed.tzinfo is not None
                and timedelta(0) <= self._now - observed <= timedelta(
                    seconds=self.controller.config.dead_man_timeout_seconds
                )
                and self.venue.now == self._now
            ):
                raise ValueError("invalid simulated receipt")
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            # A failed simulated renewal is a failure, not a clean stop that
            # could implicitly repair the missing acknowledgement on restart.
            reason = "offline_liveness_receipt_invalid"
            self.controller._degrade_after_cycle_error(reason, recoverable=False)
            self.controller._append_event("offline_liveness_failed", {"error": reason})
            self.controller._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc
        dead_man["last_ack_utc"] = observed.isoformat()
        return receipt

    def reconcile_terminal_observation(
        self, *, completed_bar: datetime, observation_time: datetime,
        fail_after_ledger_before_evidence: bool = False,
    ) -> dict[str, Any]:
        """Observe existing historical economics; never run a decision/order cycle.

        The original controller/store remains the ledger authority. A terminal
        input is an observation, not a fabricated executable next candle.
        """
        if (self._closed or self.config.venue_factory is None
            or self.config.decision_time_provider is None
            or self.venue.state.get("schema_version") != "btc_donchian_historical_venue_state_v1"
            or self.venue.state.get("quote")):
            raise OkxDemoPaperRuntimeError("offline_terminal_requires_historical_no_next_bar")
        if any(t.tzinfo is None or t.utcoffset() is None for t in (completed_bar, observation_time)):
            raise OkxDemoPaperRuntimeError("offline_terminal_timezone_required")
        completed_bar = completed_bar.astimezone(timezone.utc)
        observation_time = observation_time.astimezone(timezone.utc)
        events = self.venue.state.get("historical_events") or []
        if (observation_time < completed_bar or not events
            or events[-1].get("available_time_utc") != completed_bar.isoformat()):
            raise OkxDemoPaperRuntimeError("offline_terminal_event_time_invalid")
        recovery = self.controller._runtime_store.recover()
        if recovery.blockers:
            raise OkxDemoPaperRuntimeError("offline_terminal_recovery_blocked")
        self._assert_runtime_identity(recovery)
        pending = recovery.state.get("risk_control", {}).get("pending_order_intents", {})
        if any(isinstance(row, Mapping) and row.get("status") in {"submit_pending", "unknown", "accepted", "reconciled_open"} for row in pending.values()):
            raise OkxDemoPaperRuntimeError("offline_terminal_unresolved_order_intent")
        fact = recovery.state.get("account_risk_facts") or {}
        if fact.get("observed_at_utc") and observation_time < pd.Timestamp(fact["observed_at_utc"]).to_pydatetime():
            raise OkxDemoPaperRuntimeError("offline_terminal_time_regression")
        self._now = self.venue.now = observation_time
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        snapshot_hash = canonical_ledger_snapshot_sha256(snapshot)
        prior = [e for e in recovery.events if e.get("event_type") == "ledger_uow_committed"
                 and e.get("payload", {}).get("account_drawdown_fact", {}).get("snapshot_sha256") == snapshot_hash
                 and e.get("payload", {}).get("account_drawdown_fact", {}).get("observed_at_utc") == observation_time.isoformat().replace("+00:00", "Z")]
        if not prior:
            self.controller._apply_snapshot(snapshot)
            self.controller._commit_ledger_reconciliation(snapshot=snapshot, trigger="offline_terminal_observation")
            recovery = self.controller._runtime_store.recover()
            prior = [e for e in recovery.events if e.get("event_type") == "ledger_uow_committed"
                     and e.get("payload", {}).get("account_drawdown_fact", {}).get("snapshot_sha256") == snapshot_hash
                     and e.get("payload", {}).get("account_drawdown_fact", {}).get("observed_at_utc") == observation_time.isoformat().replace("+00:00", "Z")]
        self._assert_ledger_current(snapshot)
        if len(prior) != 1 or prior[0]["payload"]["risk_context"]["account_ledger_replay"].get("reconciled") is not True:
            raise OkxDemoPaperRuntimeError("offline_terminal_ledger_not_exact")
        if fail_after_ledger_before_evidence:
            raise RuntimeError("injected_terminal_ledger_before_evidence_crash")
        ledger = prior[0]
        receipt = {
            "identity_digest": self.identity["identity_digest"],
            "completed_bar_close_utc": completed_bar.isoformat(),
            "observation_time_utc": observation_time.isoformat(),
            "exchange_snapshot_sha256": snapshot_hash,
            "ledger_event_id": ledger["idempotency_key"], "ledger_event_hash": ledger["event_hash"],
            "position_contracts": ledger["payload"]["position_ledger"]["signed_contracts"],
            "funding_cashflow_usdt": ledger["payload"]["funding_ledger"]["cashflow"],
            "no_new_decision_or_order": True, "runtime_observed": False,
        }
        state = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="offline_terminal_observation_reconciled", payload=receipt,
            state_after=state, idempotency_key=f"offline-terminal:{self.identity['identity_digest']}:{completed_bar.isoformat()}",
            timestamp_utc=observation_time.isoformat(), run_id=self.config.run_id,
            safety=dict(state["safety"]),
        )
        return receipt

    def close(self) -> None:
        try:
            self._close_with_evidence()
        finally:
            try:
                self.guardian_supervisor.close()
            finally:
                self.controller._runtime_store.close()

    def _close_with_evidence(self) -> None:
        """Release the durable Guardian single-writer lease for a restart."""

        if self._closed:
            return
        self._closed = True
        state = self.controller._state
        pending = state.get("risk_control", {}).get("pending_order_intents", {})
        unresolved_pending = any(
            isinstance(row, Mapping)
            and str(row.get("status") or "")
            in {"submit_pending", "unknown", "accepted", "reconciled_open"}
            for row in pending.values()
        )
        healthy = (
            state.get("runtime", {}).get("active") is True
            and state.get("runtime", {}).get("opening_allowed") is True
            and state.get("runtime", {}).get("cancel_only") is False
            and state.get("risk_control", {}).get("mode") == "RUNNING"
            and state.get("risk_control", {}).get("write_path_trusted") is True
            and state.get("private_ws", {}).get("connected") is True
            and state.get("private_ws", {}).get("listener_alive") is True
            and state.get("private_ws", {}).get(
                "opening_allowed_after_reconciliation"
            )
            is True
            and not unresolved_pending
            and self.guardian_supervisor.tripped is False
            and not self.guardian_supervisor.persistence_error
        )
        if healthy:
            state["runtime"].update(
                {
                    "active": False,
                    "opening_allowed": False,
                    "cancel_only": False,
                    "status": "offline_clean_stopped",
                }
            )
            state["risk_control"].update(
                {"mode": "FROZEN_UNKNOWN", "write_path_trusted": False}
            )
            state["private_ws"].update(
                {
                    "status": "disconnected",
                    "connected": False,
                    "listener_alive": False,
                    "opening_allowed_after_reconciliation": False,
                }
            )
            state_after = self.controller._durable_state_snapshot()
            self.controller._runtime_store.append(
                event_type="offline_replay_clean_stopped",
                payload={
                    "identity_digest": self.identity["identity_digest"],
                    "offline_execution_only": True,
                },
                state_after=state_after,
                idempotency_key=(
                    "offline-clean-stop:"
                    + self.identity["identity_digest"]
                    + ":"
                    + str(state["runtime"].get("last_processed_bar_close_utc") or "none")
                ),
                timestamp_utc=self._now.isoformat(),
                run_id=self.config.run_id,
                safety=dict(state_after["safety"]),
            )
            self.controller._persist_state()

    def __enter__(self) -> "DonchianOfflineReplay":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def evaluate_frame(self, frame: pd.DataFrame, *, visible_until: datetime | None = None) -> Mapping[str, Any]:
        visible = frame.loc[:visible_until] if visible_until is not None else frame
        self._frame, _ = self._canonical_frame_cache(visible)
        return self.controller._signal_decision(self.spec.identity())

    def _assert_runtime_identity(self, recovery: Any) -> None:
        state = recovery.state or {}
        if not state:
            return
        runtime = state.get("runtime", {})
        strategy = state.get("strategy", {})
        comparisons = {
            "run_id": (runtime.get("run_id"), self.config.run_id),
            "source_head": (runtime.get("source_head"), self.source_head),
            "strategy_id": (strategy.get("strategy_id"), self.spec.strategy_id),
            "strategy_version": (
                strategy.get("strategy_version"),
                self.spec.strategy_version,
            ),
            "params_hash": (strategy.get("params_hash"), self.spec.params_hash),
        }
        mismatches = [
            name
            for name, (observed, expected) in comparisons.items()
            if observed and observed != expected
        ]
        if mismatches:
            raise OkxDemoPaperRuntimeError(
                "offline_replay_runtime_identity_mismatch:"
                + ",".join(sorted(mismatches))
            )

    def _event_identity(
        self, *, frame_digest: str, completed_bar: str
    ) -> tuple[str, Mapping[str, Any]]:
        payload = {
            "schema_version": INPUT_SCHEMA_VERSION,
            "identity_digest": self.identity["identity_digest"],
            "run_id": self.config.run_id,
            "package_digest": self.package_digest,
            "strategy_id": self.spec.strategy_id,
            "strategy_version": self.spec.strategy_version,
            "params_hash": self.spec.params_hash,
            "code_version": self.source_head,
            "data_version": self.config.data_version,
            "instrument_id": INSTRUMENT_ID,
            "completed_bar_close_utc": completed_bar,
            "frame_digest": frame_digest,
            "row_count": len(self._frame),
        }
        return _sha(payload), payload

    def _assert_same_bar_input_not_changed(
        self,
        events: Sequence[Mapping[str, Any]],
        input_payload: Mapping[str, Any],
    ) -> None:
        for event in events:
            if event.get("event_type") != "offline_replay_input_bound":
                continue
            observed = event.get("payload", {})
            if (
                observed.get("identity_digest") == self.identity["identity_digest"]
                and observed.get("completed_bar_close_utc")
                == input_payload["completed_bar_close_utc"]
                and observed.get("frame_digest") != input_payload["frame_digest"]
            ):
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_same_bar_input_conflict"
                )

    @staticmethod
    def _event_slice(
        events: Sequence[Mapping[str, Any]], *, event_id: str, phase: str
    ) -> list[Mapping[str, Any]]:
        anchors = [
            index
            for index, event in enumerate(events)
            if event.get("event_type") == "offline_replay_input_bound"
            and event.get("payload", {}).get("event_id") == event_id
            and event.get("payload", {}).get("phase") == phase
        ]
        if len(anchors) != 1:
            return []
        start = anchors[0]
        end = next(
            (
                index
                for index in range(start + 1, len(events))
                if events[index].get("event_type") == "offline_replay_input_bound"
            ),
            len(events),
        )
        return list(events[start:end])

    def _evidence_events(
        self, events: Sequence[Mapping[str, Any]], event_id: str
    ) -> list[Mapping[str, Any]]:
        return [
            event
            for event in events
            if event.get("event_type") == "strategy_decision_evidence"
            and event.get("payload", {}).get("event_id") == event_id
        ]

    def _determine_phase(
        self,
        *,
        recovery: Any,
        event_id: str,
        preview: Mapping[str, Any],
    ) -> tuple[str, bool]:
        evidence = self._evidence_events(recovery.events, event_id)
        phases = {
            str(event.get("payload", {}).get("phase") or "")
            for event in evidence
        }
        for terminal in ("reversal_open", "exit", "primary", "hold"):
            if terminal in phases:
                return terminal, True
        anchors = {
            str(event.get("payload", {}).get("phase") or "")
            for event in recovery.events
            if event.get("event_type") == "offline_replay_input_bound"
            and event.get("payload", {}).get("event_id") == event_id
        }
        incomplete = sorted(phase for phase in anchors if phase not in phases)
        if len(incomplete) > 1:
            raise OkxDemoPaperRuntimeError(
                "offline_replay_incomplete_phase_ambiguous"
            )
        if incomplete:
            return incomplete[0], False
        current = Decimal(str(self.venue.state["position"]))
        target = Decimal(str(preview["target_contracts"]))
        if "reversal_close" in phases:
            if current != 0:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_reversal_close_not_flat"
                )
            if target == 0:
                policy = preview.get("market_entry_policy")
                if (
                    not isinstance(policy, Mapping)
                    or policy.get("applied") is not True
                    or policy.get("effective_target_contracts") != "0"
                    or policy.get("original_target_contracts") in {None, "0"}
                ):
                    raise OkxDemoPaperRuntimeError(
                        "offline_replay_reversal_reopen_target_missing"
                    )
                # The original strategy requested the reopen.  The separately
                # frozen entry-only policy may reject only this flat phase;
                # persist it under the existing reversal_open phase so retries
                # and recovery remain terminal and idempotent.
            return "reversal_open", False
        if current == target:
            return "hold", False
        if current != 0 and target != 0 and (current > 0) != (target > 0):
            return "reversal_close", False
        if target == 0 and current != 0:
            return "exit", False
        return "primary", False

    def _bind_input(
        self,
        *,
        event_id: str,
        phase: str,
        input_payload: Mapping[str, Any],
    ) -> None:
        payload = {
            **dict(input_payload),
            "event_id": event_id,
            "phase": phase,
            "decision_time_utc": self._now.isoformat(),
        }
        recovery = self.controller._runtime_store.recover()
        existing = [
            event.get("payload", {})
            for event in recovery.events
            if event.get("event_type") == "offline_replay_input_bound"
            and event.get("payload", {}).get("event_id") == event_id
            and event.get("payload", {}).get("phase") == phase
        ]
        if existing:
            if len(existing) != 1 or existing[0] != payload:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_phase_input_binding_conflict"
                )
            return
        state_after = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="offline_replay_input_bound",
            payload=payload,
            state_after=state_after,
            idempotency_key=f"offline-input:{event_id}:{phase}",
            timestamp_utc=self._now.isoformat(),
            run_id=self.config.run_id,
            safety=dict(state_after["safety"]),
        )

    def _build_context(
        self, *, event_time: str, frame_digest: str
    ) -> StrategyDecisionContext:
        bar_time = pd.Timestamp(event_time).to_pydatetime()
        return StrategyDecisionContext(
            identity=StrategyIdentity(
                run_id=self.config.run_id,
                strategy_id=self.spec.strategy_id,
                strategy_version=self.spec.strategy_version,
                code_version=self.source_head,
                data_version=self.config.data_version,
            ),
            clock=StrategyClock(
                mode=StrategyRuntimeMode.REPLAY,
                event_time=bar_time,
                available_time=bar_time,
                decision_time=self._now,
                is_new_bar=True,
                is_final=True,
            ),
            market={
                "instrument_id": INSTRUMENT_ID,
                "completed_bar_close_utc": event_time,
                "canonical_frame_digest": frame_digest,
                "visible_row_count": len(self._frame),
            },
            universe=(INSTRUMENT_ID,),
            capabilities=(
                StrategyDecisionCapability.SIGNAL,
                StrategyDecisionCapability.TARGET_POSITION,
                StrategyDecisionCapability.ORDER_INTENT,
            ),
            parameters=dict(self.spec.params),
        )

    @staticmethod
    def _lifecycle_client_id(event: Mapping[str, Any]) -> str:
        return str(
            event.get("payload", {}).get("oms", {}).get("client_order_id") or ""
        )

    def _assert_envelope_identity(self, envelope: DecisionEvidenceEnvelope) -> None:
        expected = {
            "run_id": self.config.run_id,
            "strategy_id": self.spec.strategy_id,
            "strategy_version": self.spec.strategy_version,
            "code_version": self.source_head,
            "data_version": self.config.data_version,
        }
        mismatches = [
            name for name, value in expected.items() if getattr(envelope, name) != value
        ]
        if mismatches:
            raise OkxDemoPaperRuntimeError(
                "offline_replay_evidence_identity_mismatch:" + ",".join(mismatches)
            )

    def _recover_phase_outcome(
        self,
        *,
        event_id: str,
        phase: str,
        frame_digest: str,
        event_time: str,
    ) -> Mapping[str, Any] | None:
        recovery = self.controller._runtime_store.recover()
        existing = [
            event
            for event in self._evidence_events(recovery.events, event_id)
            if event.get("payload", {}).get("phase") == phase
        ]
        if existing:
            if len(existing) != 1:
                raise OkxDemoPaperRuntimeError("offline_replay_duplicate_evidence")
            envelope = DecisionEvidenceEnvelope.from_mapping(existing[0]["payload"])
            envelope.require_binding(
                package_digest=self.package_digest,
                input_digest=frame_digest,
            )
            self._assert_envelope_identity(envelope)
            return envelope.to_dict()
        scoped = self._event_slice(
            recovery.events, event_id=event_id, phase=phase
        )
        if not scoped:
            return None
        no_order = [
            event for event in scoped if event.get("event_type") == "signal_no_order"
        ]
        lifecycles = [
            event for event in scoped if event.get("event_type") == "order_lifecycle"
        ]
        if no_order and lifecycles:
            raise OkxDemoPaperRuntimeError("offline_replay_outcome_ambiguous")
        links: dict[str, Any]
        if no_order:
            if len(no_order) != 1:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_no_order_outcome_ambiguous"
                )
            decision = no_order[0]["payload"].get("signal", {})
            links = {
                "decision_outcome": "no_order",
                "decision_digest": _sha(decision),
                "raw_signal": decision.get("raw_signal"),
                "target_contracts": decision.get("target_contracts"),
                "current_contracts": no_order[0]["payload"].get(
                    "current_contracts"
                ),
                "order_intent_id": None,
                "client_order_id": None,
                "exchange_order_id": None,
                "fill_ids": [],
                "ledger_event_id": None,
                "ledger_event_hash": None,
                "action": "hold",
            }
        elif lifecycles:
            if len(lifecycles) != 1:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_order_outcome_ambiguous"
                )
            lifecycle = lifecycles[0]
            audit = lifecycle["payload"]
            client_id = self._lifecycle_client_id(lifecycle)
            fill_ids = [
                str(row.get("fill_id") or "") for row in audit.get("fills", [])
            ]
            lifecycle_sequence = int(lifecycle.get("sequence") or 0)
            ledger_candidates = []
            for event in scoped:
                if (
                    event.get("event_type") != "ledger_uow_committed"
                    or int(event.get("sequence") or 0) <= lifecycle_sequence
                ):
                    continue
                payload = event.get("payload", {})
                orders = payload.get("order_ledger", {}).get("orders", [])
                ledger_fills = payload.get("fill_ledger", [])
                if (
                    any(
                        str(row.get("client_order_id") or "") == client_id
                        for row in orders
                    )
                    and all(
                        any(
                            str(row.get("fill_id") or "") == fill_id
                            for row in ledger_fills
                        )
                        for fill_id in fill_ids
                    )
                ):
                    ledger_candidates.append(event)
            if not ledger_candidates:
                return None
            ledger = ledger_candidates[-1]
            links = {
                "decision_outcome": "order_terminal",
                "signal_id": audit["signal"]["signal_id"],
                "target_position_id": audit["target_position"][
                    "target_position_id"
                ],
                "risk_check_id": audit["risk_decision"]["risk_check_id"],
                "order_intent_id": audit["oms"]["order_intent_id"],
                "client_order_id": client_id,
                "exchange_order_id": audit["exchange_order_id"],
                "fill_ids": fill_ids,
                "ledger_event_id": ledger["idempotency_key"],
                "ledger_event_hash": ledger["event_hash"],
                "action": audit["order_plan"]["action"],
            }
        else:
            return None
        envelope = DecisionEvidenceEnvelope.build(
            context=self._build_context(
                event_time=event_time, frame_digest=frame_digest
            ),
            package_digest=self.package_digest,
            event_id=event_id,
            phase=phase,
            links=links,
            input_digest=frame_digest,
        )
        state_after = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="strategy_decision_evidence",
            payload=envelope.to_dict(),
            state_after=state_after,
            idempotency_key=f"decision-evidence:{envelope.decision_id}",
            timestamp_utc=self._now.isoformat(),
            run_id=self.config.run_id,
            safety=dict(state_after["safety"]),
        )
        return envelope.to_dict()

    def _cleanup_flat_protection(self) -> None:
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        if (
            Decimal(str(self.venue.state["position"])) != 0
            or not snapshot.get("pending_algo_orders")
        ):
            return
        refreshed, _receipt = self.controller._cleanup_owned_flat_algos(
            self.venue, snapshot=snapshot
        )
        self.controller._apply_snapshot(refreshed)
        self.controller._commit_ledger_reconciliation(
            snapshot=refreshed,
            trigger="offline_flat_protection_cleanup",
        )
        self._assert_ledger_current(refreshed)

    def run_frame(
        self,
        frame: pd.DataFrame,
        *,
        fail_after_ledger_before_evidence: bool = False,
    ) -> dict[str, Any]:
        self._frame, frame_digest = self._canonical_frame_cache(frame)
        completed = pd.Timestamp(self._frame.index[-1]).to_pydatetime()
        completed_bar = completed.isoformat()
        self.completed_bar_time = completed
        # A historical resume constructs the venue before the exact recovered
        # phase/ordinal is known.  Advance only the in-memory observation clock
        # enough for this signal preview; the exact persisted phase timestamp
        # is selected below from its anchor or deterministic provider.
        if (
            self.config.decision_time_provider is not None
            and self.venue.now < completed
        ):
            self._now = completed
            self.venue.now = completed
        if (
            self.config.decision_time_provider is None
            and completed > self.config.decision_time_utc
        ):
            raise OkxDemoPaperRuntimeError("offline_replay_future_completed_bar")
        recovery = self.controller._runtime_store.recover()
        if recovery.blockers:
            raise OkxDemoPaperRuntimeError(
                "offline_replay_recovery_blocked:" + ",".join(recovery.blockers)
            )
        self._assert_runtime_identity(recovery)
        event_id, input_payload = self._event_identity(
            frame_digest=frame_digest, completed_bar=completed_bar
        )
        self._assert_same_bar_input_not_changed(recovery.events, input_payload)
        prior_bar_times = [
            pd.Timestamp(event.get("payload", {}).get("completed_bar_close_utc"))
            for event in recovery.events
            if event.get("event_type") == "offline_replay_input_bound"
            and event.get("payload", {}).get("identity_digest")
            == self.identity["identity_digest"]
        ]
        if prior_bar_times and pd.Timestamp(completed) < max(prior_bar_times):
            raise OkxDemoPaperRuntimeError("offline_replay_event_time_regression")

        preview = self.controller._signal_decision(self.spec.identity())
        phase, terminal = self._determine_phase(
            recovery=recovery, event_id=event_id, preview=preview
        )
        phase_anchors = [
            event.get("payload", {})
            for event in recovery.events
            if event.get("event_type") == "offline_replay_input_bound"
            and event.get("payload", {}).get("identity_digest")
            == self.identity["identity_digest"]
        ]
        exact_anchor = next(
            (
                row
                for row in phase_anchors
                if row.get("event_id") == event_id and row.get("phase") == phase
            ),
            None,
        )
        if exact_anchor is not None:
            self._now = pd.Timestamp(
                exact_anchor["decision_time_utc"]
            ).to_pydatetime()
        else:
            observation_ordinal = len(phase_anchors)
            if (
                self.config.decision_time_provider is None
                and observation_ordinal > 4
            ):
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_observation_budget_exhausted"
                )
            # Market-event time and account-observation time are deliberately
            # distinct.  Five frozen V1 phases receive a deterministic,
            # monotonic observation sequence inside the dispatcher's freshness
            # window; exact retries reuse the persisted phase timestamp.
            if self.config.decision_time_provider is None:
                self._now = self.config.decision_time_utc + timedelta(
                    seconds=observation_ordinal
                )
            else:
                supplied = self.config.decision_time_provider(
                    completed, observation_ordinal, phase
                )
                if supplied.tzinfo is None or supplied.utcoffset() is None:
                    raise OkxDemoPaperRuntimeError(
                        "offline_replay_supplied_decision_time_timezone"
                    )
                self._now = supplied.astimezone(timezone.utc)
                if self._now < completed:
                    raise OkxDemoPaperRuntimeError(
                        "offline_replay_supplied_decision_time_before_event"
                    )
        self.venue.now = self._now
        if terminal:
            envelope = self._recover_phase_outcome(
                event_id=event_id,
                phase=phase,
                frame_digest=frame_digest,
                event_time=completed_bar,
            )
            if envelope is None:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_terminal_evidence_missing"
                )
            return self._result(
                event_id=event_id,
                phase=phase,
                envelope=envelope,
            )

        self._bind_input(
            event_id=event_id, phase=phase, input_payload=input_payload
        )
        recovered_outcome = self._recover_phase_outcome(
            event_id=event_id,
            phase=phase,
            frame_digest=frame_digest,
            event_time=completed_bar,
        )
        if recovered_outcome is not None:
            return self._result(
                event_id=event_id,
                phase=phase,
                envelope=recovered_outcome,
            )

        unresolved_pending = any(
            isinstance(row, Mapping)
            and str(row.get("status") or "")
            in {"submit_pending", "unknown", "accepted", "reconciled_open"}
            for row in (
                recovery.state.get("risk_control", {})
                .get("pending_order_intents", {})
                .values()
            )
        )
        if unresolved_pending:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_order_submit_blocked_by_unresolved_intent"
            )

        self._resume_after_verified_recovery()
        self.controller.run_cycle()
        self._cleanup_flat_protection()
        if fail_after_ledger_before_evidence:
            raise RuntimeError("injected_ledger_before_evidence_crash")
        envelope = self._recover_phase_outcome(
            event_id=event_id,
            phase=phase,
            frame_digest=frame_digest,
            event_time=completed_bar,
        )
        if envelope is None:
            raise OkxDemoPaperRuntimeError("offline_replay_phase_outcome_missing")
        return self._result(
            event_id=event_id,
            phase=phase,
            envelope=envelope,
        )

    def _result(
        self,
        *,
        event_id: str,
        phase: str,
        envelope: Mapping[str, Any],
    ) -> dict[str, Any]:
        recovery = self.controller._runtime_store.recover()
        scoped = self._event_slice(
            recovery.events, event_id=event_id, phase=phase
        )
        lifecycle_rows = [
            event for event in scoped if event.get("event_type") == "order_lifecycle"
        ]
        no_order_rows = [
            event for event in scoped if event.get("event_type") == "signal_no_order"
        ]
        links = dict(envelope.get("links", {}))
        if lifecycle_rows:
            client_id = str(links.get("client_order_id") or "")
            exact_lifecycle = [
                event
                for event in lifecycle_rows
                if self._lifecycle_client_id(event) == client_id
            ]
            if len(exact_lifecycle) != 1:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_result_lifecycle_not_exact"
                )
            audit = dict(exact_lifecycle[0]["payload"])
        elif no_order_rows:
            if len(no_order_rows) != 1:
                raise OkxDemoPaperRuntimeError(
                    "offline_replay_result_no_order_not_exact"
                )
            signal = dict(no_order_rows[0]["payload"].get("signal", {}))
            audit = {
                "signal": signal,
                "decision_outcome": "no_order",
                "current_contracts": no_order_rows[0]["payload"].get(
                    "current_contracts"
                ),
                "fills": [],
            }
        else:
            raise OkxDemoPaperRuntimeError("offline_replay_result_trace_missing")

        ledger_event_hash = str(links.get("ledger_event_hash") or "")
        ledger_rows = [
            event
            for event in recovery.events
            if event.get("event_type") == "ledger_uow_committed"
        ]
        ledger = next(
            (
                event
                for event in ledger_rows
                if ledger_event_hash and event.get("event_hash") == ledger_event_hash
            ),
            {},
        )
        if links.get("decision_outcome") == "order_terminal" and not ledger:
            raise OkxDemoPaperRuntimeError("offline_replay_result_ledger_not_exact")
        evidence_rows = [
            event
            for event in recovery.events
            if event.get("event_type") == "strategy_decision_evidence"
        ]
        policy_evidence = dict(
            self.controller._state.get("signal", {}).get(
                "market_entry_policy", {}
            )
        )
        return {
            **audit,
            "event_id": event_id,
            "phase": phase,
            "evidence": dict(envelope),
            "ledger": dict(ledger),
            "position_contracts": self.venue.state["position"],
            "equity_usdt": self.venue.state["equity"],
            "submit_count": int(self.venue.state["submit_count"]),
            "fill_count": len(self.venue.state["fills"]),
            "cancel_algo_count": int(self.venue.state["cancel_algo_count"]),
            "ledger_uow_count": len(ledger_rows),
            "decision_evidence_count": len(evidence_rows),
            "market_entry_policy": policy_evidence or None,
            "safety": {
                "demo_enabled": False,
                "paper_enabled": False,
                "live_enabled": False,
                "runtime_observed": False,
                "network_accessed": False,
            },
        }


__all__ = [
    "DonchianOfflineReplay",
    "DonchianOfflineReplayConfig",
    "build_closeout_scenario",
    "build_trend_frame",
]
