"""Read-only portfolio observability evidence inspection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_OBSERVABILITY_CANDIDATES = (
    "reports/portfolio_observability.json",
    "reports/paper_production/portfolio_observability.json",
    "paper_ledger/reports/portfolio_observability.json",
)

_MULTI_STRATEGY_CANDIDATES = (
    "reports/multi_strategy_status.json",
    "reports/paper_production/multi_strategy_status.json",
    "paper_ledger/reports/multi_strategy_status.json",
)

_MULTI_TIMEFRAME_CANDIDATES = (
    "reports/multi_timeframe_status.json",
    "reports/paper_production/multi_timeframe_status.json",
    "paper_ledger/reports/multi_timeframe_status.json",
)

_PNL_ATTRIBUTION_CANDIDATES = (
    "reports/pnl_attribution.json",
    "reports/paper_production/pnl_attribution.json",
    "paper_ledger/reports/pnl_attribution.json",
)

_PAPER_SESSION_MANIFEST_CANDIDATES = (
    "paper_ledger/audit/paper_session_manifest.json",
    "reports/paper_production/paper_session_manifest.json",
)


@dataclass(frozen=True)
class PortfolioObservabilityStatus:
    data_root: str
    multi_strategy: dict[str, Any] = field(default_factory=dict)
    multi_timeframe: dict[str, Any] = field(default_factory=dict)
    pnl_attribution: dict[str, Any] = field(default_factory=dict)
    paper_submit_gates: dict[str, Any] = field(default_factory=dict)
    next_paper_command: str = ""
    live_state: str = "FROZEN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_root": self.data_root,
            "multi_strategy": dict(self.multi_strategy),
            "multi_timeframe": dict(self.multi_timeframe),
            "pnl_attribution": dict(self.pnl_attribution),
            "paper_submit_gates": dict(self.paper_submit_gates),
            "next_paper_command": self.next_paper_command,
            "live_state": self.live_state,
        }


def inspect_portfolio_observability(
    data_root: str | Path = "data",
    *,
    strategy: str = "portfolio",
) -> PortfolioObservabilityStatus:
    """Summarize persisted portfolio observability artifacts.

    This function only reads JSON evidence already on disk. Missing evidence is
    rendered as fail-closed operator status, not inferred from live runtime.
    """
    root = Path(data_root)
    aggregate_path, aggregate = _first_json(root, _OBSERVABILITY_CANDIDATES)
    multi_strategy_path, multi_strategy_payload = _first_json(root, _MULTI_STRATEGY_CANDIDATES)
    multi_timeframe_path, multi_timeframe_payload = _first_json(root, _MULTI_TIMEFRAME_CANDIDATES)
    pnl_path, pnl_payload = _first_json(root, _PNL_ATTRIBUTION_CANDIDATES)
    manifest_path, manifest_payload = _first_json(root, _PAPER_SESSION_MANIFEST_CANDIDATES)
    attribution_path, attribution_payload = _latest_json(
        root / "paper_ledger" / "daily_reports",
        "strategy_attribution_*.json",
    )

    if aggregate:
        multi_strategy_payload = _coalesce_dict(
            multi_strategy_payload,
            aggregate.get("multi_strategy"),
            aggregate.get("multi_strategy_status"),
        )
        multi_timeframe_payload = _coalesce_dict(
            multi_timeframe_payload,
            aggregate.get("multi_timeframe"),
            aggregate.get("multi_timeframe_status"),
        )
        pnl_payload = _coalesce_dict(
            pnl_payload,
            aggregate.get("pnl_attribution"),
            aggregate.get("pnl_attribution_status"),
        )

    if not multi_strategy_payload and manifest_payload:
        multi_strategy_payload = _multi_strategy_payload_from_manifest(manifest_payload)
        multi_strategy_path = manifest_path
    if not multi_timeframe_payload and manifest_payload:
        multi_timeframe_payload = _multi_timeframe_payload_from_manifest(manifest_payload)
        multi_timeframe_path = manifest_path
    if not pnl_payload and attribution_payload:
        pnl_payload = attribution_payload
        pnl_path = attribution_path

    multi_strategy = _multi_strategy_status(multi_strategy_payload)
    multi_strategy["evidence_path"] = str(multi_strategy_path or aggregate_path or "")

    multi_timeframe = _multi_timeframe_status(multi_timeframe_payload)
    multi_timeframe["evidence_path"] = str(multi_timeframe_path or aggregate_path or "")

    pnl_attribution = _pnl_attribution_status(pnl_payload)
    pnl_attribution["evidence_path"] = str(pnl_path or aggregate_path or "")

    paper_command = (
        f"python -m quant_us.cli paper --data-root {root} "
        f"--strategy {strategy} --broker simulated --bar-sizes 1m,5m,15m --run"
    )
    return PortfolioObservabilityStatus(
        data_root=str(root),
        multi_strategy=multi_strategy,
        multi_timeframe=multi_timeframe,
        pnl_attribution=pnl_attribution,
        paper_submit_gates={
            "state": "BLOCKED_BY_DEFAULT",
            "paper_submit_default": "disabled",
            "requires": [
                "paper mode",
                "explicit submit_orders=True",
                "QUANT_ALPACA_PAPER_NETWORK_SUBMIT=true",
                "Alpaca paper credentials",
                "paper base URL allowlist",
                "approved paper-review evidence",
                "startup sync artifact",
                "broker recovery artifact",
                "risk/OMS gate",
            ],
        },
        next_paper_command=paper_command,
    )


def _first_json(root: Path, candidates: tuple[str, ...]) -> tuple[Path | None, dict[str, Any]]:
    for relative in candidates:
        path = root / relative
        payload = _read_json_object(path)
        if payload:
            return path, payload
    return None, {}


def _latest_json(root: Path, pattern: str) -> tuple[Path | None, dict[str, Any]]:
    try:
        paths = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return None, {}
    for path in paths:
        payload = _read_json_object(path)
        if payload:
            return path, payload
    return None, {}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _coalesce_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _multi_strategy_payload_from_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("strategies", [])
    strategy_ids: list[str] = []
    if isinstance(entries, list):
        strategy_ids = [
            str(entry.get("strategy_id", ""))
            for entry in entries
            if isinstance(entry, dict) and entry.get("strategy_id")
        ]
    if not strategy_ids:
        raw_ids = payload.get("strategy_ids", [])
        if isinstance(raw_ids, list):
            strategy_ids = [str(strategy_id) for strategy_id in raw_ids if strategy_id]
    child_ids = [
        strategy_id
        for strategy_id in dict.fromkeys(strategy_ids)
        if strategy_id not in {"portfolio", "multi_strategy"}
    ]
    return {
        "strategies": child_ids or strategy_ids,
        "summary": "derived from paper session manifest",
    }


def _multi_timeframe_payload_from_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("strategies", [])
    timeframes: list[str] = []
    for key in ("bar_sizes", "timeframes"):
        raw = payload.get(key, [])
        if isinstance(raw, list):
            timeframes.extend(str(item) for item in raw if item)
    raw_strategy_timeframes = payload.get("strategy_timeframes", {})
    if isinstance(raw_strategy_timeframes, dict):
        timeframes.extend(str(item) for item in raw_strategy_timeframes.values() if item)
    market_data = payload.get("market_data_symbols_evidence", {})
    if isinstance(market_data, dict):
        for key in ("bar_sizes", "timeframes"):
            raw = market_data.get(key, [])
            if isinstance(raw, list):
                timeframes.extend(str(item) for item in raw if item)
    if isinstance(entries, list):
        timeframes.extend(
            str(entry.get("timeframe", ""))
            for entry in entries
            if isinstance(entry, dict) and entry.get("timeframe")
        )
    return {
        "timeframes": list(dict.fromkeys(timeframes)),
        "summary": "derived from paper session manifest",
    }


def _status_from_payload(payload: dict[str, Any], default: str) -> str:
    raw = str(payload.get("status") or payload.get("state") or "").strip().upper()
    if raw:
        return raw
    return default


def _multi_strategy_status(payload: dict[str, Any]) -> dict[str, Any]:
    strategies = payload.get("strategies", payload.get("strategy_ids", []))
    if isinstance(strategies, dict):
        strategy_count = len(strategies)
    elif isinstance(strategies, list):
        strategy_count = len(strategies)
    else:
        strategy_count = int(payload.get("strategy_count", 0) or 0)
    default = "PASS" if strategy_count > 1 else "NOT_CONFIGURED"
    return {
        "status": _status_from_payload(payload, default),
        "strategy_count": strategy_count,
        "detail": str(payload.get("detail") or payload.get("summary") or ""),
    }


def _multi_timeframe_status(payload: dict[str, Any]) -> dict[str, Any]:
    timeframes = payload.get("timeframes", payload.get("timeframe_ids", []))
    if isinstance(timeframes, dict):
        timeframe_count = len(timeframes)
    elif isinstance(timeframes, list):
        timeframe_count = len(timeframes)
    else:
        timeframe_count = int(payload.get("timeframe_count", 0) or 0)
    default = "PASS" if timeframe_count > 1 else "NOT_CONFIGURED"
    return {
        "status": _status_from_payload(payload, default),
        "timeframe_count": timeframe_count,
        "detail": str(payload.get("detail") or payload.get("summary") or ""),
    }


def _pnl_attribution_status(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows", payload.get("attribution", payload.get("by_strategy", [])))
    if isinstance(rows, dict):
        row_count = len(rows)
    elif isinstance(rows, list):
        row_count = len(rows)
    else:
        row_count = int(payload.get("row_count", 0) or 0)
    default = "PASS" if row_count > 0 else "MISSING"
    return {
        "status": _status_from_payload(payload, default),
        "row_count": row_count,
        "detail": str(payload.get("detail") or payload.get("summary") or ""),
    }
