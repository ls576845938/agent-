#!/usr/bin/env python3
"""Orchestrate multi-day paper trading validation.

Runs one trading day at a time through PaperTradingLoop, tracks consecutive
clean days, persists validation state across runs, and generates a final
report.  Exits with code 0 only when ``consecutive_clean_days >= days_required``.

Usage::

    # Continuous run with default 30-day target
    python scripts/run_paper_validation.py --symbols AAPL,MSFT

    # Resume an interrupted validation
    python scripts/run_paper_validation.py --symbols AAPL --ledger-root data/paper_ledger

    # Quick smoke test (3 days)
    python scripts/run_paper_validation.py --symbols AAPL --days-required 3

State is saved to ``{ledger_root}/validation_state.json`` after every trading
day so that a Ctrl+C does not lose progress.

Current boundary: this CLI resumes validation counters and evidence pointers,
but it does not restore in-memory broker positions/cash from the ledger.  Treat
resumed runs as operationally incomplete until a ledger-backed broker restore
exists in the runtime path.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.backtest.data_bridge import bars_from_dataframe
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from quant_us.strategies.factory import build_strategy

DEFAULT_STATE_FILE = "validation_state.json"
DEFAULT_REPORT_FILE = "validation_report.json"


# ------------------------------------------------------------------
# State persistence
# ------------------------------------------------------------------

def _make_initial_state(symbols: list[str], capital: float, days_required: int) -> dict[str, Any]:
    return {
        "symbols": symbols,
        "capital": capital,
        "days_required": days_required,
        "days_completed": 0,
        "consecutive_clean_days": 0,
        "start_date": None,
        "last_date": None,
        "daily_results": [],
    }


def load_state(path: Path) -> dict[str, Any]:
    """Load validation state from *path*, or return a fresh empty state."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_state(state: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, default=str)


def enrich_validation_evidence(
    state: dict[str, Any],
    *,
    ledger_root: Path,
    state_path: Path,
    report_path: Path,
) -> None:
    """Attach review evidence pointers and current operational boundaries."""
    latest_daily = _latest_file(ledger_root / "daily_reports", "daily_report_*.json")
    latest_recon = _latest_file(ledger_root / "reconciliation", "recon_*.json")
    latest_ledger_artifact = _latest_file(
        ledger_root / "reconciliation", "ledger_recon_artifact_*.json"
    )
    session_manifest = ledger_root / "audit" / "paper_session_manifest.json"
    startup_sync = ledger_root / "audit" / "paper_broker_adapter_startup_sync.json"
    broker_state_recovery = ledger_root / "audit" / "paper_broker_state_recovery.json"
    run_journal = ledger_root / "run_journal.jsonl"

    session_payload = load_state(session_manifest) if session_manifest.exists() else {}
    startup_payload = load_state(startup_sync) if startup_sync.exists() else {}
    recovery_payload = load_state(broker_state_recovery) if broker_state_recovery.exists() else {}
    recon_payload = load_state(latest_recon) if latest_recon else {}
    resume_state_loaded = bool(state.get("resume_state_loaded", False))

    state["evidence_schema_version"] = "paper_validation_evidence_v1"
    state["evidence"] = {
        "validation_state_path": str(state_path),
        "validation_report_path": str(report_path),
        "daily_report_path": str(latest_daily) if latest_daily else "",
        "paper_session_manifest_path": str(session_manifest) if session_manifest.exists() else "",
        "paper_session_history_artifact_path": str(session_payload.get("history_artifact_path", "")),
        "startup_sync_path": str(startup_sync) if startup_sync.exists() else "",
        "broker_state_recovery_path": str(broker_state_recovery) if broker_state_recovery.exists() else "",
        "ledger_reconciliation_path": str(latest_recon) if latest_recon else "",
        "ledger_reconciliation_artifact_path": str(latest_ledger_artifact) if latest_ledger_artifact else "",
        "run_journal_path": str(run_journal) if run_journal.exists() else "",
    }
    state["paper_submit_evidence"] = {
        "submit_orders": bool(session_payload.get("submit_orders", False)),
        "paper_broker": str(session_payload.get("paper_broker", "")),
        "broker_backend": str(session_payload.get("broker_backend", "")),
        "no_real_order_submission_proof": session_payload.get("no_real_order_submission_proof", {}),
    }
    state["broker_local_diff_summary"] = _broker_local_diff_summary(recon_payload)
    state["ledger_reconciliation_summary"] = {
        "status": str(recon_payload.get("status", "unknown") if recon_payload else "unknown"),
        "halt_new_orders": bool(recon_payload.get("halt_new_orders", False)) if recon_payload else False,
    }
    state["startup_sync_summary"] = {
        "status": str(startup_payload.get("status", "")),
        "halt_reconciliation": bool(startup_payload.get("halt_reconciliation", False)),
    }
    recovery_required = bool(recovery_payload.get("resume_detected", False)) or resume_state_loaded
    operationally_complete = bool(
        recovery_payload.get(
            "operationally_complete",
            not recovery_required,
        )
    )
    state["recovery_summary"] = {
        "required": recovery_required,
        "status": str(
            recovery_payload.get(
                "status",
                "missing" if recovery_required else "not_required",
            )
        ),
        "resume_restores_broker_state": bool(recovery_payload.get("broker_state_restored", False)),
        "resume_restores_validation_counters": True,
        "broker_state_verified": bool(recovery_payload.get("broker_state_verified", False)),
        "operationally_complete": operationally_complete,
        "artifact_path": str(broker_state_recovery) if broker_state_recovery.exists() else "",
        "reason": str(recovery_payload.get("error", "")),
        "boundary": (
            "run_paper_validation depends on ledger-backed broker-state recovery evidence; "
            "resume is operationally incomplete until cash/positions restore or verify passes"
        ),
    }


def _recovery_operationally_complete(state: dict[str, Any]) -> bool:
    recovery = state.get("recovery_summary", {})
    if not isinstance(recovery, dict) or not recovery:
        return False
    artifact_path = str(
        recovery.get("artifact_path")
        or state.get("evidence", {}).get("broker_state_recovery_path", "")
    )
    if not artifact_path:
        return False
    return bool(recovery.get("operationally_complete", False))


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = list(directory.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _broker_local_diff_summary(recon_payload: dict[str, Any]) -> dict[str, Any]:
    if not recon_payload:
        return {
            "cash_diff": 0.0,
            "position_diff_count": 0,
            "order_diff_count": 0,
            "fill_diff_count": 0,
            "total_diff_count": 0,
        }
    position_diffs = recon_payload.get("position_diffs", {})
    order_diffs = recon_payload.get("order_diffs", {})
    fill_diffs = recon_payload.get("fill_diffs", {})
    if not isinstance(position_diffs, dict):
        position_diffs = {}
    if not isinstance(order_diffs, dict):
        order_diffs = {}
    if not isinstance(fill_diffs, dict):
        fill_diffs = {}
    cash_diff = float(recon_payload.get("cash_diff", 0.0) or 0.0)
    total = len(position_diffs) + len(order_diffs) + len(fill_diffs)
    if abs(cash_diff) > 1e-6:
        total += 1
    return {
        "cash_diff": cash_diff,
        "position_diff_count": len(position_diffs),
        "order_diff_count": len(order_diffs),
        "fill_diff_count": len(fill_diffs),
        "total_diff_count": total,
    }


def save_report(state: dict[str, Any], path: Path) -> None:
    passed = (
        state.get("consecutive_clean_days", 0) >= state.get("days_required", 30)
        and _recovery_operationally_complete(state)
    )
    report = {
        "status": "PASS" if passed else "INCOMPLETE",
        "symbols": state.get("symbols", []),
        "capital": state.get("capital", 100_000.0),
        "days_required": state.get("days_required", 30),
        "days_completed": state.get("days_completed", 0),
        "consecutive_clean_days": state.get("consecutive_clean_days", 0),
        "start_date": state.get("start_date"),
        "last_date": state.get("last_date"),
        "passed": passed,
        "daily_results": state.get("daily_results", []),
        "evidence_schema_version": state.get("evidence_schema_version", ""),
        "evidence": state.get("evidence", {}),
        "paper_submit_evidence": state.get("paper_submit_evidence", {}),
        "broker_local_diff_summary": state.get("broker_local_diff_summary", {}),
        "ledger_reconciliation_summary": state.get("ledger_reconciliation_summary", {}),
        "startup_sync_summary": state.get("startup_sync_summary", {}),
        "recovery_summary": state.get("recovery_summary", {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)


# ------------------------------------------------------------------
# Data loading
# ------------------------------------------------------------------

def load_bars_by_date(
    data_root: str,
    symbols: list[str],
    source: str,
    interval: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[date, list[Any]]:
    """Load parquet bars from the data lake, grouped by trading date.

    Returns a dict mapping ``date`` → list of ``Bar`` objects for all
    requested symbols on that date.
    """
    groups: dict[date, list[Any]] = defaultdict(list)

    for symbol in symbols:
        parquet_root = (
            Path(data_root)
            / "raw"
            / f"vendor={source}"
            / "asset_class=equity"
            / f"bar_size={interval}"
            / f"symbol={symbol}"
        )
        if not parquet_root.is_dir():
            print(f"  WARNING: no data directory for {symbol} at {parquet_root}")
            continue

        date_dirs = sorted(parquet_root.glob("date=*.parquet"))
        if not date_dirs:
            print(f"  WARNING: no parquet files for {symbol} at {parquet_root}")
            continue

        frames: list[pd.DataFrame] = []
        loaded_count = 0
        for pq in date_dirs:
            date_str = pq.stem.replace("date=", "")
            try:
                pq_date = date.fromisoformat(date_str)
            except ValueError:
                continue
            if start_date and pq_date < start_date:
                continue
            if end_date and pq_date > end_date:
                continue
            frames.append(pd.read_parquet(pq))
            loaded_count += 1

        if not frames:
            print(f"  WARNING: no parquet files in date range for {symbol}")
            continue

        frame = pd.concat(frames, ignore_index=True)
        bars = bars_from_dataframe(frame, source=source, session="regular")
        for bar in bars:
            groups[bar.timestamp_utc.date()].append(bar)
        print(f"  {symbol}: {len(bars)} bars across {len(frames)} file(s)")

    return dict(groups)


# ------------------------------------------------------------------
# Console helpers
# ------------------------------------------------------------------

def _fmt_pnl(value: float) -> str:
    return f"+${value:,.2f}" if value >= 0 else f"-${abs(value):,.2f}"


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Orchestrate multi-day paper trading validation.  Runs one trading "
            "day at a time, tracks consecutive clean days, persists state across "
            "runs, and exits with code 0 only when consecutive clean days >= days_required."
        ),
    )
    parser.add_argument("--data-root", default="data", help="Data lake root directory (default: data)")
    parser.add_argument(
        "--symbols", default="AAPL",
        help="Comma-separated ticker symbols (default: AAPL)",
    )
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital (default: 100000)")
    parser.add_argument("--days-required", type=int, default=30, help="Minimum consecutive clean days (default: 30)")
    parser.add_argument("--ledger-root", default="data/paper_ledger", help="Ledger root directory (default: data/paper_ledger)")
    parser.add_argument("--strategy-id", default="trend_momentum", help="Strategy identifier (default: trend_momentum)")
    parser.add_argument("--strategy-params-json", default="{}", help="Strategy parameters as JSON (default: {})")
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD (default: first date in data)")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD (default: last date in data)")
    parser.add_argument("--bar-size", default="1d", help="Bar interval (default: 1d)")
    parser.add_argument("--source", default="yfinance", help="Data source vendor (default: yfinance)")
    parser.add_argument("--state-path", default="", help="Validation state JSON path (default: {ledger_root}/validation_state.json)")
    parser.add_argument("--report-path", default="", help="Validation report JSON path (default: {ledger_root}/validation_report.json)")
    parser.add_argument("--commission", type=float, default=0.0001, help="Commission rate (default: 0.0001)")
    parser.add_argument("--slippage", type=float, default=1.0, help="Slippage in bps (default: 1.0)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Parse / validate inputs
    # ------------------------------------------------------------------
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("ERROR: --symbols must specify at least one symbol.")
        sys.exit(1)

    start_date = date.fromisoformat(args.start) if args.start else None
    end_date = date.fromisoformat(args.end) if args.end else None

    ledger_root = Path(args.ledger_root)
    state_path = Path(args.state_path) if args.state_path else ledger_root / DEFAULT_STATE_FILE
    report_path = Path(args.report_path) if args.report_path else ledger_root / DEFAULT_REPORT_FILE

    # ------------------------------------------------------------------
    # Load / initialise validation state
    # ------------------------------------------------------------------
    raw_state = load_state(state_path)
    if raw_state:
        state = raw_state
        state["resume_state_loaded"] = True
        completed_dates = {r["date"] for r in state.get("daily_results", [])}
        print(f"Resuming from previous state ({state_path}) — "
              f"{state.get('days_completed', 0)} days completed, "
              f"{state.get('consecutive_clean_days', 0)} consecutive clean")
        print("  NOTE: readiness now depends on ledger-backed broker-state recovery evidence.")
        print()
    else:
        state = _make_initial_state(symbols, args.capital, args.days_required)
        state["resume_state_loaded"] = False
        completed_dates = set()
        print("Starting fresh validation run.")
        print()

    # ------------------------------------------------------------------
    # Print banner
    # ------------------------------------------------------------------
    print("Paper Trading Validation")
    print("=" * 56)
    print(f"  Symbols:          {', '.join(symbols)}")
    print(f"  Capital:          ${args.capital:,.2f}")
    print(f"  Days required:    {args.days_required}")
    print(f"  Strategy:         {args.strategy_id}")
    print(f"  Data root:        {args.data_root}")
    print(f"  Ledger root:      {args.ledger_root}")
    print(f"  State path:       {state_path}")
    print(f"  Report path:      {report_path}")
    print()

    # ------------------------------------------------------------------
    # Load market data
    # ------------------------------------------------------------------
    print("Loading market data ...")
    bars_by_date = load_bars_by_date(
        data_root=args.data_root,
        symbols=symbols,
        source=args.source,
        interval=args.bar_size,
        start_date=start_date,
        end_date=end_date,
    )
    if not bars_by_date:
        print("ERROR: no market data loaded — cannot run validation.")
        sys.exit(1)

    sorted_dates = sorted(bars_by_date)
    print(f"\n  Total trading days loaded: {len(sorted_dates)}")
    print(f"  Range: {sorted_dates[0]} to {sorted_dates[-1]}")
    print()

    # ------------------------------------------------------------------
    # Initialise / update state metadata
    # ------------------------------------------------------------------
    # On first run, populate all fields from CLI.  On resume, days_required
    # and capital may change (e.g. extending the validation window).
    if state.get("days_completed", 0) == 0:
        state["symbols"] = symbols
        state["capital"] = args.capital
        state["days_required"] = args.days_required
        state["start_date"] = sorted_dates[0].isoformat()
    else:
        state["symbols"] = symbols
        state["capital"] = args.capital
        state["days_required"] = args.days_required

    # ------------------------------------------------------------------
    # Early exit if already passed
    # ------------------------------------------------------------------
    if state.get("consecutive_clean_days", 0) >= state.get("days_required", 30):
        enrich_validation_evidence(
            state,
            ledger_root=ledger_root,
            state_path=state_path,
            report_path=report_path,
        )
        if _recovery_operationally_complete(state):
            print(f"Validation already passed "
                  f"({state['consecutive_clean_days']} >= {state['days_required']})")
        else:
            print("Validation counters reached target, but recovery evidence is incomplete.")
        save_report(state, report_path)
        sys.exit(0 if _recovery_operationally_complete(state) else 1)

    # ------------------------------------------------------------------
    # Build trading infrastructure
    # ------------------------------------------------------------------
    config = PaperTradingConfig(
        initial_cash=args.capital,
        commission_rate=args.commission,
        slippage_bps=args.slippage,
        ledger_root=str(ledger_root),
    )
    try:
        loop = PaperTradingLoop(config=config)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        state["runtime_error"] = str(exc)
        enrich_validation_evidence(
            state,
            ledger_root=ledger_root,
            state_path=state_path,
            report_path=report_path,
        )
        save_state(state, state_path)
        save_report(state, report_path)
        sys.exit(1)

    strategy_params = json.loads(args.strategy_params_json) if args.strategy_params_json else {}
    try:
        strategy = build_strategy(args.strategy_id, strategy_params)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Signal handler for graceful shutdown
    # ------------------------------------------------------------------
    def _handle_interrupt(signum: int, frame: object) -> None:  # noqa: ANN401
        print("\n\nInterrupted — saving state and report ...")
        enrich_validation_evidence(
            state,
            ledger_root=ledger_root,
            state_path=state_path,
            report_path=report_path,
        )
        save_state(state, state_path)
        save_report(state, report_path)
        print(f"State saved to {state_path}")
        print(f"Report saved to {report_path}")
        sys.exit(130)

    signal.signal(signal.SIGINT, _handle_interrupt)
    signal.signal(signal.SIGTERM, _handle_interrupt)

    # ------------------------------------------------------------------
    # Run loop — one trading day at a time
    # ------------------------------------------------------------------
    consecutive = state.get("consecutive_clean_days", 0)
    days_completed = state.get("days_completed", 0)
    reached_target = False

    for day in sorted_dates:
        day_str = day.isoformat()

        # Skip days already accounted for in the state
        if day_str in completed_dates:
            print(f"  Day {days_completed}/{args.days_required} | {day_str} | SKIP (completed)")
            continue

        bars = bars_by_date[day]
        if not bars:
            continue

        result = loop.run_day(bars=bars, strategies=[strategy])

        days_completed += 1
        is_clean = result.reconciliation_passed and len(result.errors) == 0
        consecutive = consecutive + 1 if is_clean else 0

        # Build daily result entry
        day_entry: dict[str, Any] = {
            "date": day_str,
            "pnl": round(result.daily_pnl, 2),
            "return_pct": round(result.daily_return_pct, 4),
            "starting_equity": round(result.starting_equity, 2),
            "ending_equity": round(result.ending_equity, 2),
            "orders_submitted": result.orders_submitted,
            "orders_filled": result.orders_filled,
            "orders_rejected": result.orders_rejected,
            "recon": "PASS" if result.reconciliation_passed else "FAIL",
            "kill_switch": result.kill_switch_triggered,
            "stale_bars": result.stale_bars,
            "errors": result.errors,
            "consecutive_clean": consecutive,
        }
        state.setdefault("daily_results", []).append(day_entry)
        state["days_completed"] = days_completed
        state["consecutive_clean_days"] = consecutive
        state["last_date"] = day_str

        # Console status line
        extra = ""
        if result.errors:
            extra += f" | ERRORS: {len(result.errors)}"
        if result.kill_switch_triggered:
            extra += " | KILL_SWITCH"
        if result.stale_bars:
            extra += f" | STALE: {result.stale_bars}"

        print(
            f"  Day {days_completed}/{args.days_required}"
            f" | {day_str}"
            f" | PnL: {_fmt_pnl(result.daily_pnl)}"
            f" | Recon: {'PASS' if result.reconciliation_passed else 'FAIL'}"
            f" | Consecutive: {consecutive}"
            f"{extra}"
        )

        # Persist after every day
        enrich_validation_evidence(
            state,
            ledger_root=ledger_root,
            state_path=state_path,
            report_path=report_path,
        )
        save_state(state, state_path)

        # Check target
        if consecutive >= args.days_required:
            reached_target = True
            print()
            print("=" * 56)
            print(f"VALIDATION PASSED: {consecutive} consecutive clean days")
            print("=" * 56)
            break

        # Stop if the loop is unhealthy
        if not loop.is_healthy():
            print(f"\n  Paper trading loop is UNHEALTHY — stopping early.")
            break

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    total_available = len(sorted_dates)
    final_equity = loop.broker.get_account().equity
    enrich_validation_evidence(
        state,
        ledger_root=ledger_root,
        state_path=state_path,
        report_path=report_path,
    )
    passed = reached_target and _recovery_operationally_complete(state)

    print()
    print("=" * 56)
    print("VALIDATION SUMMARY")
    print("=" * 56)
    print(f"  Days completed:        {days_completed} / {args.days_required}")
    print(f"  Consecutive clean:     {consecutive} / {args.days_required}")
    print(f"  Data days available:   {total_available}")
    print(f"  Last date:             {state.get('last_date')}")
    print(f"  Final equity:          ${final_equity:,.2f}")
    print(f"  Result:                {'PASS' if passed else 'INCOMPLETE'}")

    save_state(state, state_path)
    save_report(state, report_path)
    print(f"\nState saved to {state_path}")
    print(f"Report saved to {report_path}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
