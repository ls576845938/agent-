from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now


class OpenBBAdapterError(RuntimeError):
    """Base OpenBB adapter error."""


@dataclass(frozen=True)
class OpenBBResearchRequest:
    request_id: str
    topic: str
    symbols: list[str]
    requested_datasets: list[str]
    operator: str = "codex"
    source: str = "openbb"
    purpose: str = "supplemental_research"
    allow_promotion_clean: bool = False
    allow_implicit_trading_use: bool = False
    allow_paper: bool = False
    allow_live: bool = False

    def __post_init__(self) -> None:
        if not self.request_id:
            raise OpenBBAdapterError("request_id is required")
        if not self.topic:
            raise OpenBBAdapterError("topic is required")
        if not self.requested_datasets:
            raise OpenBBAdapterError("requested_datasets is required")
        blocked_flags = {
            "allow_promotion_clean": self.allow_promotion_clean,
            "allow_implicit_trading_use": self.allow_implicit_trading_use,
            "allow_paper": self.allow_paper,
            "allow_live": self.allow_live,
        }
        enabled = [name for name, value in blocked_flags.items() if value]
        if enabled:
            raise OpenBBAdapterError(f"openbb_supplemental_request_cannot_enable:{','.join(enabled)}")


@dataclass(frozen=True)
class OpenBBResearchManifest:
    schema_version: str
    status: str
    request_id: str
    source: str
    purpose: str
    topic: str
    symbols: list[str]
    requested_datasets: list[str]
    created_at: str
    production_pit_clean: bool
    promotion_status: str
    allow_paper: bool
    allow_live: bool
    required_normalization_before_promotion: list[str] = field(default_factory=list)
    lineage_tags: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


def build_openbb_research_manifest(
    request: OpenBBResearchRequest,
    *,
    output_path: str | Path | None = None,
) -> OpenBBResearchManifest:
    manifest = OpenBBResearchManifest(
        schema_version="openbb_research_manifest_v1",
        status="RESEARCH_ONLY",
        request_id=request.request_id,
        source=request.source,
        purpose=request.purpose,
        topic=request.topic,
        symbols=_normalize_symbols(request.symbols),
        requested_datasets=[str(item).strip() for item in request.requested_datasets if str(item).strip()],
        created_at=utc_now().isoformat(),
        production_pit_clean=False,
        promotion_status="supplemental_research_only",
        allow_paper=False,
        allow_live=False,
        required_normalization_before_promotion=[
            "provider_neutral_ingest",
            "event_time_available_time_mapping",
            "local_hash_and_schema_validation",
            "pit_bundle_or_release_calendar_binding",
            "standard_data_quality_gate",
        ],
        lineage_tags={
            "source_role": "supplemental_data_exploration",
            "not_sufficient_for": [
                "production_pit_data",
                "strategy_validation_gate",
                "paper_readiness",
                "live_readiness",
            ],
        },
    )
    if output_path is not None:
        write_json(output_path, manifest)
    return manifest


def _normalize_symbols(symbols: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def to_jsonable(payload: Any) -> Any:
    if is_dataclass(payload):
        return {key: to_jsonable(value) for key, value in asdict(payload).items()}
    if isinstance(payload, dict):
        return {str(key): to_jsonable(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple, set)):
        return [to_jsonable(value) for value in payload]
    if isinstance(payload, Path):
        return str(payload)
    if isinstance(payload, (datetime, date)):
        return payload.isoformat()
    item = getattr(payload, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:
            pass
    return payload


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(to_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return target
