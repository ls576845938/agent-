from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema

from scripts.build_btc_perpetual_data_bundle_manifest import (
    build_btc_perpetual_data_bundle_manifest,
    write_manifest,
)
from scripts.build_btc_perpetual_provider_verification_report import (
    MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER,
    build_btc_perpetual_provider_verification_report,
)


SCHEMA = Path("schemas/btc_perpetual_provider_verification_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")


def test_btc_perpetual_provider_verification_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_default_provider_verification_is_fail_closed() -> None:
    payload = build_btc_perpetual_provider_verification_report(
        repo_root=Path("/tmp/nonexistent-btc-provider-root"),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["selected_provider"] == "binance_usdm"
    assert payload["selected_bundle_id"] is None
    assert payload["perpetual_evidence_ready"] is False
    assert payload["liquidation_snapshot_gate_eligible"] is False
    assert "btc_perpetual_explicit_bundle_selection_missing" in payload["blockers"]


def test_complete_fixture_bundle_is_not_perpetual_evidence_ready(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/fixture1"
    _write_required_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="fixture1",
        source_type="fixture",
        license_note="fixture",
    )
    write_manifest(manifest, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="fixture1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["source_type"] == "fixture"
    assert payload["preflight_pass"] is False
    assert payload["klines_verified"] is True
    assert payload["perpetual_evidence_ready"] is False
    assert "btc_perpetual_source_type_fixture_not_candidate_eligible" in payload["blockers"]


def test_complete_production_bundle_can_be_ready_only_when_explicitly_allowed(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    _write_diagnostic_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    _write_verified_manual_import_report(tmp_path, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["source_type"] == "production"
    assert payload["preflight_pass"] is True
    assert payload["manual_metadata_import_verified"] is True
    assert payload["manual_metadata_import_exchange_info_output_hash_verified"] is True
    assert payload["manual_metadata_import_funding_info_output_hash_verified"] is True
    assert payload["perpetual_evidence_ready"] is True
    assert payload["blockers"] == []


def test_provider_verification_diagnostic_market_microstructure_gaps_do_not_block_perpetual_evidence_ready(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    _write_verified_manual_import_report(tmp_path, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["perpetual_evidence_ready"] is True
    assert payload["open_interest_verified"] is False
    assert payload["open_interest_gate_eligible"] is False
    assert payload["liquidation_snapshot_available"] is False
    assert payload["liquidation_snapshot_gate_eligible"] is False
    assert "btc_open_interest_history_not_verified_diagnostic_partial" in payload["diagnostic_warnings"]
    assert "btc_open_interest_history_not_verified_diagnostic_partial" not in payload["blockers"]


def test_provider_verification_blocks_manual_metadata_import_in_progress_marker(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    _write_diagnostic_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    _write_verified_manual_import_report(tmp_path, bundle)
    (bundle / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER).write_text(
        json.dumps(
            {
                "schema_version": "btc_manual_metadata_import_in_progress_v1",
                "generated_at": "2026-05-22T00:00:00Z",
                "bundle_id": "prod1",
            }
        ),
        encoding="utf-8",
    )
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["manual_metadata_import_verified"] is False
    assert payload["perpetual_evidence_ready"] is False
    assert "btc_manual_metadata_import_in_progress" in payload["blockers"]


def test_production_bundle_requires_verified_manual_metadata_import_report(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    _write_diagnostic_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["preflight_pass"] is True
    assert payload["manual_metadata_import_verified"] is False
    assert payload["perpetual_evidence_ready"] is False
    assert "btc_manual_metadata_import_report_missing" in payload["blockers"]


def test_provider_verification_rejects_manual_import_output_hash_mismatch(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    _write_diagnostic_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    _write_verified_manual_import_report(tmp_path, bundle, exchange_hash="0" * 64)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["manual_metadata_import_verified"] is False
    assert payload["manual_metadata_import_exchange_info_output_hash_verified"] is False
    assert payload["perpetual_evidence_ready"] is False
    assert "btc_manual_metadata_import_exchange_info_output_hash_mismatch" in payload["blockers"]


def test_provider_verification_rejects_manual_import_raw_http_evidence_not_200(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    _write_diagnostic_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    _write_verified_manual_import_report(tmp_path, bundle)
    report_path = tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["raw_input_files"]["funding_info_raw"]["http_status"] = 451
    report["raw_input_files"]["funding_info_raw"]["http_status_verified"] = False
    status_path = tmp_path / report["raw_input_files"]["funding_info_raw"]["http_status_file"]
    status_path.write_text("451\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["manual_metadata_import_verified"] is False
    assert payload["perpetual_evidence_ready"] is False
    assert "btc_funding_info_raw_http_status_not_200" in payload["blockers"]


def test_provider_verification_blocks_when_network_flags_stay_enabled(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    _write_diagnostic_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="production export",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    config = _write_config(
        tmp_path,
        enabled=True,
        selected_bundle_id="prod1",
        promotion_clean_allowed=True,
        allow_public_rest_fetch=True,
        allow_network=True,
    )

    payload = build_btc_perpetual_provider_verification_report(repo_root=tmp_path, config_path=config)

    assert payload["perpetual_evidence_ready"] is False
    assert "btc_perpetual_allow_network_must_be_disabled_for_verification" in payload["blockers"]
    assert "btc_perpetual_public_rest_fetch_must_be_disabled_for_verification" in payload["blockers"]


def _write_config(
    root: Path,
    *,
    enabled: bool,
    selected_bundle_id: str | None,
    promotion_clean_allowed: bool,
    allow_public_rest_fetch: bool = False,
    allow_network: bool = False,
) -> Path:
    path = root / "configs/data/btc_perpetual_sources.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = "null" if selected_bundle_id is None else selected_bundle_id
    path.write_text(
        "\n".join(
            [
                "providers:",
                "  binance_usdm:",
                f"    enabled: {str(enabled).lower()}",
                "    mode: local_bundle",
                "    root: data/external/btc_perpetual/binance_usdm/",
                f"    selected_bundle_id: {selected}",
                f"    allow_public_rest_fetch: {str(allow_public_rest_fetch).lower()}",
                f"    allow_network: {str(allow_network).lower()}",
                "    allow_private_endpoints: false",
                "    allow_order_endpoints: false",
                f"    promotion_clean_allowed: {str(promotion_clean_allowed).lower()}",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_required_files(bundle: Path) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    _write_csv(bundle / "klines_1h.csv", _timestamps("2026-01-01T00:00:00Z", hours=1, count=25))
    _write_csv(bundle / "klines_4h.csv", _timestamps("2026-01-01T00:00:00Z", hours=4, count=7))
    _write_csv(bundle / "klines_1d.csv", ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"])
    _write_csv(
        bundle / "mark_price_klines_1h.csv",
        _timestamps("2026-01-01T00:00:00Z", hours=1, count=25),
    )
    _write_csv(
        bundle / "premium_index_klines_1h.csv",
        _timestamps("2026-01-01T00:00:00Z", hours=1, count=25),
    )
    _write_csv(bundle / "funding_rate.csv", _timestamps("2026-01-01T00:00:00Z", hours=8, count=4))
    (bundle / "funding_info.json").write_text(
        json.dumps(
            {
                "source_method": "public_rest_response",
                "source_endpoint": "/fapi/v1/fundingInfo",
                "captured_at": "2026-01-01T00:00:00Z",
                "symbol": "BTCUSDT",
                "endpoint_response_available": True,
                "raw_response": [
                    {
                        "symbol": "BTCUSDT",
                        "adjustedFundingRateCap": "0.02500000",
                        "adjustedFundingRateFloor": "-0.02500000",
                        "fundingIntervalHours": 8,
                        "disclaimer": False,
                    }
                ],
                "symbol_adjustment_record_present": True,
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    (bundle / "exchange_info.json").write_text(
        json.dumps(
            {
                "source_method": "manual_offline_capture",
                "source_endpoint": "/fapi/v1/exchangeInfo",
                "source_url_or_doc": "offline capture from /fapi/v1/exchangeInfo",
                "captured_at": "2026-01-01T00:00:00Z",
                "symbol": "BTCUSDT",
                "raw_symbol_info": {
                    "symbol": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "pricePrecision": 2,
                    "quantityPrecision": 3,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "100"},
                    ],
                },
                "historical_rule_lineage_available": False,
                "operator_note": "manual public exchangeInfo capture",
                "api_key_used": False,
                "private_endpoint_used": False,
                "auth_headers_present": False,
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )


def _write_csv(path: Path, timestamps: list[str]) -> None:
    path.write_text(
        "timestamp,value\n" + "\n".join(f"{timestamp},1" for timestamp in timestamps) + "\n",
        encoding="utf-8",
    )


def _timestamps(start: str, *, hours: int, count: int) -> list[str]:
    current = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
    return [
        (current + timedelta(hours=hours * index)).isoformat().replace("+00:00", "Z")
        for index in range(count)
    ]


def _write_diagnostic_files(bundle: Path) -> None:
    (bundle / "open_interest_hist_1h.csv").write_text(
        "timestamp,value\n" + "\n".join(f"{timestamp},1" for timestamp in _timestamps("2026-01-01T00:00:00Z", hours=1, count=25)) + "\n",
        encoding="utf-8",
    )
    (bundle / "open_interest_current.json").write_text(
        json.dumps({"rows": [{"timestamp": "2026-01-01T01:00:00Z"}]}),
        encoding="utf-8",
    )


def _write_verified_manual_import_report(root: Path, bundle: Path, *, exchange_hash: str | None = None) -> None:
    report = root / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    exchange_path = bundle / "exchange_info.json"
    funding_path = bundle / "funding_info.json"
    raw_dir = root / "artifacts/btc_data_status/raw/manual_metadata"
    raw_dir.mkdir(parents=True, exist_ok=True)
    exchange_raw = raw_dir / "exchange_info_raw.json"
    funding_raw = raw_dir / "funding_info_raw.json"
    exchange_status = raw_dir / "exchange_info_http_status.txt"
    funding_status = raw_dir / "funding_info_http_status.txt"
    exchange_raw.write_text(
        json.dumps({"serverTime": 1779408000000, "symbols": [{"symbol": "BTCUSDT"}]}),
        encoding="utf-8",
    )
    funding_raw.write_text(
        json.dumps({"symbols": [{"symbol": "BTCUSDT", "adjustedFundingRateCap": "0.003"}]}),
        encoding="utf-8",
    )
    exchange_status.write_text("200\n", encoding="utf-8")
    funding_status.write_text("200\n", encoding="utf-8")
    report.write_text(
        json.dumps(
            {
                "schema_version": "btc_manual_metadata_import_report_v1",
                "status": "verified",
                "generated_at": "2026-05-22T00:00:00Z",
                "dry_run": False,
                "captured_at": "2026-05-22T00:00:00Z",
                "writes_performed": True,
                "exchange_info_verified": True,
                "funding_info_verified": True,
                "raw_input_files": {
                    "exchange_info_raw": {
                        "path": str(exchange_raw.relative_to(root)),
                        "exists": True,
                        "size_bytes": exchange_raw.stat().st_size,
                        "sha256": _sha256(exchange_raw),
                        "http_status_file": str(exchange_status.relative_to(root)),
                        "http_status": 200,
                        "http_status_verified": True,
                    },
                    "funding_info_raw": {
                        "path": str(funding_raw.relative_to(root)),
                        "exists": True,
                        "size_bytes": funding_raw.stat().st_size,
                        "sha256": _sha256(funding_raw),
                        "http_status_file": str(funding_status.relative_to(root)),
                        "http_status": 200,
                        "http_status_verified": True,
                    },
                },
                "exchange_info_output_path": str(exchange_path.relative_to(root)),
                "exchange_info_output_sha256": exchange_hash or _sha256(exchange_path),
                "funding_info_output_path": str(funding_path.relative_to(root)),
                "funding_info_output_sha256": _sha256(funding_path),
                "bundle_dir": str(bundle.relative_to(root)),
                "post_import_validation_command": "make validate-btc-public-data-bundle",
                "blockers": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
