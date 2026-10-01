import copy
import pandas as pd
import pytest

from scripts.prepare_donchian_long_input import END, terminal_funding_row
from scripts.prepare_donchian_long_input import funding_numeric_missing
from decimal import Decimal
from io import BytesIO


def test_all_missing_marks_remain_numeric_missing_across_parquet():
    frame = funding_numeric_missing(pd.DataFrame({"markPrice": [None, None]}))
    restored = pd.read_parquet(BytesIO(frame.to_parquet(index=False)))
    assert all(Decimal(str(v)).is_nan() for v in restored.markPrice)


def response():
    return {"payload": {"code": "0", "data": [
        {"instId": "BTC-USDT-SWAP", "fundingTime": str(int(END.timestamp()*1000)),
         "fundingRate": "0.0001", "realizedRate": "0.0001"},
        {"instId": "BTC-USDT-SWAP", "fundingTime": str(int((END-pd.Timedelta(hours=8)).timestamp()*1000)),
         "fundingRate": "0.0002"} ]}, "captured_at": "2026-09-21T00:00:00Z"}


def prior():
    return pd.DataFrame([{"event_time": END-pd.Timedelta(hours=8), "fundingRate": 0.0002}])


def test_exact_terminal_real_rate_and_missing_mark():
    row, count = terminal_funding_row(response(), prior())
    assert count == 1 and row["fundingRate"] == "0.0001"
    assert pd.Timestamp(row["available_time"]) == END
    assert row["markPrice"] is None
    assert row["source_record_id"].endswith(str(int(END.timestamp()*1000)))


@pytest.mark.parametrize("kind", ["missing", "wrong_identity", "duplicate", "nan", "conflict", "api_error"])
def test_boundary_fail_closed(kind):
    r = copy.deepcopy(response())
    if kind == "missing": r["payload"]["data"].pop(0)
    if kind == "wrong_identity": r["payload"]["data"][0]["instId"] = "ETH-USDT-SWAP"
    if kind == "duplicate": r["payload"]["data"].append(r["payload"]["data"][0])
    if kind == "nan": r["payload"]["data"][0]["fundingRate"] = "nan"
    if kind == "conflict": r["payload"]["data"][1]["fundingRate"] = "0.0003"
    if kind == "api_error": r["payload"]["code"] = "500"
    with pytest.raises(ValueError): terminal_funding_row(r, prior())
