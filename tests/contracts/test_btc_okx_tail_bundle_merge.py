from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.merge_btc_okx_swap_tail_bundle import merge_okx_tail_bundle


def test_okx_tail_merge_preserves_target_history_and_adds_pit_fields(tmp_path: Path) -> None:
    bundle_root = tmp_path / "data/external/btc_perpetual/okx_swap/bundles"
    target = bundle_root / "target_90d"
    tail = bundle_root / "tail_10d"
    target.mkdir(parents=True)
    tail.mkdir(parents=True)
    for filename in [
        "klines_1h.csv",
        "mark_price_klines_1h.csv",
        "premium_index_klines_1h.csv",
    ]:
        _write_bar_csv(target / filename, "2026-06-23T00:00:00Z")
        _write_bar_csv(tail / filename, "2026-06-29T00:00:00Z")
    for filename in ["klines_4h.csv", "klines_1d.csv"]:
        _write_bar_csv(target / filename, "2026-06-23T00:00:00Z")
        _write_bar_csv(tail / filename, "2026-06-29T00:00:00Z")
    _write_funding_csv(target / "funding_rate.csv", "2026-06-23T00:00:00Z")
    _write_funding_csv(tail / "funding_rate.csv", "2026-06-29T00:00:00Z")
    _write_json(target / "funding_info.json", {"captured_at": "2026-06-23T00:00:00Z", "symbol": "BTCUSDT"})
    _write_json(target / "exchange_info.json", {"captured_at": "2026-06-23T00:00:00Z", "symbol": "BTCUSDT"})
    _write_json(tail / "funding_info.json", {"captured_at": "2026-06-29T00:00:00Z", "symbol": "BTCUSDT"})
    _write_json(tail / "exchange_info.json", {"captured_at": "2026-06-29T00:00:00Z", "symbol": "BTCUSDT"})
    raw = tmp_path / "artifacts/btc_data_status/latest/okx_public_metadata_raw_capture"
    raw.mkdir(parents=True)
    (raw / "exchange_info_raw.json").write_text(json.dumps({"data": [{"instId": "BTC-USDT-SWAP"}]}), encoding="utf-8")
    (raw / "funding_info_raw.json").write_text(json.dumps({"data": [{"instId": "BTC-USDT-SWAP"}]}), encoding="utf-8")
    (raw / "exchange_info_http_status.txt").write_text("200\n", encoding="utf-8")
    (raw / "funding_info_http_status.txt").write_text("200\n", encoding="utf-8")

    payload = merge_okx_tail_bundle(
        repo_root=tmp_path,
        target_bundle_id="target_90d",
        tail_bundle_id="tail_10d",
        bundle_root=bundle_root,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert payload["status"] == "verified"
    assert payload["manifest_sample_end"] == "2026-06-29T00:00:00Z"
    row = _last_csv_row(target / "klines_1h.csv")
    assert row["timestamp"] == "2026-06-29T00:00:00Z"
    assert row["event_time"] == "2026-06-29T00:00:00Z"
    assert row["available_time"] == "2026-06-29T01:00:00Z"
    manifest = json.loads((target / "btc_perpetual_bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest["blockers"] == [
        "btc_open_interest_history_not_verified_diagnostic_partial",
        "btc_liquidation_snapshots_missing_diagnostic_only",
    ]
    manual = json.loads(
        (tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert manual["bundle_dir"].endswith("target_90d")


def _write_bar_csv(path: Path, timestamp: str) -> None:
    path.write_text(
        "timestamp,open_time,symbol,open,high,low,close,confirm,source_record_id\n"
        f"{timestamp},{timestamp},BTCUSDT,1,2,1,2,1,test\n",
        encoding="utf-8",
    )


def _write_funding_csv(path: Path, timestamp: str) -> None:
    path.write_text(
        "timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id,instId,realizedRate\n"
        f"{timestamp},{timestamp},BTCUSDT,0.001,2,test,BTC-USDT-SWAP,0.001\n",
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _last_csv_row(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))[-1]
