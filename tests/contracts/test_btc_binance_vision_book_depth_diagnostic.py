from __future__ import annotations

import csv
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_binance_vision_book_depth import build_btc_binance_vision_book_depth_diagnostic


def test_binance_vision_book_depth_fixture_is_diagnostic_not_okx_gate(tmp_path: Path) -> None:
    _write_book_depth_zip(tmp_path / "data/raw_archives/BTCUSDT-bookDepth-2026-05-17.zip")

    report = build_btc_binance_vision_book_depth_diagnostic(
        data_root=tmp_path / "data",
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        execute_network=False,
        start_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
    )

    assert report["row_count"] == 8
    assert report["coverage"]["two_sided_timestamp_count"] == 2
    assert report["execution_gate_interpretation"]["free_public_depth_diagnostic_available"] is True
    assert report["execution_gate_interpretation"]["gate_eligible_for_selected_venue"] is False
    assert report["execution_gate_interpretation"]["depth_aware_slippage_history_verified_for_selected_venue"] is False
    assert "btc_binance_vision_book_depth_cross_venue_not_okx_execution_gate" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert (tmp_path / "out/btc_binance_vision_book_depth_diagnostic_report.json").exists()
    assert (tmp_path / "out/btc_binance_vision_book_depth_safety_status.json").exists()


def test_binance_vision_book_depth_without_network_or_local_rows_is_planned(tmp_path: Path) -> None:
    report = build_btc_binance_vision_book_depth_diagnostic(
        data_root=tmp_path / "data",
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        execute_network=False,
        start_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
        end_date=datetime(2026, 5, 17, tzinfo=timezone.utc).date(),
    )

    assert report["status"] == "planned_no_network_or_local_rows"
    assert report["row_count"] == 0
    assert "btc_binance_vision_book_depth_execute_network_false_or_no_local_archives" in report["blockers"]
    assert report["guardrails"]["private_endpoint_used"] is False
    assert report["guardrails"]["order_endpoint_used"] is False


def _write_book_depth_zip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ["timestamp", "percentage", "depth", "notional"],
        ["2026-05-17 00:00:09", "-5.00", "100.0", "1000000.0"],
        ["2026-05-17 00:00:09", "-1.00", "20.0", "200000.0"],
        ["2026-05-17 00:00:09", "1.00", "22.0", "210000.0"],
        ["2026-05-17 00:00:09", "5.00", "110.0", "1100000.0"],
        ["2026-05-17 00:05:09", "-5.00", "101.0", "1010000.0"],
        ["2026-05-17 00:05:09", "-1.00", "19.0", "190000.0"],
        ["2026-05-17 00:05:09", "1.00", "21.0", "205000.0"],
        ["2026-05-17 00:05:09", "5.00", "108.0", "1080000.0"],
    ]
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, arcname=csv_path.name)
    csv_path.unlink()
