"""BTC-owned, current-HEAD, fail-closed operator read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence


SCHEMA_VERSION = "btc_domain_read_model_v1"
TEAM_CONTEXT_DISCOVERY_PATH = (
    "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
)
LAYER_IDS = ("data", "strategy", "risk", "oms", "ledger", "replay", "gate")
SAFETY_FLAGS = {
    "promotion_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "private_endpoint_allowed": False,
    "order_endpoint_allowed": False,
    "broker_access_allowed": False,
    "withdraw_allowed": False,
}
SELF_REFERENCE_TOKENS = (
    "dashboard_summary",
    "gate_summary",
    "readiness_summary",
)
CANONICAL_BLOCKER_ALIASES = {
    "btc_next_stage:real_funding_cashflow_evidence_missing": (
        "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime"
    ),
    "btc_next_stage:real_private_ws_reconciliation_evidence_missing": (
        "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete"
    ),
    "btc_next_stage:real_non_flat_fill_evidence_missing": (
        "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing"
    ),
    "btc_next_stage:manual_promotion_approval_missing": (
        "btc_okx_native:manual_promotion_approval_missing"
    ),
    "btc_next_stage:natural_observation_window_30_60d_incomplete": (
        "btc_okx_native:25_hour_demo_observation_window_incomplete"
    ),
}
CANONICAL_BLOCKER_OWNERS = {
    "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime": (
        "engineering",
        "btc_operations",
    ),
    "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete": (
        "engineering",
        "btc_operations",
    ),
    "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing": (
        "natural_time",
        "btc_observation",
    ),
    "btc_okx_native:25_hour_demo_observation_window_incomplete": (
        "natural_time",
        "btc_observation",
    ),
    "btc_okx_native:manual_promotion_approval_missing": (
        "manual_approval",
        "architect/manual_reviewer",
    ),
}


class BTCDomainReadModelRepository(Protocol):
    def read_sources(
        self, *, source_head: str, generated_at_utc: datetime
    ) -> Mapping[str, Mapping[str, Any]]: ...


class BTCPublishedDomainReadModelRepository(Protocol):
    def read_published(self, *, source_head: str) -> Mapping[str, Any]: ...


class BTCPublishedDomainReadModelUnavailable(RuntimeError):
    """Stable fail-closed error raised for an unusable published contract."""


@dataclass(frozen=True)
class BTCPublishedDomainReadModelService:
    """Read the already-published contract without rebuilding legacy sources."""

    repository: BTCPublishedDomainReadModelRepository
    head_resolver: Callable[[], str]

    def read(self) -> dict[str, Any]:
        source_head = self.head_resolver()
        if not source_head:
            raise BTCPublishedDomainReadModelUnavailable(
                "btc_published_domain_read_model_current_head_unavailable"
            )
        return dict(self.repository.read_published(source_head=source_head))


@dataclass(frozen=True)
class BTCDomainReadModelService:
    repository: BTCDomainReadModelRepository
    head_resolver: Callable[[], str]
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def read(self) -> dict[str, Any]:
        generated = _ensure_utc(self.clock())
        source_head = self.head_resolver()
        sources = self.repository.read_sources(
            source_head=source_head, generated_at_utc=generated
        )
        return build_btc_domain_read_model(
            sources=sources,
            source_head=source_head,
            generated_at_utc=generated,
        )


def build_btc_domain_read_model(
    *,
    sources: Mapping[str, Mapping[str, Any]],
    source_head: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc)
    source_rows = {
        layer: _source_row(layer, sources.get(layer, {})) for layer in LAYER_IDS
    }
    technical_blockers: list[str] = []
    raw_blockers: list[str] = []
    for layer, row in source_rows.items():
        freshness = row["freshness"]
        if freshness != "current":
            technical_blockers.append(
                f"btc_domain_read_model_source_{freshness}:{layer}"
            )
        raw_blockers.extend(str(item) for item in row.get("blockers", []))
    blockers = _classify_blockers([*technical_blockers, *raw_blockers])
    gate_source = source_rows["gate"]
    natural_wait = _natural_nonflat_wait(source_rows)
    blocked = bool(blockers)
    gate_decision = (
        "blocked_fail_closed_no_paper_no_live"
        if blocked
        else str(gate_source.get("decision") or "manual_review_required")
    )
    readiness = _readiness_class(
        blocked=blocked, source_rows=source_rows, gate_decision=gate_decision
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "domain": "btc",
        "owner": "btc_developer",
        "source_head": source_head,
        "code_commit": source_head,
        "generated_at_utc": generated.isoformat(),
        "freshness": (
            "current_head"
            if source_head
            and all(row["freshness"] == "current" for row in source_rows.values())
            else "blocked"
        ),
        "status": "blocked" if blocked else "current_read_only",
        "current_stage": (
            "waiting_for_natural_non_flat_sample"
            if natural_wait
            else ("blocked" if blocked else "manual_gate_review")
        ),
        "gate_decision": gate_decision,
        "readiness_class": readiness,
        "promotion_evidence_ready": readiness == "promotion_evidence_ready"
        and not blocked,
        "paper_ready": False,
        "live_ready": False,
        "layers": source_rows,
        "evidence": [
            {
                "layer": layer,
                "path": row["path"],
                "sha256": row["sha256"],
                "source_head": row["source_head"],
                "generated_at_utc": row["generated_at_utc"],
                "freshness": row["freshness"],
            }
            for layer, row in source_rows.items()
        ],
        "blockers": blockers,
        "blocker_count": len(blockers),
        "next_executable_action": _next_action(blockers, natural_wait=natural_wait),
        "safety": dict(SAFETY_FLAGS),
        "api_contract": {
            "method": "GET",
            "path": "/api/research/btc/domain-read-model",
            "cache_control": "no-store",
            "read_only": True,
            "side_effects": False,
            "builder_triggered": False,
            "runtime_triggered": False,
            "order_path_registered": False,
        },
        "team_context_contract": {
            "discovery_path": TEAM_CONTEXT_DISCOVERY_PATH,
            "shared_entry_wiring_owner": "integrator",
        },
        "ui_semantics": {
            "research_only_is_paper_ready": False,
            "blocked_is_paper_ready": False,
            "blocked_is_live_ready": False,
            "display_stage": (
                "等待自然非空样本"
                if natural_wait
                else ("阻断（只读）" if blocked else "只读复核")
            ),
        },
    }
    return report


def _source_row(layer: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "layer": layer,
        "status": str(raw.get("status") or "missing"),
        "decision": str(raw.get("decision") or ""),
        "readiness_class": str(raw.get("readiness_class") or "blocked"),
        "path": str(raw.get("path") or ""),
        "sha256": str(raw.get("sha256") or ""),
        "source_head": str(raw.get("source_head") or ""),
        "generated_at_utc": str(raw.get("generated_at_utc") or ""),
        "freshness": str(raw.get("freshness") or "missing"),
        "blockers": list(raw.get("blockers") or []),
        "summary": dict(raw.get("summary") or {}),
    }


def _classify_blockers(values: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        lowered = text.lower()
        if not text or any(token in lowered for token in SELF_REFERENCE_TOKENS):
            continue
        if "btc_domain_read_model" in lowered and "summary" in lowered:
            continue
        if lowered == "domain_read_model_missing":
            continue
        canonical = _canonical_blocker(text)
        if canonical in seen:
            continue
        seen.add(canonical)
        category, owner = _category_owner(text, canonical=canonical)
        rows.append(
            {
                "code": canonical,
                "category": category,
                "owner": owner,
                "next_executable_action": _action_for(category, canonical),
            }
        )
    return rows


def _canonical_blocker(text: str) -> str:
    value = text
    if value.startswith("owner:"):
        parts = value.split(" ", 1)
        value = parts[1] if len(parts) == 2 else value
    prefixes = (
        "dashboard:",
        "gate:",
        "readiness:",
        "promotion_gate:",
        "source:",
    )
    lowered = value.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.strip()
    return CANONICAL_BLOCKER_ALIASES.get(value, value)


def _category_owner(text: str, *, canonical: str = "") -> tuple[str, str]:
    lowered = text.lower()
    explicit_owner = _explicit_owner(text)
    if canonical in CANONICAL_BLOCKER_OWNERS:
        category, default_owner = CANONICAL_BLOCKER_OWNERS[canonical]
        return category, explicit_owner or default_owner
    if explicit_owner == "data_steward" or any(
        token in lowered for token in ("manifest", "data_", "snapshot", "attestation")
    ):
        return "data_steward", explicit_owner or "data_steward"
    if explicit_owner == "integrator" or "wiring" in lowered:
        return "integrator", explicit_owner or "integrator"
    if any(token in lowered for token in ("manual", "approval", "reviewer")):
        return (
            "manual_approval",
            explicit_owner or "architect/manual_reviewer",
        )
    if any(
        token in lowered
        for token in ("natural", "observation_window", "waiting_for", "30_60_day")
    ):
        return "natural_time", explicit_owner or "btc_observation"
    return "engineering", explicit_owner or "btc_developer"


def _explicit_owner(text: str) -> str:
    stripped = text.strip()
    if not stripped.lower().startswith("owner:"):
        return ""
    token = stripped.split(" ", 1)[0]
    return token.partition(":")[2].strip()


def _action_for(category: str, code: str) -> str:
    if category == "data_steward":
        return "wait_for_validated_immutable_data_handoff_then_rebuild_read_model"
    if category == "integrator":
        return "integrator_wire_committed_contract_then_rebuild_read_model"
    if category == "manual_approval":
        return "manual_reviewer_review_current_head_packet"
    if category == "natural_time":
        return "continue_observe_only_without_signal_or_threshold_changes"
    return f"resolve_engineering_blocker:{code}"


def _next_action(
    blockers: Sequence[Mapping[str, str]], *, natural_wait: bool
) -> dict[str, str]:
    if blockers:
        first = blockers[0]
        return {
            "owner": first["owner"],
            "category": first["category"],
            "action": first["next_executable_action"],
        }
    if natural_wait:
        return {
            "owner": "btc_observation",
            "category": "natural_time",
            "action": "continue_observe_only_without_signal_or_threshold_changes",
        }
    return {
        "owner": "architect/manual_reviewer",
        "category": "manual_approval",
        "action": "manual_reviewer_review_current_head_packet",
    }


def _natural_nonflat_wait(
    source_rows: Mapping[str, Mapping[str, Any]]
) -> bool:
    replay = source_rows["replay"]
    summary = replay.get("summary", {})
    return (
        summary.get("current_non_flat_sample_capture_status")
        in {
            "flat_waiting_no_false_positive",
            "waiting_for_natural_non_flat_sample",
        }
        or summary.get("trade_execution_evidence_pending_reason")
        in {
            "waiting_for_current_gate_eligible_non_flat_fill",
            "waiting_for_natural_non_flat_sample",
        }
    )


def _readiness_class(
    *,
    blocked: bool,
    source_rows: Mapping[str, Mapping[str, Any]],
    gate_decision: str,
) -> str:
    if blocked:
        return "quality_checked"
    declared = {
        str(row.get("readiness_class") or "") for row in source_rows.values()
    }
    if (
        "promotion_evidence_ready" in declared
        and gate_decision not in {"research_only", "blocked", "fail_closed"}
    ):
        return "promotion_evidence_ready"
    if "backtest_ready" in declared:
        return "backtest_ready"
    if "research_ready" in declared:
        return "research_ready"
    return "quality_checked"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "BTCDomainReadModelService",
    "BTCPublishedDomainReadModelService",
    "BTCPublishedDomainReadModelUnavailable",
    "SCHEMA_VERSION",
    "TEAM_CONTEXT_DISCOVERY_PATH",
    "build_btc_domain_read_model",
]
