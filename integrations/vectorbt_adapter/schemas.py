from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


class VectorBTAdapterError(RuntimeError):
    """Base vectorbt adapter error."""


@dataclass(frozen=True)
class VectorBTScreenConfig:
    run_id: str
    strategy_family: str
    timeframe: str
    data_source: str
    cost_bps: float = 0.0
    decision_time_rule: str = "completed_bar_close_signal"
    execution_time_rule: str = "next_bar_exposure"
    promotion_status: str = "research_screen_only"
    allow_paper: bool = False
    allow_live: bool = False

    def __post_init__(self) -> None:
        if not self.run_id:
            raise VectorBTAdapterError("run_id is required")
        if not self.strategy_family:
            raise VectorBTAdapterError("strategy_family is required")
        if self.cost_bps < 0:
            raise VectorBTAdapterError("cost_bps must be non-negative")
        if self.allow_paper or self.allow_live:
            raise VectorBTAdapterError("vectorbt screening cannot enable paper or live")


@dataclass(frozen=True)
class VectorBTScreenRow:
    candidate_id: str
    total_return_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    turnover_pct: float
    exposure_ratio_pct: float
    observation_count: int
    cost_paid_pct: float


@dataclass(frozen=True)
class VectorBTScreenReport:
    schema_version: str
    status: str
    run_id: str
    strategy_family: str
    timeframe: str
    data_source: str
    vectorbt_available: bool
    promotion_status: str
    must_replay_with_ledger: bool
    allow_paper: bool
    allow_live: bool
    decision_time_rule: str
    execution_time_rule: str
    cost_bps: float
    candidate_count: int
    ranking: list[VectorBTScreenRow] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


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
