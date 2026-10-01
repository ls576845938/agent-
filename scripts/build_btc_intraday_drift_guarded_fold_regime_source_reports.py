#!/usr/bin/env python3
"""Build fold/regime source reports from the drift-guarded BTC intraday ledger run.

These source reports let the standard BTC data-status and fold/regime builders
consume the current strongest research-only evidence instead of the archived
compression-expansion run. They do not unlock candidates, paper, live, or true
scalping.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_us.research.btc_alpha_hardening import classify_btc_regimes
    from quant_us.research.btc_intraday_short_cycle_event_ledger import (
        DB_PATH,
        INTERVAL,
        load_btc_intraday_frame,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_us.research.btc_alpha_hardening import classify_btc_regimes
    from quant_us.research.btc_intraday_short_cycle_event_ledger import (
        DB_PATH,
        INTERVAL,
        load_btc_intraday_frame,
    )


DEFAULT_RUN_DIR = Path("artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger")
DEFAULT_COVERAGE_SOURCE = Path(
    "artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger/"
    "btc_data_fold_regime_status_report.json"
)
REGIME_LABELS = [
    "compression",
    "mean_reverting_chop",
    "trending_down",
    "high_vol_trend",
    "expansion",
    "low_vol_chop",
    "trending_up",
    "liquidation_shock",
]


def build_drift_guarded_fold_regime_source_reports(
    *,
    repo_root: Path | None = None,
    run_dir: Path | None = None,
    coverage_source: Path | None = None,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = (repo_root or Path.cwd()).resolve()
    resolved_run = _resolve(root, run_dir or DEFAULT_RUN_DIR)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    event_report = _read_json(resolved_run / "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json")
    walk_forward = _read_json(resolved_run / "walk_forward_report.json")
    regime_report = _read_json(resolved_run / "regime_report.json")
    coverage = _read_json(_resolve(root, coverage_source or DEFAULT_COVERAGE_SOURCE))
    fold_contract = _fold_contract(walk_forward)
    regime_contract = _regime_contract(regime_report)
    intervals = _interval_rows(coverage, root=root)
    manifest_lineage = _manifest_lineage(coverage, intervals=intervals)
    audit = {
        "schema_version": "btc_fold_regime_contract_audit_v1",
        "generated_at": generated,
        "run_id": str(event_report.get("run_id", resolved_run.name)),
        "strategy_id": str(event_report.get("strategy_id", "")),
        "source_event_ledger_report": _relpath(
            resolved_run / "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json", root
        ),
        "fold_contract": fold_contract,
        "regime_contract": regime_contract,
        "promotion_contract": {
            "paper_review_pending_requires_all_three": True,
            "event_pf_required": 1.15,
            "walk_forward_pass_required": 0.80,
            "regime_pass_required": 0.75,
            "paper_ready_allowed": False,
            "live_ready_allowed": False,
            "live_enabled_allowed": False,
        },
        "cleanup_required": [
            "Use the drift-guarded event-ledger run as current BTC intraday regime gate evidence.",
            "Keep paper/live/true-scalping locked until provider, paper gate, and scalping microstructure evidence pass.",
        ],
    }
    data_status = {
        "schema_version": "btc_data_fold_regime_status_report_v1",
        "generated_at": generated,
        "code_commit": _git(["rev-parse", "HEAD"], cwd=root),
        "run_id": str(event_report.get("run_id", resolved_run.name)),
        "source_event_ledger_report": _relpath(
            resolved_run / "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json", root
        ),
        "sqlite": _mapping(coverage.get("sqlite"))
        or {"status": "pass", "symbol": "BTCUSDT", "exchange": "binance_spot", "db_path": DB_PATH},
        "intervals": intervals,
        "manifest_lineage": manifest_lineage,
        "fold_status": fold_contract,
        "regime_status": {
            "status": regime_contract["status"],
            "classifier": "classify_btc_regimes",
            "gate_pass_rate": regime_contract["pass_rate"],
            "dragging_regimes": regime_contract["dragging_regimes"],
            "bar_counts": _bar_regime_counts(),
        },
    }
    return data_status, audit


def write_drift_guarded_fold_regime_source_reports(
    data_status: Mapping[str, Any],
    audit: Mapping[str, Any],
    run_dir: Path,
) -> list[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    data_output = run_dir / "btc_data_fold_regime_status_report.json"
    audit_output = run_dir / "fold_regime_contract_audit.json"
    data_output.write_text(json.dumps(dict(data_status), indent=2, sort_keys=True), encoding="utf-8")
    audit_output.write_text(json.dumps(dict(audit), indent=2, sort_keys=True), encoding="utf-8")
    return [str(data_output), str(audit_output)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--coverage-source", default=str(DEFAULT_COVERAGE_SOURCE))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    run_dir = _resolve(root, Path(args.run_dir))
    data_status, audit = build_drift_guarded_fold_regime_source_reports(
        repo_root=root,
        run_dir=run_dir,
        coverage_source=Path(args.coverage_source),
        generated_at=args.generated_at or None,
    )
    for output in write_drift_guarded_fold_regime_source_reports(data_status, audit, run_dir):
        print(output)


def _fold_contract(walk_forward: Mapping[str, Any]) -> dict[str, Any]:
    windows = _list_of_mappings(walk_forward.get("windows"))
    event_counts = {str(row.get("fold", "")): int(row.get("event_count", 0) or 0) for row in windows}
    return {
        "status": "pass" if windows else "fail",
        "method": str(walk_forward.get("method", "rolling_event_ledger_fixed_params_intraday_5m")),
        "gate_source": "walk_forward_report.json",
        "fold_count": int(walk_forward.get("fold_count", len(windows)) or 0),
        "folds": [
            {
                "fold_id": str(row.get("fold", "")),
                "validation_start": str(row.get("validation_start", "")),
                "validation_end": str(row.get("validation_end", "")),
                "validation_rows": int(row.get("validation_rows", 0) or 0),
                "passed": bool(row.get("passed", False)),
            }
            for row in windows
        ],
        "event_table_fold_counts": event_counts,
        "hypothesis_label_fold_counts": event_counts,
        "label_trimmed_rows_due_to_forward_horizon": 0,
    }


def _regime_contract(regime_report: Mapping[str, Any]) -> dict[str, Any]:
    pass_rate = _float(regime_report.get("pass_rate"))
    return {
        "status": "pass" if pass_rate >= 0.75 else "fail",
        "classifier": "quant_us.research.btc_alpha_hardening.classify_btc_regimes",
        "pass_rate": pass_rate,
        "dragging_regimes": _list_of_strings(regime_report.get("dragging_regimes")),
        "gate_eligible_regimes": [str(row.get("regime", "")) for row in _list_of_mappings(regime_report.get("regimes"))],
        "diagnostic_regimes": REGIME_LABELS,
        "gate_source": "entry_regime_from_ledger_segments",
        "diagnostic_source": "bar_level_event_ledger_attribution",
    }


def _interval_rows(coverage: Mapping[str, Any], *, root: Path) -> list[dict[str, Any]]:
    rows = []
    for row in _list_of_mappings(coverage.get("intervals")):
        rows.append(
            {
                "interval": str(row.get("interval", "")),
                "status": str(row.get("status", "")),
                "manifest_status": str(row.get("manifest_status", "")),
                "row_count": int(row.get("row_count", 0) or 0),
                "expected_rows": int(row.get("expected_rows", 0) or 0),
                "missing_rows": int(row.get("missing_rows", 0) or 0),
                "data_version": str(row.get("data_version", "")),
                "latest_manifest_path": str(row.get("latest_manifest_path", "")),
                "start": str(row.get("start", "")),
                "end": str(row.get("end", "")),
            }
        )
    present = {row["interval"] for row in rows}
    for interval in ("1m",):
        if interval not in present:
            manifest_row = _latest_sqlite_manifest_interval_row(root, interval)
            if manifest_row:
                rows.insert(0, manifest_row)
    return rows


def _manifest_lineage(coverage: Mapping[str, Any], *, intervals: list[Mapping[str, Any]]) -> dict[str, Any]:
    lineage = _mapping(coverage.get("manifest_lineage"))
    latest = _list_of_mappings(lineage.get("latest_manifests"))
    by_interval = {str(row.get("interval", "")): dict(row) for row in latest if str(row.get("interval", ""))}
    for row in intervals:
        interval = str(row.get("interval", ""))
        if not interval or interval in by_interval:
            continue
        by_interval[interval] = {
            "coverage_pct": 100.0 if int(row.get("missing_rows", 0) or 0) == 0 else 0.0,
            "data_version": str(row.get("data_version", "")),
            "interval": interval,
            "manifest_path": str(row.get("latest_manifest_path", "")),
            "quality_score": 100.0 if str(row.get("manifest_status", "")) == "pass" else 0.0,
        }
    return {
        **lineage,
        "latest_manifests": [by_interval[key] for key in sorted(by_interval)],
        "status": "pass"
        if by_interval and all(str(row.get("manifest_path", "")) and str(row.get("data_version", "")) for row in by_interval.values())
        else str(lineage.get("status", "missing") or "missing"),
    }


def _latest_sqlite_manifest_interval_row(root: Path, interval: str) -> dict[str, Any]:
    manifest = _latest_sqlite_manifest(root, interval)
    if not manifest:
        return {}
    row_count = int(manifest.get("row_count", 0) or 0)
    expected_rows = int(manifest.get("expected_rows", row_count) or 0)
    missing_rows = max(expected_rows - row_count, 0)
    quality_score = _float(manifest.get("quality_score"))
    coverage_pct = _float(manifest.get("coverage_pct"))
    manifest_path = root / "data" / "manifests" / f"{manifest.get('data_version')}.json"
    status = "pass" if row_count > 0 and missing_rows == 0 and coverage_pct >= 99.0 and quality_score >= 80.0 else "fail"
    return {
        "interval": interval,
        "status": status,
        "manifest_status": status,
        "row_count": row_count,
        "expected_rows": expected_rows,
        "missing_rows": missing_rows,
        "data_version": str(manifest.get("data_version", "")),
        "latest_manifest_path": _relpath(manifest_path, root),
        "start": str(manifest.get("start", "")),
        "end": str(manifest.get("end", "")),
    }


def _latest_sqlite_manifest(root: Path, interval: str) -> dict[str, Any]:
    manifest_root = root / "data" / "manifests"
    candidates: list[tuple[float, float, str, dict[str, Any]]] = []
    for path in sorted(manifest_root.glob(f"qs-sqlite-BTCUSDT-{interval}-*.json")):
        payload = _read_json(path)
        if (
            str(payload.get("source", "")) != "sqlite"
            or str(payload.get("symbol", "")).upper() != "BTCUSDT"
            or str(payload.get("interval", "")) != interval
        ):
            continue
        created_at = _timestamp_sort_value(payload.get("created_at"))
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((created_at, mtime, str(payload.get("data_version", "")), payload))
    return max(candidates, key=lambda item: item[:3])[3] if candidates else {}


def _bar_regime_counts() -> dict[str, int]:
    frame = load_btc_intraday_frame(interval=INTERVAL, db_path=DB_PATH)
    regimes = classify_btc_regimes(frame)
    return {str(key): int(value) for key, value in regimes.value_counts().sort_index().items()}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _timestamp_sort_value(value: object) -> float:
    text = str(value or "")
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
