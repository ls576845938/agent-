from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_perpetual_data_bundle_manifest import (
    build_btc_perpetual_data_bundle_manifest,
    write_manifest,
)
from scripts.build_btc_perpetual_bundle_preflight_report import build_btc_perpetual_bundle_preflight_report


SCHEMA = Path("schemas/btc_perpetual_bundle_preflight_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")


def test_btc_perpetual_bundle_preflight_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["selected_bundle_id"] == "btc_okx_swap_btcusdt_history_365d_v1"
    assert payload["preflight_pass"] is True
    assert payload["missing_required_files"] == []
    assert payload["manifest_missing_file_entries"] == []
    assert payload["disk_missing_required_files"] == []
    assert payload["next_required_action"] == "none"


def test_no_selected_bundle_fails_preflight() -> None:
    payload = build_btc_perpetual_bundle_preflight_report(
        repo_root=Path("/tmp/nonexistent-btc-preflight-root"),
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["selected_bundle_id"] is None
    assert set(payload["missing_required_files"]) == {
        "klines_1h.csv",
        "klines_4h.csv",
        "klines_1d.csv",
        "mark_price_klines_1h.csv",
        "premium_index_klines_1h.csv",
        "funding_rate.csv",
        "funding_info.json",
        "exchange_info.json",
    }
    assert payload["preflight_pass"] is False
    assert "btc_perpetual_selected_bundle_missing" in payload["blockers"]


def test_fixture_bundle_fails_preflight_even_when_structural(tmp_path: Path) -> None:
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

    payload = build_btc_perpetual_bundle_preflight_report(repo_root=tmp_path, config_path=config)

    assert payload["source_type"] == "fixture"
    assert payload["required_files_present"] is True
    assert payload["missing_required_files"] == []
    assert payload["preflight_pass"] is False
    assert "btc_perpetual_bundle_source_type_not_production" in payload["blockers"]


def test_complete_production_bundle_can_preflight_pass_even_before_provider_ready(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="public archive",
        promotion_clean_allowed=False,
    )
    write_manifest(manifest, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=False)

    payload = build_btc_perpetual_bundle_preflight_report(repo_root=tmp_path, config_path=config)

    assert payload["preflight_pass"] is True
    assert payload["missing_required_files"] == []
    assert payload["next_required_action"] == "none"
    assert payload["promotion_clean_allowed_by_config"] is False
    assert payload["promotion_clean_allowed_by_manifest"] is False


def test_production_missing_manifest_metadata_fails(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_bundle_preflight_report(repo_root=tmp_path, config_path=config)

    assert payload["preflight_pass"] is False
    assert payload["license_note_present"] is False
    assert payload["next_required_action"] == "repair_btc_perpetual_bundle_manifest"
    assert "btc_perpetual_bundle_license_note_missing" in payload["blockers"]


def test_network_flags_must_be_disabled_for_preflight_verification(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="public archive",
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

    payload = build_btc_perpetual_bundle_preflight_report(repo_root=tmp_path, config_path=config)

    assert payload["preflight_pass"] is False
    assert "btc_perpetual_allow_network_must_be_disabled_for_verification" in payload["blockers"]
    assert "btc_perpetual_public_rest_fetch_must_be_disabled_for_verification" in payload["blockers"]


def test_missing_exchange_info_is_structured_for_manual_capture(tmp_path: Path) -> None:
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/prod1"
    _write_required_files(bundle)
    (bundle / "exchange_info.json").unlink()
    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="prod1",
        source_type="production",
        license_note="public archive",
        promotion_clean_allowed=True,
    )
    write_manifest(manifest, bundle)
    config = _write_config(tmp_path, enabled=True, selected_bundle_id="prod1", promotion_clean_allowed=True)

    payload = build_btc_perpetual_bundle_preflight_report(repo_root=tmp_path, config_path=config)

    exchange_check = next(item for item in payload["required_files"] if item["path"] == "exchange_info.json")
    assert payload["preflight_pass"] is False
    assert "exchange_info.json" in payload["missing_required_files"]
    assert "exchange_info.json" in payload["manifest_missing_file_entries"]
    assert "exchange_info.json" in payload["disk_missing_required_files"]
    assert exchange_check["role"] == "exchange_info"
    assert exchange_check["disk_file_exists"] is False
    assert exchange_check["manifest_entry_present"] is False
    assert payload["next_required_action"] == "manual_capture_metadata_from_allowed_network"


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
                "    landing_mode: local_archive_import",
                "    root: data/external/btc_perpetual/binance_usdm/",
                f"    selected_bundle_id: {selected}",
                "    require_explicit_bundle_selection: true",
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
    required = [
        "klines_1h.csv",
        "klines_4h.csv",
        "klines_1d.csv",
        "mark_price_klines_1h.csv",
        "premium_index_klines_1h.csv",
        "funding_rate.csv",
        "funding_info.json",
        "exchange_info.json",
    ]
    for filename in required:
        path = bundle / filename
        if filename.endswith(".csv"):
            path.write_text(
                "timestamp,value\n2026-01-01T00:00:00Z,1\n2026-01-01T01:00:00Z,2\n",
                encoding="utf-8",
            )
        else:
            path.write_text(json.dumps({"rows": [{"timestamp": "2026-01-01T00:00:00Z"}]}), encoding="utf-8")
