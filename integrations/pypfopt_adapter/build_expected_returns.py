from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .schemas import (
    PortfolioAdapterConfig,
    expected_returns_path,
    load_portfolio_config,
    now_iso,
    portfolio_run_dir,
    read_score_frame,
    resolve_portfolio_run_id,
    write_frame,
)


def build_expected_returns(
    *,
    score_run_id: str,
    config: PortfolioAdapterConfig,
    portfolio_run_id: str | None = None,
) -> tuple[pd.DataFrame, Path]:
    resolved_run_id = resolve_portfolio_run_id(config, portfolio_run_id)
    portfolio_run_dir(config, resolved_run_id)
    score_frame = read_score_frame(config, score_run_id)
    created_at = now_iso()

    rows: list[dict[str, object]] = []
    for timestamp, group in _iter_rebalance_groups(score_frame, config):
        ordered = group.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True)
        selected = ordered.head(min(config.top_k, len(ordered))).copy()
        if selected.empty:
            continue
        if "rank" in selected.columns:
            selected["source_rank"] = selected["rank"]
        else:
            selected["source_rank"] = pd.NA
        selected_count = len(selected)
        selected["rank"] = range(1, selected_count + 1)
        selected["expected_return"] = _expected_return_proxy(
            selected=selected,
            full_score_frame=score_frame,
            timestamp=pd.Timestamp(timestamp),
            config=config,
        )

        for row in selected.to_dict(orient="records"):
            rows.append(
                {
                    "portfolio_run_id": resolved_run_id,
                    "source_score_run_id": score_run_id,
                    "datetime": timestamp,
                    "symbol": row["symbol"],
                    "score": float(row["score"]),
                    "source_rank": row.get("source_rank"),
                    "rank": int(row["rank"]),
                    "expected_return": float(row["expected_return"]),
                    "method": config.expected_return_method,
                    "selected_count": selected_count,
                    "top_k": config.top_k,
                    "created_at": created_at,
                    "model_id": row.get("model_id", ""),
                    "data_version": row.get("data_version", ""),
                    "universe": row.get("universe", ""),
                    "feature_set": row.get("feature_set", ""),
                    "label": row.get("label", ""),
                }
            )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values(["datetime", "rank", "symbol"]).reset_index(drop=True)

    output_path = expected_returns_path(config, resolved_run_id)
    write_frame(frame, output_path)
    return frame, output_path


def _iter_rebalance_groups(
    score_frame: pd.DataFrame,
    config: PortfolioAdapterConfig,
) -> list[tuple[pd.Timestamp, pd.DataFrame]]:
    working = score_frame.copy()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    if config.rebalance_freq == "daily":
        return [(pd.Timestamp(timestamp), group.copy()) for timestamp, group in working.groupby("datetime", sort=True)]

    unique_dates = pd.Series(sorted(working["datetime"].drop_duplicates()))
    week_key = unique_dates.dt.tz_convert(None).dt.to_period("W-FRI").astype(str)
    weekly_dates = set(unique_dates.groupby(week_key).max().tolist())
    weekly = working[working["datetime"].isin(weekly_dates)].copy()
    return [(pd.Timestamp(timestamp), group.copy()) for timestamp, group in weekly.groupby("datetime", sort=True)]


def _expected_return_proxy(
    *,
    selected: pd.DataFrame,
    full_score_frame: pd.DataFrame,
    timestamp: pd.Timestamp,
    config: PortfolioAdapterConfig,
) -> list[float]:
    if config.expected_return_method == "rank_zscore":
        signal = pd.Series((len(selected) - selected["rank"] + 1).astype(float).to_numpy(), index=selected.index)
        return _bounded_expected_returns(_zscore(signal), config)

    if config.expected_return_method == "score_zscore":
        signal = pd.to_numeric(selected["score"], errors="raise")
        return _bounded_expected_returns(_zscore(signal), config)

    if config.expected_return_method == "forward_return_fit":
        return _forward_return_fit_expected_returns(
            selected=selected,
            full_score_frame=full_score_frame,
            timestamp=timestamp,
            config=config,
        )

    raise ValueError(f"Unsupported expected_return_method: {config.expected_return_method}")


def _zscore(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="raise").astype(float)
    if len(numeric) <= 1:
        return pd.Series([0.0] * len(numeric), index=numeric.index)
    std = float(numeric.std(ddof=0))
    if std <= 0.0:
        return pd.Series([0.0] * len(numeric), index=numeric.index)
    return (numeric - float(numeric.mean())) / std


def _bounded_expected_returns(zscores: pd.Series, config: PortfolioAdapterConfig) -> list[float]:
    midpoint = (config.max_expected_return + config.min_expected_return) / 2.0
    half_spread = (config.max_expected_return - config.min_expected_return) / 2.0
    return [
        float(midpoint + max(-2.0, min(2.0, float(value))) / 2.0 * half_spread)
        for value in zscores.tolist()
    ]


def _forward_return_fit_expected_returns(
    *,
    selected: pd.DataFrame,
    full_score_frame: pd.DataFrame,
    timestamp: pd.Timestamp,
    config: PortfolioAdapterConfig,
) -> list[float]:
    label_column = next(
        (
            name
            for name in ("forward_return", "future_return", "realized_forward_return", "label_return")
            if name in full_score_frame.columns
        ),
        "",
    )
    if not label_column:
        raise ValueError(
            "expected_return_method=forward_return_fit requires a historical forward return column "
            "(forward_return, future_return, realized_forward_return, or label_return)."
        )

    history = full_score_frame.copy()
    history["datetime"] = pd.to_datetime(history["datetime"], utc=True)
    history = history[history["datetime"] < timestamp].copy()
    history["score"] = pd.to_numeric(history["score"], errors="coerce")
    history[label_column] = pd.to_numeric(history[label_column], errors="coerce")
    history = history.dropna(subset=["score", label_column])
    if len(history) < max(3, config.min_observations):
        raise ValueError(
            f"forward_return_fit has only {len(history)} prior observations before {timestamp.isoformat()}; "
            f"need at least {max(3, config.min_observations)}."
        )

    score_var = float(history["score"].var(ddof=0))
    if score_var <= 0.0:
        raise ValueError("forward_return_fit cannot calibrate with zero historical score variance.")
    slope = float(history[["score", label_column]].cov(ddof=0).loc["score", label_column] / score_var)
    intercept = float(history[label_column].mean() - slope * history["score"].mean())
    raw = intercept + slope * pd.to_numeric(selected["score"], errors="raise")
    return [
        float(max(config.min_expected_return, min(config.max_expected_return, value)))
        for value in raw.tolist()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build expected returns from Qlib score artifacts.")
    parser.add_argument("--score-run-id", required=True, help="Qlib score run id under artifacts/qlib_runs/<run_id>/")
    parser.add_argument("--config", required=False, help="Portfolio config yaml path.")
    parser.add_argument("--portfolio-run-id", required=False, help="Optional explicit portfolio run id.")
    args = parser.parse_args()

    config = load_portfolio_config(args.config)
    frame, output_path = build_expected_returns(
        score_run_id=args.score_run_id,
        config=config,
        portfolio_run_id=args.portfolio_run_id,
    )
    print(f"wrote expected returns: {output_path}")
    print(f"rows={len(frame)} dates={frame['datetime'].nunique() if not frame.empty else 0}")


if __name__ == "__main__":
    main()
