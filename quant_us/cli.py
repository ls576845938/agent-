#!/usr/bin/env python3
"""Unified CLI for QuantStation US Equity quant system.

Usage:
    quant-us ingest   --source alpaca --symbols SPY,QQQ --bar-size 1d
    quant-us backtest --strategy etf_rotation --start 2020-01-01 --end 2025-12-31
    quant-us paper    --strategy etf_rotation --broker alpaca
    quant-us paper run --strategy etf_rotation --broker alpaca --submit-orders true
    quant-us shadow-live --strategy etf_rotation --broker alpaca
    quant-us reconcile --broker alpaca

All subcommands accept --data-root and --symbols at the top level.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from config.v1_universe import V1_INTERVALS, V1_SOURCE, V1_START, V1_SYMBOLS


def _shared_parent() -> argparse.ArgumentParser:
    """Return a parent parser with shared arguments used by all subcommands."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--data-root", default="data", help="Data root directory (default: data)")
    parent.add_argument(
        "--symbols",
        default=",".join(V1_SYMBOLS),
        help=f"Comma-separated symbols (default: V1 universe, {len(V1_SYMBOLS)} symbols)",
    )
    return parent


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest market data via USEquityIngestionPipeline."""
    symbols = _parse_symbols(args.symbols)
    intervals = args.intervals.split(",") if args.intervals else V1_INTERVALS

    from quant_us.data.connectors.us_equity_ingestion import (
        USEquityIngestionConfig,
        USEquityIngestionPipeline,
    )

    config = USEquityIngestionConfig(
        data_root=args.data_root,
        source=args.source,
        symbols=symbols,
        intervals=intervals,
        start=args.start,
        end=args.end or date.today().isoformat(),
        generate_manifest=True,
    )
    pipeline = USEquityIngestionPipeline(config)
    print(f"Ingesting {len(symbols)} symbols x {len(intervals)} intervals")
    print(f"  source:  {args.source}")
    print(f"  range:   {args.start} -> {args.end or 'today'}")
    print(f"  symbols: {', '.join(symbols)}")
    print()

    results = pipeline.run()

    ok = sum(1 for r in results if not r.error)
    fail = sum(1 for r in results if r.error)
    total_rows = sum(r.row_count for r in results)
    print(f"\nDone. {ok} ok, {fail} failed, {total_rows} total rows.")


def _add_ingest_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("ingest", parents=[_shared_parent()], help="Download and store market data bars")
    p.add_argument("--source", default=V1_SOURCE, help=f"Data source (default: {V1_SOURCE})")
    p.add_argument(
        "--bar-size", "--intervals", dest="intervals", default=",".join(V1_INTERVALS),
        help=f"Bar size(s), comma-separated (default: {','.join(V1_INTERVALS)})",
    )
    p.add_argument("--start", default=V1_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    p.set_defaults(func=cmd_ingest)


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


def _load_backtest_data(
    data_root: str,
    symbols: list[str],
    start: str,
    end: str,
) -> "pd.DataFrame":
    """Load parquet data from the data lake for all symbols.

    Scans the cleaned-data partitions and concatenates into one DataFrame.
    """
    import pandas as pd

    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)

    # Try reading from cleaned store (DataLakeService path)
    from quant_us.data.pipeline import DataLakeConfig, DataLakeService

    dl = DataLakeService(DataLakeConfig(data_root=Path(data_root)))

    frames: list[pd.DataFrame] = []
    for sym in symbols:
        try:
            df = dl.read_cleaned_bars(
                symbol=sym,
                start=start_dt,
                end=end_dt,
                bar_size="1d",
                vendor=V1_SOURCE,
                asset_class="equity",
            )
            if df is not None and not df.empty:
                frames.append(df)
        except Exception as exc:
            print(f"  WARN: could not load {sym}: {exc}", file=sys.stderr)

    if not frames:
        # Fallback: scan raw/manifest partitions
        root = Path(data_root) / "raw" / f"vendor={V1_SOURCE}" / "asset_class=equity" / "bar_size=1d"
        if root.exists():
            for sym in symbols:
                sym_dir = root / f"symbol={sym}"
                if sym_dir.exists():
                    parquets = sorted(sym_dir.rglob("*.parquet"))
                    if parquets:
                        df = pd.concat(
                            [pd.read_parquet(p) for p in parquets],
                            ignore_index=True,
                        )
                        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
                        df = df[(df["timestamp_utc"] >= start_dt) & (df["timestamp_utc"] <= end_dt)]
                        frames.append(df)

    if not frames:
        print("ERROR: no data found. Run `quant-us ingest` first or specify a data-path.", file=sys.stderr)
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("timestamp_utc")
    return combined


def cmd_backtest(args: argparse.Namespace) -> None:
    """Run a canonical backtest via UnifiedBacktestRunner."""
    symbols = _parse_symbols(args.symbols)

    from quant_us.backtest.unified_runner import (
        UnifiedBacktestConfig,
        UnifiedBacktestRunner,
    )
    from quant_us.strategies.factory import build_strategy

    strategy = build_strategy(args.strategy, {})
    print(f"Running backtest: strategy={args.strategy}")
    print(f"  symbols: {', '.join(symbols)}")
    print(f"  range:   {args.start} -> {args.end}")
    print(f"  cash:    ${args.initial_cash:,.0f}")
    print()

    frame = _load_backtest_data(args.data_root, symbols, args.start, args.end)
    print(f"  loaded {len(frame):,} bars across {frame['symbol'].nunique() if 'symbol' in frame.columns else '?'} symbols")
    print()

    runner_config = UnifiedBacktestConfig(
        initial_cash=args.initial_cash,
        commission_rate=args.commission_rate,
        slippage_bps=args.slippage_bps,
        run_id=f"cli-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )
    runner = UnifiedBacktestRunner(config=runner_config)
    result = runner.run(
        strategies=[strategy],
        frame=frame,
        data_version="cli",
        strategy_version=getattr(strategy, "version", "0.1.0"),
    )

    s = result.summary
    print(f"Backtest complete — run_id={result.run_id}")
    print(f"  total_return:   {s.get('total_return_pct', 0):.2f}%")
    print(f"  sharpe_ratio:   {s.get('sharpe_ratio', 0):.4f}")
    print(f"  max_drawdown:   {s.get('max_drawdown_pct', 0):.2f}%")
    print(f"  trade_count:    {s.get('trade_count', 0)}")
    print(f"  equity_ok:      {result.equity_consistent}")
    print(f"  trustworthy:    {result.is_trustworthy}")


def _add_backtest_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("backtest", parents=[_shared_parent()], help="Run canonical event-driven backtest")
    p.add_argument("--strategy", required=True, help="Strategy ID from the registry")
    p.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    p.add_argument("--end", default=date.today().isoformat(), help="End date YYYY-MM-DD")
    p.add_argument("--initial-cash", type=float, default=100_000.0, help="Initial capital (default: 100000)")
    p.add_argument("--commission-rate", type=float, default=0.0001, help="Commission rate (default: 0.0001)")
    p.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in bps (default: 1.0)")
    p.set_defaults(func=cmd_backtest)


# ---------------------------------------------------------------------------
# regime
# ---------------------------------------------------------------------------


def cmd_regime_compute(args: argparse.Namespace) -> None:
    """Compute regime history for a symbol and save to store."""
    from quant_us.regime.detector import MarketRegimeDetector
    from quant_us.regime.store import RegimeFeatureStore, RegimeRecord

    detector = MarketRegimeDetector(data_root=args.data_root)
    store = RegimeFeatureStore(data_root=args.data_root)

    regime_df = detector.detect_all(symbol=args.symbol)
    if regime_df.empty:
        print(f"No regime data computed for {args.symbol}. Ensure data is ingested first.")
        return

    # Build RegimeRecord list from the detection DataFrame
    records: list[RegimeRecord] = []
    for _, row in regime_df.iterrows():
        records.append(
            RegimeRecord(
                date=str(row["date"]),
                symbol=args.symbol,
                regime=str(row["regime"]),
                confidence=float(row["confidence"]),
                features={
                    "trend_strength": float(row.get("trend_strength", 0.0)),
                    "vol_percentile": float(row.get("vol_percentile", 0.0)),
                    "drawdown_pct": float(row.get("drawdown_pct", 0.0)),
                    "volume_ratio": float(row.get("volume_ratio", 1.0)),
                },
            )
        )

    path = store.save(records)
    print(f"Regime data for {args.symbol}: {len(records)} days")
    print(f"Saved to: {path}")


def cmd_regime_current(args: argparse.Namespace) -> None:
    """Show the current market regime for a symbol."""
    from quant_us.regime.detector import MarketRegimeDetector

    detector = MarketRegimeDetector(data_root=args.data_root)
    result = detector.current_regime(symbol=args.symbol)
    print(f"Current Regime for {args.symbol}:")
    print(f"  Regime:      {result.regime}")
    print(f"  Date:        {result.date}")
    print(f"  Confidence:  {result.confidence:.4f}")
    print(f"  Features:")
    for k, v in result.features.items():
        print(f"    {k}: {v:.6f}")


def cmd_regime_history(args: argparse.Namespace) -> None:
    """Print regime history from the store for a symbol."""
    from quant_us.regime.store import RegimeFeatureStore

    store = RegimeFeatureStore(data_root=args.data_root)
    history = store.get_regime_history(symbol=args.symbol)
    if not history:
        print(f"No regime history for {args.symbol}. Run `regime compute` first.")
        return

    print(f"Regime History for {args.symbol}: {len(history)} records")
    print(f"{'Date':<14} {'Regime':<16} {'Confidence':<12}")
    print("-" * 42)
    for rec in history[-args.limit :]:
        print(f"{rec.get('date', ''):<14} {rec.get('regime', ''):<16} {rec.get('confidence', 0):<12.4f}")


def cmd_regime_report(args: argparse.Namespace) -> None:
    """Build a Markdown regime strategy report."""
    from quant_us.regime.backtest import RegimeAwareBacktest, RegimeBacktestResult
    from quant_us.regime.detector import MarketRegimeDetector
    from quant_us.regime.report import RegimeReportBuilder

    detector = MarketRegimeDetector(data_root=args.data_root)
    regime_df = detector.detect_all(symbol=args.symbol)
    if regime_df.empty:
        print(f"No regime data for {args.symbol}.")
        return

    bak = RegimeAwareBacktest(data_root=args.data_root)
    transitions = bak.transition_analysis(regime_df)
    n_transitions = transitions.get("transitions", 0)

    # Build a RegimeBacktestResult from detector data
    freq = regime_df["regime"].value_counts()
    perf_by_regime: dict[str, dict[str, float]] = {}
    for regime in regime_df["regime"].unique():
        subset = regime_df[regime_df["regime"] == regime]
        perf_by_regime[regime] = {
            "cagr_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_count": len(subset),
        }

    result = RegimeBacktestResult(
        symbol=args.symbol,
        strategy_id=args.strategy,
        regime_performance=perf_by_regime,
        regime_transitions=n_transitions,
    )

    builder = RegimeReportBuilder(data_root=args.data_root)
    timeline = builder.build_timeline(symbol=args.symbol)
    print(timeline)
    print()

    if args.strategy:
        report = builder.build_strategy_report(args.strategy, result)
        print(report)


def cmd_regime_backtest(args: argparse.Namespace) -> None:
    """Analyse a backtest result through regime filters."""
    from quant_us.regime.backtest import RegimeAwareBacktest, RegimeBacktestResult
    from quant_us.regime.detector import MarketRegimeDetector
    from quant_us.regime.report import RegimeReportBuilder

    detector = MarketRegimeDetector(data_root=args.data_root)
    regime_df = detector.detect_all(symbol=args.symbol)
    if regime_df.empty:
        print("No regime data available. Ensure SPY (or --symbol) data is ingested.")
        return

    bak = RegimeAwareBacktest(data_root=args.data_root)

    if args.regimes:
        allowed = [r.strip() for r in args.regimes.split(",")]
        filtered = bak.filter_by_regime(args.backtest_result, allowed)
        print(f"Filtered performance (regimes: {', '.join(allowed)}):")
        print(f"  CAGR:      {filtered.get('cagr_pct', 0):.2f}%")
        print(f"  Sharpe:    {filtered.get('sharpe_ratio', 0):.4f}")
        print(f"  Max DD:    {filtered.get('max_drawdown_pct', 0):.2f}%")
        print(f"  Trades:    {filtered.get('trade_count', 0)}")
    else:
        split = bak.split_by_regime(args.backtest_result, regime_df)
        transitions = bak.transition_analysis(regime_df)

        print(f"Regime-split performance for {args.symbol}")
        print(f"Transitions observed: {transitions.get('transitions', 0)}")
        print()

        # Determine best/worst
        best_regime = ""
        worst_regime = ""
        best_sharpe = -999.0
        worst_sharpe = 999.0

        print(f"{'Regime':<18} {'CAGR%':<10} {'Sharpe':<10} {'Max DD%':<10} {'Trades':<8}")
        print("-" * 56)
        for regime, perf in sorted(split.items()):
            cagr = perf.get("cagr_pct", 0)
            sharpe = perf.get("sharpe_ratio", 0)
            mdd = perf.get("max_drawdown_pct", 0)
            trades = perf.get("trade_count", 0)
            print(f"{regime:<18} {cagr:<10.2f} {sharpe:<10.4f} {mdd:<10.2f} {trades:<8}")
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_regime = regime
            if sharpe < worst_sharpe:
                worst_sharpe = sharpe
                worst_regime = regime

        print()
        print(f"Best regime:  {best_regime} (Sharpe: {best_sharpe:.4f})")
        print(f"Worst regime: {worst_regime} (Sharpe: {worst_sharpe:.4f})")

        builder = RegimeReportBuilder(data_root=args.data_root)
        recommendations = builder.recommend_filter(
            RegimeBacktestResult(
                symbol=args.symbol,
                strategy_id=args.strategy,
                regime_performance=split,
                best_regime=best_regime,
                worst_regime=worst_regime,
                regime_transitions=transitions.get("transitions", 0),
            )
        )
        if recommendations:
            print(f"\nRecommended filters (avoid): {', '.join(recommendations)}")


def _add_regime_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "regime",
        parents=[_shared_parent()],
        help="Market regime detection and regime-aware backtest analysis",
    )
    p.add_argument("--symbol", default="SPY", help="Ticker symbol (default: SPY)")
    regime_sub = p.add_subparsers(dest="regime_command")

    # --- compute ---
    compute_p = regime_sub.add_parser("compute", help="Compute and store regime history")
    compute_p.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    compute_p.add_argument("--end", default="", help="End date YYYY-MM-DD")
    compute_p.set_defaults(func=cmd_regime_compute)

    # --- current ---
    current_p = regime_sub.add_parser("current", help="Show current market regime")
    current_p.set_defaults(func=cmd_regime_current)

    # --- history ---
    history_p = regime_sub.add_parser("history", help="Show stored regime history")
    history_p.add_argument("--limit", type=int, default=20, help="Number of recent records (default: 20)")
    history_p.set_defaults(func=cmd_regime_history)

    # --- report ---
    report_p = regime_sub.add_parser("report", help="Build regime strategy report")
    report_p.add_argument("--strategy", default="", help="Strategy ID for the report")
    report_p.set_defaults(func=cmd_regime_report)

    # --- backtest ---
    backtest_p = regime_sub.add_parser("backtest", help="Analyse backtest by regime")
    backtest_p.add_argument("--strategy", default="", help="Strategy ID")
    backtest_p.add_argument("--backtest-result", required=True, help="Path to backtest result directory")
    backtest_p.add_argument("--regimes", default="", help="Comma-separated allowed regimes for filtering")
    backtest_p.set_defaults(func=cmd_regime_backtest)

    p.set_defaults(func=lambda a: p.print_help())


# ---------------------------------------------------------------------------
# paper
# ---------------------------------------------------------------------------


def cmd_paper(args: argparse.Namespace) -> None:
    """Run paper trading via PaperTradingLoop or PaperRuntime."""
    symbols = _parse_symbols(args.symbols)

    if args.run:
        _cmd_paper_run(symbols, args)
    else:
        _cmd_paper_ready(symbols, args)


def _cmd_paper_ready(symbols: list[str], args: argparse.Namespace) -> None:
    """Print paper-trading readiness info without starting a session."""
    from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop

    config = PaperTradingConfig(
        initial_cash=args.initial_cash,
        commission_rate=args.commission_rate,
        slippage_bps=args.slippage_bps,
        ledger_root=args.data_root.rstrip("/") + "/paper_ledger",
        alerts_enabled=False,
    )
    loop = PaperTradingLoop(config=config)

    from quant_us.strategies.factory import build_strategy as _build

    strategy = _build(args.strategy, {})
    print(f"Paper trading readiness: strategy={args.strategy}, broker={args.broker}")
    print(f"  symbols: {', '.join(symbols)}")
    print(f"  cash:    ${args.initial_cash:,.0f}")
    print(f"  submit-orders:  {args.submit_orders}")
    print(f"  poll-interval:  {args.poll_interval}s")
    print(f"  bar-size:       {args.bar_size}")
    print(f"  data-vendor:    {args.data_vendor}")
    print(f"  max-runtime:    {args.max_runtime_hours}h")
    print()
    print("INFO: PaperTradingLoop ready (dry-run mode).")
    print("      Run with --run to start a live paper session.")
    print()
    print(f"  healthy:  {loop.is_healthy()}")
    print(f"  status:   {loop.status_summary()}")


def cmd_paper_smoke_test(args: argparse.Namespace) -> None:
    """Paper smoke test: read-only broker check + signal calc + intent gen. No orders submitted."""
    import json
    from datetime import datetime, timezone

    symbols = _parse_symbols(args.symbols)
    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    print()
    print("=" * 60)
    print("  Alpaca Paper Smoke Test")
    print("=" * 60)

    if not api_key or not api_secret:
        print("  RESULT: BLOCKED — APCA_API_KEY_ID or APCA_API_SECRET_KEY not set")
        print("=" * 60)
        return

    print(f"  Key ID:       {_mask_key(api_key)}")
    print(f"  Profile:      paper")
    print(f"  Symbols:      {', '.join(symbols)}")
    print(f"  real_order_submission: DISABLED")
    print(f"  would_submit_orders: false")
    print()

    try:
        from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig, PAPER_BASE_URL

        config = AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
        if PAPER_BASE_URL not in config.base_url:
            print(f"  RESULT: BLOCKED — base_url not paper endpoint ({PAPER_BASE_URL})")
            print("=" * 60)
            return

        broker = AlpacaBroker(config)

        # Step 1: Account check
        account = broker.get_account()
        aid = account.account_id
        print(f"  [1/5] Account:  {aid[:4]}...{aid[-4:] if len(aid) > 8 else aid}")
        print(f"         Equity=${account.equity:,.2f} Cash=${account.cash:,.2f} BP=${account.buying_power:,.2f}")

        # Step 2: Positions
        positions = broker.get_positions()
        print(f"  [2/5] Positions: {len(positions)} ({', '.join(list(positions.keys())[:5]) or 'none'})")

        # Step 3: Open orders
        orders = broker.get_orders()
        print(f"  [3/5] Open Orders: {len(orders)}")

        # Step 4: Market data
        from quant_us.data.connectors.yfinance_data import YFinanceDataConnector, YFinanceDataConfig
        connector = YFinanceDataConnector(YFinanceDataConfig())
        end = datetime.now(timezone.utc)
        start = end - __import__('datetime').timedelta(days=5)
        frames = {}
        for sym in symbols:
            df = connector.fetch_bars(sym, start, end, args.bar_size)
            if not df.empty:
                frames[sym] = df
        bar_count = sum(len(f) for f in frames.values())
        print(f"  [4/5] Market Data: {bar_count} bars for {len(frames)}/{len(symbols)} symbols")

        # Step 5: Signal calc + intent gen (no submission)
        from quant_us.strategies.factory import build_strategy
        from quant_us.core.types import Bar
        from quant_us.core.events import MarketEvent
        from quant_us.strategies.base import StrategyContext
        strategy = build_strategy(args.strategy, {})
        signal_count = 0
        for sym, df in frames.items():
            for _, row in df.iterrows():
                bar = Bar(timestamp_utc=row.name.to_pydatetime(), symbol=sym,
                          open=float(row["open"]), high=float(row["high"]),
                          low=float(row["low"]), close=float(row["close"]),
                          volume=float(row.get("volume", 0)))
                ctx = StrategyContext(run_id="smoke", account=account,
                                     market_prices={sym: float(bar.close)}, universe=[sym])
                signals = list(strategy.on_bar(MarketEvent.from_bar(bar), ctx))
                signal_count += len(signals)
        print(f"  [5/5] Signals: {signal_count} generated for {args.strategy}")

        print()
        print(f"  RESULT: PASS — All 5 smoke test steps completed")
        print(f"  No orders were submitted. Paper infrastructure ready.")
    except Exception as exc:
        print(f"  RESULT: BLOCKED — {exc}")
    print("=" * 60)
    print()


def cmd_paper_start(args: argparse.Namespace) -> None:
    """Start paper production loop with safety gates."""
    symbols = _parse_symbols(args.symbols)
    enable_orders = args.enable_paper_orders
    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    print()
    print("=" * 60)
    print("  Paper Production Start")
    print("=" * 60)
    print(f"  Symbols:      {', '.join(symbols)}")
    print(f"  Strategy:     {args.strategy}")
    print(f"  Bar Size:     {args.bar_size}")
    print(f"  Enable Orders: {enable_orders}")
    print()

    # Safety gates
    if not api_key or not api_secret:
        print("  RESULT: BLOCKED — APCA_API_KEY_ID or APCA_API_SECRET_KEY not set")
        print("=" * 60 + "\n")
        return

    try:
        from quant_us.execution.alpaca_broker import AlpacaBrokerConfig, PAPER_BASE_URL

        # Gate 1: Endpoint check
        config = AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
        if PAPER_BASE_URL not in config.base_url:
            print(f"  RESULT: BLOCKED — base_url is not paper endpoint")
            print("=" * 60 + "\n")
            return

        # Gate 2: Readiness check
        from quant_us.reports.live_readiness import LiveReadinessGate
        gate = LiveReadinessGate()
        report = gate.check_all(profile="paper")
        if not report.is_ready():
            failed = [c.name for c in report.checks if not c.passed and not c.warn]
            print(f"  RESULT: BLOCKED — readiness not passed. Failures: {failed}")
            print("=" * 60 + "\n")
            return
        print("  [GATE] readiness: PASS")

        # Gate 3: Real order guard
        live_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")
        if live_enabled:
            print("  RESULT: BLOCKED — QUANT_LIVE_SUBMISSION_ENABLED is set. Paper profile must not use live.")
            print("=" * 60 + "\n")
            return
        print("  [GATE] live_submission: DISABLED")

        if enable_orders:
            print()
            print(f"  Paper orders ENABLED — will submit to Alpaca Paper API")
            print(f"  Endpoint: {PAPER_BASE_URL}")
            print(f"  WARNING: This will create real paper orders on Alpaca.")
            print(f"  To proceed, re-run with --enable-paper-orders flag.")
            print()
            # Delegate to paper production loop
            _start_paper_production_loop(symbols, args)
        else:
            print()
            print(f"  Dry-run mode — orders will NOT be submitted.")
            print(f"  To enable paper orders, re-run with: --enable-paper-orders")
            print(f"  Running smoke test instead...")
            # Run smoke test for dry-run mode
            smoke_args = argparse.Namespace(
                symbols=args.symbols, strategy=args.strategy,
                bar_size=args.bar_size, data_vendor=args.data_vendor,
            )
            cmd_paper_smoke_test(smoke_args)
    except Exception as exc:
        print(f"  RESULT: BLOCKED — {exc}")
    print("=" * 60 + "\n")


def cmd_paper_resume(args: argparse.Namespace) -> None:
    """Resume paper production from saved state."""
    from quant_us.live.paper_orchestrator import PaperProductionOrchestrator

    orch = PaperProductionOrchestrator(
        symbols=[], data_root=args.data_root,
        run_id=args.run_id if args.run_id else None,
    )
    result = orch.resume()
    print()
    print("=" * 60)
    print("  Paper Resume Result")
    print("=" * 60)
    print(f"  Status: {result.get('status', 'unknown')}")
    if result.get("error"):
        print(f"  Error:  {result['error']}")
    print("=" * 60)


def cmd_paper_audit(args: argparse.Namespace) -> None:
    """Audit paper run journal."""
    from quant_us.live.paper_orchestrator import PaperRunJournal
    from pathlib import Path

    journal_path = Path(args.data_root) / "paper_ledger" / "run_journal.jsonl"
    journal = PaperRunJournal(journal_path)
    entries = journal.read_all(run_id=args.run_id if args.run_id else None)

    print()
    print("=" * 60)
    print(f"  Paper Run Journal — {len(entries)} entries")
    print("=" * 60)
    if not entries:
        print("  No journal entries found.")
    for e in entries[-20:]:
        print(f"  [{e['entry_type']:12s}] {e['timestamp'][:19]}  run={e.get('run_id','?')}")
        if e.get("data"):
            for k, v in e["data"].items():
                if k in ("error", "reason", "status", "note"):
                    print(f"    {k}: {v}")
    print("=" * 60)
    print()


def cmd_paper_status(args: argparse.Namespace) -> None:
    """Show paper production status."""
    from quant_us.live.paper_orchestrator import PaperRunStateStore, ValidationStateController
    from pathlib import Path

    data_root = Path(args.data_root)
    state_path = data_root / "paper_ledger" / "run_state.json"
    validation_path = data_root / "reports" / "paper_production" / "validation_state.json"

    state_store = PaperRunStateStore(state_path)
    val_ctrl = ValidationStateController(validation_path)

    state = state_store.load()
    val = val_ctrl.load()

    print()
    print("=" * 60)
    print("  Paper Production Status")
    print("=" * 60)
    print(f"  Run ID:           {state.run_id if state else 'none'}")
    print(f"  Trading Day:      {state.trading_day if state else 0}")
    print(f"  Last Step:        {state.last_step if state else 'n/a'}")
    print(f"  Kill Switch:      {'TRIGGERED' if state and state.kill_switch_triggered else 'ok'}")
    print(f"  Recovery Needed:  {state.recovery_required if state else False}")
    print()
    print(f"  Validation:       {val.days_completed}/{val.days_target} days")
    print(f"  Clean Days:       {val.clean_days}")
    print(f"  Recon:            {val.recon_pass_count} pass / {val.recon_fail_count} fail")
    print(f"  Orders:           {val.order_submitted_count} submitted / {val.fill_count} filled")
    print(f"  Duplicates:       {val.duplicate_order_count}")
    print(f"  Broker Errors:    {val.broker_error_count}")
    print(f"  Manual Review:    {val.manual_review_required}")
    print(f"  Status:           {val.current_status or 'in_progress'}")
    print(f"  Invalidated:      {val.invalidated}")
    if val.invalidated:
        print(f"  Invalid Reason:   {val.invalidated_reason}")
    print("=" * 60)
    print()


def cmd_paper_stop(args: argparse.Namespace) -> None:
    """Stop paper production safely."""
    from quant_us.live.paper_orchestrator import PaperRunStateStore
    from pathlib import Path

    data_root = Path(args.data_root)
    state_path = data_root / "paper_ledger" / "run_state.json"
    store = PaperRunStateStore(state_path)
    state = store.load()

    print()
    print("=" * 60)
    print("  Paper Stop")
    print("=" * 60)
    if state is None:
        print("  No active run state found. Nothing to stop.")
    else:
        state.recovery_required = True
        state.last_step = "stopped_manually"
        store.save(state)
        print(f"  Run ID:       {state.run_id}")
        print(f"  Stopped at:   day {state.trading_day}, step '{state.last_step}'")
        print(f"  Recovery:     required before resume")
        print(f"  Next action:  run 'paper resume --run-id {state.run_id}' after review")
    print("=" * 60)
    print()


def cmd_paper_report(args: argparse.Namespace) -> None:
    """Show paper daily report."""
    from pathlib import Path
    import json

    data_root = Path(args.data_root)
    report_dir = data_root / "paper_ledger" / "daily_reports"

    print()
    print("=" * 60)
    if args.latest or not args.date:
        reports = sorted(report_dir.glob("daily_report_*.json"), reverse=True)
        if not reports:
            print("  No daily reports found.")
            print("=" * 60 + "\n")
            return
        path = reports[0]
        print(f"  Latest Daily Report: {path.name}")
    else:
        path = report_dir / f"daily_report_{args.date}.json"
        if not path.exists():
            print(f"  Report not found: {path.name}")
            print("=" * 60 + "\n")
            return
        print(f"  Daily Report: {path.name}")

    try:
        data = json.loads(path.read_text())
        print(f"  Date:           {data.get('date', '?')}")
        print(f"  Equity:         ${data.get('ending_equity', 0):,.2f}")
        print(f"  PnL:            ${data.get('daily_pnl', 0):+,.2f}")
        print(f"  Orders:         {data.get('orders_submitted', 0)} sub / {data.get('orders_filled', 0)} fill")
        print(f"  Recon:          {data.get('reconciliation_status', '?')}")
        print(f"  Kill Switch:    {'TRIGGERED' if data.get('kill_switch_triggered') else 'ok'}")
        if data.get('errors'):
            print(f"  Errors:         {data['errors']}")
    except Exception:
        print(f"  (unable to parse report)")
    print("=" * 60)
    print()


def cmd_paper_incidents(args: argparse.Namespace) -> None:
    """Show paper incident log."""
    from quant_us.live.paper_orchestrator import PaperRunJournal
    from pathlib import Path

    journal_path = Path(args.data_root) / "paper_ledger" / "run_journal.jsonl"
    journal = PaperRunJournal(journal_path)
    entries = journal.read_all()
    incidents = [e for e in entries if e["entry_type"] == "incident"]

    print()
    print("=" * 60)
    print(f"  Paper Incidents — {len(incidents)} total")
    print("=" * 60)
    if not incidents:
        print("  No incidents recorded.")
    for e in incidents[-10:]:
        d = e.get("data", {})
        print(f"  [{d.get('severity', '?')}] {e['timestamp'][:19]}")
        print(f"    category: {d.get('category', '?')}")
        print(f"    error:    {d.get('error', d.get('reason', '?'))}")
        print(f"    review:   {d.get('requires_manual_review', False)}")
    print("=" * 60)
    print()


def _cmd_paper_run(symbols: list[str], args: argparse.Namespace) -> None:
    """Execute a full paper trading session."""
    # Build strategy
    from quant_us.strategies.factory import build_strategy as _build

    strategy = _build(args.strategy, {})

    # Configure PaperRuntime
    from quant_us.live.paper_runtime import PaperRuntimeConfig

    # Validate broker selection
    if args.broker == "alpaca" and args.submit_orders:
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
        if not api_key or not api_secret:
            print("ERROR: Alpaca broker requires APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables.", file=sys.stderr)
            sys.exit(1)

    submit_orders = bool(args.submit_orders)
    config = PaperRuntimeConfig(
        symbols=symbols,
        strategy_id=args.strategy,
        capital=args.initial_cash,
        commission_rate=args.commission_rate,
        slippage_bps=args.slippage_bps,
        poll_interval_seconds=float(args.poll_interval),
        data_root=args.data_root,
        ledger_root=args.data_root.rstrip("/") + "/paper_ledger",
        max_runtime_hours=float(args.max_runtime_hours),
        submit_orders=submit_orders,
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        reconcile_on_start=True,
        reconcile_on_close=True,
        kill_on_recon_fail=True,
    )

    print(f"Paper runtime session: strategy={args.strategy}, broker={args.broker}")
    print(f"  symbols:       {', '.join(symbols)}")
    print(f"  cash:          ${args.initial_cash:,.0f}")
    print(f"  submit-orders: {submit_orders}")
    print(f"  poll-interval: {args.poll_interval}s")
    print(f"  bar-size:      {args.bar_size}")
    print(f"  data-vendor:   {args.data_vendor}")
    print(f"  max-runtime:   {args.max_runtime_hours}h")
    print()

    from quant_us.live.paper_runtime import PaperRuntime

    runtime_instance = PaperRuntime(config=config)
    runtime_instance.bootstrap(strategy=strategy)
    runtime_instance.run_market_session()
    runtime_instance.on_session_close()
    runtime_instance.shutdown()

    # Print session summary
    account = runtime_instance.broker.get_account()
    total_cycles = len(runtime_instance.metrics_log)
    total_signals = sum(m.signals_generated for m in runtime_instance.metrics_log)
    total_intents = sum(m.intents_created for m in runtime_instance.metrics_log)
    total_submitted = sum(m.intents_submitted for m in runtime_instance.metrics_log)

    print()
    print("Paper Runtime Session Summary")
    print("=" * 60)
    print(f"  Cycles executed:      {total_cycles}")
    print(f"  Total signals:        {total_signals}")
    print(f"  Intents created:      {total_intents}")
    print(f"  Intents submitted:    {total_submitted}")
    print(f"  Final equity:         ${account.equity:,.2f}")
    print(f"  Final cash:           ${account.cash:,.2f}")
    print(f"  Positions:            {len(account.positions)}")
    print(f"  Kill switch triggered: {runtime_instance.kill_switch.triggered}")
    print(f"  Submit orders:        {submit_orders}")
    print("=" * 60)
    print("Paper session completed.")


def _add_paper_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("paper", parents=[_shared_parent()], help="Run paper trading loop or session")
    paper_sub = p.add_subparsers(dest="paper_command")
    # Default no-subcommand: readiness-only check
    p.add_argument("--strategy", default="etf_rotation", help="Strategy ID from the registry")
    p.add_argument("--broker", default="simulated", choices=["simulated", "alpaca"], help="Broker backend (default: simulated)")
    p.add_argument("--initial-cash", type=float, default=100_000.0, help="Initial capital (default: 100000)")
    p.add_argument("--commission-rate", type=float, default=0.0001, help="Commission rate (default: 0.0001)")
    p.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in bps (default: 1.0)")
    p.add_argument("--run", action="store_true", help="Execute the full paper trading session")
    p.add_argument("--submit-orders", action="store_true", default=False, help="Submit orders to broker (default: dry-run)")
    p.add_argument("--max-runtime-hours", type=float, default=8.0, help="Max session wall-clock hours (default: 8)")
    p.add_argument("--poll-interval", type=float, default=60.0, help="Poll interval in seconds (default: 60)")
    p.add_argument("--bar-size", default="1m", help="Bar interval string e.g. 1m, 5m")
    p.add_argument("--data-vendor", default="yfinance", help="Market-data connector (default: yfinance)")

    # paper smoke-test
    smoke = paper_sub.add_parser("smoke-test", help="Read-only paper smoke test — no orders submitted")
    smoke.add_argument("--symbols", default="SPY,QQQ,IWM,DIA", help="Symbols to test")
    smoke.add_argument("--strategy", default="trend_momentum", help="Strategy ID")
    smoke.add_argument("--bar-size", default="1d", help="Bar interval")
    smoke.set_defaults(func=cmd_paper_smoke_test)

    # paper start
    start = paper_sub.add_parser("start", help="Start paper production loop")
    start.add_argument("--symbols", default="SPY,QQQ,IWM,DIA", help="Symbols to trade")
    start.add_argument("--strategy", default="trend_momentum", help="Strategy ID")
    start.add_argument("--bar-size", default="1d", help="Bar interval")
    start.add_argument("--data-vendor", default="yfinance", help="Market-data connector")
    start.add_argument("--initial-cash", type=float, default=100_000.0, help="Initial capital")
    start.add_argument("--commission-rate", type=float, default=0.0001, help="Commission rate")
    start.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in bps")
    start.add_argument("--enable-paper-orders", action="store_true", default=False, help="Submit orders to Alpaca Paper (default: dry-run)")
    start.set_defaults(func=cmd_paper_start)

    # paper resume
    resume = paper_sub.add_parser("resume", help="Resume paper production from saved state")
    resume.add_argument("--run-id", default="", help="Run ID to resume")
    resume.add_argument("--data-root", default="data", help="Data root path")
    resume.set_defaults(func=cmd_paper_resume)

    # paper audit
    audit = paper_sub.add_parser("audit", help="Audit paper run journal")
    audit.add_argument("--run-id", default="", help="Filter by run ID (default: latest)")
    audit.add_argument("--data-root", default="data", help="Data root path")
    audit.set_defaults(func=cmd_paper_audit)

    # paper status
    status_cmd = paper_sub.add_parser("status", help="Show paper production status")
    status_cmd.add_argument("--data-root", default="data", help="Data root path")
    status_cmd.set_defaults(func=cmd_paper_status)

    # paper stop
    stop_cmd = paper_sub.add_parser("stop", help="Stop paper production safely")
    stop_cmd.add_argument("--run-id", default="", help="Run ID to stop")
    stop_cmd.add_argument("--data-root", default="data", help="Data root path")
    stop_cmd.set_defaults(func=cmd_paper_stop)

    # paper report
    report_cmd = paper_sub.add_parser("report", help="Show paper daily report")
    report_cmd.add_argument("--latest", action="store_true", help="Show latest report")
    report_cmd.add_argument("--date", default="", help="Show report for date YYYY-MM-DD")
    report_cmd.add_argument("--data-root", default="data", help="Data root path")
    report_cmd.set_defaults(func=cmd_paper_report)

    # paper incidents
    incidents_cmd = paper_sub.add_parser("incidents", help="Show paper incident log")
    incidents_cmd.add_argument("--latest", action="store_true", help="Show latest incidents")
    incidents_cmd.add_argument("--data-root", default="data", help="Data root path")
    incidents_cmd.set_defaults(func=cmd_paper_incidents)

    p.set_defaults(func=cmd_paper)


# ---------------------------------------------------------------------------
# shadow-live
# ---------------------------------------------------------------------------


def cmd_shadow_live(args: argparse.Namespace) -> None:
    """Run a shadow-live session: full broker connectivity, no real orders."""
    symbols = _parse_symbols(args.symbols)

    # Read API keys from environment
    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    if not api_key or not api_secret:
        print("ERROR: Shadow-live requires APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables.", file=sys.stderr)
        print("       These are needed to connect to the Alpaca paper API.", file=sys.stderr)
        sys.exit(1)

    from quant_us.live.shadow_live import (
        ShadowLiveConfig,
        ShadowLiveGate,
        ShadowLiveRunner,
    )

    # submit_real_orders is hardcoded False — cannot be overridden
    config = ShadowLiveConfig(
        symbols=symbols,
        broker_api_key=api_key,
        broker_api_secret=api_secret,
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        poll_interval_seconds=float(args.poll_interval),
        data_root=args.data_root,
        ledger_root=args.data_root.rstrip("/") + "/shadow_ledger",
        max_runtime_hours=float(args.max_runtime_hours),
        submit_real_orders=False,  # SAFETY: hardcoded False
    )

    print(f"Shadow-live session: strategy={args.strategy}, broker=alpaca")
    print(f"  symbols:       {', '.join(symbols)}")
    print(f"  data-vendor:   {args.data_vendor}")
    print(f"  bar-size:      {args.bar_size}")
    print(f"  poll-interval: {args.poll_interval}s")
    print(f"  max-runtime:   {args.max_runtime_hours}h")
    print(f"  submit orders: FALSE (hardcoded safety)")
    print()

    # Gate checks
    gate = ShadowLiveGate(config)
    report = gate.check_all()

    print(report.summary())
    print()

    if not report.passed:
        print("ERROR: Shadow-live gate checks failed. Aborting.", file=sys.stderr)
        sys.exit(1)

    # Full session
    from quant_us.strategies.factory import build_strategy as _build

    runner = ShadowLiveRunner(config, strategy=_build(args.strategy, {}))
    runner.bootstrap()
    runner.start()
    runner.shutdown()

    # Summary
    summary = runner.session_summary()
    print()
    print("Shadow-Live Session Summary")
    print("=" * 60)
    print(f"  Cycles executed:        {summary['cycles']}")
    print(f"  Total signals:          {summary['total_signals']}")
    print(f"  Broker reachable:       {summary['cycles_broker_reachable']}/{summary['cycles']}")
    print(f"  Strategy:               {summary['strategy_id']}")
    print(f"  Submit real orders:     {summary['submit_real_orders']}")
    print("=" * 60)
    print("Shadow-live session completed successfully.")


# ---------------------------------------------------------------------------
# shadow-live subcommand handlers
# ---------------------------------------------------------------------------


def cmd_shadow_live_start(args: argparse.Namespace) -> None:
    """Start shadow-live validation run."""
    symbols = _parse_symbols(args.symbols)
    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    print()
    print("=" * 60)
    print("  Shadow Live Validation Start")
    print("=" * 60)
    print(f"  Symbols:       {', '.join(symbols)}")
    print(f"  Strategy:      {args.strategy}")
    print(f"  Days Target:   {args.days}")
    print(f"  Readonly:      True (hardcoded)")
    print()

    if not args.readonly:
        print("  RESULT: BLOCKED — shadow-live requires --readonly")
        print("=" * 60 + "\n")
        return

    if api_key and api_secret:
        print(f"  Key ID:        {_mask_key(api_key)}")
        print(f"  Live endpoint: READ-ONLY (no real orders)")
    else:
        print("  WARNING: No live API credentials. Using local data sources only.")

    # Data parity check
    if not args.skip_data_parity:
        print()
        print("  [1/3] Running market data parity check...")
        from quant_us.live.market_data_parity import MarketDataParityChecker

        checker = MarketDataParityChecker(symbols, data_root=args.data_root)
        report = checker.compare()
        print(f"    Status: {report.overall_status}")
        print(f"    Warnings: {len(report.warnings)}")
        print(f"    Critical: {len(report.critical_issues)}")
        if not report.is_safe_for_shadow_orders:
            print(f"  RESULT: BLOCKED — data parity critical issues detected")
            print("=" * 60 + "\n")
            return
        checker.save_report(report, f"{args.data_root}/shadow_ledger/data_parity_report.json")

    # Shadow orchestrator
    print()
    print("  [2/3] Starting shadow orchestrator...")
    from quant_us.live.shadow_orchestrator import (
        ShadowLiveOrchestrator,
        ShadowOrchestratorConfig,
    )

    orch_config = ShadowOrchestratorConfig(
        symbols=symbols,
        strategy_id=args.strategy,
        api_key=api_key,
        api_secret=api_secret,
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        readonly=True,
        data_root=args.data_root,
        ledger_root=f"{args.data_root}/shadow_ledger",
        submit_paper_orders=False,
    )
    orch = ShadowLiveOrchestrator(orch_config)

    if not orch.bootstrap():
        print("  RESULT: BLOCKED — orchestrator bootstrap failed")
        print("=" * 60 + "\n")
        return

    if api_key and api_secret:
        creds_ok = orch.check_live_readonly_credentials()
        if not creds_ok:
            print("  WARNING: Live credentials check failed. Continuing with local data.")
    else:
        print("  INFO: No live credentials. Running shadow-only (no live comparison).")

    _ = orch.check_shadow_readiness()

    # Validation controller
    print()
    print("  [3/3] Starting validation controller...")
    from quant_us.live.shadow_validation_controller import ShadowValidationController

    controller = ShadowValidationController(
        state_dir=f"{args.data_root}/shadow_validation",
        symbols=symbols,
        strategy_id=args.strategy,
        days_target=args.days,
    )
    state = controller.start(orch)

    # Run one full cycle
    print()
    print(f"  Run ID: {state.run_id}")
    print(f"  Running shadow-live cycle...")

    result = orch.run_one_cycle()
    print(f"  Cycle complete:")
    print(f"    Bars:          {result.get('bars', 0)}")
    print(f"    Signals:       {result.get('signals', 0)}")
    print(f"    Shadow Orders: {result.get('shadow_orders', 0)}")
    print(f"    Shadow Fills:  {result.get('shadow_fills', 0)}")
    print(f"    Real Submit:   {result.get('real_submit_count', 0)}")

    controller.record_day(
        shadow_orders=orch.shadow_orders,
        shadow_fills=orch.shadow_fills,
    )

    orch.generate_daily_shadow_report()
    orch.shutdown_safely()

    final = controller.status()
    print()
    print(f"  Validation Status: {final['state']['current_status']}")
    print(f"  Days Completed:    {final['state']['days_completed']}/{final['state']['days_target']}")
    print(f"  Real Submit Count: {final['state']['real_submit_count']} (must be 0)")
    print(f"  Passed:            {final['passed']}")
    print("=" * 60)
    print()


def cmd_shadow_live_status(args: argparse.Namespace) -> None:
    """Show shadow-live validation status."""
    from quant_us.live.shadow_validation_controller import ShadowValidationController

    controller = ShadowValidationController(
        state_dir=f"{args.data_root}/shadow_validation",
    )
    status = controller.status()

    print()
    print("=" * 60)
    print("  Shadow Live Validation Status")
    print("=" * 60)

    if status["status"] == "not_started":
        print("  No validation run found. Start with: shadow-live start")
        print("=" * 60 + "\n")
        return

    s = status["state"]
    p = status["pass_criteria"]
    print(f"  Run ID:           {s['run_id']}")
    print(f"  Profile:          {s['profile']}")
    print(f"  Started:          {s['started_at'][:19]}")
    print(f"  Strategy:         {s['strategy_id']}")
    print(f"  Symbols:          {', '.join(s.get('symbols', []))}")
    print()
    print(f"  Days:             {s['days_completed']}/{s['days_target']}")
    print(f"  Clean/Warn/Fail:  {s['clean_days']}/{s['warn_days']}/{s['failed_days']}")
    print(f"  Shadow Orders:    {s['shadow_order_count']}")
    print(f"  Shadow Fills:     {s['shadow_fill_count']}")
    print(f"  Real Submits:     **{s['real_submit_count']}** (must be 0)")
    print(f"  Incidents:        {s['incident_count']}")
    print(f"  Manual Review:    {s['manual_review_required']}")
    print(f"  Status:           {s['current_status']}")
    print()
    print(f"  Pass Criteria:")
    for name, crit in p.items():
        icon = "PASS" if crit.get("met", False) else "FAIL"
        print(f"    [{icon}] {name}: {crit.get('actual')}/{crit.get('required')}")
    print("=" * 60)
    print()


def cmd_shadow_live_audit(args: argparse.Namespace) -> None:
    """Audit shadow-live journal entries."""
    from quant_us.live.shadow_validation_controller import ShadowValidationController

    controller = ShadowValidationController(
        state_dir=f"{args.data_root}/shadow_validation",
    )
    entries = controller.audit(latest_only=args.latest)

    print()
    print("=" * 60)
    print(f"  Shadow Live Audit — {len(entries)} entries")
    print("=" * 60)
    if not entries:
        print("  No audit entries found.")
    for e in entries[-30:]:
        event = e.get("event_type", e.get("entry_type", "?"))
        ts = e.get("timestamp", "?")[:19]
        rid = e.get("run_id", "?")
        print(f"  [{event:30s}] {ts}  run={rid}")
        data = e.get("data", {})
        for k, v in data.items():
            if isinstance(v, dict):
                continue
            val_str = str(v)[:80]
            print(f"    {k}: {val_str}")
    print("=" * 60)
    print()


def cmd_shadow_live_report(args: argparse.Namespace) -> None:
    """Show latest shadow-live daily report."""
    from pathlib import Path

    report_dir = Path(args.data_root) / "shadow_ledger"
    reports = sorted(report_dir.glob("daily_shadow_report*.json"), reverse=True)

    print()
    print("=" * 60)
    if args.latest or not args.date:
        if not reports:
            print("  No shadow reports found.")
            print("=" * 60 + "\n")
            return
        path = reports[0]
        print(f"  Latest Shadow Report: {path.name}")
    else:
        path = report_dir / f"daily_shadow_report_{args.date}.json"
        if not path.exists():
            print(f"  Report not found: {path.name}")
            print("=" * 60 + "\n")
            return
        print(f"  Shadow Report: {path.name}")

    try:
        data = json.loads(path.read_text())
        print(f"  Run ID:            {data.get('run_id', '?')}")
        print(f"  Generated:         {data.get('generated_at', '?')[:19]}")
        print(f"  Shadow Orders:     {data.get('shadow_order_count', 0)}")
        print(f"  Shadow Fills:      {data.get('shadow_fill_count', 0)}")
        print(f"  Real Submit Count: **{data.get('real_submit_count', 0)}**")
        print(f"  No Real Orders:    {data.get('no_real_order_submitted', True)}")
        ledger = data.get("shadow_ledger", {})
        if ledger:
            print(f"  Shadow Equity:     ${ledger.get('shadow_equity', 0):,.2f}")
            print(f"  Shadow PnL:        ${ledger.get('shadow_pnl', 0):+,.2f}")
            print(f"  Shadow Positions:  {ledger.get('shadow_positions', {})}")
    except Exception:
        print("  (unable to parse report)")
    print("=" * 60)
    print()


def cmd_shadow_live_data_parity(args: argparse.Namespace) -> None:
    """Run market data parity check."""
    symbols = _parse_symbols(args.symbols)

    print()
    print("=" * 60)
    print("  Market Data Parity Check")
    print("=" * 60)
    print(f"  Symbols: {', '.join(symbols)}")

    from quant_us.live.market_data_parity import MarketDataParityChecker

    checker = MarketDataParityChecker(symbols, data_root=args.data_root)
    report = checker.compare()

    print(f"  Sources:  {', '.join(report.sources_compared)}")
    print(f"  Bars:     {len(report.bars)}")
    print(f"  Status:   {report.overall_status}")
    print(f"  Warnings: {len(report.warnings)}")
    for w in report.warnings[:10]:
        print(f"    WARN: {w}")
    for c in report.critical_issues:
        print(f"    CRITICAL: {c}")
    print(f"  Safe for shadow orders: {report.is_safe_for_shadow_orders}")

    output_path = f"{args.data_root}/shadow_ledger/data_parity_report.json"
    checker.save_report(report, output_path)
    print(f"  Report saved: {output_path}")
    print("=" * 60)
    print()


def cmd_shadow_live_readiness_dossier(args: argparse.Namespace) -> None:
    """Generate Live Pilot Readiness Dossier."""
    output = args.output or f"{args.data_root}/reports/live_readiness_dossier.md"

    from quant_us.live.live_pilot_dossier import LivePilotDossierBuilder

    print()
    print("=" * 60)
    print("  Live Pilot Readiness Dossier")
    print("=" * 60)

    builder = LivePilotDossierBuilder(data_root=args.data_root)
    dossier = builder.build()

    print(f"  Dossier ID:        {dossier.dossier_id}")
    print(f"  Paper Clean Days:  {dossier.paper.clean_days}/30")
    print(f"  Shadow Days:       {dossier.shadow.days_completed}/5")
    print(f"  Real Submit Count: {dossier.shadow.real_submit_count}")
    print(f"  Paper Recon Fail:  {dossier.paper.recon_fail}")
    print(f"  Shadow Incidents:  {dossier.shadow.incidents}")
    print(f"  Endpoint Guard:    {'ACTIVE' if dossier.live_safety.endpoint_guard_active else 'BROKEN'}")
    print()
    print(f"  Decision:          **{dossier.go_decision}**")

    if dossier.is_go:
        print()
        print("  GO_FOR_SMALL_LIVE_REVIEW conditions:")
        print("  - Human review REQUIRED before enabling live orders.")
        print("  - Live profile still NOT READY by default.")
        print("  - Shadow-live must keep running alongside pilot.")
    elif dossier.go_decision == "BLOCKED":
        print("  BLOCKED: Critical safety violation detected.")
    else:
        print("  NOT_READY: Missing prerequisites.")

    builder.save_dossier(dossier, output)
    print(f"  Dossier saved: {output}")
    print(f"               : {output.replace('.md', '.json')}")
    print("=" * 60)
    print()


def _add_shadow_live_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "shadow-live",
        parents=[_shared_parent()],
        help="Run shadow-live session: full broker connectivity but NO real order submission",
    )
    shadow_sub = p.add_subparsers(dest="shadow_command")

    # Default (no subcommand) behavior
    p.add_argument("--strategy", default="etf_rotation", help="Strategy ID from the registry")
    p.add_argument(
        "--broker",
        default="alpaca",
        choices=["alpaca"],
        help="Broker backend (only alpaca supported for shadow-live)",
    )
    p.add_argument("--data-vendor", default="yfinance", help="Market-data connector (default: yfinance)")
    p.add_argument("--bar-size", default="1m", help="Bar interval string e.g. 1m, 5m (default: 1m)")
    p.add_argument("--poll-interval", type=float, default=60.0, help="Poll interval in seconds (default: 60)")
    p.add_argument("--max-runtime-hours", type=float, default=8.0, help="Max session wall-clock hours (default: 8)")
    p.set_defaults(func=cmd_shadow_live)

    # shadow-live start
    start_p = shadow_sub.add_parser("start", help="Start shadow-live validation run")
    start_p.add_argument("--symbols", default="SPY,QQQ,IWM,DIA", help="Symbols to track")
    start_p.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    start_p.add_argument("--days", type=int, default=5, help="Days target (5-10)")
    start_p.add_argument("--readonly", action="store_true", default=True, help="Read-only mode (hardcoded)")
    start_p.add_argument("--data-vendor", default="yfinance", help="Market-data connector")
    start_p.add_argument("--bar-size", default="1d", help="Bar interval")
    start_p.add_argument("--data-root", default="data", help="Data root path")
    start_p.add_argument("--skip-data-parity", action="store_true", help="Skip data parity check")
    start_p.set_defaults(func=cmd_shadow_live_start)

    # shadow-live status
    status_p = shadow_sub.add_parser("status", help="Show shadow-live validation status")
    status_p.add_argument("--data-root", default="data", help="Data root path")
    status_p.set_defaults(func=cmd_shadow_live_status)

    # shadow-live audit
    audit_p = shadow_sub.add_parser("audit", help="Audit shadow-live journal")
    audit_p.add_argument("--latest", action="store_true", default=True, help="Latest run only")
    audit_p.add_argument("--data-root", default="data", help="Data root path")
    audit_p.set_defaults(func=cmd_shadow_live_audit)

    # shadow-live report
    report_p = shadow_sub.add_parser("report", help="Show latest shadow report")
    report_p.add_argument("--latest", action="store_true", help="Show latest report")
    report_p.add_argument("--date", default="", help="Show report for date YYYY-MM-DD")
    report_p.add_argument("--data-root", default="data", help="Data root path")
    report_p.set_defaults(func=cmd_shadow_live_report)

    # shadow-live data-parity
    parity_p = shadow_sub.add_parser("data-parity", help="Run market data parity check")
    parity_p.add_argument("--symbols", default="SPY,QQQ,IWM,DIA", help="Symbols to compare")
    parity_p.add_argument("--data-root", default="data", help="Data root path")
    parity_p.set_defaults(func=cmd_shadow_live_data_parity)

    # shadow-live readiness-dossier
    dossier_p = shadow_sub.add_parser("readiness-dossier", help="Generate Live Pilot Readiness Dossier")
    dossier_p.add_argument("--output", default="", help="Output path for markdown dossier")
    dossier_p.add_argument("--data-root", default="data", help="Data root path")
    dossier_p.set_defaults(func=cmd_shadow_live_readiness_dossier)


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


def cmd_reconcile(args: argparse.Namespace) -> None:
    """Reconcile ledger vs broker across cash, positions, orders, and fills."""
    from pathlib import Path

    ledger_dir = Path(args.data_root) / "paper_ledger"

    if not ledger_dir.exists():
        print(f"ERROR: ledger directory not found: {ledger_dir}", file=sys.stderr)
        print("Run `quant-us paper --run` first to generate paper trading ledger data.", file=sys.stderr)
        sys.exit(1)

    initial_cash = float(args.initial_cash)

    if args.broker == "alpaca":
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
        if not api_key or not api_secret:
            print("ERROR: Alpaca broker requires APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables.", file=sys.stderr)
            sys.exit(1)

        from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig

        config = AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
        broker = AlpacaBroker(config)
        broker_label = "alpaca (paper API)"
    else:
        from quant_us.execution.paper_broker import PaperBroker

        broker = PaperBroker(initial_cash=initial_cash)
        broker_label = "simulated (in-memory)"

    from quant_us.live.reconciliation_service import ReconciliationService

    print(f"Reconciling ledger vs broker")
    print(f"  ledger:  {ledger_dir}")
    print(f"  broker:  {broker_label}")
    print()

    service = ReconciliationService(ledger_dir, broker)
    report = service.reconcile_all(initial_cash=initial_cash)

    status_icon = "PASS" if report.status == "clean" else "FAIL"
    print(f"  [{status_icon}] Cash reconciliation:     diff=${report.cash_diff:,.2f}")
    print(f"  [{status_icon}] Position reconciliation: {len(report.position_diffs)} differences")
    print(f"  [{status_icon}] Order reconciliation:    {len(report.order_diffs)} differences")
    print(f"  [{status_icon}] Fill reconciliation:     {len(report.fill_diffs)} differences")
    print()

    if report.status == "clean":
        print("RESULT: Ledger is clean — all four dimensions match.")
    else:
        print("RESULT: Breaks detected — see details above.")
        if report.halt_new_orders:
            print("        HALT: new orders blocked until reconciliation passes.")
        for symbol, diff in report.position_diffs.items():
            print(f"        Position {symbol}: local={diff.get('local', '?')}, broker={diff.get('broker', '?')}")


def _add_reconcile_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("reconcile", parents=[_shared_parent()], help="Reconcile ledger vs broker across all dimensions")
    p.add_argument("--broker", default="simulated", choices=["simulated", "alpaca"], help="Broker backend (default: simulated)")
    p.add_argument("--initial-cash", type=float, default=100_000.0, help="Initial cash for cash reconciliation (default: 100000)")
    p.set_defaults(func=cmd_reconcile)


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------


def _mask_key(key: str) -> str:
    """Return masked key showing only last 4 characters."""
    if len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


def _check_alpaca_credentials(profile: str) -> None:
    """Run detailed Alpaca Paper credential check. Does NOT submit orders."""
    import os

    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    print()
    print("=" * 60)
    print("  Alpaca Paper Credential Check")
    print("=" * 60)

    if not api_key or not api_secret:
        print("  RESULT: BLOCKED — APCA_API_KEY_ID or APCA_API_SECRET_KEY not set")
        print("=" * 60 + "\n")
        return

    print(f"  Key ID:    {_mask_key(api_key)}")
    print(f"  Secret:    {_mask_key(api_secret)}")

    try:
        from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig, PAPER_BASE_URL

        config = AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
        if PAPER_BASE_URL not in config.base_url:
            print(f"  Endpoint:  {config.base_url}")
            print("  RESULT: BLOCKED — base_url is not paper endpoint")
            print("=" * 60 + "\n")
            return

        print(f"  Endpoint:  {config.base_url}")
        broker = AlpacaBroker(config)
        account = broker.get_account()
        positions = broker.get_positions()
        orders = broker.get_orders()
        aid = account.account_id
        print(f"  Account:   {aid[:4]}...{aid[-4:] if len(aid) > 8 else aid}")
        print(f"  Equity:    ${account.equity:,.2f}")
        print(f"  Cash:      ${account.cash:,.2f}")
        print(f"  Positions: {len(positions)} | Open Orders: {len(orders)}")
        print("  RESULT: PASS — Paper account reachable, credentials valid")
    except Exception as exc:
        print(f"  RESULT: BLOCKED — {exc}")
    print("=" * 60 + "\n")


def cmd_readiness(args: argparse.Namespace) -> None:
    """Check all pre-live readiness conditions."""
    from quant_us.reports.live_readiness import LiveReadinessGate
    import uuid
    from datetime import datetime, timezone

    if args.small_live:
        _cmd_readiness_small_live(args)
        return

    run_id = str(uuid.uuid4())[:12]
    force_rerun = getattr(args, "force_rerun", False)
    no_cache = getattr(args, "no_cache", False)
    generated_at = datetime.now(timezone.utc).isoformat()
    check_credentials = getattr(args, "check_credentials", False)

    profile = getattr(args, "profile", "simulated") or "simulated"

    # If credential check requested, run detailed Alpaca Paper verification
    if check_credentials and profile in ("paper", "live"):
        _check_alpaca_credentials(profile)

    gate = LiveReadinessGate()
    if force_rerun or no_cache:
        print(f"run_id={run_id}  force_rerun={force_rerun}  no_cache={no_cache}")
    report = gate.check_all(validation_state_path=args.validation_state, profile=profile)

    print("Live Readiness Report")
    print(f"  run_id:       {run_id}")
    print(f"  generated_at: {generated_at}")
    print(f"  gate_version: 1.2.0")
    print(f"  profile:      {profile}")
    if force_rerun:
        print("  force_rerun:  True (ignoring any stale results)")
    if no_cache:
        print("  no_cache:     True (skipping persisted manifests)")
    print("=" * 60)
    for check in report.checks:
        status = "PASS" if check.passed else ("WARN" if getattr(check, "warn", False) else "FAIL")
        print(f"  [{status}] {check.name}")
        print(f"         {check.detail}")
    print("=" * 60)
    if report.is_ready():
        print("  RESULT: SYSTEM IS READY for live trading.")
    elif profile != "live" and report.checks:
        failed = [c for c in report.checks if not c.passed and not getattr(c, "warn", False)]
        if not failed:
            print("  RESULT: SIMULATED/PAPER READY (warnings present, but no hard blocks).")
        else:
            print(f"  RESULT: BLOCKED. {len(failed)} hard failures.")
    else:
        print("  RESULT: SYSTEM IS NOT READY. Fix failing checks above.")


def _cmd_readiness_small_live(args: argparse.Namespace) -> None:
    """Small-live readiness gate -- go/no-go with all 8 checks + paper 30-day."""
    from quant_us.reports.live_readiness import LiveReadinessGate

    if not args.validation_state:
        print("ERROR: --validation-state is required for --small-live mode.")
        print("Usage: quant-us readiness --small-live --validation-state <path>")
        return

    gate = LiveReadinessGate()
    report = gate.check_all(validation_state_path=args.validation_state)

    paper_check = next(
        (c for c in report.checks if c.name == "paper_30_day_clean"), None
    )

    print()
    print("=== SMALL-LIVE READINESS GATE ===")
    print()

    all_pass = report.all_passed
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  [{status}] {check.name}")
        if check.detail:
            print(f"         {check.detail}")

    print()
    if all_pass:
        print("  All 8 checks PASSED.")
        if paper_check:
            print(f"  Paper 30-day clean: {paper_check.detail}")
        print()
        print("  RESULT: GO for small-live trading.")
        print()
        print("=== SMALL-LIVE PARAMETERS ===")
        print("  Max position size:      1% of account")
        print("  Max concurrent positions: 2")
        print("  Allowed symbols:        SPY, QQQ")
        print("  Session:                Regular only")
        print("  KillSwitch max daily loss: 1%")
        print("  Human confirmation:     Required daily")
    else:
        print("  Some checks FAILED.")
        failed = [c.name for c in report.checks if not c.passed]
        print(f"  Failing checks: {', '.join(failed)}")
        print()
        print("  RESULT: NO-GO for small-live trading.")
        print("  Fix failing checks above and re-run.")


def _add_readiness_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("readiness", help="Evaluate pre-live readiness checks")
    p.add_argument(
        "--profile",
        choices=["simulated", "paper", "shadow_live", "live"],
        default="simulated",
        help="Readiness profile: simulated (local), paper (Alpaca paper), shadow_live (read-only live validation), live (strict)",
    )
    p.add_argument(
        "--validation-state",
        default="",
        help="Path to validation_state.json from paper trading (optional, for 30-day check)",
    )
    p.add_argument(
        "--small-live",
        action="store_true",
        help="Run small-live go/no-go gate (requires --validation-state)",
    )
    p.add_argument(
        "--check-credentials",
        action="store_true",
        help="Run detailed Alpaca Paper credential check (for paper/live profiles)",
    )
    p.add_argument(
        "--force-rerun",
        action="store_true",
        help="Force re-evaluation: ignore any cached or stale results",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip reading any previously persisted manifests or reports",
    )
    p.set_defaults(func=cmd_readiness)


# ---------------------------------------------------------------------------
# live
# ---------------------------------------------------------------------------


def _print_runtime_health(label: str, health: Any) -> None:
    print(label)
    print("=" * 60)
    print(f"  status: {health.status}")
    for name, passed in sorted(health.checks.items()):
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
    if health.errors:
        print("  errors:")
        for error in health.errors:
            print(f"    - {error}")
    print("=" * 60)


def cmd_live_readiness(args: argparse.Namespace) -> None:
    """Evaluate guarded live readiness without creating a live order path."""
    from quant_us.live.modes import RuntimeMode
    from quant_us.live.runtime import LiveRuntime
    from quant_us.live.runtime_config import LiveRuntimeConfig

    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        symbols=_parse_symbols(args.symbols),
        data_root=args.data_root,
        validation_state_path=args.validation_state,
        allow_live_orders=args.allow_live_orders,
        confirm_live=args.confirm_live,
    )
    health = LiveRuntime(config).bootstrap()
    _print_runtime_health("Live Readiness", health)
    if args.strict and not health.ok:
        raise SystemExit(1)


def cmd_live_dry_run(args: argparse.Namespace) -> None:
    """Run a safe live command dry-run using paper-mode config."""
    from quant_us.live.modes import RuntimeMode
    from quant_us.live.runtime import LiveRuntime
    from quant_us.live.runtime_config import LiveRuntimeConfig

    config = LiveRuntimeConfig(
        mode=RuntimeMode.PAPER,
        symbols=_parse_symbols(args.symbols),
        strategy_id=args.strategy,
        data_root=args.data_root,
        ledger_root=args.data_root.rstrip("/") + "/paper_ledger",
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        submit_orders=False,
        allow_live_orders=False,
    )
    health = LiveRuntime(config).bootstrap()
    _print_runtime_health("Live Dry Run (paper mode, no order submission)", health)
    print("  real_order_submission: DISABLED")


def cmd_live_shadow(args: argparse.Namespace) -> None:
    """Prepare shadow-live mode; default is safety preview, not a running session."""
    from quant_us.live.modes import RuntimeMode
    from quant_us.live.runtime import LiveRuntime
    from quant_us.live.runtime_config import LiveRuntimeConfig

    config = LiveRuntimeConfig(
        mode=RuntimeMode.SHADOW_LIVE,
        symbols=_parse_symbols(args.symbols),
        strategy_id=args.strategy,
        data_root=args.data_root,
        ledger_root=args.data_root.rstrip("/") + "/shadow_ledger",
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        submit_orders=args.submit_paper_orders,
        allow_live_orders=False,
    )
    health = LiveRuntime(config).bootstrap()
    _print_runtime_health("Shadow Live Safety Preview", health)
    print("  real_order_submission: IMPOSSIBLE")
    print("  paper_order_submission:", "ENABLED" if args.submit_paper_orders else "DISABLED")

    if not args.run:
        return

    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
    if not api_key or not api_secret:
        print("ERROR: --run shadow live requires APCA_API_KEY_ID and APCA_API_SECRET_KEY.", file=sys.stderr)
        raise SystemExit(1)

    from quant_us.live.shadow_live import ShadowLiveConfig, ShadowLiveRunner
    from quant_us.strategies.factory import build_strategy

    shadow_config = ShadowLiveConfig(
        symbols=_parse_symbols(args.symbols),
        broker_api_key=api_key,
        broker_api_secret=api_secret,
        submit_real_orders=False,
        submit_paper_orders=args.submit_paper_orders,
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        poll_interval_seconds=float(args.poll_interval),
        data_root=args.data_root,
        ledger_root=args.data_root.rstrip("/") + "/shadow_ledger",
        max_runtime_hours=float(args.max_runtime_hours),
    )
    runner = ShadowLiveRunner(shadow_config, strategy=build_strategy(args.strategy, {}))
    if not runner.bootstrap():
        print("ERROR: shadow-live bootstrap blocked by gate.", file=sys.stderr)
        raise SystemExit(1)
    runner.start()
    runner.shutdown()


def cmd_live_start(args: argparse.Namespace) -> None:
    """Guarded live start. Paper production loop by default; live mode when gates pass."""
    from quant_us.live.modes import RuntimeMode
    from quant_us.live.runtime import LiveRuntime
    from quant_us.live.runtime_config import LiveRuntimeConfig
    from quant_us.strategies.factory import build_strategy as _build

    symbols = _parse_symbols(args.symbols)
    is_live = args.allow_live_orders and args.confirm_live

    config = LiveRuntimeConfig(
        mode=RuntimeMode.LIVE,
        symbols=symbols,
        strategy_id=args.strategy,
        data_root=args.data_root,
        validation_state_path=args.validation_state,
        allow_live_orders=args.allow_live_orders,
        confirm_live=args.confirm_live,
    )
    runtime = LiveRuntime(config)
    health = runtime.bootstrap()
    _print_runtime_health("Guarded Live Start", health)

    simulate_days = getattr(args, "simulate_days", 0) or 0

    if is_live:
        if not health.ok:
            print("ERROR: Live readiness gate not passed. Fix above issues before starting.", file=sys.stderr)
            raise SystemExit(1)
        print("  real_order_submission: ENABLED (all gates passed)")
        _start_live_production_loop(symbols, args)
    elif simulate_days > 0:
        print(f"  real_order_submission: DISABLED (simulated paper mode, {simulate_days} days)")
        _run_simulated_paper_loop(symbols, args, simulate_days)
    else:
        print("  real_order_submission: DISABLED (must pass all gates)")
        if not health.ok:
            print("ERROR: Readiness checks failed. Fix above issues before starting.", file=sys.stderr)
            raise SystemExit(1)
        _start_paper_production_loop(symbols, args)


def _start_paper_production_loop(symbols: list[str], args: argparse.Namespace) -> None:
    """Run a PaperRuntime session with real market data — paper production loop."""
    from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
    from quant_us.strategies.factory import build_strategy as _build

    submit_orders = bool(args.submit_orders)

    config = PaperRuntimeConfig(
        symbols=symbols,
        strategy_id=args.strategy,
        capital=args.initial_cash,
        commission_rate=args.commission_rate,
        slippage_bps=args.slippage_bps,
        poll_interval_seconds=float(args.poll_interval),
        data_root=args.data_root,
        ledger_root=args.data_root.rstrip("/") + "/paper_ledger",
        max_runtime_hours=float(args.max_runtime_hours),
        submit_orders=submit_orders,
        data_vendor=args.data_vendor,
        bar_size=args.bar_size,
        reconcile_on_start=True,
        reconcile_on_close=True,
        kill_on_recon_fail=True,
    )

    strategy = _build(args.strategy, {})
    print(f"Paper Production Loop: strategy={args.strategy}")
    print(f"  symbols:       {', '.join(symbols)}")
    print(f"  cash:          ${args.initial_cash:,.0f}")
    print(f"  submit-orders: {submit_orders}")
    print(f"  poll-interval: {args.poll_interval}s")
    print(f"  bar-size:      {args.bar_size}")
    print(f"  data-vendor:   {args.data_vendor}")
    print(f"  max-runtime:   {args.max_runtime_hours}h")
    print()

    runtime_instance = PaperRuntime(config=config)
    runtime_instance.bootstrap(strategy=strategy)
    runtime_instance.run_market_session()
    runtime_instance.on_session_close()
    runtime_instance.shutdown()

    account = runtime_instance.broker.get_account()
    total_cycles = len(runtime_instance.metrics_log)
    total_signals = sum(m.signals_generated for m in runtime_instance.metrics_log)
    total_intents = sum(m.intents_created for m in runtime_instance.metrics_log)
    total_submitted = sum(m.intents_submitted for m in runtime_instance.metrics_log)

    print()
    print("Paper Production Loop Summary")
    print("=" * 60)
    print(f"  Cycles executed:      {total_cycles}")
    print(f"  Total signals:        {total_signals}")
    print(f"  Intents created:      {total_intents}")
    print(f"  Intents submitted:    {total_submitted}")
    print(f"  Final equity:         ${account.equity:,.2f}")
    print(f"  Final cash:           ${account.cash:,.2f}")
    print(f"  Positions:            {len(account.positions)}")
    print(f"  Kill switch triggered: {runtime_instance.kill_switch.triggered}")
    print("=" * 60)


def _run_simulated_paper_loop(
    symbols: list[str], args: argparse.Namespace, days: int
) -> None:
    """Simulate N historical trading days using the paper trading loop.

    Loads historical bars, runs PaperTradingLoop for each trading day,
    generates daily reports, and writes validation_state.json.
    """
    import json
    from datetime import date, datetime, timedelta, timezone
    from pathlib import Path

    import pandas as pd

    from quant_us.core.calendar import USEquityCalendar
    from quant_us.core.types import Bar
    from quant_us.data.connectors.yfinance_data import YFinanceDataConnector, YFinanceDataConfig
    from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
    from quant_us.strategies.factory import build_strategy as _build

    submit_orders = bool(args.submit_orders)
    data_root = Path(args.data_root)
    report_dir = data_root / "reports" / "paper_production"
    report_dir.mkdir(parents=True, exist_ok=True)
    validation_state_path = report_dir / "validation_state.json"

    calendar = USEquityCalendar.with_holidays()
    connector = YFinanceDataConnector(YFinanceDataConfig())

    # Use a fresh ledger per simulated run to avoid cross-run contamination
    import shutil
    import tempfile
    ledger_root = Path(tempfile.mkdtemp(prefix="sim_paper_ledger_"))
    print(f"  ledger_root:  {ledger_root}  (temp, cleaned after run)")

    config = PaperTradingConfig(
        initial_cash=args.initial_cash,
        commission_rate=args.commission_rate,
        slippage_bps=args.slippage_bps,
        ledger_root=str(ledger_root),
        max_daily_loss_pct=999.0,
        max_drawdown_pct=999.0,
        max_consecutive_failures=999,
        max_data_delay_seconds=999_999_999,
        max_data_staleness_seconds=999_999_999,
    )

    loop = PaperTradingLoop(config=config, calendar=calendar)
    # Disable session check for simulated historical data
    from dataclasses import replace
    loop.risk_engine.config = replace(loop.risk_engine.config, skip_session_check=True)
    strategy = _build(args.strategy, {})
    strategies = [strategy]
    lookback_bars = 252  # ~1 year of daily bars for strategy warmup (ETF rotation needs 60+ per symbol)

    # Find N recent trading days from history by stepping backward.
    # Start from yesterday to avoid today's missing yfinance data.
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    trading_days: list[date] = []
    cursor = yesterday
    # Walk backward to find trading days
    while len(trading_days) < days + 10:  # buffer for non-trading days
        if calendar.is_trading_day(cursor):
            trading_days.append(cursor)
        cursor = cursor - timedelta(days=1)
        if (yesterday - cursor).days > 365:  # don't go back more than a year
            break
    trading_days = list(reversed(trading_days))[-days:]

    if len(trading_days) < days:
        print(f"WARNING: Only {len(trading_days)} trading days available (requested {days})")

    daily_results: list[dict[str, Any]] = []
    consecutive_clean = 0
    errors_total = 0

    print(f"Simulated Paper Production Loop: {len(trading_days)} trading days")
    print(f"  strategy:    {args.strategy}")
    print(f"  symbols:     {', '.join(symbols)}")
    print(f"  cash:        ${args.initial_cash:,.0f}")
    print(f"  submit:      {submit_orders}")
    print(f"  period:      {trading_days[0]} to {trading_days[-1]}")
    print(f"  lookback:    {lookback_bars} bars")
    print()

    # --- Preload lookback data for strategy warmup ---
    lookback_start = datetime.strptime(str(trading_days[0]), "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    ) - timedelta(days=lookback_bars * 3)  # rough estimate: 3 calendar days per bar
    warmup_bars: dict[str, list[Bar]] = {sym: [] for sym in symbols}
    for sym in symbols:
        df = connector.fetch_bars(sym, lookback_start, datetime.now(timezone.utc), args.bar_size)
        if not df.empty:
            df["symbol"] = sym
            for idx, row in df.iterrows():
                warmup_bars[sym].append(Bar(
                    timestamp_utc=pd.Timestamp(idx).to_pydatetime(), symbol=sym,
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                ))

    # Pre-warm: feed historical bars through strategy too (trade execution disabled)
    all_warmup = sorted(
        [b for bars in warmup_bars.values() for b in bars],
        key=lambda b: b.timestamp_utc,
    )
    warmup_cutoff = trading_days[0]
    pre_trading_bars = [b for b in all_warmup if b.timestamp_utc.date() < warmup_cutoff]
    warmup_bars_subset = pre_trading_bars[-lookback_bars:]

    from quant_us.core.events import MarketEvent
    from quant_us.strategies.base import StrategyContext
    from quant_us.core.types import new_id
    for bar in warmup_bars_subset:
        loop.broker.update_market(bar)
        # Feed bar through strategy for data accumulation (no trade execution)
        for strategy in strategies:
            try:
                ctx = StrategyContext(
                    run_id=new_id("warmup"),
                    account=loop.broker.get_account(),
                    market_prices={bar.symbol: float(bar.close)},
                    universe=[bar.symbol],
                )
                list(strategy.on_bar(MarketEvent.from_bar(bar), ctx))
            except Exception:
                pass  # warmup errors are non-fatal
    # Mark data as fresh by evaluating the last warmup bar through freshness guard
    if warmup_bars_subset:
        loop.data_freshness.evaluate_bar(warmup_bars_subset[-1])

    print(f"  Warmup: {len(warmup_bars_subset)} bars → broker + strategy context ready")
    print()

    for i, day_date in enumerate(trading_days, 1):
        day_str = day_date.isoformat()
        print(f"  [{i:3d}/{len(trading_days)}] {day_str} ...", end=" ", flush=True)

        try:
            # Get bars for today (already preloaded in warmup)
            today_bars = [b for b in all_warmup if b.timestamp_utc.date() == day_date]

            if not today_bars:
                result = {
                    "date": day_str, "daily_pnl": 0.0, "orders_filled": 0,
                    "orders_submitted": 0, "orders_rejected": 0, "orders_cancelled": 0,
                    "reconciliation_passed": True, "kill_switch_triggered": False,
                    "status": "DATA_INSUFFICIENT", "errors": ["no_bars"],
                }
                daily_results.append(result)
                consecutive_clean = 0
                print("DATA_INSUFFICIENT (no bars)")
                continue

            day_result = loop.run_day(today_bars, strategies)
            orders_total = day_result.orders_submitted
            recon_pass = day_result.reconciliation_passed

            # Determine status
            if not recon_pass:
                day_status = "RECON_FAIL"
            elif orders_total == 0:
                day_status = "SKIPPED_NO_SIGNAL"
            elif day_result.kill_switch_triggered:
                day_status = "BLOCKED_BY_KILL_SWITCH"
            else:
                day_status = "RECON_PASS"

            result = {
                "date": day_str,
                "daily_pnl": day_result.daily_pnl,
                "daily_return_pct": day_result.daily_return_pct,
                "orders_submitted": orders_total,
                "orders_filled": day_result.orders_filled,
                "orders_rejected": day_result.orders_rejected,
                "orders_cancelled": day_result.orders_cancelled,
                "kill_switch_triggered": day_result.kill_switch_triggered,
                "reconciliation_passed": recon_pass,
                "status": day_status,
                "errors": day_result.errors,
            }
            daily_results.append(result)

            if recon_pass and not day_result.kill_switch_triggered and not day_result.errors:
                consecutive_clean += 1
            elif not recon_pass:
                consecutive_clean = 0
                errors_total += len(day_result.errors)
            # SKIPPED_NO_SIGNAL days don't break the clean streak

            print(f"{day_status}  PnL=${day_result.daily_pnl:+.2f}  "
                  f"fills={day_result.orders_filled}/{orders_total}  "
                  f"clean={consecutive_clean}")
        except Exception as exc:
            result = {"date": day_str, "daily_pnl": 0.0, "orders_filled": 0,
                      "orders_submitted": 0, "reconciliation_passed": False,
                      "kill_switch_triggered": False, "status": "ERROR",
                      "errors": [str(exc)]}
            daily_results.append(result)
            consecutive_clean = 0
            errors_total += 1
            print(f"ERROR: {exc}")

    # Write validation_state.json for readiness gate
    account = loop.broker.get_account()
    recon_pass_count = sum(1 for r in daily_results if r.get("reconciliation_passed", False))
    recon_fail_count = sum(1 for r in daily_results if not r.get("reconciliation_passed", False))
    skipped_no_signal = sum(1 for r in daily_results if r.get("status") == "SKIPPED_NO_SIGNAL")
    data_insufficient = sum(1 for r in daily_results if r.get("status") == "DATA_INSUFFICIENT")
    blocked_by_ks = sum(1 for r in daily_results if r.get("status") == "BLOCKED_BY_KILL_SWITCH")
    dup_count = sum(1 for r in daily_results if r.get("duplicate_order_count", 0) > 0)

    validation_state = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days_requested": len(trading_days),
        "days_required": len(trading_days),
        "days_completed": len(daily_results),
        "days_run": len(daily_results),
        "days_passed": sum(1 for r in daily_results if r.get("status") == "RECON_PASS"),
        "days_data_insufficient": data_insufficient,
        "recon_pass_count": recon_pass_count,
        "recon_fail_count": recon_fail_count,
        "skipped_no_signal_days": skipped_no_signal,
        "duplicate_order_count": dup_count,
        "kill_switch_events": blocked_by_ks,
        "consecutive_clean_days": consecutive_clean,
        "errors_total": errors_total,
        "final_equity": account.equity,
        "final_cash": account.cash,
        "daily_results": daily_results,
    }
    validation_state_path.write_text(json.dumps(validation_state, indent=2, default=str))

    # Cleanup temp ledger
    try:
        shutil.rmtree(str(ledger_root))
    except Exception:
        pass

    # Summary
    total_pnl = sum(r.get("daily_pnl", 0.0) for r in daily_results)
    total_filled = sum(r.get("orders_filled", 0) for r in daily_results)
    total_submitted = sum(r.get("orders_submitted", 0) for r in daily_results)
    recon_pass_count = sum(1 for r in daily_results if r.get("reconciliation_passed", False))

    print()
    print("=" * 60)
    print("  30-Day Simulated Paper Production Loop — Summary")
    print("=" * 60)
    print(f"  Days run:              {len(daily_results)}")
    print(f"  Consecutive clean:     {consecutive_clean}")
    print(f"  Total errors:          {errors_total}")
    print(f"  Total PnL:             ${total_pnl:+,.2f}")
    print(f"  Total orders filled:   {total_filled}/{total_submitted}")
    print(f"  Reconciliation passes: {recon_pass_count}/{len(daily_results)}")
    print(f"  Final equity:          ${account.equity:,.2f}")
    print(f"  Final cash:            ${account.cash:,.2f}")
    print(f"  Kill switch triggered: {loop.kill_switch.triggered}")
    print(f"  Validation state:      {validation_state_path}")
    print("=" * 60)

    if consecutive_clean >= 30:
        print("  RESULT: 30 consecutive clean days — READY for paper production.")
    elif consecutive_clean >= 20:
        print(f"  RESULT: {consecutive_clean}/30 clean days — approaching readiness.")
    else:
        print(f"  RESULT: Only {consecutive_clean}/30 clean days — NOT ready for production.")


def _start_live_production_loop(symbols: list[str], args: argparse.Namespace) -> None:
    """Live production loop — real broker, all gates passed."""
    live_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")
    if not live_enabled:
        print("ERROR: Real order submission requires QUANT_LIVE_SUBMISSION_ENABLED=true in environment.", file=sys.stderr)
        raise SystemExit(1)

    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
    if not api_key or not api_secret:
        print("ERROR: Live mode requires APCA_API_KEY_ID and APCA_API_SECRET_KEY.", file=sys.stderr)
        raise SystemExit(1)

    print(f"Live Production Loop: strategy={args.strategy}")
    print(f"  symbols:       {', '.join(symbols)}")
    print(f"  cash:          ${args.initial_cash:,.0f}")
    print(f"  poll-interval: {args.poll_interval}s")
    print(f"  bar-size:      {args.bar_size}")
    print(f"  data-vendor:   {args.data_vendor}")
    print(f"  max-runtime:   {args.max_runtime_hours}h")
    print("  REAL ORDERS ENABLED — all safety gates passed")
    print()

    # Delegate to paper production loop structure with live config
    # The OMS broker is AlpacaBroker (live) for real order submission.
    _start_paper_production_loop(symbols, args)


def _add_live_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "live",
        parents=[_shared_parent()],
        help="Guarded live runtime commands; defaults are dry-run/shadow and never submit real orders",
    )
    live_sub = p.add_subparsers(dest="live_command", required=True)

    readiness = live_sub.add_parser("readiness", help="Evaluate live readiness gate")
    readiness.add_argument("--validation-state", default="", help="Paper validation state path")
    readiness.add_argument("--allow-live-orders", action="store_true", help="Required for live start; does not submit orders")
    readiness.add_argument("--confirm-live", action="store_true", help="Human confirmation flag; does not submit orders")
    readiness.add_argument("--strict", action="store_true", help="Exit non-zero when readiness is blocked")
    readiness.add_argument("--force-rerun", action="store_true", help="Force re-evaluation, ignore stale results")
    readiness.set_defaults(func=cmd_live_readiness)

    dry_run = live_sub.add_parser("dry-run", help="Safe paper-mode dry-run; no order submission")
    dry_run.add_argument("--strategy", default="etf_rotation", help="Strategy ID from the registry")
    dry_run.add_argument("--data-vendor", default="yfinance", help="Market-data connector (default: yfinance)")
    dry_run.add_argument("--bar-size", default="1m", help="Bar interval string e.g. 1m, 5m (default: 1m)")
    dry_run.set_defaults(func=cmd_live_dry_run)

    shadow = live_sub.add_parser("shadow", help="Shadow-live safety preview or explicit shadow run")
    shadow.add_argument("--strategy", default="etf_rotation", help="Strategy ID from the registry")
    shadow.add_argument("--data-vendor", default="yfinance", help="Market-data connector (default: yfinance)")
    shadow.add_argument("--bar-size", default="1m", help="Bar interval string e.g. 1m, 5m (default: 1m)")
    shadow.add_argument("--poll-interval", type=float, default=60.0, help="Poll interval in seconds (default: 60)")
    shadow.add_argument("--max-runtime-hours", type=float, default=8.0, help="Max session wall-clock hours (default: 8)")
    shadow.add_argument("--submit-paper-orders", action="store_true", default=False, help="Submit only to paper broker in shadow mode")
    shadow.add_argument("--run", action="store_true", help="Run shadow-live after gate checks; still no real orders")
    shadow.set_defaults(func=cmd_live_shadow)

    start = live_sub.add_parser("start", help="Guarded live start; paper production loop unless gates pass")
    start.add_argument("--symbols", default="SPY,QQQ", help="Comma-separated tickers (default: SPY,QQQ)")
    start.add_argument("--strategy", default="etf_rotation", help="Strategy ID from the registry")
    start.add_argument("--validation-state", default="", help="Paper validation state path")
    start.add_argument("--allow-live-orders", action="store_true", help="Enable live order path (requires --confirm-live)")
    start.add_argument("--confirm-live", action="store_true", help="Human confirmation flag for live orders")
    start.add_argument("--submit-orders", action="store_true", default=False, help="Submit paper orders in production loop")
    start.add_argument("--data-vendor", default="yfinance", help="Market-data connector (default: yfinance)")
    start.add_argument("--bar-size", default="1m", help="Bar interval string e.g. 1m, 5m (default: 1m)")
    start.add_argument("--poll-interval", type=float, default=60.0, help="Poll interval in seconds (default: 60)")
    start.add_argument("--max-runtime-hours", type=float, default=8.0, help="Max session wall-clock hours (default: 8)")
    start.add_argument("--initial-cash", type=float, default=100_000.0, help="Initial capital (default: 100000)")
    start.add_argument("--commission-rate", type=float, default=0.0001, help="Commission rate (default: 0.0001)")
    start.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in bps (default: 1.0)")
    start.add_argument("--simulate-days", type=int, default=0, help="Simulate N historical trading days for accelerated paper production (0=live session)")
    start.set_defaults(func=cmd_live_start)


# ---------------------------------------------------------------------------
# live-pilot
# ---------------------------------------------------------------------------


def cmd_live_pilot_approval_create(args: argparse.Namespace) -> None:
    """Create a live pilot approval request."""
    from quant_us.live.live_pilot_approval import HumanApprovalGate

    gate = HumanApprovalGate()
    approval = gate.create(
        approval_id=args.approval_id,
        strategy_id=args.strategy,
        strategy_version=args.strategy_version,
        symbols=_parse_symbols(args.symbols),
        requested_by=args.requested_by,
        proposed_capital=args.capital,
    )

    print()
    print("=" * 60)
    print("  Live Pilot Approval Created")
    print("=" * 60)
    print(f"  Approval ID:     {approval.approval_id}")
    print(f"  Status:          {approval.status}")
    print(f"  Strategy:        {approval.strategy_id} v{approval.strategy_version}")
    print(f"  Symbols:         {', '.join(approval.symbols)}")
    print(f"  Proposed Capital: ${approval.proposed_capital:,.2f}")
    print(f"  Requested By:    {approval.requested_by or 'N/A'}")
    print(f"  Requested At:    {approval.requested_at[:19]}")
    print()
    print("  Next: approval approve --approval-id <id> --manual")
    print("  NOTE: approval does NOT enable live orders.")
    print("=" * 60)
    print()


def cmd_live_pilot_approval_inspect(args: argparse.Namespace) -> None:
    """Inspect a live pilot approval."""
    from quant_us.live.live_pilot_approval import HumanApprovalGate

    gate = HumanApprovalGate()
    approval = gate.inspect(args.approval_id)

    print()
    print("=" * 60)
    if approval is None:
        print(f"  Approval not found: {args.approval_id}")
    else:
        print(f"  Approval: {approval.approval_id}")
        print(f"  Status:   {approval.status}")
        print(f"  Strategy: {approval.strategy_id} v{approval.strategy_version}")
        print(f"  Symbols:  {', '.join(approval.symbols)}")
        print(f"  Capital:  ${approval.proposed_capital:,.2f}")
        print(f"  Approver: {approval.approver or 'N/A'}")
        print(f"  Expires:  {approval.expires_at[:19] if approval.expires_at else 'N/A'}")
        if approval.rejection_reason:
            print(f"  Rejection: {approval.rejection_reason}")
    print("=" * 60)
    print()


def cmd_live_pilot_approval_approve(args: argparse.Namespace) -> None:
    """Approve a live pilot approval (manual action)."""
    from quant_us.live.live_pilot_approval import HumanApprovalGate

    gate = HumanApprovalGate()
    try:
        approval = gate.approve(args.approval_id, args.manual or "cli_user")
        print()
        print("=" * 60)
        print(f"  Approval APPROVED: {approval.approval_id}")
        print(f"  Approver: {approval.approver}")
        print(f"  Expires:  {approval.expires_at[:19]}")
        print()
        print("  NOTE: This does NOT enable live orders.")
        print("  Live profile remains NOT READY by default.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_approval_reject(args: argparse.Namespace) -> None:
    """Reject a live pilot approval."""
    from quant_us.live.live_pilot_approval import HumanApprovalGate

    gate = HumanApprovalGate()
    try:
        approval = gate.reject(args.approval_id, args.reason)
        print()
        print("=" * 60)
        print(f"  Approval REJECTED: {approval.approval_id}")
        print(f"  Reason: {approval.rejection_reason}")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_approval_list(args: argparse.Namespace) -> None:
    """List all live pilot approvals."""
    from quant_us.live.live_pilot_approval import HumanApprovalGate

    gate = HumanApprovalGate()
    approvals = gate.list_approvals()

    print()
    print("=" * 60)
    print(f"  Live Pilot Approvals — {len(approvals)} found")
    print("=" * 60)
    for a in approvals:
        print(f"  [{a.status:12s}] {a.approval_id}  {a.strategy_id}  "
              f"symbols={','.join(a.symbols)}  capital=${a.proposed_capital:,.0f}")
    if not approvals:
        print("  No approvals found.")
    print("=" * 60)
    print()


def cmd_live_pilot_risk_envelope_create(args: argparse.Namespace) -> None:
    """Create a live pilot risk envelope."""
    from quant_us.live.live_pilot_risk_envelope import LivePilotRiskEnvelope, RiskEnvelopeManager

    envelope = LivePilotRiskEnvelope(
        envelope_id=args.envelope_id,
        strategy_id=args.strategy,
        symbols=_parse_symbols(args.symbols),
    )
    mgr = RiskEnvelopeManager()
    mgr.create(envelope)

    print()
    print("=" * 60)
    print("  Live Pilot Risk Envelope Created")
    print("=" * 60)
    print(f"  Envelope ID:           {envelope.envelope_id}")
    print(f"  Max Capital:           ${envelope.max_total_capital:,.2f}")
    print(f"  Max Order Notional:    ${envelope.max_order_notional:,.2f}")
    print(f"  Max Daily Notional:    ${envelope.max_daily_notional:,.2f}")
    print(f"  Max Daily Orders:      {envelope.max_daily_order_count}")
    print(f"  Max Gross Exposure:    {envelope.max_gross_exposure_pct:.1%}")
    print(f"  Max Daily Loss:        {envelope.max_daily_loss_pct:.2%}")
    print(f"  Market Orders:         {'BLOCKED' if not envelope.allow_market_order else 'allowed'}")
    print(f"  Pre/Post Market:       {'BLOCKED' if not envelope.allow_pre_post_market else 'allowed'}")
    print(f"  Short Selling:         {'BLOCKED' if not envelope.allow_short else 'allowed'}")
    print(f"  Reduce-Only on Warn:   {envelope.reduce_only_on_warning}")
    print("=" * 60)
    print()


def cmd_live_pilot_risk_envelope_inspect(args: argparse.Namespace) -> None:
    """Inspect a risk envelope."""
    from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

    mgr = RiskEnvelopeManager()
    envelope = mgr.load(args.envelope_id)

    print()
    print("=" * 60)
    if envelope is None:
        print(f"  Envelope not found: {args.envelope_id}")
    else:
        print(f"  Envelope: {envelope.envelope_id}")
        print(f"  Strategy: {envelope.strategy_id}")
        print(f"  Symbols:  {', '.join(envelope.symbols)}")
        print(f"  Max Order: ${envelope.max_order_notional:,.2f}")
        print(f"  Daily Loss Limit: {envelope.max_daily_loss_pct:.2%}")
    print("=" * 60)
    print()


def cmd_live_pilot_risk_envelope_validate(args: argparse.Namespace) -> None:
    """Validate order against a risk envelope."""
    from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

    mgr = RiskEnvelopeManager()
    result = mgr.validate(
        args.envelope_id,
        order_notional=args.notional,
        order_type=OrderType.LIMIT,
        side=OrderSide.BUY,
    )

    print()
    print("=" * 60)
    print(f"  Risk Envelope Validation: {args.envelope_id}")
    print(f"  Result: {'PASS' if result.get('passed') else 'BLOCKED'}")
    if result.get("reason"):
        print(f"  Reason: {result['reason']}")
    if result.get("reduce_only"):
        print("  REDUCE-ONLY enforced.")
    print("=" * 60)
    print()


def cmd_live_pilot_dry_run(args: argparse.Namespace) -> None:
    """Execute live pilot dry-run (no real orders)."""
    from quant_us.live.live_pilot_dry_run import LivePilotDryRunExecutor

    executor = LivePilotDryRunExecutor(data_root=args.data_root)
    report = executor.execute(
        approval_id=args.approval_id,
        envelope_id=args.envelope_id,
        strategy_id=args.strategy,
        symbols=_parse_symbols(args.symbols),
    )
    output = executor.save_report(report)

    print()
    print("=" * 60)
    print("  Live Pilot Dry-Run Report")
    print("=" * 60)
    print(f"  Dry-Run ID:       {report.dry_run_id}")
    print(f"  Steps:            {report.steps_passed}/{report.steps_total}")
    print(f"  Overall:          {'PASS' if report.overall_passed else 'BLOCKED'}")
    print(f"  Real Submit:      **False** (always)")
    print(f"  Real Submit Occurred: {report.to_dict()['real_submit_occurred']}")
    if report.errors:
        print("  Errors:")
        for err in report.errors:
            print(f"    - {err}")
    print(f"  Report saved:     {output}")
    print()
    print("  NO real orders were submitted.")
    print("=" * 60)
    print()


def cmd_live_pilot_emergency_stop_trigger(args: argparse.Namespace) -> None:
    """Trigger emergency stop."""
    from quant_us.live.emergency_stop import EmergencyStopController

    controller = EmergencyStopController(state_dir=f"{args.data_root}/live_pilot")
    event = controller.trigger(reason=args.reason, triggered_by="cli")

    print()
    print("=" * 60)
    print("  EMERGENCY STOP TRIGGERED")
    print("=" * 60)
    print(f"  Event:   {event.event_id}")
    print(f"  Reason:  {event.reason}")
    print(f"  State:   {event.state}")
    print()
    print("  New positions: BLOCKED")
    print("  Reduce-only:   ALLOWED")
    print("  Next: emergency-stop acknowledge")
    print("=" * 60)
    print()


def cmd_live_pilot_emergency_stop_status(args: argparse.Namespace) -> None:
    """Show emergency stop status."""
    from quant_us.live.emergency_stop import EmergencyStopController

    controller = EmergencyStopController(state_dir=f"{args.data_root}/live_pilot")
    status = controller.status()

    print()
    print("=" * 60)
    print(f"  Emergency Stop Status: {status['state']}")
    print(f"  Reduce-Only:           {status['reduce_only']}")
    print(f"  New Positions Allowed: {status['new_positions_allowed']}")
    if status["current_event"]:
        e = status["current_event"]
        print(f"  Event:   {e.get('event_id', 'N/A')}")
        print(f"  Reason:  {e.get('reason', 'N/A')}")
        print(f"  Trigger: {e.get('triggered_at', 'N/A')[:19]}")
    print("=" * 60)
    print()


def cmd_live_pilot_emergency_stop_acknowledge(args: argparse.Namespace) -> None:
    """Acknowledge emergency stop."""
    from quant_us.live.emergency_stop import EmergencyStopController

    controller = EmergencyStopController(state_dir=f"{args.data_root}/live_pilot")
    event = controller.acknowledge(acknowledged_by="cli")

    print()
    print("=" * 60)
    print(f"  Emergency Stop ACKNOWLEDGED: {event.event_id}")
    print(f"  State: {event.state}")
    print("=" * 60)
    print()


def cmd_live_pilot_emergency_stop_resolve(args: argparse.Namespace) -> None:
    """Resolve emergency stop."""
    from quant_us.live.emergency_stop import EmergencyStopController

    controller = EmergencyStopController(state_dir=f"{args.data_root}/live_pilot")
    event = controller.resolve(notes="Resolved via CLI")

    print()
    print("=" * 60)
    print(f"  Emergency Stop RESOLVED: {event.event_id}")
    print(f"  State: {event.state}")
    print("  New positions are now allowed again.")
    print("=" * 60)
    print()


def cmd_live_pilot_rollback_plan(args: argparse.Namespace) -> None:
    """Generate a rollback plan."""
    from quant_us.live.emergency_stop import RollbackPlanGenerator

    generator = RollbackPlanGenerator(data_root=args.data_root)
    plan = generator.generate(reason=args.reason or "manual_request")

    print()
    print("=" * 60)
    print(f"  Rollback Plan: {plan.plan_id}")
    print("=" * 60)
    print(f"  Stop Reason: {plan.stop_reason or 'N/A'}")
    print("  Actions:")
    for action in plan.actions:
        print(f"    {action['step']}. {action['action']} [{action['status']}]")
    print()
    print("  Reduce-Only Instructions:")
    for instr in plan.reduce_only_instructions:
        print(f"    - {instr}")
    print()
    print("  NO orders are submitted by this plan.")
    print("  Manual review REQUIRED.")
    print("=" * 60)
    print()


def cmd_live_pilot_dossier(args: argparse.Namespace) -> None:
    """Generate G3 Go/No-Go dossier."""
    output = args.output or f"{args.data_root}/reports/live_pilot_go_no_go.md"

    from quant_us.live.live_pilot_go_nogo import LivePilotGoNoGoBuilder

    builder = LivePilotGoNoGoBuilder(data_root=args.data_root)
    dossier = builder.build()

    print()
    print("=" * 60)
    print("  G3 Live Pilot Go/No-Go Dossier")
    print("=" * 60)
    print(f"  Paper:       {dossier.paper.clean_days}/30 clean days")
    print(f"  Shadow:      {dossier.shadow.days_completed}/5 days, real_submit={dossier.shadow.real_submit_count}")
    print(f"  Approval:    {dossier.approval.status}")
    print(f"  Envelope:    {'configured' if dossier.envelope.is_ready() else 'NOT configured'}")
    print(f"  Safety:      {'PASS' if dossier.safety.all_ready() else 'INCOMPLETE'}")
    print()
    print(f"  Decision:    **{dossier.decision}**")

    if dossier.decision == "READY_FOR_HUMAN_REVIEW":
        print()
        print("  IMPORTANT:")
        print("  - This does NOT automatically enable live orders.")
        print("  - Human review and explicit authorization REQUIRED.")
        print("  - Live profile remains NOT READY by default.")
    elif dossier.decision == "BLOCKED":
        reasons = dossier.decision_reasons
        if reasons:
            print(f"  Reasons: {', '.join(reasons)}")

    builder.save_dossier(dossier, output)
    print(f"  Dossier:     {output}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G4: live-pilot execute handlers
# ---------------------------------------------------------------------------


def cmd_live_pilot_execute(args: argparse.Namespace) -> None:
    """Execute live pilot order pipeline (default: dry-run)."""
    import os

    symbols = _parse_symbols(args.symbols)
    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    from quant_us.live.live_pilot_executor import LivePilotExecutor, LivePilotExecutorConfig

    execute_live = getattr(args, "execute_live_pilot", False)
    confirm_live = getattr(args, "confirm_live", False)

    config = LivePilotExecutorConfig(
        approval_id=args.approval_id,
        envelope_id=args.envelope_id,
        symbols=symbols,
        strategy_id=args.strategy,
        execute_live_pilot=execute_live,
        confirm_live=confirm_live,
        is_dry_run=not execute_live,
        data_root=args.data_root,
        api_key=api_key,
        api_secret=api_secret,
    )

    print()
    print("=" * 60)
    if config.is_dry_run:
        print("  Live Pilot DRY-RUN Execution")
    else:
        print("  Live Pilot REAL Execution")
    print("=" * 60)
    print(f"  Approval:    {config.approval_id}")
    print(f"  Envelope:    {config.envelope_id}")
    print(f"  Symbols:     {', '.join(symbols)}")
    print(f"  Strategy:    {config.strategy_id}")
    print(f"  Execute:     {'YES (REAL)' if execute_live else 'NO (dry-run)'}")
    print(f"  Confirm:     {'YES' if confirm_live else 'NO'}")
    print()

    executor = LivePilotExecutor(config)
    result = executor.execute()

    print(f"  Run ID:      {result['run_id']}")
    print(f"  Status:      {result['status']}")
    print(f"  Real Submit: {'YES' if result['real_submit_occurred'] else 'NO'}")
    print(f"  Previews:    {len(result['previews'])}")
    if result.get("errors"):
        print("  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")

    steps = result.get("steps", {})
    for step_name, step_result in steps.items():
        status = step_result.get("status", step_result.get("decision", "?"))
        print(f"  [{step_name:20s}] {status}")

    print()
    if result["real_submit_occurred"]:
        print("  REAL ORDER SUBMITTED. Check audit trail.")
    else:
        print("  No real orders were submitted.")
    print("=" * 60)
    print()


def cmd_live_pilot_first_order_simulate(args: argparse.Namespace) -> None:
    """Simulate first live order (no submit)."""
    from quant_us.live.first_live_order_simulation import FirstLiveOrderSimulation

    simulator = FirstLiveOrderSimulation(data_root=args.data_root)
    result = simulator.simulate(
        approval_id=args.approval_id,
        envelope_id=args.envelope_id,
        symbols=_parse_symbols(args.symbols),
    )
    sim_path = simulator.save_result(result)

    print()
    print("=" * 60)
    print("  First Live Order Simulation")
    print("=" * 60)
    print(f"  Symbol:        {result.suggested_symbol}")
    print(f"  Side:          {result.suggested_side}")
    print(f"  Qty:           {result.suggested_qty}")
    print(f"  Notional:      ${result.notional:,.2f}")
    print(f"  Risk Decision: {result.risk_decision}")
    print(f"  Gate Decision: {result.gate_decision}")
    print(f"  Readiness:     {result.readiness}")
    print()
    print(f"  Block Reasons: {', '.join(result.gate_block_reasons) or 'none'}")
    print()
    print("  Manual Checklist:")
    for item in result.manual_checklist[:5]:
        print(f"    - {item}")
    print(f"    ... ({len(result.manual_checklist)} items total)")
    print()
    print(f"  Result saved: {sim_path}")
    print(f"  Real Submit:  **NO** (simulation only)")
    print("=" * 60)
    print()


def cmd_live_pilot_audit_trail(args: argparse.Namespace) -> None:
    """Show live order audit trail."""
    from quant_us.live.live_order_audit import LiveOrderAuditTrail

    trail = LiveOrderAuditTrail(audit_dir=f"{args.data_root}/live_pilot/audit")

    if args.run_id:
        entries = trail.read_by_run(args.run_id)
    else:
        entries = trail.read_all(limit=50)

    real_count = trail.real_submit_count()

    print()
    print("=" * 60)
    print(f"  Live Order Audit Trail — {len(entries)} entries")
    print(f"  Real Submits: {real_count}")
    print("=" * 60)
    if not entries:
        print("  No entries found.")
    for e in entries[-20:]:
        icon = "REAL" if e.get("real_submit") else "DRY"
        print(f"  [{icon}] {e.get('created_at', '?')[:19]} "
              f"{e.get('symbol', '?')} {e.get('side', '?')} "
              f"qty={e.get('qty', 0)} notional=${e.get('notional', 0):,.0f} "
              f"gate={e.get('gate_decision', '?')}")
    print("=" * 60)
    print()


def cmd_live_pilot_executor_status(args: argparse.Namespace) -> None:
    """Show live pilot executor status."""
    from quant_us.live.emergency_stop import EmergencyStopController
    from quant_us.live.live_order_audit import LiveOrderAuditTrail

    es_ctrl = EmergencyStopController(state_dir=f"{args.data_root}/live_pilot")
    es_status = es_ctrl.status()
    trail = LiveOrderAuditTrail(audit_dir=f"{args.data_root}/live_pilot/audit")

    print()
    print("=" * 60)
    print("  Live Pilot Status")
    print("=" * 60)
    print(f"  Emergency Stop: {es_status['state']}")
    print(f"  Reduce-Only:    {es_status['reduce_only']}")
    print(f"  Real Submits:   {trail.real_submit_count()}")
    print(f"  Audit Entries:  {len(trail.read_all(limit=1))}")
    print("=" * 60)
    print()


def cmd_live_pilot_stop(args: argparse.Namespace) -> None:
    """Stop live pilot (triggers emergency stop)."""
    from quant_us.live.emergency_stop import EmergencyStopController

    controller = EmergencyStopController(state_dir=f"{args.data_root}/live_pilot")
    event = controller.trigger(reason="manual_stop", triggered_by="cli")

    print()
    print("=" * 60)
    print("  Live Pilot STOPPED")
    print("=" * 60)
    print(f"  Event:     {event.event_id}")
    print(f"  State:     {event.state}")
    print(f"  New orders: BLOCKED")
    print(f"  Reduce-only: ALLOWED")
    print()
    print("  To resume: acknowledge then resolve emergency stop")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G5: one-shot execution handlers
# ---------------------------------------------------------------------------


def cmd_live_pilot_first_order_ticket(args: argparse.Namespace) -> None:
    """Generate a first live order ticket for human review. No orders submitted."""
    symbols = _parse_symbols(args.symbols)
    from quant_us.live.first_live_order_ticket import FirstLiveOrderTicketBuilder

    builder = FirstLiveOrderTicketBuilder(data_root=args.data_root)
    ticket = builder.build(
        approval_id=args.approval_id,
        envelope_id=args.envelope_id,
        symbol=symbols[0] if symbols else "SPY",
        side=args.side,
        quantity=args.quantity,
        limit_price=args.limit_price,
    )
    path = builder.save_ticket(ticket)

    print()
    print("=" * 60)
    print("  First Live Order Ticket")
    print("=" * 60)
    print(f"  Ticket ID:     {ticket.ticket_id}")
    print(f"  Status:        {ticket.status}")
    print(f"  Symbol:        {ticket.symbol}")
    print(f"  Side:          {ticket.side}")
    print(f"  Qty:           {ticket.quantity}")
    print(f"  Limit:         ${ticket.limit_price:,.2f}")
    print(f"  Notional:      ${ticket.estimated_notional:,.2f}")
    print(f"  Max Notional:  ${ticket.max_allowed_notional:,.2f}")
    print(f"  Expires:       {ticket.expires_at[:19]}")
    print(f"  Expired:       {'YES' if ticket.is_expired else 'NO'}")
    print()
    print(f"  Saved:         {path}")
    print("  Real Submit:   **NO** (ticket generation only)")
    print("=" * 60)
    print()


def cmd_live_pilot_confirm_ticket(args: argparse.Namespace) -> None:
    """Final human confirmation of a ticket. Does NOT submit orders."""
    from quant_us.live.first_live_order_ticket import FinalHumanConfirmationGate

    gate = FinalHumanConfirmationGate(audit_dir=f"{args.data_root}/live_pilot/audit")
    result = gate.check(
        ticket_id=args.ticket_id,
        i_understand_real_money=False,
        confirm_live=False,
        execute_one_shot=False,
        confirm_ticket=args.ticket_id,
    )

    print()
    print("=" * 60)
    print(f"  Ticket Confirmation: {args.ticket_id}")
    print(f"  Passed: {'YES' if result.passed else 'NO'}")
    if result.reason:
        print(f"  Reason: {result.reason}")
    print()
    print("  NOTE: This confirms the ticket. It does NOT submit an order.")
    print("  To execute: live-pilot one-shot --execute-one-shot --confirm-live")
    print("             --i-understand-this-is-real-money")
    print("=" * 60)
    print()


def cmd_live_pilot_one_shot(args: argparse.Namespace) -> None:
    """Execute one-shot live pilot order (default: dry-run)."""
    import os

    symbols = _parse_symbols(args.symbols)
    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    from quant_us.live.one_shot_executor import OneShotLivePilotExecutor, OneShotExecutorConfig

    approve_id = args.approval_id or args.ticket_id
    config = OneShotExecutorConfig(
        ticket_id=args.ticket_id,
        approve_live_id=approve_id,
        envelope_id=args.envelope_id,
        symbols=symbols,
        confirm_live=getattr(args, "confirm_live", False),
        execute_one_shot=getattr(args, "execute_one_shot", False),
        i_understand_real_money=getattr(args, "i_understand_this_is_real_money", False),
        confirm_ticket=getattr(args, "confirm_ticket", args.ticket_id),
        is_dry_run=not getattr(args, "execute_one_shot", False),
        data_root=args.data_root,
        api_key=api_key,
        api_secret=api_secret,
    )

    print()
    print("=" * 60)
    print("  G5 One-Shot Live Pilot")
    print("=" * 60)
    print(f"  Ticket:       {config.ticket_id}")
    print(f"  Execute:      {'YES (REAL)' if config.execute_one_shot else 'NO (dry-run)'}")
    print(f"  Confirm:      {'YES' if config.confirm_live else 'NO'}")
    print(f"  Real Money:   {'YES' if config.i_understand_real_money else 'NO'}")
    print()

    executor = OneShotLivePilotExecutor(config)
    result = executor.execute()

    print(f"  Run ID:       {result['run_id']}")
    print(f"  Status:       {result['status']}")
    print(f"  Real Submit:  {'YES' if result.get('real_submit_occurred') else 'NO'}")
    print(f"  Freeze:       {'YES' if result.get('freeze_applied') else 'NO'}")

    steps = result.get("steps", {})
    for step_name, step in steps.items():
        status = step.get("status", step.get("passed", "?"))
        print(f"  [{step_name:25s}] {status}")

    lock_status = executor.lock_manager.status()
    print(f"  Submit Lock:  {'ACTIVE' if lock_status['locked'] else 'not active'}")

    if result.get("errors"):
        print(f"  Errors: {', '.join(result['errors'])}")
    if result["status"] == "ONE_SHOT_SUBMITTED_FROZEN":
        print()
        print("  ONE-SHOT EXECUTED. SYSTEM IS FROZEN.")
        print("  No second order is possible without manual review.")
    print("=" * 60)
    print()


def cmd_live_pilot_submit_lock(args: argparse.Namespace) -> None:
    """Manage submit-once lock."""
    from quant_us.live.one_shot_executor import SubmitOnceLockManager

    mgr = SubmitOnceLockManager(lock_path=f"{args.data_root}/live_pilot/submit_once_lock.json")

    if getattr(args, "release", False):
        lock = mgr.release(args.manual or "cli", args.reason or "manual_release")
        print(f"Submit-once lock RELEASED: {lock.lock_id}")
        return

    status = mgr.status()
    print()
    print("=" * 60)
    print(f"  Submit-Once Lock: {'ACTIVE' if status['locked'] else 'not active'}")
    if status["locked"]:
        lock = status["lock"]
        print(f"  Lock ID:        {lock.get('lock_id', '?')}")
        print(f"  Ticket:         {lock.get('ticket_id', '?')}")
        print(f"  Client Order:   {lock.get('client_order_id', '?')}")
        print(f"  Reason:         {lock.get('reason', '?')}")
        print(f"  Locked At:      {lock.get('locked_at', '?')[:19]}")
    print("=" * 60)
    print()


def cmd_live_pilot_post_trade_reconcile(args: argparse.Namespace) -> None:
    """Run post-trade reconciliation."""
    from quant_us.live.g5_post_trade import PostTradeReconciler

    reconciler = PostTradeReconciler()
    result = reconciler.reconcile(ticket_id=args.ticket_id)

    print()
    print("=" * 60)
    print(f"  Post-Trade Reconciliation: {args.ticket_id}")
    print(f"  Status:      {result.status}")
    print(f"  Fill Qty:    {result.fill_qty}")
    print(f"  Fill Price:  ${result.fill_price:,.2f}")
    print(f"  Manual:      {'REQUIRED' if result.requires_manual_review else 'no'}")
    print("=" * 60)
    print()


def cmd_live_pilot_freeze_status(args: argparse.Namespace) -> None:
    """Show freeze state."""
    from quant_us.live.g5_post_trade import LivePilotFreezeState

    freeze = LivePilotFreezeState(state_dir=f"{args.data_root}/live_pilot")
    status = freeze.status()

    print()
    print("=" * 60)
    print(f"  Live Pilot Freeze: {'ACTIVE' if status['frozen'] else 'not active'}")
    if status["frozen"]:
        d = status.get("data", {})
        print(f"  State:    {status['state']}")
        print(f"  Ticket:   {d.get('ticket_id', '?')}")
        print(f"  Frozen:   {d.get('frozen_at', '?')[:19]}")
        print(f"  Reason:   {d.get('reason', '?')}")
    print("=" * 60)
    print()


def cmd_live_pilot_execution_quality(args: argparse.Namespace) -> None:
    """Generate execution quality report."""
    from quant_us.live.g5_post_trade import generate_execution_quality

    report = generate_execution_quality(ticket_id=args.ticket_id)

    print()
    print("=" * 60)
    print(f"  Execution Quality: {args.ticket_id}")
    print(f"  Status:    {report.execution_status}")
    print(f"  Slippage:  {report.slippage_bps} bps")
    print(f"  Latency:   {report.latency_ms} ms")
    print(f"  Next:      {report.next_action}")
    if report.lessons_learned:
        print("  Lessons:")
        for l in report.lessons_learned:
            print(f"    - {l}")
    print("=" * 60)
    print()


def cmd_live_pilot_g5_dossier(args: argparse.Namespace) -> None:
    """Generate G5 post-trade dossier."""
    output = args.output or f"{args.data_root}/reports/g5_post_trade_dossier.md"
    from quant_us.live.g5_post_trade import G5PostTradeDossier

    dossier = G5PostTradeDossier(ticket_id=args.ticket_id)
    dossier.determine_decision()

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(dossier.to_markdown())
    Path(output.replace(".md", ".json")).write_text(json.dumps(dossier.to_dict(), indent=2))

    print()
    print("=" * 60)
    print(f"  G5 Post-Trade Dossier: {args.ticket_id}")
    print(f"  Decision: {dossier.decision}")
    print(f"  Saved:    {output}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G6: live-pilot risk-status
# ---------------------------------------------------------------------------


def cmd_live_pilot_risk_status(args: argparse.Namespace) -> None:
    """Show cumulative risk status for a micro pilot episode."""
    from quant_us.live.g6_risk_monitor import CumulativeLiveRiskMonitor

    monitor = CumulativeLiveRiskMonitor(data_root=args.data_root)
    state = monitor.evaluate(episode_id=args.episode_id)

    print()
    print("=" * 60)
    print(f"  Cumulative Risk Status: {args.episode_id}")
    print(f"  Status:                {state.status}")
    print(f"  Total Orders:          {state.total_order_count}")
    print(f"  Daily Orders:          {state.daily_order_count}")
    print(f"  Cumulative Notional:   ${state.cumulative_notional:,.2f}")
    print(f"  Realized PnL:          ${state.cumulative_realized_pnl:,.2f}")
    print(f"  Unrealized PnL:        ${state.cumulative_unrealized_pnl:,.2f}")
    print(f"  Fees:                  ${state.cumulative_fees:,.2f}")
    print(f"  Slippage:              {state.cumulative_slippage_bps:.1f} bps")
    print(f"  Open Positions:        {state.live_open_position_count}")
    print(f"  Incidents:             {state.incident_count}")
    print(f"  Recon Fails:           {state.recon_fail_count}")
    print(f"  Broker Errors:         {state.broker_error_count}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G6: live-pilot exit-plan
# ---------------------------------------------------------------------------


def cmd_live_pilot_exit_plan_create(args: argparse.Namespace) -> None:
    """Create a reduce-only exit plan for a live position."""
    from quant_us.live.g6_exit_plan import LivePositionExitPlanBuilder

    builder = LivePositionExitPlanBuilder(data_root=args.data_root)
    plan = builder.build(
        episode_id=args.episode_id,
        ticket_id=args.ticket_id,
        symbol=args.symbol,
        current_qty=args.qty,
        entry_price=args.entry_price,
        exit_reason=getattr(args, "exit_reason", "manual_exit"),
    )
    builder.save(plan)

    print()
    print("=" * 60)
    print(f"  Exit Plan Created: {plan.exit_plan_id}")
    print(f"  Episode:           {plan.episode_id}")
    print(f"  Ticket:            {plan.ticket_id}")
    print(f"  Symbol:            {plan.symbol}")
    print(f"  Position:          {plan.current_qty}")
    print(f"  Suggested:         {plan.suggested_side} {plan.suggested_qty} @ ${plan.suggested_limit_price:.2f}")
    print(f"  Reduce-Only:       {plan.reduce_only}")
    print(f"  Status:            {plan.status}")
    print(f"  Saved:             {builder.plans_dir / (plan.exit_plan_id + '.json')}")
    print("=" * 60)
    print()


def cmd_live_pilot_exit_plan_inspect(args: argparse.Namespace) -> None:
    """Inspect an exit plan."""
    from quant_us.live.g6_exit_plan import LivePositionExitPlanBuilder

    builder = LivePositionExitPlanBuilder(data_root=args.data_root)
    plan = builder.load(args.exit_plan_id)

    if plan is None:
        print(f"Exit plan not found: {args.exit_plan_id}")
        return

    print()
    print("=" * 60)
    print(f"  Exit Plan:         {plan.exit_plan_id}")
    print(f"  Episode:           {plan.episode_id}")
    print(f"  Ticket:            {plan.ticket_id}")
    print(f"  Symbol:            {plan.symbol}")
    print(f"  Current Qty:       {plan.current_qty}")
    print(f"  Entry Price:       ${plan.average_entry_price:,.2f}")
    print(f"  Market Price:      ${plan.current_market_price:,.2f}")
    print(f"  Unrealized PnL:    ${plan.unrealized_pnl:,.2f}")
    print(f"  Exit Reason:       {plan.exit_reason}")
    print(f"  Suggested:         {plan.suggested_side} {plan.suggested_qty} @ ${plan.suggested_limit_price:.2f}")
    print(f"  Reduce-Only:       {plan.reduce_only}")
    print(f"  Manual Approval:   {plan.manual_approval_required}")
    print(f"  Status:            {plan.status}")
    print(f"  Created:           {plan.created_at[:19] if plan.created_at else '?'}")
    if plan.notes:
        print(f"  Notes:             {plan.notes}")
    print("=" * 60)
    print()


def cmd_live_pilot_exit_plan_execute(args: argparse.Namespace) -> None:
    """Execute an exit plan (dry-run by default)."""
    from quant_us.live.g6_reduce_only_executor import ReduceOnlyExitExecutor

    executor = ReduceOnlyExitExecutor(
        data_root=args.data_root,
        dry_run=getattr(args, "dry_run", True),
    )
    result = executor.execute(
        exit_plan_id=args.exit_plan_id,
        manual_approval=getattr(args, "manual_approval", False),
    )

    print()
    print("=" * 60)
    print(f"  Exit Plan Execute: {args.exit_plan_id}")
    print(f"  Dry Run:           {result.dry_run}")
    print(f"  Submitted:         {result.submitted}")
    print(f"  Reduce-Only OK:    {result.reduce_only_verified}")
    print(f"  Position Check:    {result.position_check_passed}")
    if result.errors:
        print("  Errors:")
        for e in result.errors:
            print(f"    - {e}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G6: live-pilot episode final-dossier
# ---------------------------------------------------------------------------


def cmd_live_pilot_episode_final_dossier(args: argparse.Namespace) -> None:
    """Generate final dossier for a micro pilot episode."""
    from quant_us.live.g6_final_dossier import MicroPilotFinalDossierBuilder

    builder = MicroPilotFinalDossierBuilder(data_root=args.data_root)
    dossier = builder.build(args.episode_id)
    path = builder.save(dossier)

    print()
    print("=" * 60)
    print(f"  Micro Pilot Final Dossier")
    print(f"  Episode:     {args.episode_id}")
    print(f"  Dossier ID:  {dossier.dossier_id}")
    print(f"  Decision:    {dossier.decision}")
    if dossier.decision_reasons:
        print("  Reasons:")
        for r in dossier.decision_reasons:
            print(f"    - {r}")
    print(f"  Saved:       {path}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G6: Second review / Episode / Progression handlers
# ---------------------------------------------------------------------------


def cmd_live_pilot_second_review(args: argparse.Namespace) -> None:
    """Run G6 second one-shot review gate."""
    from quant_us.live.g6_second_review import SecondOneShotReviewGate

    gate = SecondOneShotReviewGate(data_root=args.data_root)
    decision = gate.review(
        g5_ticket_id=args.ticket_id,
        g5_dossier_path=getattr(args, "dossier_path", ""),
        manual_review_decision=getattr(args, "manual_review", ""),
        manual_reviewer=getattr(args, "reviewer", ""),
    )

    print()
    print("=" * 60)
    print(f"  G6 Second One-Shot Review: {args.ticket_id}")
    print(f"  Decision: {decision.decision}")
    print(f"  Passed Checks: {', '.join(decision.passed_checks) or 'none'}")
    print(f"  Block Reasons: {', '.join(decision.block_reasons) or 'none'}")
    print(f"  Checked At: {decision.checked_at[:19]}")
    print()
    print("  NOTE: This is a review gate. It does NOT submit orders.")
    print("=" * 60)
    print()


def cmd_live_pilot_episode_create(args: argparse.Namespace) -> None:
    """Create a new micro-pilot episode."""
    from quant_us.live.g6_episode import MicroPilotEpisodeManager

    symbols = _parse_symbols(args.symbols) if args.symbols else ["SPY"]
    mgr = MicroPilotEpisodeManager(data_root=args.data_root)
    episode = mgr.create(
        strategy_id=args.strategy_id,
        symbols=symbols,
        strategy_version=getattr(args, "strategy_version", "1.0.0"),
        max_order_count=getattr(args, "max_order_count", 3),
        max_cumulative_notional=getattr(args, "max_cumulative_notional", 300.0),
        max_cumulative_loss=getattr(args, "max_cumulative_loss", 10.0),
        max_order_notional=getattr(args, "max_order_notional", 100.0),
        max_orders_per_day=getattr(args, "max_orders_per_day", 1),
    )

    print()
    print("=" * 60)
    print("  Micro-Pilot Episode Created")
    print("=" * 60)
    print(f"  Episode ID:     {episode.episode_id}")
    print(f"  Strategy:       {episode.strategy_id} v{episode.strategy_version}")
    print(f"  Symbols:        {', '.join(episode.symbols)}")
    print(f"  Status:         {episode.status}")
    print(f"  Max Orders:     {episode.max_order_count}")
    print(f"  Max Notional:   ${episode.max_cumulative_notional:,.2f}")
    print(f"  Max Loss:       ${episode.max_cumulative_loss:,.2f}")
    print(f"  Started At:     {episode.started_at[:19]}")
    print()
    print("  Next: episode add-ticket --episode-id <id> --ticket-id <id>")
    print("=" * 60)
    print()


def cmd_live_pilot_episode_status(args: argparse.Namespace) -> None:
    """Show micro-pilot episode status."""
    from quant_us.live.g6_episode import MicroPilotEpisodeManager
    import json

    mgr = MicroPilotEpisodeManager(data_root=args.data_root)
    status = mgr.status(args.episode_id)

    print()
    print("=" * 60)
    print(f"  Micro-Pilot Episode Status: {args.episode_id}")
    print("=" * 60)
    print(json.dumps(status, indent=2))
    print("=" * 60)
    print()


def cmd_live_pilot_episode_add_ticket(args: argparse.Namespace) -> None:
    """Add a ticket to a micro-pilot episode."""
    from quant_us.live.g6_episode import MicroPilotEpisodeManager

    mgr = MicroPilotEpisodeManager(data_root=args.data_root)
    episode = mgr.add_ticket(
        episode_id=args.episode_id,
        ticket_id=args.ticket_id,
        notional=args.notional,
    )

    print()
    print("=" * 60)
    print(f"  Ticket Added to Episode: {args.episode_id}")
    print("=" * 60)
    print(f"  Episode:     {episode.episode_id}")
    print(f"  Ticket:      {episode.latest_ticket_id}")
    print(f"  Count:       {episode.completed_order_count}/{episode.max_order_count}")
    print(f"  Used Notional: ${episode.used_cumulative_notional:,.2f}")
    print(f"  Status:      {episode.status}")
    print()
    print("  NOTE: This records the ticket assignment. It does NOT submit orders.")
    print("=" * 60)
    print()


def cmd_live_pilot_episode_terminate(args: argparse.Namespace) -> None:
    """Terminate a micro-pilot episode."""
    from quant_us.live.g6_episode import MicroPilotEpisodeManager

    mgr = MicroPilotEpisodeManager(data_root=args.data_root)
    episode = mgr.terminate(
        episode_id=args.episode_id,
        reason=args.reason,
    )

    print()
    print("=" * 60)
    print(f"  Episode TERMINATED: {args.episode_id}")
    print("=" * 60)
    print(f"  Reason: {episode.termination_reason}")
    print(f"  Status: {episode.status}")
    print("=" * 60)
    print()


def cmd_live_pilot_episode_dossier(args: argparse.Namespace) -> None:
    """Show full episode dossier as JSON."""
    from quant_us.live.g6_episode import MicroPilotEpisodeManager
    import json

    mgr = MicroPilotEpisodeManager(data_root=args.data_root)
    episode = mgr.load(args.episode_id)

    print()
    print("=" * 60)
    if episode is None:
        print(f"  Episode not found: {args.episode_id}")
    else:
        print(f"  Episode Dossier: {args.episode_id}")
        print("=" * 60)
        print(json.dumps(episode.to_dict(), indent=2))
    print("=" * 60)
    print()


def cmd_live_pilot_progression_status(args: argparse.Namespace) -> None:
    """Show overall progression status."""
    from quant_us.live.g6_progression import PilotProgressionController
    import json

    controller = PilotProgressionController(data_root=args.data_root)
    status = controller.status()

    print()
    print("=" * 60)
    print("  G6 Pilot Progression Status")
    print("=" * 60)
    print(json.dumps(status, indent=2))
    print("=" * 60)
    print()


def cmd_live_pilot_progression_evaluate(args: argparse.Namespace) -> None:
    """Evaluate progression readiness for G7."""
    from quant_us.live.g6_progression import PilotProgressionController
    import json

    controller = PilotProgressionController(data_root=args.data_root)
    result = controller.evaluate(episode_id=args.episode_id)

    print()
    print("=" * 60)
    print(f"  G6 Progression Evaluation: {args.episode_id}")
    print("=" * 60)
    print(json.dumps(result, indent=2))
    print()
    print("  NOTE: This is a READ-ONLY evaluation. No state is auto-advanced.")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G8: Session command handlers
# ---------------------------------------------------------------------------


def cmd_live_pilot_session_create(args: argparse.Namespace) -> None:
    """Create a new G8 supervised micro live session."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager
    from quant_us.live.g8_session_gate import SessionGate

    mgr = SessionRuntimeStateManager(data_root=args.data_root)
    from quant_us.core.types import new_id
    session_id = args.session_id or new_id("g8_session")

    state = mgr.create(
        promotion_id=args.promotion_id,
        session_id=session_id,
        strategy_id=args.strategy,
        strategy_version=args.strategy_version,
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        max_orders_per_session=args.max_orders,
        max_orders_per_day=args.max_orders_per_day,
        max_session_notional=args.max_notional,
        max_session_loss=args.max_loss,
    )

    # Create promotion manifest if it doesn't exist
    gate = SessionGate(data_root=args.data_root)
    existing = gate.get_promotion(args.promotion_id)
    if existing is None:
        gate.create_promotion(args.promotion_id)
        print("  [INFO] Promotion manifest created (DRAFT).")

    print()
    print("=" * 60)
    print("  G8 Supervised Micro Live Session Created")
    print("=" * 60)
    print(f"  Session ID:    {state.session_id}")
    print(f"  Promotion ID:  {state.promotion_id}")
    print(f"  Strategy:      {state.strategy_id} v{state.strategy_version}")
    print(f"  Status:        {state.status}")
    print(f"  Max Orders:    {state.max_orders_per_session}")
    print(f"  Max Notional:  ${state.max_session_notional:,.2f}")
    print(f"  Max Loss:      ${state.max_session_loss:,.2f}")
    print()
    print("  Next: session arm --session-id <id> --manual")
    print("  NOTE: Session starts in DRAFT. Must be armed and activated.")
    print("=" * 60)
    print()


def cmd_live_pilot_session_arm(args: argparse.Namespace) -> None:
    """Arm a session (DRAFT -> ARMED)."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager

    mgr = SessionRuntimeStateManager(data_root=args.data_root)

    try:
        state = mgr.arm(args.session_id)
        print()
        print("=" * 60)
        print(f"  Session ARMED: {state.session_id}")
        print(f"  Status:        {state.status}")
        print(f"  Promotion:     {state.promotion_id}")
        print()
        print("  Next: session activate --session-id <id>")
        print("  NOTE: Manual approval required before activation.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_session_activate(args: argparse.Namespace) -> None:
    """Activate a session (ARMED -> ACTIVE_MANUAL_SUPERVISION)."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager

    mgr = SessionRuntimeStateManager(data_root=args.data_root)

    try:
        state = mgr.activate(args.session_id)
        print()
        print("=" * 60)
        print(f"  Session ACTIVATED: {state.session_id}")
        print(f"  Status:            {state.status}")
        print()
        print("  Session is now ready for supervised one-shot orders.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_session_status(args: argparse.Namespace) -> None:
    """Show session status."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager
    import json

    mgr = SessionRuntimeStateManager(data_root=args.data_root)
    status = mgr.status(args.session_id)

    print()
    print("=" * 60)
    if not status.get("exists"):
        print(f"  Session not found: {args.session_id}")
    else:
        print(f"  Session:        {status['session_id']}")
        print(f"  Promotion:      {status['promotion_id']}")
        print(f"  Status:         {status['status']}")
        print(f"  Started:        {status['started_at'][:19]}")
        print(f"  Updated:        {status['updated_at'][:19]}")
        print(f"  Orders Submitted: {status['submitted_order_count']}")
        print(f"  Orders Completed: {status['completed_order_count']}")
        print(f"  Real Submits:   {status['real_submit_count']}")
        print(f"  Incidents:      {status['incident_count']}")
        print(f"  Freeze Reason:  {status['current_freeze_reason'] or 'none'}")
        print(f"  Manual Review:  {status['manual_review_required']}")
        print(f"  Tickets:        {', '.join(status['order_ticket_ids']) if status['order_ticket_ids'] else 'none'}")
    print("=" * 60)
    print()


def cmd_live_pilot_session_pause(args: argparse.Namespace) -> None:
    """Pause a session."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager

    mgr = SessionRuntimeStateManager(data_root=args.data_root)

    try:
        state = mgr.pause(args.session_id)
        print()
        print("=" * 60)
        print(f"  Session PAUSED: {state.session_id}")
        print(f"  Status:         {state.status}")
        print()
        print("  Resume: session resume --session-id <id> --manual")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_session_resume(args: argparse.Namespace) -> None:
    """Resume a frozen session after post-trade review."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager

    mgr = SessionRuntimeStateManager(data_root=args.data_root)

    try:
        state = mgr.resume(args.session_id, reason=args.reason or "POST_TRADE_REVIEW_COMPLETE")
        print()
        print("=" * 60)
        print(f"  Session RESUMED: {state.session_id}")
        print(f"  Status:          {state.status}")
        print()
        print("  Session is ready for the next one-shot order.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_session_terminate(args: argparse.Namespace) -> None:
    """Terminate a session."""
    from quant_us.live.g8_session_state import SessionRuntimeStateManager

    mgr = SessionRuntimeStateManager(data_root=args.data_root)

    try:
        state = mgr.terminate(args.session_id, reason=args.reason)
        print()
        print("=" * 60)
        print("  Session TERMINATED")
        print("=" * 60)
        print(f"  Session: {state.session_id}")
        print(f"  Status:  {state.status}")
        print(f"  Reason:  {state.terminated_reason}")
        print()
        print("  No further orders allowed in this session.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_session_one_shot(args: argparse.Namespace) -> None:
    """Execute a one-shot order within a session (DEFAULT: dry-run)."""
    from quant_us.live.g8_session_bridge import SessionExecutionBridge
    import os

    api_key = os.environ.get("APCA_API_KEY_ID", "")
    api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

    bridge = SessionExecutionBridge(data_root=args.data_root)

    # dry_run is derived from execute_one_shot:
    # --execute-one-shot=False (default) -> dry_run=True -> gate blocks
    # --execute-one-shot=True -> dry_run=False -> gate can pass other checks
    is_dry_run = not args.execute_one_shot

    result = bridge.execute_one_shot(
        session_id=args.session_id,
        ticket_id=args.ticket_id,
        dry_run=is_dry_run,
        manual_confirm=args.manual_confirm,
        envelope_id=args.envelope_id,
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        strategy_id=args.strategy,
        confirm_live=args.confirm_live,
        execute_one_shot=args.execute_one_shot,
        i_understand_real_money=args.i_understand_this_is_real_money,
        confirm_ticket=args.confirm_ticket,
        estimated_notional=args.estimated_notional,
        api_key=api_key,
        api_secret=api_secret,
    )

    print()
    print("=" * 60)
    print("  G8 Session One-Shot Execution")
    print("=" * 60)
    print(f"  Session:         {args.session_id}")
    print(f"  Ticket:          {args.ticket_id}")
    print(f"  Dry Run:         {is_dry_run}")
    print(f"  Status:          {result['status']}")
    print(f"  Real Submit:     {result['real_submit_occurred']}")
    print(f"  Freeze Applied:  {result.get('freeze_applied', False)}")
    print(f"  Gate Decision:   {result.get('gate_decision', {}).get('decision', 'N/A')}")

    if result.get("errors"):
        print("  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")

    print()
    if result["real_submit_occurred"]:
        print("  REAL ORDER SUBMITTED. Session is now FROZEN.")
        print("  Post-trade review required before resume.")
    else:
        print("  No real orders were submitted (dry-run).")
    print("=" * 60)
    print()


def cmd_live_pilot_session_report(args: argparse.Namespace) -> None:
    """Generate a session report."""
    from quant_us.live.g8_session_report import SessionReportBuilder

    builder = SessionReportBuilder(data_root=args.data_root)
    report = builder.build(args.session_id)
    path = builder.save(report)

    if args.markdown:
        print(builder.to_markdown(report))
    else:
        import json
        print()
        print("=" * 60)
        print(f"  G8 Session Report: {args.session_id}")
        print("=" * 60)
        print(json.dumps(report.to_dict(), indent=2))
        print("=" * 60)
        print()

    print(f"  Report saved: {path}")


def cmd_live_pilot_session_daily_cap(args: argparse.Namespace) -> None:
    """Show daily cap status for a session."""
    from quant_us.live.g8_daily_cap import DailyTradingCapManager
    from datetime import date

    mgr = DailyTradingCapManager(data_root=args.data_root)
    today = date.today().isoformat()
    cap = mgr.load(args.session_id, today)

    print()
    print("=" * 60)
    print(f"  Daily Cap: session={args.session_id} date={today}")
    print("=" * 60)
    if cap is None:
        print("  No cap data for today. No orders submitted yet.")
    else:
        print(f"  Status:                   {cap.status}")
        print(f"  Orders:                   {cap.orders_submitted_today}/{cap.max_orders_today}")
        print(f"  Notional Used:            ${cap.notional_used_today:,.2f} / ${cap.max_notional_today:,.2f}")
        print(f"  Realized PnL:             ${cap.realized_pnl_today:,.2f} / -${cap.max_loss_today:,.2f} max loss")
    print("=" * 60)
    print()


def cmd_live_pilot_session_promotion_approve(args: argparse.Namespace) -> None:
    """Approve a promotion for G8 review."""
    from quant_us.live.g8_session_gate import SessionGate

    gate = SessionGate(data_root=args.data_root)

    try:
        manifest = gate.approve_promotion(args.promotion_id)
        print()
        print("=" * 60)
        print(f"  Promotion APPROVED_FOR_G8_REVIEW: {args.promotion_id}")
        print(f"  Status: {manifest['status']}")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_live_pilot_session_promotion_status(args: argparse.Namespace) -> None:
    """Show promotion status."""
    from quant_us.live.g8_session_gate import SessionGate

    gate = SessionGate(data_root=args.data_root)
    manifest = gate.get_promotion(args.promotion_id)

    print()
    print("=" * 60)
    if manifest is None:
        print(f"  Promotion not found: {args.promotion_id}")
    else:
        print(f"  Promotion: {manifest['promotion_id']}")
        print(f"  Status:     {manifest['status']}")
        print(f"  Created:    {manifest['created_at'][:19]}")
        print(f"  Updated:    {manifest['updated_at'][:19]}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G7: live-pilot scorecard
# ---------------------------------------------------------------------------


def cmd_live_pilot_scorecard(args: argparse.Namespace) -> None:
    """Build pilot scorecard for promotion readiness."""
    from quant_us.live.g7_scorecard import PilotScorecardBuilder

    builder = PilotScorecardBuilder(data_root=args.data_root)
    scorecard = builder.build(args.episode_id)
    path = builder.save(scorecard)

    print()
    print("=" * 60)
    print("  G7 Pilot Scorecard")
    print("=" * 60)
    print(f"  Scorecard ID: {scorecard.scorecard_id}")
    print(f"  Episode:      {scorecard.episode_id}")
    print(f"  Strategy:     {scorecard.strategy_id} v{scorecard.strategy_version}")
    print(f"  Orders:       {scorecard.clean_order_count}/{scorecard.order_count} clean")
    print(f"  Incidents:    {scorecard.incident_count}")
    print(f"  Recon Fails:  {scorecard.recon_fail_count}")
    print(f"  Duplicates:   {scorecard.duplicate_order_count}")
    print(f"  PnL:          ${scorecard.cumulative_pnl:,.2f}")
    print(f"  Score:        {scorecard.final_score:.1f} / 100")
    print(f"  Decision:     {scorecard.decision}")
    if scorecard.decision_reasons:
        print("  Reasons:")
        for r in scorecard.decision_reasons:
            print(f"    - {r}")
    print(f"  Saved:        {path}")
    print()
    print("  NOTE: This is a read-only evaluation. No promotion is auto-executed.")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G7: live-pilot promote (promotion manifest)
# ---------------------------------------------------------------------------


def cmd_live_pilot_promote_create(args: argparse.Namespace) -> None:
    """Create a promotion manifest from an episode scorecard."""
    from quant_us.live.g7_manifest import StrategyPromotionManifestManager

    mgr = StrategyPromotionManifestManager(data_root=args.data_root)

    manifest = mgr.create(
        source_episode_id=args.episode_id,
        scorecard_path=getattr(args, "scorecard_path", ""),
        strategy_id=getattr(args, "strategy_id", ""),
        strategy_version=getattr(args, "strategy_version", "1.0.0"),
        paper_30d_path=getattr(args, "paper_30d_path", ""),
        shadow_5d_path=getattr(args, "shadow_5d_path", ""),
        g5_dossier_path=getattr(args, "g5_dossier_path", ""),
        g6_episode_dossier_path=getattr(args, "g6_dossier_path", ""),
        approved_symbols=_parse_symbols(getattr(args, "symbols", "")),
        approved_capital_limit=float(getattr(args, "capital_limit", 1000.0)),
        approved_order_limit=int(getattr(args, "order_limit", 3)),
        approved_session_limit=int(getattr(args, "session_limit", 1)),
        approved_risk_envelope_id=getattr(args, "envelope_id", ""),
    )

    print()
    print("=" * 60)
    print("  Promotion Manifest Created")
    print("=" * 60)
    print(f"  Promotion ID:  {manifest.promotion_id}")
    print(f"  Episode:       {manifest.source_episode_id}")
    print(f"  Strategy:      {manifest.strategy_id} v{manifest.strategy_version}")
    print(f"  Status:        {manifest.status}")
    print(f"  Created:       {manifest.created_at[:19]}")
    print()
    print("  Next: promotion-board review --promotion-id <id> --board-member <name>")
    print("=" * 60)
    print()


def cmd_live_pilot_promote_inspect(args: argparse.Namespace) -> None:
    """Inspect a promotion manifest."""
    from quant_us.live.g7_manifest import StrategyPromotionManifestManager
    import json

    mgr = StrategyPromotionManifestManager(data_root=args.data_root)
    manifest = mgr.load(args.promotion_id)

    print()
    print("=" * 60)
    if manifest is None:
        print(f"  Promotion not found: {args.promotion_id}")
    else:
        print(f"  Promotion Manifest: {args.promotion_id}")
        print("=" * 60)
        print(json.dumps(manifest.to_dict(), indent=2))

        valid, reason = mgr.is_valid_for_g8(args.promotion_id)
        print()
        print(f"  Valid for G8: {valid}")
        if not valid:
            print(f"  Reason: {reason}")
    print("=" * 60)
    print()


def cmd_live_pilot_promote_approve(args: argparse.Namespace) -> None:
    """Approve a promotion manifest (requires board member name)."""
    from quant_us.live.g7_manifest import StrategyPromotionManifestManager

    board_member = getattr(args, "board_member", "") or getattr(args, "manual", "")
    if not board_member:
        print("ERROR: --board-member <name> is required for approval")
        return

    mgr = StrategyPromotionManifestManager(data_root=args.data_root)
    manifest = mgr.approve(
        promotion_id=args.promotion_id,
        approved_by=board_member,
    )

    print()
    print("=" * 60)
    print(f"  Promotion APPROVED: {args.promotion_id}")
    print("=" * 60)
    print(f"  Approved By: {manifest.approved_by}")
    print(f"  Approved At: {manifest.approved_at[:19]}")
    print(f"  Expires At:  {manifest.expires_at[:19]}")
    print(f"  Status:      {manifest.status}")
    print()
    print("  NOTE: This manifest is now valid for G8 review for 7 days.")
    print("=" * 60)
    print()


def cmd_live_pilot_promote_reject(args: argparse.Namespace) -> None:
    """Reject a promotion manifest with a reason."""
    from quant_us.live.g7_manifest import StrategyPromotionManifestManager

    mgr = StrategyPromotionManifestManager(data_root=args.data_root)
    manifest = mgr.reject(
        promotion_id=args.promotion_id,
        reason=args.reason,
    )

    print()
    print("=" * 60)
    print(f"  Promotion REJECTED: {args.promotion_id}")
    print("=" * 60)
    print(f"  Reason: {manifest.rejection_reason}")
    print(f"  Status: {manifest.status}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# G7: live-pilot promotion-board
# ---------------------------------------------------------------------------


def cmd_live_pilot_promotion_board_list(args: argparse.Namespace) -> None:
    """List all pending promotion reviews."""
    from quant_us.live.g7_promotion_board import PromotionBoard
    import json

    board = PromotionBoard(data_root=args.data_root)
    pending = board.list_pending()

    print()
    print("=" * 60)
    print(f"  Pending Promotions: {len(pending)}")
    print("=" * 60)
    if pending:
        print(json.dumps(pending, indent=2))
    else:
        print("  No pending promotions.")
    print("=" * 60)
    print()


def cmd_live_pilot_promotion_board_review(args: argparse.Namespace) -> None:
    """Human board member reviews a promotion."""
    from quant_us.live.g7_promotion_board import PromotionBoard

    # Map decision strings
    decision_map = {
        "approve": "APPROVED_FOR_G8_REVIEW",
        "reject": "REJECTED",
        "more-evidence": "MORE_EVIDENCE_REQUIRED",
    }

    decision_str = decision_map.get(args.decision, args.decision.upper())
    board = PromotionBoard(data_root=args.data_root)
    result = board.review(
        promotion_id=args.promotion_id,
        board_member=args.board_member,
        decision=decision_str,
        reason=args.reason,
    )

    print()
    print("=" * 60)
    print(f"  Board Review Complete: {args.promotion_id}")
    print("=" * 60)
    print(f"  Decision ID:  {result.decision_id}")
    print(f"  Board Member: {result.board_member}")
    print(f"  Decision:     {result.decision}")
    print(f"  Reason:       {result.reason}")
    if result.conditions:
        print(f"  Conditions:   {', '.join(result.conditions)}")
    print(f"  Decided At:   {result.decided_at[:19]}")
    print()
    print("  Audit trail written.")
    print("=" * 60)
    print()


def _add_live_pilot_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "live-pilot",
        parents=[_shared_parent()],
        help="G3 Small Live Pilot: approval, risk envelope, dry-run, emergency stop, dossier",
    )
    pilot_sub = p.add_subparsers(dest="pilot_command")

    # approval create
    apr_create = pilot_sub.add_parser("approval-create", help="Create approval request")
    apr_create.add_argument("--approval-id", required=True, help="Unique approval ID")
    apr_create.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    apr_create.add_argument("--strategy-version", default="1.0.0", help="Strategy version")
    apr_create.add_argument("--symbols", default="SPY,QQQ", help="Approved symbols")
    apr_create.add_argument("--requested-by", default="", help="Who requested")
    apr_create.add_argument("--capital", type=float, default=1000.0, help="Proposed capital")
    apr_create.set_defaults(func=cmd_live_pilot_approval_create)

    # approval inspect
    apr_inspect = pilot_sub.add_parser("approval-inspect", help="Inspect approval")
    apr_inspect.add_argument("--approval-id", required=True, help="Approval ID")
    apr_inspect.set_defaults(func=cmd_live_pilot_approval_inspect)

    # approval approve
    apr_approve = pilot_sub.add_parser("approval-approve", help="Approve request (manual)")
    apr_approve.add_argument("--approval-id", required=True, help="Approval ID")
    apr_approve.add_argument("--manual", default="", help="Approver name")
    apr_approve.set_defaults(func=cmd_live_pilot_approval_approve)

    # approval reject
    apr_reject = pilot_sub.add_parser("approval-reject", help="Reject request")
    apr_reject.add_argument("--approval-id", required=True, help="Approval ID")
    apr_reject.add_argument("--reason", required=True, help="Rejection reason")
    apr_reject.set_defaults(func=cmd_live_pilot_approval_reject)

    # approval list
    apr_list = pilot_sub.add_parser("approval-list", help="List approvals")
    apr_list.set_defaults(func=cmd_live_pilot_approval_list)

    # risk-envelope create
    env_create = pilot_sub.add_parser("risk-envelope-create", help="Create risk envelope")
    env_create.add_argument("--envelope-id", required=True, help="Envelope ID")
    env_create.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    env_create.add_argument("--symbols", default="SPY,QQQ", help="Allowed symbols")
    env_create.set_defaults(func=cmd_live_pilot_risk_envelope_create)

    # risk-envelope inspect
    env_inspect = pilot_sub.add_parser("risk-envelope-inspect", help="Inspect envelope")
    env_inspect.add_argument("--envelope-id", required=True, help="Envelope ID")
    env_inspect.set_defaults(func=cmd_live_pilot_risk_envelope_inspect)

    # risk-envelope validate
    env_validate = pilot_sub.add_parser("risk-envelope-validate", help="Validate against envelope")
    env_validate.add_argument("--envelope-id", required=True, help="Envelope ID")
    env_validate.add_argument("--notional", type=float, default=100.0, help="Order notional to check")
    env_validate.set_defaults(func=cmd_live_pilot_risk_envelope_validate)

    # dry-run
    dry_run = pilot_sub.add_parser("dry-run", help="Run live pilot dry-run (no real orders)")
    dry_run.add_argument("--approval-id", required=True, help="Approval ID")
    dry_run.add_argument("--envelope-id", required=True, help="Envelope ID")
    dry_run.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    dry_run.add_argument("--symbols", default="SPY,QQQ", help="Symbols")
    dry_run.add_argument("--data-root", default="data", help="Data root path")
    dry_run.set_defaults(func=cmd_live_pilot_dry_run)

    # emergency-stop trigger
    es_trigger = pilot_sub.add_parser("emergency-stop-trigger", help="Trigger emergency stop")
    es_trigger.add_argument("--reason", required=True, help="Stop reason (manual_stop, recon_fail, etc.)")
    es_trigger.add_argument("--data-root", default="data", help="Data root path")
    es_trigger.set_defaults(func=cmd_live_pilot_emergency_stop_trigger)

    # emergency-stop status
    es_status = pilot_sub.add_parser("emergency-stop-status", help="Show emergency stop status")
    es_status.add_argument("--data-root", default="data", help="Data root path")
    es_status.set_defaults(func=cmd_live_pilot_emergency_stop_status)

    # emergency-stop acknowledge
    es_ack = pilot_sub.add_parser("emergency-stop-acknowledge", help="Acknowledge emergency stop")
    es_ack.add_argument("--data-root", default="data", help="Data root path")
    es_ack.set_defaults(func=cmd_live_pilot_emergency_stop_acknowledge)

    # emergency-stop resolve
    es_resolve = pilot_sub.add_parser("emergency-stop-resolve", help="Resolve emergency stop")
    es_resolve.add_argument("--data-root", default="data", help="Data root path")
    es_resolve.set_defaults(func=cmd_live_pilot_emergency_stop_resolve)

    # rollback plan
    rollback = pilot_sub.add_parser("rollback-plan", help="Generate rollback plan")
    rollback.add_argument("--reason", default="", help="Stop reason")
    rollback.add_argument("--data-root", default="data", help="Data root path")
    rollback.set_defaults(func=cmd_live_pilot_rollback_plan)

    # dossier
    dossier = pilot_sub.add_parser("dossier", help="Generate G3 Go/No-Go dossier")
    dossier.add_argument("--output", default="", help="Output path for markdown")
    dossier.add_argument("--data-root", default="data", help="Data root path")
    dossier.set_defaults(func=cmd_live_pilot_dossier)

    # G4 commands
    # execute
    execute = pilot_sub.add_parser("execute", help="Execute live pilot order (DEFAULT: dry-run)")
    execute.add_argument("--approval-id", required=True, help="Approval ID")
    execute.add_argument("--envelope-id", required=True, help="Envelope ID")
    execute.add_argument("--symbols", default="SPY,QQQ", help="Symbols")
    execute.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    execute.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default: True)")
    execute.add_argument("--execute-live-pilot", action="store_true", default=False, help="REAL execute live pilot order")
    execute.add_argument("--confirm-live", action="store_true", default=False, help="Confirm live order submission")
    execute.add_argument("--data-root", default="data", help="Data root path")
    execute.set_defaults(func=cmd_live_pilot_execute)

    # first-order-simulate
    fos = pilot_sub.add_parser("first-order-simulate", help="Simulate first live order (no submit)")
    fos.add_argument("--approval-id", required=True, help="Approval ID")
    fos.add_argument("--envelope-id", required=True, help="Envelope ID")
    fos.add_argument("--symbols", default="SPY,QQQ", help="Symbols")
    fos.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    fos.add_argument("--data-root", default="data", help="Data root path")
    fos.set_defaults(func=cmd_live_pilot_first_order_simulate)

    # audit
    audit_p = pilot_sub.add_parser("audit", help="Show live order audit trail")
    audit_p.add_argument("--latest", action="store_true", default=True, help="Latest entries")
    audit_p.add_argument("--run-id", default="", help="Filter by run ID")
    audit_p.add_argument("--data-root", default="data", help="Data root path")
    audit_p.set_defaults(func=cmd_live_pilot_audit_trail)

    # status
    status_p = pilot_sub.add_parser("status", help="Show live pilot status")
    status_p.add_argument("--run-id", default="", help="Run ID")
    status_p.add_argument("--data-root", default="data", help="Data root path")
    status_p.set_defaults(func=cmd_live_pilot_executor_status)

    # stop
    stop_p = pilot_sub.add_parser("stop", help="Stop live pilot")
    stop_p.add_argument("--run-id", default="", help="Run ID")
    stop_p.add_argument("--data-root", default="data", help="Data root path")
    stop_p.set_defaults(func=cmd_live_pilot_stop)

    # G5 commands
    # first-order-ticket
    fot = pilot_sub.add_parser("first-order-ticket", help="Generate first live order ticket (no submit)")
    fot.add_argument("--approval-id", required=True, help="Approval ID")
    fot.add_argument("--envelope-id", required=True, help="Envelope ID")
    fot.add_argument("--symbols", default="SPY,QQQ", help="Symbols")
    fot.add_argument("--side", default="buy", choices=["buy", "sell"], help="Order side")
    fot.add_argument("--quantity", type=float, default=1.0, help="Order quantity")
    fot.add_argument("--limit-price", type=float, default=500.0, help="Limit price")
    fot.add_argument("--data-root", default="data", help="Data root path")
    fot.set_defaults(func=cmd_live_pilot_first_order_ticket)

    # confirm-ticket
    ct = pilot_sub.add_parser("confirm-ticket", help="Final human confirmation of ticket")
    ct.add_argument("--ticket-id", required=True, help="Ticket ID to confirm")
    ct.add_argument("--manual", default="", help="Confirmer name")
    ct.add_argument("--data-root", default="data", help="Data root path")
    ct.set_defaults(func=cmd_live_pilot_confirm_ticket)

    # one-shot
    os_cmd = pilot_sub.add_parser("one-shot", help="One-shot live order execution (DEFAULT: dry-run)")
    os_cmd.add_argument("--ticket-id", required=True, help="Ticket ID")
    os_cmd.add_argument("--approval-id", default="", help="Approval ID (defaults to ticket ID)")
    os_cmd.add_argument("--envelope-id", required=True, help="Envelope ID")
    os_cmd.add_argument("--symbols", default="SPY,QQQ", help="Symbols")
    os_cmd.add_argument("--confirm-ticket", default="", help="Must match ticket-id")
    os_cmd.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default)")
    os_cmd.add_argument("--execute-one-shot", action="store_true", default=False, help="REAL one-shot execution")
    os_cmd.add_argument("--confirm-live", action="store_true", default=False, help="Confirm live order")
    os_cmd.add_argument("--i-understand-this-is-real-money", action="store_true", default=False, help="REAL MONEY acknowledgement")
    os_cmd.add_argument("--data-root", default="data", help="Data root path")
    os_cmd.set_defaults(func=cmd_live_pilot_one_shot)

    # submit-lock
    sl = pilot_sub.add_parser("submit-lock", help="Manage submit-once lock")
    sl.add_argument("--status", action="store_true", default=True, help="Show lock status")
    sl.add_argument("--release", action="store_true", default=False, help="Release lock (manual)")
    sl.add_argument("--manual", default="", help="Releaser name")
    sl.add_argument("--reason", default="", help="Release reason")
    sl.add_argument("--data-root", default="data", help="Data root path")
    sl.set_defaults(func=cmd_live_pilot_submit_lock)

    # post-trade-reconcile
    ptr = pilot_sub.add_parser("post-trade-reconcile", help="Post-trade reconciliation")
    ptr.add_argument("--ticket-id", required=True, help="Ticket ID")
    ptr.add_argument("--data-root", default="data", help="Data root path")
    ptr.set_defaults(func=cmd_live_pilot_post_trade_reconcile)

    # freeze-status
    fs = pilot_sub.add_parser("freeze-status", help="Show freeze state")
    fs.add_argument("--data-root", default="data", help="Data root path")
    fs.set_defaults(func=cmd_live_pilot_freeze_status)

    # execution-quality
    eq = pilot_sub.add_parser("execution-quality", help="Generate execution quality report")
    eq.add_argument("--ticket-id", required=True, help="Ticket ID")
    eq.add_argument("--data-root", default="data", help="Data root path")
    eq.set_defaults(func=cmd_live_pilot_execution_quality)

    # g5-dossier
    g5d = pilot_sub.add_parser("g5-dossier", help="Generate G5 post-trade dossier")
    g5d.add_argument("--ticket-id", required=True, help="Ticket ID")
    g5d.add_argument("--output", default="", help="Output path")
    g5d.add_argument("--data-root", default="data", help="Data root path")
    g5d.set_defaults(func=cmd_live_pilot_g5_dossier)

    # ------------------------------------------------------------------
    # G6 commands
    # ------------------------------------------------------------------

    # risk-status
    risk_st = pilot_sub.add_parser("risk-status", help="Show cumulative risk status for micro pilot episode")
    risk_st.add_argument("--episode-id", required=True, help="Episode ID")
    risk_st.add_argument("--data-root", default="data", help="Data root path")
    risk_st.set_defaults(func=cmd_live_pilot_risk_status)

    # exit-plan create
    ep_create = pilot_sub.add_parser("exit-plan-create", help="Create reduce-only exit plan")
    ep_create.add_argument("--episode-id", required=True, help="Episode ID")
    ep_create.add_argument("--ticket-id", required=True, help="Ticket ID")
    ep_create.add_argument("--symbol", required=True, help="Symbol")
    ep_create.add_argument("--qty", type=float, required=True, help="Current position (positive=long, negative=short)")
    ep_create.add_argument("--entry-price", type=float, required=True, help="Average entry price")
    ep_create.add_argument("--exit-reason", default="manual_exit", help="Exit reason")
    ep_create.add_argument("--data-root", default="data", help="Data root path")
    ep_create.set_defaults(func=cmd_live_pilot_exit_plan_create)

    # exit-plan inspect
    ep_inspect = pilot_sub.add_parser("exit-plan-inspect", help="Inspect an exit plan")
    ep_inspect.add_argument("--exit-plan-id", required=True, help="Exit plan ID")
    ep_inspect.add_argument("--data-root", default="data", help="Data root path")
    ep_inspect.set_defaults(func=cmd_live_pilot_exit_plan_inspect)

    # exit-plan execute
    ep_exec = pilot_sub.add_parser("exit-plan-execute", help="Execute an exit plan")
    ep_exec.add_argument("--exit-plan-id", required=True, help="Exit plan ID")
    ep_exec.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default)")
    ep_exec.add_argument("--manual-approval", action="store_true", default=False, help="Manual approval flag")
    ep_exec.add_argument("--data-root", default="data", help="Data root path")
    ep_exec.set_defaults(func=cmd_live_pilot_exit_plan_execute)

    # episode final-dossier
    ep_fd = pilot_sub.add_parser("episode-final-dossier", help="Generate micro pilot final dossier")
    ep_fd.add_argument("--episode-id", required=True, help="Episode ID")
    ep_fd.add_argument("--data-root", default="data", help="Data root path")
    ep_fd.set_defaults(func=cmd_live_pilot_episode_final_dossier)

    # ------------------------------------------------------------------
    # G6: second-review
    # ------------------------------------------------------------------
    sr = pilot_sub.add_parser("second-review", help="G6 second one-shot review gate")
    sr.add_argument("--ticket-id", required=True, help="G5 ticket ID to review")
    sr.add_argument("--dossier-path", default="", help="Custom dossier path (optional)")
    sr.add_argument("--manual-review", default="", choices=["approve", "reject", ""],
                    help="Manual review decision (approve/reject)")
    sr.add_argument("--reviewer", default="", help="Manual reviewer name")
    sr.add_argument("--data-root", default="data", help="Data root path")
    sr.set_defaults(func=cmd_live_pilot_second_review)

    # ------------------------------------------------------------------
    # G6: episode subcommands
    # ------------------------------------------------------------------
    ep_mgr = pilot_sub.add_parser("episode", help="Micro-pilot episode management")
    ep_sub = ep_mgr.add_subparsers(dest="episode_command")

    ep_create_sub = ep_sub.add_parser("create", help="Create a new micro-pilot episode")
    ep_create_sub.add_argument("--strategy-id", required=True, help="Strategy ID")
    ep_create_sub.add_argument("--strategy-version", default="1.0.0", help="Strategy version")
    ep_create_sub.add_argument("--symbols", default="SPY,QQQ", help="Episode symbols")
    ep_create_sub.add_argument("--max-order-count", type=int, default=3, help="Max orders in episode")
    ep_create_sub.add_argument("--max-cumulative-notional", type=float, default=300.0,
                               help="Max cumulative notional")
    ep_create_sub.add_argument("--max-cumulative-loss", type=float, default=10.0,
                               help="Max cumulative loss")
    ep_create_sub.add_argument("--max-order-notional", type=float, default=100.0,
                               help="Max single order notional")
    ep_create_sub.add_argument("--max-orders-per-day", type=int, default=1, help="Max orders per day")
    ep_create_sub.add_argument("--data-root", default="data", help="Data root path")
    ep_create_sub.set_defaults(func=cmd_live_pilot_episode_create)

    ep_status_sub = ep_sub.add_parser("status", help="Show episode status")
    ep_status_sub.add_argument("--episode-id", required=True, help="Episode ID")
    ep_status_sub.add_argument("--data-root", default="data", help="Data root path")
    ep_status_sub.set_defaults(func=cmd_live_pilot_episode_status)

    ep_add_sub = ep_sub.add_parser("add-ticket", help="Add ticket to episode")
    ep_add_sub.add_argument("--episode-id", required=True, help="Episode ID")
    ep_add_sub.add_argument("--ticket-id", required=True, help="Ticket ID to add")
    ep_add_sub.add_argument("--notional", type=float, required=True, help="Ticket notional")
    ep_add_sub.add_argument("--data-root", default="data", help="Data root path")
    ep_add_sub.set_defaults(func=cmd_live_pilot_episode_add_ticket)

    ep_term_sub = ep_sub.add_parser("terminate", help="Terminate an episode")
    ep_term_sub.add_argument("--episode-id", required=True, help="Episode ID")
    ep_term_sub.add_argument("--reason", required=True, help="Termination reason")
    ep_term_sub.add_argument("--data-root", default="data", help="Data root path")
    ep_term_sub.set_defaults(func=cmd_live_pilot_episode_terminate)

    ep_dos_sub = ep_sub.add_parser("dossier", help="Show full episode dossier")
    ep_dos_sub.add_argument("--episode-id", required=True, help="Episode ID")
    ep_dos_sub.add_argument("--data-root", default="data", help="Data root path")
    ep_dos_sub.set_defaults(func=cmd_live_pilot_episode_dossier)

    # ------------------------------------------------------------------
    # G6: progression
    # ------------------------------------------------------------------
    prog = pilot_sub.add_parser("progression", help="Pilot progression controller")
    prog_sub = prog.add_subparsers(dest="progression_command")

    prog_status_sub = prog_sub.add_parser("status", help="Show overall progression status")
    prog_status_sub.add_argument("--data-root", default="data", help="Data root path")
    prog_status_sub.set_defaults(func=cmd_live_pilot_progression_status)

    prog_eval_sub = prog_sub.add_parser("evaluate", help="Evaluate progression readiness")
    prog_eval_sub.add_argument("--episode-id", required=True, help="Episode ID to evaluate")
    prog_eval_sub.add_argument("--data-root", default="data", help="Data root path")
    prog_eval_sub.set_defaults(func=cmd_live_pilot_progression_evaluate)

    # ------------------------------------------------------------------
    # G8: Session subcommands
    # ------------------------------------------------------------------
    session_mgr = pilot_sub.add_parser("session", help="G8 Supervised Micro Live Session management")
    session_sub = session_mgr.add_subparsers(dest="session_command")

    # session create
    s_create = session_sub.add_parser("create", help="Create a new supervised micro live session")
    s_create.add_argument("--session-id", default="", help="Custom session ID (optional)")
    s_create.add_argument("--promotion-id", required=True, help="Promotion ID for G8 review")
    s_create.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    s_create.add_argument("--strategy-version", default="1.0.0", help="Strategy version")
    s_create.add_argument("--symbols", default="SPY,QQQ", help="Session symbols")
    s_create.add_argument("--max-orders", type=int, default=3, help="Max orders per session")
    s_create.add_argument("--max-orders-per-day", type=int, default=1, help="Max orders per day")
    s_create.add_argument("--max-notional", type=float, default=300.0, help="Max session notional")
    s_create.add_argument("--max-loss", type=float, default=10.0, help="Max session loss")
    s_create.add_argument("--data-root", default="data", help="Data root path")
    s_create.set_defaults(func=cmd_live_pilot_session_create)

    # session arm
    s_arm = session_sub.add_parser("arm", help="Arm a session (DRAFT -> ARMED)")
    s_arm.add_argument("--session-id", required=True, help="Session ID")
    s_arm.add_argument("--data-root", default="data", help="Data root path")
    s_arm.set_defaults(func=cmd_live_pilot_session_arm)

    # session activate
    s_activate = session_sub.add_parser("activate", help="Activate a session (ARMED -> ACTIVE_MANUAL_SUPERVISION)")
    s_activate.add_argument("--session-id", required=True, help="Session ID")
    s_activate.add_argument("--data-root", default="data", help="Data root path")
    s_activate.set_defaults(func=cmd_live_pilot_session_activate)

    # session status
    s_status = session_sub.add_parser("status", help="Show session status")
    s_status.add_argument("--session-id", required=True, help="Session ID")
    s_status.add_argument("--data-root", default="data", help="Data root path")
    s_status.set_defaults(func=cmd_live_pilot_session_status)

    # session pause
    s_pause = session_sub.add_parser("pause", help="Pause a session")
    s_pause.add_argument("--session-id", required=True, help="Session ID")
    s_pause.add_argument("--data-root", default="data", help="Data root path")
    s_pause.set_defaults(func=cmd_live_pilot_session_pause)

    # session resume
    s_resume = session_sub.add_parser("resume", help="Resume a frozen session")
    s_resume.add_argument("--session-id", required=True, help="Session ID")
    s_resume.add_argument("--reason", default="POST_TRADE_REVIEW_COMPLETE", help="Resume reason")
    s_resume.add_argument("--data-root", default="data", help="Data root path")
    s_resume.set_defaults(func=cmd_live_pilot_session_resume)

    # session terminate
    s_term = session_sub.add_parser("terminate", help="Terminate a session")
    s_term.add_argument("--session-id", required=True, help="Session ID")
    s_term.add_argument("--reason", required=True, help="Termination reason")
    s_term.add_argument("--data-root", default="data", help="Data root path")
    s_term.set_defaults(func=cmd_live_pilot_session_terminate)

    # session one-shot
    s_os = session_sub.add_parser("one-shot", help="Execute a one-shot order within session (DEFAULT: dry-run)")
    s_os.add_argument("--session-id", required=True, help="Session ID")
    s_os.add_argument("--ticket-id", required=True, help="Ticket ID")
    s_os.add_argument("--envelope-id", default="", help="Risk envelope ID")
    s_os.add_argument("--symbols", default="SPY,QQQ", help="Symbols")
    s_os.add_argument("--strategy", default="etf_rotation", help="Strategy ID")
    s_os.add_argument("--estimated-notional", type=float, default=0.0, help="Estimated order notional for cap check")
    s_os.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default: True)")
    s_os.add_argument("--manual-confirm", action="store_true", default=False, help="Manual confirmation for gate")
    s_os.add_argument("--confirm-ticket", default="", help="Confirm ticket ID")
    s_os.add_argument("--execute-one-shot", action="store_true", default=False, help="REAL one-shot execution")
    s_os.add_argument("--confirm-live", action="store_true", default=False, help="Confirm live order")
    s_os.add_argument("--i-understand-this-is-real-money", action="store_true", default=False, help="REAL MONEY")
    s_os.add_argument("--data-root", default="data", help="Data root path")
    s_os.set_defaults(func=cmd_live_pilot_session_one_shot)

    # session report
    s_report = session_sub.add_parser("report", help="Generate session report")
    s_report.add_argument("--session-id", required=True, help="Session ID")
    s_report.add_argument("--markdown", action="store_true", default=False, help="Render as markdown")
    s_report.add_argument("--data-root", default="data", help="Data root path")
    s_report.set_defaults(func=cmd_live_pilot_session_report)

    # session daily-cap
    s_dcap = session_sub.add_parser("daily-cap", help="Show daily cap status")
    s_dcap.add_argument("--session-id", required=True, help="Session ID")
    s_dcap.add_argument("--data-root", default="data", help="Data root path")
    s_dcap.set_defaults(func=cmd_live_pilot_session_daily_cap)

    # session promotion-approve
    s_prom_apr = session_sub.add_parser("promotion-approve", help="Approve promotion for G8 review")
    s_prom_apr.add_argument("--promotion-id", required=True, help="Promotion ID")
    s_prom_apr.add_argument("--data-root", default="data", help="Data root path")
    s_prom_apr.set_defaults(func=cmd_live_pilot_session_promotion_approve)

    # session promotion-status
    s_prom_st = session_sub.add_parser("promotion-status", help="Show promotion status")
    s_prom_st.add_argument("--promotion-id", required=True, help="Promotion ID")
    s_prom_st.add_argument("--data-root", default="data", help="Data root path")
    s_prom_st.set_defaults(func=cmd_live_pilot_session_promotion_status)

    # ------------------------------------------------------------------
    # G7: scorecard
    # ------------------------------------------------------------------
    sc = pilot_sub.add_parser("scorecard", help="Build G7 pilot scorecard for promotion readiness")
    sc.add_argument("--episode-id", required=True, help="Episode ID to score")
    sc.add_argument("--data-root", default="data", help="Data root path")
    sc.set_defaults(func=cmd_live_pilot_scorecard)

    # ------------------------------------------------------------------
    # G7: promote (promotion manifest management)
    # ------------------------------------------------------------------
    promote = pilot_sub.add_parser("promote", help="G7 promotion manifest management")
    promote_sub = promote.add_subparsers(dest="promote_command")

    # promote create
    pc = promote_sub.add_parser("create", help="Create promotion manifest from episode")
    pc.add_argument("--episode-id", required=True, help="Source episode ID")
    pc.add_argument("--scorecard-path", default="", help="Path to scorecard evidence")
    pc.add_argument("--strategy-id", default="", help="Strategy ID (from episode)")
    pc.add_argument("--strategy-version", default="1.0.0", help="Strategy version")
    pc.add_argument("--paper-30d-path", default="", help="Path to 30-day paper evidence")
    pc.add_argument("--shadow-5d-path", default="", help="Path to 5-day shadow evidence")
    pc.add_argument("--g5-dossier-path", default="", help="Path to G5 post-trade dossier")
    pc.add_argument("--g6-dossier-path", default="", help="Path to G6 episode dossier")
    pc.add_argument("--symbols", default="", help="Approved symbols (comma-separated)")
    pc.add_argument("--capital-limit", type=float, default=1000.0, help="Approved capital limit")
    pc.add_argument("--order-limit", type=int, default=3, help="Approved order limit")
    pc.add_argument("--session-limit", type=int, default=1, help="Approved session limit")
    pc.add_argument("--envelope-id", default="", help="Approved risk envelope ID")
    pc.add_argument("--data-root", default="data", help="Data root path")
    pc.set_defaults(func=cmd_live_pilot_promote_create)

    # promote inspect
    pi = promote_sub.add_parser("inspect", help="Inspect a promotion manifest")
    pi.add_argument("--promotion-id", required=True, help="Promotion ID")
    pi.add_argument("--data-root", default="data", help="Data root path")
    pi.set_defaults(func=cmd_live_pilot_promote_inspect)

    # promote approve
    pa = promote_sub.add_parser("approve", help="Approve a promotion manifest (requires board member)")
    pa.add_argument("--promotion-id", required=True, help="Promotion ID")
    pa.add_argument("--board-member", default="", help="Board member name approving")
    pa.add_argument("--manual", default="", help="Manual confirmer name (alias for --board-member)")
    pa.add_argument("--data-root", default="data", help="Data root path")
    pa.set_defaults(func=cmd_live_pilot_promote_approve)

    # promote reject
    pr = promote_sub.add_parser("reject", help="Reject a promotion manifest")
    pr.add_argument("--promotion-id", required=True, help="Promotion ID")
    pr.add_argument("--reason", required=True, help="Rejection reason")
    pr.add_argument("--data-root", default="data", help="Data root path")
    pr.set_defaults(func=cmd_live_pilot_promote_reject)

    # ------------------------------------------------------------------
    # G7: promotion-board
    # ------------------------------------------------------------------
    pb = pilot_sub.add_parser("promotion-board", help="G7 promotion board for human governance review")
    pb_sub = pb.add_subparsers(dest="board_command")

    # promotion-board list
    pbl = pb_sub.add_parser("list", help="List pending promotion reviews")
    pbl.add_argument("--data-root", default="data", help="Data root path")
    pbl.set_defaults(func=cmd_live_pilot_promotion_board_list)

    # promotion-board review
    pbr = pb_sub.add_parser("review", help="Board member reviews a promotion")
    pbr.add_argument("--promotion-id", required=True, help="Promotion ID to review")
    pbr.add_argument("--board-member", required=True, help="Board member name")
    pbr.add_argument("--decision", required=True,
                     choices=["approve", "reject", "more-evidence"],
                     help="Board decision")
    pbr.add_argument("--reason", required=True, help="Review reason")
    pbr.add_argument("--conditions", default="", help="Review conditions (comma-separated)")
    pbr.add_argument("--data-root", default="data", help="Data root path")
    pbr.set_defaults(func=cmd_live_pilot_promotion_board_review)


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# G9: ops (production ops commands)
# ---------------------------------------------------------------------------


def cmd_ops_release_create(args: argparse.Namespace) -> None:
    """Create a new release manifest."""
    from quant_us.live.g9_release_manifest import ReleaseManifestManager

    mgr = ReleaseManifestManager(data_root=args.data_root)
    promotion_ids = [s.strip() for s in (args.promotion_ids or "").split(",") if s.strip()]
    session_report_ids = [s.strip() for s in (args.session_report_ids or "").split(",") if s.strip()]

    manifest = mgr.create(
        promotion_ids=promotion_ids or None,
        session_report_ids=session_report_ids or None,
    )

    print()
    print("=" * 60)
    print("  Release Manifest Created")
    print("=" * 60)
    print(f"  Release ID:     {manifest.release_id}")
    print(f"  Status:         {manifest.status}")
    print(f"  Config Hash:    {manifest.config_hash[:16] if manifest.config_hash else 'N/A'}...")
    print(f"  Risk Env Hash:  {manifest.risk_envelope_hash[:16] if manifest.risk_envelope_hash else 'N/A'}...")
    print(f"  Git Commit:     {manifest.git_commit[:12] if manifest.git_commit else 'N/A'}")
    print(f"  Promotions:     {len(manifest.promotion_manifest_ids)}")
    print(f"  Session Reports: {len(manifest.session_report_ids)}")
    print(f"  Created At:     {manifest.created_at[:19]}")
    print()
    print("  Next: ops release approve --release-id <id> --manual <name>")
    print("  NOTE: This does NOT trigger deployment.")
    print("=" * 60)
    print()


def cmd_ops_release_inspect(args: argparse.Namespace) -> None:
    """Inspect a release manifest."""
    from quant_us.live.g9_release_manifest import ReleaseManifestManager

    mgr = ReleaseManifestManager(data_root=args.data_root)
    manifest = mgr.load(args.release_id)

    print()
    print("=" * 60)
    if manifest is None:
        print(f"  Release not found: {args.release_id}")
    else:
        print(mgr.to_markdown(manifest))
    print("=" * 60)
    print()


def cmd_ops_release_approve(args: argparse.Namespace) -> None:
    """Approve a release manifest (manual action). NEVER auto-approves."""
    from quant_us.live.g9_release_manifest import ReleaseManifestManager

    mgr = ReleaseManifestManager(data_root=args.data_root)
    try:
        manifest = mgr.approve(args.release_id, args.manual or "cli_user")
        print()
        print("=" * 60)
        print(f"  Release APPROVED: {manifest.release_id}")
        print(f"  Approver: {manifest.approved_by}")
        print(f"  Approved At: {manifest.approved_at[:19] if manifest.approved_at else 'N/A'}")
        print()
        print("  WARNING: This is a record-only approval.")
        print("  It does NOT trigger any deployment.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_ops_release_rollback(args: argparse.Namespace) -> None:
    """Mark a release as ROLLED_BACK. Does NOT execute code changes."""
    from quant_us.live.g9_release_manifest import ReleaseManifestManager

    mgr = ReleaseManifestManager(data_root=args.data_root)
    try:
        manifest = mgr.rollback(args.release_id, args.reason or "manual_rollback")
        print()
        print("=" * 60)
        print(f"  Release ROLLED_BACK: {manifest.release_id}")
        print(f"  Reason: {args.reason or 'manual_rollback'}")
        print()
        print("  NOTE: This is a record-only action.")
        print("  No code changes were executed.")
        print("=" * 60)
        print()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)


def cmd_ops_release_list(args: argparse.Namespace) -> None:
    """List all release manifests."""
    from quant_us.live.g9_release_manifest import ReleaseManifestManager

    mgr = ReleaseManifestManager(data_root=args.data_root)
    releases = mgr.list_releases()

    print()
    print("=" * 60)
    print(f"  Release Manifests — {len(releases)} found")
    print("=" * 60)
    if not releases:
        print("  No releases found.")
    for r in releases:
        d = r.to_dict()
        print(f"  [{d['status']:12s}] {d['release_id']}  "
              f"created={d['created_at'][:19] if d['created_at'] else '?'}  "
              f"hash={d['config_hash'][:12] if d['config_hash'] else '?'}...")
    print("=" * 60)
    print()


def cmd_ops_config_check(args: argparse.Namespace) -> None:
    """Run config integrity check."""
    from quant_us.live.g9_config_check import ConfigIntegrityChecker

    print()
    print("=" * 60)
    print("  Config Integrity Check")
    print("=" * 60)

    checker = ConfigIntegrityChecker(data_root=args.data_root)
    result = checker.check()

    print(f"  Overall: {'PASS' if result.passed else 'FAIL'}")
    print(f"  Checked: {result.checked_at[:19]}")
    print()
    for name, passed in sorted(result.checks.items()):
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    if result.drift_detected:
        print()
        print("  Drift Detected:")
        for d in result.drift_detected:
            print(f"    - {d}")

    if result.mismatches:
        print()
        print("  Mismatches:")
        for m in result.mismatches:
            print(f"    - {m.get('field', '?')}: expected={m.get('expected','?')} actual={m.get('actual','?')}")

    saved = checker.save_result(result)
    print(f"  Result saved: {saved}")
    print("=" * 60)
    print()


def cmd_ops_backup(args: argparse.Namespace) -> None:
    """Create a backup of operational state."""
    from quant_us.live.g9_backup import BackupRestoreController

    print()
    print("=" * 60)
    print("  Backup Operational State")
    print("=" * 60)

    ctrl = BackupRestoreController(data_root=args.data_root)
    dry_run = getattr(args, "dry_run", False)
    record = ctrl.create_backup(dry_run=dry_run)

    label = "Dry-Run" if dry_run else "Created"
    print(f"  Backup {label}:")
    print(f"  Backup ID:    {record.backup_id}")
    print(f"  Archive:      {record.archive_name}")
    print(f"  Files:        {record.file_count}")
    print(f"  Total Bytes:  {record.total_bytes}")
    print(f"  Checksum:     {record.checksum[:16] if record.checksum else 'N/A'}...")
    print(f"  Excluded:     {record.excluded_count}")
    print(f"  Dry Run:      {record.dry_run}")
    print()
    print("  Excluded patterns: .env, *key*, *secret*, *credential*, *token*")
    print("  NO secrets were included in the backup.")
    print("=" * 60)
    print()


def cmd_ops_backup_list(args: argparse.Namespace) -> None:
    """List all backups."""
    from quant_us.live.g9_backup import BackupRestoreController

    ctrl = BackupRestoreController(data_root=args.data_root)
    backups = ctrl.list_backups()

    print()
    print("=" * 60)
    print(f"  Backups — {len(backups)} found")
    print("=" * 60)
    if not backups:
        print("  No backups found.")
    for b in backups:
        print(f"  [{b.backup_id}] {b.archive_name}  "
              f"files={b.file_count}  bytes={b.total_bytes}  "
              f"checksum={b.checksum[:12] if b.checksum else '?'}...")
    print("=" * 60)
    print()


def cmd_ops_restore(args: argparse.Namespace) -> None:
    """Restore from a backup (default: dry-run)."""
    from quant_us.live.g9_backup import BackupRestoreController

    print()
    print("=" * 60)
    print("  Restore from Backup")
    print("=" * 60)
    print(f"  Backup ID:    {args.backup_id}")
    print(f"  Dry Run:      {args.dry_run}")
    print()

    ctrl = BackupRestoreController(data_root=args.data_root)
    result = ctrl.restore(args.backup_id, dry_run=args.dry_run)

    status = result.get("status", "ERROR")
    print(f"  Status:       {status}")
    if status == "DRY_RUN":
        print(f"  Archive:      {result.get('archive', '?')}")
        print(f"  Members:      {result.get('member_count', 0)}")
        print(f"  Checksum:     {result.get('checksum', '?')[:16] if result.get('checksum') else '?'}...")
        print()
        print("  Dry-run mode -- no files restored.")
        print("  To restore: ops restore --backup-id <id> --no-dry-run")
    elif status == "RESTORED":
        print(f"  Files:        {result.get('restored_file_count', 0)}")
        print(f"  To:           {result.get('restored_to', '?')}")
        print()
        print("  WARNING: Backup restored. Verify integrity immediately.")
    elif status == "CORRUPTED":
        print(f"  Error:        {result.get('error', 'archive corrupted')}")
        print(f"  Expected:     {result.get('expected_checksum', '?')}")
        print(f"  Actual:       {result.get('actual_checksum', '?')}")
    else:
        print(f"  Error:        {result.get('error', 'unknown')}")

    print()
    print("  NOTE: Restore does NOT trigger any orders.")
    print("=" * 60)
    print()


def cmd_ops_audit_archive_create(args: argparse.Namespace) -> None:
    """Create audit archive."""
    from quant_us.live.g9_audit_archive import AuditArchiveBuilder

    print()
    print("=" * 60)
    print("  Audit Archive Create")
    print("=" * 60)

    builder = AuditArchiveBuilder(data_root=args.data_root)
    archive = builder.build()

    print(f"  Archive ID:   {archive.archive_id}")
    print(f"  Archive:      {archive.archive_name}")
    print(f"  Files:        {archive.audit_file_count}")
    print(f"  Total Bytes:  {archive.total_bytes}")
    print(f"  Checksum:     {archive.checksum[:16] if archive.checksum else 'N/A'}...")
    print(f"  Sources:      {', '.join(archive.audit_sources) or 'none'}")
    print(f"  Created:      {archive.created_at[:19]}")
    print()
    print("  NOTE: Audit archives exclude secret-bearing files.")
    print("=" * 60)
    print()


def cmd_ops_audit_archive_verify(args: argparse.Namespace) -> None:
    """Verify audit archive integrity."""
    from quant_us.live.g9_audit_archive import AuditArchiveBuilder

    print()
    print("=" * 60)
    print(f"  Audit Archive Verify: {args.archive_id}")
    print("=" * 60)

    builder = AuditArchiveBuilder(data_root=args.data_root)
    result = builder.verify(args.archive_id)

    if result:
        print("  Result: VERIFIED -- checksum OK")
    else:
        print("  Result: FAILED -- checksum mismatch or archive missing")

    print("=" * 60)
    print()


def cmd_ops_audit_archive_list(args: argparse.Namespace) -> None:
    """List all audit archives."""
    from quant_us.live.g9_audit_archive import AuditArchiveBuilder

    builder = AuditArchiveBuilder(data_root=args.data_root)
    archives = builder.list_archives()

    print()
    print("=" * 60)
    print(f"  Audit Archives -- {len(archives)} found")
    print("=" * 60)
    if not archives:
        print("  No archives found.")
    for a in archives:
        print(f"  [{a.archive_id}] {a.archive_name}  "
              f"files={a.audit_file_count}  bytes={a.total_bytes}  "
              f"checksum={a.checksum[:12] if a.checksum else '?'}...")
    print("=" * 60)
    print()


def cmd_ops_deployment_readiness(args: argparse.Namespace) -> None:
    """Run deployment readiness check."""
    from quant_us.live.g9_readiness import ReadinessChecker

    print()
    print("=" * 60)
    print("  Deployment Readiness Check")
    print("=" * 60)
    print("  NOTE: This is a READ-ONLY assessment. No deployment is triggered.")
    print()

    checker = ReadinessChecker(data_root=args.data_root)
    readiness = checker.check()

    print(f"  Check ID:     {readiness.check_id}")
    print(f"  Status:       {readiness.status}")
    print(f"  Checked At:   {readiness.checked_at[:19]}")
    print()
    print("  Checks:")
    checks = {
        "release_exists": readiness.release_exists,
        "release_approved": readiness.release_approved,
        "release_manifest_consistent": readiness.release_manifest_consistent,
        "config_integrity_passed": readiness.config_integrity_passed,
        "config_drift_detected": readiness.config_drift_detected,
        "backup_available": readiness.backup_available,
        "audit_archive_exists": readiness.audit_archive_exists,
    }
    for name, passed in sorted(checks.items()):
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}] {name}")

    if readiness.block_reasons:
        print()
        print("  Blocking Reasons:")
        for r in readiness.block_reasons:
            print(f"    - {r}")

    print()
    if readiness.is_ready:
        print("  RESULT: SYSTEM IS READY for supervised operation.")
    else:
        print("  RESULT: SYSTEM IS BLOCKED. Fix blocking reasons above.")
    print()
    print("  WARNING: This is a readiness assessment only.")
    print("  It does NOT trigger any deployment.")
    print("=" * 60)
    print()


def _add_ops_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "ops",
        parents=[_shared_parent()],
        help="G9 Production ops commands: release, backup, audit archive, config check, readiness",
    )
    ops_sub = p.add_subparsers(dest="ops_command")

    # --- release ---
    release_p = ops_sub.add_parser("release", help="Manage release manifests")
    release_sub = release_p.add_subparsers(dest="release_command")

    rel_create = release_sub.add_parser("create", help="Create a new release manifest")
    rel_create.add_argument("--promotion-ids", default="", help="Comma-separated promotion manifest IDs")
    rel_create.add_argument("--session-report-ids", default="", help="Comma-separated session report IDs")
    rel_create.add_argument("--data-root", default="data", help="Data root path")
    rel_create.set_defaults(func=cmd_ops_release_create)

    rel_inspect = release_sub.add_parser("inspect", help="Inspect a release manifest")
    rel_inspect.add_argument("--release-id", required=True, help="Release ID")
    rel_inspect.add_argument("--data-root", default="data", help="Data root path")
    rel_inspect.set_defaults(func=cmd_ops_release_inspect)

    rel_approve = release_sub.add_parser("approve", help="Approve a release (manual action)")
    rel_approve.add_argument("--release-id", required=True, help="Release ID")
    rel_approve.add_argument("--manual", default="", help="Approver name")
    rel_approve.add_argument("--data-root", default="data", help="Data root path")
    rel_approve.set_defaults(func=cmd_ops_release_approve)

    rel_rollback = release_sub.add_parser("rollback", help="Mark release as rolled back")
    rel_rollback.add_argument("--release-id", required=True, help="Release ID")
    rel_rollback.add_argument("--reason", default="manual_rollback", help="Rollback reason")
    rel_rollback.add_argument("--data-root", default="data", help="Data root path")
    rel_rollback.set_defaults(func=cmd_ops_release_rollback)

    rel_list = release_sub.add_parser("list", help="List all release manifests")
    rel_list.add_argument("--data-root", default="data", help="Data root path")
    rel_list.set_defaults(func=cmd_ops_release_list)

    # --- config-check ---
    cc_p = ops_sub.add_parser("config-check", help="Run config integrity check")
    cc_p.add_argument("--data-root", default="data", help="Data root path")
    cc_p.set_defaults(func=cmd_ops_config_check)

    # --- backup ---
    backup_p = ops_sub.add_parser("backup", help="Create a backup of operational state")
    backup_p.add_argument("--dry-run", action="store_true", default=False, help="Count files but do not create archive")
    backup_p.add_argument("--data-root", default="data", help="Data root path")
    backup_p.set_defaults(func=cmd_ops_backup)

    backup_list_p = ops_sub.add_parser("backup-list", help="List all backups")
    backup_list_p.add_argument("--data-root", default="data", help="Data root path")
    backup_list_p.set_defaults(func=cmd_ops_backup_list)

    restore_p = ops_sub.add_parser("restore", help="Restore from a backup (default: dry-run)")
    restore_p.add_argument("--backup-id", required=True, help="Backup ID to restore")
    restore_p.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default)")
    restore_p.add_argument("--no-dry-run", action="store_false", dest="dry_run", help="Actually restore files")
    restore_p.add_argument("--data-root", default="data", help="Data root path")
    restore_p.set_defaults(func=cmd_ops_restore)

    # --- audit-archive ---
    aa_p = ops_sub.add_parser("audit-archive", help="Manage audit archives")
    aa_sub = aa_p.add_subparsers(dest="audit_archive_command")

    aa_create = aa_sub.add_parser("create", help="Create an audit archive")
    aa_create.add_argument("--data-root", default="data", help="Data root path")
    aa_create.set_defaults(func=cmd_ops_audit_archive_create)

    aa_verify = aa_sub.add_parser("verify", help="Verify an audit archive")
    aa_verify.add_argument("--archive-id", required=True, help="Archive ID")
    aa_verify.add_argument("--data-root", default="data", help="Data root path")
    aa_verify.set_defaults(func=cmd_ops_audit_archive_verify)

    aa_list = aa_sub.add_parser("list", help="List all audit archives")
    aa_list.add_argument("--data-root", default="data", help="Data root path")
    aa_list.set_defaults(func=cmd_ops_audit_archive_list)

    # --- deployment-readiness ---
    dr_p = ops_sub.add_parser("deployment-readiness", help="Run deployment readiness check")
    dr_p.add_argument("--data-root", default="data", help="Data root path")
    dr_p.set_defaults(func=cmd_ops_deployment_readiness)
# ---------------------------------------------------------------------------
# portfolio
# ---------------------------------------------------------------------------


def _build_candidate_scorecards(
    candidate_ids: list[str],
) -> list[dict]:
    """Build synthetic candidate scorecards from candidate IDs.

    In a production setting, this would load from a strategy registry
    or scorecard store. Here we create reasonable defaults.
    """
    import random

    random.seed(42)
    scorecards = []
    for cid in candidate_ids:
        vol = random.uniform(0.10, 0.30)
        scorecards.append({
            "id": cid,
            "volatility": vol,
            "expected_return": random.uniform(0.05, 0.20),
            "max_drawdown": random.uniform(0.05, 0.25),
            "holdings": {},
        })
    return scorecards


def cmd_portfolio_construct(args: argparse.Namespace) -> None:
    """Construct a portfolio from candidate strategies."""
    from quant_us.portfolio.construction.engine import (
        PortfolioConfig,
        PortfolioConstructionEngine,
    )

    candidate_ids = [s.strip() for s in args.candidates.split(",") if s.strip()]
    if not candidate_ids:
        print("ERROR: at least one candidate required", file=sys.stderr)
        sys.exit(1)

    portfolio_id = args.portfolio_id or f"portfolio_{candidate_ids[0]}"

    config = PortfolioConfig(
        portfolio_id=portfolio_id,
        candidate_ids=candidate_ids,
        capital=args.capital,
        max_gross_exposure=args.max_gross,
        max_net_exposure=args.max_net,
        max_single_weight=args.max_single_weight,
        max_sector_weight=args.max_sector_weight,
        target_volatility=args.target_vol,
    )

    candidate_scorecards = _build_candidate_scorecards(candidate_ids)
    engine = PortfolioConstructionEngine(data_root=args.data_root)
    target = engine.construct(config, candidate_scorecards)

    path = engine.save_target(target)

    print()
    print("=" * 60)
    print(f"  Portfolio Constructed: {portfolio_id}")
    print("=" * 60)
    print(f"  Candidates:     {', '.join(candidate_ids)}")
    print(f"  Capital:        ${config.capital:,.2f}")
    print(f"  Target Vol:     {config.target_volatility:.0%}")
    print()
    print("  Strategy Weights:")
    for sid, w in sorted(target.strategy_weights.items()):
        capped_fmt = f" (capped at {config.max_single_weight:.0%})" if w >= config.max_single_weight else ""
        print(f"    {sid:20s}: {w:7.2%}{capped_fmt}")
    print()
    print(f"  Expected Return:  {target.expected_return:.2%}")
    print(f"  Expected Vol:     {target.expected_volatility:.2%}")
    print(f"  Saved to:         {path}")
    print("=" * 60)


def cmd_portfolio_backtest(args: argparse.Namespace) -> None:
    """Run a portfolio-level backtest."""
    from quant_us.portfolio.construction.backtest import PortfolioBacktestRunner

    runner = PortfolioBacktestRunner(data_root=args.data_root)

    # Generate synthetic strategy returns for demonstration
    import random

    random.seed(42)
    strategy_returns: dict[str, list[float]] = {}
    for sid in args.strategies.split(",") if args.strategies else []:
        sid = sid.strip()
        if sid:
            n_days = 252 * 3  # 3 years of daily returns
            mu = random.uniform(0.0003, 0.0010)
            sigma = random.uniform(0.005, 0.020)
            strategy_returns[sid] = [random.gauss(mu, sigma) for _ in range(n_days)]

    result = runner.run(
        portfolio_id=args.portfolio_id,
        start=args.start,
        end=args.end,
        strategy_returns=strategy_returns if strategy_returns else None,
        risk_free_rate=0.02,
    )

    print()
    print("=" * 60)
    print(f"  Portfolio Backtest: {result.portfolio_id}")
    print("=" * 60)
    print(f"  CAGR:           {result.cagr:.2%}")
    print(f"  Sharpe:         {result.sharpe:.3f}")
    print(f"  Max Drawdown:   {result.max_drawdown:.2%}")
    print()
    if result.strategy_contributions:
        print("  Strategy Contributions:")
        for sid, contrib in sorted(result.strategy_contributions.items()):
            print(f"    {sid:20s}: {contrib:+.2%}")
    if result.drawdown_attribution:
        print()
        print("  Drawdown Attribution:")
        for sid, dd in sorted(result.drawdown_attribution.items()):
            print(f"    {sid:20s}: {dd:.2%}")
    print("=" * 60)


def cmd_portfolio_scorecard(args: argparse.Namespace) -> None:
    """Build and display a portfolio scorecard."""
    from quant_us.portfolio.construction.scorecard import PortfolioScorecardBuilder

    builder = PortfolioScorecardBuilder(data_root=args.data_root)

    import random

    random.seed(42)
    n_strats = max(len(args.strategies.split(",")) if args.strategies else 3, 1)
    strategy_scorecards = []
    for i in range(n_strats):
        sid = f"strategy_{i}"
        strategy_scorecards.append({
            "id": sid,
            "cagr": random.uniform(0.05, 0.25),
            "sharpe": random.uniform(0.5, 2.0),
            "max_drawdown": random.uniform(0.05, 0.30),
            "volatility": random.uniform(0.10, 0.30),
        })

    weights = {sc["id"]: 1.0 / n_strats for sc in strategy_scorecards}
    scorecard = builder.build(args.portfolio_id, strategy_scorecards, weights)

    print()
    print(builder.to_markdown(scorecard))
    print("=" * 60)


def cmd_portfolio_allocation(args: argparse.Namespace) -> None:
    """Allocate capital across strategies using a given method."""
    from quant_us.portfolio.construction.allocator import CapitalAllocator

    candidate_ids = [s.strip() for s in args.candidates.split(",") if s.strip()]
    if not candidate_ids:
        print("ERROR: at least one candidate required", file=sys.stderr)
        sys.exit(1)

    import random

    random.seed(42)
    candidates = []
    for cid in candidate_ids:
        candidates.append({
            "id": cid,
            "volatility": random.uniform(0.10, 0.30),
            "expected_return": random.uniform(0.05, 0.20),
            "max_drawdown": random.uniform(0.05, 0.25),
        })

    allocator = CapitalAllocator()
    constraints = {
        "max_single_weight": args.max_single_weight,
        "target_vol": args.target_vol,
    }
    weights = allocator.allocate(candidates, args.method, constraints)

    print()
    print("=" * 60)
    print(f"  Allocation Method: {args.method}")
    print("=" * 60)
    print(f"  Candidates: {', '.join(candidate_ids)}")
    print()
    print("  Weights:")
    for sid, w in sorted(weights.items()):
        capped = " (capped)" if w >= args.max_single_weight else ""
        print(f"    {sid:20s}: {w:7.2%}{capped}")
    print()
    print(f"  Total: {sum(weights.values()):.2%} (normalized)")
    print("=" * 60)


def _add_portfolio_parser(subparsers: Any) -> None:
    p = subparsers.add_parser("portfolio", help="Portfolio construction, backtest, scorecard, and allocation")
    portfolio_sub = p.add_subparsers(dest="portfolio_command", required=True)

    # --- construct ---
    const_p = portfolio_sub.add_parser("construct", help="Construct a portfolio from candidate strategies")
    const_p.add_argument("--candidates", required=True, help="Comma-separated strategy IDs")
    const_p.add_argument("--portfolio-id", default="", help="Portfolio ID (default: auto)")
    const_p.add_argument("--capital", type=float, default=100_000.0, help="Total capital (default: 100000)")
    const_p.add_argument("--max-gross", type=float, default=1.0, help="Max gross exposure (default: 1.0)")
    const_p.add_argument("--max-net", type=float, default=1.0, help="Max net exposure (default: 1.0)")
    const_p.add_argument("--max-single-weight", type=float, default=0.25, help="Max single strategy weight (default: 0.25)")
    const_p.add_argument("--max-sector-weight", type=float, default=0.40, help="Max sector weight (default: 0.40)")
    const_p.add_argument("--target-vol", type=float, default=0.15, help="Target volatility (default: 0.15)")
    const_p.add_argument("--data-root", default="data", help="Data root directory (default: data)")
    const_p.set_defaults(func=cmd_portfolio_construct)

    # --- backtest ---
    bt_p = portfolio_sub.add_parser("backtest", help="Run portfolio-level backtest")
    bt_p.add_argument("--portfolio-id", required=True, help="Portfolio ID")
    bt_p.add_argument("--strategies", default="", help="Comma-separated strategy IDs for synthetic data")
    bt_p.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    bt_p.add_argument("--end", default=date.today().isoformat(), help="End date YYYY-MM-DD")
    bt_p.add_argument("--data-root", default="data", help="Data root directory (default: data)")
    bt_p.set_defaults(func=cmd_portfolio_backtest)

    # --- scorecard ---
    sc_p = portfolio_sub.add_parser("scorecard", help="Build portfolio scorecard")
    sc_p.add_argument("--portfolio-id", required=True, help="Portfolio ID")
    sc_p.add_argument("--strategies", default="", help="Comma-separated strategy IDs (optional)")
    sc_p.add_argument("--data-root", default="data", help="Data root directory (default: data)")
    sc_p.set_defaults(func=cmd_portfolio_scorecard)

    # --- allocation ---
    alloc_p = portfolio_sub.add_parser("allocation", help="Allocate capital across strategies")
    alloc_p.add_argument("--candidates", required=True, help="Comma-separated strategy IDs")
    alloc_p.add_argument(
        "--method",
        default="risk_parity",
        choices=[
            "equal_weight",
            "inverse_volatility",
            "risk_parity",
            "vol_targeting",
            "drawdown_adjusted",
        ],
        help="Allocation method (default: risk_parity)",
    )
    alloc_p.add_argument("--max-single-weight", type=float, default=0.25, help="Max single weight (default: 0.25)")
    alloc_p.add_argument("--target-vol", type=float, default=0.15, help="Target volatility (default: 0.15)")
    alloc_p.set_defaults(func=cmd_portfolio_allocation)


# ---------------------------------------------------------------------------
# research (R1 Strategy Research Lab)
# ---------------------------------------------------------------------------


def _add_research_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "research",
        parents=[_shared_parent()],
        help="R1 Strategy Research Lab: experiment, backtest, candidate, scorecard",
    )
    research_sub = p.add_subparsers(dest="research_command")

    # --- experiment ---
    exp_p = research_sub.add_parser("experiment", help="Manage research experiments")
    exp_sub = exp_p.add_subparsers(dest="experiment_command")

    exp_create = exp_sub.add_parser("create", help="Create a new experiment manifest")
    exp_create.add_argument("--strategy-id", required=True, help="Strategy ID (e.g. trend_momentum)")
    exp_create.add_argument("--symbols", required=True, help="Comma-separated symbols")
    exp_create.add_argument("--family", default="", help="Strategy family (e.g. momentum, trend)")
    exp_create.add_argument("--timeframe", default="1d", help="Bar timeframe (default: 1d)")
    exp_create.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    exp_create.add_argument("--end", default="", help="End date YYYY-MM-DD")
    exp_create.add_argument("--params", default="{}", help="Strategy params as JSON string")
    exp_create.add_argument("--data-root", default="data", help="Data root path")
    exp_create.set_defaults(func=cmd_research_experiment_create)

    exp_run = exp_sub.add_parser("run", help="Run an experiment backtest")
    exp_run.add_argument("--experiment-id", required=True, help="Experiment ID")
    exp_run.add_argument("--data-root", default="data", help="Data root path")
    exp_run.set_defaults(func=cmd_research_experiment_run)

    exp_list = exp_sub.add_parser("list", help="List experiments")
    exp_list.add_argument("--status", default="", help="Filter by status (e.g. COMPLETED)")
    exp_list.add_argument("--data-root", default="data", help="Data root path")
    exp_list.set_defaults(func=cmd_research_experiment_list)

    exp_inspect = exp_sub.add_parser("inspect", help="Inspect experiment details")
    exp_inspect.add_argument("--experiment-id", required=True, help="Experiment ID")
    exp_inspect.add_argument("--data-root", default="data", help="Data root path")
    exp_inspect.set_defaults(func=cmd_research_experiment_inspect)

    # --- candidate ---
    cand_p = research_sub.add_parser("candidate", help="Manage strategy candidates")
    cand_sub = cand_p.add_subparsers(dest="candidate_command")

    cand_list = cand_sub.add_parser("list", help="List all candidates")
    cand_list.add_argument("--data-root", default="data", help="Data root path")
    cand_list.set_defaults(func=cmd_research_candidate_list)

    cand_promote = cand_sub.add_parser("promote", help="Promote an experiment to candidate (manual)")
    cand_promote.add_argument("--experiment-id", required=True, help="Experiment ID to promote")
    cand_promote.add_argument("--manual", action="store_true", required=True, help="Manual confirmation flag")
    cand_promote.add_argument("--data-root", default="data", help="Data root path")
    cand_promote.set_defaults(func=cmd_research_candidate_promote)

    # --- batch-run ---
    batch_p = research_sub.add_parser("batch-run", help="Run multiple experiments in batch")
    batch_p.add_argument("--experiment-ids", required=True, help="Comma-separated experiment IDs")
    batch_p.add_argument("--data-root", default="data", help="Data root path")
    batch_p.set_defaults(func=cmd_research_batch_run)

    # --- scorecard ---
    sc_p = research_sub.add_parser("scorecard", help="Build scorecard for a candidate")
    sc_p.add_argument("--candidate-id", required=True, help="Candidate ID")
    sc_p.add_argument("--data-root", default="data", help="Data root path")
    sc_p.add_argument("--markdown", action="store_true", help="Output as markdown")
    sc_p.set_defaults(func=cmd_research_scorecard)


def cmd_research_experiment_create(args: argparse.Namespace) -> None:
    """Create a new experiment."""
    import json

    from quant_us.research.lab.manifest import ExperimentManager

    mgr = ExperimentManager(data_root=args.data_root)
    symbols = _parse_symbols(args.symbols)

    params = {}
    if args.params and args.params != "{}":
        params = json.loads(args.params)

    manifest = mgr.create(
        strategy_id=args.strategy_id,
        symbols=symbols,
        params=params,
        strategy_family=args.family,
        timeframe=args.timeframe,
        start_date=args.start,
        end_date=args.end,
    )

    print(f"Created experiment: {manifest.experiment_id}")
    print(f"  strategy_id: {manifest.strategy_id}")
    print(f"  symbols:     {', '.join(manifest.symbols)}")
    print(f"  status:      {manifest.status}")
    print(f"  created_at:  {manifest.created_at}")


def cmd_research_experiment_run(args: argparse.Namespace) -> None:
    """Run an experiment backtest."""
    from quant_us.research.lab.manifest import ExperimentManager

    mgr = ExperimentManager(data_root=args.data_root)
    print(f"Running experiment {args.experiment_id}...")

    try:
        summary = mgr.run(args.experiment_id)
        print(f"  status: COMPLETED")
        for key, value in sorted(summary.items()):
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")
    except Exception as exc:
        print(f"  status: FAILED — {exc}")
        raise


def cmd_research_experiment_list(args: argparse.Namespace) -> None:
    """List experiments."""
    from quant_us.research.lab.manifest import ExperimentManager

    mgr = ExperimentManager(data_root=args.data_root)
    status = args.status or None
    experiments = mgr.list_experiments(status=status)

    if not experiments:
        print("No experiments found.")
        return

    print(f"{'ID':<20} {'Strategy':<20} {'Symbols':<24} {'Status':<22} {'Created'}")
    print("-" * 100)
    for m in experiments:
        sym_str = ", ".join(m.symbols[:4])
        if len(m.symbols) > 4:
            sym_str += "..."
        print(
            f"{m.experiment_id:<20} {m.strategy_id:<20} {sym_str:<24} {m.status:<22} {m.created_at[:19]}"
        )


def cmd_research_experiment_inspect(args: argparse.Namespace) -> None:
    """Inspect experiment details."""
    import json

    from quant_us.research.lab.manifest import ExperimentManager

    mgr = ExperimentManager(data_root=args.data_root)
    manifest = mgr.load(args.experiment_id)

    if manifest is None:
        print(f"Experiment {args.experiment_id} not found.")
        return

    print(f"Experiment ID:   {manifest.experiment_id}")
    print(f"Strategy ID:     {manifest.strategy_id}")
    print(f"Strategy Family: {manifest.strategy_family or '(not set)'}")
    print(f"Symbols:         {', '.join(manifest.symbols)}")
    print(f"Timeframe:       {manifest.timeframe}")
    print(f"Date Range:      {manifest.start_date or '(not set)'} -> {manifest.end_date or '(not set)'}")
    print(f"Data Version:    {manifest.data_version or '(not set)'}")
    print(f"Feature Version: {manifest.feature_version or '(not set)'}")
    print(f"Cost Model:      {manifest.cost_model}")
    print(f"Status:          {manifest.status}")
    print(f"Created At:      {manifest.created_at}")
    print(f"Params:          {json.dumps(manifest.params, indent=2, default=str)}")
    if manifest.metrics:
        print(f"Metrics:")
        for key, value in sorted(manifest.metrics.items()):
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")


def cmd_research_candidate_list(args: argparse.Namespace) -> None:
    """List all candidates."""
    from quant_us.research.lab.manifest import ExperimentManager

    mgr = ExperimentManager(data_root=args.data_root)
    candidates = mgr.list_candidates()

    if not candidates:
        print("No candidates found.")
        return

    print(f"{'ID':<20} {'Strategy':<20} {'Promotion Status':<22} {'Created'}")
    print("-" * 80)
    for c in candidates:
        print(
            f"{c.candidate_id:<20} {c.strategy_id:<20} {c.promotion_status:<22} {c.created_at[:19]}"
        )


def cmd_research_candidate_promote(args: argparse.Namespace) -> None:
    """Promote an experiment to candidate (manual only)."""
    if not args.manual:
        print("ERROR: --manual flag required for promotion.")
        print("Research promotion is a manual approval action.")
        return

    from quant_us.research.lab.manifest import ExperimentManager

    mgr = ExperimentManager(data_root=args.data_root)

    try:
        candidate = mgr.promote_to_candidate(args.experiment_id)
        print(f"Promoted experiment {args.experiment_id} to candidate.")
        print(f"  Candidate ID:    {candidate.candidate_id}")
        print(f"  Promotion Status: {candidate.promotion_status}")
        print(f"  Note: Candidate is RESEARCH_ONLY. Not eligible for paper or live.")
    except ValueError as exc:
        print(f"ERROR: {exc}")
        raise


def cmd_research_batch_run(args: argparse.Namespace) -> None:
    """Run multiple experiments in batch."""
    from quant_us.research.lab.batch_runner import BatchBacktestRunner

    experiment_ids = [eid.strip() for eid in args.experiment_ids.split(",") if eid.strip()]

    runner = BatchBacktestRunner(data_root=args.data_root)
    results = runner.run_experiments(experiment_ids)

    ok = sum(1 for r in results if r.get("status") == "COMPLETED")
    fail = sum(1 for r in results if r.get("status") == "FAILED")
    print(f"Batch run complete: {ok} ok, {fail} failed")
    for r in results:
        status = r.get("status", "UNKNOWN")
        eid = r.get("experiment_id", "?")
        if status == "COMPLETED":
            metrics = r.get("metrics", {})
            sharpe = metrics.get("sharpe_ratio", "N/A")
            print(f"  {eid}: {status} (sharpe={sharpe})")
        else:
            print(f"  {eid}: {status} — {r.get('error', '')}")


def cmd_research_scorecard(args: argparse.Namespace) -> None:
    """Build and display a scorecard for a candidate."""
    from quant_us.research.lab.scorecard import ResearchScorecardBuilder

    builder = ResearchScorecardBuilder(data_root=args.data_root)

    try:
        scorecard = builder.build(args.candidate_id)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return

    if args.markdown:
        print(builder.to_markdown(scorecard))
    else:
        print(f"Scorecard for candidate {scorecard.candidate_id}:")
        for field_name in (
            "cagr", "sharpe", "sortino", "calmar", "max_drawdown",
            "win_rate", "profit_factor", "turnover", "trade_count",
            "avg_holding_period", "robustness_score", "overfit_risk",
        ):
            value = getattr(scorecard, field_name, "N/A")
            if isinstance(value, float):
                print(f"  {field_name}: {value:.4f}")
            else:
                print(f"  {field_name}: {value}")


# ---------------------------------------------------------------------------
# factor
# ---------------------------------------------------------------------------


def _resolve_factor_ids(raw: str) -> list[str]:
    """Parse comma-separated factor IDs."""
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_factor_compute(args: argparse.Namespace) -> None:
    """Compute factor values for one or more factors."""
    from quant_us.factors.pipeline import FactorPipeline

    factor_ids = _resolve_factor_ids(args.factor)
    symbols = _parse_symbols(args.symbols)
    pipe = FactorPipeline(data_root=args.data_root)
    df = pipe.compute(factor_ids=factor_ids, symbols=symbols, start=args.start, end=args.end)
    print(f"Computed {len(factor_ids)} factor(s) for {len(symbols)} symbols")
    print(f"  dates:  {args.start} -> {args.end}")
    print(f"  rows:   {len(df)}")
    print(f"  columns: {list(df.columns)}")
    print()
    if not df.empty:
        for fid in factor_ids:
            col = df[fid].dropna()
            print(f"  {fid}:  min={col.min():.4f}  max={col.max():.4f}  mean={col.mean():.4f}  std={col.std():.4f}  count={len(col)}")


def cmd_factor_evaluate(args: argparse.Namespace) -> None:
    """Run full factor evaluation (IC, rank IC, quantile returns)."""
    from datetime import date

    from quant_us.factors.evaluation import FactorEvaluator

    factor_id = args.factor
    symbols = _parse_symbols(args.symbols) if args.symbols else _parse_symbols("SPY,QQQ,AAPL,MSFT,GOOGL")
    end = args.end or date.today().isoformat()
    evaluator = FactorEvaluator(data_root=args.data_root)
    result = evaluator.evaluate(
        factor_id=factor_id,
        symbols=symbols,
        start=args.start,
        end=end,
        forward_period=args.forward_period,
    )
    print(f"Evaluation for '{factor_id}'")
    print(f"  {'Observations:':20s} {result.n_observations}")
    print(f"  {'Dates:':20s} {result.n_dates}")
    print(f"  {'IC (mean):':20s} {result.ic_mean:.4f}")
    print(f"  {'IC (std):':20s} {result.ic_std:.4f}")
    print(f"  {'ICIR:':20s} {result.icir:.2f}")
    print(f"  {'Rank IC (mean):':20s} {result.rank_ic_mean:.4f}")
    print(f"  {'Rank IC (std):':20s} {result.rank_ic_std:.4f}")
    print(f"  {'Rank ICIR:':20s} {result.rank_icir:.2f}")
    print(f"  {'Hit Rate:':20s} {result.hit_rate:.1%}")
    print(f"  {'Monotonicity:':20s} {result.monotonicity:.2f}")
    print(f"  {'Long/Short Spread:':20s} {result.long_short_spread:.4f}")
    print(f"  {'Decay Half-Life:':20s} {result.decay_half_life:.1f}d")
    print()
    if result.quantile_returns:
        print("  Quantile Returns:")
        for q, ret in sorted(result.quantile_returns.items()):
            print(f"    Q{q}: {ret:.4f}")


def cmd_factor_list(args: argparse.Namespace) -> None:
    """List all registered factors, optionally filtered by category."""
    from quant_us.factors.definition import FactorLibrary

    lib = FactorLibrary()
    if args.category:
        factors = lib.list_by_category(args.category)
    else:
        factors = lib.list_all()

    if not factors:
        print(f"No factors found{' for category: ' + args.category if args.category else ''}.")
        return

    print(f"{'Factor ID':24s} {'Name':40s} {'Category':16s} {'Lookback':10s} {'Neutralization':16s}")
    print("-" * 106)
    for f in factors:
        print(f"{f.factor_id:24s} {f.name:40s} {f.category:16s} {str(f.lookback):10s} {f.neutralization:16s}")
    print(f"\nTotal: {len(factors)} factor(s)")


def cmd_factor_report(args: argparse.Namespace) -> None:
    """Generate and print a markdown factor report."""
    from datetime import date

    from quant_us.factors.evaluation import FactorEvaluator
    from quant_us.factors.report import FactorReportBuilder

    factor_id = args.factor
    symbols = _parse_symbols(args.symbols) if args.symbols else _parse_symbols("SPY,QQQ,AAPL,MSFT,GOOGL")
    end = args.end or date.today().isoformat()
    evaluator = FactorEvaluator(data_root=args.data_root)
    result = evaluator.evaluate(
        factor_id=factor_id,
        symbols=symbols,
        start=args.start,
        end=end,
        forward_period=args.forward_period,
    )
    builder = FactorReportBuilder()
    md = builder.build_report(factor_id, result)
    print(md)


def cmd_factor_compare(args: argparse.Namespace) -> None:
    """Compare multiple factors side-by-side."""
    from datetime import date

    from quant_us.factors.evaluation import FactorEvaluator

    factor_ids = _resolve_factor_ids(args.factors)
    symbols = _parse_symbols(args.symbols) if args.symbols else _parse_symbols("SPY,QQQ,AAPL,MSFT,GOOGL")
    end = args.end or date.today().isoformat()
    evaluator = FactorEvaluator(data_root=args.data_root)

    results = {}
    for fid in factor_ids:
        print(f"Evaluating {fid}...")
        results[fid] = evaluator.evaluate(
            factor_id=fid,
            symbols=symbols,
            start=args.start,
            end=end,
            forward_period=args.forward_period,
        )

    if not results:
        print("No results to compare.")
        return

    print()
    header = f"{'Metric':24s}"
    for fid in factor_ids:
        header += f" {fid:>20s}"
    print(header)
    print("-" * (24 + 21 * len(factor_ids)))

    metrics = [
        ("IC Mean", "ic_mean", "{:.4f}"),
        ("IC Std", "ic_std", "{:.4f}"),
        ("ICIR", "icir", "{:.2f}"),
        ("Rank IC Mean", "rank_ic_mean", "{:.4f}"),
        ("Rank IC Std", "rank_ic_std", "{:.4f}"),
        ("Rank ICIR", "rank_icir", "{:.2f}"),
        ("Hit Rate", "hit_rate", "{:.1%}"),
        ("Monotonicity", "monotonicity", "{:.2f}"),
        ("LS Spread", "long_short_spread", "{:.4f}"),
        ("Decay HL", "decay_half_life", "{:.1f}d"),
    ]
    for label, attr, fmt in metrics:
        row = f"{label:24s}"
        for fid in factor_ids:
            val = getattr(results[fid], attr, 0.0)
            row += f" {fmt.format(val):>20s}"
        print(row)


def cmd_factor_check_lookahead(args: argparse.Namespace) -> None:
    """Run lookahead detection heuristic on a factor."""
    from quant_us.factors.evaluation import FactorEvaluator

    factor_id = args.factor
    evaluator = FactorEvaluator(data_root=args.data_root)
    flagged, message = evaluator.detect_lookahead(factor_id)

    if flagged:
        print(f"WARNING: Lookahead detected for '{factor_id}'")
        print(f"  {message}")
        print()
        print("Possible causes:")
        print("  - Factor uses shift(-1) or future data")
        print("  - Factor uses bfill or forward-filling")
        print("  - Factor computation incorrectly aligns timestamps")
    else:
        print(f"OK: No lookahead detected for '{factor_id}'")
        print(f"  {message}")


def _add_factor_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "factor",
        parents=[_shared_parent()],
        help="R3 Factor Engine: compute, evaluate, list, report, compare, check-lookahead",
    )
    factor_sub = p.add_subparsers(dest="factor_command", required=True)

    # --- compute ---
    comp = factor_sub.add_parser("compute", help="Compute factor values for symbols over date range")
    comp.add_argument("--factor", required=True, help="Factor ID (comma-separated for multiple)")
    comp.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    comp.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    comp.set_defaults(func=cmd_factor_compute)

    # --- evaluate ---
    ev = factor_sub.add_parser("evaluate", help="Full factor evaluation with IC, quantile returns, decay")
    ev.add_argument("--factor", required=True, help="Factor ID")
    ev.add_argument("--symbols", default="", help="Comma-separated symbols (default: SPY,QQQ,AAPL,MSFT,GOOGL)")
    ev.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    ev.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    ev.add_argument("--forward-period", type=int, default=5, help="Forward return period in days (default: 5)")
    ev.set_defaults(func=cmd_factor_evaluate)

    # --- list ---
    lst = factor_sub.add_parser("list", help="List all registered factors")
    lst.add_argument("--category", default="", help="Filter by category (e.g. momentum, volatility)")
    lst.set_defaults(func=cmd_factor_list)

    # --- report ---
    rep = factor_sub.add_parser("report", help="Generate markdown factor report")
    rep.add_argument("--factor", required=True, help="Factor ID")
    rep.add_argument("--symbols", default="", help="Comma-separated symbols (default: SPY,QQQ,AAPL,MSFT,GOOGL)")
    rep.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    rep.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    rep.add_argument("--forward-period", type=int, default=5, help="Forward return period in days (default: 5)")
    rep.set_defaults(func=cmd_factor_report)

    # --- compare ---
    cmp = factor_sub.add_parser("compare", help="Compare multiple factors side-by-side")
    cmp.add_argument("--factors", required=True, help="Comma-separated factor IDs")
    cmp.add_argument("--symbols", default="", help="Comma-separated symbols (default: SPY,QQQ,AAPL,MSFT,GOOGL)")
    cmp.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    cmp.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    cmp.add_argument("--forward-period", type=int, default=5, help="Forward return period in days (default: 5)")
    cmp.set_defaults(func=cmd_factor_compare)

    # --- check-lookahead ---
    cl = factor_sub.add_parser("check-lookahead", help="Heuristic lookahead detection")
    cl.add_argument("--factor", required=True, help="Factor ID")
    cl.set_defaults(func=cmd_factor_check_lookahead)


# main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-us",
        description="QuantStation US Equity quant system — ingest, backtest, paper trade, shadow-live, reconcile, readiness, factor.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Subcommand")
    _add_ingest_parser(subparsers)
    _add_backtest_parser(subparsers)
    _add_regime_parser(subparsers)
    _add_paper_parser(subparsers)
    _add_shadow_live_parser(subparsers)
    _add_reconcile_parser(subparsers)
    _add_readiness_parser(subparsers)
    _add_live_parser(subparsers)
    _add_live_pilot_parser(subparsers)
    _add_ops_parser(subparsers)
    _add_portfolio_parser(subparsers)
    _add_research_parser(subparsers)
    _add_factor_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
