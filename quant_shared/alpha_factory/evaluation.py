"""Split-scoped signal statistics, not backtest returns or order turnover."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import FactoryError, validate_expression


def validate_panel(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"datetime", "instrument", "open", "high", "low", "close", "volume"}
    if required - set(frame):
        raise FactoryError("panel_missing_columns:" + ",".join(sorted(required - set(frame))))
    result = frame.copy()
    result["datetime"] = pd.to_datetime(result.datetime, utc=True)
    if result[["datetime", "instrument"]].duplicated().any() or result.datetime.isna().any():
        raise FactoryError("duplicate_or_invalid_panel_identity")
    values = result[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
        raise FactoryError("invalid_ohlcv")
    if ((result.high < result[["open", "close", "low"]].max(axis=1)) |
        (result.low > result[["open", "close", "high"]].min(axis=1))).any():
        raise FactoryError("invalid_price_envelope")
    return result.sort_values(["datetime", "instrument"]).set_index(["datetime", "instrument"])


def split_plan(index: pd.MultiIndex, *, horizon: int, delay: int, min_rows=80) -> dict:
    if type(horizon) is not int or type(delay) is not int or horizon < 1 or delay < 1:
        raise FactoryError("invalid_label_offsets")
    calendar = index.get_level_values("datetime").unique().sort_values()
    n = len(calendar)
    boundaries = [0, int(n * .50), int(n * .65), int(n * .80), n]
    gap = horizon + delay + 1
    output = {}
    for name, start, stop in zip(("train", "valid", "selection", "audit"), boundaries[:-1], boundaries[1:]):
        end = stop - gap
        if end - start < min_rows:
            raise FactoryError("insufficient_segment_calendar:" + name)
        output[name] = [calendar[start].isoformat(), calendar[end - 1].isoformat()]
    return {"segments": output, "horizon_bars": horizon, "entry_delay_bars": delay,
        "purge_bars": gap, "calendar_rows": n, "method": "purged_chronological_four_way",
        "label": f"open[t+{horizon + delay}]/open[t+{delay}]-1",
        "test_used_for_generation_or_selection": False}


def segment(value: pd.DataFrame | pd.Series, plan: dict, name: str):
    timestamps = value.index.get_level_values("datetime")
    start, end = map(pd.Timestamp, plan["segments"][name])
    return value.loc[(timestamps >= start) & (timestamps <= end)]


def forward_labels(panel: pd.DataFrame, plan: dict) -> pd.Series:
    # Shift by actual bars, never by wall-clock hours over stock holidays.
    group = panel.open.groupby(level="instrument")
    horizon, delay = plan["horizon_bars"], plan["entry_delay_bars"]
    return (group.shift(-(horizon + delay)) / group.shift(-delay) - 1).rename("label")


def effective_temporal_samples(index: pd.MultiIndex, plan: dict) -> int:
    # Conservative overlap-adjusted time count, not a proof of statistical
    # independence. More securities at the same time do not create more periods.
    return index.get_level_values("datetime").nunique() // (plan["horizon_bars"] + plan["entry_delay_bars"])


def rolling_z(values: pd.Series, window=60) -> pd.Series:
    def one(x):
        mean = x.rolling(window, min_periods=window).mean()
        std = x.rolling(window, min_periods=window).std(ddof=0)
        return ((x - mean) / std.replace(0, np.nan)).clip(-5, 5)
    return values.groupby(level="instrument", group_keys=False).transform(one)


def evaluate_expression(node: dict, primitives: pd.DataFrame) -> pd.Series:
    validate_expression(node, set(primitives))
    def evaluate(expr):
        op = expr["op"]
        if op == "primitive": return primitives[expr["primitive"]]
        if op == "const": return pd.Series(expr["value"], index=primitives.index, dtype=float)
        args = [evaluate(child) for child in expr["args"]]
        if op == "add": return args[0] + args[1]
        if op == "sub": return args[0] - args[1]
        if op == "mul": return args[0] * args[1]
        if op == "safe_ratio": return args[0] / args[1].where(args[1].abs() > 1e-6)
        if op == "gate": return args[0] * (args[1] > 0).where(args[1].notna()).astype(float)
        if op == "clip": return args[0].clip(-5, 5)
        if op == "tanh": return np.tanh(args[0].clip(-20, 20))
        if op == "sign": return np.sign(args[0])
        if op == "signed_power": return np.sign(args[0]) * args[0].abs().clip(upper=25) ** 1.5
        if op == "rolling_z": return rolling_z(args[0], expr["window"])
        raise FactoryError("invalid_expression")
    return evaluate(node).replace([np.inf, -np.inf], np.nan)


def _corr(x, y, method="pearson"):
    if len(x) < 3 or x.nunique() < 2 or y.nunique() < 2: return None
    value = x.corr(y, method=method)
    return float(value) if np.isfinite(value) else None


def signal_metrics(values: pd.Series, labels: pd.Series, mode: str, *, block_size=60) -> dict:
    pair = pd.concat([values.rename("score"), labels.rename("label")], axis=1).replace([np.inf, -np.inf], np.nan)
    total = len(pair)
    pair = pair.dropna()
    result = {"observations": len(pair), "coverage": len(pair) / total if total else 0,
        "metric_mode": mode, "ic": None, "rank_ic": None, "icir": None,
        "factor_signal_turnover": None, "turnover_semantics": "mean_absolute_change_of_tanh_factor_not_order_turnover",
        "pnl": None, "block_count": 0, "positive_block_fraction": None}
    if len(pair) < 30: return result
    blocks = []
    if mode == "cross_sectional":
        for _, rows in pair.groupby(level="datetime"):
            if len(rows) >= 3:
                blocks.append((_corr(rows.score, rows.label), _corr(rows.score, rows.label, "spearman")))
    elif mode == "time_series":
        for _, rows in pair.groupby(level="instrument"):
            for offset in range(0, len(rows), block_size):
                block = rows.iloc[offset:offset + block_size]
                if len(block) >= 30:
                    blocks.append((_corr(block.score, block.label), _corr(block.score, block.label, "spearman")))
    else: raise FactoryError("unknown_metric_mode")
    blocks = [(ic, rank) for ic, rank in blocks if ic is not None and rank is not None]
    if blocks:
        ic = np.array([item[0] for item in blocks]); rank = np.array([item[1] for item in blocks])
        result.update(ic=float(ic.mean()), rank_ic=float(rank.mean()),
            icir=float(rank.mean() / rank.std(ddof=1)) if len(rank) > 1 and rank.std(ddof=1) > 0 else None,
            block_count=len(rank), positive_block_fraction=float((rank > 0).mean()), block_rank_ic=rank.tolist())
    turnover = np.tanh(pair.score).groupby(level="instrument").diff().abs().dropna()
    result["factor_signal_turnover"] = float(turnover.mean()) if len(turnover) else None
    result["mse"] = float(((pair.score - pair.label) ** 2).mean())
    result["zero_forecast_mse"] = float((pair.label ** 2).mean())
    result["direction_hit_rate"] = float((np.sign(pair.score) == np.sign(pair.label)).mean())
    return result


def select_decorrelated(scored: list[dict], values: dict[str, pd.Series], *, maximum: int, threshold=.90):
    selected, rejected = [], []
    for row in sorted(scored, key=lambda x: (-x["fitness"], x["factor_id"])):
        reason = None
        if row["fitness"] <= 0: reason = "insufficient_train_signal"
        elif len(selected) >= maximum: reason = "feature_budget_exhausted"
        else:
            for retained in selected:
                pair = pd.concat([values[row["factor_id"]], values[retained["factor_id"]]], axis=1).dropna()
                if len(pair) < 30: reason = "insufficient_pairwise_coverage"; break
                correlation = _corr(pair.iloc[:, 0], pair.iloc[:, 1])
                if correlation is None or abs(correlation) >= threshold:
                    reason = "correlated_with:" + retained["factor_id"]; break
        if reason: rejected.append({"factor_id": row["factor_id"], "reason": reason})
        else: selected.append(row)
    return selected, rejected


def nomination_gate(selection: dict, audit: dict, *, observed_audit: bool) -> dict:
    reasons = []
    for name, metrics in (("selection", selection), ("audit", audit)):
        if metrics.get("coverage", 0) < .90 or metrics.get("block_count", 0) < 4:
            reasons.append(name + ":insufficient_evidence")
        if metrics.get("rank_ic") is None or metrics["rank_ic"] < .02:
            reasons.append(name + ":rank_ic_below_0.02")
        if metrics.get("positive_block_fraction") is None or metrics["positive_block_fraction"] < .75:
            reasons.append(name + ":unstable_block_ic")
        if not metrics.get("zero_forecast_mse") or metrics.get("mse", float("inf")) >= metrics["zero_forecast_mse"]:
            reasons.append(name + ":no_improvement_over_zero_forecast")
    return {"status": "rejected" if reasons else "exploratory_nomination" if observed_audit else "research_candidate", "blockers": reasons,
        "confirmatory_holdout": not observed_audit,
        "evidence_class": "exploratory_research_only", "trading_promotion": "not_evaluated",
        "required_next_evidence": ["independent_walk_forward", "parameter_stability", "cost_stress",
            "nonzero_fill_ledger_replay", "independent_confirmation"], "rule_version": "research_nomination_v1"}


def hac_p_value(metrics: dict) -> float | None:
    """One-sided exploratory test of mean block Rank IC, Newey-West variance.

    Blocks are chronological, ICIR is not annualized, and this does not certify
    independent trades or replace the untouched confirmation gate.
    """
    from scipy.stats import norm
    values = np.asarray(metrics.get("block_rank_ic", []), dtype=float)
    if len(values) < 4 or not np.isfinite(values).all(): return None
    centered = values - values.mean(); n = len(values)
    lag_count = min(n - 1, max(1, int(n ** .25)))
    variance = float(centered @ centered / n)
    for lag in range(1, lag_count + 1):
        variance += 2 * (1 - lag / (lag_count + 1)) * float(centered[lag:] @ centered[:-lag] / n)
    if variance <= 0: return None
    return float(norm.sf(values.mean() / np.sqrt(variance / n)))


def by_fdr(p_values: list[float | None]) -> list[float | None]:
    # Failed/unknown tests count in family size and can never pass.
    count = len(p_values)
    if not count: return []
    harmonic = sum(1 / i for i in range(1, count + 1))
    ranked = sorted((p, index) for index, p in enumerate(p_values) if p is not None)
    result = [None] * count; bound = 1.0
    for rank in range(len(ranked), 0, -1):
        p, index = ranked[rank - 1]
        bound = min(bound, p * count * harmonic / rank)
        result[index] = min(1.0, bound)
    return result


def purged_selection_folds(index, plan):
    calendar = index.get_level_values("datetime").unique().sort_values()
    start, end = map(pd.Timestamp, plan["segments"]["selection"])
    positions = np.flatnonzero((calendar >= start) & (calendar <= end))
    folds = np.array_split(positions, 4)
    valid_start, valid_end = map(pd.Timestamp, plan["segments"]["valid"])
    valid_length = int(((calendar >= valid_start) & (calendar <= valid_end)).sum())
    gap = plan["purge_bars"]
    output = []
    for positions in folds:
        test_start, test_end = int(positions[0]), int(positions[-1]) - gap
        valid_end = test_start - gap - 1
        valid_start = valid_end - valid_length + 1
        train_end = valid_start - gap - 1
        if test_end - test_start < 30 or train_end < 80: raise FactoryError("insufficient_purged_fold")
        output.append({"train": [calendar[0].isoformat(), calendar[train_end].isoformat()],
            "valid": [calendar[valid_start].isoformat(), calendar[valid_end].isoformat()],
            "test": [calendar[test_start].isoformat(), calendar[test_end].isoformat()]})
    return output
