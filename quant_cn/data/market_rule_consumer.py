"""Read-only, fail-closed consumer for immutable CN market-rule bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from quant_cn.data.contracts import ensure_aware_timestamp, ensure_sha256_checksum
from quant_cn.market.calendar import InjectedCalendar, SessionPhase, TradingSession
from quant_cn.market.rules import (
    BOARD_LOT,
    FEE_SCHEDULE,
    PRICE_LIMIT,
    SELLABILITY,
    SETTLEMENT,
    BoardLotPolicy,
    EffectiveRule,
    EffectiveRuleBook,
    FeeComponent,
    FeePolicy,
    MarketDimensions,
    PriceLimitPolicy,
    SellabilityPolicy,
    SettlementPolicy,
)
from tools.agent_governance.shared_data import SharedDataError, resolve_manifest_file


BUNDLE_FILE = "market_rule_bundle.json"
BUNDLE_SCHEMA = "cn_market_rule_bundle_v1"
DATASET_ID = "cn-equity-market-rule-bundle"

SESSION = "session"
REQUIRED_RULE_KINDS = (
    BOARD_LOT,
    PRICE_LIMIT,
    SELLABILITY,
    FEE_SCHEDULE,
    SESSION,
    SETTLEMENT,
)
DOMAIN_RULE_KINDS = (
    BOARD_LOT,
    PRICE_LIMIT,
    SELLABILITY,
    FEE_SCHEDULE,
    SETTLEMENT,
)
MISSING_RULE_BLOCKERS = {
    BOARD_LOT: "board_lot_rule_missing",
    PRICE_LIMIT: "price_limit_rule_missing",
    SELLABILITY: "sellability_rule_missing",
    FEE_SCHEDULE: "fee_schedule_rule_missing",
    SESSION: "session_rule_missing",
    SETTLEMENT: "settlement_rule_missing",
}

CN_MARKET_RULE_HANDOFF_MISSING = "cn_market_rule_handoff_missing"
CN_MARKET_RULE_HANDOFF_INVALID = "cn_market_rule_handoff_invalid"
CN_MARKET_RULE_MANIFEST_MISSING = "cn_market_rule_manifest_missing"
CN_MARKET_RULE_MANIFEST_RESOLVE_FAILED = "cn_market_rule_manifest_resolve_failed"
CN_MARKET_RULE_MANIFEST_CONTRACT_INVALID = (
    "cn_market_rule_manifest_contract_invalid"
)
CN_MARKET_RULE_MANIFEST_BLOCKED = "cn_market_rule_manifest_blocked"
CN_MARKET_RULE_FILE_MISSING = "cn_market_rule_file_missing"
CN_MARKET_RULE_FILE_EMPTY = "cn_market_rule_file_empty"
CN_MARKET_RULE_WEB_TEXT_FORBIDDEN = "cn_market_rule_web_text_forbidden"
CN_MARKET_RULE_BUNDLE_INVALID = "cn_market_rule_bundle_invalid"
CN_MARKET_RULE_BUNDLE_SCHEMA_MISMATCH = "cn_market_rule_bundle_schema_mismatch"
CN_MARKET_RULE_IDENTITY_MISMATCH = "cn_market_rule_identity_mismatch"
CN_MARKET_RULE_PIT_BRIDGE_INCOMPLETE = "cn_market_rule_pit_bridge_incomplete"
CN_MARKET_RULE_RECORD_INVALID = "cn_market_rule_record_invalid"
CN_MARKET_RULE_SOURCE_NOT_FORMAL = "cn_market_rule_source_not_formal"
CN_MARKET_RULE_DIMENSION_INCOMPLETE = "cn_market_rule_dimension_incomplete"
CN_MARKET_RULE_FEE_TAX_SCOPE_INCOMPLETE = (
    "cn_market_rule_fee_tax_scope_incomplete"
)

FORMAL_SOURCE_TYPES = frozenset(
    {
        "exchange_rulebook",
        "statutory_rule",
        "clearing_rulebook",
        "broker_fee_schedule",
    }
)
TRADING_SAFETY_FLAGS = (
    "broker",
    "live",
    "oms",
    "order",
    "paper",
    "private",
    "promotion",
    "real_order",
)


@dataclass(frozen=True, order=True)
class MarketRuleBlocker:
    code: str
    detail: str = ""
    owner: str = "data_steward"
    next_action: str = "publish_current_main_cn_market_rule_bundle"

    def __post_init__(self) -> None:
        for name in ("code", "owner", "next_action"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"non_empty_string_required:{name}")


@dataclass(frozen=True)
class RuleEvidenceBinding:
    rule_kind: str
    version: str
    source: str
    source_type: str
    source_document_id: str
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    dimensions: MarketDimensions
    checksum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "available_time": self.available_time.isoformat(),
            "checksum": self.checksum,
            "dimensions": {
                "board": self.dimensions.board,
                "instrument": self.dimensions.instrument,
                "security_id": self.dimensions.security_id,
                "security_type": self.dimensions.security_type,
                "venue": self.dimensions.venue,
            },
            "effective_from": self.effective_from.isoformat(),
            "effective_to": (
                self.effective_to.isoformat()
                if self.effective_to is not None
                else None
            ),
            "rule_kind": self.rule_kind,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "source_type": self.source_type,
            "version": self.version,
        }


@dataclass(frozen=True)
class MarketRuleConsumption:
    status: str
    decision: str
    dataset_id: str = ""
    dataset_version: str = ""
    manifest_sha256: str = ""
    bundle_sha256: str = ""
    handoff_event_id: str = ""
    manifest_source: str = ""
    resolved_path: str = ""
    blockers: tuple[MarketRuleBlocker, ...] = ()
    bindings: tuple[RuleEvidenceBinding, ...] = ()
    rulebook: EffectiveRuleBook = field(
        default_factory=lambda: EffectiveRuleBook(())
    )
    calendar: InjectedCalendar = field(default_factory=lambda: InjectedCalendar(()))
    consumer_read_only: bool = True

    def __post_init__(self) -> None:
        blockers = _dedupe_blockers(self.blockers)
        bindings = tuple(
            sorted(
                self.bindings,
                key=lambda item: (
                    item.rule_kind,
                    item.dimensions.venue,
                    item.dimensions.board,
                    item.dimensions.instrument,
                    item.dimensions.security_type,
                    item.dimensions.security_id or "",
                    item.effective_from,
                    item.version,
                ),
            )
        )
        if self.consumer_read_only is not True:
            raise ValueError("cn_market_rule_consumer_must_be_read_only")
        if self.status not in {"blocked", "pass"}:
            raise ValueError("cn_market_rule_status_invalid")
        if self.decision not in {"blocked", "research_only"}:
            raise ValueError("cn_market_rule_decision_invalid")
        if (self.status == "blocked") != bool(blockers):
            raise ValueError("cn_market_rule_status_blocker_mismatch")
        if self.decision == "research_only" and blockers:
            raise ValueError("cn_market_rule_research_only_with_blockers")
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "bindings", bindings)

    @classmethod
    def blocked(
        cls,
        blockers: Iterable[MarketRuleBlocker],
        *,
        handoff_event_id: str = "",
        manifest_source: str = "",
    ) -> "MarketRuleConsumption":
        values = list(blockers)
        values.extend(_missing_rule_blockers())
        return cls(
            status="blocked",
            decision="blocked",
            handoff_event_id=handoff_event_id,
            manifest_source=manifest_source,
            blockers=tuple(values),
        )

    @property
    def safety_flags(self) -> dict[str, bool]:
        return {name: False for name in TRADING_SAFETY_FLAGS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings": [item.to_dict() for item in self.bindings],
            "blockers": [
                {
                    "code": item.code,
                    "detail": item.detail,
                    "next_action": item.next_action,
                    "owner": item.owner,
                }
                for item in self.blockers
            ],
            "bundle_sha256": self.bundle_sha256,
            "consumer_read_only": self.consumer_read_only,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "decision": self.decision,
            "handoff_event_id": self.handoff_event_id,
            "manifest_sha256": self.manifest_sha256,
            "manifest_source": self.manifest_source,
            "resolved_path": self.resolved_path,
            "safety_flags": self.safety_flags,
            "status": self.status,
        }


def consume_cn_market_rule_bundle(
    *,
    manifest_path: Path | None,
    shared_root: Path,
    handoff_event_id: str,
    handoff_validated: bool,
    evaluated_at: datetime,
    manifest_reference: str = "",
) -> MarketRuleConsumption:
    """Resolve immutable bytes and bind only formal, visible rule evidence."""

    evaluated = _timestamp(evaluated_at, "evaluated_at")
    event_id = str(handoff_event_id).strip()
    if not event_id:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_HANDOFF_MISSING),)
        )
    if handoff_validated is not True:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_HANDOFF_INVALID, event_id),),
            handoff_event_id=event_id,
        )
    if manifest_path is None:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_MANIFEST_MISSING),),
            handoff_event_id=event_id,
        )
    manifest = Path(manifest_path)
    source = manifest_reference or str(manifest)
    if not manifest.is_file():
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_MANIFEST_MISSING, str(manifest)),),
            handoff_event_id=event_id,
            manifest_source=source,
        )

    try:
        manifest_before = manifest.read_bytes()
        resolved = resolve_manifest_file(
            manifest,
            shared_root=Path(shared_root),
            verify_files=True,
        )
        manifest_bytes = manifest.read_bytes()
        if manifest_before != manifest_bytes:
            raise ValueError("manifest_changed_during_resolution")
        manifest_payload = _json_object(
            manifest_bytes,
            CN_MARKET_RULE_MANIFEST_CONTRACT_INVALID,
        )
    except (OSError, SharedDataError, ValueError) as exc:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_MANIFEST_RESOLVE_FAILED, str(exc)),),
            handoff_event_id=event_id,
            manifest_source=source,
        )

    manifest_blockers = _validate_manifest_contract(manifest_payload)
    if manifest_blockers:
        return MarketRuleConsumption.blocked(
            manifest_blockers,
            handoff_event_id=event_id,
            manifest_source=source,
        )

    declared = next(
        (
            item
            for item in manifest_payload["files"]
            if item.get("path") == BUNDLE_FILE
        ),
        None,
    )
    if declared is None:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_FILE_MISSING, BUNDLE_FILE),),
            handoff_event_id=event_id,
            manifest_source=source,
        )
    if declared.get("bytes") == 0:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_FILE_EMPTY, BUNDLE_FILE),),
            handoff_event_id=event_id,
            manifest_source=source,
        )

    bundle_path = resolved / BUNDLE_FILE
    try:
        bundle_bytes = bundle_path.read_bytes()
    except OSError as exc:
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_FILE_MISSING, str(exc)),),
            handoff_event_id=event_id,
            manifest_source=source,
        )
    if (
        len(bundle_bytes) != declared.get("bytes")
        or hashlib.sha256(bundle_bytes).hexdigest() != declared.get("sha256")
    ):
        return MarketRuleConsumption.blocked(
            (
                _blocker(
                    CN_MARKET_RULE_MANIFEST_RESOLVE_FAILED,
                    "bundle_changed_after_resolution",
                ),
            ),
            handoff_event_id=event_id,
            manifest_source=source,
        )
    if not bundle_bytes.strip():
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_FILE_EMPTY, BUNDLE_FILE),),
            handoff_event_id=event_id,
            manifest_source=source,
        )
    prefix = bundle_bytes.lstrip()[:32].lower()
    if prefix.startswith(b"<html") or prefix.startswith(b"<!doctype"):
        return MarketRuleConsumption.blocked(
            (_blocker(CN_MARKET_RULE_WEB_TEXT_FORBIDDEN, BUNDLE_FILE),),
            handoff_event_id=event_id,
            manifest_source=source,
        )
    try:
        bundle = _json_object(bundle_bytes, CN_MARKET_RULE_BUNDLE_INVALID)
    except ValueError as exc:
        return MarketRuleConsumption.blocked(
            (_blocker(str(exc)),),
            handoff_event_id=event_id,
            manifest_source=source,
        )

    blockers: list[MarketRuleBlocker] = []
    if bundle.get("schema_version") != BUNDLE_SCHEMA:
        blockers.append(_blocker(CN_MARKET_RULE_BUNDLE_SCHEMA_MISMATCH))
    if (
        bundle.get("dataset_id") != DATASET_ID
        or bundle.get("dataset_version") != manifest_payload["dataset_version"]
    ):
        blockers.append(_blocker(CN_MARKET_RULE_IDENTITY_MISMATCH))
    if not _pit_bridge_complete(bundle.get("pit_bridge"), evaluated):
        blockers.append(_blocker(CN_MARKET_RULE_PIT_BRIDGE_INCOMPLETE))

    rule_records = bundle.get("rules")
    session_records = bundle.get("sessions")
    if not isinstance(rule_records, list):
        blockers.append(_blocker(CN_MARKET_RULE_BUNDLE_INVALID, "rules"))
        rule_records = []
    if not isinstance(session_records, list):
        blockers.append(_blocker(CN_MARKET_RULE_BUNDLE_INVALID, "sessions"))
        session_records = []

    inventory = {
        str(item["path"]): item
        for item in manifest_payload["files"]
        if isinstance(item, Mapping)
    }
    rules: list[EffectiveRule] = []
    sessions: list[TradingSession] = []
    bindings: list[RuleEvidenceBinding] = []
    invalid_kinds: set[str] = set()
    for index, raw in enumerate(rule_records):
        kind = (
            str(raw.get("rule_kind", "")).strip()
            if isinstance(raw, Mapping)
            else ""
        )
        try:
            rule, binding = _parse_effective_rule(
                raw,
                evaluated=evaluated,
                repository=resolved,
                inventory=inventory,
            )
        except ValueError as exc:
            invalid_kinds.add(kind)
            blockers.append(
                _blocker(
                    str(exc),
                    f"rules[{index}]" + (f":{kind}" if kind else ""),
                )
            )
        else:
            rules.append(rule)
            bindings.append(binding)

    for index, raw in enumerate(session_records):
        try:
            session, binding = _parse_session(
                raw,
                evaluated=evaluated,
                repository=resolved,
                inventory=inventory,
            )
        except ValueError as exc:
            invalid_kinds.add(SESSION)
            blockers.append(_blocker(str(exc), f"sessions[{index}]"))
        else:
            sessions.append(session)
            bindings.append(binding)

    resolved_kinds = {item.rule_kind for item in bindings}
    for kind in REQUIRED_RULE_KINDS:
        if kind not in resolved_kinds or kind in invalid_kinds:
            blockers.append(_blocker(MISSING_RULE_BLOCKERS[kind]))

    if any(
        item.code
        in {
            CN_MARKET_RULE_BUNDLE_SCHEMA_MISMATCH,
            CN_MARKET_RULE_IDENTITY_MISMATCH,
            CN_MARKET_RULE_PIT_BRIDGE_INCOMPLETE,
        }
        for item in blockers
    ):
        blockers.extend(_missing_rule_blockers())
        rules = []
        sessions = []
        bindings = []

    result_blockers = _dedupe_blockers(blockers)
    return MarketRuleConsumption(
        status="blocked" if result_blockers else "pass",
        decision="blocked" if result_blockers else "research_only",
        dataset_id=str(manifest_payload["dataset_id"]),
        dataset_version=str(manifest_payload["dataset_version"]),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        bundle_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        handoff_event_id=event_id,
        manifest_source=source,
        resolved_path=str(resolved),
        blockers=result_blockers,
        bindings=tuple(bindings),
        rulebook=EffectiveRuleBook(rules),
        calendar=InjectedCalendar(sessions),
    )


def _validate_manifest_contract(
    manifest: Mapping[str, Any],
) -> tuple[MarketRuleBlocker, ...]:
    blockers: list[MarketRuleBlocker] = []
    if (
        manifest.get("dataset_id") != DATASET_ID
        or manifest.get("data_schema") != BUNDLE_SCHEMA
    ):
        blockers.append(_blocker(CN_MARKET_RULE_IDENTITY_MISMATCH))
    if (
        manifest.get("quality_status") != "pass"
        or manifest.get("blockers")
        or manifest.get("known_gaps")
    ):
        blockers.append(_blocker(CN_MARKET_RULE_MANIFEST_BLOCKED))
    guardrails = manifest.get("guardrails")
    required_false = (
        "promotion_unlock_allowed",
        "paper_or_live_unlock_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
    )
    if (
        not isinstance(guardrails, Mapping)
        or guardrails.get("immutable_version") is not True
        or guardrails.get("consumer_read_only") is not True
        or any(guardrails.get(name) is not False for name in required_false)
    ):
        blockers.append(_blocker(CN_MARKET_RULE_MANIFEST_CONTRACT_INVALID))
    return _dedupe_blockers(blockers)


def _pit_bridge_complete(value: Any, evaluated: datetime) -> bool:
    if not isinstance(value, Mapping):
        return False
    if (
        value.get("complete") is not True
        or value.get("dimension_mapping_complete") is not True
        or not str(value.get("version", "")).strip()
    ):
        return False
    required = ("event_time", "available_time", "ingested_at", "processed_at")
    try:
        event, available, ingested, processed = (
            _timestamp(value.get(name), f"pit_bridge.{name}") for name in required
        )
    except ValueError:
        return False
    return event <= available <= ingested <= processed and available <= evaluated


def _parse_effective_rule(
    value: Any,
    *,
    evaluated: datetime,
    repository: Path,
    inventory: Mapping[str, Mapping[str, Any]],
) -> tuple[EffectiveRule, RuleEvidenceBinding]:
    if not isinstance(value, Mapping):
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    kind = str(value.get("rule_kind", "")).strip()
    if kind not in DOMAIN_RULE_KINDS:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    _verify_evidence_reference(
        value,
        repository=repository,
        inventory=inventory,
    )
    metadata = _formal_metadata(value, kind=kind, evaluated=evaluated)
    dimensions = _dimensions(value.get("dimensions"))
    payload_value = value.get("payload")
    if not isinstance(payload_value, Mapping):
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    try:
        payload = _policy(kind, payload_value, value)
        rule = EffectiveRule(
            rule_kind=kind,
            rule_version=metadata["version"],
            effective_from=metadata["effective_from"],
            effective_to=metadata["effective_to"],
            available_time=metadata["available_time"],
            ingested_at=metadata["ingested_at"],
            processed_at=metadata["processed_at"],
            dimensions=dimensions,
            payload=payload,
            source=metadata["source"],
            checksum=metadata["checksum"],
        )
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("cn_market_rule_"):
            raise
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID) from exc
    if not rule.is_effective(evaluated):
        raise ValueError(f"{kind}_rule_not_effective")
    return rule, _binding(kind, dimensions, metadata)


def _parse_session(
    value: Any,
    *,
    evaluated: datetime,
    repository: Path,
    inventory: Mapping[str, Mapping[str, Any]],
) -> tuple[TradingSession, RuleEvidenceBinding]:
    if not isinstance(value, Mapping):
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    _verify_evidence_reference(
        value,
        repository=repository,
        inventory=inventory,
    )
    metadata = _formal_metadata(value, kind=SESSION, evaluated=evaluated)
    dimensions = _dimensions(value.get("dimensions"))
    phases_value = value.get("phases")
    if not isinstance(phases_value, list) or not phases_value:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    try:
        phases = tuple(
            SessionPhase(
                name=str(item["name"]),
                starts_at=_timestamp(item["starts_at"], "phase.starts_at"),
                ends_at=_timestamp(item["ends_at"], "phase.ends_at"),
                accepts_orders=item["accepts_orders"],
            )
            for item in phases_value
            if isinstance(item, Mapping)
        )
        if len(phases) != len(phases_value):
            raise ValueError("invalid phase")
        session = TradingSession(
            session_id=str(value["session_id"]),
            calendar_version=metadata["version"],
            venue=dimensions.venue,
            board=dimensions.board,
            instrument=dimensions.instrument,
            security_type=dimensions.security_type,
            available_time=metadata["available_time"],
            ingested_at=metadata["ingested_at"],
            processed_at=metadata["processed_at"],
            source=metadata["source"],
            checksum=metadata["checksum"],
            starts_at=metadata["effective_from"],
            ends_at=metadata["effective_to"],
            is_open=value["is_open"],
            phases=phases,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID) from exc
    if metadata["effective_to"] is None:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    if not (session.starts_at <= evaluated < session.ends_at):
        raise ValueError("session_rule_not_effective")
    return session, _binding(SESSION, dimensions, metadata)


def _formal_metadata(
    value: Mapping[str, Any],
    *,
    kind: str,
    evaluated: datetime,
) -> dict[str, Any]:
    source_type = str(value.get("source_type", "")).strip()
    if (
        value.get("formal_evidence") is not True
        or source_type not in FORMAL_SOURCE_TYPES
        or source_type in {"webpage", "web_text"}
    ):
        raise ValueError(CN_MARKET_RULE_SOURCE_NOT_FORMAL)
    if (
        value.get("dimension_evidence_complete") is not True
        or value.get("pit_complete") is not True
        or not str(value.get("source_document_id", "")).strip()
    ):
        raise ValueError(CN_MARKET_RULE_DIMENSION_INCOMPLETE)
    available = _timestamp(value.get("available_time"), "available_time")
    if available > evaluated:
        raise ValueError(f"{kind}_rule_not_available")
    effective_to = (
        _timestamp(value.get("effective_to"), "effective_to")
        if value.get("effective_to") is not None
        else None
    )
    return {
        "available_time": available,
        "checksum": ensure_sha256_checksum(
            str(value.get("checksum", "")),
            "market_rule.checksum",
        ),
        "effective_from": _timestamp(
            value.get("effective_from"),
            "effective_from",
        ),
        "effective_to": effective_to,
        "ingested_at": _timestamp(value.get("ingested_at"), "ingested_at"),
        "processed_at": _timestamp(value.get("processed_at"), "processed_at"),
        "source": _non_empty(value.get("source"), "source"),
        "source_document_id": _non_empty(
            value.get("source_document_id"),
            "source_document_id",
        ),
        "source_type": source_type,
        "version": _non_empty(value.get("rule_version"), "rule_version"),
    }


def _verify_evidence_reference(
    value: Mapping[str, Any],
    *,
    repository: Path,
    inventory: Mapping[str, Mapping[str, Any]],
) -> None:
    evidence_path = value.get("evidence_path")
    evidence_sha256 = value.get("evidence_sha256")
    evidence_bytes = value.get("evidence_bytes")
    if (
        not isinstance(evidence_path, str)
        or not evidence_path
        or "\\" in evidence_path
        or Path(evidence_path).is_absolute()
        or ".." in Path(evidence_path).parts
        or evidence_path == BUNDLE_FILE
    ):
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    declared = inventory.get(evidence_path)
    if declared is None:
        raise ValueError(CN_MARKET_RULE_FILE_MISSING)
    if (
        not isinstance(evidence_bytes, int)
        or isinstance(evidence_bytes, bool)
        or evidence_bytes <= 0
        or declared.get("bytes") != evidence_bytes
    ):
        raise ValueError(CN_MARKET_RULE_FILE_EMPTY)
    try:
        digest = ensure_sha256_checksum(
            str(evidence_sha256),
            "market_rule.evidence_sha256",
        )
    except ValueError as exc:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID) from exc
    if declared.get("sha256") != digest:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    if Path(evidence_path).suffix.lower() in {".html", ".htm", ".txt"}:
        raise ValueError(CN_MARKET_RULE_WEB_TEXT_FORBIDDEN)
    if Path(evidence_path).suffix.lower() != ".json":
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    try:
        raw = (repository / evidence_path).read_bytes()
    except OSError as exc:
        raise ValueError(CN_MARKET_RULE_FILE_MISSING) from exc
    if (
        len(raw) != declared.get("bytes")
        or hashlib.sha256(raw).hexdigest() != declared.get("sha256")
    ):
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)
    if not raw.strip():
        raise ValueError(CN_MARKET_RULE_FILE_EMPTY)
    prefix = raw.lstrip()[:32].lower()
    if prefix.startswith(b"<html") or prefix.startswith(b"<!doctype"):
        raise ValueError(CN_MARKET_RULE_WEB_TEXT_FORBIDDEN)
    try:
        evidence_payload = _json_object(raw, CN_MARKET_RULE_RECORD_INVALID)
    except ValueError as exc:
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID) from exc
    if evidence_payload.get("source_document_id") != value.get(
        "source_document_id"
    ):
        raise ValueError(CN_MARKET_RULE_RECORD_INVALID)


def _dimensions(value: Any) -> MarketDimensions:
    if not isinstance(value, Mapping):
        raise ValueError(CN_MARKET_RULE_DIMENSION_INCOMPLETE)
    if set(value) != {
        "venue",
        "board",
        "instrument",
        "security_type",
        "security_id",
        "security_scope",
    }:
        raise ValueError(CN_MARKET_RULE_DIMENSION_INCOMPLETE)
    security_id = value.get("security_id")
    if security_id is not None and not isinstance(security_id, str):
        raise ValueError(CN_MARKET_RULE_DIMENSION_INCOMPLETE)
    if not str(value.get("security_scope", "")).strip():
        raise ValueError(CN_MARKET_RULE_DIMENSION_INCOMPLETE)
    try:
        return MarketDimensions(
            venue=str(value["venue"]),
            board=str(value["board"]),
            instrument=str(value["instrument"]),
            security_type=str(value["security_type"]),
            security_id=security_id,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(CN_MARKET_RULE_DIMENSION_INCOMPLETE) from exc


def _policy(kind: str, payload: Mapping[str, Any], record: Mapping[str, Any]):
    if kind == BOARD_LOT:
        return BoardLotPolicy(
            buy_lot_size=payload["buy_lot_size"],
            sell_lot_size=payload["sell_lot_size"],
            odd_lot_sell_allowed=payload["odd_lot_sell_allowed"],
            odd_lot_sell_mode=payload["odd_lot_sell_mode"],
        )
    if kind == PRICE_LIMIT:
        return PriceLimitPolicy(
            has_price_limit=payload["has_price_limit"],
            upper_ratio=(
                _decimal(payload["upper_ratio"], "upper_ratio")
                if payload["upper_ratio"] is not None
                else None
            ),
            lower_ratio=(
                _decimal(payload["lower_ratio"], "lower_ratio")
                if payload["lower_ratio"] is not None
                else None
            ),
            upper_rounding_mode=payload["upper_rounding_mode"],
            lower_rounding_mode=payload["lower_rounding_mode"],
        )
    if kind == SELLABILITY:
        return SellabilityPolicy(
            sellable_after_sessions=payload["sellable_after_sessions"]
        )
    if kind == FEE_SCHEDULE:
        if record.get("tax_scope_complete") is not True:
            raise ValueError(CN_MARKET_RULE_FEE_TAX_SCOPE_INCOMPLETE)

        def components(side: str) -> tuple[FeeComponent, ...]:
            rows = payload[side]
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"{FEE_SCHEDULE}_rule_missing")
            return tuple(
                FeeComponent(
                    name=str(item["name"]),
                    rate=_decimal(item["rate"], "rate"),
                    minimum_amount=_decimal(
                        item["minimum_amount"],
                        "minimum_amount",
                    ),
                    fixed_amount=_decimal(item["fixed_amount"], "fixed_amount"),
                    rounding_quantum=_decimal(
                        item["rounding_quantum"],
                        "rounding_quantum",
                    ),
                    rounding_mode=str(item["rounding_mode"]),
                )
                for item in rows
                if isinstance(item, Mapping)
            )

        return FeePolicy(buy=components("buy"), sell=components("sell"))
    if kind == SETTLEMENT:
        return SettlementPolicy(
            position_settlement_sessions=payload["position_settlement_sessions"],
            cash_settlement_sessions=payload["cash_settlement_sessions"],
            same_day_sell_allowed=payload["same_day_sell_allowed"],
        )
    raise ValueError(CN_MARKET_RULE_RECORD_INVALID)


def _binding(
    kind: str,
    dimensions: MarketDimensions,
    metadata: Mapping[str, Any],
) -> RuleEvidenceBinding:
    return RuleEvidenceBinding(
        rule_kind=kind,
        version=metadata["version"],
        source=metadata["source"],
        source_type=metadata["source_type"],
        source_document_id=metadata["source_document_id"],
        effective_from=metadata["effective_from"],
        effective_to=metadata["effective_to"],
        available_time=metadata["available_time"],
        dimensions=dimensions,
        checksum=metadata["checksum"],
    )


def _json_object(raw: bytes, blocker_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(blocker_code) from exc
    if not isinstance(payload, dict):
        raise ValueError(blocker_code)
    return payload


def _timestamp(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"timestamp_invalid:{field_name}") from exc
    else:
        raise ValueError(f"timestamp_invalid:{field_name}")
    try:
        return ensure_aware_timestamp(parsed, field_name).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"timestamp_invalid:{field_name}") from exc


def _decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"decimal_string_required:{field_name}")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"decimal_invalid:{field_name}") from exc
    if not parsed.is_finite():
        raise ValueError(f"decimal_invalid:{field_name}")
    return parsed


def _non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"non_empty_string_required:{field_name}")
    return value.strip()


def _blocker(code: str, detail: str = "") -> MarketRuleBlocker:
    return MarketRuleBlocker(code=str(code), detail=str(detail))


def _missing_rule_blockers() -> tuple[MarketRuleBlocker, ...]:
    return tuple(_blocker(MISSING_RULE_BLOCKERS[kind]) for kind in REQUIRED_RULE_KINDS)


def _dedupe_blockers(
    values: Iterable[MarketRuleBlocker],
) -> tuple[MarketRuleBlocker, ...]:
    unique: dict[tuple[str, str], MarketRuleBlocker] = {}
    for value in values:
        if not isinstance(value, MarketRuleBlocker):
            raise TypeError("market_rule_blocker_type_invalid")
        unique.setdefault((value.code, value.detail), value)
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.code, item.detail, item.owner),
        )
    )
