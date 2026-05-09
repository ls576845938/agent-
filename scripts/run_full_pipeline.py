#!/usr/bin/env python3
"""End-to-end quant pipeline: data ingestion -> backtest -> promotion gate -> paper-review handoff.

Usage:
    python scripts/run_full_pipeline.py --symbol AAPL --start 2020-01-01 --end 2024-12-31
    python scripts/run_full_pipeline.py --symbol AAPL --mode full --register

Stages:
    1. Data ingestion + manifest generation
    2. Event-driven backtest
    3. Promotion gate evaluation
    4. Paper review handoff (if gate passes; no trading is started)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_VALID_GATE_SOURCES = {"fixture", "sqlite", "auto", "yfinance", "alpaca"}


def _gate_source(source: str) -> str:
    if source in _VALID_GATE_SOURCES:
        return source
    raise ValueError(f"source must be one of {sorted(_VALID_GATE_SOURCES)}")


def run_pipeline(
    symbol: str = "AAPL",
    source: str = "yfinance",
    interval: str = "1d",
    start: str = "2020-01-01",
    end: str = "2024-12-31",
    capital: float = 100000.0,
    commission: float = 0.0001,
    slippage: float = 1.0,
    strategy: str = "trend_momentum",
    mode: str = "backtest",
    register: bool = False,
    data_db_path: str = "",
    data_root: str = "data",
) -> dict[str, Any]:
    """Run full quant pipeline end-to-end and return results dict.

    Parameters match the CLI flags from ``main()``.  Returns a dict with keys
    depending on *mode*:

    ``backtest``
        data_version, run_id, sharpe, equity_consistent, mode
    ``gate``
        above plus promotion_decision, promotion_next_stage, gate_result
    ``full``
        above plus paper_review_required/manual_review_required. It never starts paper trading.

    Stages that are not reached (because of a shallower *mode*) are simply
    omitted from the returned dict.
    """
    symbol = symbol.upper()
    results: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Stage 1: Data ingestion + manifest
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"STAGE 1: Data ingestion -- {symbol} {interval}")
    print(f"{'='*60}")
    from quant_us.data.connectors.us_equity_ingestion import USEquityIngestionConfig, USEquityIngestionPipeline

    ingest_config = USEquityIngestionConfig(
        source=source,
        symbols=[symbol],
        intervals=[interval],
        start=start,
        end=end,
        generate_manifest=True,
    )
    pipeline = USEquityIngestionPipeline(ingest_config)
    ingest_results = pipeline.run()
    for r in ingest_results:
        if r.error:
            print(f"  FAIL: {r.symbol} {r.interval} -- {r.error}")
            sys.exit(1)
        print(f"  {r.symbol} {r.interval}: {r.row_count} rows, data_version={r.data_version}")
        if getattr(r, "manifest_path", ""):
            print(f"    manifest: {r.manifest_path}")
    results["data_version"] = ingest_results[0].data_version if ingest_results else "unknown"
    results["data_manifest_path"] = getattr(ingest_results[0], "manifest_path", "") if ingest_results else ""

    # ------------------------------------------------------------------
    # Stage 2: Event-driven backtest
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"STAGE 2: Event-driven backtest -- {symbol}")
    print(f"{'='*60}")
    from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
    from quant_us.strategies.factory import build_strategy

    import pandas as pd
    parquet_root = (
        Path(data_root)
        / "raw"
        / f"vendor={source}"
        / "asset_class=equity"
        / f"bar_size={interval}"
        / f"symbol={symbol}"
    )
    frames = []
    for pq in sorted(parquet_root.glob("date=*.parquet")):
        frames.append(pd.read_parquet(pq))
    if not frames:
        print(f"  ERROR: No Parquet files found at {parquet_root}")
        sys.exit(1)
    frame = pd.concat(frames, ignore_index=True)
    print(f"  Loaded {len(frame)} bars from {parquet_root}")

    strategy_instance = build_strategy(strategy, {})

    unified_config = UnifiedBacktestConfig(
        initial_cash=capital,
        commission_rate=commission,
        slippage_bps=slippage,
        fill_ratio=0.95,
    )
    unified_runner = UnifiedBacktestRunner(config=unified_config)
    unified_result = unified_runner.run(
        strategies=[strategy_instance],
        frame=frame,
        data_version=results.get("data_version", ""),
    )

    print(f"  Run ID: {unified_result.run_id}")
    for key, val in unified_result.summary.items():
        print(f"  {key}: {val}")
    print(f"  Equity consistent: {unified_result.equity_consistent}")
    results["run_id"] = unified_result.run_id
    results["backtest_manifest_id"] = getattr(unified_result, "manifest_id", unified_result.run_id)
    results["backtest_manifest_path"] = str(Path(data_root) / "manifests" / f"run_{getattr(unified_result, 'manifest_id', unified_result.run_id)}.json")
    results["sharpe"] = str(unified_result.summary.get("sharpe_ratio", "N/A"))
    results["equity_consistent"] = unified_result.equity_consistent

    if mode == "backtest":
        print(f"\nPipeline complete (backtest only). Run ID: {unified_result.run_id}")
        results["mode"] = "backtest"
        return results

    # ------------------------------------------------------------------
    # Stage 3: Promotion gate
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"STAGE 3: Promotion gate -- {symbol}")
    print(f"{'='*60}")
    from backend.app.services.research_gate import ResearchPromotionGateService

    gate_request: dict[str, Any] = {
        "mode": "single",
        "source": _gate_source(source),
        "symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end,
        "capital": capital,
        "commission_rate": commission,
        "slippage": slippage,
        "leverage": 1.0,
        "position_basis": "equity",
        "strategy_id": strategy,
        "data_db_path": data_db_path,
        "register_experiment": register,
        "experiment_name": f"{symbol.lower()}_momentum_gate",
    }

    gate_service = ResearchPromotionGateService()
    gate_result = gate_service.evaluate(gate_request)

    print(f"  Decision: {gate_result['decision']}")
    print(f"  Next stage: {gate_result['next_stage']}")
    print(f"  Manifest ID: {gate_result.get('manifest_id', 'N/A')}")
    for gate in gate_result["gates"]:
        print(f"  Gate '{gate['name']}': {gate['status']} -- {gate['message']}")

    results["promotion_decision"] = gate_result["decision"]
    results["promotion_next_stage"] = gate_result["next_stage"]
    results["gate_result"] = gate_result

    if mode == "gate":
        results["mode"] = "gate"
        return results

    # ------------------------------------------------------------------
    # Stage 4: Paper review handoff (only if gate passes)
    # ------------------------------------------------------------------
    if gate_result["decision"] not in ("pass",):
        print(f"\nPromotion gate did not pass (decision={gate_result['decision']}). Skipping paper review handoff.")
        results["mode"] = "full"
        results["paper_skipped"] = True
        return results

    print(f"\n{'='*60}")
    print(f"STAGE 4: Paper review handoff -- {symbol}")
    print(f"{'='*60}")
    print("  RESULT: READY_FOR_MANUAL_PAPER_REVIEW")
    print("  No paper trading session was started by this script.")
    print("  Required next action: create/approve a paper review manually before any paper run.")
    print(f"  Evidence: data_manifest={results.get('data_manifest_path') or results.get('data_version')}")
    print(f"  Evidence: backtest_manifest={results.get('backtest_manifest_path')}")
    print(f"  Evidence: promotion_manifest={gate_result.get('manifest_id', 'N/A')}")

    results["paper_review_required"] = True
    results["manual_review_required"] = True
    results["paper_not_started"] = True

    results["mode"] = "full"
    print(f"\n{'='*60}")
    print("FULL PIPELINE COMPLETE")
    print(f"{'='*60}")
    for key, val in results.items():
        if key != "gate_result":
            print(f"  {key}: {val}")

    return results


def main() -> None:
    """CLI entry point -- parse args and delegate to ``run_pipeline()``."""
    parser = argparse.ArgumentParser(description="Run full quant pipeline end-to-end")
    parser.add_argument("--symbol", default="AAPL", help="Ticker symbol")
    parser.add_argument("--source", default="yfinance", help="Data source")
    parser.add_argument("--interval", default="1d", help="Bar interval")
    parser.add_argument("--start", default="2020-01-01", help="Start date")
    parser.add_argument("--end", default="2024-12-31", help="End date")
    parser.add_argument("--capital", type=float, default=100000.0, help="Initial capital")
    parser.add_argument("--commission", type=float, default=0.0001, help="Commission rate")
    parser.add_argument("--slippage", type=float, default=1.0, help="Slippage in bps")
    parser.add_argument("--strategy", default="trend_momentum", help="Strategy ID from the registry")
    parser.add_argument("--mode", default="backtest", choices=["backtest", "gate", "paper", "full"], help="Pipeline depth")
    parser.add_argument("--register", action="store_true", help="Register as experiment")
    parser.add_argument("--data-db-path", default="", help="SQLite DB path")
    parser.add_argument("--data-root", default="data", help="Data lake root directory")
    args = parser.parse_args()

    run_pipeline(
        symbol=args.symbol,
        source=args.source,
        interval=args.interval,
        start=args.start,
        end=args.end,
        capital=args.capital,
        commission=args.commission,
        slippage=args.slippage,
        strategy=args.strategy,
        mode=args.mode,
        register=args.register,
        data_db_path=args.data_db_path,
        data_root=args.data_root,
    )


if __name__ == "__main__":
    main()
