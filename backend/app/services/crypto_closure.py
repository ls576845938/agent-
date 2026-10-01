from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.data_management import MarketDataService
from backend.app.services.market_data import inspect_market_data_quality
from backend.app.services.research_gate import ResearchPromotionGateService
from quant_crypto.adapters.closure_evidence_repository import file_closure_evidence_uow_factory
from quant_crypto.application.closure_ports import ClosureEvidenceUnitOfWorkFactory
from quant_crypto.application.crypto_closure import (
    DEFAULT_CRYPTO_STRATEGIES,
    DEFAULT_CRYPTO_TARGET_INTERVALS,
    CryptoClosureService as ApplicationCryptoClosureService,
)
from quant_us.backtest.crypto_event import (
    default_crypto_cost_stress_scenarios,
    qualify_crypto_candidates,
    summarize_crypto_interval_validation,
)
from quant_us.research.validation import summarize_candidate_validation


class CryptoClosureService(ApplicationCryptoClosureService):
    """Backend composition facade for the BTC application service."""

    def __init__(
        self,
        *,
        research_service: ResearchBacktestService,
        promotion_gate_service: ResearchPromotionGateService,
        market_data_service: MarketDataService,
        quality_inspector: Callable[..., dict[str, Any]] = inspect_market_data_quality,
        evidence_uow_factory: ClosureEvidenceUnitOfWorkFactory = file_closure_evidence_uow_factory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            research_service=research_service,
            promotion_gate_service=promotion_gate_service,
            market_data_service=market_data_service,
            quality_inspector=quality_inspector,
            evidence_uow_factory=evidence_uow_factory,
            cost_stress_scenarios=default_crypto_cost_stress_scenarios,
            candidate_qualifier=qualify_crypto_candidates,
            interval_validation_summarizer=summarize_crypto_interval_validation,
            candidate_validation_summarizer=summarize_candidate_validation,
            clock=clock,
        )


__all__ = [
    "CryptoClosureService",
    "DEFAULT_CRYPTO_STRATEGIES",
    "DEFAULT_CRYPTO_TARGET_INTERVALS",
]
