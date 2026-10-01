from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any

import pandas as pd


def _normalize_lineage_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return ""
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if timestamp.time() == datetime.min.time():
        return timestamp.date().isoformat()
    return timestamp.isoformat().replace("+00:00", "Z")


def infer_single_symbol_lineage(
    *,
    source: str,
    symbol: str,
    bar_size: str,
    start: Any,
    end: Any,
) -> dict[str, str]:
    normalized_source = str(source or "").strip().lower()
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_bar_size = str(bar_size or "").strip().lower()
    normalized_start = _normalize_lineage_timestamp(start)
    normalized_end = _normalize_lineage_timestamp(end)
    if not (
        normalized_source
        and normalized_symbol
        and normalized_bar_size
        and normalized_start
        and normalized_end
        and normalized_symbol not in {"*", "ALL"}
        and re.fullmatch(r"[A-Z0-9._-]+", normalized_symbol) is not None
    ):
        return {
            "universe_id": "",
            "universe_source": "",
            "survivorship_bias_risk": "unknown",
        }
    payload = ":".join(
        [
            normalized_source,
            normalized_symbol,
            normalized_bar_size,
            normalized_start,
            normalized_end,
        ]
    )
    lineage_suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return {
        "universe_id": f"single-symbol-{normalized_symbol}-{normalized_bar_size}-{lineage_suffix}",
        "universe_source": (
            "auto_lineage:single_symbol_request:v1:"
            f"{normalized_source}:{normalized_symbol}:{normalized_bar_size}:{normalized_start}:{normalized_end}"
        ),
        "survivorship_bias_risk": "clean",
    }


class MarketDataConnector(ABC):
    vendor: str

    @abstractmethod
    def fetch_bars(self, symbol: str, start: datetime, end: datetime, bar_size: str) -> pd.DataFrame:
        """Fetch historical bars for a symbol.

        Returns a DataFrame with columns:
            timestamp_utc, symbol, open, high, low, close, volume, vwap, trade_count, source, adjusted_flag
        Returns empty DataFrame on error or no data.
        """
        raise NotImplementedError

    def fetch_account(self) -> dict[str, Any]:
        """Fetch account information (broker data sources only).

        Returns an empty dict by default for non-broker connectors.
        """
        return {}

    @classmethod
    def quality_metadata(
        cls,
        *,
        symbol: str,
        start: Any,
        end: Any,
        bar_size: str,
        frame: pd.DataFrame | None = None,
        data_root: str | Path = "data/cleaned",
    ) -> dict[str, Any]:
        metadata = {
            "timezone": "UTC",
            "adjustment_policy": "",
            "corporate_action_adjustment": "",
            "raw_path": "",
            "cleaned_path": "",
            "source_lineage": "",
        }
        metadata.update(
            infer_single_symbol_lineage(
                source=cls.vendor,
                symbol=symbol,
                bar_size=bar_size,
                start=start,
                end=end,
            )
        )
        return metadata

    def supports(self, symbol: str) -> bool:
        """Check whether this connector can provide data for *symbol*."""
        return True
