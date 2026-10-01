#!/usr/bin/env python3
"""Probe IBKR historical bars for US ETF research.

This is a read-only market-data probe. It does not create orders, does not use
account state, and does not promote IBKR data as research-clean historical data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

import pandas as pd


SCHEMA_VERSION = "us_equity_ibkr_historical_bars_probe_report_v1"
DEFAULT_SYMBOLS = ("QQQ", "TQQQ")
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_intraday/ibkr_probe/interval=1m")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/ibkr_historical_bars_probe_report.json")


class IbkrClient(Protocol):
    def connect(self, host: str, port: int, clientId: int, timeout: float, **kwargs: Any) -> Any: ...

    def disconnect(self) -> Any: ...

    def isConnected(self) -> bool: ...

    def qualifyContracts(self, contract: Any) -> list[Any]: ...

    def reqHistoricalData(
        self,
        contract: Any,
        endDateTime: str,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
        keepUpToDate: bool,
    ) -> list[Any]: ...


def probe_ibkr_historical_bars(
    *,
    repo_root: Path,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 71,
    duration: str = "1 D",
    bar_size: str = "1 min",
    what_to_show: str = "TRADES",
    use_rth: bool = False,
    connect_timeout_seconds: float = 5.0,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    generated_at: str | None = None,
    ib_client: IbkrClient | None = None,
    stock_factory: Any | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    output_abs = _resolve(root, output_root)
    report_abs = _resolve(root, report_path)
    kline_root = output_abs / "kline"
    selected_symbols = tuple(_unique(symbols))

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "blocked",
        "provider": "ibkr",
        "asset": "us_equity",
        "source_type": "broker_historical_market_data_probe",
        "symbols": list(selected_symbols),
        "symbol_count": len(selected_symbols),
        "host": host,
        "port": int(port),
        "client_id": int(client_id),
        "duration": duration,
        "bar_size": bar_size,
        "what_to_show": what_to_show,
        "use_rth": bool(use_rth),
        "readonly_connection_requested": True,
        "output_root": _relpath(output_abs, root),
        "report_path": _relpath(report_abs, root),
        "guardrails": _guardrails(),
        "symbol_reports": {},
        "blockers": [],
    }

    try:
        ib, stock = _load_ibkr_runtime(ib_client=ib_client, stock_factory=stock_factory)
    except Exception as exc:  # noqa: BLE001
        payload["blockers"] = ["ibkr_python_runtime_missing"]
        payload["runtime_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        _write_json(report_abs, payload)
        return payload

    try:
        _connect_readonly(
            ib,
            host=host,
            port=int(port),
            client_id=int(client_id),
            timeout=float(connect_timeout_seconds),
        )
        if not ib.isConnected():
            raise ConnectionError("ibkr_not_connected_after_connect")
    except Exception as exc:  # noqa: BLE001
        payload["blockers"] = ["ibkr_tws_or_gateway_not_connected"]
        payload["connection_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        _write_json(report_abs, payload)
        return payload

    kline_root.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    try:
        for symbol in selected_symbols:
            symbol_report = _fetch_symbol(
                ib=ib,
                stock_factory=stock,
                symbol=symbol,
                duration=duration,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
                kline_root=kline_root,
                root=root,
            )
            payload["symbol_reports"][symbol] = symbol_report
            blockers.extend(symbol_report.get("blockers", []))
    finally:
        try:
            ib.disconnect()
        except Exception:  # noqa: BLE001
            pass

    available = [item for item in payload["symbol_reports"].values() if item.get("status") == "available"]
    payload["status"] = "pass" if len(available) == len(selected_symbols) and not blockers else "partial"
    payload["summary"] = _summary(payload["symbol_reports"])
    payload["blockers"] = _dedupe(blockers)
    _write_json(report_abs, payload)
    return payload


def _fetch_symbol(
    *,
    ib: IbkrClient,
    stock_factory: Any,
    symbol: str,
    duration: str,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
    kline_root: Path,
    root: Path,
) -> dict[str, Any]:
    path = kline_root / f"{symbol}.parquet"
    try:
        contract = stock_factory(symbol, "SMART", "USD")
        qualified = ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=bool(use_rth),
            formatDate=2,
            keepUpToDate=False,
        )
        frame = _bars_to_frame(symbol, bars)
        if frame.empty:
            return {
                "status": "blocked",
                "blockers": [f"ibkr_{symbol.lower()}_historical_bars_empty"],
                "rows": 0,
                "path": _relpath(path, root),
            }
        frame.to_parquet(path, index=False)
        return {
            "status": "available",
            "blockers": [],
            "rows": int(len(frame)),
            "start": _ts_str(frame["datetime"].min()),
            "end": _ts_str(frame["datetime"].max()),
            "path": _relpath(path, root),
            "data_version": "ibkr_historical_intraday_probe_v1",
            "promotion_clean_allowed": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "blocked",
            "blockers": [f"ibkr_{symbol.lower()}_historical_bars_failed"],
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            "path": _relpath(path, root),
        }


def _bars_to_frame(symbol: str, bars: Iterable[Any]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for bar in bars:
        dt = pd.Timestamp(getattr(bar, "date"))
        if dt.tzinfo is None:
            dt = dt.tz_localize("UTC")
        else:
            dt = dt.tz_convert("UTC")
        end = dt + pd.Timedelta(minutes=1)
        open_value = float(getattr(bar, "open"))
        high_value = float(getattr(bar, "high"))
        low_value = float(getattr(bar, "low"))
        close_value = float(getattr(bar, "close"))
        records.append(
            {
                "datetime": dt,
                "bar_start_utc": dt,
                "bar_end_utc": end,
                "available_time": end,
                "symbol": symbol.upper(),
                "Open": open_value,
                "High": max(open_value, high_value, low_value, close_value),
                "Low": min(open_value, high_value, low_value, close_value),
                "Close": close_value,
                "Volume": float(getattr(bar, "volume", 0.0) or 0.0),
                "source": "ibkr_historical_data",
                "interval": "1m",
                "data_version": "ibkr_historical_intraday_probe_v1",
                "adjustment_policy": "ibkr_returned_values_no_pit_replay",
                "quality_flags": "",
            }
        )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def _load_ibkr_runtime(*, ib_client: IbkrClient | None, stock_factory: Any | None) -> tuple[IbkrClient, Any]:
    if ib_client is not None and stock_factory is not None:
        return ib_client, stock_factory
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    from ib_insync import IB, Stock  # type: ignore

    return IB(), Stock


def _connect_readonly(
    ib: IbkrClient,
    *,
    host: str,
    port: int,
    client_id: int,
    timeout: float,
) -> Any:
    try:
        return ib.connect(host, port, clientId=client_id, timeout=timeout, readonly=True)
    except TypeError:
        return ib.connect(host, port, clientId=client_id, timeout=timeout)


def _guardrails() -> dict[str, bool]:
    return {
        "private_account_endpoint_used": False,
        "broker_order_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
        "paper_or_live_unlock_allowed": False,
        "promotion_clean_granted_by_this_report": False,
    }


def _summary(symbol_reports: dict[str, Any]) -> dict[str, Any]:
    rows = [int(item.get("rows", 0) or 0) for item in symbol_reports.values()]
    starts = [str(item.get("start")) for item in symbol_reports.values() if item.get("start")]
    ends = [str(item.get("end")) for item in symbol_reports.values() if item.get("end")]
    return {
        "available_symbol_count": sum(1 for item in symbol_reports.values() if item.get("status") == "available"),
        "min_rows": min(rows) if rows else 0,
        "max_rows": max(rows) if rows else 0,
        "common_start_timestamp": max(starts) if starts else None,
        "common_end_timestamp": min(ends) if ends else None,
        "latest_any_timestamp": max(ends) if ends else None,
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).upper().strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item)
        if value and value not in result:
            result.append(value)
    return result


def _ts_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe IBKR historical bars for US ETF research.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=71)
    parser.add_argument("--duration", default="1 D")
    parser.add_argument("--bar-size", default="1 min")
    parser.add_argument("--what-to-show", default="TRADES")
    parser.add_argument("--use-rth", action="store_true")
    parser.add_argument("--connect-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = probe_ibkr_historical_bars(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        host=args.host,
        port=int(args.port),
        client_id=int(args.client_id),
        duration=args.duration,
        bar_size=args.bar_size,
        what_to_show=args.what_to_show,
        use_rth=bool(args.use_rth),
        connect_timeout_seconds=float(args.connect_timeout_seconds),
        output_root=Path(args.output_root),
        report_path=Path(args.report),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "report": payload["report_path"],
                "blockers": payload.get("blockers", []),
                "summary": payload.get("summary", {}),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
