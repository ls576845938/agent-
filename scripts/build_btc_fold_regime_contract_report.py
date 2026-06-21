#!/usr/bin/env python3
"""Build BTC fold/regime contract report from existing validation artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SOURCE_RUN_DIR = Path(
    "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
)
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_fold_regime/latest")
FOLD_DEFINITION_VERSION = "btc_walk_forward_fold_contract_v1"
REGIME_CLASSIFIER_VERSION = "classify_btc_regimes_v1"


def build_btc_fold_regime_contract_report(
    *,
    repo_root: Path | None = None,
    source_run_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = _resolve(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    audit = _read_json(run_dir / "fold_regime_contract_audit.json")
    data_status = _read_json(run_dir / "btc_data_fold_regime_status_report.json")
    canonical = _read_json(run_dir / "canonical_backtest_report.json")
    fold_contract = _mapping(audit.get("fold_contract"))
    regime_contract = _mapping(audit.get("regime_contract"))
    data_range = _mapping(canonical.get("data_range"))
    sample_start = str(data_range.get("start") or _first_interval_value(data_status, "start") or "")
    folds = _fold_rows(fold_contract, sample_start=sample_start)
    blockers = _build_blockers(folds=folds, fold_contract=fold_contract, regime_contract=regime_contract)
    gate_regimes = [str(item) for item in regime_contract.get("gate_eligible_regimes", [])]
    diagnostic_regimes = [str(item) for item in regime_contract.get("diagnostic_regimes", [])]
    return {
        "schema_version": "btc_fold_regime_contract_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "source_run_dir": _relpath(run_dir, root),
        "source_fold_regime_contract_audit": _relpath(run_dir / "fold_regime_contract_audit.json", root)
        if (run_dir / "fold_regime_contract_audit.json").exists()
        else None,
        "status": "pass" if not blockers else "fail",
        "fold_definition": {
            "fold_definition_version": FOLD_DEFINITION_VERSION,
            "fold_count": int(fold_contract.get("fold_count", len(folds)) or 0),
            "fold_schema_version": "btc_oos_fold_schema_v1",
            "folds": folds,
        },
        "regime_classifier": {
            "regime_classifier_version": REGIME_CLASSIFIER_VERSION,
            "classifier_inputs": [
                "close",
                "high",
                "low",
                "volume",
                "taker_buy_base_volume",
                "trend_window_168",
                "volatility_window_168",
                "compression_window_336",
            ],
            "regime_labels": _dedupe(gate_regimes + diagnostic_regimes),
            "gate_regimes": gate_regimes,
            "diagnostic_regimes": diagnostic_regimes,
            "gate_source": str(regime_contract.get("gate_source", "")),
            "diagnostic_source": str(regime_contract.get("diagnostic_source", "")),
        },
        "regime_dimensions": {
            "trend_regime": True,
            "volatility_regime": True,
            "liquidity_regime": False,
            "funding_regime": False,
            "drawdown_regime": False,
        },
        "fold_contract_status": str(fold_contract.get("status", "missing")),
        "regime_contract_status": str(regime_contract.get("status", "missing")),
        "regime_gate_pass_rate": _float(regime_contract.get("pass_rate")),
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
        "blockers": blockers,
    }


def write_btc_fold_regime_contract_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "fold_regime_contract_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_fold_regime_contract_report(
        repo_root=Path(args.repo_root),
        source_run_dir=Path(args.source_run_dir),
        generated_at=args.generated_at or None,
    )
    print(write_btc_fold_regime_contract_report(payload, Path(args.output_root)))


def _fold_rows(fold_contract: Mapping[str, Any], *, sample_start: str) -> list[dict[str, Any]]:
    rows = []
    previous_train_start = sample_start
    for raw in _list_of_mappings(fold_contract.get("folds")):
        test_start = str(raw.get("validation_start", ""))
        test_end = str(raw.get("validation_end", ""))
        rows.append(
            {
                "fold_id": str(raw.get("fold_id", "")),
                "train_start": previous_train_start,
                "train_end": test_start,
                "test_start": test_start,
                "test_end": test_end,
                "sample_type": "rolling_event_ledger_oos_validation",
                "notes": "Fold definition is for validation comparability; candidate parameters are fixed, not optimized here.",
            }
        )
        previous_train_start = sample_start or previous_train_start
    return rows


def _build_blockers(
    *,
    folds: list[Mapping[str, Any]],
    fold_contract: Mapping[str, Any],
    regime_contract: Mapping[str, Any],
) -> list[str]:
    blockers = []
    if not FOLD_DEFINITION_VERSION:
        blockers.append("btc_fold_definition_version_missing")
    if not REGIME_CLASSIFIER_VERSION:
        blockers.append("btc_regime_classifier_version_missing")
    if not folds:
        blockers.append("btc_fold_test_windows_missing")
    for row in folds:
        if not row.get("test_start") or not row.get("test_end"):
            blockers.append("btc_fold_test_window_missing")
        if str(row.get("train_end")) > str(row.get("test_start")):
            blockers.append("btc_fold_train_test_overlap_invalid")
    if str(fold_contract.get("status", "")) != "pass":
        blockers.append("btc_fold_contract_not_pass")
    if not regime_contract.get("gate_eligible_regimes"):
        blockers.append("btc_gate_regimes_missing")
    if not (regime_contract.get("diagnostic_regimes") is not None):
        blockers.append("btc_diagnostic_regimes_not_explicit")
    if str(regime_contract.get("status", "")) != "pass":
        blockers.append("btc_regime_contract_not_pass")
    return _dedupe(blockers)


def _first_interval_value(payload: Mapping[str, Any], key: str) -> str:
    intervals = _list_of_mappings(payload.get("intervals"))
    values = [str(item.get(key, "")) for item in intervals if str(item.get(key, ""))]
    return min(values) if values else ""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
