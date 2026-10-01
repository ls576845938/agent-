from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_cn.data.contracts import PITLookaheadError

from .factories import AS_OF, make_record


@pytest.mark.parametrize(
    "field_name",
    ["event_time", "available_time", "ingested_at", "processed_at"],
)
def test_pit_record_rejects_naive_timestamps(field_name: str) -> None:
    with pytest.raises(
        ValueError,
        match=f"^timestamp_must_be_timezone_aware:{field_name}$",
    ):
        make_record(**{field_name: datetime(2025, 1, 2, 3, 0)})


def test_pit_record_normalizes_all_timestamps_to_utc() -> None:
    cst = timezone(timedelta(hours=8))
    record = make_record(
        event_time=datetime(2025, 1, 2, 10, 55, tzinfo=cst),
    )
    assert record.event_time == AS_OF - timedelta(minutes=5)
    assert record.event_time.tzinfo == timezone.utc


def test_pit_visibility_is_inclusive_and_blocks_lookahead() -> None:
    record = make_record(
        available_time=AS_OF,
        ingested_at=AS_OF,
        processed_at=AS_OF,
    )
    with pytest.raises(PITLookaheadError, match="^pit_record_not_available$"):
        record.assert_available(AS_OF - timedelta(microseconds=1))
    record.assert_available(AS_OF)


def test_pit_timestamp_order_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="^pit_event_time_after_available_time$"):
        make_record(event_time=AS_OF, available_time=AS_OF - timedelta(seconds=1))
    with pytest.raises(ValueError, match="^pit_available_time_after_ingested_at$"):
        make_record(available_time=AS_OF, ingested_at=AS_OF - timedelta(seconds=1))
    with pytest.raises(ValueError, match="^pit_ingested_at_after_processed_at$"):
        make_record(ingested_at=AS_OF, processed_at=AS_OF - timedelta(seconds=1))


def test_pit_contract_exposes_identity_lineage_and_visibility_fields() -> None:
    assert {
        "stable_security_id",
        "venue",
        "instrument",
        "board",
        "security_type",
        "state",
        "event_time",
        "available_time",
        "ingested_at",
        "processed_at",
        "source",
        "version",
        "checksum",
    } == set(make_record().to_dict())


@pytest.mark.parametrize("checksum", ["d" * 63, "D" * 64, "g" * 64])
def test_pit_checksum_requires_canonical_sha256(checksum: str) -> None:
    with pytest.raises(
        ValueError,
        match="^checksum_must_be_lowercase_sha256:checksum$",
    ):
        make_record(checksum=checksum)
