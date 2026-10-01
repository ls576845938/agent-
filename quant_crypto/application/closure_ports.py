from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class CryptoResampleRequest:
    symbol: str = "BTCUSDT"
    target_interval: str = "1h"
    start: datetime | None = None
    end: datetime | None = None
    db_path: str = ""
    exchange: str = "binance_spot"
    source_interval: str = "1m"
    persist_manifest: bool = True


class ResearchBacktestPort(Protocol):
    def optimize_strategy(self, request: dict[str, Any]) -> Any: ...

    def run_crypto_event(self, request: dict[str, Any]) -> Any: ...

    def run_event_driven_cost_stress(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def run_walk_forward(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def run_cpcv_validation(self, request: dict[str, Any]) -> dict[str, Any]: ...


class PromotionGatePort(Protocol):
    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]: ...


class MarketDataPort(Protocol):
    def resample_crypto_klines(self, spec: CryptoResampleRequest) -> Any: ...


class ClosureEvidenceUnitOfWork(Protocol):
    def stage_candidate_evidence(self, *, run_id_prefix: str, payload: dict[str, Any]) -> str: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


ClosureEvidenceUnitOfWorkFactory = Callable[[str], ClosureEvidenceUnitOfWork]
