"""Daily trading report generator.

Produces comprehensive daily reports with account summary, order stats,
position details, risk events, reconciliation status, and data quality.

Usage:

    from quant_us.monitoring.daily_report import (
        generate_daily_report,
        format_report_text,
        format_report_json,
        save_report,
    )

    report = generate_daily_report(today, ledger, broker, kill_switch)
    report.stale_bars = 3  # override runtime-derived values
    save_report(report, "data/daily_reports")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import OrderStatus
from quant_us.core.types import AccountState, Position
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.risk.kill_switch import KillSwitch

_logger = logging.getLogger("daily_report")


@dataclass
class DailyTradingReport:
    """Comprehensive daily trading report.

    Fields are grouped into sections matching the acceptance criteria
    for the daily trading report acceptance gate.
    """

    report_date: date
    generated_at: datetime = field(default_factory=utc_now)

    # -- Account summary --
    starting_equity: float = 0.0
    ending_equity: float = 0.0
    daily_pnl: float = 0.0
    daily_return_pct: float = 0.0
    total_fees: float = 0.0

    # -- Order stats --
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    orders_cancelled: int = 0
    orders_pending: int = 0

    # -- Position summary (symbol -> {quantity, market_value, ...}) --
    positions: dict[str, dict[str, float]] = field(default_factory=dict)

    # -- Risk events --
    kill_switch_triggered: bool = False
    kill_switch_reason: str = ""
    kill_switch_consecutive_failures: int = 0
    risk_rejection_count: int = 0

    # -- Reconciliation --
    reconciliation_status: str = "unknown"  # clean / breaks_detected / unknown
    reconciliation_diff_count: int = 0
    reconciliation_halt: bool = False

    # -- Data quality --
    stale_bars: int = 0
    missing_bars: list[str] = field(default_factory=list)

    # -- Errors --
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_daily_report(
    report_date: date,
    ledger: JsonlLedgerStore,
    broker: BrokerBase,
    kill_switch: KillSwitch,
) -> DailyTradingReport:
    """Generate a comprehensive daily trading report.

    Args:
        report_date:
            The trading date (UTC) that this report covers.
        ledger:
            The local ledger store used to read persisted fills, orders,
            snapshots, and reconciliation files.
        broker:
            The broker adapter.  Account, positions, and orders are read
            from the broker at call time (end-of-day state).
        kill_switch:
            Kill switch instance whose ``triggered`` / ``reason`` flags
            are included in the risk-events section.

    Returns:
        A fully populated ``DailyTradingReport``.  Some fields that can
        only be computed at runtime (``stale_bars``, ``missing_bars``,
        ``errors``) are zero/empty by default; the caller should override
        them when richer data is available.
    """
    # -- Account summary --
    account: AccountState = broker.get_account()
    ending_equity = account.equity
    starting_equity = _determine_starting_equity(ledger, report_date, broker)
    daily_pnl = ending_equity - starting_equity
    daily_return_pct = (daily_pnl / starting_equity * 100.0) if starting_equity > 0 else 0.0
    total_fees = _compute_total_fees(ledger)

    # -- Order stats --
    all_orders = broker.get_orders()
    submitted = len(all_orders)
    filled = sum(1 for o in all_orders if o.status == OrderStatus.FILLED)
    rejected = sum(1 for o in all_orders if o.status in (OrderStatus.REJECTED, OrderStatus.ERROR))
    cancelled = sum(1 for o in all_orders if o.status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED))
    pending = sum(
        1
        for o in all_orders
        if o.status
        in (
            OrderStatus.CREATED,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        )
    )

    # -- Position summary --
    raw_positions: dict[str, Position] = broker.get_positions()
    position_summary: dict[str, dict[str, float]] = {}
    for sym, pos in raw_positions.items():
        position_summary[sym] = {
            "quantity": pos.quantity,
            "market_price": pos.market_price,
            "market_value": pos.market_value,
            "avg_price": pos.avg_price,
            "unrealized_pnl": pos.unrealized_pnl,
        }

    # -- Risk events --
    risk_rejection_count = 0
    try:
        ledger_orders = ledger.read_records("orders.jsonl")
        risk_rejection_count = sum(
            1
            for r in ledger_orders
            if r.get("status") in (OrderStatus.REJECTED.value, OrderStatus.ERROR.value)
        )
    except Exception:
        _logger.warning("Could not read ledger orders for risk_rejection_count", exc_info=True)

    # -- Reconciliation status from latest report file --
    recon_status, recon_diff_count, recon_halt = _read_reconciliation_status(ledger)

    return DailyTradingReport(
        report_date=report_date,
        starting_equity=round(starting_equity, 2),
        ending_equity=round(ending_equity, 2),
        daily_pnl=round(daily_pnl, 2),
        daily_return_pct=round(daily_return_pct, 4),
        total_fees=round(total_fees, 2),
        orders_submitted=submitted,
        orders_filled=filled,
        orders_rejected=rejected,
        orders_cancelled=cancelled,
        orders_pending=pending,
        positions=position_summary,
        kill_switch_triggered=kill_switch.triggered,
        kill_switch_reason=kill_switch.reason,
        kill_switch_consecutive_failures=kill_switch.consecutive_order_failures,
        risk_rejection_count=risk_rejection_count,
        reconciliation_status=recon_status,
        reconciliation_diff_count=recon_diff_count,
        reconciliation_halt=recon_halt,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _determine_starting_equity(
    ledger: JsonlLedgerStore,
    report_date: date,
    broker: BrokerBase,
) -> float:
    """Return the equity at the open of *report_date*.

    Strategy:
        1. Look for the most recent portfolio snapshot whose date is
           strictly before *report_date*.
        2. Fall back to the broker's current equity (end-of-day).

    This works because the ledger's "portfolio_snapshots.jsonl" is
    appended to at the close of each trading day.
    """
    try:
        snapshots = ledger.read_records("portfolio_snapshots.jsonl")
        if snapshots:
            report_day_start = datetime(
                report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc
            )
            candidates: list[tuple[datetime, float]] = []
            for snap in snapshots:
                ts_raw = snap.get("timestamp_utc", "")
                if ts_raw:
                    ts = ensure_utc(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")))
                    if ts.date() < report_date:
                        candidates.append((ts, float(snap.get("equity", 0.0))))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return max(candidates[0][1], 0.0)
    except Exception:
        _logger.warning("Failed to determine starting equity from ledger", exc_info=True)

    return broker.get_account().equity


def _compute_total_fees(ledger: JsonlLedgerStore) -> float:
    """Sum up all commission from ledger fills."""
    total = 0.0
    try:
        fill_records = ledger.read_records("fills.jsonl")
        for fill in fill_records:
            total += float(fill.get("commission", 0.0))
    except Exception:
        _logger.warning("Failed to compute total fees from ledger", exc_info=True)
    return total


def _read_reconciliation_status(
    ledger: JsonlLedgerStore,
) -> tuple[str, int, bool]:
    """Read the latest reconciliation report from the ledger directory.

    Returns:
        A 3-tuple ``(status, diff_count, halt_new_orders)``.
    """
    recon_dir = Path(ledger.root) / "reconciliation"
    if not recon_dir.exists():
        return "unknown", 0, False

    try:
        recon_files = sorted(recon_dir.glob("recon_*.json"), reverse=True)
        if not recon_files:
            return "unknown", 0, False

        latest = json.loads(recon_files[0].read_text(encoding="utf-8"))
        status = latest.get("status", "unknown")
        pos_diffs = latest.get("position_diffs", {})
        ord_diffs = latest.get("order_diffs", {})
        fill_diffs = latest.get("fill_diffs", {})
        diff_count = len(pos_diffs) + len(ord_diffs) + len(fill_diffs)
        halt = latest.get("halt_new_orders", False)
        return str(status), diff_count, bool(halt)
    except Exception:
        _logger.warning("Failed to read reconciliation status", exc_info=True)
        return "unknown", 0, False


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_report_text(report: DailyTradingReport) -> str:
    """Return a human-readable text summary of *report*.

    The output is designed for:
    - Console / log output during paper trading
    - Plain-text file attachment
    - Reading in a terminal or simple editor
    """
    lines: list[str] = []
    _sep = "=" * 60

    # -- Header --
    lines.append(_sep)
    lines.append(f"  DAILY TRADING REPORT  {report.report_date.isoformat()}")
    lines.append(_sep)
    lines.append("")

    # -- Account summary --
    _add_section(lines, "Account Summary")
    lines.append(f"  Starting Equity       ${report.starting_equity:>12,.2f}")
    lines.append(f"  Ending Equity         ${report.ending_equity:>12,.2f}")
    lines.append(f"  Daily PnL             ${report.daily_pnl:>12,.2f}")
    lines.append(f"  Daily Return          {report.daily_return_pct:>11.4f} %")
    lines.append(f"  Total Fees            ${report.total_fees:>12,.2f}")
    lines.append("")

    # -- Order stats --
    _add_section(lines, "Order Statistics")
    lines.append(f"  Submitted              {report.orders_submitted:>6d}")
    lines.append(f"  Filled                 {report.orders_filled:>6d}")
    lines.append(f"  Rejected               {report.orders_rejected:>6d}")
    lines.append(f"  Cancelled              {report.orders_cancelled:>6d}")
    lines.append(f"  Pending                {report.orders_pending:>6d}")
    lines.append("")

    # -- Positions --
    _add_section(lines, "Positions")
    if report.positions:
        _add_position_header(lines)
        for sym in sorted(report.positions):
            p = report.positions[sym]
            lines.append(
                f"  {sym:<6s}  {p['quantity']:>10.4f}  {p['market_price']:>10.2f}  "
                f"{p['market_value']:>12,.2f}  {p['unrealized_pnl']:>12,.2f}"
            )
    else:
        lines.append("  (no open positions)")
    lines.append("")

    # -- Risk events --
    _add_section(lines, "Risk Events")
    if report.kill_switch_triggered:
        lines.append(f"  [X] KILL SWITCH TRIGGERED: {report.kill_switch_reason}")
        lines.append(f"      Consecutive failures:  {report.kill_switch_consecutive_failures}")
    else:
        lines.append("  [ ] Kill switch not triggered")
    lines.append(f"  Risk rejections:  {report.risk_rejection_count}")
    lines.append("")

    # -- Reconciliation --
    _add_section(lines, "Reconciliation")
    lines.append(f"  Status:    {report.reconciliation_status}")
    lines.append(f"  Diffs:     {report.reconciliation_diff_count}")
    lines.append(f"  Halt:      {'YES' if report.reconciliation_halt else 'no'}")
    lines.append("")

    # -- Data quality --
    _add_section(lines, "Data Quality")
    lines.append(f"  Stale bars:   {report.stale_bars}")
    if report.missing_bars:
        lines.append(f"  Missing:      {', '.join(sorted(report.missing_bars))}")
    else:
        lines.append("  Missing:      (none)")
    lines.append("")

    # -- Errors --
    if report.errors:
        _add_section(lines, "Errors")
        for err in report.errors:
            lines.append(f"  - {err}")
        lines.append("")

    lines.append(_sep)
    lines.append(f"  Generated: {report.generated_at.isoformat()}")
    lines.append(_sep)

    return "\n".join(lines)


def _add_section(lines: list[str], title: str) -> None:
    lines.append(f"\N{BOX DRAWINGS LIGHT HORIZONTAL}\N{BOX DRAWINGS LIGHT HORIZONTAL} "
                 f"{title} "
                 f"\N{BOX DRAWINGS LIGHT HORIZONTAL}\N{BOX DRAWINGS LIGHT HORIZONTAL}")


def _add_position_header(lines: list[str]) -> None:
    lines.append(
        f"  {'Symbol':<6s}  {'Quantity':>10s}  {'Price':>10s}  "
        f"{'Mkt Value':>12s}  {'Unreal. PnL':>12s}"
    )
    lines.append(
        f"  {'------':<6s}  {'--------':>10s}  {'-----':>10s}  "
        f"{'---------':>12s}  {'-----------':>12s}"
    )


def format_report_json(report: DailyTradingReport) -> str:
    """Return a JSON string representation of *report*."""
    data = asdict(report)
    data["report_date"] = report.report_date.isoformat()
    data["generated_at"] = report.generated_at.isoformat()
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Save to filesystem
# ---------------------------------------------------------------------------


def save_report(report: DailyTradingReport, directory: str | Path) -> Path:
    """Save *report* to *directory* as both JSON and plain-text files.

    Files are named ``daily_report_<YYYY-MM-DD>.json`` and
    ``daily_report_<YYYY-MM-DD>.txt``.

    Args:
        report: The report to persist.
        directory: Output directory (created if it does not exist).

    Returns:
        The absolute ``Path`` of the written JSON file.
    """
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = report.report_date.isoformat()

    json_path = output_dir / f"daily_report_{date_str}.json"
    json_path.write_text(format_report_json(report), encoding="utf-8")

    text_path = output_dir / f"daily_report_{date_str}.txt"
    text_path.write_text(format_report_text(report), encoding="utf-8")

    _logger.info("Daily report saved: %s (json), %s (txt)", json_path, text_path)
    return json_path
