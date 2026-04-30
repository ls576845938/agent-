from __future__ import annotations

from backend.app.services.backtests import ResearchBacktestService
from backend.app.services.data_management import DataUpdateScheduler, MarketDataService
from backend.app.services.run_registry import RunRegistry
from backend.app.services.us_quant import USQuantService


research_service = ResearchBacktestService()
run_registry = RunRegistry()
market_data_service = MarketDataService()
data_update_scheduler = DataUpdateScheduler()
us_quant_service = USQuantService()
