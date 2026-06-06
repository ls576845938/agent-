#!/usr/bin/env python3
"""Atomically import manually captured BTC public metadata overlays."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import yaml

try:
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info, evaluate_funding_info
    from scripts.build_btc_exchange_info_overlay import build_exchange_info_overlay
    from scripts.build_btc_funding_info_overlay import read_bundle_manifest
    from quant_crypto.data.binance_usdm_metadata import build_funding_info_endpoint_overlay
    from scripts.build_btc_perpetual_data_bundle_manifest import build_btc_perpetual_data_bundle_manifest
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info, evaluate_funding_info
    from scripts.build_btc_exchange_info_overlay import build_exchange_info_overlay
    from scripts.build_btc_funding_info_overlay import read_bundle_manifest
    from quant_crypto.data.binance_usdm_metadata import build_funding_info_endpoint_overlay
    from scripts.build_btc_perpetual_data_bundle_manifest import build_btc_perpetual_data_bundle_manifest


DEFAULT_BUNDLE_DIR = Path(
    "data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1"
)
DEFAULT_BUNDLE_ID = "btc_usdm_binance_btcusdt_20240101_20260512_v1"
DEFAULT_LICENSE_NOTE = "Binance public USD-M Futures market data local archive and manual public metadata capture."
DEFAULT_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
EXCHANGE_INFO_SCHEMA = Path("schemas/btc_exchange_info_overlay.schema.json")
FUNDING_INFO_SCHEMA = Path("schemas/btc_funding_info_overlay.schema.json")
EXCHANGE_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingInfo"
MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER = ".btc_manual_metadata_import_in_progress.json"


def import_manual_metadata_capture(
    *,
    bundle_dir: Path,
    bundle_id: str,
    exchange_info_raw: Path,
    funding_info_raw: Path,
    exchange_info_http_status: Path | None = None,
    funding_info_http_status: Path | None = None,
    captured_at: str | None = None,
    operator_note: str,
    license_note: str = DEFAULT_LICENSE_NOTE,
    dry_run: bool = False,
    selected_bundle_config: Path | None = None,
    require_http_status_evidence: bool = False,
) -> dict[str, Any]:
    generated = _utc_z_now()
    raw_input_files = {
        "exchange_info_raw": _raw_file_evidence(exchange_info_raw, http_status_path=exchange_info_http_status),
        "funding_info_raw": _raw_file_evidence(funding_info_raw, http_status_path=funding_info_http_status),
    }
    selected_bundle_blockers = (
        _selected_bundle_blockers(bundle_dir=bundle_dir, bundle_id=bundle_id, config=selected_bundle_config)
        if selected_bundle_config is not None
        else []
    )
    if selected_bundle_blockers:
        return _failure_many(
            selected_bundle_blockers,
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=None,
        )
    raw_location_blockers = _raw_location_blockers(
        bundle_dir=bundle_dir,
        exchange_info_raw=exchange_info_raw,
        funding_info_raw=funding_info_raw,
    )
    if raw_location_blockers:
        return _failure_many(
            raw_location_blockers,
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=None,
        )
    http_status_blockers = _http_status_blockers(raw_input_files) if require_http_status_evidence else []
    if http_status_blockers:
        return _failure_many(
            http_status_blockers,
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=None,
        )
    if not _non_empty_text(operator_note):
        return _failure(
            "btc_manual_metadata_operator_note_missing",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=None,
        )
    try:
        captured = _captured_at_or_now(captured_at)
    except ValueError:
        return _failure(
            "btc_manual_metadata_captured_at_not_utc_iso8601",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=None,
        )
    if _captured_at_is_after_generated_at(captured, generated):
        return _failure(
            "btc_manual_metadata_captured_at_in_future",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=None,
        )
    try:
        exchange_raw = _read_json(exchange_info_raw)
    except FileNotFoundError:
        return _failure(
            "exchange_info_raw_missing",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=captured,
        )
    except (json.JSONDecodeError, ValueError):
        return _failure(
            "exchange_info_raw_invalid_json",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=captured,
        )
    try:
        funding_raw = _read_json(funding_info_raw)
    except FileNotFoundError:
        return _failure(
            "funding_info_raw_missing",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=captured,
        )
    except (json.JSONDecodeError, ValueError):
        return _failure(
            "funding_info_raw_invalid_json",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=captured,
        )
    exchange_symbol = _extract_btcusdt_symbol_info(exchange_raw)
    if not exchange_symbol:
        return _failure(
            "exchange_info_raw_missing_btcusdt",
            generated=generated,
            dry_run=dry_run,
            raw_input_files=raw_input_files,
            captured_at=captured,
        )
    exchange_overlay = build_exchange_info_overlay(
        source_payload=exchange_symbol,
        source_method="manual_offline_capture",
        source_url_or_doc=EXCHANGE_URL,
        operator_note=operator_note,
        captured_at=captured,
    )
    funding_overlay = build_funding_info_endpoint_overlay(
        bundle_dir=bundle_dir,
        raw_response=funding_raw,
        source_method="manual_offline_capture",
        source_url_or_doc=FUNDING_URL,
        captured_at=captured,
        operator_note=operator_note,
    )
    with tempfile.TemporaryDirectory(prefix="btc_manual_metadata_import_") as temp_name:
        temp_dir = Path(temp_name)
        _stage_supporting_files(bundle_dir, temp_dir)
        exchange_path = temp_dir / "exchange_info.json"
        funding_path = temp_dir / "funding_info.json"
        _write_json_atomic(exchange_overlay, exchange_path)
        _write_json_atomic(funding_overlay, funding_path)
        exchange_output_sha256 = _sha256(exchange_path)
        funding_output_sha256 = _sha256(funding_path)
        exchange_status = evaluate_exchange_info(exchange_path)
        funding_status = evaluate_funding_info(temp_dir, read_bundle_manifest(temp_dir))
        schema_blockers = _overlay_schema_blockers(exchange_overlay, funding_overlay)
        blockers = _dedupe(
            [
                *_list_of_strings(exchange_status.get("blockers")),
                *_list_of_strings(funding_status.get("blockers")),
                *_list_of_strings(funding_overlay.get("blockers")),
                *schema_blockers,
            ]
        )
        verified = bool(exchange_status.get("exchange_info_verified") and funding_status.get("funding_info_verified") and not blockers)
        if not verified:
            return {
                "schema_version": "btc_manual_metadata_import_report_v1",
                "status": "rejected",
                "generated_at": generated,
                "dry_run": bool(dry_run),
                "captured_at": captured,
                "writes_performed": False,
                "exchange_info_verified": bool(exchange_status.get("exchange_info_verified", False)),
                "funding_info_verified": bool(funding_status.get("funding_info_verified", False)),
                "raw_input_files": raw_input_files,
                "blockers": blockers,
            }
        manifest = build_btc_perpetual_data_bundle_manifest(
            bundle_dir=temp_dir,
            bundle_id=bundle_id,
            source_type="production",
            promotion_clean_allowed=True,
            license_note=license_note,
        )
        manifest_blockers = _fatal_manifest_blockers(manifest.get("blockers"))
        if manifest_blockers:
            return {
                "schema_version": "btc_manual_metadata_import_report_v1",
                "status": "rejected",
                "generated_at": generated,
                "dry_run": bool(dry_run),
                "captured_at": captured,
                "writes_performed": False,
                "exchange_info_verified": True,
                "funding_info_verified": True,
                "raw_input_files": raw_input_files,
                "blockers": manifest_blockers,
            }
        if not dry_run:
            bundle_dir.mkdir(parents=True, exist_ok=True)
            marker = bundle_dir / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
            _write_json_atomic(
                {
                    "schema_version": "btc_manual_metadata_import_in_progress_v1",
                    "generated_at": generated,
                    "bundle_id": bundle_id,
                    "bundle_dir": str(bundle_dir),
                    "captured_at": captured,
                    "raw_input_files": raw_input_files,
                    "target_files": [
                        str(bundle_dir / "exchange_info.json"),
                        str(bundle_dir / "funding_info.json"),
                        str(bundle_dir / "btc_perpetual_bundle_manifest.json"),
                    ],
                },
                marker,
            )
            _write_json_atomic(exchange_overlay, bundle_dir / "exchange_info.json")
            _write_json_atomic(funding_overlay, bundle_dir / "funding_info.json")
            _write_json_atomic(
                build_btc_perpetual_data_bundle_manifest(
                    bundle_dir=bundle_dir,
                    bundle_id=bundle_id,
                    source_type="production",
                    promotion_clean_allowed=True,
                    license_note=license_note,
                ),
                bundle_dir / "btc_perpetual_bundle_manifest.json",
            )
        return {
            "schema_version": "btc_manual_metadata_import_report_v1",
            "status": "verified",
            "generated_at": generated,
            "dry_run": bool(dry_run),
            "captured_at": captured,
            "writes_performed": not dry_run,
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "raw_input_files": raw_input_files,
            "exchange_info_output_path": str(bundle_dir / "exchange_info.json"),
            "exchange_info_output_sha256": exchange_output_sha256,
            "funding_info_output_path": str(bundle_dir / "funding_info.json"),
            "funding_info_output_sha256": funding_output_sha256,
            "bundle_dir": str(bundle_dir),
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        }


def write_manual_metadata_import_report(payload: Mapping[str, Any], output: Path) -> str:
    _write_json_atomic(payload, output)
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--exchange-info-raw", required=True)
    parser.add_argument("--funding-info-raw", required=True)
    parser.add_argument("--exchange-info-http-status", required=True)
    parser.add_argument("--funding-info-http-status", required=True)
    parser.add_argument("--captured-at", default="")
    parser.add_argument("--operator-note", required=True)
    parser.add_argument("--license-note", default=DEFAULT_LICENSE_NOTE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-output", default="")
    parser.add_argument("--selected-bundle-config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    if not args.dry_run and not args.report_output:
        parser.error("--report-output is required for write-capable manual metadata import")
    result = import_manual_metadata_capture(
        bundle_dir=Path(args.bundle_dir),
        bundle_id=args.bundle_id,
        exchange_info_raw=Path(args.exchange_info_raw),
        funding_info_raw=Path(args.funding_info_raw),
        exchange_info_http_status=Path(args.exchange_info_http_status),
        funding_info_http_status=Path(args.funding_info_http_status),
        captured_at=args.captured_at or None,
        operator_note=args.operator_note,
        license_note=args.license_note,
        dry_run=bool(args.dry_run),
        selected_bundle_config=Path(args.selected_bundle_config) if args.selected_bundle_config else None,
        require_http_status_evidence=True,
    )
    if args.report_output:
        write_manual_metadata_import_report(result, Path(args.report_output))
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "verified":
        raise SystemExit(1)


def _stage_supporting_files(bundle_dir: Path, temp_dir: Path) -> None:
    for filename in (
        "btc_perpetual_bundle_manifest.json",
        "funding_rate.csv",
        "klines_1h.csv",
        "klines_4h.csv",
        "klines_1d.csv",
        "mark_price_klines_1h.csv",
        "premium_index_klines_1h.csv",
    ):
        source = bundle_dir / filename
        if source.exists():
            shutil.copy2(source, temp_dir / filename)


def _failure(
    reason: str,
    *,
    generated: str,
    dry_run: bool,
    raw_input_files: Mapping[str, Any] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "btc_manual_metadata_import_report_v1",
        "status": "rejected",
        "generated_at": generated,
        "dry_run": bool(dry_run),
        "captured_at": captured_at,
        "writes_performed": False,
        "exchange_info_verified": False,
        "funding_info_verified": False,
        "raw_input_files": dict(raw_input_files or {}),
        "blockers": [reason],
    }


def _failure_many(
    reasons: list[str],
    *,
    generated: str,
    dry_run: bool,
    raw_input_files: Mapping[str, Any] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    payload = _failure(
        reasons[0] if reasons else "btc_manual_metadata_import_rejected",
        generated=generated,
        dry_run=dry_run,
        raw_input_files=raw_input_files,
        captured_at=captured_at,
    )
    payload["blockers"] = _dedupe(reasons)
    return payload


def _extract_btcusdt_symbol_info(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        if payload.get("symbol") == "BTCUSDT":
            return dict(payload)
        for key in ("symbols", "rows", "data", "payload", "raw_symbol_info"):
            found = _extract_btcusdt_symbol_info(payload.get(key))
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_btcusdt_symbol_info(item)
            if found:
                return found
    return {}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)


def _write_json_atomic(payload: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(output)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def _overlay_schema_blockers(exchange_overlay: Mapping[str, Any], funding_overlay: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not _schema_valid(exchange_overlay, EXCHANGE_INFO_SCHEMA):
        blockers.append("btc_exchange_info_overlay_schema_invalid")
    if not _schema_valid(funding_overlay, FUNDING_INFO_SCHEMA):
        blockers.append("btc_funding_info_overlay_schema_invalid")
    return blockers


def _schema_valid(payload: Mapping[str, Any], schema_path: Path) -> bool:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(dict(payload), schema)
    except jsonschema.ValidationError:
        return False
    return True


def _captured_at_or_now(value: str | None) -> str:
    if not value:
        raise ValueError("captured_at is required")
    parsed = _parse_utc_timestamp(value)
    if parsed is None:
        raise ValueError("captured_at must be an ISO-8601 UTC timestamp")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _captured_at_is_after_generated_at(captured_at: str, generated_at: str) -> bool:
    captured = _parse_utc_timestamp(captured_at)
    generated = _parse_utc_timestamp(generated_at)
    if captured is None or generated is None:
        return True
    return captured > generated


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def _raw_file_evidence(path: Path, *, http_status_path: Path | None = None) -> dict[str, Any]:
    exists = path.exists()
    http_status = _read_http_status(http_status_path)
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _sha256(path) if exists else None,
        "http_status_file": str(http_status_path) if http_status_path is not None else None,
        "http_status": http_status,
        "http_status_verified": http_status == 200,
    }


def _http_status_blockers(raw_input_files: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    exchange = raw_input_files.get("exchange_info_raw")
    funding = raw_input_files.get("funding_info_raw")
    if not isinstance(exchange, Mapping) or exchange.get("http_status_verified") is not True:
        blockers.append("btc_exchange_info_raw_http_status_not_200")
    if not isinstance(funding, Mapping) or funding.get("http_status_verified") is not True:
        blockers.append("btc_funding_info_raw_http_status_not_200")
    return blockers


def _read_http_status(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    try:
        return int(text)
    except ValueError:
        return None


def _selected_bundle_blockers(*, bundle_dir: Path, bundle_id: str, config: Path) -> list[str]:
    if not config.exists():
        return []
    selected = _selected_bundle_from_config(config)
    if not selected:
        return ["btc_manual_metadata_import_selected_bundle_config_missing"]
    blockers: list[str] = []
    if bundle_id != selected["bundle_id"]:
        blockers.append("btc_manual_metadata_import_bundle_id_not_selected")
    if not _same_resolved_path(bundle_dir, selected["bundle_dir"]):
        blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
    return blockers


def _raw_location_blockers(*, bundle_dir: Path, exchange_info_raw: Path, funding_info_raw: Path) -> list[str]:
    blockers: list[str] = []
    if _same_resolved_path(exchange_info_raw, funding_info_raw):
        blockers.append("btc_manual_metadata_raw_files_not_distinct")
    if _path_is_relative_to(exchange_info_raw, bundle_dir):
        blockers.append("btc_exchange_info_raw_inside_bundle_dir")
    if _path_is_relative_to(funding_info_raw, bundle_dir):
        blockers.append("btc_funding_info_raw_inside_bundle_dir")
    return blockers


def _selected_bundle_from_config(config: Path) -> dict[str, Any]:
    payload = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        return {}
    provider = payload.get("providers", {}).get("binance_usdm", {})
    if not isinstance(provider, Mapping):
        return {}
    root_value = provider.get("root")
    bundle_id = provider.get("selected_bundle_id")
    if not _non_empty_text(root_value) or not _non_empty_text(bundle_id):
        return {}
    repo_root = config.resolve().parents[2]
    return {
        "bundle_id": str(bundle_id),
        "bundle_dir": repo_root / str(root_value).strip() / "bundles" / str(bundle_id).strip(),
    }


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _fatal_manifest_blockers(value: object) -> list[str]:
    diagnostic_allowed = {
        "btc_open_interest_history_not_verified_diagnostic_partial",
        "btc_liquidation_snapshots_missing_diagnostic_only",
    }
    return [item for item in _list_of_strings(value) if item not in diagnostic_allowed]


if __name__ == "__main__":
    main()
