from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from quant_us.backtest.configuration import build_backtest_config
from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.data.cleaners.corporate_action_adjuster import CorporateAction
from quant_us.data.events import EarningsEvent
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.execution.paper_broker import PaperBroker
from quant_us.factors.feature_pipeline import FeaturePipeline
from quant_us.live.reconciliation_service import ReconciliationService


class USQuantService:
    def _date_from_payload(self, value: Any) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    def _corporate_actions_from_payload(self, items: list[dict[str, Any]]) -> list[CorporateAction]:
        return [
            CorporateAction(
                symbol=str(item["symbol"]),
                action_type=str(item["action_type"]).lower(),
                ex_date=self._date_from_payload(item["ex_date"]),
                ratio=float(item.get("ratio", 1.0)),
                cash_amount=float(item.get("cash_amount", 0.0)),
                source=str(item.get("source", "")),
            )
            for item in items
        ]

    def _earnings_events_from_payload(self, items: list[dict[str, Any]]) -> list[EarningsEvent]:
        return [
            EarningsEvent(
                symbol=str(item["symbol"]),
                event_date=self._date_from_payload(item["event_date"]),
                source=str(item.get("source", "")),
            )
            for item in items
        ]

    def _symbols_from_payload(self, request: dict[str, Any]) -> list[str]:
        raw_symbols = request.get("symbols") or [request["symbol"]]
        symbols: list[str] = []
        seen: set[str] = set()
        for item in raw_symbols:
            symbol = str(item).strip().upper()
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols

    def _backtest_parameters_from_payload(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "capital": request.get("capital", 100_000.0),
            "commission_rate": request.get("commission_rate", 0.0001),
            "slippage_bps": request.get("slippage_bps", 1.0),
            "max_symbol_weight": request.get("max_symbol_weight", 0.10),
            "max_order_notional_pct": request.get("max_order_notional_pct", 0.10),
            "max_gross_exposure": request.get("max_gross_exposure", 1.0),
            "min_cash_buffer_pct": request.get("min_cash_buffer_pct", 0.02),
            "default_strategy_weight": request.get("default_strategy_weight", 0.10),
            "cash_reserve_weight": request.get("cash_reserve_weight", 0.05),
            "max_group_weight": request.get("max_group_weight"),
            "group_map": request.get("group_map", {}),
            "min_trade_notional": request.get("min_trade_notional", 25.0),
            "min_weight_change": request.get("min_weight_change", 0.0),
            "long_only": request.get("long_only", True),
            "strategy_allocations": request.get("strategy_allocations", {}),
            "blacklisted_symbols": request.get("blacklisted_symbols", []),
        }

    def sync_data(self, request: dict[str, Any]) -> dict[str, Any]:
        data = DataLakeService(DataLakeConfig(data_root=Path(request.get("data_root") or "data")))
        result = data.sync_bars(
            symbol=request["symbol"],
            start=request["start"],
            end=request["end"],
            bar_size=request.get("bar_size", "1d"),
            vendor=request.get("vendor", "yfinance"),
            asset_class=request.get("asset_class", "equity"),
        )
        payload = asdict(result)
        payload["quality"] = asdict(result.quality)
        payload["quality"]["is_usable"] = result.quality.is_usable
        return payload

    def build_features(self, request: dict[str, Any]) -> dict[str, Any]:
        data_root = Path(request.get("data_root") or "data")
        data = DataLakeService(DataLakeConfig(data_root=data_root))
        bars = data.read_cleaned_bars(
            symbol=request["symbol"],
            start=request["start"],
            end=request["end"],
            bar_size=request.get("bar_size", "1d"),
            vendor=request.get("vendor", "yfinance"),
            asset_class=request.get("asset_class", "equity"),
        )
        if bars.empty and request.get("auto_sync", False):
            sync = data.sync_bars(
                symbol=request["symbol"],
                start=request["start"],
                end=request["end"],
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
            )
            if sync.status != "completed":
                raise ValueError(sync.error or "Unable to sync bars before building features")
            bars = data.read_cleaned_bars(
                symbol=request["symbol"],
                start=request["start"],
                end=request["end"],
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
            )
        result = FeaturePipeline(feature_root=data_root / "features").build_bar_factors(
            bars,
            universe=request.get("universe", "default"),
            version=request.get("version", "v1"),
        )
        return asdict(result)

    def run_event_backtest(self, request: dict[str, Any]) -> dict[str, Any]:
        data_root = Path(request.get("data_root") or "data")
        symbols = self._symbols_from_payload(request)
        corporate_actions = self._corporate_actions_from_payload(request.get("corporate_actions", []))
        earnings_events = self._earnings_events_from_payload(request.get("earnings_events", []))
        backtest_parameters = self._backtest_parameters_from_payload(request)
        config = build_backtest_config(parameters=backtest_parameters)
        try:
            result = run_event_backtest_from_lake(
                data_root=str(data_root),
                symbol=request["symbol"],
                symbols=symbols,
                start=request["start"],
                end=request["end"],
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
                strategy_id=request.get("strategy_id", "trend_momentum"),
                strategy_params=request.get("strategy_params", {}),
                feature_names=request.get("feature_names", []),
                feature_version=request.get("feature_version", "v1"),
                feature_universe=request.get("feature_universe", "default"),
                config=config,
                corporate_actions=corporate_actions,
                earnings_events=earnings_events,
            )
        except ValueError:
            if not request.get("auto_sync", True):
                raise
            data = DataLakeService(DataLakeConfig(data_root=data_root))
            for symbol in symbols:
                sync = data.sync_bars(
                    symbol=symbol,
                    start=request["start"],
                    end=request["end"],
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
                if sync.status != "completed":
                    raise ValueError(sync.error or f"Unable to sync {symbol} bars before running backtest")
            result = run_event_backtest_from_lake(
                data_root=str(data_root),
                symbol=request["symbol"],
                symbols=symbols,
                start=request["start"],
                end=request["end"],
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
                strategy_id=request.get("strategy_id", "trend_momentum"),
                strategy_params=request.get("strategy_params", {}),
                feature_names=request.get("feature_names", []),
                feature_version=request.get("feature_version", "v1"),
                feature_universe=request.get("feature_universe", "default"),
                config=config,
                corporate_actions=corporate_actions,
                earnings_events=earnings_events,
            )
        return {
            "run_id": result.run_id,
            "status": "completed",
            "summary": result.summary,
            "order_count": len(result.orders),
            "fill_count": len(result.fills),
            "snapshot_count": len(result.snapshots),
            "event_count": len(result.events),
            "diagnostics": {
                "symbol": request["symbol"].upper(),
                "symbols": symbols,
                "bar_size": request.get("bar_size", "1d"),
                "strategy_id": request.get("strategy_id", "trend_momentum"),
                "strategy_params": request.get("strategy_params", {}),
                "feature_names": request.get("feature_names", []),
                "feature_version": request.get("feature_version", "v1"),
                "feature_universe": request.get("feature_universe", "default"),
                "backtest_parameters": backtest_parameters,
                "data_root": str(data_root),
                "data_filters": result.metadata,
            },
        }

    def reconcile_local_ledger(self, request: dict[str, Any]) -> dict[str, Any]:
        ledger_dir = Path(request.get("ledger_dir") or "data/ledger/paper")
        broker = PaperBroker()
        service = ReconciliationService(ledger_dir, broker)
        broker.positions = service.ledger.latest_positions_from_fills()
        return service.reconcile_positions(tolerance=float(request.get("tolerance", 1e-6)))
