#!/usr/bin/env python3
"""Build a fail-closed BTC funding ledger report."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.backtest.funding_ledger import FundingFill, FundingRateEvent, calculate_funding_payments
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.backtest.funding_ledger import FundingFill, FundingRateEvent, calculate_funding_payments


DEFAULT_PROVIDER_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_SOURCE_RUN_DIR = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_cost_model/latest")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
FUNDING_ADJUSTED_LEDGER_NAME = "funding_adjusted_trade_ledger.csv"


def build_btc_funding_ledger_report(
    *,
    repo_root: Path | None = None,
    provider_report_path: Path | None = None,
    source_run_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    provider_path = _resolve(root, provider_report_path or DEFAULT_PROVIDER_REPORT)
    run_dir = _resolve(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    provider = _read_json(provider_path)
    generated = generated_at or _utc_z_now()
    funding_rate_available = bool(provider.get("funding_rate_verified", False))
    funding_info_available = bool(provider.get("funding_info_verified", False))
    fills_source = run_dir / "trade_ledger.csv"
    funding_rate_source = _selected_bundle_file(root, "funding_rate.csv")
    funding_info_source = _selected_bundle_file(root, "funding_info.json")
    funding_events = _read_funding_events(funding_rate_source) if funding_rate_available and funding_rate_source else []
    trades = _read_trade_ledger_trades(fills_source) if fills_source.exists() else []
    fills = _trades_to_fills(trades)
    payments = calculate_funding_payments(funding_rates=funding_events, fills=fills) if funding_events and fills else []
    funding_adjusted_rows = _funding_adjusted_trade_rows(trades, funding_events)
    blockers: list[str] = []
    if not provider_path.exists():
        blockers.append("btc_perpetual_provider_verification_report_missing")
    if not funding_rate_available:
        blockers.append("btc_funding_rate_missing")
    if not funding_info_available:
        blockers.append("btc_funding_info_missing")
    if not fills_source.exists():
        blockers.append("btc_fills_or_trade_ledger_missing")
    if funding_rate_available and not funding_events:
        blockers.append("btc_funding_rate_events_not_readable")
    if fills_source.exists() and not fills:
        blockers.append("btc_fills_or_trade_ledger_not_readable")
    if funding_events and fills and str(provider.get("source_type")) in {"fixture", "sample"}:
        blockers.append("btc_fixture_or_sample_funding_ledger_not_candidate_eligible")
    funding_merged_into_net_ledger = bool(funding_adjusted_rows)
    if not payments:
        blockers.append("btc_funding_payment_not_in_ledger")
    payment_total = round(sum(float(payment.funding_payment) for payment in payments), 12)
    pnl_by_side = {"long": 0.0, "short": 0.0, "flat": 0.0}
    for payment in payments:
        if payment.position_qty > 0:
            pnl_by_side["long"] = round(pnl_by_side["long"] + payment.funding_payment, 12)
        elif payment.position_qty < 0:
            pnl_by_side["short"] = round(pnl_by_side["short"] + payment.funding_payment, 12)
        else:
            pnl_by_side["flat"] = round(pnl_by_side["flat"] + payment.funding_payment, 12)
    interval_hours = _funding_interval_hours(funding_events) or provider.get("funding_interval_hours")
    interval_confidence = provider.get("funding_interval_inference_confidence")
    interval_stable = interval_confidence == "high"
    funding_payment_in_ledger = bool(payments and funding_merged_into_net_ledger and str(provider.get("source_type")) == "production")
    if not funding_payment_in_ledger:
        blockers.append("btc_funding_payment_not_in_ledger")
    if funding_payment_in_ledger and not funding_info_available:
        blockers.append("btc_funding_info_not_verified_for_promotion_evidence")
    gross_net_pnl_total = round(sum(float(row.get("net_pnl", 0.0) or 0.0) for row in funding_adjusted_rows), 12)
    funding_adjusted_net_pnl_total = round(
        sum(float(row.get("net_pnl_after_funding", 0.0) or 0.0) for row in funding_adjusted_rows),
        12,
    )
    expected_funding_adjusted_net_pnl_total = round(gross_net_pnl_total + payment_total, 12)
    raw_reconciliation_delta = funding_adjusted_net_pnl_total - expected_funding_adjusted_net_pnl_total
    net_pnl_reconciled = bool(funding_adjusted_rows and abs(raw_reconciliation_delta) <= 1e-9)
    reconciliation_delta = 0.0 if net_pnl_reconciled else round(raw_reconciliation_delta, 12)
    if funding_adjusted_rows and not net_pnl_reconciled:
        blockers.append("btc_funding_adjusted_net_pnl_reconciliation_failed")
    return {
        "schema_version": "btc_funding_ledger_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "source_type": str(provider.get("source_type") or "research_spot_proxy"),
        "funding_rate_source": _relpath(funding_rate_source, root) if funding_rate_source and funding_rate_source.exists() else None,
        "funding_rate_available": funding_rate_available,
        "funding_info_available": funding_info_available,
        "funding_interval_hours": interval_hours,
        "funding_interval_source": provider.get("funding_interval_source")
        or (
            _relpath(funding_info_source, root)
            if funding_info_source and funding_info_source.exists()
            else ("funding_time_spacing_low_confidence" if interval_hours else None)
        ),
        "funding_interval_inference_confidence": interval_confidence,
        "funding_interval_stable": bool(interval_stable),
        "position_source": _relpath(fills_source, root) if fills_source.exists() else None,
        "fills_source": _relpath(fills_source, root) if fills_source.exists() else None,
        "funding_events_count": len(funding_events),
        "funding_payment_count": len(payments),
        "funding_pnl_total": payment_total,
        "funding_pnl_by_side": pnl_by_side,
        "funding_payment_in_ledger": funding_payment_in_ledger,
        "funding_merged_into_net_ledger": funding_merged_into_net_ledger,
        "funding_adjusted_ledger_path": str(DEFAULT_OUTPUT_ROOT / FUNDING_ADJUSTED_LEDGER_NAME)
        if funding_adjusted_rows
        else None,
        "trade_ledger_net_pnl_total": gross_net_pnl_total,
        "funding_adjusted_net_pnl_total": funding_adjusted_net_pnl_total,
        "expected_funding_adjusted_net_pnl_total": expected_funding_adjusted_net_pnl_total,
        "funding_adjusted_net_pnl_reconciliation_delta": reconciliation_delta,
        "funding_adjusted_net_pnl_reconciled": net_pnl_reconciled,
        "funding_adjusted_trade_count": len(funding_adjusted_rows),
        "promotion_evidence": False,
        "blockers": _dedupe(blockers),
    }


def write_btc_funding_ledger_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_funding_ledger_report.json"
    writable = dict(payload)
    rows = _funding_adjusted_rows_from_report(writable)
    if rows and writable.get("funding_adjusted_ledger_path"):
        _write_funding_adjusted_ledger(rows, output_root / FUNDING_ADJUSTED_LEDGER_NAME)
    output.write_text(json.dumps(writable, indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--provider-report-path", default=str(DEFAULT_PROVIDER_REPORT))
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_funding_ledger_report(
        repo_root=Path(args.repo_root),
        provider_report_path=Path(args.provider_report_path),
        source_run_dir=Path(args.source_run_dir),
        generated_at=args.generated_at or None,
    )
    print(write_btc_funding_ledger_report(payload, Path(args.output_root)))


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_bundle_file(root: Path, filename: str) -> Path | None:
    config = root / DEFAULT_CONFIG
    bundle_dir = selected_btc_perpetual_bundle_dir(root, config)
    if bundle_dir is None:
        return None
    path = bundle_dir / filename
    return path if path.exists() else None


def _read_funding_events(path: Path | None) -> list[FundingRateEvent]:
    if path is None or not path.exists():
        return []
    events: list[FundingRateEvent] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            funding_time = _parse_time(row.get("fundingTime") or row.get("funding_time") or row.get("timestamp"))
            if funding_time is None:
                continue
            mark_price = _float(row.get("markPrice") or row.get("mark_price") or row.get("price"))
            funding_rate = _float(row.get("fundingRate") or row.get("funding_rate") or row.get("value"))
            if mark_price is None or funding_rate is None:
                continue
            events.append(
                FundingRateEvent(
                    funding_time=funding_time,
                    funding_rate=funding_rate,
                    mark_price=mark_price,
                    source_record_id=str(row.get("source_record_id", "")),
                )
            )
    return events


def _read_trade_ledger_trades(path: Path) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            side = str(row.get("side", "")).lower()
            quantity = _float(row.get("size") or row.get("quantity"))
            entry_price = _float(row.get("entry_price"))
            exit_price = _float(row.get("exit_price"))
            entry_time = _parse_time(row.get("entry_time"))
            exit_time = _parse_time(row.get("exit_time"))
            if quantity is None or entry_price is None or exit_price is None or entry_time is None or exit_time is None:
                continue
            trades.append(
                {
                    **row,
                    "side": side,
                    "quantity": quantity,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "entry_time_parsed": entry_time,
                    "exit_time_parsed": exit_time,
                    "net_pnl_float": _float(row.get("net_pnl")) or 0.0,
                }
            )
    return trades


def _trades_to_fills(trades: list[Mapping[str, Any]]) -> list[FundingFill]:
    fills: list[FundingFill] = []
    for row in trades:
        side = str(row.get("side", "")).lower()
        entry_side = "buy" if side in {"long", "buy"} else "sell"
        exit_side = "sell" if entry_side == "buy" else "buy"
        trade_id = str(row.get("trade_id", ""))
        fills.append(
            FundingFill(
                filled_at=row["entry_time_parsed"],
                side=entry_side,
                quantity=float(row["quantity"]),
                price=float(row["entry_price"]),
                fill_id=f"{trade_id}:entry",
            )
        )
        fills.append(
            FundingFill(
                filled_at=row["exit_time_parsed"],
                side=exit_side,
                quantity=float(row["quantity"]),
                price=float(row["exit_price"]),
                fill_id=f"{trade_id}:exit",
            )
        )
    return fills


def _funding_adjusted_trade_rows(
    trades: list[Mapping[str, Any]],
    funding_events: list[FundingRateEvent],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered_events = sorted(funding_events, key=lambda event: event.funding_time)
    for trade in trades:
        entry_time = trade["entry_time_parsed"]
        exit_time = trade["exit_time_parsed"]
        signed_qty = float(trade["quantity"]) if str(trade.get("side")) in {"long", "buy"} else -float(trade["quantity"])
        trade_events = [
            event
            for event in ordered_events
            if entry_time <= event.funding_time < exit_time
        ]
        funding_pnl = round(
            sum(-signed_qty * float(event.mark_price) * float(event.funding_rate) for event in trade_events),
            12,
        )
        net_pnl = float(trade["net_pnl_float"])
        row = {
            key: value
            for key, value in trade.items()
            if key not in {"entry_time_parsed", "exit_time_parsed", "net_pnl_float", "quantity"}
        }
        row["funding_event_count"] = len(trade_events)
        row["funding_pnl"] = funding_pnl
        row["net_pnl_before_funding"] = round(net_pnl, 12)
        row["net_pnl_after_funding"] = round(net_pnl + funding_pnl, 12)
        rows.append(row)
    return rows


def _write_funding_adjusted_ledger(rows: list[Mapping[str, Any]], path: Path) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _funding_adjusted_rows_from_report(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    funding_rate_source = payload.get("funding_rate_source")
    fills_source = payload.get("fills_source")
    if not funding_rate_source or not fills_source:
        return []
    funding_events = _read_funding_events(Path(str(funding_rate_source)))
    trades = _read_trade_ledger_trades(Path(str(fills_source)))
    if not funding_events or not trades:
        return []
    return _funding_adjusted_trade_rows(trades, funding_events)


def _funding_interval_hours(events: list[FundingRateEvent]) -> float | None:
    if len(events) < 2:
        return None
    ordered = sorted(event.funding_time for event in events)
    deltas = [
        (ordered[index + 1] - ordered[index]).total_seconds() / 3600
        for index in range(len(ordered) - 1)
        if ordered[index + 1] > ordered[index]
    ]
    if not deltas:
        return None
    return round(sorted(deltas)[len(deltas) // 2], 6)


def _parse_time(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value)
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(float(number), tz=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
