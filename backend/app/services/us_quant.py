from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from typing import Optional

import pandas as pd

from quant_us.backtest.configuration import build_backtest_config
from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
from quant_us.core.calendar import USEquityCalendar
from quant_us.data.cleaners.corporate_action_adjuster import CorporateAction
from quant_us.data.events import EarningsEvent
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.execution.paper_broker import PaperBroker
from quant_us.factors.feature_pipeline import FeaturePipeline
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.strategies.factory import build_strategy


class USQuantService:
    def __init__(self, db_connection: Any | None = None) -> None:
        self._paper_loop: Optional[PaperTradingLoop] = None
        self._db_connection = db_connection

    def _execute(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a single SQL statement and return the cursor."""
        if self._db_connection is None:
            raise RuntimeError("Database connection required. Provide db_connection to USQuantService.")
        with self._db_connection.cursor() as cursor:
            cursor.execute(sql, params or {})
        self._db_connection.commit()
        return cursor

    def _executemany(self, sql: str, rows: list[dict[str, Any]]) -> None:
        """Execute a batch SQL statement and commit."""
        if self._db_connection is None:
            raise RuntimeError("Database connection required. Provide db_connection to USQuantService.")
        with self._db_connection.cursor() as cursor:
            cursor.executemany(sql, rows)
        self._db_connection.commit()

    def populate_trading_calendar(self, start_year: int, end_year: int) -> int:
        """Populate quant.trading_calendar for every date in the year range.

        For each date determines:
          - is_trading_day (not weekend, not NYSE holiday)
          - session_hours ("09:30-16:00" regular, "09:30-13:00" early close, "00:00-00:00" non-trading)
          - early_close_time_et (13:00 ET on early close days, None otherwise)
          - holiday_name (name if holiday, None otherwise)

        Uses INSERT ... ON CONFLICT DO UPDATE (upsert) for idempotent writes.
        Returns the number of rows inserted.
        """
        calendar = USEquityCalendar.with_holidays(years=tuple(range(start_year, end_year + 1)))

        rows: list[dict[str, Any]] = []
        current = date(start_year, 1, 1)
        end = date(end_year, 12, 31)

        while current <= end:
            holiday_name = calendar.holidays.get(current)
            is_trading_day = calendar.is_trading_day(current)

            if not is_trading_day:
                session_hours = "00:00-00:00"
                early_close_time_et = None
            elif calendar.is_early_close(current):
                session_hours = "09:30-13:00"
                early_close_time_et = time(13, 0)
            else:
                session_hours = "09:30-16:00"
                early_close_time_et = None

            if not is_trading_day and holiday_name:
                notes = holiday_name
            elif calendar.is_early_close(current):
                notes = "Early close"
            else:
                notes = ""
            rows.append({
                "date": current,
                "is_trading_day": is_trading_day,
                "session_hours": session_hours,
                "early_close_time": early_close_time_et,
                "holiday_name": holiday_name,
                "notes": notes,
            })

            current += timedelta(days=1)

        sql = """
            INSERT INTO quant.trading_calendar
                (date, is_trading_day, session_hours, early_close_time, holiday_name, notes)
            VALUES
                (%(date)s, %(is_trading_day)s, %(session_hours)s, %(early_close_time)s, %(holiday_name)s, %(notes)s)
            ON CONFLICT (date) DO UPDATE SET
                is_trading_day = EXCLUDED.is_trading_day,
                session_hours = EXCLUDED.session_hours,
                early_close_time = EXCLUDED.early_close_time,
                holiday_name = EXCLUDED.holiday_name,
                notes = EXCLUDED.notes
        """
        self._executemany(sql, rows)
        return len(rows)

    def _ensure_paper_loop(self, initial_cash: float = 100_000.0) -> PaperTradingLoop:
        if self._paper_loop is None:
            config = PaperTradingConfig(
                initial_cash=initial_cash,
                commission_rate=0.0001,
                slippage_bps=1.0,
            )
            self._paper_loop = PaperTradingLoop(config=config)
        return self._paper_loop

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

    def _optional_symbols_from_payload(self, request: dict[str, Any]) -> list[str] | None:
        raw_symbols = request.get("symbols")
        if raw_symbols is None and not request.get("symbol"):
            return None
        if raw_symbols is None:
            raw_symbols = [request["symbol"]]
        symbols: list[str] = []
        seen: set[str] = set()
        for item in raw_symbols:
            symbol = str(item).strip().upper()
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols or None

    def _minute_bar_sizes_from_payload(self, request: dict[str, Any]) -> list[str]:
        from quant_us.data.minute_quality_gate import SUPPORTED_MINUTE_BAR_SIZES

        raw_bar_sizes = request.get("bar_sizes")
        if raw_bar_sizes is None and request.get("bar_size"):
            raw_bar_sizes = [request["bar_size"]]
        elif isinstance(raw_bar_sizes, str):
            raw_bar_sizes = [item.strip() for item in raw_bar_sizes.split(",")]
        if raw_bar_sizes is None:
            return list(SUPPORTED_MINUTE_BAR_SIZES)

        bar_sizes: list[str] = []
        seen: set[str] = set()
        invalid: set[str] = set()
        for item in raw_bar_sizes:
            bar_size = str(item or "").strip().lower()
            if not bar_size:
                continue
            if bar_size not in SUPPORTED_MINUTE_BAR_SIZES:
                invalid.add(bar_size)
                continue
            if bar_size in seen:
                continue
            bar_sizes.append(bar_size)
            seen.add(bar_size)
        if invalid:
            raise ValueError(
                f"Unsupported minute bar sizes: {sorted(invalid)}. Allowed values: {list(SUPPORTED_MINUTE_BAR_SIZES)}"
            )
        if not bar_sizes:
            raise ValueError(
                f"At least one minute bar size is required. Allowed values: {list(SUPPORTED_MINUTE_BAR_SIZES)}"
            )
        return bar_sizes

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

    def data_quality_report(self, request: dict[str, Any]) -> dict[str, Any]:
        """Generate auditable minute quality gates for raw and cleaned US equity data."""
        from quant_us.data.minute_quality_gate import inspect_minute_data_quality_overview

        data_root = request.get("data_root", "data")
        symbols = self._optional_symbols_from_payload(request)
        bar_sizes = self._minute_bar_sizes_from_payload(request)
        lookback_trading_days = max(1, int(request.get("lookback_trading_days", 5)))
        root_subdirs = request.get("root_subdirs")
        if root_subdirs is None:
            root_subdirs = ("raw", "cleaned")
        if isinstance(root_subdirs, str):
            root_subdirs = [item.strip() for item in root_subdirs.split(",") if item.strip()]
        if not root_subdirs:
            raise ValueError("At least one root_subdir is required. Allowed values: ['raw', 'cleaned']")

        report = inspect_minute_data_quality_overview(
            data_root=Path(data_root),
            symbols=symbols,
            vendor=str(request.get("vendor", "yfinance")),
            asset_class=str(request.get("asset_class", "equity")),
            bar_sizes=bar_sizes,
            lookback_trading_days=lookback_trading_days,
            root_subdirs=root_subdirs,
        )
        return report.to_dict()

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

    def run_unified_backtest(self, request: dict[str, Any]) -> dict[str, Any]:
        data_root = Path(request.get("data_root") or "data")
        symbols = self._symbols_from_payload(request)
        data = DataLakeService(DataLakeConfig(data_root=data_root))

        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            frame = data.read_cleaned_bars(
                symbol=symbol,
                start=request["start"],
                end=request["end"],
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
            )
            if frame.empty and request.get("auto_sync", True):
                sync = data.sync_bars(
                    symbol=symbol,
                    start=request["start"],
                    end=request["end"],
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
                if sync.status != "completed":
                    raise ValueError(sync.error or f"Unable to sync {symbol}")
                frame = data.read_cleaned_bars(
                    symbol=symbol,
                    start=request["start"],
                    end=request["end"],
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
            frames.append(frame)

        if not frames or all(f.empty for f in frames):
            raise ValueError(f"No data loaded for symbols {symbols}")

        combined = pd.concat(frames, ignore_index=True)
        strategy_id = str(request.get("strategy_id", "trend_momentum"))
        strategy_params = dict(request.get("strategy_params", {}))
        strategy = build_strategy(strategy_id, strategy_params)

        runner = UnifiedBacktestRunner(
            config=UnifiedBacktestConfig(
                initial_cash=float(request.get("capital", 100_000.0)),
                commission_rate=float(request.get("commission_rate", 0.0001)),
                slippage_bps=float(request.get("slippage_bps", 1.0)),
            )
        )
        result = runner.run(
            strategies=[strategy],
            frame=combined,
        )

        equity_curve: list[dict[str, float | int]] = []
        drawdown_curve: list[dict[str, float | int]] = []
        peak = result.ledger_curve.initial_cash
        for p in result.ledger_curve.points:
            # Skip placeholder timestamps (datetime.min used for empty fills)
            if p.timestamp_utc.year < 1970:
                continue
            ts = int(p.timestamp_utc.timestamp())
            equity_curve.append({"time": ts, "value": round(p.equity, 4)})
            peak = max(peak, p.equity)
            dd = (p.equity / peak - 1.0) * 100 if peak > 0 else 0.0
            drawdown_curve.append({"time": ts, "value": round(dd, 4)})

        # Build turnover report dict
        turnover_report_dict: dict[str, Any] | None = None
        if result.turnover_report is not None:
            tr = result.turnover_report
            turnover_report_dict = {
                "total_turnover": tr.total_turnover,
                "total_notional_traded": tr.total_notional_traded,
                "average_equity": tr.average_equity,
                "turnover_rate_pct": tr.turnover_rate_pct,
                "excessive_turnover_days": tr.excessive_turnover_days,
                "max_daily_turnover_pct": tr.max_daily_turnover_pct,
                "max_daily_turnover_pct_limit": tr.max_daily_turnover_pct_limit,
            }

        # Build cost summary from ledger curve
        cost_summary_dict: dict[str, Any] | None = None
        if result.ledger_curve.points:
            last = result.ledger_curve.points[-1]
            cost_summary_dict = {
                "total_commission": round(last.cumulative_fees, 4),
                "total_slippage_cost": round(last.cumulative_slippage_cost, 4),
                "total_cost": round(last.cumulative_fees + last.cumulative_slippage_cost, 4),
            }

        return {
            "run_id": result.run_id,
            "status": "completed",
            "summary": dict(result.summary),
            "equity_consistent": result.equity_consistent,
            "equity_consistency_msg": result.equity_consistency_msg,
            "order_count": len(result.orders),
            "fill_count": len(result.fills),
            "snapshot_count": len(result.snapshots),
            "event_count": len(result.event_driven.events),
            "ledger_final_equity": result.ledger_curve.final_equity,
            "ledger_total_fees": result.ledger_curve.total_fees,
            "ledger_curve_points": len(result.ledger_curve.points),
            "data_version": result.data_version,
            "strategy_version": result.strategy_version,
            "manifest_id": result.manifest_id,
            "determinism_verified": result.determinism_verified,
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_curve,
            "turnover_report": turnover_report_dict,
            "gap_skipped_bars": result.gap_skipped_bars,
            "cost_summary": cost_summary_dict,
            "diagnostics": {
                "symbol": request.get("symbol", "").upper(),
                "symbols": symbols,
                "bar_size": request.get("bar_size", "1d"),
                "strategy_id": strategy_id,
                "strategy_params": strategy_params,
                "data_root": str(data_root),
                "equity_consistent": result.equity_consistent,
            },
        }

    def run_paper_day(self, request: dict[str, Any]) -> dict[str, Any]:
        data_root = Path(request.get("data_root") or "data")
        symbols = self._symbols_from_payload(request)
        target_date = self._date_from_payload(request["target_date"])
        target_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
        target_end = datetime.combine(target_date, time.max, tzinfo=timezone.utc)
        data = DataLakeService(DataLakeConfig(data_root=data_root))

        all_bars: list = []
        for symbol in symbols:
            frame = data.read_cleaned_bars(
                symbol=symbol,
                start=target_start,
                end=target_end,
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
            )
            if frame.empty and request.get("auto_sync", True):
                sync = data.sync_bars(
                    symbol=symbol,
                    start=target_start,
                    end=target_end,
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
                if sync.status != "completed":
                    raise ValueError(sync.error or f"Unable to sync {symbol}")
                frame = data.read_cleaned_bars(
                    symbol=symbol,
                    start=target_start,
                    end=target_end,
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
            if not frame.empty:
                from quant_us.backtest.data_bridge import bars_from_dataframe
                all_bars.extend(bars_from_dataframe(frame, source=str(request.get("vendor", "yfinance"))))

        strategy_id = str(request.get("strategy_id", "trend_momentum"))
        strategy_params = dict(request.get("strategy_params", {}))
        strategy = build_strategy(strategy_id, strategy_params)

        loop = self._ensure_paper_loop(initial_cash=float(request.get("capital", 100_000.0)))
        day_result = loop.run_day(bars=all_bars, strategies=[strategy])

        return {
            "date": day_result.date,
            "starting_equity": day_result.starting_equity,
            "ending_equity": day_result.ending_equity,
            "daily_pnl": day_result.daily_pnl,
            "daily_return_pct": day_result.daily_return_pct,
            "orders_submitted": day_result.orders_submitted,
            "orders_filled": day_result.orders_filled,
            "orders_rejected": day_result.orders_rejected,
            "orders_cancelled": day_result.orders_cancelled,
            "kill_switch_triggered": day_result.kill_switch_triggered,
            "reconciliation_passed": day_result.reconciliation_passed,
            "reconciliation_diff": day_result.reconciliation_diff,
            "errors": day_result.errors,
        }

    def paper_status(self) -> dict[str, Any]:
        loop = self._ensure_paper_loop()
        status = loop.status_summary()
        return {
            "equity": status["account"]["equity"],
            "cash": status["account"]["cash"],
            "buying_power": status["account"]["buying_power"],
            "positions": status["positions"],
            "kill_switch_triggered": status["kill_switch"]["triggered"],
            "kill_switch_reason": status["kill_switch"]["reason"],
            "days_traded": status["days_traded"],
            "healthy": status["healthy"],
            "last_reconciliation_passed": status.get("last_reconciliation"),
        }

    def paper_daily_results(self) -> list[dict[str, Any]]:
        loop = self._ensure_paper_loop()
        return [
            {
                "date": r.date,
                "starting_equity": r.starting_equity,
                "ending_equity": r.ending_equity,
                "daily_pnl": r.daily_pnl,
                "daily_return_pct": r.daily_return_pct,
                "orders_submitted": r.orders_submitted,
                "orders_filled": r.orders_filled,
                "orders_rejected": r.orders_rejected,
                "orders_cancelled": r.orders_cancelled,
                "kill_switch_triggered": r.kill_switch_triggered,
                "reconciliation_passed": r.reconciliation_passed,
                "reconciliation_diff": r.reconciliation_diff,
                "errors": r.errors,
            }
            for r in loop.daily_results
        ]

    def run_paper_backtest(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run paper trading over a date range, processing each trading day sequentially."""
        data_root = Path(request.get("data_root") or "data")
        symbols = self._symbols_from_payload(request)
        data = DataLakeService(DataLakeConfig(data_root=data_root))

        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            frame = data.read_cleaned_bars(
                symbol=symbol,
                start=request["start"],
                end=request["end"],
                bar_size=request.get("bar_size", "1d"),
                vendor=request.get("vendor", "yfinance"),
                asset_class=request.get("asset_class", "equity"),
            )
            if frame.empty and request.get("auto_sync", True):
                sync = data.sync_bars(
                    symbol=symbol,
                    start=request["start"],
                    end=request["end"],
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
                if sync.status != "completed":
                    raise ValueError(sync.error or f"Unable to sync {symbol}")
                frame = data.read_cleaned_bars(
                    symbol=symbol,
                    start=request["start"],
                    end=request["end"],
                    bar_size=request.get("bar_size", "1d"),
                    vendor=request.get("vendor", "yfinance"),
                    asset_class=request.get("asset_class", "equity"),
                )
            frames.append(frame)

        if not frames or all(f.empty for f in frames):
            raise ValueError(f"No data loaded for symbols {symbols}")

        combined = pd.concat(frames, ignore_index=True)
        strategy_id = str(request.get("strategy_id", "trend_momentum"))
        strategy_params = dict(request.get("strategy_params", {}))
        strategy = build_strategy(strategy_id, strategy_params)

        self._paper_loop = None
        loop = self._ensure_paper_loop(initial_cash=float(request.get("capital", 100_000.0)))

        from quant_us.backtest.data_bridge import bars_from_dataframe
        all_bars = bars_from_dataframe(combined, source=str(request.get("vendor", "yfinance")))

        daily_bars: dict[date, list] = {}
        for bar in all_bars:
            try:
                bar_date = bar.timestamp_utc.date()
            except Exception:
                continue
            if bar_date not in daily_bars:
                daily_bars[bar_date] = []
            daily_bars[bar_date].append(bar)

        daily_results: list[dict[str, Any]] = []
        total_pnl = 0.0
        active = True
        for day in sorted(daily_bars):
            if not active:
                break
            bars = daily_bars[day]
            try:
                result = loop.run_day(bars=bars, strategies=[strategy])
                total_pnl += result.daily_pnl
                daily_results.append({
                    "date": day.isoformat(),
                    "starting_equity": result.starting_equity,
                    "ending_equity": result.ending_equity,
                    "daily_pnl": result.daily_pnl,
                    "daily_return_pct": result.daily_return_pct,
                    "orders_submitted": result.orders_submitted,
                    "orders_filled": result.orders_filled,
                    "orders_rejected": result.orders_rejected,
                    "orders_cancelled": result.orders_cancelled,
                    "kill_switch_triggered": result.kill_switch_triggered,
                    "reconciliation_passed": result.reconciliation_passed,
                    "reconciliation_diff": result.reconciliation_diff,
                    "errors": result.errors,
                })
                if result.kill_switch_triggered:
                    active = False
            except Exception as exc:
                daily_results.append({
                    "date": day.isoformat(),
                    "error": str(exc),
                })

        status = loop.status_summary()
        return {
            "status": "completed",
            "days_processed": len(daily_results),
            "total_pnl": total_pnl,
            "final_equity": status["account"]["equity"],
            "healthy": loop.is_healthy(),
            "kill_switch_triggered": loop.kill_switch.triggered,
            "daily_results": daily_results,
        }

    def reset_paper_loop(self) -> dict[str, str]:
        self._paper_loop = None
        return {"status": "reset", "message": "Paper trading loop cleared. Next run will reinitialize."}
