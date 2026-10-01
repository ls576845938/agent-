from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema

from scripts.merge_btc_funding_rate_patch import merge_btc_funding_rate_patch
from scripts.validate_btc_funding_rate_patch import DEFAULT_PATCH_ID, validate_btc_funding_rate_patch


SCHEMA = Path("schemas/btc_funding_rate_patch_metadata.schema.json")


def test_valid_manual_patch_passes_validation_and_dry_run_merge(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv)
    metadata = _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)

    jsonschema.validate(metadata, json.loads(SCHEMA.read_text(encoding="utf-8")))
    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")
    merge = merge_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles", dry_run=True)

    assert report["validation_pass"] is True
    assert report["record_count"] == 34
    assert merge["rows_added"] == 34
    assert merge["merge_success"] is False
    assert merge["blockers"] == []


def test_patch_duplicate_funding_time_fails(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv, duplicate=True)
    _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)

    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")

    assert report["validation_pass"] is False
    assert "btc_funding_rate_patch_duplicate_funding_time" in report["blockers"]


def test_patch_rejects_api_key_or_private_endpoint_metadata(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv)
    metadata = _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)
    metadata["api_key_used"] = True
    metadata["private_endpoint_used"] = True
    (bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")

    assert report["validation_pass"] is False
    assert "btc_funding_rate_patch_metadata_api_key_used_invalid" in report["blockers"]
    assert "btc_funding_rate_patch_metadata_private_endpoint_used_invalid" in report["blockers"]


def test_patch_rejects_non_manual_source_method(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv)
    metadata = _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)
    metadata["source_method"] = "explicit_public_rest_fetch"
    (bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")

    assert report["validation_pass"] is False
    assert "btc_funding_rate_patch_metadata_source_method_invalid" in report["blockers"]


def test_patch_rejects_wrong_request_window_metadata(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv)
    metadata = _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)
    metadata["startTime"] = 1777593600001
    (bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")

    assert report["validation_pass"] is False
    assert "btc_funding_rate_patch_metadata_startTime_invalid" in report["blockers"]


def test_patch_rejects_wrong_expected_times_even_if_metadata_is_consistent(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv, start_time="2026-05-01T08:00:00Z", row_count=34)
    _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)

    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")

    assert report["validation_pass"] is False
    assert "btc_funding_rate_patch_expected_times_mismatch" in report["blockers"]


def test_patch_rejects_non_finite_funding_rate(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv, funding_rate="NaN")
    _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)

    report = validate_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles")

    assert report["validation_pass"] is False
    assert "btc_funding_rate_patch_funding_rate_not_finite" in report["blockers"]


def test_merge_rejects_overlap_with_existing_funding_time(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv", last_time="2026-05-01T00:00:00Z")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv)
    _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)

    report = merge_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles", dry_run=True)

    assert "btc_funding_rate_patch_overlaps_existing_funding_time" in report["blockers"]
    assert report["rows_added"] == 0


def test_merge_rejects_existing_duplicate_funding_time(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    _write_existing_funding(bundle / "funding_rate.csv")
    with (bundle / "funding_rate.csv").open("a", encoding="utf-8") as handle:
        handle.write("2026-04-30T16:00:00Z,1777564800000,BTCUSDT,0.0001,1,existing_duplicate\n")
    patch_csv = bundle / "patches" / f"{DEFAULT_PATCH_ID}.csv"
    _write_patch_csv(patch_csv)
    _write_metadata(bundle / "patches" / f"{DEFAULT_PATCH_ID}.metadata.json", patch_csv)

    report = merge_btc_funding_rate_patch(bundle_id="bundle1", bundle_root=tmp_path / "bundles", dry_run=True)

    assert "btc_funding_rate_existing_duplicate_funding_time" in report["blockers"]
    assert report["rows_added"] == 0


def _bundle(root: Path) -> Path:
    bundle = root / "bundles/bundle1"
    (bundle / "patches").mkdir(parents=True)
    return bundle


def _write_existing_funding(path: Path, *, last_time: str = "2026-04-30T16:00:00Z") -> None:
    dt = datetime.fromisoformat(last_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    ms = int(dt.timestamp() * 1000)
    path.write_text(
        "timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id\n"
        f"{last_time},{ms},BTCUSDT,0.0001,1,existing\n",
        encoding="utf-8",
    )


def _write_patch_csv(path: Path, *, duplicate: bool = False, start_time: str = "2026-05-01T00:00:00Z", row_count: int = 34, funding_rate: str = "0.0001") -> None:
    start = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    rows = []
    for index in range(row_count):
        dt = start + timedelta(hours=8 * index)
        if duplicate and index == 1:
            dt = start
        ms = int(dt.timestamp() * 1000)
        rows.append(
            {
                "timestamp": dt.isoformat().replace("+00:00", "Z"),
                "fundingTime": str(ms),
                "symbol": "BTCUSDT",
                "fundingRate": funding_rate,
                "markPrice": "100000",
                "source_record_id": f"manual:{index}",
            }
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_metadata(path: Path, csv_path: Path) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "btc_funding_rate_patch_metadata_v1",
        "patch_id": DEFAULT_PATCH_ID,
        "csv_filename": f"{DEFAULT_PATCH_ID}.csv",
        "csv_sha256": _sha256(csv_path),
        "source_method": "manual_offline_public_rest_capture",
        "source_base_url": "https://fapi.binance.com",
        "source_endpoint": "/fapi/v1/fundingRate",
        "symbol": "BTCUSDT",
        "requested_start": "2026-05-01T00:00:00Z",
        "requested_end": "2026-05-12T00:00:00Z",
        "startTime": 1777593600000,
        "endTime": 1778544000000,
        "captured_at": "2026-05-19T00:00:00Z",
        "operator_note": "manual public REST capture from accessible environment",
        "api_key_used": False,
        "private_endpoint_used": False,
        "auth_headers_present": False,
        "record_count": 34,
        "expected_row_count": 34,
        "expected_first_fundingTime": 1777593600000,
        "expected_last_fundingTime": 1778544000000,
        "funding_interval_hours": 8,
        "target_bundle_id": "bundle1",
        "target_file": "funding_rate.csv",
        "merge_key": "fundingTime",
        "merge_policy": "fail_on_duplicate_fundingTime",
        "operator": "test",
        "created_at": "2026-05-19T00:00:00Z",
        "requests": [],
        "blockers": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
