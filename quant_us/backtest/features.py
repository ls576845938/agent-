from __future__ import annotations

from datetime import date

import pandas as pd


def feature_map_from_frame(frame: pd.DataFrame) -> dict[date, dict[str, dict[str, float]]]:
    if frame.empty:
        return {}
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"]).dt.date
    working["symbol"] = working["symbol"].astype(str).str.upper()
    output: dict[date, dict[str, dict[str, float]]] = {}
    for row in working.to_dict("records"):
        date_value = row["date"]
        symbol = str(row["symbol"]).upper()
        factor_name = str(row["factor_name"])
        value = row.get("factor_value", row.get("value"))
        if pd.isna(value):
            continue
        output.setdefault(date_value, {}).setdefault(symbol, {})[factor_name] = float(value)
    return output
