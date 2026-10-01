from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.monitoring_snapshot import (
    build_btc_monitoring_snapshot,
    render_btc_monitoring_snapshot_html,
    render_btc_monitoring_snapshot_markdown,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_monitoring/latest")
DEFAULT_DB = Path("data/market_data.sqlite")
DEFAULT_SOURCES = {
    "current_status": Path("artifacts/btc_current_status/latest/btc_current_status_report.json"),
    "data_status": Path("artifacts/btc_data_status/latest/btc_data_status_report.json"),
    "gate_dashboard": Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"),
    "daily_observation": Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json"),
    "funding_ledger": Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json"),
    "live_readiness": Path("artifacts/btc_live_readiness/latest/btc_live_readiness_risk_constitution_report.json"),
    "paper_validation_runtime": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_runtime_report.json"),
    "paper_validation_replay": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_replay_report.json"),
    "incident_replay_drill": Path("artifacts/btc_completion_evidence/latest/incident_replay_drill_contract.json"),
    "paper_oms_session_contract": Path("artifacts/btc_completion_evidence/latest/paper_oms_session_contract.json"),
}


def build_btc_monitoring_snapshot_file(
    *,
    repo_root: Path = Path("."),
    db_path: Path = DEFAULT_DB,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated_at = datetime.now(timezone.utc)
    sources: dict[str, Mapping[str, Any] | None] = {
        name: _load_json(_resolve(root, path)) for name, path in DEFAULT_SOURCES.items()
    }
    source_paths: dict[str, str] = {
        name: _relpath(_resolve(root, path), root) for name, path in DEFAULT_SOURCES.items()
    }
    _add_latest_chain_sources(root=root, sources=sources, source_paths=source_paths)
    market_1h_status = load_market_1h_status(
        _resolve(root, db_path),
        generated_at_utc=generated_at,
    )
    output_dir = _resolve(root, output_root)
    json_path = output_dir / "btc_monitoring_snapshot.json"
    md_path = output_dir / "btc_monitoring_snapshot_cn.md"
    html_path = output_dir / "btc_monitoring_snapshot.html"
    payload = build_btc_monitoring_snapshot(
        generated_at_utc=generated_at,
        market_1h_status=market_1h_status,
        sources=sources,
        source_paths=source_paths,
        report_paths={
            "json": _relpath(json_path, root),
            "markdown_cn": _relpath(md_path, root),
            "html": _relpath(html_path, root),
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_btc_monitoring_snapshot_markdown(payload), encoding="utf-8")
    html_path.write_text(render_btc_monitoring_snapshot_html(payload), encoding="utf-8")
    return payload


def load_market_1h_status(db_path: Path, *, generated_at_utc: datetime) -> dict[str, Any]:
    if not db_path.exists():
        return {"status": "missing", "db_path": str(db_path)}
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        count_row = connection.execute(
            """
            select count(*) as row_count,
                   min(close_time) as first_close_time,
                   max(close_time) as latest_close_time
            from market_klines
            where exchange = ? and symbol = ? and interval = ?
            """,
            ("binance_spot", "BTCUSDT", "1h"),
        ).fetchone()
        latest_row = connection.execute(
            """
            select exchange, symbol, interval, open_time, close_time, close,
                   volume, source, ingested_at, updated_at
            from market_klines
            where exchange = ? and symbol = ? and interval = ?
            order by close_time_ms desc
            limit 1
            """,
            ("binance_spot", "BTCUSDT", "1h"),
        ).fetchone()
    if latest_row is None:
        return {"status": "missing", "db_path": str(db_path), "exchange": "binance_spot", "symbol": "BTCUSDT", "interval": "1h"}
    latest_close_time = str(latest_row["close_time"])
    return {
        "status": "pass",
        "db_path": str(db_path),
        "exchange": str(latest_row["exchange"]),
        "symbol": str(latest_row["symbol"]),
        "interval": str(latest_row["interval"]),
        "row_count": int(count_row["row_count"] or 0),
        "first_close_time_utc": count_row["first_close_time"],
        "latest_close_time_utc": latest_close_time,
        "latest_open_time_utc": latest_row["open_time"],
        "latest_close": float(latest_row["close"]),
        "latest_volume": float(latest_row["volume"]),
        "latest_source": latest_row["source"],
        "latest_ingested_at_utc": latest_row["ingested_at"],
        "latest_updated_at_utc": latest_row["updated_at"],
        "closed_bar_only": _is_closed_bar(latest_close_time, generated_at_utc=generated_at_utc),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC read-only monitoring snapshot artifacts.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    payload = build_btc_monitoring_snapshot_file(
        repo_root=args.repo_root,
        db_path=args.db_path,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "blockers": payload["blockers"],
                "warnings": payload["warnings"],
                "report_paths": payload.get("report_paths", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _add_latest_chain_sources(
    *,
    root: Path,
    sources: dict[str, Mapping[str, Any] | None],
    source_paths: dict[str, str],
) -> None:
    daily = sources.get("daily_observation")
    chain = daily.get("forecast_target_order_chain") if isinstance(daily, Mapping) else {}
    if not isinstance(chain, Mapping):
        chain = {}
    chain_paths = {
        "latest_target": chain.get("target_artifact"),
        "latest_order_intent": chain.get("order_intent_artifact"),
        "latest_paper_oms_lifecycle": chain.get("paper_oms_lifecycle_artifact"),
    }
    for name, raw_path in chain_paths.items():
        path = Path(str(raw_path)) if raw_path else Path("__missing__")
        resolved = _resolve(root, path)
        sources[name] = _load_json(resolved)
        source_paths[name] = _relpath(resolved, root) if raw_path else ""


def _load_json(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else None


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_closed_bar(value: str, *, generated_at_utc: datetime) -> bool:
    try:
        close_time = datetime.fromisoformat(value)
    except ValueError:
        return False
    if close_time.tzinfo is None:
        close_time = close_time.replace(tzinfo=timezone.utc)
    return close_time.astimezone(timezone.utc) <= generated_at_utc.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
