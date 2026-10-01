from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.strategy_attribution import (
    build_btc_multi_strategy_attribution,
    render_btc_multi_strategy_attribution_markdown,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_multi_strategy_attribution/latest")
DEFAULT_INTRADAY_RUN_DIR = Path(
    "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
)
DEFAULT_SOURCES = {
    "current_status": Path("artifacts/btc_current_status/latest/btc_current_status_report.json"),
    "trend_forward_observation": Path(
        "artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json"
    ),
    "ga_factor_diagnostics": Path("artifacts/btc_ga_factor_mining/latest/ga_factor_diagnostics_report.json"),
    "ga_candidate_review": Path("artifacts/btc_ga_factor_mining/latest/ga_candidate_review_packet.json"),
    "timesfm_vs_trend_baseline": Path(
        "artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest/btc_timesfm_vs_trend_baseline_oos_report.json"
    ),
    "compression_expansion_attribution": Path(
        "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json"
    ),
}


def build_btc_multi_strategy_attribution_file(
    *,
    repo_root: Path = Path("."),
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    intraday_run_dir: Path = DEFAULT_INTRADAY_RUN_DIR,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated_at = datetime.now(timezone.utc)
    intraday_dir = _resolve(root, intraday_run_dir)
    sources: dict[str, Mapping[str, Any] | None] = {
        name: _load_json(_resolve(root, path)) for name, path in DEFAULT_SOURCES.items()
    }
    source_paths: dict[str, str] = {
        name: _relpath(_resolve(root, path), root) for name, path in DEFAULT_SOURCES.items()
    }
    intraday_sources = {
        "intraday_canonical_backtest": intraday_dir / "canonical_backtest_report.json",
        "intraday_fold_audit": intraday_dir / "fold_regime_contract_audit.json",
    }
    for name, path in intraday_sources.items():
        sources[name] = _load_json(path)
        source_paths[name] = _relpath(path, root)

    trade_ledger_path = intraday_dir / "trade_ledger.csv"
    trade_attribution_path = intraday_dir / "trade_attribution.csv"
    sources["intraday_trade_ledger_summary"] = _csv_summary(trade_ledger_path)
    sources["intraday_trade_attribution_summary"] = _csv_summary(trade_attribution_path)
    source_paths["intraday_trade_ledger_summary"] = _relpath(trade_ledger_path, root)
    source_paths["intraday_trade_attribution_summary"] = _relpath(trade_attribution_path, root)

    output_dir = _resolve(root, output_root)
    json_path = output_dir / "btc_multi_strategy_attribution_report.json"
    markdown_path = output_dir / "btc_multi_strategy_attribution_summary_cn.md"
    payload = build_btc_multi_strategy_attribution(
        generated_at_utc=generated_at,
        sources=sources,
        source_paths=source_paths,
        report_paths={
            "json": _relpath(json_path, root),
            "markdown_cn": _relpath(markdown_path, root),
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_btc_multi_strategy_attribution_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC read-only multi-strategy attribution report.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--intraday-run-dir", type=Path, default=DEFAULT_INTRADAY_RUN_DIR)
    args = parser.parse_args()
    payload = build_btc_multi_strategy_attribution_file(
        repo_root=args.repo_root,
        output_root=args.output_root,
        intraday_run_dir=args.intraday_run_dir,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "decision": payload["decision"],
                "blockers": payload["blockers"],
                "warnings": payload["warnings"],
                "report_paths": payload.get("report_paths", {}),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_json(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else None


def _csv_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "missing",
            "row_count": 0,
            "path": str(path),
            "sha256": "",
            "columns": [],
        }
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = sum(1 for _ in reader)
        columns = [str(item) for item in (reader.fieldnames or [])]
    return {
        "status": "present",
        "row_count": rows,
        "path": str(path),
        "sha256": sha256,
        "columns": columns,
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
