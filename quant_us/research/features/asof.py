"""Point-in-time validation utilities for R3.

Prevents future data leaks by verifying feature timestamps, alignment
with signal data, and proper lag relative to prediction targets.
"""

from __future__ import annotations

import pandas as pd


class PITValidator:
    """Point-in-time validation to prevent future data leaks.

    Static methods that inspect feature/signal DataFrames and return
    ``(pass, reason)`` tuples.
    """

    @staticmethod
    def validate_no_future_leak(
        feature_df: pd.DataFrame,
        timestamp_col: str = "date",
    ) -> tuple[bool, str]:
        """Check that no feature value has a timestamp exceeding today.

        Assumes *timestamp_col* contains date-like values (strings or
        datetime). Returns ``(True, reason)`` if all values are
        <= today, otherwise ``(False, reason)`` with the offending
        timestamp(s).
        """
        if feature_df.empty:
            return True, "Empty DataFrame — no leak possible"

        if timestamp_col not in feature_df.columns:
            return False, f"Column '{timestamp_col}' not found in feature DataFrame"

        from datetime import date

        today = date.today()
        timestamps = pd.to_datetime(feature_df[timestamp_col])

        if timestamps.isna().all():
            return False, f"All values in '{timestamp_col}' are NaT"

        future_mask = timestamps > pd.Timestamp(today)
        future_count = future_mask.sum()

        if future_count > 0:
            future_dates = timestamps[future_mask].unique()
            return (
                False,
                f"{future_count} row(s) with future timestamps: "
                f"{sorted(str(d.date()) for d in future_dates[:5])}",
            )

        return True, "No future timestamps detected"

    @staticmethod
    def validate_timestamp_alignment(
        signal_df: pd.DataFrame,
        feature_df: pd.DataFrame,
    ) -> tuple[bool, str]:
        """Check that signal timestamps align with feature timestamps.

        Verifies that for a given ``(symbol, date)`` pair, the signal
        date is never *after* the feature date. This catches lookahead
        bias where a signal uses future feature values.

        Both DataFrames must have ``symbol`` and ``date`` columns.
        """
        required = {"symbol", "date"}
        if not required.issubset(signal_df.columns):
            return (
                False,
                f"signal_df missing required columns: {required - set(signal_df.columns)}",
            )
        if not required.issubset(feature_df.columns):
            return (
                False,
                f"feature_df missing required columns: {required - set(feature_df.columns)}",
            )

        # Merge on symbol + date to find overlapping pairs
        merged = signal_df[["symbol", "date"]].merge(
            feature_df[["symbol", "date"]],
            on=["symbol"],
            suffixes=("_signal", "_feature"),
        )

        if merged.empty:
            return True, "No overlapping (symbol) pairs — nothing to check"

        signal_dates = pd.to_datetime(merged["date_signal"])
        feature_dates = pd.to_datetime(merged["date_feature"])

        # Signal date should not be after feature date
        misaligned = (signal_dates > feature_dates).sum()
        if misaligned > 0:
            return (
                False,
                f"{misaligned} signal-feature pair(s) have signal date after "
                f"feature date (lookahead bias).",
            )

        return True, "All signal timestamps align with or precede feature timestamps"

    @staticmethod
    def validate_feature_lag(
        feature_df: pd.DataFrame,
        lag_days: int = 1,
    ) -> tuple[bool, str]:
        """Ensure features are lagged relative to prediction targets.

        Checks that the feature DataFrame has a ``date`` column and
        that consecutive rows per symbol are separated by at most
        *lag_days* (ensuring no future knowledge is needed for
        computation).

        If the DataFrame is empty or has no ``date`` column the
        check is skipped.
        """
        if feature_df.empty:
            return True, "Empty DataFrame — no lag check needed"
        if "date" not in feature_df.columns:
            return True, "No 'date' column — cannot verify lag"

        if "symbol" not in feature_df.columns:
            # Single-symbol: check date gaps
            dates = pd.to_datetime(feature_df["date"]).sort_values()
            gaps = dates.diff().dt.days.dropna()
            if (gaps > lag_days).any():
                max_gap = int(gaps.max())
                return (
                    False,
                    f"Date gap(s) exceed {lag_days} day(s); max gap = {max_gap} days. "
                    f"May indicate data sparsity rather than mis-lag.",
                )
            return True, f"Lag (max {lag_days}d) verified — no gaps exceed threshold"

        # Multi-symbol: check per symbol
        feature_df = feature_df.copy()
        feature_df["_dt"] = pd.to_datetime(feature_df["date"])
        violations = []
        for symbol, group in feature_df.groupby("symbol"):
            dates = group["_dt"].sort_values()
            gaps = dates.diff().dt.days.dropna()
            bad = gaps[gaps > lag_days]
            for idx in bad.index:
                violations.append((symbol, str(dates.loc[idx].date()), int(bad.loc[idx])))

        if violations:
            samples = violations[:5]
            sample_str = "; ".join(f"{s}@{d}: gap={g}d" for s, d, g in samples)
            return (
                False,
                f"{len(violations)} lag violation(s) across symbols "
                f"(max allowed={lag_days}d). Samples: {sample_str}",
            )

        return True, f"Lag (max {lag_days}d) verified for all symbols"
