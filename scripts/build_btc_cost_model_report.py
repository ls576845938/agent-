#!/usr/bin/env python3
"""Build a fail-closed BTC perpetual cost model contract report.

The report is read-only. It summarizes existing event-ledger artifacts and
marks missing perpetual-specific evidence as blockers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import jsonschema
try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info, exchange_rules_from_status
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info, exchange_rules_from_status


DEFAULT_SOURCE_RUN_DIR = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_cost_model/latest")
DEFAULT_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_FUNDING_LEDGER = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
DEFAULT_FEE_TIER_OVERLAY = Path("artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json")
DEFAULT_FEE_TIER_IMPORT_REPORT = Path("artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
FEE_TIER_SCHEMA = Path("schemas/btc_fee_tier_overlay.schema.json")
FEE_TIER_IMPORT_REPORT_SCHEMA = Path("schemas/btc_fee_tier_overlay_import_report.schema.json")
ALLOWED_FEE_TIER_SOURCES = {
    "manual_public_binance_usdm_fee_schedule",
    "manual_public_okx_swap_fee_schedule",
}
UTC_SECOND_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DIAGNOSTIC_ONLY_WARNINGS = {
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_agg_trades_missing",
    "btc_liquidation_snapshot_missing_diagnostic_only",
    "btc_liquidation_snapshots_missing_diagnostic_only",
    "diagnostic_only_not_gate_evidence",
}


def build_btc_cost_model_report(
    *,
    repo_root: Path | None = None,
    source_run_dir: Path | None = None,
    fee_tier_overlay_path: Path | None = None,
    fee_tier_import_report_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = _resolve(root, source_run_dir or DEFAULT_SOURCE_RUN_DIR)
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    canonical = _read_json(run_dir / "canonical_backtest_report.json")
    manifest = _read_json(run_dir / "manifests/run_btc_compression_expansion_breakout_v1_base.json")
    provider = _read_json(root / DEFAULT_PROVIDER_VERIFICATION)
    funding_report = _read_json(root / DEFAULT_FUNDING_LEDGER)
    exchange_info_status = evaluate_exchange_info(_selected_bundle_file(root, "exchange_info.json"))
    exchange_rules = exchange_rules_from_status(exchange_info_status)
    fee_tier = _evaluate_fee_tier_overlay(
        _resolve(root, fee_tier_overlay_path or DEFAULT_FEE_TIER_OVERLAY),
        schema_path=_resolve(root, FEE_TIER_SCHEMA),
        import_report_path=_resolve(root, fee_tier_import_report_path or DEFAULT_FEE_TIER_IMPORT_REPORT),
        import_report_schema_path=_resolve(root, FEE_TIER_IMPORT_REPORT_SCHEMA),
    )
    cost_model = _mapping(manifest.get("cost_model"))
    config = _mapping(manifest.get("config"))
    metrics = _mapping(canonical.get("metrics"))
    manifest_slippage_model = _mapping(manifest.get("slippage_model"))
    research_commission_rate = _first_not_none(
        _float_or_none(config.get("commission_rate")),
        _float_or_none(cost_model.get("commission_rate")),
    )
    research_taker_fee_bps = round(research_commission_rate * 10_000, 6) if research_commission_rate is not None else None
    slippage_bps = _first_not_none(
        _float_or_none(cost_model.get("slippage_bps")),
        _float_or_none(config.get("slippage_bps")),
        _float_or_none(manifest_slippage_model.get("slippage_bps")),
        _float_or_none(manifest_slippage_model.get("bps")),
    )
    slippage_blockers = [] if slippage_bps is not None else ["btc_slippage_bps_missing"]
    blockers = _build_blockers(
        canonical=canonical,
        manifest=manifest,
        provider=provider,
        funding_report=funding_report,
        exchange_rules=exchange_rules,
        fee_tier=fee_tier,
        slippage_bps=slippage_bps,
    )
    diagnostic_warnings = _diagnostic_warnings(
        [
            *([] if provider.get("open_interest_verified", False) else ["btc_open_interest_history_not_verified_diagnostic_partial"]),
            *_list_of_strings(provider.get("diagnostic_warnings")),
            *_diagnostic_only_items(_list_of_strings(provider.get("blockers"))),
            *_diagnostic_only_items(_list_of_strings(funding_report.get("blockers"))),
        ]
    )
    return {
        "schema_version": "btc_cost_model_contract_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "source_run_dir": _relpath(run_dir, root),
        "source_canonical_backtest_report": _relpath(run_dir / "canonical_backtest_report.json", root)
        if (run_dir / "canonical_backtest_report.json").exists()
        else None,
        "status": "fail" if blockers else "pass",
        "funding_model": {
            "funding_rate_available": bool(provider.get("funding_rate_verified", False)),
            "funding_info_available": bool(provider.get("funding_info_verified", False)),
            "funding_interval_hours": funding_report.get("funding_interval_hours"),
            "funding_interval_source": funding_report.get("funding_interval_source"),
            "funding_interval_inference_confidence": provider.get("funding_interval_inference_confidence"),
            "funding_rate_sample_start": None,
            "funding_rate_sample_end": None,
            "funding_payment_in_ledger": bool(funding_report.get("funding_payment_in_ledger", False)),
            "funding_ledger_report": _relpath(root / DEFAULT_FUNDING_LEDGER, root)
            if (root / DEFAULT_FUNDING_LEDGER).exists()
            else None,
            "funding_blockers": _merge(
                _list_of_strings(funding_report.get("blockers")),
                [] if provider.get("funding_rate_verified", False) else ["btc_funding_rate_missing"],
                [] if provider.get("funding_info_verified", False) else ["btc_funding_info_missing"],
                [] if funding_report.get("funding_payment_in_ledger", False) else ["btc_funding_payment_not_in_ledger"],
            ),
        },
        "fee_model": {
            "maker_fee_bps": fee_tier["maker_fee_bps"] if fee_tier["verified"] else None,
            "taker_fee_bps": fee_tier["taker_fee_bps"] if fee_tier["verified"] else research_taker_fee_bps,
            "fee_source": fee_tier["source"]
            if fee_tier["verified"]
            else "event_ledger_percent_commission_research_config"
            if cost_model
            else None,
            "fee_in_ledger": bool(cost_model.get("realized_commission", 0.0) or metrics.get("fill_count", 0)),
            "fee_tier_verified": bool(fee_tier["verified"]),
            "fee_tier_overlay": _relpath(fee_tier["path"], root) if fee_tier["path"] else None,
            "fee_tier_overlay_sha256": fee_tier["overlay_payload_sha256"],
            "fee_tier_import_report": _relpath(fee_tier["import_report_path"], root)
            if fee_tier["import_report_path"]
            else None,
            "fee_tier_import_report_verified": bool(fee_tier["import_report_verified"]),
            "fee_tier_source": fee_tier["source"],
            "fee_tier_source_url_or_doc": fee_tier["source_url_or_doc"],
            "fee_tier_captured_at": fee_tier["captured_at"],
            "fee_blockers": fee_tier["blockers"],
        },
        "exchange_rules": {
            "exchange_info_available": bool(provider.get("exchange_info_verified", False)),
            "exchange_rules_available": bool(provider.get("exchange_info_verified", False) and exchange_rules["rules_available"]),
            "tick_size": exchange_rules["tick_size"],
            "step_size": exchange_rules["step_size"],
            "min_qty": exchange_rules["min_qty"],
            "min_notional": exchange_rules["min_notional"],
            "price_precision": exchange_rules["price_precision"],
            "quantity_precision": exchange_rules["quantity_precision"],
            "rules_source": _relpath(root / DEFAULT_PROVIDER_VERIFICATION, root)
            if provider.get("exchange_info_verified", False) and exchange_rules["rules_available"]
            else None,
            "exchange_info_source_method": provider.get("exchange_info_source_method"),
            "historical_rule_lineage_available": bool(provider.get("exchange_info_historical_rule_lineage_available", False)),
            "exchange_rules_blockers": []
            if provider.get("exchange_info_verified", False) and exchange_rules["rules_available"]
            else exchange_rules.get("blockers", ["btc_exchange_info_missing"]),
        },
        "mark_price_model": {
            "mark_price_available": bool(provider.get("mark_price_klines_verified", False)),
            "mark_price_klines_available": bool(provider.get("mark_price_klines_verified", False)),
            "premium_index_available": bool(provider.get("premium_index_klines_verified", False)),
            "premium_index_klines_available": bool(provider.get("premium_index_klines_verified", False)),
            "mark_price_current_available": False,
            "mark_price_alignment_pass": bool(provider.get("mark_price_klines_verified", False)),
            "mark_price_used_for_liquidation_risk": False,
            "last_price_vs_mark_price_diagnostic_available": False,
            "mark_price_blockers": _merge(
                [] if provider.get("mark_price_klines_verified", False) else ["btc_mark_price_missing"],
                [] if provider.get("premium_index_klines_verified", False) else ["btc_premium_index_missing"],
            ),
        },
        "slippage_model": {
            "slippage_model_name": "bps_slippage_research_config" if cost_model else None,
            "slippage_bps": slippage_bps,
            "slippage_in_ledger": bool(cost_model.get("realized_slippage_cost", 0.0) or metrics.get("fill_count", 0)),
            "slippage_stress_levels": ["base", "fees_2x", "slippage_2x", "costs_2x"],
            "slippage_blockers": slippage_blockers,
        },
        "liquidation_data": {
            "liquidation_snapshot_available": False,
            "liquidation_snapshot_status": "diagnostic_missing_not_complete_history",
            "complete_liquidation_history_available": False,
        },
        "candidate_pass_allowed": False,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
        "diagnostic_warnings": diagnostic_warnings,
        "blockers": blockers,
    }


def write_btc_cost_model_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_cost_model_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-dir", default=str(DEFAULT_SOURCE_RUN_DIR))
    parser.add_argument("--fee-tier-overlay", default=str(DEFAULT_FEE_TIER_OVERLAY))
    parser.add_argument("--fee-tier-import-report", default=str(DEFAULT_FEE_TIER_IMPORT_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_cost_model_report(
        repo_root=Path(args.repo_root),
        source_run_dir=Path(args.source_run_dir),
        fee_tier_overlay_path=Path(args.fee_tier_overlay),
        fee_tier_import_report_path=Path(args.fee_tier_import_report),
        generated_at=args.generated_at or None,
    )
    print(write_btc_cost_model_report(payload, Path(args.output_root)))


def _build_blockers(
    *,
    canonical: Mapping[str, Any],
    manifest: Mapping[str, Any],
    provider: Mapping[str, Any],
    funding_report: Mapping[str, Any],
    exchange_rules: Mapping[str, Any],
    fee_tier: Mapping[str, Any],
    slippage_bps: float | None,
) -> list[str]:
    blockers = []
    if not canonical:
        blockers.append("btc_canonical_backtest_report_missing")
    if not manifest:
        blockers.append("btc_event_ledger_manifest_missing")
    if not provider.get("funding_rate_verified", False):
        blockers.append("btc_funding_rate_missing")
    if not provider.get("funding_info_verified", False):
        blockers.append("btc_funding_info_missing")
    if not funding_report.get("funding_payment_in_ledger", False):
        blockers.append("btc_funding_payment_not_in_ledger")
    if not provider.get("mark_price_klines_verified", False):
        blockers.append("btc_mark_price_missing")
    if not provider.get("premium_index_klines_verified", False):
        blockers.append("btc_premium_index_missing")
    if not provider.get("exchange_info_verified", False):
        blockers.append("btc_exchange_info_missing")
    elif not exchange_rules.get("rules_available", False):
        blockers.append("btc_exchange_rules_missing")
    blockers.extend(_list_of_strings(fee_tier.get("blockers")))
    if slippage_bps is None:
        blockers.append("btc_slippage_bps_missing")
    blockers.extend(_hard_blockers(_list_of_strings(provider.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(funding_report.get("blockers"))))
    return _dedupe(blockers)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluate_fee_tier_overlay(
    path: Path,
    *,
    schema_path: Path | None = None,
    import_report_path: Path | None = None,
    import_report_schema_path: Path | None = None,
) -> dict[str, Any]:
    if not path.exists():
        return _fee_tier_status(path=None, blockers=["btc_maker_taker_fee_tier_missing"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _fee_tier_status(path=path, blockers=["btc_fee_tier_overlay_invalid_json"])
    if not isinstance(payload, Mapping):
        return _fee_tier_status(path=path, blockers=["btc_fee_tier_overlay_not_object"])

    blockers: list[str] = []
    schema = _read_json(schema_path or FEE_TIER_SCHEMA)
    if schema:
        try:
            jsonschema.validate(payload, schema)
        except jsonschema.ValidationError:
            blockers.append("btc_fee_tier_overlay_schema_invalid")
    else:
        blockers.append("btc_fee_tier_overlay_schema_file_missing")

    maker_fee_bps = payload.get("maker_fee_bps")
    taker_fee_bps = payload.get("taker_fee_bps")
    if payload.get("schema_version") != "btc_fee_tier_overlay_v1":
        blockers.append("btc_fee_tier_overlay_schema_version_invalid")
    if str(payload.get("symbol", "")).upper() != "BTCUSDT":
        blockers.append("btc_fee_tier_overlay_symbol_invalid")
    if str(payload.get("market_type", "")) != "usds_m_perpetual":
        blockers.append("btc_fee_tier_overlay_market_type_invalid")
    if not isinstance(maker_fee_bps, (int, float)) or float(maker_fee_bps) < 0:
        blockers.append("btc_maker_fee_bps_missing_or_invalid")
    if not isinstance(taker_fee_bps, (int, float)) or float(taker_fee_bps) < 0:
        blockers.append("btc_taker_fee_bps_missing_or_invalid")
    source = str(payload.get("source", "")).strip()
    source_url_or_doc = str(payload.get("source_url_or_doc", "")).strip()
    captured_at = str(payload.get("captured_at", "")).strip()
    if not source:
        blockers.append("btc_fee_tier_source_missing")
    elif source not in ALLOWED_FEE_TIER_SOURCES:
        blockers.append("btc_fee_tier_source_not_canonical")
    if not source_url_or_doc:
        blockers.append("btc_fee_tier_source_url_or_doc_missing")
    if not captured_at:
        blockers.append("btc_fee_tier_captured_at_missing")
    elif not UTC_SECOND_TIMESTAMP_RE.match(captured_at):
        blockers.append("btc_fee_tier_captured_at_not_utc")
    if payload.get("api_key_used") is not False:
        blockers.append("btc_fee_tier_api_key_usage_not_explicitly_false")
    if payload.get("private_endpoint_used") is not False:
        blockers.append("btc_fee_tier_private_endpoint_usage_not_explicitly_false")
    if payload.get("auth_headers_used") is not False:
        blockers.append("btc_fee_tier_auth_headers_not_explicitly_false")
    overlay_hash = _stable_json_sha256(payload)
    import_report = (
        _evaluate_fee_tier_import_report(
            import_report_path,
            schema_path=import_report_schema_path,
            overlay_path=path,
            overlay_payload=payload,
            overlay_hash=overlay_hash,
        )
        if not blockers
        else _fee_tier_import_report_status(import_report_path, blockers=[])
    )
    blockers.extend(_list_of_strings(import_report.get("blockers")))

    return _fee_tier_status(
        path=path,
        verified=not blockers,
        maker_fee_bps=float(maker_fee_bps) if isinstance(maker_fee_bps, (int, float)) else None,
        taker_fee_bps=float(taker_fee_bps) if isinstance(taker_fee_bps, (int, float)) else None,
        source=source or None,
        source_url_or_doc=source_url_or_doc or None,
        captured_at=captured_at or None,
        overlay_payload_sha256=overlay_hash,
        import_report_path=import_report.get("path"),
        import_report_verified=bool(import_report.get("verified", False)),
        blockers=blockers,
    )


def _evaluate_fee_tier_import_report(
    path: Path | None,
    *,
    schema_path: Path | None,
    overlay_path: Path,
    overlay_payload: Mapping[str, Any],
    overlay_hash: str,
) -> dict[str, Any]:
    if path is None or not path.exists():
        return _fee_tier_import_report_status(
            path,
            blockers=["btc_fee_tier_overlay_import_report_missing"],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _fee_tier_import_report_status(
            path,
            blockers=["btc_fee_tier_overlay_import_report_invalid_json"],
        )
    if not isinstance(payload, Mapping):
        return _fee_tier_import_report_status(
            path,
            blockers=["btc_fee_tier_overlay_import_report_not_object"],
        )

    blockers: list[str] = []
    schema = _read_json(schema_path) if schema_path is not None else {}
    if schema:
        try:
            jsonschema.validate(payload, schema)
        except jsonschema.ValidationError:
            blockers.append("btc_fee_tier_overlay_import_report_schema_invalid")
    else:
        blockers.append("btc_fee_tier_overlay_import_report_schema_file_missing")
    if payload.get("status") != "verified":
        blockers.append("btc_fee_tier_overlay_import_report_not_verified")
    if payload.get("dry_run") is not False:
        blockers.append("btc_fee_tier_overlay_import_report_is_dry_run")
    if payload.get("writes_performed") is not True:
        blockers.append("btc_fee_tier_overlay_import_report_no_write")
    if payload.get("fee_tier_verified") is not True:
        blockers.append("btc_fee_tier_overlay_import_report_fee_not_verified")
    report_output = str(payload.get("overlay_output", "") or "")
    if not report_output or Path(report_output).resolve(strict=False) != overlay_path.resolve(strict=False):
        blockers.append("btc_fee_tier_overlay_import_report_output_mismatch")
    if not _number_equal(payload.get("maker_fee_bps"), overlay_payload.get("maker_fee_bps")):
        blockers.append("btc_fee_tier_overlay_import_report_maker_fee_mismatch")
    if not _number_equal(payload.get("taker_fee_bps"), overlay_payload.get("taker_fee_bps")):
        blockers.append("btc_fee_tier_overlay_import_report_taker_fee_mismatch")
    if str(payload.get("source", "") or "") != str(overlay_payload.get("source", "") or ""):
        blockers.append("btc_fee_tier_overlay_import_report_source_mismatch")
    if str(payload.get("source_url_or_doc", "") or "") != str(overlay_payload.get("source_url_or_doc", "") or ""):
        blockers.append("btc_fee_tier_overlay_import_report_source_url_mismatch")
    if str(payload.get("captured_at", "") or "") != str(overlay_payload.get("captured_at", "") or ""):
        blockers.append("btc_fee_tier_overlay_import_report_captured_at_mismatch")
    if str(payload.get("overlay_payload_sha256", "") or "") != overlay_hash:
        blockers.append("btc_fee_tier_overlay_import_report_hash_mismatch")
    return _fee_tier_import_report_status(path, verified=not blockers, blockers=blockers)


def _fee_tier_import_report_status(
    path: Path | None,
    *,
    verified: bool = False,
    blockers: list[str],
) -> dict[str, Any]:
    return {"path": path, "verified": verified, "blockers": _dedupe(blockers)}


def _fee_tier_status(
    *,
    path: Path | None,
    verified: bool = False,
    maker_fee_bps: float | None = None,
    taker_fee_bps: float | None = None,
    source: str | None = None,
    source_url_or_doc: str | None = None,
    captured_at: str | None = None,
    overlay_payload_sha256: str | None = None,
    import_report_path: Path | None = None,
    import_report_verified: bool = False,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "verified": verified,
        "maker_fee_bps": maker_fee_bps,
        "taker_fee_bps": taker_fee_bps,
        "source": source,
        "source_url_or_doc": source_url_or_doc,
        "captured_at": captured_at,
        "overlay_payload_sha256": overlay_payload_sha256,
        "import_report_path": import_report_path,
        "import_report_verified": import_report_verified,
        "blockers": blockers or [],
    }


def _selected_bundle_file(root: Path, filename: str) -> Path | None:
    config = root / DEFAULT_CONFIG
    bundle_dir = selected_btc_perpetual_bundle_dir(root, config)
    if bundle_dir is None:
        return None
    path = bundle_dir / filename
    return path if path.exists() else None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


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


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _merge(*groups: object) -> list[str]:
    merged: list[str] = []
    for group in groups:
        if isinstance(group, list):
            merged.extend(str(item) for item in group if str(item))
    return _dedupe(merged)


def _diagnostic_only_items(values: list[str]) -> list[str]:
    return [value for value in _list_of_strings(values) if value in DIAGNOSTIC_ONLY_WARNINGS]


def _diagnostic_warnings(values: list[str]) -> list[str]:
    return _dedupe(_diagnostic_only_items(values))


def _hard_blockers(values: list[str]) -> list[str]:
    return _dedupe([value for value in _list_of_strings(values) if value not in DIAGNOSTIC_ONLY_WARNINGS])


def _stable_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number_equal(left: object, right: object) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _first_not_none(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
