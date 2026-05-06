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
    p.add_argument("--strategy", required=True, help="Strategy ID from the registry")
    p.add_argument("--broker", default="simulated", choices=["simulated", "alpaca"], help="Broker backend (default: simulated)")
    p.add_argument("--initial-cash", type=float, default=100_000.0, help="Initial capital (default: 100000)")
    p.add_argument("--commission-rate", type=float, default=0.0001, help="Commission rate (default: 0.0001)")
    p.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in bps (default: 1.0)")
    p.add_argument("--run", action="store_true", help="Execute the full paper trading session (not just readiness)")
    p.add_argument("--submit-orders", action="store_true", default=False, help="Submit orders to the broker (default: dry-run)")
    p.add_argument("--max-runtime-hours", type=float, default=8.0, help="Max session wall-clock hours (default: 8)")
    p.add_argument("--poll-interval", type=float, default=60.0, help="Market-data poll interval in seconds (default: 60)")
    p.add_argument("--bar-size", default="1m", help="Bar interval string e.g. 1m, 5m (default: 1m)")
    p.add_argument("--data-vendor", default="yfinance", help="Market-data connector (default: yfinance)")
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
        strategy_id=args.strategy,
        api_key=api_key,
        api_secret=api_secret,
        base_url="https://paper-api.alpaca.markets",
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
    gate = ShadowLiveGate()
    report = gate.run_checks(config)

    print(report.summary())
    print()

    if not report.gate_passed:
        print("ERROR: Shadow-live gate checks failed. Aborting.", file=sys.stderr)
        sys.exit(1)

    # Full session
    runner = ShadowLiveRunner(config)
    runner.bootstrap()
    runner.start()
    runner.on_close()
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


def _add_shadow_live_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "shadow-live",
        parents=[_shared_parent()],
        help="Run shadow-live session: full broker connectivity but NO real order submission",
    )
    p.add_argument("--strategy", required=True, help="Strategy ID from the registry")
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


def cmd_readiness(args: argparse.Namespace) -> None:
    """Check all pre-live readiness conditions."""
    from quant_us.reports.live_readiness import LiveReadinessGate

    if args.small_live:
        _cmd_readiness_small_live(args)
        return

    gate = LiveReadinessGate()
    report = gate.check_all(validation_state_path=args.validation_state)

    print("Live Readiness Report")
    print("=" * 60)
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  [{status}] {check.name}")
        print(f"         {check.detail}")
    print("=" * 60)
    if report.is_ready():
        print("  RESULT: SYSTEM IS READY for live trading.")
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
        "--validation-state",
        default="",
        help="Path to validation_state.json from paper trading (optional, for 30-day check)",
    )
    p.add_argument(
        "--small-live",
        action="store_true",
        help="Run small-live go/no-go gate (requires --validation-state)",
    )
    p.set_defaults(func=cmd_readiness)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-us",
        description="QuantStation US Equity quant system — ingest, backtest, paper trade, shadow-live, reconcile, readiness.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Subcommand")
    _add_ingest_parser(subparsers)
    _add_backtest_parser(subparsers)
    _add_paper_parser(subparsers)
    _add_shadow_live_parser(subparsers)
    _add_reconcile_parser(subparsers)
    _add_readiness_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
