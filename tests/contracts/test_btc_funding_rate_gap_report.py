from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema

from scripts.build_btc_funding_rate_gap_report import build_btc_funding_rate_gap_report


SCHEMA = Path("schemas/btc_funding_rate_gap_report.schema.json")


def test_current_btc_funding_rate_gap_report_schema_valid() -> None:
    payload = build_btc_funding_rate_gap_report(generated_at="2026-05-19T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["bundle_id"] == "btc_usdm_binance_btcusdt_20240101_20260512_v1"
    assert payload["coverage_complete"] is True
    assert payload["expected_missing_funding_times"] == []
    assert payload["blockers"] == []


def test_complete_fixture_has_no_gap(tmp_path: Path) -> None:
    bundle = tmp_path / "bundles/test_bundle"
    bundle.mkdir(parents=True)
    (bundle / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps(
            {
                "sample_start": "2026-05-01T00:00:00Z",
                "sample_end": "2026-05-02T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    _write_funding_rate(bundle / "funding_rate.csv", "2026-05-01T00:00:00Z", 4)

    payload = build_btc_funding_rate_gap_report(
        bundle_id="test_bundle",
        bundle_root=tmp_path / "bundles",
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["coverage_complete"] is True
    assert payload["expected_missing_funding_times"] == []
    assert payload["blockers"] == []


def test_duplicate_funding_time_is_blocker(tmp_path: Path) -> None:
    bundle = tmp_path / "bundles/test_bundle"
    bundle.mkdir(parents=True)
    (bundle / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps({"sample_start": "2026-05-01T00:00:00Z", "sample_end": "2026-05-01T08:00:00Z"}),
        encoding="utf-8",
    )
    first = int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
    (bundle / "funding_rate.csv").write_text(
        "timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id\n"
        f"2026-05-01T00:00:00Z,{first},BTCUSDT,0.0001,1,a\n"
        f"2026-05-01T00:00:00Z,{first},BTCUSDT,0.0001,1,b\n",
        encoding="utf-8",
    )

    payload = build_btc_funding_rate_gap_report(
        bundle_id="test_bundle",
        bundle_root=tmp_path / "bundles",
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert payload["coverage_complete"] is False
    assert "btc_funding_rate_duplicate_funding_time" in payload["blockers"]


def _write_funding_rate(path: Path, start: str, count: int) -> None:
    current = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
    rows = []
    for index in range(count):
        dt = current + timedelta(hours=8 * index)
        ms = int(dt.timestamp() * 1000)
        rows.append(f"{dt.isoformat().replace('+00:00', 'Z')},{ms},BTCUSDT,0.0001,1,r{index}")
    path.write_text(
        "timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
