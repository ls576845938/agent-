from __future__ import annotations

from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.crypto_closure import CryptoClosureService
from backend.app.services.data_management import DataUpdateScheduler, MarketDataService
from backend.app.services.research_gate import ResearchPromotionGateService
from backend.app.services.run_registry import RunRegistry
from backend.app.services.us_quant import USQuantService


research_service = ResearchBacktestService()
promotion_gate_service = ResearchPromotionGateService(research_service=research_service)
run_registry = RunRegistry()
market_data_service = MarketDataService()
data_update_scheduler = DataUpdateScheduler()
us_quant_service = USQuantService()
crypto_closure_service = CryptoClosureService(
    research_service=research_service,
    promotion_gate_service=promotion_gate_service,
    market_data_service=market_data_service,
)
