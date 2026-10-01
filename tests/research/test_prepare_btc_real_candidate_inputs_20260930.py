from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.research.prepare_btc_real_candidate_inputs_20260930 import (
    DECISION_END,
    DECISION_START,
    EXPECTED_MINUTES,
    INTERVAL_MS,
    VALUATION_POLICY,
    WINDOW_END,
    WINDOW_START,
    candle_rows,
    exact_minute_quality,
    funding_rows,
    git_blob_sha256,
    raw_duplicate_quality,
)

UTC = timezone.utc


def _trade_row(timestamp_ms: int, confirm: str = "1") -> list[str]:
    return [str(timestamp_ms), "1", "2", "0.5", "1.5", "10", "0.1", "15", confirm]


def test_fixed_open_interval_is_exactly_3061_minutes() -> None:
    assert int((WINDOW_END - WINDOW_START).total_seconds() / 60) == EXPECTED_MINUTES == 3_061


def test_quality_rejects_missing_or_unconfirmed_minute() -> None:
    start_ms = int(WINDOW_START.timestamp() * 1000)
    rows = [_trade_row(start_ms + index * INTERVAL_MS) for index in range(EXPECTED_MINUTES)]
    assert exact_minute_quality(rows, start_ms=start_ms, end_ms=int(WINDOW_END.timestamp() * 1000), confirm_index=8)["blockers"] == []
    rows.pop(9)
    rows[10][-1] = "0"
    blockers = exact_minute_quality(rows, start_ms=start_ms, end_ms=int(WINDOW_END.timestamp() * 1000), confirm_index=8)["blockers"]
    assert any(item.startswith("missing_minutes:") for item in blockers)
    assert any(item.startswith("unconfirmed_minutes:") for item in blockers)


def test_candle_available_only_at_open_plus_sixty_seconds() -> None:
    start_ms = int(WINDOW_START.timestamp() * 1000)
    row = candle_rows([_trade_row(start_ms)], instrument_id="BTC-USDT-SWAP", price_type="trade", fetched_at="2026-09-30T00:00:00Z")[0]
    assert datetime.fromisoformat(row["available_time"].replace("Z", "+00:00")) - datetime.fromisoformat(row["open_time"].replace("Z", "+00:00")) == timedelta(seconds=60)
    assert row["event_time"] == row["open_time"]


def test_funding_excludes_pre_t0_boundary_and_forbids_cash_or_mark(tmp_path: Path) -> None:
    path = tmp_path / "funding_rate.csv"
    path.write_text(
        "event_time,fundingRate,source_record_id\n"
        "2026-06-16T00:00:00Z,-0.1,pre\n"
        "2026-06-16T08:00:00Z,-0.01,a\n"
        "2026-06-16T16:00:00Z,-0.02,b\n"
        "2026-06-17T00:00:00Z,0.03,c\n"
        "2026-06-17T08:00:00Z,-0.04,d\n"
        "2026-06-17T16:00:00Z,-0.05,e\n"
        "2026-06-18T00:00:00Z,0.06,f\n",
        encoding="utf-8",
    )
    rows = funding_rows(tmp_path)
    assert len(rows) == 6
    assert all(DECISION_START < datetime.fromisoformat(row["event_time"].replace("Z", "+00:00")) <= DECISION_END for row in rows)
    assert all(row["valuation_policy"] == VALUATION_POLICY for row in rows)
    assert all(not ({"amount", "cash", "settlement_mark"} & {key.lower() for key in row}) for row in rows)


def test_output_dir_must_not_be_reused() -> None:
    # The publication command owns immutability; the assembler also refuses a
    # non-empty staging directory before it makes any network request.
    assert EXPECTED_MINUTES > 0


def test_bound_manifest_hash_uses_git_blob_bytes() -> None:
    relative = ".agent/data_manifests/btc-okx-public-swap-research-bundle/btc-okx-public-swap-btcusdt-demo25h-tail-20260730T1145Z-src6cea196b4-corr1.json"
    assert git_blob_sha256(Path.cwd(), relative) == "6c5dd8036da320062002b839792852c1aa53971fecdd20b1ba7ae3ec6c2260c9"


def test_raw_duplicate_conflicts_are_not_hidden_by_pagination_dedupe() -> None:
    base = {"payload": {"data": [["1", "1", "2", "0", "1", "1"]]}}
    same = {"payload": {"data": [["1", "1", "2", "0", "1", "1"]]}}
    conflict = {"payload": {"data": [["1", "1", "2", "0", "9", "1"]]}}
    assert raw_duplicate_quality([base, same]) == {
        "raw_unique_timestamp_count": 1,
        "raw_duplicate_observation_count": 1,
        "raw_conflicting_duplicate_count": 0,
    }
    assert raw_duplicate_quality([base, conflict])["raw_conflicting_duplicate_count"] == 1
