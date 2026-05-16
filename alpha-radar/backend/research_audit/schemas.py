"""
Alpha Radar Research Credibility Audit Engine — Schema Definitions.

Defines core data structures for evidence collection, audit targets, and
audit results.  Uses only Python stdlib — no Pydantic or external deps.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SOURCE_TYPES: frozenset[str] = frozenset({
    "news",
    "filing",
    "price_volume",
    "financial",
    "industry_data",
    "manual_note",
    "ai_generated",
})

VALID_TARGET_TYPES: frozenset[str] = frozenset({
    "signal",
    "factor",
    "stock_pool",
    "narrative",
    "sector_chain_node",
    "strategy_note",
})

VALID_DIRECTIONS: frozenset[str] = frozenset({
    "positive",
    "negative",
    "neutral",
    "uncertain",
})

VALID_FRESHNESS: frozenset[str] = frozenset({
    "recent",
    "moderate",
    "stale",
    "unknown",
})

VALID_AUDIT_STATUSES: frozenset[str] = frozenset({
    "BLOCKED",
    "WATCHLIST",
    "NEED_MORE_EVIDENCE",
    "RESEARCH_READY",
    "HIGH_CONVICTION",
})

SIGNAL_REQUIRED_KEYS: frozenset[str] = frozenset({"name", "direction"})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _json_serialize(obj: Any) -> str:
    """JSON-serialise with dataclass-friendly defaults."""
    return json.dumps(obj, default=_default_serialiser, ensure_ascii=False, sort_keys=True)


def _default_serialiser(o: Any) -> Any:
    """Convert dataclasses and UUIDs to plain JSON-safe types."""
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "__dataclass_fields__"):
        return _dataclass_to_dict(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON-serialisable")


def _dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    """Recursively convert a dataclass instance to a plain dict."""
    result: Dict[str, Any] = {}
    for f_name in (f.name for f in obj.__dataclass_fields__.values()):
        val = getattr(obj, f_name)
        if isinstance(val, list):
            result[f_name] = [_dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__") else v for v in val]
        elif isinstance(val, dict):
            result[f_name] = {k: _dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__") else v for k, v in val.items()}
        elif hasattr(val, "__dataclass_fields__"):
            result[f_name] = _dataclass_to_dict(val)
        else:
            result[f_name] = val
    return result


def _from_dict_evidence_list(data: List[Dict[str, Any]]) -> List[EvidenceItem]:
    return [EvidenceItem.from_dict(d) for d in data]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------

@dataclass
class EvidenceItem:
    """A single piece of evidence — a claim from a named source."""

    source_type: str
    source_name: str
    source_url: str = ""
    publish_time: str = ""
    claim: str = ""
    affected_targets: List[str] = field(default_factory=list)
    direction: str = "neutral"
    confidence: float = 0.5
    freshness: str = "unknown"

    def __post_init__(self) -> None:
        # Clamp confidence to [0.0, 1.0]
        if self.confidence < 0.0:
            self.confidence = 0.0
        elif self.confidence > 1.0:
            self.confidence = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "publish_time": self.publish_time,
            "claim": self.claim,
            "affected_targets": list(self.affected_targets),
            "direction": self.direction,
            "confidence": self.confidence,
            "freshness": self.freshness,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> EvidenceItem:
        return EvidenceItem(
            source_type=d.get("source_type", ""),
            source_name=d.get("source_name", ""),
            source_url=d.get("source_url", ""),
            publish_time=d.get("publish_time", ""),
            claim=d.get("claim", ""),
            affected_targets=list(d.get("affected_targets", [])),
            direction=d.get("direction", "neutral"),
            confidence=float(d.get("confidence", 0.5)),
            freshness=d.get("freshness", "unknown"),
        )

    def __repr__(self) -> str:
        return (
            f"EvidenceItem(source_type={self.source_type!r}, "
            f"source_name={self.source_name!r}, "
            f"direction={self.direction!r}, "
            f"confidence={self.confidence})"
        )


# ---------------------------------------------------------------------------
# ResearchAuditTarget
# ---------------------------------------------------------------------------

@dataclass
class ResearchAuditTarget:
    """An entity under audit — signal, factor, narrative, or chain node."""

    target_type: str
    target_id: str
    title: str = ""
    thesis: str = ""
    related_symbols: List[str] = field(default_factory=list)
    related_industries: List[str] = field(default_factory=list)
    related_chain_nodes: List[str] = field(default_factory=list)
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    signals: List[Dict[str, Any]] = field(default_factory=list)
    backtest_summary: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "title": self.title,
            "thesis": self.thesis,
            "related_symbols": list(self.related_symbols),
            "related_industries": list(self.related_industries),
            "related_chain_nodes": list(self.related_chain_nodes),
            "evidence_items": [e.to_dict() for e in self.evidence_items],
            "signals": list(self.signals),
            "backtest_summary": self.backtest_summary,
            "metadata": dict(self.metadata),
        }
        return result

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> ResearchAuditTarget:
        raw_items = d.get("evidence_items", [])
        if isinstance(raw_items, list):
            evidence = _from_dict_evidence_list(raw_items)
        else:
            evidence = []

        return ResearchAuditTarget(
            target_type=d.get("target_type", ""),
            target_id=d.get("target_id", ""),
            title=d.get("title", ""),
            thesis=d.get("thesis", ""),
            related_symbols=list(d.get("related_symbols", [])),
            related_industries=list(d.get("related_industries", [])),
            related_chain_nodes=list(d.get("related_chain_nodes", [])),
            evidence_items=evidence,
            signals=list(d.get("signals", [])),
            backtest_summary=d.get("backtest_summary"),
            metadata=dict(d.get("metadata", {})),
        )

    def __repr__(self) -> str:
        return (
            f"ResearchAuditTarget(target_type={self.target_type!r}, "
            f"target_id={self.target_id!r}, "
            f"evidence_count={len(self.evidence_items)})"
        )


# ---------------------------------------------------------------------------
# ResearchAuditResult
# ---------------------------------------------------------------------------

@dataclass
class ResearchAuditResult:
    """The outcome of a research credibility audit."""

    audit_id: str = field(default_factory=_new_uuid)
    target_type: str = ""
    target_id: str = ""
    audit_score: float = 0.0
    audit_status: str = "NEED_MORE_EVIDENCE"
    risk_flags: List[str] = field(default_factory=list)
    passed_checks: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence_score: float = 0.0
    signal_score: float = 0.0
    narrative_score: float = 0.0
    bias_score: float = 0.0
    report_json: Dict[str, Any] = field(default_factory=dict)
    report_markdown: str = ""
    created_at: str = field(default_factory=_now_utc_iso)

    def __post_init__(self) -> None:
        # Clamp sub-scores to [0.0, 1.0]
        for attr in ("evidence_score", "signal_score", "narrative_score", "bias_score"):
            val = getattr(self, attr)
            if val < 0.0:
                setattr(self, attr, 0.0)
            elif val > 1.0:
                setattr(self, attr, 1.0)
        # Clamp audit_score to [0.0, 100.0]
        if self.audit_score < 0.0:
            self.audit_score = 0.0
        elif self.audit_score > 100.0:
            self.audit_score = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "audit_score": self.audit_score,
            "audit_status": self.audit_status,
            "risk_flags": list(self.risk_flags),
            "passed_checks": list(self.passed_checks),
            "failed_checks": list(self.failed_checks),
            "warnings": list(self.warnings),
            "evidence_score": self.evidence_score,
            "signal_score": self.signal_score,
            "narrative_score": self.narrative_score,
            "bias_score": self.bias_score,
            "report_json": dict(self.report_json),
            "report_markdown": self.report_markdown,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> ResearchAuditResult:
        return ResearchAuditResult(
            audit_id=d.get("audit_id", _new_uuid()),
            target_type=d.get("target_type", ""),
            target_id=d.get("target_id", ""),
            audit_score=float(d.get("audit_score", 0.0)),
            audit_status=d.get("audit_status", "NEED_MORE_EVIDENCE"),
            risk_flags=list(d.get("risk_flags", [])),
            passed_checks=list(d.get("passed_checks", [])),
            failed_checks=list(d.get("failed_checks", [])),
            warnings=list(d.get("warnings", [])),
            evidence_score=float(d.get("evidence_score", 0.0)),
            signal_score=float(d.get("signal_score", 0.0)),
            narrative_score=float(d.get("narrative_score", 0.0)),
            bias_score=float(d.get("bias_score", 0.0)),
            report_json=dict(d.get("report_json", {})),
            report_markdown=d.get("report_markdown", ""),
            created_at=d.get("created_at", _now_utc_iso()),
        )

    def __repr__(self) -> str:
        return (
            f"ResearchAuditResult(audit_id={self.audit_id!r}, "
            f"target_id={self.target_id!r}, "
            f"score={self.audit_score}, "
            f"status={self.audit_status!r})"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_target(target: ResearchAuditTarget) -> List[str]:
    """Validate a ResearchAuditTarget, returning a list of error messages.

    An empty list means the target is valid.
    """
    errors: List[str] = []

    # --- target_type ---
    if target.target_type not in VALID_TARGET_TYPES:
        errors.append(
            f"Invalid target_type {target.target_type!r}; "
            f"must be one of {sorted(VALID_TARGET_TYPES)}"
        )

    # --- target_id ---
    if not target.target_id or not target.target_id.strip():
        errors.append("target_id must be a non-empty string")

    # --- evidence_items ---
    for idx, item in enumerate(target.evidence_items):
        if not isinstance(item, EvidenceItem):
            errors.append(f"evidence_items[{idx}] is not an EvidenceItem instance")
            continue
        if item.source_type not in VALID_SOURCE_TYPES:
            errors.append(
                f"evidence_items[{idx}].source_type {item.source_type!r} "
                f"is invalid; must be one of {sorted(VALID_SOURCE_TYPES)}"
            )
        if item.direction not in VALID_DIRECTIONS:
            errors.append(
                f"evidence_items[{idx}].direction {item.direction!r} "
                f"is invalid; must be one of {sorted(VALID_DIRECTIONS)}"
            )

    # --- signals ---
    for idx, sig in enumerate(target.signals):
        if not isinstance(sig, dict):
            errors.append(f"signals[{idx}] is not a dict")
            continue
        missing = [k for k in SIGNAL_REQUIRED_KEYS if k not in sig]
        if missing:
            errors.append(
                f"signals[{idx}] is missing required key(s): {sorted(missing)}"
            )
        if "direction" in sig and sig["direction"] not in VALID_DIRECTIONS:
            errors.append(
                f"signals[{idx}].direction {sig['direction']!r} "
                f"is invalid; must be one of {sorted(VALID_DIRECTIONS)}"
            )

    return errors
