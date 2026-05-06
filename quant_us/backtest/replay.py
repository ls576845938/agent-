"""Backtest replay — deterministic replay from saved event log.

Saves the full event log from an event-driven backtest, then replays it
to verify determinism. Essential for debugging and auditing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.core.events import Event
from quant_us.core.types import Bar
from quant_us.strategies.base import Strategy


def _serialize(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for key, field_def in value.__dataclass_fields__.items():
            result[key] = _serialize(getattr(value, key))
        result["__type__"] = type(value).__name__
        return result
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_serialize(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass
class BacktestReplay:
    """Save and replay backtest event logs for deterministic verification."""

    run_id: str = ""
    bars: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, float | int] = field(default_factory=dict)

    @classmethod
    def from_result(cls, result: BacktestResult, bars: list[Bar], config: BacktestConfig) -> "BacktestReplay":
        return cls(
            run_id=result.run_id,
            bars=[_serialize(b) for b in bars],
            config=_serialize(config),
            events=[_serialize(e) for e in result.events],
            fills=[_serialize(f) for f in result.fills],
            orders=[_serialize(o) for o in result.orders],
            snapshots=[_serialize(s) for s in result.snapshots],
            summary=dict(result.summary),
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self.run_id,
            "config": self.config,
            "bars_count": len(self.bars),
            "events_count": len(self.events),
            "fills_count": len(self.fills),
            "orders_count": len(self.orders),
            "snapshots_count": len(self.snapshots),
            "summary": self.summary,
            "bars": self.bars,
            "events": self.events,
            "fills": self.fills,
            "orders": self.orders,
            "snapshots": self.snapshots,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "BacktestReplay":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            run_id=data.get("run_id", ""),
            bars=data.get("bars", []),
            config=data.get("config", {}),
            events=data.get("events", []),
            fills=data.get("fills", []),
            orders=data.get("orders", []),
            snapshots=data.get("snapshots", []),
            summary=data.get("summary", {}),
        )

    def verify_determinism(
        self,
        strategies: list[Strategy],
        bars: list[Bar],
        config: BacktestConfig | None = None,
    ) -> dict[str, Any]:
        """Re-run the backtest and verify results match the replay.

        Returns a dict with match status and any discrepancies.
        """
        engine_config = config or BacktestConfig(
            run_id=self.run_id,
            initial_cash=float(self.config.get("initial_cash", 100_000.0)),
            commission_rate=float(self.config.get("commission_rate", 0.0001)),
            slippage_bps=float(self.config.get("slippage_bps", 1.0)),
        )
        engine = EventDrivenBacktestEngine(strategies=strategies, config=engine_config)
        new_result = engine.run(bars)

        mismatches: list[str] = []

        for key in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "trade_count"]:
            old_val = self.summary.get(key)
            new_val = new_result.summary.get(key)
            if old_val is not None and new_val is not None:
                if abs(float(old_val) - float(new_val)) > 1e-8:
                    mismatches.append(f"{key}: {old_val} vs {new_val}")

        if len(self.fills) != len(new_result.fills):
            mismatches.append(f"fill count: {len(self.fills)} vs {len(new_result.fills)}")

        if len(self.orders) != len(new_result.orders):
            mismatches.append(f"order count: {len(self.orders)} vs {len(new_result.orders)}")

        if len(self.snapshots) != len(new_result.snapshots):
            mismatches.append(f"snapshot count: {len(self.snapshots)} vs {len(new_result.snapshots)}")

        return {
            "run_id": self.run_id,
            "deterministic": len(mismatches) == 0,
            "mismatches": mismatches,
            "replay_summary": new_result.summary,
        }
