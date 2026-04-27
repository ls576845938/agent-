from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class StrategyDescriptor:
    id: str
    display_name: str
    description: str
    category: str
    default_weight: float
    default_params: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategySignalPack:
    signal: Any
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class TradeMarker:
    time: int
    position: str
    color: str
    shape: str
    text: str


@dataclass
class BacktestArtifacts:
    mode: str
    summary: dict[str, float | int]
    chart: dict[str, list[dict[str, float | int | str]]]
    strategy_details: list[dict[str, Any]]
    latest_weights: list[dict[str, float | str]]
    diagnostics: dict[str, Any]


@dataclass
class RunRecord:
    run_id: str
    mode: str
    request: dict[str, Any]
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    result: BacktestArtifacts | None = None
