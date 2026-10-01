from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from scripts.clear_btc_manual_metadata_import_marker import clear_btc_manual_metadata_import_marker
import scripts.import_btc_manual_metadata_capture as manual_metadata_importer
from scripts.import_btc_manual_metadata_capture import (
    MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER,
    import_manual_metadata_capture,
    write_manual_metadata_import_report,
)


SCHEMA = Path("schemas/btc_manual_metadata_import_report.schema.json")


def test_manual_metadata_operator_docs_use_atomic_importer() -> None:
    request = Path("docs/btc_exchange_info_manual_capture_request.md").read_text(encoding="utf-8")
    funding_policy = Path("docs/btc_funding_info_metadata_policy.md").read_text(encoding="utf-8")
    operator_guide = Path("docs/btc_binance_usdm_public_data_operator_guide.md").read_text(encoding="utf-8")

    for text in (request, funding_policy, operator_guide):
        assert "make dry-run-btc-manual-metadata-import" in text
        assert "make apply-btc-manual-metadata-import" in text
        assert "BTC_MANUAL_METADATA_CAPTURED_AT" in text
    assert "EXCHANGE_INFO_RAW=exchange_info_raw.json" in request
    assert "FUNDING_INFO_RAW=funding_info_raw.json" in request
    assert "make dry-run-btc-manual-metadata-import" in request
    assert "make apply-btc-manual-metadata-import" in request
    assert "Only after the dry-run import verifies both contracts" in request
    assert "make dry-run-btc-manual-metadata-import" in funding_policy
    assert "make apply-btc-manual-metadata-import" in funding_policy
    assert "Only after the dry-run verifies both metadata contracts" in funding_policy
    assert "make dry-run-btc-manual-metadata-import" in operator_guide
    assert "make apply-btc-manual-metadata-import" in operator_guide
    assert "make dry-run-btc-paper-gate-manual-inputs" in operator_guide
    assert "make apply-btc-paper-gate-manual-inputs" in operator_guide
    assert "writes nothing unless both" in funding_policy


def test_manual_metadata_import_dry_run_verifies_both_inputs_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path)
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        exchange_info_http_status=exchange_status,
        funding_info_http_status=funding_status,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
        dry_run=True,
        require_http_status_evidence=True,
    )

    assert result["status"] == "verified"
    assert result["writes_performed"] is False
    assert result["captured_at"] == "2026-05-22T00:00:00Z"
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is True
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert result["raw_input_files"]["exchange_info_raw"]["size_bytes"] == exchange_raw.stat().st_size
    assert len(result["raw_input_files"]["exchange_info_raw"]["sha256"]) == 64
    assert result["raw_input_files"]["exchange_info_raw"]["http_status"] == 200
    assert result["raw_input_files"]["exchange_info_raw"]["http_status_verified"] is True
    assert result["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert len(result["raw_input_files"]["funding_info_raw"]["sha256"]) == 64
    assert result["raw_input_files"]["funding_info_raw"]["http_status"] == 200
    assert result["raw_input_files"]["funding_info_raw"]["http_status_verified"] is True
    assert result["exchange_info_output_path"] == str(bundle / "exchange_info.json")
    assert len(result["exchange_info_output_sha256"]) == 64
    assert result["funding_info_output_path"] == str(bundle / "funding_info.json")
    assert len(result["funding_info_output_sha256"]) == 64
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()

    report_path = tmp_path / "btc_manual_metadata_import_report.json"
    write_manual_metadata_import_report(result, report_path)
    _assert_schema_valid(json.loads(report_path.read_text(encoding="utf-8")))


def test_manual_metadata_import_rejects_bundle_id_not_selected_before_writing(tmp_path: Path) -> None:
    config = _write_selected_bundle_config(tmp_path, selected_bundle_id="selected_bundle")
    selected_bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/selected_bundle"
    wrong_bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/wrong_bundle"
    _write_bundle_support_files(selected_bundle)
    _write_bundle_support_files(wrong_bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path)
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=wrong_bundle,
        bundle_id="wrong_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
        selected_bundle_config=config,
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_manual_metadata_import_bundle_id_not_selected" in result["blockers"]
    assert "btc_manual_metadata_import_bundle_dir_not_selected_bundle" in result["blockers"]
    assert not (wrong_bundle / "exchange_info.json").exists()
    assert not (wrong_bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_accepts_configured_selected_bundle(tmp_path: Path) -> None:
    config = _write_selected_bundle_config(tmp_path, selected_bundle_id="selected_bundle")
    selected_bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/selected_bundle"
    _write_bundle_support_files(selected_bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path)
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=selected_bundle,
        bundle_id="selected_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        exchange_info_http_status=exchange_status,
        funding_info_http_status=funding_status,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
        dry_run=True,
        selected_bundle_config=config,
        require_http_status_evidence=True,
    )

    assert result["status"] == "verified"
    assert result["writes_performed"] is False
    assert result["blockers"] == []


def test_manual_metadata_import_rejects_non_200_http_status_before_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path, exchange_status=200, funding_status=451)
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        exchange_info_http_status=exchange_status,
        funding_info_http_status=funding_status,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
        require_http_status_evidence=True,
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_funding_info_raw_http_status_not_200" in result["blockers"]
    assert result["raw_input_files"]["exchange_info_raw"]["http_status_verified"] is True
    assert result["raw_input_files"]["funding_info_raw"]["http_status"] == 451
    assert result["raw_input_files"]["funding_info_raw"]["http_status_verified"] is False
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_raw_files_inside_bundle_before_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = bundle / "exchange_info_raw.json"
    funding_raw = bundle / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_exchange_info_raw_inside_bundle_dir" in result["blockers"]
    assert "btc_funding_info_raw_inside_bundle_dir" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_one_raw_file_inside_selected_bundle(tmp_path: Path) -> None:
    config = _write_selected_bundle_config(tmp_path, selected_bundle_id="selected_bundle")
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/selected_bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = bundle / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="selected_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
        selected_bundle_config=config,
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_exchange_info_raw_inside_bundle_dir" not in result["blockers"]
    assert "btc_funding_info_raw_inside_bundle_dir" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_reused_raw_file_path_before_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    shared_raw = tmp_path / "manual_metadata_raw.json"
    shared_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=shared_raw,
        funding_info_raw=shared_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "btc_manual_metadata_raw_files_not_distinct" in result["blockers"]
    assert result["raw_input_files"]["exchange_info_raw"]["path"] == str(shared_raw)
    assert result["raw_input_files"]["funding_info_raw"]["path"] == str(shared_raw)
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_report_schema_rejects_verified_report_without_utc_capture_time() -> None:
    payload = _valid_verified_import_report()
    payload["captured_at"] = None

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)

    payload = _valid_verified_import_report()
    payload["captured_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_report_schema_rejects_blank_raw_input_path() -> None:
    payload = _valid_verified_import_report()
    payload["raw_input_files"]["exchange_info_raw"]["path"] = "   "

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_report_schema_rejects_verified_report_without_validation_command() -> None:
    payload = _valid_verified_import_report()
    payload.pop("post_import_validation_command")

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)

    payload = _valid_verified_import_report()
    payload["post_import_validation_command"] = "   "

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_report_schema_rejects_verified_report_without_bundle_dir() -> None:
    payload = _valid_verified_import_report()
    payload.pop("bundle_dir")

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)

    payload = _valid_verified_import_report()
    payload["bundle_dir"] = "   "

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_report_schema_rejects_verified_report_without_output_hashes() -> None:
    payload = _valid_verified_import_report()
    payload.pop("exchange_info_output_sha256")

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)

    payload = _valid_verified_import_report()
    payload["funding_info_output_path"] = "   "

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_report_schema_rejects_non_utc_generated_at() -> None:
    payload = _valid_verified_import_report()
    payload["generated_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_report_schema_rejects_rejected_report_without_blocker() -> None:
    payload = _valid_verified_import_report()
    payload["status"] = "rejected"
    payload["writes_performed"] = False
    payload["exchange_info_verified"] = False
    payload["funding_info_verified"] = False
    payload["captured_at"] = None
    payload["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        _assert_schema_valid(payload)


def test_manual_metadata_import_writes_only_after_both_inputs_verify(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    exchange_overlay = json.loads((bundle / "exchange_info.json").read_text(encoding="utf-8"))
    funding_overlay = json.loads((bundle / "funding_info.json").read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "btc_perpetual_bundle_manifest.json").read_text(encoding="utf-8"))

    assert result["status"] == "verified"
    assert result["writes_performed"] is True
    assert result["captured_at"] == "2026-05-22T00:00:00Z"
    assert exchange_overlay["source_method"] == "manual_offline_capture"
    assert exchange_overlay["captured_at"] == "2026-05-22T00:00:00Z"
    assert exchange_overlay["api_key_used"] is False
    assert funding_overlay["endpoint_response_available"] is True
    assert funding_overlay["captured_at"] == "2026-05-22T00:00:00Z"
    assert manifest["source_type"] == "production"
    assert manifest["promotion_clean_allowed"] is True
    assert result["exchange_info_output_sha256"] == _sha256(bundle / "exchange_info.json")
    assert result["funding_info_output_sha256"] == _sha256(bundle / "funding_info.json")
    assert (bundle / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER).exists()


def test_manual_metadata_import_interruption_leaves_in_progress_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")
    real_write_json_atomic = manual_metadata_importer._write_json_atomic

    def interrupted_write(payload: dict[str, object], output: Path) -> None:
        real_write_json_atomic(payload, output)
        if output == bundle / "exchange_info.json":
            raise RuntimeError("simulated interrupted manual metadata publication")

    monkeypatch.setattr(manual_metadata_importer, "_write_json_atomic", interrupted_write)

    with pytest.raises(RuntimeError, match="simulated interrupted"):
        import_manual_metadata_capture(
            bundle_dir=bundle,
            bundle_id="fixture_bundle",
            exchange_info_raw=exchange_raw,
            funding_info_raw=funding_raw,
            captured_at="2026-05-22T00:00:00Z",
            operator_note="manual public metadata capture; no API key and no private endpoint",
        )

    assert (bundle / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER).exists()
    assert (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()


def test_manual_metadata_import_marker_clear_requires_report_and_blocked_rebuild(
    tmp_path: Path,
) -> None:
    config = _write_selected_bundle_config(tmp_path, selected_bundle_id="selected_bundle")
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/selected_bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path)
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="selected_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        exchange_info_http_status=exchange_status,
        funding_info_http_status=funding_status,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
        selected_bundle_config=config,
        require_http_status_evidence=True,
    )
    report = tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    write_manual_metadata_import_report(result, report)

    blocked_clear = clear_btc_manual_metadata_import_marker(
        repo_root=tmp_path,
        bundle_dir=bundle,
        import_report=report,
        selected_bundle_config=config,
        generated_at="2026-05-22T00:01:00Z",
    )

    assert blocked_clear["status"] == "rejected"
    assert "btc_manual_metadata_import_provider_marker_blocker_missing" in blocked_clear["blockers"]
    assert "btc_manual_metadata_import_readiness_marker_blocker_missing" in blocked_clear["blockers"]
    assert (bundle / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER).exists()

    _write_json_file(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {"blockers": ["btc_manual_metadata_import_in_progress"]},
    )
    _write_json_file(
        tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json",
        {"blockers": ["btc_paper_readiness_manual_metadata_import_in_progress"]},
    )

    cleared = clear_btc_manual_metadata_import_marker(
        repo_root=tmp_path,
        bundle_dir=bundle,
        import_report=report,
        selected_bundle_config=config,
        generated_at="2026-05-22T00:02:00Z",
    )

    assert cleared["status"] == "cleared"
    assert cleared["blockers"] == []
    assert cleared["marker_exists_before"] is True
    assert cleared["marker_exists_after"] is False
    assert not (bundle / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER).exists()


def test_manual_metadata_import_rejects_non_utc_capture_time_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T08:00:00+08:00",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["captured_at"] is None
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert result["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert "btc_manual_metadata_captured_at_not_utc_iso8601" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_future_capture_time_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2999-01-01T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["captured_at"] is None
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert result["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert "btc_manual_metadata_captured_at_in_future" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_missing_capture_time_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at=None,
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["captured_at"] is None
    assert "btc_manual_metadata_captured_at_not_utc_iso8601" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_whitespace_operator_note_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="   ",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["captured_at"] is None
    assert "btc_manual_metadata_operator_note_missing" in result["blockers"]
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert result["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_invalid_exchange_info_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [{**_valid_symbol_info(), "filters": []}]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert result["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert "btc_exchange_info_tick_size_missing" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()

    report_path = tmp_path / "btc_manual_metadata_import_report.json"
    write_manual_metadata_import_report(result, report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    _assert_schema_valid(report)
    assert report["status"] == "rejected"
    assert report["writes_performed"] is False


def test_manual_metadata_import_rejects_schema_invalid_exchange_overlay_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    numeric_filter_symbol = {
        **_valid_symbol_info(),
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": 0.10},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"},
        ],
    }
    exchange_raw.write_text(json.dumps({"symbols": [numeric_filter_symbol]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is True
    assert "btc_exchange_info_overlay_schema_invalid" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_funding_info_error_body_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(
        json.dumps(
            {
                "code": 0,
                "msg": "Service unavailable from a restricted location according to 'b. Eligibility'.",
            }
        ),
        encoding="utf-8",
    )

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_error_response" in result["blockers"]
    assert "btc_funding_info_endpoint_response_not_array" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_non_array_funding_info_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps({"note": "unexpected object shape"}), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_response_not_array" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_schema_invalid_funding_overlay_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([{"symbol": "ETHUSDT", "adjustedFundingRateCap": "NaN"}]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is True
    assert "btc_funding_info_overlay_schema_invalid" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_malformed_funding_info_array_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([1, "bad-row"]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_array_item_not_object" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_malformed_btcusdt_funding_info_row_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([{"symbol": "BTCUSDT"}]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is False
    assert "btc_funding_info_btcusdt_funding_interval_missing" in result["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_cap_missing" in result["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_floor_missing" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_non_finite_btcusdt_funding_info_row_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(
        json.dumps(
            [
                {
                    "symbol": "BTCUSDT",
                    "adjustedFundingRateCap": "NaN",
                    "adjustedFundingRateFloor": "-Infinity",
                    "fundingIntervalHours": "Infinity",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["exchange_info_verified"] is True
    assert result["funding_info_verified"] is False
    assert "btc_funding_info_btcusdt_funding_interval_missing" in result["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_cap_missing" in result["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_floor_missing" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_missing_raw_file_with_reportable_provenance(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is False
    assert result["raw_input_files"]["exchange_info_raw"]["sha256"] is None
    assert result["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert "exchange_info_raw_missing" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_malformed_raw_json_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text("{not-json", encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert result["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert len(result["raw_input_files"]["exchange_info_raw"]["sha256"]) == 64
    assert "exchange_info_raw_invalid_json" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_cli_writes_rejected_report_before_nonzero_exit(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path)
    report_path = tmp_path / "btc_manual_metadata_import_report.json"
    exchange_raw.write_text("{not-json", encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/import_btc_manual_metadata_capture.py",
            "--bundle-dir",
            str(bundle),
            "--bundle-id",
            "fixture_bundle",
            "--exchange-info-raw",
            str(exchange_raw),
            "--funding-info-raw",
            str(funding_raw),
            "--exchange-info-http-status",
            str(exchange_status),
            "--funding-info-http-status",
            str(funding_status),
            "--captured-at",
            "2026-05-22T00:00:00Z",
            "--operator-note",
            "manual public metadata capture; no API key and no private endpoint",
            "--selected-bundle-config",
            "",
            "--report-output",
            str(report_path),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "rejected"
    assert report["writes_performed"] is False
    assert "exchange_info_raw_invalid_json" in report["blockers"]
    assert report["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert report["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(report)


def test_manual_metadata_import_cli_writes_rejected_report_for_blank_operator_note(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_status, funding_status = _write_http_status_files(tmp_path)
    report_path = tmp_path / "btc_manual_metadata_import_report.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/import_btc_manual_metadata_capture.py",
            "--bundle-dir",
            str(bundle),
            "--bundle-id",
            "fixture_bundle",
            "--exchange-info-raw",
            str(exchange_raw),
            "--funding-info-raw",
            str(funding_raw),
            "--exchange-info-http-status",
            str(exchange_status),
            "--funding-info-http-status",
            str(funding_status),
            "--captured-at",
            "2026-05-22T00:00:00Z",
            "--operator-note",
            "   ",
            "--selected-bundle-config",
            "",
            "--report-output",
            str(report_path),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "rejected"
    assert report["writes_performed"] is False
    assert "btc_manual_metadata_operator_note_missing" in report["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(report)


def test_manual_metadata_import_rejects_non_standard_exchange_json_constants_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text('{"symbols":[{"symbol":"BTCUSDT","pricePrecision":NaN}]}', encoding="utf-8")
    funding_raw.write_text(json.dumps([]), encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "exchange_info_raw_invalid_json" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def test_manual_metadata_import_rejects_non_standard_funding_json_constants_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle_support_files(bundle)
    exchange_raw = tmp_path / "exchange_info_raw.json"
    funding_raw = tmp_path / "funding_info_raw.json"
    exchange_raw.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    funding_raw.write_text('[{"symbol":"BTCUSDT","fundingIntervalHours":Infinity}]', encoding="utf-8")

    result = import_manual_metadata_capture(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        exchange_info_raw=exchange_raw,
        funding_info_raw=funding_raw,
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public metadata capture; no API key and no private endpoint",
    )

    assert result["status"] == "rejected"
    assert result["writes_performed"] is False
    assert "funding_info_raw_invalid_json" in result["blockers"]
    assert not (bundle / "exchange_info.json").exists()
    assert not (bundle / "funding_info.json").exists()
    _assert_schema_valid(result)


def _assert_schema_valid(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def _write_bundle_support_files(bundle: Path) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    _write_funding_rate(bundle / "funding_rate.csv", count=120)
    for filename in (
        "klines_1h.csv",
        "klines_4h.csv",
        "klines_1d.csv",
        "mark_price_klines_1h.csv",
        "premium_index_klines_1h.csv",
    ):
        (bundle / filename).write_text(
            "timestamp,open_time_ms,open,high,low,close,volume,close_time_ms,source_record_id\n"
            "2026-01-01T00:00:00Z,1767225600000,1,1,1,1,1,1767229199999,row1\n",
            encoding="utf-8",
        )
    (bundle / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps({"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}),
        encoding="utf-8",
    )


def _write_funding_rate(path: Path, *, count: int) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        timestamp = start + timedelta(hours=8 * index)
        funding_ms = int(timestamp.timestamp() * 1000)
        rows.append(f"{timestamp.isoformat().replace('+00:00', 'Z')},{funding_ms},BTCUSDT,0.0001,100000,f{index}")
    path.write_text(
        "timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _write_selected_bundle_config(tmp_path: Path, *, selected_bundle_id: str) -> Path:
    config = tmp_path / "configs/data/btc_perpetual_sources.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "\n".join(
            [
                "providers:",
                "  binance_usdm:",
                "    root: data/external/btc_perpetual/binance_usdm/",
                f"    selected_bundle_id: {selected_bundle_id}",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _write_http_status_files(
    tmp_path: Path,
    *,
    exchange_status: int = 200,
    funding_status: int = 200,
) -> tuple[Path, Path]:
    exchange = tmp_path / "exchange_info_http_status.txt"
    funding = tmp_path / "funding_info_http_status.txt"
    exchange.write_text(f"{exchange_status}\n", encoding="utf-8")
    funding.write_text(f"{funding_status}\n", encoding="utf-8")
    return exchange, funding


def _write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _valid_symbol_info() -> dict[str, object]:
    return {
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
    }


def _valid_verified_import_report() -> dict[str, object]:
    return {
        "schema_version": "btc_manual_metadata_import_report_v1",
        "status": "verified",
        "generated_at": "2026-05-22T00:01:00Z",
        "dry_run": False,
        "captured_at": "2026-05-22T00:00:00Z",
        "writes_performed": True,
        "exchange_info_verified": True,
        "funding_info_verified": True,
        "raw_input_files": {
            "exchange_info_raw": {
                "path": "exchange_info_raw.json",
                "exists": True,
                "size_bytes": 100,
                "sha256": "a" * 64,
                "http_status_file": "exchange_info_http_status.txt",
                "http_status": 200,
                "http_status_verified": True,
            },
            "funding_info_raw": {
                "path": "funding_info_raw.json",
                "exists": True,
                "size_bytes": 2,
                "sha256": "b" * 64,
                "http_status_file": "funding_info_http_status.txt",
                "http_status": 200,
                "http_status_verified": True,
            },
        },
        "exchange_info_output_path": "data/external/btc_perpetual/binance_usdm/bundles/fixture/exchange_info.json",
        "exchange_info_output_sha256": "c" * 64,
        "funding_info_output_path": "data/external/btc_perpetual/binance_usdm/bundles/fixture/funding_info.json",
        "funding_info_output_sha256": "d" * 64,
        "bundle_dir": "data/external/btc_perpetual/binance_usdm/bundles/fixture",
        "post_import_validation_command": "make validate-btc-public-data-bundle",
        "blockers": [],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
