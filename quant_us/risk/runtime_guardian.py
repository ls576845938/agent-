"""Independent runtime/post-trade/account-level risk guardian.

The guardian deliberately consumes a small, read-only observation projection
instead of importing Strategy, Portfolio, OMS, broker adapters, or a runtime
supervisor.  An integration owner can adapt the canonical broker/runtime
models to :class:`RiskGuardianObservationProtocol` without making this module
the owner of those models.

This module is an observation and decision boundary only:

* no broker, private, order, or network calls are made;
* a failed or incomplete observation blocks new orders (fail closed);
* ``enforce`` may call a supplied kill-switch ``trip`` method, never an
  untrip/reset method;
* recovery and any clearing of a kill switch remain the responsibility of the
  runtime supervisor/operator workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
from math import isfinite
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable
from types import MappingProxyType
from uuid import uuid4

from quant_us.core.clock import ensure_utc, utc_now


SCHEMA_VERSION = "us_equity_runtime_risk_guardian_v1"


class GuardianStatus(str, Enum):
    """Outcome class for one deterministic guardian evaluation."""

    PASS = "pass"
    BLOCKED = "blocked"
    TRIPPED = "tripped"


class GuardianSeverity(str, Enum):
    """Severity used for the decision and each violation."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@runtime_checkable
class RiskGuardianObservationProtocol(Protocol):
    """Read-only projection required from an upstream runtime/broker source.

    The protocol is intentionally structural.  Agent 1/2 integrations can
    expose their canonical RuntimeSnapshot/BrokerTruthSnapshot without this
    module copying or owning either canonical model.
    """

    observed_at: datetime
    equity: float | None
    cash: float | None
    daily_pnl: float | None
    drawdown: float | None
    gross_exposure: float | None
    net_exposure: float | None
    positions: Mapping[str, Any]
    open_orders: Any
    unknown_orders: Any
    market_data_fresh: bool | None
    market_data_age_seconds: float | None
    broker_truth_fresh: bool | None
    broker_truth_age_seconds: float | None
    reconciliation_status: str | None
    heartbeat_age_seconds: float | None
    heartbeat_ok: bool | None
    account_verified: bool | None
    position_mismatch: bool | None
    cash_mismatch: bool | None
    runtime_state: str | None
    session_id: str


# Short alias for consumers that prefer the generic protocol name.
RiskObservationProtocol = RiskGuardianObservationProtocol


@runtime_checkable
class RiskGuardianAuditSink(Protocol):
    """Minimal append-only audit interface accepted by the guardian."""

    def record(
        self,
        event_type: str,
        details: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> Any:
        ...


@dataclass(frozen=True)
class RiskGuardianConfig:
    """Immutable per-session guardian limits.

    Absolute limits use the units supplied by the observation (normally the
    account currency for exposure/loss and account units for position size).
    Optional ``*_pct`` limits express a fraction of ``equity`` and can be used
    when an integration wants percentage-based exposure limits.  A limit set
    to ``None`` is intentionally disabled; this keeps policy in configuration
    rather than scattering constants through the evaluator.
    """

    max_gross_exposure: float | None = None
    max_net_exposure: float | None = None
    max_position_size: float | None = None
    max_daily_loss: float | None = None
    max_drawdown: float | None = None
    max_gross_exposure_pct: float | None = None
    max_net_exposure_pct: float | None = None
    max_position_size_pct: float | None = None
    max_market_data_staleness_seconds: float = 300.0
    max_broker_truth_staleness_seconds: float = 300.0
    max_heartbeat_age_seconds: float = 60.0
    require_observation_health: bool = True
    require_account_verification: bool = True
    require_cash: bool = True
    require_equity: bool = True
    require_exposure: bool = True
    config_version: str = "risk_guardian_v1"
    session_id: str = "unbound-session"
    tolerance: float = 1e-9

    def __post_init__(self) -> None:
        for name in (
            "max_gross_exposure",
            "max_net_exposure",
            "max_position_size",
            "max_daily_loss",
            "max_drawdown",
            "max_gross_exposure_pct",
            "max_net_exposure_pct",
            "max_position_size_pct",
            "max_market_data_staleness_seconds",
            "max_broker_truth_staleness_seconds",
            "max_heartbeat_age_seconds",
            "tolerance",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            numeric = float(value)
            if not isfinite(numeric) or numeric < 0:
                raise ValueError(f"{name}_must_be_finite_non_negative")
            object.__setattr__(self, name, numeric)
        if not str(self.config_version).strip():
            raise ValueError("config_version_required")
        if not str(self.session_id).strip():
            raise ValueError("session_id_required")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "RiskGuardianConfig":
        """Build a validated immutable config from a YAML/JSON-like mapping."""

        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in allowed})

    from_dict = from_mapping

    @property
    def config_hash(self) -> str:
        """Stable, non-secret fingerprint for audit correlation."""

        payload = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
            if key not in {"config_hash"}
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskGuardianObservation:
    """Immutable, adapter-friendly observation envelope.

    This is not a replacement for the canonical broker truth/runtime models.
    It only carries the read-only fields the guardian needs and is useful for
    fakes, tests, and a narrow integration adapter.
    """

    observed_at: datetime = field(default_factory=utc_now)
    equity: float | None = None
    cash: float | None = None
    daily_pnl: float | None = None
    drawdown: float | None = None
    gross_exposure: float | None = None
    net_exposure: float | None = None
    positions: Mapping[str, Any] = field(default_factory=dict)
    open_orders: Any = 0
    unknown_orders: Any = 0
    market_data_fresh: bool | None = None
    market_data_age_seconds: float | None = None
    broker_truth_fresh: bool | None = None
    broker_truth_age_seconds: float | None = None
    reconciliation_status: str | None = None
    heartbeat_age_seconds: float | None = None
    heartbeat_ok: bool | None = None
    account_verified: bool | None = None
    position_mismatch: bool | None = False
    cash_mismatch: bool | None = False
    runtime_state: str | None = None
    session_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", ensure_utc(_coerce_datetime(self.observed_at)))
        # Freeze the top-level mapping boundary.  Nested broker objects remain
        # read-only from this module's perspective and are never mutated.
        object.__setattr__(self, "positions", MappingProxyType(_normalise_positions(self.positions)))

    @classmethod
    def from_source(
        cls,
        source: RiskGuardianObservationProtocol | Mapping[str, Any] | Any,
        *,
        observed_at: datetime | None = None,
    ) -> "RiskGuardianObservation":
        """Adapt a structural source without importing its canonical model."""

        if isinstance(source, cls):
            return source

        def read(*names: str, default: Any = None) -> Any:
            if isinstance(source, Mapping):
                for name in names:
                    if name in source:
                        return source[name]
                return default
            for name in names:
                if hasattr(source, name):
                    return getattr(source, name)
            return default

        broker_truth = read("broker_truth", "broker_truth_snapshot", default=None)
        market_data = read("market_data", "market_data_status", default=None)
        heartbeat = read("heartbeat", "runtime_heartbeat", default=None)
        reconciliation = read("reconciliation", "reconciliation_report", default=None)

        def nested(obj: Any, *names: str, default: Any = None) -> Any:
            if obj is None:
                return default
            if isinstance(obj, Mapping):
                for name in names:
                    if name in obj:
                        return obj[name]
                return default
            for name in names:
                if hasattr(obj, name):
                    return getattr(obj, name)
            return default

        positions = read("positions", default=None)
        if positions is None:
            positions = nested(broker_truth, "positions", default={})
        gross = read("gross_exposure", "gross_notional", default=None)
        net = read("net_exposure", "net_notional", default=None)
        if gross is None:
            gross = nested(broker_truth, "gross_exposure", "gross_notional", default=None)
        if net is None:
            net = nested(broker_truth, "net_exposure", "net_notional", default=None)

        observed = read("observed_at", "captured_at", "timestamp", default=None)
        observed = observed_at or observed or nested(broker_truth, "captured_at", "captured_at_utc", default=None)
        if observed is None:
            observed = utc_now()

        reconciliation_status = read("reconciliation_status", default=None)
        if reconciliation_status is None:
            reconciliation_status = nested(reconciliation, "status", "reconciliation_status", default=None)

        market_fresh = read("market_data_fresh", default=None)
        if market_fresh is None:
            market_fresh = nested(market_data, "fresh", "healthy", default=None)
        if market_fresh is None:
            market_fresh = _health_flag(nested(market_data, "status", "freshness", default=None))
        else:
            market_fresh = _health_flag(market_fresh)
        market_age = read("market_data_age_seconds", "market_data_stale_seconds", default=None)
        if market_age is None:
            market_age = nested(market_data, "age_seconds", "stale_seconds", default=None)

        broker_fresh = read("broker_truth_fresh", default=None)
        if broker_fresh is None:
            broker_fresh = nested(broker_truth, "fresh", "freshness", default=None)
        broker_fresh = _health_flag(broker_fresh)
        broker_age = read("broker_truth_age_seconds", "broker_snapshot_age_seconds", default=None)
        if broker_age is None:
            broker_age = nested(broker_truth, "age_seconds", "snapshot_age_seconds", default=None)

        heartbeat_ok = read("heartbeat_ok", "heartbeat", default=None)
        if heartbeat_ok is None:
            heartbeat_ok = nested(heartbeat, "ok", "healthy", default=None)
        heartbeat_ok = _health_flag(heartbeat_ok)
        heartbeat_age = read("heartbeat_age_seconds", "heartbeat_stale_seconds", default=None)
        if heartbeat_age is None:
            heartbeat_age = nested(heartbeat, "age_seconds", "stale_seconds", default=None)

        return cls(
            observed_at=observed,
            equity=read("equity", "net_liquidation", default=nested(broker_truth, "equity", "net_liquidation", default=None)),
            cash=read("cash", default=nested(broker_truth, "cash", default=None)),
            daily_pnl=read("daily_pnl", "pnl", default=None),
            drawdown=read("drawdown", "drawdown_pct", default=None),
            gross_exposure=gross,
            net_exposure=net,
            positions=positions or {},
            open_orders=read("open_orders", "open_order_count", default=nested(broker_truth, "open_orders", default=0)),
            unknown_orders=read(
                "unknown_orders",
                "unknown_broker_orders",
                default=nested(broker_truth, "unknown_orders", "unknown_broker_orders", default=0),
            ),
            market_data_fresh=market_fresh,
            market_data_age_seconds=market_age,
            broker_truth_fresh=broker_fresh,
            broker_truth_age_seconds=broker_age,
            reconciliation_status=reconciliation_status,
            heartbeat_age_seconds=heartbeat_age,
            heartbeat_ok=heartbeat_ok,
            account_verified=read("account_verified", default=nested(broker_truth, "account_verified", default=None)),
            position_mismatch=read(
                "position_mismatch",
                "positions_mismatch",
                default=nested(
                    reconciliation,
                    "position_mismatch",
                    "positions_mismatch",
                    "position_mismatch_count",
                    default=False,
                ),
            ),
            cash_mismatch=read(
                "cash_mismatch",
                default=nested(reconciliation, "cash_mismatch", "cash_mismatch_amount", default=False),
            ),
            runtime_state=read("runtime_state", "state", default=None),
            session_id=str(read("session_id", default="") or ""),
        )


# Explicit name for callers that prefer a runtime-oriented envelope.
RuntimeRiskObservation = RiskGuardianObservation
GuardianObservation = RiskGuardianObservation


@dataclass(frozen=True)
class RiskGuardianViolation:
    """One explainable guardian rule breach."""

    rule: str
    observed_value: Any
    limit: Any
    severity: GuardianSeverity = GuardianSeverity.CRITICAL
    message: str = ""
    recommended_action: str = "block_new_orders"

    @property
    def rule_name(self) -> str:
        return self.rule

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "rule_name": self.rule,
            "observed_value": _json_value(self.observed_value),
            "limit": _json_value(self.limit),
            "severity": self.severity.value,
            "message": self.message,
            "recommended_action": self.recommended_action,
        }


RiskViolation = RiskGuardianViolation
GuardianViolation = RiskGuardianViolation


@dataclass(frozen=True)
class RiskGuardianDecision:
    """Immutable, auditable guardian output."""

    status: GuardianStatus
    observed_at: datetime
    violations: tuple[RiskGuardianViolation, ...]
    severity: GuardianSeverity
    recommended_trading_mode: str
    trip_kill_switch: bool
    block_new_orders: bool
    config_version: str
    session_id: str
    config_hash: str
    decision_id: str = field(default_factory=lambda: f"rgd_{uuid4().hex[:16]}")
    schema_version: str = SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return self.status == GuardianStatus.PASS and not self.block_new_orders

    @property
    def primary_reason(self) -> str:
        return self.violations[0].rule if self.violations else "guardian_pass"

    @property
    def reason(self) -> str:
        return self.primary_reason

    @property
    def fail_closed(self) -> bool:
        return self.block_new_orders

    @property
    def kill_switch_tripped(self) -> bool:
        return self.trip_kill_switch

    @property
    def safety_flags(self) -> dict[str, bool]:
        """Explicitly keep all external execution permissions disabled."""

        return {
            "broker_called": False,
            "network_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "order_submitted": False,
            "paper_order_allowed": False,
            "live_order_allowed": False,
            "broker_access_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "secret_read": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "status": self.status.value,
            "observed_at": self.observed_at.isoformat(),
            "violations": [item.to_dict() for item in self.violations],
            "severity": self.severity.value,
            "recommended_trading_mode": self.recommended_trading_mode,
            "trip_kill_switch": self.trip_kill_switch,
            "block_new_orders": self.block_new_orders,
            "config_version": self.config_version,
            "config_hash": self.config_hash,
            "session_id": self.session_id,
        }


class RiskGuardian:
    """Deterministic, side-effect-free evaluator for runtime account risk."""

    _PASS_RECONCILIATION = frozenset({"pass", "passed", "clean", "reconciled", "ok", "success"})
    _BAD_RUNTIME_STATES = frozenset(
        {"unknown", "offline", "connecting", "authenticating", "broker_syncing", "reconciling", "degraded", "reconnecting", "recovery_pending", "halted"}
    )

    def __init__(
        self,
        config: RiskGuardianConfig | None = None,
        *,
        audit_sink: RiskGuardianAuditSink | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.config = config or RiskGuardianConfig()
        self.audit_sink = audit_sink
        self._clock = clock
        self._last_decision: RiskGuardianDecision | None = None

    @property
    def last_decision(self) -> RiskGuardianDecision | None:
        return self._last_decision

    def evaluate(
        self,
        observation: RiskGuardianObservationProtocol | Mapping[str, Any] | Any,
        *,
        observed_at: datetime | None = None,
    ) -> RiskGuardianDecision:
        """Evaluate a read-only snapshot and return a fail-closed decision."""

        try:
            item = RiskGuardianObservation.from_source(observation, observed_at=observed_at)
            violations = self._evaluate(item)
        except (TypeError, ValueError, OverflowError):
            # Malformed or non-finite upstream state must never become an
            # implicit pass.  Do not include the raw malformed value in audit.
            item = RiskGuardianObservation(observed_at=observed_at or self._clock())
            violations = [
                RiskGuardianViolation(
                    "INVALID_OBSERVATION",
                    "unavailable",
                    "valid_read_only_observation",
                    message="guardian observation could not be normalised",
                )
            ]

        decision = self._decision(item, violations)
        self._last_decision = decision
        self._audit(decision)
        return decision

    # Discoverable aliases keep integration adapters simple and do not add a
    # second implementation of the rules.
    check = evaluate
    assess = evaluate

    def enforce(
        self,
        observation: RiskGuardianObservationProtocol | Mapping[str, Any] | Any,
        kill_switch: Any | None = None,
        *,
        observed_at: datetime | None = None,
    ) -> RiskGuardianDecision:
        """Evaluate and optionally trip a supplied kill switch.

        The only permitted mutation is a one-way ``trip(reason)`` call.  The
        guardian deliberately has no ``untrip``/``reset`` API and does not
        inspect or clear a switch that was already tripped.
        """

        decision = self.evaluate(observation, observed_at=observed_at)
        if decision.trip_kill_switch and kill_switch is not None:
            trip = getattr(kill_switch, "trip", None)
            if not callable(trip):
                raise TypeError("kill_switch_must_expose_trip_only")
            trip(decision.primary_reason)
        return decision

    evaluate_and_trip = enforce

    def _evaluate(self, observation: RiskGuardianObservation) -> list[RiskGuardianViolation]:
        violations: list[RiskGuardianViolation] = []
        cfg = self.config

        # Required broker/account health is deliberately checked before limits.
        if cfg.require_equity and observation.equity is None:
            violations.append(self._missing("equity"))
        if cfg.require_cash and observation.cash is None:
            violations.append(self._missing("cash"))
        if cfg.require_exposure and (
            observation.gross_exposure is None or observation.net_exposure is None
        ):
            violations.append(self._missing("exposure"))
        if cfg.max_daily_loss is not None and observation.daily_pnl is None:
            violations.append(self._missing("daily_pnl"))
        if cfg.max_drawdown is not None and observation.drawdown is None:
            violations.append(self._missing("drawdown"))
        if cfg.require_account_verification and observation.account_verified is not True:
            violations.append(
                RiskGuardianViolation(
                    "ACCOUNT_UNVERIFIED",
                    observation.account_verified,
                    True,
                    message="broker account verification is not confirmed",
                )
            )

        if cfg.require_observation_health:
            if observation.market_data_fresh is None and observation.market_data_age_seconds is None:
                violations.append(self._missing("market_data_freshness"))
            if observation.broker_truth_fresh is None and observation.broker_truth_age_seconds is None:
                violations.append(self._missing("broker_truth_freshness"))
            if observation.reconciliation_status is None:
                violations.append(self._missing("reconciliation_status"))
            if observation.heartbeat_ok is None and observation.heartbeat_age_seconds is None:
                violations.append(self._missing("runtime_heartbeat"))

        self._check_numeric_observation(observation, violations)

        if cfg.max_gross_exposure is not None and observation.gross_exposure is not None:
            self._limit(
                violations,
                "MAX_GROSS_EXPOSURE",
                abs(float(observation.gross_exposure)),
                cfg.max_gross_exposure,
            )
        if cfg.max_net_exposure is not None and observation.net_exposure is not None:
            self._limit(
                violations,
                "MAX_NET_EXPOSURE",
                abs(float(observation.net_exposure)),
                cfg.max_net_exposure,
            )
        if observation.equity is not None and float(observation.equity) > 0:
            if cfg.max_gross_exposure_pct is not None and observation.gross_exposure is not None:
                self._limit(
                    violations,
                    "MAX_GROSS_EXPOSURE",
                    abs(float(observation.gross_exposure)) / float(observation.equity),
                    cfg.max_gross_exposure_pct,
                )
            if cfg.max_net_exposure_pct is not None and observation.net_exposure is not None:
                self._limit(
                    violations,
                    "MAX_NET_EXPOSURE",
                    abs(float(observation.net_exposure)) / float(observation.equity),
                    cfg.max_net_exposure_pct,
                )

        max_position = self._max_position_size(observation.positions)
        if cfg.max_position_size is not None and max_position is not None:
            self._limit(violations, "MAX_POSITION_SIZE", max_position, cfg.max_position_size)
        if cfg.max_position_size_pct is not None and max_position is not None and observation.equity:
            self._limit(
                violations,
                "MAX_POSITION_SIZE",
                max_position / abs(float(observation.equity)),
                cfg.max_position_size_pct,
            )

        if cfg.max_daily_loss is not None and observation.daily_pnl is not None:
            daily_loss = max(0.0, -float(observation.daily_pnl))
            self._limit(violations, "MAX_DAILY_LOSS", daily_loss, cfg.max_daily_loss)
        if cfg.max_drawdown is not None and observation.drawdown is not None:
            self._limit(violations, "MAX_DRAWDOWN", abs(float(observation.drawdown)), cfg.max_drawdown)

        if _count(observation.unknown_orders) > 0:
            violations.append(
                RiskGuardianViolation(
                    "UNKNOWN_BROKER_ORDER",
                    _count(observation.unknown_orders),
                    0,
                    message="broker truth contains an order not known by the local runtime",
                )
            )
        if _truthy(observation.position_mismatch):
            violations.append(
                RiskGuardianViolation(
                    "POSITION_MISMATCH",
                    True,
                    False,
                    message="broker position does not reconcile with local truth",
                )
            )
        if _truthy(observation.cash_mismatch):
            violations.append(
                RiskGuardianViolation(
                    "CASH_MISMATCH",
                    True,
                    False,
                    message="broker cash does not reconcile with local truth",
                )
            )

        self._freshness(
            violations,
            rule="MARKET_DATA_STALE",
            fresh=observation.market_data_fresh,
            age=observation.market_data_age_seconds,
            threshold=cfg.max_market_data_staleness_seconds,
        )
        self._freshness(
            violations,
            rule="BROKER_TRUTH_STALE",
            fresh=observation.broker_truth_fresh,
            age=observation.broker_truth_age_seconds,
            threshold=cfg.max_broker_truth_staleness_seconds,
        )

        if observation.reconciliation_status is not None:
            status = str(observation.reconciliation_status).strip().lower().replace("-", "_")
            if status not in self._PASS_RECONCILIATION:
                violations.append(
                    RiskGuardianViolation(
                        "RECONCILIATION_FAILED",
                        status or "unknown",
                        sorted(self._PASS_RECONCILIATION),
                        message="reconciliation did not produce a clean/pass result",
                    )
                )

        if observation.heartbeat_ok is False:
            violations.append(
                RiskGuardianViolation(
                    "HEARTBEAT_STALE",
                    False,
                    True,
                    message="runtime heartbeat is not healthy",
                )
            )
        if observation.heartbeat_age_seconds is not None:
            age = _finite_float(observation.heartbeat_age_seconds)
            if age > cfg.max_heartbeat_age_seconds:
                violations.append(
                    RiskGuardianViolation(
                        "HEARTBEAT_STALE",
                        age,
                        cfg.max_heartbeat_age_seconds,
                        message="runtime heartbeat age exceeds configured limit",
                    )
                )

        if observation.runtime_state is not None:
            runtime_state = str(observation.runtime_state).strip().lower().replace("-", "_")
            if runtime_state in self._BAD_RUNTIME_STATES:
                violations.append(
                    RiskGuardianViolation(
                        "RUNTIME_STATE_UNKNOWN",
                        runtime_state,
                        "ready",
                        message="runtime is not in a known ready state",
                    )
                )

        return _deduplicate_violations(violations)

    def _decision(
        self,
        observation: RiskGuardianObservation,
        violations: Sequence[RiskGuardianViolation],
    ) -> RiskGuardianDecision:
        if not violations:
            return RiskGuardianDecision(
                status=GuardianStatus.PASS,
                observed_at=observation.observed_at,
                violations=(),
                severity=GuardianSeverity.INFO,
                recommended_trading_mode="normal",
                trip_kill_switch=False,
                block_new_orders=False,
                config_version=self.config.config_version,
                session_id=observation.session_id or self.config.session_id,
                config_hash=self.config.config_hash,
            )

        critical = any(item.severity == GuardianSeverity.CRITICAL for item in violations)
        severity = GuardianSeverity.CRITICAL if critical else GuardianSeverity.WARNING
        return RiskGuardianDecision(
            status=GuardianStatus.TRIPPED if critical else GuardianStatus.BLOCKED,
            observed_at=observation.observed_at,
            violations=tuple(violations),
            severity=severity,
            recommended_trading_mode="frozen",
            trip_kill_switch=critical,
            block_new_orders=True,
            config_version=self.config.config_version,
            session_id=observation.session_id or self.config.session_id,
            config_hash=self.config.config_hash,
        )

    def _audit(self, decision: RiskGuardianDecision) -> None:
        if self.audit_sink is None:
            return
        self.audit_sink.record(
            "risk_guardian_decision",
            {
                "schema_version": decision.schema_version,
                "decision_id": decision.decision_id,
                "status": decision.status.value,
                "severity": decision.severity.value,
                "trip_kill_switch": decision.trip_kill_switch,
                "block_new_orders": decision.block_new_orders,
                "recommended_trading_mode": decision.recommended_trading_mode,
                "config_version": decision.config_version,
                "config_hash": decision.config_hash,
                "session_id": decision.session_id,
                "violations": [item.to_dict() for item in decision.violations],
            },
            timestamp=decision.observed_at,
        )

    @staticmethod
    def _missing(name: str) -> RiskGuardianViolation:
        return RiskGuardianViolation(
            "OBSERVATION_INCOMPLETE",
            name,
            "available",
            message=f"required observation field missing: {name}",
        )

    def _check_numeric_observation(
        self,
        observation: RiskGuardianObservation,
        violations: list[RiskGuardianViolation],
    ) -> None:
        names = (
            "equity",
            "cash",
            "daily_pnl",
            "drawdown",
            "gross_exposure",
            "net_exposure",
            "market_data_age_seconds",
            "broker_truth_age_seconds",
            "heartbeat_age_seconds",
        )
        for name in names:
            value = getattr(observation, name)
            if value is None:
                continue
            try:
                _finite_float(value)
            except (TypeError, ValueError, OverflowError):
                violations.append(
                    RiskGuardianViolation(
                        "INVALID_OBSERVATION",
                        name,
                        "finite_numeric",
                        message=f"observation field is not finite numeric: {name}",
                    )
                )

    def _max_position_size(self, positions: Mapping[str, Any]) -> float | None:
        if positions is None:
            return None
        values: list[float] = []
        for value in positions.values():
            try:
                values.append(abs(_position_size(value)))
            except (TypeError, ValueError, AttributeError, OverflowError):
                # Invalid position truth is itself handled as a fail-closed
                # observation rather than being silently ignored.
                return float("nan")
        return max(values, default=0.0)

    def _limit(
        self,
        violations: list[RiskGuardianViolation],
        rule: str,
        observed: float,
        limit: float,
    ) -> None:
        if not isfinite(observed) or observed > limit + self.config.tolerance:
            violations.append(
                RiskGuardianViolation(
                    rule,
                    observed,
                    limit,
                    message=f"{rule.lower()} exceeded",
                )
            )

    @staticmethod
    def _freshness(
        violations: list[RiskGuardianViolation],
        *,
        rule: str,
        fresh: bool | None,
        age: float | None,
        threshold: float,
    ) -> None:
        if fresh is False:
            violations.append(RiskGuardianViolation(rule, False, True, message=f"{rule.lower()} flag is false"))
        if age is not None:
            numeric_age = _finite_float(age)
            if numeric_age > threshold:
                violations.append(
                    RiskGuardianViolation(
                        rule,
                        numeric_age,
                        threshold,
                        message=f"{rule.lower()} age exceeds configured limit",
                    )
                )


def _position_size(value: Any) -> float:
    """Extract a notional/size from a generic broker position projection."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _finite_float(value)
    if isinstance(value, Mapping):
        for name in ("market_value", "notional", "market_notional", "quantity"):
            if name in value and value[name] is not None:
                return abs(_finite_float(value[name]))
        quantity = value.get("quantity")
        market_price = value.get("market_price", value.get("price"))
        if quantity is not None and market_price is not None:
            return abs(_finite_float(quantity) * _finite_float(market_price))
        raise ValueError("position_size_missing")
    for name in ("market_value", "notional", "market_notional", "quantity"):
        if hasattr(value, name):
            candidate = getattr(value, name)
            if candidate is not None:
                return abs(_finite_float(candidate))
    quantity = getattr(value, "quantity", None)
    market_price = getattr(value, "market_price", getattr(value, "price", None))
    if quantity is not None and market_price is not None:
        return abs(_finite_float(quantity) * _finite_float(market_price))
    raise ValueError("position_size_missing")


def _normalise_positions(value: Any) -> dict[str, Any]:
    """Keep position projections keyed by a stable, non-secret symbol."""

    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key).upper(): item for key, item in value.items()}
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError("positions_must_be_mapping_or_sequence")
    try:
        items = list(value)
    except TypeError as exc:
        raise TypeError("positions_must_be_mapping_or_sequence") from exc
    result: dict[str, Any] = {}
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            symbol = item.get("symbol", item.get("ticker", index))
        else:
            symbol = getattr(item, "symbol", getattr(item, "ticker", index))
        result[str(symbol).upper()] = item
    return result


def _health_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower().replace("-", "_")
        if normalised in {"fresh", "healthy", "pass", "passed", "ok", "true", "ready"}:
            return True
        if normalised in {"stale", "unhealthy", "fail", "failed", "false", "unknown", "blocked"}:
            return False
    return bool(value)


def _finite_float(value: Any) -> float:
    result = float(value)
    if not isfinite(result):
        raise ValueError("non_finite_numeric")
    return result


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("observed_at_must_be_datetime")


def _count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        number = _finite_float(value)
        if number < 0 or int(number) != number:
            raise ValueError("invalid_count")
        return int(number)
    if isinstance(value, (str, bytes, bytearray)):
        return 1 if value else 0
    try:
        return len(value)
    except TypeError:
        return 1


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "failed", "mismatch"}
    return bool(value)


def _deduplicate_violations(items: Sequence[RiskGuardianViolation]) -> list[RiskGuardianViolation]:
    seen: set[tuple[str, str]] = set()
    result: list[RiskGuardianViolation] = []
    for item in items:
        key = (item.rule, str(item.observed_value))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


__all__ = [
    "SCHEMA_VERSION",
    "GuardianStatus",
    "GuardianSeverity",
    "RiskGuardianConfig",
    "RiskGuardianObservationProtocol",
    "RiskObservationProtocol",
    "RiskGuardianAuditSink",
    "RiskGuardianObservation",
    "RuntimeRiskObservation",
    "GuardianObservation",
    "RiskGuardianViolation",
    "RiskViolation",
    "GuardianViolation",
    "RiskGuardianDecision",
    "RiskGuardian",
    "RuntimeRiskGuardian",
    "IndependentRiskGuardian",
]


RuntimeRiskGuardian = RiskGuardian
IndependentRiskGuardian = RiskGuardian
