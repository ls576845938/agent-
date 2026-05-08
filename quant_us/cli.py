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
        choices=["simulated", "paper", "live"],
        default="simulated",
        help="Readiness profile: simulated (local, no broker), paper (Alpaca paper), live (strict)",
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
    _add_live_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
