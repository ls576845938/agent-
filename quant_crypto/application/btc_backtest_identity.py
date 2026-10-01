from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.application.btc_strategy_registry import (
    BTCStrategySpec,
    STABLE_STRATEGY_LINE,
    compare_strategy_identities,
)


SCHEMA_VERSION = "btc_strategy_backtest_run_manifest_v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_strategy_backtest_runs")


def write_btc_backtest_run_manifest(
    *,
    repo_root: Path,
    spec: BTCStrategySpec,
    result: Any,
    request: Mapping[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    root = repo_root.resolve()
    diagnostics = result.diagnostics if isinstance(getattr(result, "diagnostics", None), dict) else {}
    unified = getattr(result, "unified", None)
    run_id = str(diagnostics.get("run_id") or getattr(unified, "run_id", "") or f"btc_bt_{uuid.uuid4().hex[:12]}")
    canonical_manifest_path = Path(str(diagnostics.get("manifest_path") or ""))
    canonical_manifest = _read_json(canonical_manifest_path)
    observed_identity = {
        "strategy_id": str(diagnostics.get("strategy_id") or ""),
        "candidate_id": spec.candidate_id,
        "strategy_version": str(diagnostics.get("strategy_version") or ""),
        "params_hash": spec.params_hash,
    }
    identity_blockers = compare_strategy_identities(spec.identity(), observed_identity)
    ledger_evidence = getattr(unified, "evidence", {}) if isinstance(getattr(unified, "evidence", None), dict) else {}
    pnl = ledger_evidence.get("pnl", {}) if isinstance(ledger_evidence.get("pnl"), dict) else {}
    request_contract = _request_contract(spec=spec, request=request)
    checks = {
        "strategy_identity_matches": not identity_blockers,
        "canonical_manifest_present": bool(canonical_manifest),
        "pnl_derived_from_ledger_fills": diagnostics.get("pnl_source") == "ledger_fills" and pnl.get("source") == "ledger_fills",
        "ledger_equity_consistent": diagnostics.get("ledger_equity_consistent") is True,
        "generic_strategy_cannot_receive_promotion_credit": (
            spec.promotion_credit_eligible or spec.promotion_eligibility == "legacy_diagnostic_no_promotion_credit"
        ),
        **request_contract["checks"],
    }
    blockers = list(identity_blockers)
    blockers.extend(f"btc_strategy_backtest:{name}" for name, passed in checks.items() if not passed)
    promotion_credit_allowed = spec.promotion_credit_eligible and all(checks.values())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete_research_only" if not blockers else "blocked_research_only",
        "decision": (
            "btc_strategy_identity_bound_backtest_complete_research_only_no_auto_paper_no_live"
            if not blockers
            else "btc_strategy_identity_backtest_blocked_fail_closed_no_paper_no_live"
        ),
        "run_id": run_id,
        "strategy_identity": spec.identity(),
        "observed_strategy_identity": observed_identity,
        "params": dict(spec.params),
        "request_identity": {
            "strategy_id": request.get("strategy_id"),
            "candidate_id": request.get("candidate_id"),
            "strategy_version": request.get("strategy_version"),
        },
        "request_data_contract": request_contract,
        "pipeline_contract": [
            "Signal",
            "Forecast",
            "TargetPosition",
            "RiskDecision",
            "OrderIntent",
            "SimulatedFill",
            "Ledger",
        ],
        "canonical_manifest": {
            "path": str(canonical_manifest_path).replace("\\", "/"),
            "sha256": _file_sha256(canonical_manifest_path) if canonical_manifest_path.is_file() else "",
            "manifest_schema_version": canonical_manifest.get("manifest_schema_version"),
            "run_id": canonical_manifest.get("run_id"),
        },
        "ledger_binding": {
            "strategy_identity": spec.identity(),
            "pnl_source": diagnostics.get("pnl_source"),
            "ledger_artifact_path": diagnostics.get("ledger_artifact_path"),
            "ledger_hash": diagnostics.get("ledger_hash"),
            "fills_hash": diagnostics.get("fills_hash"),
            "ledger_final_equity": diagnostics.get("ledger_final_equity"),
            "ledger_total_fees": diagnostics.get("ledger_total_fees"),
            "ledger_equity_consistent": diagnostics.get("ledger_equity_consistent"),
        },
        "checks": checks,
        "promotion_credit_allowed": promotion_credit_allowed,
        "gate": _gate(),
        "blockers": sorted(set(blockers)),
    }
    destination_root = _resolve(root, output_root)
    run_dir = destination_root / run_id
    manifest_path = run_dir / "manifest.json"
    latest_manifest_path = destination_root / "latest_manifest.json"
    manifest["outputs"] = {
        "manifest": _portable_path(manifest_path, root),
        "latest_manifest": _portable_path(latest_manifest_path, root),
        "latest_pointer": _portable_path(destination_root / "latest_pointer.json", root),
    }
    _write_json_atomic(manifest_path, manifest)
    _write_json_atomic(latest_manifest_path, manifest)
    pointer = {
        "schema_version": "btc_strategy_backtest_latest_pointer_v1",
        "generated_at_utc": manifest["generated_at_utc"],
        "run_id": run_id,
        "manifest_path": _portable_path(manifest_path, root),
        "manifest_sha256": _file_sha256(manifest_path),
        "strategy_identity": spec.identity(),
        "promotion_credit_allowed": promotion_credit_allowed,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    _write_json_atomic(destination_root / "latest_pointer.json", pointer)
    return manifest


def load_latest_btc_backtest_manifest(
    repo_root: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    root = repo_root.resolve()
    pointer = _read_json(_resolve(root, output_root) / "latest_pointer.json")
    path = _safe_path(root, str(pointer.get("manifest_path") or ""))
    if path is None or not path.is_file():
        return {}
    if _file_sha256(path) != str(pointer.get("manifest_sha256") or ""):
        return {}
    return _read_json(path)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _safe_path(root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _portable_path(path: Path, root: Path) -> str:
    try:
        path = path.resolve().relative_to(root)
    except ValueError:
        pass
    return str(path).replace("\\", "/")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _request_contract(*, spec: BTCStrategySpec, request: Mapping[str, Any]) -> dict[str, Any]:
    if spec.strategy_id != STABLE_STRATEGY_LINE:
        return {
            "policy": "not_applicable_non_stable_strategy_line",
            "checks": {},
        }
    observed = {
        "source": str(request.get("source") or ""),
        "symbol": str(request.get("symbol") or "").upper(),
        "interval": str(request.get("interval") or ""),
        "leverage": float(request.get("leverage", 0.0) or 0.0),
        "candidate_id": str(request.get("candidate_id") or ""),
        "strategy_version": str(request.get("strategy_version") or ""),
    }
    checks = {
        "canonical_request_source_is_sqlite": observed["source"] == "sqlite",
        "canonical_request_symbol_is_btcusdt": observed["symbol"] == "BTCUSDT",
        "canonical_request_interval_is_completed_1h": observed["interval"] == "1h",
        "canonical_request_leverage_is_1x": observed["leverage"] == 1.0,
        "canonical_request_candidate_explicit_and_matches": observed["candidate_id"] == spec.candidate_id,
        "canonical_request_version_explicit_and_matches": observed["strategy_version"] == spec.strategy_version,
    }
    return {
        "policy": "binance_spot_completed_1h_signal_okx_swap_theoretical_execution_research_only",
        "observed": observed,
        "checks": checks,
    }
