#!/usr/bin/env python3
"""Run BTCUSD spot strategy comparison across US-accessible data sources."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.data_management import (
    DataSyncSpec,
    MarketDataRepository,
    MarketDataService,
    interval_to_milliseconds,
    to_milliseconds,
)
from quant_us.backtest.crypto_event import run_crypto_event_backtest


DEFAULT_DB_PATH = Path("data/btc_us_spot_research.sqlite")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_us_spot_source_comparison/latest")
DEFAULT_REPORT = Path("docs/reports/quantstation_vnext_btc_us_spot_source_comparison_20260523.html")
DEFAULT_START = "2024-01-01T00:00:00Z"
DEFAULT_END = "2026-05-12T00:00:00Z"
DEFAULT_INTERVAL = "1h"
SOURCES = (
    {"id": "coinbase", "exchange": "coinbase_spot", "symbol": "BTCUSD", "label": "Coinbase 现货（美国）"},
    {"id": "kraken", "exchange": "kraken_spot", "symbol": "BTCUSD", "label": "Kraken 现货（美国可访问）"},
)
STRATEGIES = (
    "btc_low_turnover_trend",
    "btc_trend_pullback",
    "btc_vol_breakout",
    "btc_regime_trend",
    "btc_low_turnover_breakout",
    "btc_compression_breakout",
    "btc_capitulation_rebound",
)
EXCLUDED_STRATEGIES = (
    {
        "strategy_id": "btc_perp_dual_trend",
        "reason": "这是永续/可做空研究信号，不能用现货一致性直接推进永续。",
    },
    {
        "strategy_id": "btc_orderflow_pressure",
        "reason": "依赖可靠主动买卖量/订单流字段，Coinbase 和 Kraken 的现货 OHLC 源不可比。",
    },
)
COST_SCENARIOS = (
    {"name": "base", "label": "基础成本", "commission_multiplier": 1.0, "slippage_multiplier": 1.0},
    {"name": "fees_2x", "label": "手续费 2 倍", "commission_multiplier": 2.0, "slippage_multiplier": 1.0},
    {"name": "costs_2x", "label": "手续费和滑点 2 倍", "commission_multiplier": 2.0, "slippage_multiplier": 2.0},
    {"name": "tail_10x", "label": "极端成本 10 倍", "commission_multiplier": 10.0, "slippage_multiplier": 10.0},
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0004)
    parser.add_argument("--slippage-bps", type=float, default=4.0)
    args = parser.parse_args()

    start = _parse_utc(args.start)
    end = _parse_utc(args.end)
    db_path = Path(args.db_path)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(output_root / "tmp_full_manifests", ignore_errors=True)
    shutil.rmtree(output_root / "compact_manifests", ignore_errors=True)

    service = MarketDataService()
    sync_rows = [
        _sync_source(
            service=service,
            source=source,
            db_path=db_path,
            interval=args.interval,
            start=start,
            end=end,
        )
        for source in SOURCES
    ]

    loaded_frames = {
        source["id"]: _load_source_frame(
            db_path=db_path,
            exchange=source["exchange"],
            symbol=source["symbol"],
            interval=args.interval,
            start=start,
            end=end,
        )
        for source in SOURCES
    }
    common_index = loaded_frames[SOURCES[0]["id"]].index
    for source in SOURCES[1:]:
        common_index = common_index.intersection(loaded_frames[source["id"]].index)
    common_index = common_index.sort_values()
    if common_index.empty:
        raise RuntimeError("Coinbase/Kraken BTCUSD frames have no common timestamps")

    source_results = []
    for source in SOURCES:
        raw_frame = loaded_frames[source["id"]]
        frame = raw_frame.loc[common_index].copy()
        source_payload = {
            "source": source,
            "coverage": _coverage_payload(raw_frame, interval=args.interval, requested_start=start, requested_end=end),
            "aligned_coverage": _coverage_payload(frame, interval=args.interval, requested_start=start, requested_end=end),
            "strategies": [],
        }
        for strategy_id in STRATEGIES:
            row = _evaluate_strategy(
                source=source,
                frame=frame,
                strategy_id=strategy_id,
                interval=args.interval,
                start=start,
                end=end,
                db_path=db_path,
                output_root=output_root,
                capital=args.capital,
                commission_rate=args.commission_rate,
                slippage_bps=args.slippage_bps,
            )
            source_payload["strategies"].append(row)
        source_results.append(source_payload)

    comparison = _compare_sources(source_results)
    payload = {
        "schema_version": "btc_us_spot_source_comparison_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "research_only_no_paper_no_live",
        "symbol": "BTCUSD",
        "interval": args.interval,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "db_path": str(db_path),
        "strategies": list(STRATEGIES),
        "excluded_strategies": list(EXCLUDED_STRATEGIES),
        "cost_scenarios": list(COST_SCENARIOS),
        "sync": sync_rows,
        "sources": source_results,
        "comparison": comparison,
        "decision": _decision(comparison),
    }
    json_path = output_root / "btc_us_spot_source_comparison_report.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    html = _html_report(payload, json_path=json_path)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")
    print(json_path)
    print(report_path)


def _sync_source(
    *,
    service: MarketDataService,
    source: dict[str, str],
    db_path: Path,
    interval: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    result = service.sync_binance_klines(
        DataSyncSpec(
            exchange=source["exchange"],
            symbol=source["symbol"],
            interval=interval,
            start=start,
            end=end,
            db_path=str(db_path),
            closed_only=True,
        )
    )
    fallback: dict[str, Any] = {}
    if source["exchange"] == "kraken_spot" and result.rows_received == 0:
        fallback = _sync_kraken_recent_window_fallback(
            service=service,
            source=source,
            db_path=db_path,
            interval=interval,
            start=start,
            end=end,
        )
    coverage = service.coverage(db_path=str(db_path), exchange=source["exchange"], symbol=source["symbol"], interval=interval)
    return {
        "source": source,
        "status": fallback.get("status", result.status),
        "rows_received": fallback.get("rows_received", result.rows_received),
        "rows_written": fallback.get("rows_written", result.rows_written),
        "requests": int(result.requests) + int(fallback.get("requests", 0)),
        "note": fallback.get("note", ""),
        "coverage": coverage[0] if coverage else {},
    }


def _sync_kraken_recent_window_fallback(
    *,
    service: MarketDataService,
    source: dict[str, str],
    db_path: Path,
    interval: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Use Kraken's direct OHLC window when old REST pagination returns no rows.

    Kraken documents that the REST OHLC endpoint is limited; this fallback is
    intentionally labelled as a recent-window diagnostic, not full historical
    evidence.
    """

    start_ms = to_milliseconds(start)
    end_ms = to_milliseconds(end)
    raw_rows = service.kraken_client.fetch_klines(
        symbol=source["symbol"],
        interval=interval,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        limit=720,
    )
    records = [
        service._parse_kraken_kline(source["exchange"], source["symbol"], interval, row)
        for row in raw_rows
    ]
    records = [record for record in records if start_ms <= record.open_time_ms <= end_ms]
    rows_written = service.repository(str(db_path)).upsert_klines(records)
    return {
        "status": "completed_recent_window_fallback",
        "rows_received": len(records),
        "rows_written": rows_written,
        "requests": 1,
        "note": "Kraken REST OHLC 历史窗口有限，本次只抓到请求结束日前的 REST 近期窗口。",
    }


def _load_source_frame(
    *,
    db_path: Path,
    exchange: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    repository = MarketDataRepository(db_path=str(db_path))
    rows = repository.load_klines(
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        start_open_time_ms=to_milliseconds(start),
        end_open_time_ms=to_milliseconds(end),
    )
    if not rows:
        raise RuntimeError(f"No rows loaded for {exchange} {symbol} {interval}")
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    frame = frame.set_index("timestamp")
    columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]
    return frame[columns].astype(float)


def _evaluate_strategy(
    *,
    source: dict[str, str],
    frame: pd.DataFrame,
    strategy_id: str,
    interval: str,
    start: datetime,
    end: datetime,
    db_path: Path,
    output_root: Path,
    capital: float,
    commission_rate: float,
    slippage_bps: float,
) -> dict[str, Any]:
    base = _run_event(
        source=source,
        frame=frame,
        strategy_id=strategy_id,
        interval=interval,
        start=start,
        end=end,
        capital=capital,
        commission_rate=commission_rate,
        slippage_bps=slippage_bps,
        output_root=output_root,
        run_suffix="base",
    )
    base_summary = base["summary"]
    base_ledger_ok = bool(base["diagnostics"].get("ledger_equity_consistent", False))
    base_survives = bool(_research_survives(base_summary, max_drawdown_floor=-20.0) and base_ledger_ok)
    cost_rows = [
        {
            "name": "base",
            "label": "基础成本",
            "summary": base_summary,
            "ledger_equity_consistent": base_ledger_ok,
            "survives": base_survives,
        }
    ]
    fold_rows = []
    stress_evaluated = base_survives
    if not stress_evaluated:
        return {
            "strategy_id": strategy_id,
            "summary": base_summary,
            "direction": _direction(base_summary),
            "research_stable": False,
            "stress_evaluated": False,
            "skip_reason": "基础场景未通过，未继续消耗成本压力和分段回测预算",
            "cost_survival_rate_pct": 0.0,
            "fold_pass_rate_pct": 0.0,
            "tail_cost_survives": False,
            "cost_stress": cost_rows,
            "folds": fold_rows,
            "ledger_equity_consistent": base_ledger_ok,
            "compact_manifest_path": base["diagnostics"].get("compact_manifest_path", ""),
            "ledger_total_fees": base["diagnostics"].get("ledger_total_fees", 0.0),
            "trade_count": base_summary.get("trade_count", 0),
        }

    for scenario in COST_SCENARIOS[1:]:
        result = _run_event(
            source=source,
            frame=frame,
            strategy_id=strategy_id,
            interval=interval,
            start=start,
            end=end,
            capital=capital,
            commission_rate=commission_rate * float(scenario["commission_multiplier"]),
            slippage_bps=slippage_bps * float(scenario["slippage_multiplier"]),
            output_root=output_root,
            run_suffix=f"cost_{scenario['name']}",
        )
        summary = result["summary"]
        ledger_ok = bool(result["diagnostics"].get("ledger_equity_consistent", False))
        cost_rows.append(
            {
                "name": scenario["name"],
                "label": scenario["label"],
                "summary": summary,
                "ledger_equity_consistent": ledger_ok,
                "survives": bool(_research_survives(summary, max_drawdown_floor=-20.0) and ledger_ok),
            }
        )
    for index, fold_frame in enumerate(_fold_frames(frame, folds=4), start=1):
        fold_start = fold_frame.index[0].to_pydatetime()
        fold_end = fold_frame.index[-1].to_pydatetime()
        result = _run_event(
            source=source,
            frame=fold_frame,
            strategy_id=strategy_id,
            interval=interval,
            start=fold_start,
            end=fold_end,
            capital=capital,
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
            output_root=output_root,
            run_suffix=f"fold_{index}",
        )
        summary = result["summary"]
        ledger_ok = bool(result["diagnostics"].get("ledger_equity_consistent", False))
        fold_rows.append(
            {
                "fold": index,
                "start": fold_start.isoformat(),
                "end": fold_end.isoformat(),
                "summary": summary,
                "ledger_equity_consistent": ledger_ok,
                "pass": bool(_research_survives(summary, max_drawdown_floor=-15.0) and ledger_ok),
            }
        )
    stress_rows = [row for row in cost_rows if row["name"] != "base"]
    cost_survival_rate = round(sum(1 for row in stress_rows if row["survives"]) / max(1, len(stress_rows)) * 100.0, 4)
    fold_pass_rate = round(sum(1 for row in fold_rows if row["pass"]) / max(1, len(fold_rows)) * 100.0, 4)
    tail_row = next((row for row in stress_rows if row["name"] == "tail_10x"), None)
    return {
        "strategy_id": strategy_id,
        "summary": base_summary,
        "direction": _direction(base_summary),
        "research_stable": bool(
            base_survives
            and cost_survival_rate >= 75.0
            and fold_pass_rate >= 75.0
        ),
        "stress_evaluated": True,
        "skip_reason": "",
        "cost_survival_rate_pct": cost_survival_rate,
        "fold_pass_rate_pct": fold_pass_rate,
        "tail_cost_survives": bool(tail_row and tail_row["survives"]),
        "cost_stress": cost_rows,
        "folds": fold_rows,
        "ledger_equity_consistent": base_ledger_ok,
        "compact_manifest_path": base["diagnostics"].get("compact_manifest_path", ""),
        "ledger_total_fees": base["diagnostics"].get("ledger_total_fees", 0.0),
        "trade_count": base_summary.get("trade_count", 0),
    }


def _run_event(
    *,
    source: dict[str, str],
    frame: pd.DataFrame,
    strategy_id: str,
    interval: str,
    start: datetime,
    end: datetime,
    capital: float,
    commission_rate: float,
    slippage_bps: float,
    output_root: Path,
    run_suffix: str,
) -> dict[str, Any]:
    def loader(**_: Any) -> pd.DataFrame:
        return frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))].copy()

    run_id = f"{source['id']}_{strategy_id}_{run_suffix}"
    data_version = f"{source['exchange']}:{source['symbol']}:{interval}:{start.date()}:{end.date()}"
    strategy_version = f"{strategy_id}:us_spot_source_comparison_v1"
    tmp_root = output_root / "tmp_full_manifests"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{run_id}_", dir=tmp_root) as temp_dir:
        result = run_crypto_event_backtest(
            source="sqlite",
            symbol=source["symbol"],
            interval=interval,
            start=start,
            end=end,
            strategy_id=strategy_id,
            capital=capital,
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
            db_path="",
            data_version=data_version,
            strategy_version=strategy_version,
            market_loader=loader,
            manifest_root=temp_dir,
            run_id=run_id,
        )
        compact_path = _write_compact_manifest(
            output_root=output_root,
            result=result,
            run_id=run_id,
            source=source,
            interval=interval,
            start=start,
            end=end,
            data_version=data_version,
            strategy_version=strategy_version,
            capital=capital,
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
        )
        event_metrics = _closed_trade_event_metrics(result.unified.fills)
        summary = {
            **result.summary,
            "bar_profit_factor": result.summary.get("profit_factor", 0.0),
            "event_profit_factor": event_metrics["event_profit_factor"],
            "event_count": event_metrics["event_count"],
            "event_win_rate_pct": event_metrics["event_win_rate_pct"],
            "closed_trade_realized_pnl": event_metrics["closed_trade_realized_pnl"],
            "open_position_quantity": event_metrics["open_position_quantity"],
        }
        diagnostics = {**result.diagnostics, "compact_manifest_path": str(compact_path), "event_metrics": event_metrics}
        return {"summary": summary, "diagnostics": diagnostics}


def _closed_trade_event_metrics(fills: list[Any]) -> dict[str, Any]:
    position_qty = 0.0
    cost_basis = 0.0
    events: list[float] = []
    for fill in sorted(fills, key=lambda item: getattr(item, "filled_at", datetime.min.replace(tzinfo=timezone.utc))):
        side = str(getattr(getattr(fill, "side", ""), "value", getattr(fill, "side", ""))).lower()
        qty = abs(float(getattr(fill, "quantity", 0.0) or 0.0))
        price = float(getattr(fill, "price", 0.0) or 0.0)
        commission = float(getattr(fill, "commission", 0.0) or 0.0)
        if qty <= 0 or price <= 0:
            continue
        if side == "buy":
            cost_basis += qty * price + commission
            position_qty += qty
            continue
        if side != "sell" or position_qty <= 0:
            continue
        close_qty = min(qty, position_qty)
        avg_cost = cost_basis / position_qty if position_qty > 0 else 0.0
        commission_alloc = commission * (close_qty / qty)
        pnl = close_qty * price - commission_alloc - avg_cost * close_qty
        events.append(pnl)
        cost_basis -= avg_cost * close_qty
        position_qty -= close_qty
        if position_qty <= 1e-12:
            position_qty = 0.0
            cost_basis = 0.0

    gains = sum(value for value in events if value > 0)
    losses = abs(sum(value for value in events if value < 0))
    if losses > 0:
        event_pf = gains / losses
    elif gains > 0:
        event_pf = 999.0
    else:
        event_pf = 0.0
    return {
        "event_profit_factor": round(float(event_pf), 4),
        "event_count": len(events),
        "event_win_rate_pct": round((sum(1 for value in events if value > 0) / len(events) * 100.0), 4)
        if events
        else 0.0,
        "closed_trade_realized_pnl": round(float(sum(events)), 6),
        "open_position_quantity": round(float(position_qty), 10),
    }


def _write_compact_manifest(
    *,
    output_root: Path,
    result: Any,
    run_id: str,
    source: dict[str, str],
    interval: str,
    start: datetime,
    end: datetime,
    data_version: str,
    strategy_version: str,
    capital: float,
    commission_rate: float,
    slippage_bps: float,
) -> Path:
    manifest_dir = output_root / "compact_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    evidence = result.unified.evidence
    payload = {
        "schema_version": "btc_us_spot_research_backtest_manifest_v1",
        "scope": "research_only_not_for_promotion",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "event_driven",
        "pnl_source": "ledger_fills",
        "source": source,
        "symbol": source["symbol"],
        "interval": interval,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "data_version": data_version,
        "strategy_version": strategy_version,
        "strategy_params": {},
        "capital": capital,
        "cost_model": {
            "commission_rate": commission_rate,
            "commission_model": evidence.get("commission", {}),
        },
        "slippage_model": {
            "slippage_bps": slippage_bps,
            "slippage_model": evidence.get("slippage", {}),
        },
        "commit_hash": _git_commit_hash(),
        "summary": result.summary,
        "event_metrics": _closed_trade_event_metrics(result.unified.fills),
        "diagnostics": {
            "ledger_equity_consistent": result.diagnostics.get("ledger_equity_consistent"),
            "ledger_consistency_msg": result.diagnostics.get("ledger_consistency_msg"),
            "ledger_hash": result.diagnostics.get("ledger_hash"),
            "fills_hash": result.diagnostics.get("fills_hash"),
            "ledger_artifact_hash": evidence.get("ledger_artifact_hash"),
            "orders": result.diagnostics.get("orders"),
            "fills": result.diagnostics.get("fills"),
            "ledger_total_fees": result.diagnostics.get("ledger_total_fees"),
            "determinism_verified": result.diagnostics.get("determinism_verified"),
        },
    }
    path = manifest_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _fold_frames(frame: pd.DataFrame, *, folds: int) -> list[pd.DataFrame]:
    size = len(frame)
    fold_size = max(1, size // folds)
    rows = []
    for index in range(folds):
        start = index * fold_size
        end = size if index == folds - 1 else (index + 1) * fold_size
        fold = frame.iloc[start:end].copy()
        if len(fold) >= 48:
            rows.append(fold)
    return rows


def _research_survives(summary: dict[str, Any], *, max_drawdown_floor: float) -> bool:
    return bool(
        float(summary.get("total_return_pct", 0.0)) > 0.0
        and float(summary.get("event_profit_factor", 0.0)) >= 1.0
        and float(summary.get("max_drawdown_pct", -100.0)) > max_drawdown_floor
        and int(summary.get("event_count", 0)) >= 3
    )


def _direction(summary: dict[str, Any]) -> str:
    total_return = float(summary.get("total_return_pct", 0.0))
    profit_factor = float(summary.get("event_profit_factor", 0.0))
    if total_return > 0 and profit_factor > 1.0:
        return "positive"
    if total_return < 0 and profit_factor < 1.0:
        return "negative"
    return "mixed"


def _compare_sources(source_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source = {row["source"]["id"]: {item["strategy_id"]: item for item in row["strategies"]} for row in source_results}
    comparison = []
    for strategy_id in STRATEGIES:
        coinbase = by_source.get("coinbase", {}).get(strategy_id)
        kraken = by_source.get("kraken", {}).get(strategy_id)
        if not coinbase or not kraken:
            continue
        same_direction = (
            coinbase["direction"] == kraken["direction"] and coinbase["direction"] in {"positive", "negative"}
        )
        both_stable = bool(coinbase["research_stable"] and kraken["research_stable"])
        comparison.append(
            {
                "strategy_id": strategy_id,
                "same_direction": same_direction,
                "direction_status": "一致" if same_direction else "不确定" if "mixed" in {coinbase["direction"], kraken["direction"]} else "不一致",
                "both_research_stable": both_stable,
                "coinbase_direction": coinbase["direction"],
                "kraken_direction": kraken["direction"],
                "coinbase_event_pf": coinbase["summary"]["event_profit_factor"],
                "kraken_event_pf": kraken["summary"]["event_profit_factor"],
                "coinbase_bar_pf": coinbase["summary"]["bar_profit_factor"],
                "kraken_bar_pf": kraken["summary"]["bar_profit_factor"],
                "coinbase_total_return_pct": coinbase["summary"]["total_return_pct"],
                "kraken_total_return_pct": kraken["summary"]["total_return_pct"],
                "coinbase_max_drawdown_pct": coinbase["summary"]["max_drawdown_pct"],
                "kraken_max_drawdown_pct": kraken["summary"]["max_drawdown_pct"],
                "coinbase_cost_survival_rate_pct": coinbase["cost_survival_rate_pct"],
                "kraken_cost_survival_rate_pct": kraken["cost_survival_rate_pct"],
                "coinbase_fold_pass_rate_pct": coinbase["fold_pass_rate_pct"],
                "kraken_fold_pass_rate_pct": kraken["fold_pass_rate_pct"],
                "coinbase": coinbase,
                "kraken": kraken,
            }
        )
    return comparison


def _decision(comparison: list[dict[str, Any]]) -> dict[str, Any]:
    both_stable = [row for row in comparison if row["both_research_stable"]]
    same_direction = [row for row in comparison if row["same_direction"]]
    positive_same_direction = [
        row
        for row in comparison
        if row["same_direction"] and row["coinbase_direction"] == "positive" and row["kraken_direction"] == "positive"
    ]
    return {
        "paper_allowed": False,
        "live_allowed": False,
        "perpetual_promotion_allowed": False,
        "continue_spot_research": bool(both_stable),
        "same_direction_count": len(same_direction),
        "positive_same_direction_count": len(positive_same_direction),
        "both_research_stable_count": len(both_stable),
        "recommended_next_strategies": [row["strategy_id"] for row in both_stable],
        "reason": "仅研究：现货源一致性只是诊断，不能替代永续合约证据门禁。",
    }


def _coverage_payload(
    frame: pd.DataFrame,
    *,
    interval: str,
    requested_start: datetime,
    requested_end: datetime,
) -> dict[str, Any]:
    expected = int((requested_end - requested_start).total_seconds() * 1000 // interval_to_milliseconds(interval)) + 1
    requested_index = pd.date_range(requested_start, requested_end, freq=interval, tz="UTC")
    actual_index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
    missing = requested_index.difference(actual_index)
    missing_head = max(0, int((actual_index[0] - pd.Timestamp(requested_start)).total_seconds() * 1000 // interval_to_milliseconds(interval))) if len(actual_index) else expected
    missing_tail = max(0, int((pd.Timestamp(requested_end) - actual_index[-1]).total_seconds() * 1000 // interval_to_milliseconds(interval))) if len(actual_index) else expected
    return {
        "rows": len(frame),
        "expected_rows": expected,
        "coverage_pct": round(len(frame) / max(1, expected) * 100.0, 4),
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "missing_rows": len(missing),
        "missing_head_rows": missing_head,
        "missing_tail_rows": missing_tail,
    }


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _git_commit_hash() -> str:
    proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.strip() or "unknown"


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _direction_label(value: Any) -> str:
    return {
        "positive": "正向",
        "negative": "负向",
        "mixed": "混合",
    }.get(str(value), str(value))


def _status_label(value: Any) -> str:
    return {
        "completed": "完成",
        "completed_recent_window_fallback": "完成（近期窗口）",
        "failed": "失败",
        "running": "运行中",
    }.get(str(value), str(value))


def _stress_text(row: dict[str, Any], key: str) -> str:
    if not row.get("stress_evaluated", False):
        return "未评估"
    return f"{_fmt(row[key])}%"


def _html_report(payload: dict[str, Any], *, json_path: Path) -> str:
    rows = "\n".join(
        f"<tr><td><code>{row['strategy_id']}</code></td>"
        f"<td>{row['direction_status']}</td>"
        f"<td>{'是' if row['both_research_stable'] else '否'}</td>"
        f"<td>{_direction_label(row['coinbase_direction'])} / {_direction_label(row['kraken_direction'])}</td>"
        f"<td>{_fmt(row['coinbase_event_pf'])} / {_fmt(row['kraken_event_pf'])}</td>"
        f"<td>{_fmt(row['coinbase_total_return_pct'])}% / {_fmt(row['kraken_total_return_pct'])}%</td>"
        f"<td>{_fmt(row['coinbase_max_drawdown_pct'])}% / {_fmt(row['kraken_max_drawdown_pct'])}%</td>"
        f"<td>{_stress_text(row['coinbase'], 'cost_survival_rate_pct')} / {_stress_text(row['kraken'], 'cost_survival_rate_pct')}</td>"
        f"<td>{_stress_text(row['coinbase'], 'fold_pass_rate_pct')} / {_stress_text(row['kraken'], 'fold_pass_rate_pct')}</td></tr>"
        for row in payload["comparison"]
    )
    coverage_rows = "\n".join(
        f"<tr><td>{source['source']['label']}</td><td>{source['coverage']['rows']}</td>"
        f"<td>{source['coverage']['coverage_pct']}%</td><td>{source['coverage']['missing_rows']}</td>"
        f"<td>{source['aligned_coverage']['rows']}</td><td>{source['coverage']['start']} - {source['coverage']['end']}</td></tr>"
        for source in payload["sources"]
    )
    sync_rows = "\n".join(
        f"<tr><td>{row['source']['label']}</td><td>{_status_label(row['status'])}</td><td>{row['rows_received']}</td>"
        f"<td>{row['rows_written']}</td><td>{row.get('note') or '无'}</td></tr>"
        for row in payload["sync"]
    )
    recommendations = payload["decision"]["recommended_next_strategies"]
    rec_text = "、".join(f"<code>{item}</code>" for item in recommendations) if recommendations else "暂无"
    excluded = "；".join(
        f"<code>{item['strategy_id']}</code>：{item['reason']}" for item in payload.get("excluded_strategies", [])
    )
    decision = payload["decision"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC 美国现货数据源策略对比</title>
  <style>
    body{{margin:0;background:#f5f7fb;color:#182230;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif;line-height:1.58}}
    header{{background:#162235;color:#fff;padding:24px 28px}} main{{max-width:1180px;margin:0 auto;padding:20px 16px 40px}}
    section{{background:#fff;border:1px solid #d8e0ea;border-radius:8px;margin-bottom:16px;padding:16px}}
    h1{{font-size:26px;margin:0 0 8px}} h2{{font-size:19px;margin:0 0 12px}}
    table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{border:1px solid #d8e0ea;padding:8px;text-align:left;vertical-align:top}} th{{background:#edf2f7}}
    code{{background:#eef2f7;border:1px solid #d7dee8;border-radius:5px;padding:1px 5px}} .bad{{color:#b42318}} .ok{{color:#157347}} .warn{{color:#a16207}}
    .callout{{border-left:4px solid #2563eb;background:#eff6ff;padding:10px 12px;border-radius:6px}} .callout.bad{{border-left-color:#b42318;background:#fff1f0}}
  </style>
</head>
<body>
<header>
  <h1>BTC 美国现货数据源策略对比</h1>
  <p>生成时间：{payload['generated_at']} | 范围：仅研究 | 样本：{payload['start']} 到 {payload['end']} | 周期：{payload['interval']}</p>
</header>
<main>
  <section>
    <h2>结论</h2>
    <div class="callout bad">
      当前结果只用于 BTC 现货研究诊断；不允许进入模拟盘或实盘，也不允许推进永续版本。现货源一致性不能替代永续合约的资金费率、交易所规则和手续费等级证据。
    </div>
    <p>方向一致策略数：<strong>{decision['same_direction_count']}</strong> / {len(payload['comparison'])}；双源同为正向的策略数：<strong>{decision['positive_same_direction_count']}</strong>；两个数据源同时达到研究稳定条件的策略数：<strong>{decision['both_research_stable_count']}</strong>。</p>
    <p>建议继续诊断的策略：{rec_text}</p>
    <p>未纳入本次现货对照的策略：{excluded}</p>
  </section>
  <section>
    <h2>数据覆盖</h2>
    <table><thead><tr><th>数据源</th><th>原始行数</th><th>按请求区间覆盖率</th><th>缺失行数</th><th>双源对齐后行数</th><th>原始样本范围</th></tr></thead><tbody>{coverage_rows}</tbody></table>
  </section>
  <section>
    <h2>数据源说明</h2>
    <table><thead><tr><th>数据源</th><th>同步状态</th><th>收到行数</th><th>写入行数</th><th>说明</th></tr></thead><tbody>{sync_rows}</tbody></table>
    <p>Kraken 官方提供完整历史 OHLCVT 下载包，但 REST OHLC 接口有历史窗口限制。本次先用 REST 近期窗口做诊断，不把它当作完整历史证据。</p>
  </section>
  <section>
    <h2>策略对比</h2>
    <table>
      <thead><tr><th>策略</th><th>方向是否一致</th><th>双源研究稳定</th><th>方向</th><th>事件盈利因子</th><th>总收益</th><th>最大回撤</th><th>成本压力通过率</th><th>分段通过率</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
  <section>
    <h2>判定规则</h2>
    <ul>
      <li>事件盈利因子：按闭合交易事件的已实现盈亏计算，不使用逐 K 线收益盈利因子冒充。</li>
      <li>方向：总收益大于 0 且事件盈利因子大于 1 记为正向；二者都弱记为负向；其余为混合。混合对混合不算方向一致。</li>
      <li>研究稳定：基础场景正收益、事件盈利因子不低于 1、最大回撤不低于 -20%、非 base 成本压力通过率不低于 75%、分段诊断通过率不低于 75%。</li>
      <li>分段诊断只是样本切片稳定性检查，不是模拟盘晋升所需的 walk-forward/OOS 证据。</li>
      <li>本报告不使用 Sharpe 作为主筛选条件。</li>
    </ul>
    <p>JSON 证据：<code>{json_path}</code></p>
  </section>
</main>
</body>
</html>
"""


if __name__ == "__main__":
    main()
