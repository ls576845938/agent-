#!/usr/bin/env python3
"""Build a read-only BTC manual metadata capture readiness report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.btc_perpetual_provider_config import (
        default_provider_root,
        selected_btc_perpetual_bundle_dir,
        selected_btc_perpetual_provider,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import (
        default_provider_root,
        selected_btc_perpetual_bundle_dir,
        selected_btc_perpetual_provider,
    )


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
DEFAULT_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_CAPTURE_ATTEMPT = Path("artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json")
DEFAULT_OPERATOR_PACKET = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_BUNDLE_DIR = Path(
    "data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1"
)
POST_CAPTURE_IMPORT_COMMAND = (
    "make apply-btc-manual-metadata-import "
    "EXCHANGE_INFO_RAW=exchange_info_raw.json "
    "FUNDING_INFO_RAW=funding_info_raw.json "
    "EXCHANGE_INFO_HTTP_STATUS=exchange_info_http_status.txt "
    "FUNDING_INFO_HTTP_STATUS=funding_info_http_status.txt "
    "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_CAPTURE_TIME>"
)
POST_CAPTURE_VALIDATE_COMMAND = "make validate-btc-public-data-bundle"
POST_CAPTURE_STRICT_VALIDATE_COMMAND = "make validate-btc-public-data-bundle-strict"
POST_CAPTURE_REBUILD_READINESS_COMMAND = "make rebuild-btc-paper-readiness-chain"
PROVIDER_PROFILES: dict[str, dict[str, Any]] = {
    "binance_usdm": {
        "exchange_endpoint": "GET /fapi/v1/exchangeInfo",
        "exchange_source_url": "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "funding_endpoint": "GET /fapi/v1/fundingInfo",
        "funding_source_url": "https://fapi.binance.com/fapi/v1/fundingInfo",
        "exchange": "binance_usdm",
        "symbol": "BTCUSDT",
        "market_type": "usds_m_perpetual",
        "license_note": "Binance public USD-M Futures market data local archive and manual public metadata capture.",
        "empty_funding_response_allowed": True,
        "required_fields": [
            "raw_symbol_info.symbol=BTCUSDT",
            "raw_symbol_info.contractType=PERPETUAL",
            "raw_symbol_info.status=TRADING",
            "PRICE_FILTER.tickSize",
            "LOT_SIZE.stepSize",
            "LOT_SIZE.minQty",
            "MIN_NOTIONAL.notional_or_minNotional",
            "api_key_used=false",
            "private_endpoint_used=false",
            "auth_headers_present=false",
        ],
    },
    "okx_swap": {
        "exchange_endpoint": "GET /api/v5/public/instruments",
        "exchange_source_url": "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
        "funding_endpoint": "GET /api/v5/public/funding-rate",
        "funding_source_url": "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
        "exchange": "okx_swap",
        "symbol": "BTCUSDT",
        "market_type": "usds_m_perpetual",
        "license_note": "OKX public swap market data local archive and manual public metadata capture.",
        "empty_funding_response_allowed": False,
        "required_fields": [
            "raw_symbol_info.instId=BTC-USDT-SWAP",
            "raw_symbol_info.instType=SWAP",
            "raw_symbol_info.state=live",
            "tickSz",
            "lotSz",
            "minSz",
            "ctVal",
            "api_key_used=false",
            "private_endpoint_used=false",
            "auth_headers_present=false",
        ],
    },
}


def build_btc_manual_metadata_capture_readiness_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    provider = _read_json(root / DEFAULT_PROVIDER_VERIFICATION)
    capture_attempt = _read_json(root / DEFAULT_CAPTURE_ATTEMPT)
    provider_name, provider_config = selected_btc_perpetual_provider(root / DEFAULT_CONFIG)
    profile = PROVIDER_PROFILES.get(provider_name, PROVIDER_PROFILES["binance_usdm"])
    configured_bundle_dir = selected_btc_perpetual_bundle_dir(root, root / DEFAULT_CONFIG)
    bundle_dir = configured_bundle_dir or _fallback_bundle_dir(root, provider_name, provider_config)
    relative_bundle_dir = Path(_relpath(bundle_dir, root))
    bundle_id = bundle_dir.name
    exchange_info_path = bundle_dir / "exchange_info.json"
    funding_info_path = bundle_dir / "funding_info.json"
    exchange_verified = bool(provider.get("exchange_info_verified", False))
    funding_verified = bool(provider.get("funding_info_verified", False))
    exchange_blockers = _filter_blockers(provider, "exchange_info")
    funding_blockers = _filter_blockers(provider, "funding_info")
    blockers = _dedupe([*exchange_blockers, *funding_blockers])
    return {
        "schema_version": "btc_manual_metadata_capture_readiness_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "bundle_dir": _relpath(bundle_dir, root),
        "provider_verification_report": _relpath(root / DEFAULT_PROVIDER_VERIFICATION, root)
        if (root / DEFAULT_PROVIDER_VERIFICATION).exists()
        else None,
        "latest_public_metadata_capture_attempt": _relpath(root / DEFAULT_CAPTURE_ATTEMPT, root)
        if (root / DEFAULT_CAPTURE_ATTEMPT).exists()
        else None,
        "manual_capture_operator_packet": _relpath(root / DEFAULT_OPERATOR_PACKET, root),
        "last_public_metadata_capture_status": _capture_attempt_status(capture_attempt),
        "status": "ready_for_manual_capture" if blockers else "metadata_verified",
        "perpetual_evidence_ready": bool(provider.get("perpetual_evidence_ready", False)),
        "exchange_info": {
            "verified": exchange_verified,
            "manual_capture_required": not exchange_verified,
            "current_overlay_path": _relpath(exchange_info_path, root) if exchange_info_path.exists() else None,
                "allowed_endpoint": str(profile["exchange_endpoint"]),
                "source_url": str(profile["exchange_source_url"]),
                "wrapper_command": "atomic_importer_only: use post_capture_commands[0]",
                "validate_command": (
                    "python3 scripts/build_btc_exchange_info_overlay.py "
                    f"--bundle-dir {relative_bundle_dir} --validate-only"
                ),
                "required_fields": list(profile["required_fields"]),
                "forbidden_endpoint_families": _forbidden_endpoint_families(),
                "blockers": exchange_blockers,
            },
        "funding_info": {
            "verified": funding_verified,
            "manual_capture_required": not funding_verified,
            "endpoint_response_available": bool(provider.get("funding_info_endpoint_response_available", False)),
            "source_method": provider.get("funding_info_source_method"),
            "current_overlay_path": _relpath(funding_info_path, root) if funding_info_path.exists() else None,
                "allowed_endpoint": str(profile["funding_endpoint"]),
                "source_url": str(profile["funding_source_url"]),
                "wrapper_command": "atomic_importer_only: use post_capture_commands[0]",
                "validate_command": (
                    "python3 scripts/build_btc_funding_info_overlay.py "
                    f"--bundle-dir {relative_bundle_dir} --validate-only"
                ),
                "empty_response_allowed": bool(profile["empty_funding_response_allowed"]),
                "funding_interval_hours": provider.get("funding_interval_hours"),
                "funding_interval_source": provider.get("funding_interval_source"),
                "funding_interval_inference_confidence": provider.get("funding_interval_inference_confidence"),
                "blockers": funding_blockers,
            },
        "post_capture_commands": _post_capture_commands(
            bundle_dir=relative_bundle_dir,
            bundle_id=bundle_id,
            provider_name=provider_name,
            profile=profile,
        ),
        "safety": {
            "api_key_required": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "strategy_retest_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "compression_expansion_state": "archived",
        },
        "blockers": blockers,
    }


def write_btc_manual_metadata_capture_readiness_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_manual_metadata_capture_readiness_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_manual_metadata_capture_readiness_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_manual_metadata_capture_readiness_report(payload, Path(args.output_root)))


def _filter_blockers(provider: Mapping[str, Any], prefix: str) -> list[str]:
    return [
        str(item)
        for item in provider.get("blockers", [])
        if str(item).startswith(f"btc_{prefix}") or str(item).startswith(f"btc_perpetual_{prefix}")
    ]


def _post_capture_commands(
    *,
    bundle_dir: Path,
    bundle_id: str,
    provider_name: str,
    profile: Mapping[str, Any],
) -> list[str]:
    return [
        POST_CAPTURE_IMPORT_COMMAND,
        _manifest_command(bundle_dir=bundle_dir, bundle_id=bundle_id, provider_name=provider_name, profile=profile),
        POST_CAPTURE_VALIDATE_COMMAND,
        POST_CAPTURE_STRICT_VALIDATE_COMMAND,
        POST_CAPTURE_REBUILD_READINESS_COMMAND,
    ]


def _forbidden_endpoint_families() -> list[str]:
    return [
        "account",
        "order",
        "trade",
        "position",
        "listenKey",
        "userData",
        "leverage",
        "margin",
        "transfer",
        "broker",
        "income",
        "balance",
        "withdrawal",
    ]


def _fallback_bundle_dir(root: Path, provider_name: str, provider_config: Mapping[str, Any]) -> Path:
    selected_bundle_id = str(provider_config.get("selected_bundle_id", "") or "").strip()
    if selected_bundle_id:
        return root / str(provider_config.get("root", default_provider_root(provider_name))) / "bundles" / selected_bundle_id
    return root / DEFAULT_BUNDLE_DIR


def _manifest_command(
    *,
    bundle_dir: Path,
    bundle_id: str,
    provider_name: str,
    profile: Mapping[str, Any],
) -> str:
    return (
        "python3 scripts/build_btc_perpetual_data_bundle_manifest.py "
        f"--bundle-dir {bundle_dir} "
        f"--bundle-id {bundle_id} "
        "--source-type production --promotion-clean-allowed "
        f"--source-provider {provider_name} "
        f"--exchange {profile['exchange']} "
        f"--symbol {profile['symbol']} "
        f"--market-type {profile['market_type']} "
        f"--license-note \"{profile['license_note']}\""
    )


def _capture_attempt_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    endpoint_results = payload.get("endpoint_results", {}) if isinstance(payload.get("endpoint_results"), Mapping) else {}
    exchange = endpoint_results.get("exchange_info", {}) if isinstance(endpoint_results.get("exchange_info"), Mapping) else {}
    funding = endpoint_results.get("funding_info", {}) if isinstance(endpoint_results.get("funding_info"), Mapping) else {}
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "network_called": bool(payload.get("network_called", False)),
        "exchange_info_capture_status": str(exchange.get("capture_status", "missing") or "missing"),
        "exchange_info_http_status": exchange.get("http_status"),
        "funding_info_capture_status": str(funding.get("capture_status", "missing") or "missing"),
        "funding_info_http_status": funding.get("http_status"),
        "next_required_action": str(payload.get("next_required_action", "manual_capture_from_allowed_network")),
        "blockers": _dedupe([str(item) for item in payload.get("blockers", [])]) if isinstance(payload.get("blockers"), list) else [],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
