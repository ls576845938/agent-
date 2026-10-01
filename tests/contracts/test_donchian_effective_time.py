"""Opening-fill attached protection must use the economic event, not receipt jitter."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_crypto.application.donchian_historical_venue import (
    HistoricalBar,
    HistoricalOfflineVenue,
    ProtectionTriggerAmbiguous,
)


UTC = timezone.utc
OPEN = datetime(2025, 11, 18, 15, tzinfo=UTC)


def _bar(at: datetime, *, opening: bool = False, high: str = "91330", low: str = "91310", mark_open: str = "91325.7", mark_low: str | None = None) -> HistoricalBar:
    mark_high_value = max(Decimal(mark_open), Decimal("92985.6" if opening else high))
    mark_low_value = min(Decimal(mark_open), Decimal(mark_low or ("90973.5" if opening else low)))
    return HistoricalBar(
        event_time_utc=at,
        available_time_utc=at + timedelta(hours=1),
        open=Decimal("91320"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal("91320"),
        mark_open=Decimal(mark_open),
        mark_high=mark_high_value,
        mark_low=mark_low_value,
        mark_close=Decimal("92856.2" if opening else "91320"),
        index_close=Decimal("92904.7" if opening else "91320"),
    )


def _open_short(path: Path, *, receipt_offset_ms: int = 2886, direction: str = "short", delay_after_quote_ms: int = 0) -> HistoricalOfflineVenue:
    venue = HistoricalOfflineVenue(path, now=OPEN + timedelta(milliseconds=receipt_offset_ms))
    venue.advance(completed_bar=_bar(OPEN - timedelta(hours=1)), next_bar_open=Decimal("91320"))
    venue.now += timedelta(milliseconds=delay_after_quote_ms)
    response = venue.submit_order({
        "clOrdId": "original-short-parent",
        "instId": "BTC-USDT-SWAP",
        "side": "sell" if direction == "short" else "buy",
        "posSide": direction,
        "ordType": "limit",
        "px": "91000" if direction == "short" else "92000",
        "sz": "0.01",
        "attachAlgoOrds": [{
            "attachAlgoClOrdId": "original-short-oco",
            "tpTriggerPx": "89444.3" if direction == "short" else "92182.4",
            "tpTriggerPxType": "mark",
            "tpOrdPx": "-1",
            "slTriggerPx": "92182.4" if direction == "short" else "90400",
            "slTriggerPxType": "mark",
            "slOrdPx": "-1",
        }],
    })
    assert response.code == "0"
    assert venue.state["fills"][0]["fillPx"] == ("91315.434" if direction == "short" else "91324.566")
    assert venue.state["fills"][0]["economicEffectiveAtUtc"] == OPEN.isoformat()
    assert venue.state["fills"][0]["economicEffectivePhase"] == "parent_open_fill"
    return venue


def test_real_blocked_bar_attached_short_stop_uses_open_fill_phase(tmp_path: Path) -> None:
    venue = _open_short(tmp_path / "venue.json")
    assert venue.state["algos"][0]["uTime"] == str(int((OPEN + timedelta(milliseconds=2886)).timestamp() * 1000))
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    venue.advance(
        completed_bar=_bar(OPEN, opening=True, high="93000", low="90962.6"),
        next_bar_open=Decimal("92861.4"),
    )
    assert venue.state["position"] == "0"
    assert len(venue.state["fills"]) == 2
    assert venue.state["fills"][-1]["execType"] == "historical_oco_stop_loss"
    assert "effectiveAtUtc" not in venue.state["fills"][-1]
    assert venue.state["fills"][-1]["effectiveTimePolicy"] == "intrabar_time_unknown"
    assert venue.state["fills"][-1]["protectionEconomicEffectiveAtUtc"] == OPEN.isoformat()
    assert venue.state["fills"][-1]["protectionEconomicEffectivePhase"] == "after_parent_open_fill"
    assert venue.state["fills"][-1]["protectionCreatedAtUtc"] == (OPEN + timedelta(milliseconds=2886)).isoformat()


@pytest.mark.parametrize("field,value", [
    ("parentClOrdId", "wrong-parent"),
    ("economicParentOrderId", "wrong-order"),
    ("economicParentFillId", "wrong-fill"),
    ("economicEffectiveBarEventUtc", "2025-11-18T14:00:00+00:00"),
])
def test_tampered_attachment_proof_still_blocks(tmp_path: Path, field: str, value: str) -> None:
    venue = _open_short(tmp_path / "venue.json")
    venue.state["algos"][0][field] = value
    venue._persist()
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    with pytest.raises(ProtectionTriggerAmbiguous):
        venue.advance(completed_bar=_bar(OPEN, opening=True, high="93000", low="90962.6"), next_bar_open=Decimal("92861.4"))
    assert len(venue.state["fills"]) == 1


def test_attached_protection_double_touch_still_blocks(tmp_path: Path) -> None:
    venue = _open_short(tmp_path / "venue.json")
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    bar = _bar(OPEN, opening=True, high="93000", low="88000", mark_low="88000")
    with pytest.raises(ProtectionTriggerAmbiguous, match="double_touch"):
        venue.advance(completed_bar=bar, next_bar_open=Decimal("92861.4"))
    assert len(venue.state["fills"]) == 1


def test_restart_and_repeat_do_not_duplicate_attached_stop(tmp_path: Path) -> None:
    path = tmp_path / "venue.json"
    venue = _open_short(path)
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    bar = _bar(OPEN, opening=True, high="93000", low="90962.6")
    venue.advance(completed_bar=bar, next_bar_open=Decimal("92861.4"))
    expected = deepcopy(venue.state)
    recovered = HistoricalOfflineVenue(path, now=OPEN + timedelta(hours=1, seconds=1))
    recovered.advance(completed_bar=bar, next_bar_open=Decimal("92861.4"))
    assert recovered.state == expected


def test_attached_long_take_uses_same_open_fill_phase(tmp_path: Path) -> None:
    venue = _open_short(tmp_path / "venue.json", direction="long")
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    venue.advance(completed_bar=_bar(OPEN, opening=True, high="93000", low="90962.6"), next_bar_open=Decimal("92861.4"))
    assert venue.state["position"] == "0"
    assert venue.state["fills"][-1]["execType"] == "historical_oco_take_profit"
    assert venue.state["fills"][-1]["protectionEconomicEffectivePhase"] == "after_parent_open_fill"


def test_attached_short_open_gap_stops_at_known_mark_open(tmp_path: Path) -> None:
    venue = _open_short(tmp_path / "venue.json")
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    venue.advance(completed_bar=_bar(OPEN, opening=True, high="93500", low="90962.6", mark_open="93000"), next_bar_open=Decimal("92861.4"))
    assert venue.state["fills"][-1]["fillPx"] == "93000"
    assert venue.state["fills"][-1]["effectivePhase"] == "after_parent_open_fill"
    assert venue.state["fills"][-1]["effectiveAtUtc"] == OPEN.isoformat()


def test_attached_open_gap_with_both_oco_legs_touched_blocks(tmp_path: Path) -> None:
    venue = _open_short(tmp_path / "venue.json")
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    with pytest.raises(ProtectionTriggerAmbiguous, match="double_touch"):
        venue.advance(completed_bar=_bar(OPEN, opening=True, high="93500", low="88000", mark_open="93000", mark_low="88000"), next_bar_open=Decimal("92861.4"))
    assert len(venue.state["fills"]) == 1


@pytest.mark.parametrize("tamper", ["missing_time", "future_time", "quote_wrong_bar", "quote_wrong_price", "quote_wrong_phase", "parent_fill_wrong_price", "parent_order_wrong_attach", "parent_order_wrong_threshold", "stop_threshold", "take_threshold", "stop_type", "take_type", "stop_order_price", "take_order_price", "nan_stop", "infinite_take"])
def test_missing_or_mismatched_source_cannot_claim_open_phase(tmp_path: Path, tamper: str) -> None:
    venue = _open_short(tmp_path / "venue.json")
    algo = venue.state["algos"][0]
    if tamper == "missing_time":
        algo.pop("uTime")
    elif tamper == "future_time":
        algo["uTime"] = str(int((OPEN + timedelta(hours=2)).timestamp() * 1000))
    elif tamper == "quote_wrong_bar":
        venue.state["quote"]["openEventUtc"] = (OPEN - timedelta(hours=1)).isoformat()
    elif tamper == "quote_wrong_price":
        venue.state["quote"]["open"] = "1"
    elif tamper == "quote_wrong_phase":
        venue.state["quote"]["processingPhase"] = "intrabar"
    elif tamper == "parent_fill_wrong_price":
        venue.state["fills"][0]["fillPx"] = "1"
    elif tamper == "parent_order_wrong_attach":
        venue.state["orders"][0]["attachAlgoOrds"] = []
    elif tamper == "parent_order_wrong_threshold":
        venue.state["orders"][0]["attachedHistoricalTerms"][0]["slTriggerPx"] = "92183.4"
    elif tamper == "stop_threshold":
        algo["slTriggerPx"] = "92183.4"
    elif tamper == "take_threshold":
        algo["tpTriggerPx"] = "89445.3"
    elif tamper == "stop_type":
        algo["slTriggerPxType"] = "last"
    elif tamper == "take_type":
        algo["tpTriggerPxType"] = "last"
    elif tamper == "stop_order_price":
        algo["slOrdPx"] = "0"
    elif tamper == "take_order_price":
        algo["tpOrdPx"] = "0"
    elif tamper == "nan_stop":
        algo["slTriggerPx"] = "NaN"
    elif tamper == "infinite_take":
        algo["tpTriggerPx"] = "Infinity"
    venue._persist()
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    with pytest.raises(ProtectionTriggerAmbiguous):
        venue.advance(completed_bar=_bar(OPEN, opening=True, high="93000", low="90962.6"), next_bar_open=Decimal("92861.4"))
    assert len(venue.state["fills"]) == 1


def test_protection_remains_valid_in_later_hour_after_quote_rotates(tmp_path: Path) -> None:
    venue = _open_short(tmp_path / "venue.json")
    venue.now = OPEN + timedelta(hours=1, seconds=1)
    first = _bar(OPEN, high="91330", low="91310")
    venue.advance(completed_bar=first, next_bar_open=Decimal("91320"))
    assert len(venue.state["fills"]) == 1
    venue.now = OPEN + timedelta(hours=2, seconds=1)
    second = _bar(OPEN + timedelta(hours=1), opening=True, high="93000", low="90962.6")
    venue.advance(completed_bar=second, next_bar_open=Decimal("92861.4"))
    assert venue.state["position"] == "0"
    assert len(venue.state["fills"]) == 2
    assert venue.state["fills"][-1]["execType"] == "historical_oco_stop_loss"


def test_late_reuse_of_open_quote_cannot_create_open_phase(tmp_path: Path) -> None:
    with pytest.raises(ProtectionTriggerAmbiguous, match="quote_missing_or_invalid"):
        _open_short(tmp_path / "venue.json", delay_after_quote_ms=30 * 60 * 1000)
    venue = HistoricalOfflineVenue(tmp_path / "venue.json", now=OPEN + timedelta(minutes=30))
    assert venue.state["fills"] == []


def test_late_quote_observation_with_immediate_submit_cannot_claim_open(tmp_path: Path) -> None:
    path = tmp_path / "venue.json"
    with pytest.raises(ProtectionTriggerAmbiguous, match="quote_missing_or_invalid"):
        _open_short(path, receipt_offset_ms=30 * 60 * 1000)
    venue = HistoricalOfflineVenue(path, now=OPEN + timedelta(minutes=30))
    assert venue.state["fills"] == []
    assert venue.state["orders"] == []


def test_frozen_8784_ordinal_processing_boundary_is_accepted(tmp_path: Path) -> None:
    late_source = _open_short(tmp_path / "late-source.json", receipt_offset_ms=1000 + 8784)
    assert len(late_source.state["fills"]) == 1
    late_phase = _open_short(tmp_path / "late-phase.json", receipt_offset_ms=1000, delay_after_quote_ms=8784)
    assert len(late_phase.state["fills"]) == 1


def test_quote_observation_after_ten_second_envelope_blocks_before_fill(tmp_path: Path) -> None:
    path = tmp_path / "venue.json"
    with pytest.raises(ProtectionTriggerAmbiguous, match="quote_missing_or_invalid"):
        _open_short(path, receipt_offset_ms=10001)
    venue = HistoricalOfflineVenue(path, now=OPEN + timedelta(milliseconds=10001))
    assert venue.state["fills"] == []


@pytest.mark.parametrize("field,value", [("bid", "1"), ("ask", "NaN"), ("open", "Infinity"), ("bid", "-1")])
def test_corrupt_open_quote_rejected_before_parent_fill(tmp_path: Path, field: str, value: str) -> None:
    path = tmp_path / "venue.json"
    venue = HistoricalOfflineVenue(path, now=OPEN + timedelta(milliseconds=2886))
    venue.advance(completed_bar=_bar(OPEN - timedelta(hours=1)), next_bar_open=Decimal("91320"))
    venue.state["quote"][field] = value
    venue._persist()
    with pytest.raises(ProtectionTriggerAmbiguous):
        venue.submit_order({
            "clOrdId": "invalid-quote-parent", "instId": "BTC-USDT-SWAP",
            "side": "sell", "posSide": "short", "ordType": "limit", "px": "91000", "sz": "0.01",
            "attachAlgoOrds": [{"attachAlgoClOrdId": "invalid-quote-oco", "tpTriggerPx": "89444.3",
                                "tpTriggerPxType": "mark", "tpOrdPx": "-1", "slTriggerPx": "92182.4",
                                "slTriggerPxType": "mark", "slOrdPx": "-1"}],
        })
    assert venue.state["fills"] == []
    assert venue.state["orders"] == []


def test_modified_source_next_open_rejected_before_parent_fill(tmp_path: Path) -> None:
    path = tmp_path / "venue.json"
    venue = HistoricalOfflineVenue(path, now=OPEN + timedelta(milliseconds=2886))
    venue.advance(completed_bar=_bar(OPEN - timedelta(hours=1)), next_bar_open=Decimal("91320"))
    venue.state["historical_events"][0]["next_open"] = "1"
    venue._persist()
    with pytest.raises(ProtectionTriggerAmbiguous, match="quote_missing_or_invalid"):
        venue.submit_order({
            "clOrdId": "wrong-source-parent", "instId": "BTC-USDT-SWAP",
            "side": "sell", "posSide": "short", "ordType": "limit", "px": "91000", "sz": "0.01",
            "attachAlgoOrds": [{"attachAlgoClOrdId": "wrong-source-oco", "tpTriggerPx": "89444.3",
                                "tpTriggerPxType": "mark", "tpOrdPx": "-1", "slTriggerPx": "92182.4",
                                "slTriggerPxType": "mark", "slOrdPx": "-1"}],
        })
    assert venue.state["orders"] == []
    assert venue.state["fills"] == []
