from __future__ import annotations

import json
import random
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_GA_FACTOR_MINING_VERSION = "btc_ga_factor_mining_v1"
DEFAULT_MARKET_DB = Path("data/market_data.sqlite")
DEFAULT_DERIVATIVES_ROWS = Path(
    "data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/"
    "derivatives_sentiment_1h.json"
)
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_ga_factor_mining/latest")
DEFAULT_GA_FACTOR_MINING_REPORT = DEFAULT_OUTPUT_ROOT / "ga_factor_mining_report.json"
DEFAULT_GA_FACTOR_DIAGNOSTICS_REPORT = DEFAULT_OUTPUT_ROOT / "ga_factor_diagnostics_report.json"
DEFAULT_GA_CANDIDATE_EXPRESSIONS = DEFAULT_OUTPUT_ROOT / "candidate_factor_expressions.json"
DEFAULT_GA_CANDIDATE_REVIEW_PACKET = DEFAULT_OUTPUT_ROOT / "ga_candidate_review_packet.json"
DEFAULT_GA_CANDIDATE_REVIEW_MARKDOWN = DEFAULT_OUTPUT_ROOT / "ga_candidate_review_packet.md"
DEFAULT_SEED = 20260627

PRIMITIVE_COLUMNS = (
    "return_1h",
    "return_4h",
    "momentum_24h",
    "realized_vol_24h",
    "range_pct",
    "volume_z_24",
    "open_interest_z_24",
    "open_interest_delta_1h",
    "funding_rate",
    "funding_z_24",
    "funding_delta_1h",
    "liquidation_z_24",
    "liquidation_imbalance",
    "long_short_ratio",
    "long_short_z_24",
    "long_short_delta_1h",
)
ALLOWED_OPERATORS = {
    "primitive",
    "const",
    "add",
    "sub",
    "mul",
    "safe_ratio",
    "clip",
    "tanh",
    "sign",
    "rolling_z",
    "gate",
}
UNARY_OPERATORS = ("clip", "tanh", "sign", "rolling_z")
BINARY_OPERATORS = ("add", "sub", "mul", "safe_ratio", "gate")
COST_SCENARIOS = {
    "base": {"fee_bps": 5.0, "slippage_bps": 4.0},
    "fees_2x": {"fee_bps": 10.0, "slippage_bps": 4.0},
    "slippage_2x": {"fee_bps": 5.0, "slippage_bps": 8.0},
    "costs_2x": {"fee_bps": 10.0, "slippage_bps": 8.0},
}
DERIVATIVE_VALUE_FIELD_ALIASES = {
    "open_interest_usd": (
        "open_interest_usd",
        "sumOpenInterestValue",
        "sum_open_interest_value",
        "openInterestUsd",
        "open_interest_value_usd",
        "open_interest_value",
        "oiUsd",
    ),
    "funding_rate": (
        "funding_rate",
        "fundingRate",
        "lastFundingRate",
        "last_funding_rate",
        "funding",
    ),
    "long_liquidation_usd": (
        "long_liquidation_usd",
        "longLiquidationUsd",
        "long_liq_usd",
        "long_liquidation_value_usd",
    ),
    "short_liquidation_usd": (
        "short_liquidation_usd",
        "shortLiquidationUsd",
        "short_liq_usd",
        "short_liquidation_value_usd",
    ),
    "long_short_ratio": (
        "long_short_ratio",
        "longShortRatio",
        "long_short_ratio_1h",
        "global_long_short_ratio",
        "long_short_account_ratio",
    ),
}


class GAFactorMiningError(ValueError):
    pass


class DSLValidationError(GAFactorMiningError):
    pass


@dataclass(frozen=True)
class FactorExpression:
    op: str
    args: tuple["FactorExpression", ...] = ()
    primitive: str = ""
    value: float | None = None
    window: int = 24

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"op": self.op}
        if self.primitive:
            payload["primitive"] = self.primitive
        if self.value is not None:
            payload["value"] = self.value
        if self.op == "rolling_z":
            payload["window"] = self.window
        if self.args:
            payload["args"] = [arg.to_dict() for arg in self.args]
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FactorExpression":
        args = tuple(cls.from_mapping(item) for item in payload.get("args", []) if isinstance(item, Mapping))
        return cls(
            op=str(payload.get("op") or ""),
            args=args,
            primitive=str(payload.get("primitive") or ""),
            value=_float_or_none(payload.get("value")),
            window=int(payload.get("window") or 24),
        )

    @property
    def signature(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def expression_hash(self) -> str:
        return stable_payload_hash(self.to_dict())[:16]


@dataclass(frozen=True)
class WalkForwardSplit:
    fold_id: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    embargo_hours: int

    def to_dict(self, index: pd.DatetimeIndex | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload["train_rows"] = max(0, self.train_end - self.train_start)
        payload["validation_rows"] = max(0, self.validation_end - self.validation_start)
        if index is not None and len(index):
            payload.update(
                {
                    "train_start_time": index[self.train_start].isoformat(),
                    "train_end_time": index[self.train_end - 1].isoformat(),
                    "validation_start_time": index[self.validation_start].isoformat(),
                    "validation_end_time": index[self.validation_end - 1].isoformat(),
                }
            )
        return payload


@dataclass(frozen=True)
class FactorMetrics:
    rank_ic: float
    profit_factor: float
    total_return: float
    max_drawdown: float
    turnover: float
    exposure: float
    hit_rate: float
    observations: int
    threshold: float
    direction: int
    cost_bps: float
    funding_cost_approx: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateEvaluation:
    expression: FactorExpression
    fold_id: int
    train_metrics: FactorMetrics
    validation_metrics: FactorMetrics
    train_fitness: float
    validation_fitness: float
    complexity: int
    depth: int
    cost_stress: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": f"btc_ga_{self.expression.expression_hash}_fold{self.fold_id}",
            "expression": self.expression.to_dict(),
            "expression_hash": self.expression.expression_hash,
            "fold_id": self.fold_id,
            "train_metrics": self.train_metrics.to_dict(),
            "validation_metrics": self.validation_metrics.to_dict(),
            "train_fitness": self.train_fitness,
            "validation_fitness": self.validation_fitness,
            "complexity": self.complexity,
            "depth": self.depth,
            "cost_stress": self.cost_stress,
            "scope": "research_only_expression",
            "paper_candidate_generated": False,
            "live_enabled": False,
        }


def primitive(name: str) -> FactorExpression:
    return FactorExpression(op="primitive", primitive=name)


def const(value: float) -> FactorExpression:
    return FactorExpression(op="const", value=float(value))


def load_market_klines(
    *,
    db_path: Path = DEFAULT_MARKET_DB,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    lookback_hours: int = 720,
    extra_history_hours: int = 240,
    decision_time: datetime | None = None,
) -> pd.DataFrame:
    if not db_path.exists():
        raise GAFactorMiningError(f"market db missing: {db_path}")
    cutoff_ms = _to_ms(decision_time) if decision_time is not None else None
    limit = max(lookback_hours + extra_history_hours + 16, 200)
    query = (
        "SELECT open_time AS timestamp, open, high, low, close, volume, "
        "quote_volume, trade_count, taker_buy_base_volume, taker_buy_quote_volume "
        "FROM market_klines WHERE symbol = ? AND interval = ? "
    )
    params: list[Any] = [symbol.upper(), interval]
    if cutoff_ms is not None:
        query += "AND open_time_ms <= ? "
        params.append(cutoff_ms)
    query += "ORDER BY open_time_ms DESC LIMIT ?"
    params.append(limit)
    with sqlite3.connect(str(db_path)) as connection:
        frame = pd.read_sql_query(query, connection, params=params)
    if frame.empty:
        raise GAFactorMiningError("no BTC market rows found for GA factor mining")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").set_index("timestamp")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    frame = frame[(frame["open"] > 0) & (frame["high"] >= frame["low"]) & (frame["close"] > 0)]
    return frame


def load_derivatives_rows(path: Path = DEFAULT_DERIVATIVES_ROWS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        return [dict(row) for row in payload["rows"] if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    return []


def filter_visible_derivative_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    decision_time: datetime,
) -> list[dict[str, Any]]:
    decision = _ensure_utc(decision_time)
    visible: list[dict[str, Any]] = []
    for row in rows:
        try:
            event_time = _parse_utc(row.get("event_time"))
            available_time = _parse_utc(row.get("available_time"))
        except (TypeError, ValueError):
            continue
        if event_time <= decision and available_time <= decision:
            visible.append(dict(row))
    return sorted(visible, key=lambda item: str(item.get("event_time")))


def build_research_frame(
    *,
    market_frame: pd.DataFrame,
    derivative_rows: Sequence[Mapping[str, Any]],
    decision_time: datetime,
    label_horizons: Sequence[int] = (1, 4, 8),
) -> tuple[pd.DataFrame, dict[str, Any]]:
    decision = _ensure_utc(decision_time)
    market = market_frame.copy()
    market.index = pd.to_datetime(market.index, utc=True)
    market = market.loc[market.index <= decision].sort_index()
    market = market[~market.index.duplicated(keep="last")]
    visible_rows = filter_visible_derivative_rows(derivative_rows, decision_time=decision)
    derivatives = _derivative_frame(visible_rows)
    merged = market.join(derivatives, how="left")
    features = _add_feature_columns(merged)
    for horizon in label_horizons:
        features[f"forward_return_{horizon}h"] = features["close"].shift(-int(horizon)) / features["close"] - 1.0
    max_horizon = max(int(item) for item in label_horizons)
    features["label_end_time"] = features.index + pd.to_timedelta(max_horizon, unit="h")
    features = features.loc[features["label_end_time"] <= decision]
    required = ["forward_return_4h", "close", "volume"]
    features = features.dropna(subset=required)
    derivative_value_fields = _derivative_value_fields()
    overlap_index = market.index.intersection(derivatives.index) if len(derivatives) else pd.DatetimeIndex([], tz="UTC")
    joined_counts = _frame_derivative_field_non_null_counts(features)
    coverage = {
        "market_rows": int(len(market)),
        "market_start_time": market.index[0].isoformat() if len(market) else None,
        "market_end_time": market.index[-1].isoformat() if len(market) else None,
        "derivatives_total_rows": int(len(derivative_rows)),
        "derivatives_visible_rows": int(len(visible_rows)),
        "derivatives_visible_start_time": derivatives.index[0].isoformat() if len(derivatives) else None,
        "derivatives_visible_end_time": derivatives.index[-1].isoformat() if len(derivatives) else None,
        "derivatives_market_overlap_rows": int(len(overlap_index)),
        "derivatives_market_overlap_start_time": overlap_index[0].isoformat() if len(overlap_index) else None,
        "derivatives_market_overlap_end_time": overlap_index[-1].isoformat() if len(overlap_index) else None,
        "derivatives_feature_rows_after_label_drop": int(features[list(derivative_value_fields)].notna().any(axis=1).sum())
        if len(features)
        else 0,
        "merged_rows": int(len(features)),
        "decision_time": decision.isoformat(),
        "field_non_null_counts": joined_counts,
        "field_non_null_counts_raw_visible": _derivative_raw_non_null_counts(visible_rows),
        "field_non_null_counts_after_join": joined_counts,
        "derivatives_alignment_status": _derivatives_alignment_status(
            visible_rows=len(visible_rows),
            raw_counts=_derivative_raw_non_null_counts(visible_rows),
            overlap_rows=len(overlap_index),
            joined_counts=joined_counts,
        ),
        "label_horizons": list(label_horizons),
        "max_label_horizon_hours": max_horizon,
        "lookahead_policy": "features use event_time/available_time <= decision_time; labels require label_end_time <= decision_time",
    }
    return features, coverage


def rolling_zscore(series: pd.Series, window: int = 24) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    window = max(2, int(window))
    mean = values.rolling(window, min_periods=max(2, window // 3)).mean()
    std = values.rolling(window, min_periods=max(2, window // 3)).std(ddof=0)
    return ((values - mean) / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def validate_expression(expr: FactorExpression, *, max_depth: int = 4, max_complexity: int = 8) -> None:
    if expr.op not in ALLOWED_OPERATORS:
        raise DSLValidationError(f"operator_not_allowed:{expr.op}")
    if expression_depth(expr) > max_depth:
        raise DSLValidationError("expression_depth_exceeds_limit")
    if expression_complexity(expr) > max_complexity:
        raise DSLValidationError("expression_complexity_exceeds_limit")
    if expr.op == "primitive":
        if expr.primitive not in PRIMITIVE_COLUMNS:
            raise DSLValidationError(f"primitive_not_allowed:{expr.primitive}")
        return
    if expr.op == "const":
        if expr.value is None:
            raise DSLValidationError("const_value_missing")
        return
    expected = 1 if expr.op in UNARY_OPERATORS else 2
    if len(expr.args) != expected:
        raise DSLValidationError(f"operator_arg_count_invalid:{expr.op}")
    for arg in expr.args:
        validate_expression(arg, max_depth=max_depth, max_complexity=max_complexity)


def evaluate_expression(
    expr: FactorExpression | Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    max_depth: int = 4,
    max_complexity: int = 8,
) -> pd.Series:
    node = FactorExpression.from_mapping(expr) if isinstance(expr, Mapping) else expr
    validate_expression(node, max_depth=max_depth, max_complexity=max_complexity)
    return _evaluate_expression_node(node, frame).replace([np.inf, -np.inf], np.nan)


def build_walk_forward_splits(
    row_count: int,
    *,
    fold_count: int = 4,
    embargo_hours: int = 4,
    min_train_rows: int = 120,
    min_validation_rows: int = 48,
) -> list[WalkForwardSplit]:
    if row_count <= min_train_rows + min_validation_rows + embargo_hours:
        return []
    validation_rows = max(min_validation_rows, row_count // (fold_count + 2))
    splits: list[WalkForwardSplit] = []
    for fold in range(fold_count):
        validation_start = row_count - validation_rows * (fold_count - fold)
        validation_end = validation_start + validation_rows
        train_end = max(0, validation_start - embargo_hours)
        if train_end < min_train_rows or validation_start < 0 or validation_end > row_count:
            continue
        splits.append(
            WalkForwardSplit(
                fold_id=fold + 1,
                train_start=0,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                embargo_hours=embargo_hours,
            )
        )
    return splits


def run_btc_ga_factor_mining(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    lookback_hours: int = 720,
    seed: int = DEFAULT_SEED,
    population_size: int = 64,
    generations: int = 20,
    fold_count: int = 4,
    embargo_hours: int = 4,
    confirmatory_holdout_hours: int = 0,
    max_depth: int = 4,
    max_complexity: int = 8,
    max_candidates: int = 12,
    decision_time: datetime | None = None,
    market_frame: pd.DataFrame | None = None,
    derivative_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    rows = list(derivative_rows) if derivative_rows is not None else load_derivatives_rows(derivatives_rows_path)
    decision = decision_time or _default_decision_time(rows)
    market = (
        market_frame.copy()
        if market_frame is not None
        else load_market_klines(db_path=market_db_path, lookback_hours=lookback_hours, decision_time=decision)
    )
    frame, coverage = build_research_frame(market_frame=market, derivative_rows=rows, decision_time=decision)
    if lookback_hours > 0:
        frame = frame.tail(int(lookback_hours)).copy()
        coverage["merged_rows_after_lookback"] = int(len(frame))
        coverage["field_non_null_counts_after_lookback"] = _frame_derivative_field_non_null_counts(frame)
        coverage["derivatives_feature_rows_after_lookback"] = (
            int(frame[list(_derivative_value_fields())].notna().any(axis=1).sum()) if len(frame) else 0
        )
        coverage["derivatives_alignment_status_after_lookback"] = _derivatives_alignment_status(
            visible_rows=int(coverage.get("derivatives_visible_rows", 0)),
            raw_counts=_mapping(coverage.get("field_non_null_counts_raw_visible")),
            overlap_rows=int(coverage.get("derivatives_market_overlap_rows", 0)),
            joined_counts=_mapping(coverage.get("field_non_null_counts_after_lookback")),
        )
    holdout_hours = max(0, int(confirmatory_holdout_hours))
    selection_frame = frame
    holdout_frame = frame.iloc[0:0].copy()
    if holdout_hours > 0 and len(frame) > holdout_hours + 200:
        holdout_frame = frame.tail(holdout_hours).copy()
        selection_frame = frame.iloc[:-holdout_hours].copy()
    coverage["ga_selection_rows"] = int(len(selection_frame))
    coverage["confirmatory_holdout_requested_hours"] = holdout_hours
    coverage["confirmatory_holdout_rows"] = int(len(holdout_frame))
    coverage["confirmatory_holdout_start_time"] = holdout_frame.index[0].isoformat() if len(holdout_frame) else None
    coverage["confirmatory_holdout_end_time"] = holdout_frame.index[-1].isoformat() if len(holdout_frame) else None
    splits = build_walk_forward_splits(len(selection_frame), fold_count=fold_count, embargo_hours=embargo_hours)
    rng = random.Random(int(seed))
    blockers: list[str] = []
    warnings = [
        "btc_ga_factor_mining_sample_short_research_only",
        "btc_ga_factor_mining_funding_cost_is_hourly_research_approximation",
    ]
    if len(frame) < 200:
        blockers.append("btc_ga_factor_mining_insufficient_rows")
    if holdout_hours > 0 and len(holdout_frame) < min(48, holdout_hours):
        blockers.append("btc_ga_factor_mining_confirmatory_holdout_insufficient_rows")
    if len(splits) < fold_count:
        blockers.append("btc_ga_factor_mining_insufficient_walk_forward_folds")
    alignment_status = str(
        coverage.get("derivatives_alignment_status_after_lookback")
        or coverage.get("derivatives_alignment_status")
        or ""
    )
    if alignment_status != "value_fields_present":
        blockers.append(f"btc_ga_factor_mining_derivatives_alignment_{alignment_status or 'unknown'}")
    candidates: list[CandidateEvaluation] = []
    trial_count = 0
    rejected_count = 0
    if not blockers:
        for split in splits:
            fold_result = _evolve_fold(
                frame=selection_frame,
                split=split,
                rng=rng,
                population_size=population_size,
                generations=generations,
                max_depth=max_depth,
                max_complexity=max_complexity,
            )
            candidates.extend(fold_result["candidates"])
            trial_count += int(fold_result["trial_count"])
            rejected_count += int(fold_result["rejected_count"])
    selected = _select_unique_candidates(candidates, max_candidates=max_candidates)
    report_payload = _build_report_payload(
        frame=selection_frame if len(selection_frame) else frame,
        candidates=selected,
        all_candidate_count=len(candidates),
        coverage=coverage,
        splits=splits,
        seed=seed,
        population_size=population_size,
        generations=generations,
        trial_count=trial_count,
        rejected_count=rejected_count,
        blockers=blockers,
    )
    report_payload["confirmatory_holdout"] = _confirmatory_holdout_report(
        selected,
        selection_frame=selection_frame,
        holdout_frame=holdout_frame,
        requested_hours=holdout_hours,
        max_depth=max_depth,
        max_complexity=max_complexity,
    )
    report_payload["funding_timestamp_cost_audit"] = _funding_timestamp_cost_audit(rows, selected)
    report = apply_btc_artifact_schema(
        report_payload,
        decision="research_only_expression_review",
        generated_at_utc=generated_at,
        as_of_utc=decision,
        blockers=blockers,
        warnings=warnings,
        input_hashes={
            "market_frame": stable_payload_hash(_frame_hash_payload(frame, ["open", "high", "low", "close", "volume"])),
            "derivatives_rows": stable_payload_hash({"rows": rows[:2000]}),
            "ga_config": stable_payload_hash(
                {
                    "seed": seed,
                    "population_size": population_size,
                    "generations": generations,
                    "fold_count": fold_count,
                    "embargo_hours": embargo_hours,
                    "confirmatory_holdout_hours": holdout_hours,
                    "max_depth": max_depth,
                    "max_complexity": max_complexity,
                }
            ),
        },
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / "ga_factor_mining_report.json", report)
    _write_json(
        output_root / "candidate_factor_expressions.json",
        {
            "schema_version": "btc_ga_candidate_factor_expressions_v1",
            "run_id": report["run_id"],
            "generated_at": report["generated_at"],
            "scope": "research_only_expression",
            "candidate_count": len(selected),
            "candidates": [candidate.to_dict() for candidate in selected],
            "paper_candidate_generated": False,
            "live_enabled": False,
        },
    )
    _write_json(output_root / "paper_live_safety_status.json", _paper_live_safety_status(report))
    return report


def build_btc_ga_factor_diagnostics_report(
    ga_report: Mapping[str, Any] | None,
    *,
    source_report_path: Path | str | None = None,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    source = dict(ga_report or {})
    blockers: list[str] = []
    warnings = ["btc_ga_factor_diagnostics_research_only_no_paper_or_live_unlock"]
    if not source:
        blockers.append("btc_ga_factor_mining_report_missing")
    elif source.get("schema_version") != "btc_ga_factor_mining_report_v1":
        blockers.append("btc_ga_factor_mining_report_schema_unexpected")
    source_candidates = _mapping_rows(source.get("top_candidates"))
    ga_config = _mapping(source.get("ga_config"))
    coverage = _mapping(source.get("data_coverage"))
    walk_forward = _mapping(source.get("walk_forward"))
    oos_stability = _mapping(walk_forward.get("oos_stability"))
    source_blockers = [str(item) for item in source.get("blockers", [])] if isinstance(source.get("blockers"), list) else []
    as_of = _report_datetime(source.get("as_of_utc") or coverage.get("decision_time"), default=generated_at)
    diagnostic_summary = _ga_diagnostic_summary(
        source=source,
        candidates=source_candidates,
        ga_config=ga_config,
        coverage=coverage,
        oos_stability=oos_stability,
        source_blockers=source_blockers,
    )
    payload = {
        "schema_version": "btc_ga_factor_diagnostics_report_v1",
        "ga_factor_mining_version": BTC_GA_FACTOR_MINING_VERSION,
        "status": "blocked" if blockers else "complete",
        "asset": "btc",
        "symbol": str(source.get("symbol") or "BTCUSDT"),
        "timeframe": str(source.get("timeframe") or "1h"),
        "scope": "research_only_ga_factor_failure_diagnostics",
        "source_report": {
            "path": str(source_report_path).replace("\\", "/") if source_report_path is not None else None,
            "run_id": source.get("run_id"),
            "status": source.get("status"),
            "decision": source.get("decision"),
            "artifact_hash": source.get("artifact_hash"),
            "selected_candidate_count": _int_or_zero(ga_config.get("selected_candidate_count")),
            "candidate_count": _int_or_zero(ga_config.get("candidate_count")),
            "trial_count": _int_or_zero(ga_config.get("trial_count")),
            "rejected_count": _int_or_zero(ga_config.get("rejected_count")),
            "source_blockers": source_blockers,
        },
        "data_diagnostics": _ga_data_diagnostics(coverage),
        "diagnostic_summary": diagnostic_summary,
        "fold_diagnostics": _ga_fold_diagnostics(source_candidates, oos_stability),
        "candidate_diagnostics": _ga_candidate_diagnostics(source_candidates),
        "cost_diagnostics": _ga_cost_diagnostics(source_candidates),
        "primitive_usage": _ga_primitive_usage(source_candidates),
        "recommended_next_actions": _ga_recommended_next_actions(diagnostic_summary),
        "gate": {
            "current_ga_batch_decision": "reject_current_ga_batch"
            if diagnostic_summary["failure_reasons"]
            else "research_only_review_complete",
            "paper_candidate_recommendation": "reject_current_ga_batch",
            "next_allowed_state": "research_only_retry_after_diagnostics",
            "paper_or_live_unlock_allowed": False,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "promotion": {
            "recommendation": "research_only_ga_factor_failure_diagnostics",
            "paper_candidate_generated": False,
            "paper_queue_status": "LOCKED",
            "paper_auto_start": False,
            "live_status": "FROZEN",
            "live_enabled": False,
        },
        "safety": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "paper_queue_write_allowed": False,
            "real_orders_created": False,
            "strategy_skeleton_generated": False,
        },
        "code_commit": _git_commit_hash(),
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="research_only_ga_factor_failure_diagnostics",
        generated_at_utc=generated_at,
        as_of_utc=as_of,
        blockers=blockers,
        warnings=warnings,
        input_hashes={
            "source_ga_factor_mining_report": stable_payload_hash(source),
        },
    )


def write_btc_ga_factor_diagnostics_report(
    *,
    source_report_path: Path = DEFAULT_GA_FACTOR_MINING_REPORT,
    output_path: Path = DEFAULT_GA_FACTOR_DIAGNOSTICS_REPORT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] | None
    if source_report_path.exists():
        source = json.loads(source_report_path.read_text(encoding="utf-8"))
        if not isinstance(source, Mapping):
            source = None
    else:
        source = None
    report = build_btc_ga_factor_diagnostics_report(
        source,
        source_report_path=source_report_path,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    return report


def build_btc_ga_candidate_review_packet(
    ga_report: Mapping[str, Any] | None,
    candidate_payload: Mapping[str, Any] | None = None,
    *,
    source_report_path: Path | str | None = None,
    candidate_path: Path | str | None = None,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    source = dict(ga_report or {})
    candidate_source = dict(candidate_payload or {})
    candidates = _mapping_rows(candidate_source.get("candidates")) or _mapping_rows(source.get("top_candidates"))
    coverage = _mapping(source.get("data_coverage"))
    ga_config = _mapping(source.get("ga_config"))
    walk_forward = _mapping(source.get("walk_forward"))
    oos_stability = _mapping(walk_forward.get("oos_stability"))
    source_blockers = [str(item) for item in source.get("blockers", [])] if isinstance(source.get("blockers"), list) else []

    blockers: list[str] = []
    warnings = [
        "btc_ga_candidate_review_packet_research_only_no_paper_or_live_unlock",
        "btc_ga_candidate_review_packet_short_sample_requires_extended_history",
    ]
    if not source:
        blockers.append("btc_ga_factor_mining_report_missing")
    elif source.get("schema_version") != "btc_ga_factor_mining_report_v1":
        blockers.append("btc_ga_factor_mining_report_schema_unexpected")
    if source_blockers:
        blockers.append("btc_ga_factor_mining_report_has_blockers")
    if candidate_payload is not None and candidate_source.get("schema_version") != "btc_ga_candidate_factor_expressions_v1":
        blockers.append("btc_ga_candidate_expressions_schema_unexpected")
    if not candidates:
        blockers.append("btc_ga_candidate_review_no_candidates")

    scenario_names = _review_cost_scenario_names(candidates)
    candidate_reviews = [
        _btc_ga_candidate_review_row(candidate, rank=index + 1, scenario_names=scenario_names)
        for index, candidate in enumerate(candidates)
    ]
    review_summary = _btc_ga_review_summary(candidate_reviews)
    manual_review_questions = _btc_ga_manual_review_questions(candidate_reviews)
    recommended_next_actions = _btc_ga_review_recommended_actions(candidate_reviews, blockers)
    as_of = _report_datetime(source.get("as_of_utc") or coverage.get("decision_time"), default=generated_at)
    packet_decision = "blocked" if blockers else "research_only_manual_review_required"
    payload = {
        "schema_version": "btc_ga_candidate_review_packet_v1",
        "ga_factor_mining_version": BTC_GA_FACTOR_MINING_VERSION,
        "status": "blocked" if blockers else "complete",
        "asset": "btc",
        "symbol": str(source.get("symbol") or "BTCUSDT"),
        "timeframe": str(source.get("timeframe") or "1h"),
        "scope": "research_only_candidate_review_packet",
        "source_report": {
            "path": str(source_report_path).replace("\\", "/") if source_report_path is not None else None,
            "candidate_path": str(candidate_path).replace("\\", "/") if candidate_path is not None else None,
            "run_id": source.get("run_id") or candidate_source.get("run_id"),
            "status": source.get("status"),
            "decision": source.get("decision"),
            "artifact_hash": source.get("artifact_hash"),
            "code_commit": source.get("code_commit"),
            "selected_candidate_count": _int_or_zero(
                ga_config.get("selected_candidate_count") or candidate_source.get("candidate_count")
            ),
            "candidate_count": _int_or_zero(ga_config.get("candidate_count")),
            "trial_count": _int_or_zero(ga_config.get("trial_count")),
            "rejected_count": _int_or_zero(ga_config.get("rejected_count")),
            "source_blockers": source_blockers,
        },
        "data_context": {
            "lookback_hours": _int_or_zero(coverage.get("merged_rows_after_lookback"))
            or _int_or_zero(coverage.get("derivatives_market_overlap_rows")),
            "market_rows": _int_or_zero(coverage.get("market_rows")),
            "market_start_time": coverage.get("market_start_time"),
            "market_end_time": coverage.get("market_end_time"),
            "derivatives_visible_start_time": coverage.get("derivatives_visible_start_time"),
            "derivatives_visible_end_time": coverage.get("derivatives_visible_end_time"),
            "derivatives_market_overlap_rows": _int_or_zero(coverage.get("derivatives_market_overlap_rows")),
            "derivatives_alignment_status": coverage.get("derivatives_alignment_status_after_lookback")
            or coverage.get("derivatives_alignment_status"),
            "field_non_null_counts_after_lookback": _normalize_derivative_counts(
                _mapping(
                    coverage.get("field_non_null_counts_after_lookback")
                    or coverage.get("field_non_null_counts_after_join")
                    or coverage.get("field_non_null_counts")
                )
            ),
            "lookahead_policy": coverage.get("lookahead_policy"),
            "sample_short": True,
        },
        "validation_context": {
            "method": walk_forward.get("method"),
            "fold_count": _int_or_zero(walk_forward.get("fold_count") or oos_stability.get("fold_count")),
            "embargo_hours": _int_or_zero(walk_forward.get("embargo_hours")),
            "oos_pass_rate": round(_float_value(oos_stability.get("pass_rate")), 6),
            "median_validation_profit_factor": round(_float_value(oos_stability.get("median_validation_pf")), 6),
            "cost_scenarios": scenario_names,
        },
        "confirmatory_holdout_summary": _btc_ga_review_holdout_summary(_mapping(source.get("confirmatory_holdout"))),
        "review_summary": review_summary,
        "logic_family_summary": _btc_ga_logic_family_summary(candidate_reviews),
        "candidate_reviews": candidate_reviews,
        "manual_review_questions": manual_review_questions,
        "manual_review_questions_zh": [_question_label_zh(question) for question in manual_review_questions],
        "recommended_next_actions": recommended_next_actions,
        "recommended_next_actions_zh": [_action_label_zh(action) for action in recommended_next_actions],
        "gate": {
            "current_packet_decision": packet_decision,
            "paper_candidate_recommendation": "defer_until_extended_research_and_manual_review",
            "next_allowed_state": "extended_research_only",
            "paper_candidate_generated": False,
            "paper_queue_write_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "live_unlock_allowed": False,
        },
        "promotion": {
            "recommendation": "research_only_candidate_review_packet",
            "paper_candidate_generated": False,
            "paper_queue_status": "LOCKED",
            "paper_auto_start": False,
            "live_status": "FROZEN",
            "live_enabled": False,
        },
        "safety": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "paper_queue_write_allowed": False,
            "real_orders_created": False,
            "strategy_skeleton_generated": False,
        },
        "code_commit": _git_commit_hash(),
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="research_only_candidate_review_packet",
        generated_at_utc=generated_at,
        as_of_utc=as_of,
        blockers=blockers,
        warnings=warnings,
        input_hashes={
            "source_ga_factor_mining_report": stable_payload_hash(source),
            "candidate_factor_expressions": stable_payload_hash(candidate_source),
        },
    )


def write_btc_ga_candidate_review_packet(
    *,
    source_report_path: Path = DEFAULT_GA_FACTOR_MINING_REPORT,
    candidate_path: Path = DEFAULT_GA_CANDIDATE_EXPRESSIONS,
    output_path: Path = DEFAULT_GA_CANDIDATE_REVIEW_PACKET,
    markdown_path: Path | None = DEFAULT_GA_CANDIDATE_REVIEW_MARKDOWN,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    source = _read_json_mapping(source_report_path)
    candidates = _read_json_mapping(candidate_path)
    report = build_btc_ga_candidate_review_packet(
        source,
        candidates,
        source_report_path=source_report_path,
        candidate_path=candidate_path,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    if markdown_path is not None:
        _write_text(markdown_path, build_btc_ga_candidate_review_markdown(report))
    return report


def build_btc_ga_candidate_review_markdown(packet: Mapping[str, Any]) -> str:
    summary = _mapping(packet.get("review_summary"))
    source = _mapping(packet.get("source_report"))
    data_context = _mapping(packet.get("data_context"))
    validation_context = _mapping(packet.get("validation_context"))
    holdout_summary = _mapping(packet.get("confirmatory_holdout_summary"))
    lines = [
        "# BTC GA 候选因子复核包",
        "",
        f"- 状态：{_status_label_zh(packet.get('status'))}",
        f"- 决策：{_decision_label_zh(packet.get('decision'))}",
        f"- 运行编号：{source.get('run_id')}",
        f"- 复核包生成器 commit：{packet.get('code_commit')}",
        f"- 原始挖掘 commit：{source.get('code_commit')}",
        f"- 候选因子数量：{summary.get('candidate_count')}",
        f"- 扩展研究短名单：{summary.get('extended_research_shortlist_count')}",
        f"- 需要人工复核：{summary.get('manual_review_count')}",
        f"- 当前批次剔除：{summary.get('reject_count')}",
        f"- Paper 队列写入允许：{str(_mapping(packet.get('gate')).get('paper_queue_write_allowed')).lower()}",
        f"- Live 解锁允许：{str(_mapping(packet.get('gate')).get('live_unlock_allowed')).lower()}",
        "",
        "## 数据与验证",
        "",
        f"- BTC 1H 行情窗口：{data_context.get('market_start_time')} 到 {data_context.get('market_end_time')}",
        f"- 衍生品情绪窗口：{data_context.get('derivatives_visible_start_time')} 到 {data_context.get('derivatives_visible_end_time')}",
        f"- 行情与情绪重叠小时数：{data_context.get('derivatives_market_overlap_rows')}",
        f"- Walk-forward 折数：{validation_context.get('fold_count')}",
        f"- 样本外通过率：{validation_context.get('oos_pass_rate')}",
        f"- 样本外中位数 PF：{validation_context.get('median_validation_profit_factor')}",
        f"- 确认性 holdout：{holdout_summary.get('status_zh') or '未启用'}",
        f"- Holdout 行数：{holdout_summary.get('holdout_rows')}",
        f"- Holdout 存活候选数：{holdout_summary.get('surviving_candidate_count')}",
        f"- Holdout 短名单：{', '.join(str(item) for item in holdout_summary.get('shortlist_for_extended_research_only', [])) or '无'}",
        "",
        "## 候选因子表",
        "",
        "| 排名 | Hash | 逻辑类型 | 复核结论 | 验证 PF | 验证收益 | 最大回撤 | 成本压力 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in _mapping_rows(packet.get("candidate_reviews")):
        metrics = _mapping(row.get("validation_metrics"))
        stress = _mapping(row.get("cost_stress_summary"))
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("rank")),
                    str(row.get("expression_hash")),
                    str(row.get("logic_family_zh") or _logic_family_label_zh(row.get("logic_family"))),
                    str(row.get("review_verdict_zh") or _verdict_label_zh(row.get("review_verdict"))),
                    _format_float(metrics.get("profit_factor")),
                    _format_pct(metrics.get("total_return")),
                    _format_pct(metrics.get("max_drawdown")),
                    f"{stress.get('survival_count')}/{stress.get('scenario_count')}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## 候选因子说明", ""])
    for row in _mapping_rows(packet.get("candidate_reviews")):
        flags_zh = row.get("review_flags_zh")
        if not isinstance(flags_zh, list):
            flags_zh = [_flag_label_zh(flag) for flag in row.get("review_flags", [])]
        lines.extend(
            [
                f"### {row.get('rank')}. {row.get('candidate_id')}",
                "",
                f"- 逻辑类型：{row.get('logic_family_zh') or _logic_family_label_zh(row.get('logic_family'))}",
                f"- 表达式解释：{row.get('expression_human_zh') or row.get('expression_human')}",
                f"- 复核结论：{row.get('review_verdict_zh') or _verdict_label_zh(row.get('review_verdict'))}",
                f"- 风险标签：{', '.join(str(item) for item in flags_zh) or '无'}",
                f"- 下一步允许状态：{_next_state_label_zh(row.get('next_allowed_state'))}",
                "",
            ]
        )
    lines.extend(["## 建议下一步", ""])
    actions = packet.get("recommended_next_actions_zh") or [
        _action_label_zh(action) for action in packet.get("recommended_next_actions", [])
    ]
    for action in actions:
        lines.append(f"- {action}")
    lines.extend(["", "## 人工复核问题", ""])
    questions = packet.get("manual_review_questions_zh") or [
        _question_label_zh(question) for question in packet.get("manual_review_questions", [])
    ]
    for question in questions:
        lines.append(f"- {question}")
    lines.append("")
    return "\n".join(lines)


def _evolve_fold(
    *,
    frame: pd.DataFrame,
    split: WalkForwardSplit,
    rng: random.Random,
    population_size: int,
    generations: int,
    max_depth: int,
    max_complexity: int,
) -> dict[str, Any]:
    train = frame.iloc[split.train_start:split.train_end].copy()
    validation = frame.iloc[split.validation_start:split.validation_end].copy()
    population = [_random_expression(rng, max_depth=max_depth) for _ in range(population_size)]
    trial_count = 0
    rejected_count = 0
    scored: list[tuple[float, FactorExpression, FactorMetrics]] = []
    for _ in range(generations):
        scored = []
        for expr in population:
            try:
                metrics = evaluate_factor_metrics(expr, train, max_depth=max_depth, max_complexity=max_complexity)
                fitness = _fitness(metrics, complexity=expression_complexity(expr))
                scored.append((fitness, expr, metrics))
                trial_count += 1
            except (DSLValidationError, GAFactorMiningError, ValueError, FloatingPointError):
                rejected_count += 1
        if not scored:
            population = [_random_expression(rng, max_depth=max_depth) for _ in range(population_size)]
            continue
        scored.sort(key=lambda item: item[0], reverse=True)
        elites = [item[1] for item in scored[: max(2, population_size // 8)]]
        next_population = list(elites)
        while len(next_population) < population_size:
            parent_a = _tournament(scored, rng)
            parent_b = _tournament(scored, rng)
            child = _crossover(parent_a, parent_b, rng) if rng.random() < 0.60 else parent_a
            if rng.random() < 0.30:
                child = _mutate(child, rng, max_depth=max_depth)
            next_population.append(child)
        population = next_population
    candidates: list[CandidateEvaluation] = []
    for train_fitness, expr, train_metrics in sorted(scored, key=lambda item: item[0], reverse=True)[:8]:
        try:
            validation_metrics = evaluate_factor_metrics(
                expr,
                validation,
                max_depth=max_depth,
                max_complexity=max_complexity,
                threshold=train_metrics.threshold,
                direction=train_metrics.direction,
            )
            validation_fitness = _fitness(validation_metrics, complexity=expression_complexity(expr))
        except (DSLValidationError, GAFactorMiningError, ValueError, FloatingPointError):
            rejected_count += 1
            continue
        candidates.append(
            CandidateEvaluation(
                expression=expr,
                fold_id=split.fold_id,
                train_metrics=train_metrics,
                validation_metrics=validation_metrics,
                train_fitness=round(float(train_fitness), 6),
                validation_fitness=round(float(validation_fitness), 6),
                complexity=expression_complexity(expr),
                depth=expression_depth(expr),
                cost_stress=_cost_stress(expr, validation, train_metrics=train_metrics),
            )
        )
    return {"candidates": candidates, "trial_count": trial_count, "rejected_count": rejected_count}


def evaluate_factor_metrics(
    expr: FactorExpression,
    frame: pd.DataFrame,
    *,
    max_depth: int = 4,
    max_complexity: int = 8,
    threshold: float | None = None,
    direction: int | None = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 4.0,
    forward_return_col: str = "forward_return_4h",
) -> FactorMetrics:
    factor = evaluate_expression(expr, frame, max_depth=max_depth, max_complexity=max_complexity)
    label = pd.to_numeric(frame[forward_return_col], errors="coerce")
    data = pd.DataFrame({"factor": factor, "label": label, "funding_rate": frame.get("funding_rate", 0.0)}, index=frame.index)
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=["factor", "label"])
    if len(data) < 20:
        raise GAFactorMiningError("insufficient_observations_for_factor_metrics")
    rank_ic = _rank_ic(data["factor"], data["label"])
    use_direction = int(direction) if direction in {-1, 1} else (1 if rank_ic >= 0 else -1)
    score = data["factor"] * use_direction
    use_threshold = float(threshold) if threshold is not None else float(score.quantile(0.70))
    signal = (score > use_threshold).astype(float)
    returns = _strategy_returns(
        signal=signal,
        forward_returns=data["label"],
        funding_rate=data["funding_rate"],
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    turnover = float(signal.diff().abs().fillna(signal.abs()).mean())
    return FactorMetrics(
        rank_ic=round(float(rank_ic), 6),
        profit_factor=_profit_factor(returns),
        total_return=round(float((1.0 + returns).prod() - 1.0), 6),
        max_drawdown=round(_max_drawdown(returns), 6),
        turnover=round(turnover, 6),
        exposure=round(float(signal.mean()), 6),
        hit_rate=round(float((returns > 0).mean()), 6),
        observations=int(len(data)),
        threshold=round(use_threshold, 10),
        direction=use_direction,
        cost_bps=round(float(fee_bps) + float(slippage_bps), 6),
        funding_cost_approx=round(float((signal * pd.to_numeric(data["funding_rate"], errors="coerce").fillna(0.0) * 0.5).sum()), 10),
    )


def expression_complexity(expr: FactorExpression) -> int:
    return 1 + sum(expression_complexity(arg) for arg in expr.args)


def expression_depth(expr: FactorExpression) -> int:
    return 1 if not expr.args else 1 + max(expression_depth(arg) for arg in expr.args)


def _add_feature_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    close = pd.to_numeric(result["close"], errors="coerce")
    high = pd.to_numeric(result["high"], errors="coerce")
    low = pd.to_numeric(result["low"], errors="coerce")
    volume = pd.to_numeric(result["volume"], errors="coerce")
    result["return_1h"] = close.pct_change()
    result["return_4h"] = close.pct_change(4)
    result["momentum_24h"] = close.pct_change(24)
    result["realized_vol_24h"] = result["return_1h"].rolling(24, min_periods=8).std(ddof=0)
    result["range_pct"] = (high - low).abs() / close.shift(1).replace(0, np.nan)
    result["volume_z_24"] = rolling_zscore(volume, 24)
    result["open_interest_z_24"] = rolling_zscore(result.get("open_interest_usd"), 24)
    result["open_interest_delta_1h"] = pd.to_numeric(result.get("open_interest_usd"), errors="coerce").pct_change()
    result["funding_z_24"] = rolling_zscore(result.get("funding_rate"), 24)
    result["funding_delta_1h"] = pd.to_numeric(result.get("funding_rate"), errors="coerce").diff()
    long_liq = pd.to_numeric(result.get("long_liquidation_usd"), errors="coerce").fillna(0.0)
    short_liq = pd.to_numeric(result.get("short_liquidation_usd"), errors="coerce").fillna(0.0)
    liquidation_total = long_liq + short_liq
    result["liquidation_z_24"] = rolling_zscore(liquidation_total, 24)
    result["liquidation_imbalance"] = (short_liq - long_liq) / liquidation_total.replace(0, np.nan)
    result["long_short_z_24"] = rolling_zscore(result.get("long_short_ratio"), 24)
    result["long_short_delta_1h"] = pd.to_numeric(result.get("long_short_ratio"), errors="coerce").diff()
    return result


def _derivative_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_derivative_value_fields(), index=pd.DatetimeIndex([], tz="UTC"))
    records = []
    for row in rows:
        try:
            event_time = _parse_utc(row.get("event_time"))
        except (TypeError, ValueError):
            continue
        record = {"timestamp": event_time}
        for field_name in _derivative_value_fields():
            record[field_name] = _derivative_field_value(row, field_name)
        records.append(record)
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=_derivative_value_fields(), index=pd.DatetimeIndex([], tz="UTC"))
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").set_index("timestamp")


def _derivative_value_fields() -> tuple[str, ...]:
    return tuple(DERIVATIVE_VALUE_FIELD_ALIASES)


def _derivative_field_value(row: Mapping[str, Any], field_name: str) -> float | None:
    for alias in DERIVATIVE_VALUE_FIELD_ALIASES[field_name]:
        value = row.get(alias)
        if value is None:
            continue
        number = _float_or_none(value)
        if number is not None:
            return number
    return None


def _derivative_raw_non_null_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        field: sum(1 for row in rows if _derivative_field_value(row, field) is not None)
        for field in _derivative_value_fields()
    }


def _frame_derivative_field_non_null_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        field: int(pd.to_numeric(frame[field], errors="coerce").notna().sum()) if field in frame else 0
        for field in _derivative_value_fields()
    }


def _derivatives_alignment_status(
    *,
    visible_rows: int,
    raw_counts: Mapping[str, Any],
    overlap_rows: int,
    joined_counts: Mapping[str, Any],
) -> str:
    raw_values = [_int_or_zero(raw_counts.get(field)) for field in _derivative_value_fields()]
    joined_values = [_int_or_zero(joined_counts.get(field)) for field in _derivative_value_fields()]
    if visible_rows <= 0:
        return "no_visible_derivatives_rows"
    if sum(raw_values) <= 0:
        return "visible_rows_but_value_fields_zero"
    if overlap_rows <= 0:
        return "no_market_derivatives_time_overlap"
    if sum(joined_values) <= 0:
        return "joined_value_fields_zero"
    if any(value <= 0 for value in joined_values):
        return "partial_value_field_coverage"
    return "value_fields_present"


def _evaluate_expression_node(expr: FactorExpression, frame: pd.DataFrame) -> pd.Series:
    if expr.op == "primitive":
        return pd.to_numeric(frame[expr.primitive], errors="coerce")
    if expr.op == "const":
        return pd.Series(float(expr.value or 0.0), index=frame.index, dtype=float)
    args = [_evaluate_expression_node(arg, frame) for arg in expr.args]
    if expr.op == "add":
        return args[0] + args[1]
    if expr.op == "sub":
        return args[0] - args[1]
    if expr.op == "mul":
        return args[0] * args[1]
    if expr.op == "safe_ratio":
        return args[0] / args[1].where(args[1].abs() > 1e-9, np.nan)
    if expr.op == "clip":
        return args[0].clip(-5.0, 5.0)
    if expr.op == "tanh":
        return np.tanh(args[0].clip(-20.0, 20.0))
    if expr.op == "sign":
        return np.sign(args[0])
    if expr.op == "rolling_z":
        return rolling_zscore(args[0], expr.window)
    if expr.op == "gate":
        return args[0] * (args[1] > 0.0).astype(float)
    raise DSLValidationError(f"operator_not_allowed:{expr.op}")


def _random_expression(rng: random.Random, *, max_depth: int, current_depth: int = 1) -> FactorExpression:
    if current_depth >= max_depth or rng.random() < 0.35:
        return primitive(rng.choice(PRIMITIVE_COLUMNS))
    op = rng.choice((*UNARY_OPERATORS, *BINARY_OPERATORS))
    if op in UNARY_OPERATORS:
        return FactorExpression(
            op=op,
            args=(_random_expression(rng, max_depth=max_depth, current_depth=current_depth + 1),),
            window=rng.choice([12, 24, 48, 96]),
        )
    return FactorExpression(
        op=op,
        args=(
            _random_expression(rng, max_depth=max_depth, current_depth=current_depth + 1),
            _random_expression(rng, max_depth=max_depth, current_depth=current_depth + 1),
        ),
    )


def _mutate(expr: FactorExpression, rng: random.Random, *, max_depth: int, current_depth: int = 1) -> FactorExpression:
    if current_depth >= max_depth or rng.random() < 0.25:
        return _random_expression(rng, max_depth=max_depth, current_depth=current_depth)
    if not expr.args:
        return primitive(rng.choice(PRIMITIVE_COLUMNS))
    index = rng.randrange(len(expr.args))
    args = list(expr.args)
    args[index] = _mutate(args[index], rng, max_depth=max_depth, current_depth=current_depth + 1)
    return FactorExpression(op=expr.op, args=tuple(args), primitive=expr.primitive, value=expr.value, window=expr.window)


def _crossover(left: FactorExpression, right: FactorExpression, rng: random.Random) -> FactorExpression:
    if not left.args or rng.random() < 0.20:
        return right
    args = list(left.args)
    args[rng.randrange(len(args))] = right if rng.random() < 0.50 or not right.args else rng.choice(right.args)
    return FactorExpression(op=left.op, args=tuple(args), primitive=left.primitive, value=left.value, window=left.window)


def _tournament(scored: list[tuple[float, FactorExpression, FactorMetrics]], rng: random.Random) -> FactorExpression:
    pool = rng.sample(scored, k=min(3, len(scored)))
    return max(pool, key=lambda item: item[0])[1]


def _strategy_returns(
    *,
    signal: pd.Series,
    forward_returns: pd.Series,
    funding_rate: pd.Series | float,
    fee_bps: float,
    slippage_bps: float,
) -> pd.Series:
    clean_signal = pd.to_numeric(signal, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    raw = clean_signal * pd.to_numeric(forward_returns, errors="coerce").fillna(0.0)
    turnover = clean_signal.diff().abs().fillna(clean_signal.abs())
    cost = turnover * (float(fee_bps) + float(slippage_bps)) / 10_000.0
    funding = clean_signal * pd.to_numeric(funding_rate, errors="coerce").fillna(0.0) * 0.5
    return (raw - cost - funding).fillna(0.0)


def _cost_stress(expr: FactorExpression, frame: pd.DataFrame, *, train_metrics: FactorMetrics) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for name, config in COST_SCENARIOS.items():
        metrics = evaluate_factor_metrics(
            expr,
            frame,
            threshold=train_metrics.threshold,
            direction=train_metrics.direction,
            fee_bps=float(config["fee_bps"]),
            slippage_bps=float(config["slippage_bps"]),
        )
        rows[name] = {
            "fee_bps": float(config["fee_bps"]),
            "slippage_bps": float(config["slippage_bps"]),
            "profit_factor": metrics.profit_factor,
            "total_return": metrics.total_return,
            "max_drawdown": metrics.max_drawdown,
            "survives": metrics.profit_factor >= 1.0 and metrics.total_return >= 0.0,
        }
    return rows


def _confirmatory_holdout_report(
    candidates: list[CandidateEvaluation],
    *,
    selection_frame: pd.DataFrame,
    holdout_frame: pd.DataFrame,
    requested_hours: int,
    max_depth: int,
    max_complexity: int,
) -> dict[str, Any]:
    if requested_hours <= 0:
        return {
            "enabled": False,
            "status": "not_requested",
            "ga_selection_used_holdout": False,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    blockers: list[str] = []
    if holdout_frame.empty:
        blockers.append("confirmatory_holdout_rows_missing")
    baseline_rows = _holdout_baseline_rows(
        selection_frame=selection_frame,
        holdout_frame=holdout_frame,
        max_depth=max_depth,
        max_complexity=max_complexity,
    )
    best_baseline_pf = max(
        (_float_value(_mapping(row.get("holdout_metrics")).get("profit_factor")) for row in baseline_rows),
        default=0.0,
    )
    candidate_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_rows.append(
            _holdout_candidate_row(
                candidate,
                holdout_frame=holdout_frame,
                best_baseline_pf=best_baseline_pf,
                max_depth=max_depth,
                max_complexity=max_complexity,
            )
        )
    surviving = [
        row
        for row in candidate_rows
        if _mapping(row.get("holdout_metrics")).get("profit_factor", 0.0) >= 1.0
        and _mapping(row.get("holdout_metrics")).get("total_return", 0.0) >= 0.0
        and bool(_mapping(row.get("cost_stress_summary")).get("all_stress_survives"))
    ]
    return {
        "enabled": True,
        "status": "blocked" if blockers else "complete",
        "requested_hours": requested_hours,
        "selection_rows": int(len(selection_frame)),
        "holdout_rows": int(len(holdout_frame)),
        "holdout_start_time": holdout_frame.index[0].isoformat() if len(holdout_frame) else None,
        "holdout_end_time": holdout_frame.index[-1].isoformat() if len(holdout_frame) else None,
        "ga_selection_used_holdout": False,
        "threshold_policy": "holdout uses train threshold and direction; no holdout re-optimization",
        "baseline_comparison_policy": "diagnostic only; does not unlock paper or live",
        "baseline_rows": baseline_rows,
        "candidate_rows": candidate_rows,
        "surviving_candidate_count": len(surviving),
        "shortlist_for_extended_research_only": [
            row.get("candidate_id") for row in surviving if row.get("candidate_id")
        ],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "blockers": blockers,
    }


def _holdout_baseline_rows(
    *,
    selection_frame: pd.DataFrame,
    holdout_frame: pd.DataFrame,
    max_depth: int,
    max_complexity: int,
) -> list[dict[str, Any]]:
    baselines = {
        "btc_trend_baseline_momentum_24h_z24": FactorExpression(
            op="rolling_z",
            args=(primitive("momentum_24h"),),
            window=24,
        ),
        "btc_trend_baseline_momentum_24h_z48": FactorExpression(
            op="rolling_z",
            args=(primitive("momentum_24h"),),
            window=48,
        ),
    }
    rows: list[dict[str, Any]] = []
    for baseline_id, expr in baselines.items():
        try:
            train_metrics = evaluate_factor_metrics(
                expr,
                selection_frame,
                max_depth=max_depth,
                max_complexity=max_complexity,
            )
            holdout_metrics = evaluate_factor_metrics(
                expr,
                holdout_frame,
                max_depth=max_depth,
                max_complexity=max_complexity,
                threshold=train_metrics.threshold,
                direction=train_metrics.direction,
            )
            rows.append(
                {
                    "baseline_id": baseline_id,
                    "expression": expr.to_dict(),
                    "train_metrics": train_metrics.to_dict(),
                    "holdout_metrics": holdout_metrics.to_dict(),
                }
            )
        except (DSLValidationError, GAFactorMiningError, ValueError, FloatingPointError) as exc:
            rows.append(
                {
                    "baseline_id": baseline_id,
                    "expression": expr.to_dict(),
                    "status": "blocked",
                    "blocker": f"{type(exc).__name__}:{exc}",
                }
            )
    return rows


def _holdout_candidate_row(
    candidate: CandidateEvaluation,
    *,
    holdout_frame: pd.DataFrame,
    best_baseline_pf: float,
    max_depth: int,
    max_complexity: int,
) -> dict[str, Any]:
    try:
        metrics = evaluate_factor_metrics(
            candidate.expression,
            holdout_frame,
            max_depth=max_depth,
            max_complexity=max_complexity,
            threshold=candidate.train_metrics.threshold,
            direction=candidate.train_metrics.direction,
        )
        cost_stress = _cost_stress(candidate.expression, holdout_frame, train_metrics=candidate.train_metrics)
        surviving = _cost_stress_surviving_scenarios(cost_stress)
        return {
            "candidate_id": f"btc_ga_{candidate.expression.expression_hash}_fold{candidate.fold_id}",
            "expression_hash": candidate.expression.expression_hash,
            "fold_id": candidate.fold_id,
            "holdout_metrics": metrics.to_dict(),
            "cost_stress": cost_stress,
            "cost_stress_summary": {
                "scenario_count": len(cost_stress),
                "survival_count": len(surviving),
                "surviving_scenarios": surviving,
                "all_stress_survives": bool(cost_stress) and len(surviving) == len(cost_stress),
            },
            "trend_baseline_comparison": {
                "best_baseline_profit_factor": round(best_baseline_pf, 6),
                "candidate_pf_minus_best_baseline_pf": round(metrics.profit_factor - best_baseline_pf, 6),
                "candidate_outperforms_best_baseline_pf": metrics.profit_factor > best_baseline_pf,
            },
            "regime_attribution": _regime_attribution(
                candidate.expression,
                holdout_frame,
                threshold=candidate.train_metrics.threshold,
                direction=candidate.train_metrics.direction,
                max_depth=max_depth,
                max_complexity=max_complexity,
            ),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    except (DSLValidationError, GAFactorMiningError, ValueError, FloatingPointError) as exc:
        return {
            "candidate_id": f"btc_ga_{candidate.expression.expression_hash}_fold{candidate.fold_id}",
            "expression_hash": candidate.expression.expression_hash,
            "fold_id": candidate.fold_id,
            "status": "blocked",
            "blocker": f"{type(exc).__name__}:{exc}",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }


def _regime_attribution(
    expr: FactorExpression,
    frame: pd.DataFrame,
    *,
    threshold: float,
    direction: int,
    max_depth: int,
    max_complexity: int,
) -> dict[str, Any]:
    data = _factor_strategy_return_frame(
        expr,
        frame,
        threshold=threshold,
        direction=direction,
        max_depth=max_depth,
        max_complexity=max_complexity,
    )
    if data.empty:
        return {"status": "blocked", "blockers": ["regime_attribution_no_rows"]}
    close = pd.to_numeric(frame["close"], errors="coerce").reindex(data.index)
    trend_24h = close.pct_change(24)
    realized_vol = pd.to_numeric(frame.get("realized_vol_24h"), errors="coerce").reindex(data.index)
    funding_rate = pd.to_numeric(frame.get("funding_rate"), errors="coerce").reindex(data.index)
    regimes = pd.DataFrame(index=data.index)
    regimes["trend_regime"] = np.where(trend_24h >= 0.0, "trend_up_or_flat", "trend_down")
    vol_median = float(realized_vol.median()) if realized_vol.notna().any() else 0.0
    regimes["volatility_regime"] = np.where(realized_vol >= vol_median, "high_vol", "low_vol")
    regimes["funding_regime"] = np.where(
        funding_rate.isna(),
        "funding_unknown",
        np.where(funding_rate >= 0.0, "funding_positive_or_zero", "funding_negative"),
    )
    return {
        "status": "complete",
        "by_trend_regime": _regime_group_rows(data["returns"], regimes["trend_regime"], data["signal"]),
        "by_volatility_regime": _regime_group_rows(data["returns"], regimes["volatility_regime"], data["signal"]),
        "by_funding_regime": _regime_group_rows(data["returns"], regimes["funding_regime"], data["signal"]),
    }


def _factor_strategy_return_frame(
    expr: FactorExpression,
    frame: pd.DataFrame,
    *,
    threshold: float,
    direction: int,
    max_depth: int,
    max_complexity: int,
) -> pd.DataFrame:
    factor = evaluate_expression(expr, frame, max_depth=max_depth, max_complexity=max_complexity)
    label = pd.to_numeric(frame["forward_return_4h"], errors="coerce")
    funding_rate = pd.to_numeric(frame.get("funding_rate", 0.0), errors="coerce")
    data = pd.DataFrame({"factor": factor, "label": label, "funding_rate": funding_rate}, index=frame.index)
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=["factor", "label"])
    if len(data) < 20:
        return pd.DataFrame()
    score = data["factor"] * int(direction)
    signal = (score > float(threshold)).astype(float)
    returns = _strategy_returns(
        signal=signal,
        forward_returns=data["label"],
        funding_rate=data["funding_rate"],
        fee_bps=5.0,
        slippage_bps=4.0,
    )
    return pd.DataFrame({"signal": signal, "returns": returns}, index=data.index)


def _regime_group_rows(returns: pd.Series, labels: pd.Series, signal: pd.Series) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped = pd.DataFrame({"returns": returns, "label": labels, "signal": signal}).dropna(subset=["label"])
    for label, group in grouped.groupby("label", sort=True):
        group_returns = pd.to_numeric(group["returns"], errors="coerce").fillna(0.0)
        rows.append(
            {
                "regime": str(label),
                "observations": int(len(group)),
                "exposure": round(float(pd.to_numeric(group["signal"], errors="coerce").fillna(0.0).mean()), 6),
                "profit_factor": _profit_factor(group_returns),
                "total_return": round(float((1.0 + group_returns).prod() - 1.0), 6),
                "max_drawdown": round(_max_drawdown(group_returns), 6),
            }
        )
    return rows


def _cost_stress_surviving_scenarios(cost_stress: Mapping[str, Any]) -> list[str]:
    return sorted(str(name) for name, row in cost_stress.items() if _mapping(row).get("survives") is True)


def _funding_timestamp_cost_audit(
    rows: Sequence[Mapping[str, Any]],
    candidates: list[CandidateEvaluation],
) -> dict[str, Any]:
    funding_rows = []
    for row in rows:
        if row.get("funding_rate") is None:
            continue
        try:
            event_time = _parse_utc(row.get("event_time"))
            available_time = _parse_utc(row.get("available_time"))
        except (TypeError, ValueError):
            continue
        funding_rows.append((event_time, available_time))
    lags = [(available - event).total_seconds() / 60.0 for event, available in funding_rows]
    funding_candidate_ids = []
    for candidate in candidates:
        primitive_counts: dict[str, int] = {}
        operator_counts: dict[str, int] = {}
        _collect_expression_usage(candidate.expression.to_dict(), primitive_counts, operator_counts)
        if any(name.startswith("funding") for name in primitive_counts):
            funding_candidate_ids.append(f"btc_ga_{candidate.expression.expression_hash}_fold{candidate.fold_id}")
    return {
        "status": "complete" if funding_rows else "blocked",
        "funding_row_count": len(funding_rows),
        "funding_candidate_count": len(funding_candidate_ids),
        "funding_candidate_ids": funding_candidate_ids,
        "available_time_lag_minutes_min": round(min(lags), 6) if lags else None,
        "available_time_lag_minutes_median": round(float(np.median(lags)), 6) if lags else None,
        "available_time_lag_minutes_max": round(max(lags), 6) if lags else None,
        "funding_cost_treatment": "hourly_research_approximation",
        "review_required": bool(funding_candidate_ids),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _fitness(metrics: FactorMetrics, *, complexity: int) -> float:
    pf_score = min(metrics.profit_factor, 3.0) - 1.0
    return round(
        abs(metrics.rank_ic) * 4.0
        + pf_score
        + max(metrics.total_return, -0.25)
        - abs(metrics.max_drawdown) * 0.50
        - metrics.turnover * 0.25
        - max(0, complexity - 4) * 0.03,
        6,
    )


def _select_unique_candidates(candidates: list[CandidateEvaluation], *, max_candidates: int) -> list[CandidateEvaluation]:
    ordered = sorted(candidates, key=lambda item: item.validation_fitness, reverse=True)
    seen: set[str] = set()
    selected: list[CandidateEvaluation] = []
    for candidate in ordered:
        signature = candidate.expression.signature
        if signature in seen:
            continue
        seen.add(signature)
        selected.append(candidate)
        if len(selected) >= max_candidates:
            break
    return selected


def _build_report_payload(
    *,
    frame: pd.DataFrame,
    candidates: list[CandidateEvaluation],
    all_candidate_count: int,
    coverage: Mapping[str, Any],
    splits: list[WalkForwardSplit],
    seed: int,
    population_size: int,
    generations: int,
    trial_count: int,
    rejected_count: int,
    blockers: list[str],
) -> dict[str, Any]:
    stability = _oos_stability(candidates)
    return {
        "schema_version": "btc_ga_factor_mining_report_v1",
        "ga_factor_mining_version": BTC_GA_FACTOR_MINING_VERSION,
        "run_id": f"btc_ga_{seed}_{stable_payload_hash({'seed': seed, 'rows': len(frame)})[:10]}",
        "status": "complete" if not blockers else "blocked",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "scope": "research_only_expression_review",
        "data_coverage": dict(coverage),
        "ga_config": {
            "seed": seed,
            "population_size": population_size,
            "generations": generations,
            "selection": "tournament",
            "crossover_rate": 0.60,
            "mutation_rate": 0.30,
            "candidate_count": all_candidate_count,
            "selected_candidate_count": len(candidates),
            "trial_count": trial_count,
            "rejected_count": rejected_count,
            "max_depth": 4,
            "max_complexity": 8,
        },
        "dsl_policy": {
            "safe_declarative_dsl": True,
            "python_eval_allowed": False,
            "allowed_operators": sorted(ALLOWED_OPERATORS),
            "allowed_primitives": list(PRIMITIVE_COLUMNS),
        },
        "walk_forward": {
            "fold_count": len(splits),
            "method": "rolling_train_validation_with_embargo",
            "embargo_hours": splits[0].embargo_hours if splits else 0,
            "splits": [split.to_dict(frame.index) for split in splits],
            "oos_stability": stability,
        },
        "cost_model": {
            "base_fee_bps": 5.0,
            "base_slippage_bps": 4.0,
            "stress_scenarios": COST_SCENARIOS,
            "funding_cost_treatment": "hourly_research_approximation_from_visible_funding_rate",
        },
        "top_candidates": [candidate.to_dict() for candidate in candidates],
        "promotion": {
            "recommendation": "research_only_expression_review",
            "paper_candidate_generated": False,
            "paper_queue_status": "LOCKED",
            "paper_auto_start": False,
            "live_status": "FROZEN",
            "live_enabled": False,
        },
        "safety": {
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "strategy_skeleton_generated": False,
        },
        "code_commit": _git_commit_hash(),
        "blockers": blockers,
    }


def _oos_stability(candidates: list[CandidateEvaluation]) -> dict[str, Any]:
    if not candidates:
        return {"pass_rate": 0.0, "fold_count": 0, "median_validation_pf": 0.0}
    by_fold = {}
    for candidate in candidates:
        current = by_fold.get(candidate.fold_id)
        if current is None or candidate.validation_fitness > current.validation_fitness:
            by_fold[candidate.fold_id] = candidate
    fold_rows = [
        {
            "fold_id": fold_id,
            "profit_factor": candidate.validation_metrics.profit_factor,
            "rank_ic": candidate.validation_metrics.rank_ic,
            "max_drawdown": candidate.validation_metrics.max_drawdown,
            "passed": candidate.validation_metrics.profit_factor >= 1.0 and candidate.validation_metrics.total_return >= 0.0,
        }
        for fold_id, candidate in sorted(by_fold.items())
    ]
    pass_rate = sum(1 for row in fold_rows if row["passed"]) / max(1, len(fold_rows))
    return {
        "pass_rate": round(pass_rate, 6),
        "fold_count": len(fold_rows),
        "median_validation_pf": round(float(np.median([row["profit_factor"] for row in fold_rows])), 6),
        "folds": fold_rows,
    }


def _paper_live_safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_ga_factor_mining_paper_live_safety_v1",
        "run_id": report.get("run_id"),
        "scope": "research_only_expression_review",
        "paper_queue_status": "LOCKED",
        "paper_review_pending_allowed": False,
        "paper_auto_start": False,
        "live_status": "FROZEN",
        "live_enabled": False,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "strategy_skeleton_generated": False,
    }


def _ga_diagnostic_summary(
    *,
    source: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    ga_config: Mapping[str, Any],
    coverage: Mapping[str, Any],
    oos_stability: Mapping[str, Any],
    source_blockers: list[str],
) -> dict[str, Any]:
    failure_reasons: list[str] = []
    selected_count = _int_or_zero(ga_config.get("selected_candidate_count"))
    pass_rate = _float_value(oos_stability.get("pass_rate"))
    median_validation_pf = _float_value(oos_stability.get("median_validation_pf"))
    fold_count = _int_or_zero(oos_stability.get("fold_count"))
    derivative_status = _derivative_value_coverage_status(coverage)
    cost = _ga_cost_diagnostics(candidates)
    inactive_count = sum(
        1
        for candidate in candidates
        if _float_value(_mapping(candidate.get("validation_metrics")).get("exposure")) <= 0.0
    )
    if source_blockers:
        failure_reasons.append("source_ga_factor_mining_report_has_blockers")
    if selected_count <= 0:
        failure_reasons.append("no_candidates_selected")
    if derivative_status == "no_market_derivatives_time_overlap":
        failure_reasons.append("derivatives_market_time_overlap_missing")
    elif derivative_status == "visible_rows_but_value_fields_zero":
        failure_reasons.append("derivatives_value_coverage_zero_after_merge")
    elif derivative_status == "joined_value_fields_zero":
        failure_reasons.append("derivatives_value_coverage_zero_after_join")
    elif derivative_status == "partial_value_field_coverage":
        failure_reasons.append("derivatives_value_coverage_partial_after_merge")
    if fold_count > 0 and pass_rate <= 0.0:
        failure_reasons.append("oos_stability_pass_rate_zero")
    elif fold_count > 0 and pass_rate < 0.5:
        failure_reasons.append("oos_stability_pass_rate_below_half")
    if fold_count > 0 and median_validation_pf < 1.0:
        failure_reasons.append("median_validation_profit_factor_below_1")
    if candidates and cost["candidate_any_scenario_survival_count"] <= 0:
        failure_reasons.append("cost_stress_no_candidate_survives_any_scenario")
    if candidates and inactive_count >= max(1, len(candidates) // 2):
        failure_reasons.append("validation_signal_inactive_or_threshold_mismatch")
    return {
        "source_status": source.get("status"),
        "source_decision": source.get("decision"),
        "selected_candidate_count": selected_count,
        "trial_count": _int_or_zero(ga_config.get("trial_count")),
        "rejected_count": _int_or_zero(ga_config.get("rejected_count")),
        "fold_count": fold_count,
        "oos_pass_rate": round(pass_rate, 6),
        "median_validation_profit_factor": round(median_validation_pf, 6),
        "validation_inactive_candidate_count": inactive_count,
        "derivative_value_coverage_status": derivative_status,
        "failure_reasons": _dedupe_text(failure_reasons),
    }


def _ga_data_diagnostics(coverage: Mapping[str, Any]) -> dict[str, Any]:
    raw_counts = _normalize_derivative_counts(_mapping(coverage.get("field_non_null_counts_raw_visible")))
    joined_counts = _normalize_derivative_counts(
        _mapping(coverage.get("field_non_null_counts_after_join") or coverage.get("field_non_null_counts"))
    )
    lookback_counts = _normalize_derivative_counts(
        _mapping(
            coverage.get("field_non_null_counts_after_lookback")
            or coverage.get("field_non_null_counts_after_join")
            or coverage.get("field_non_null_counts")
        )
    )
    visible_rows = _int_or_zero(coverage.get("derivatives_visible_rows"))
    return {
        "market_rows": _int_or_zero(coverage.get("market_rows")),
        "market_start_time": coverage.get("market_start_time"),
        "market_end_time": coverage.get("market_end_time"),
        "derivatives_total_rows": _int_or_zero(coverage.get("derivatives_total_rows")),
        "derivatives_visible_rows": visible_rows,
        "derivatives_visible_start_time": coverage.get("derivatives_visible_start_time"),
        "derivatives_visible_end_time": coverage.get("derivatives_visible_end_time"),
        "derivatives_market_overlap_rows": _int_or_zero(coverage.get("derivatives_market_overlap_rows")),
        "derivatives_market_overlap_start_time": coverage.get("derivatives_market_overlap_start_time"),
        "derivatives_market_overlap_end_time": coverage.get("derivatives_market_overlap_end_time"),
        "derivatives_feature_rows_after_label_drop": _int_or_zero(
            coverage.get("derivatives_feature_rows_after_label_drop")
        ),
        "derivatives_feature_rows_after_lookback": _int_or_zero(
            coverage.get("derivatives_feature_rows_after_lookback")
        ),
        "merged_rows": _int_or_zero(coverage.get("merged_rows")),
        "merged_rows_after_lookback": _int_or_zero(coverage.get("merged_rows_after_lookback")),
        "decision_time": coverage.get("decision_time"),
        "field_non_null_counts": lookback_counts,
        "field_non_null_counts_raw_visible": raw_counts,
        "field_non_null_counts_after_join": joined_counts,
        "field_non_null_counts_after_lookback": lookback_counts,
        "derivative_value_coverage_status": _derivative_value_coverage_status(coverage),
        "lookahead_policy": coverage.get("lookahead_policy"),
    }


def _ga_fold_diagnostics(
    candidates: list[Mapping[str, Any]],
    oos_stability: Mapping[str, Any],
) -> dict[str, Any]:
    best_by_fold: dict[int, Mapping[str, Any]] = {}
    for candidate in candidates:
        fold_id = _int_or_zero(candidate.get("fold_id"))
        if fold_id <= 0:
            continue
        current = best_by_fold.get(fold_id)
        if current is None or _float_value(candidate.get("validation_fitness")) > _float_value(current.get("validation_fitness")):
            best_by_fold[fold_id] = candidate
    fold_rows: list[dict[str, Any]] = []
    for fold in _mapping_rows(oos_stability.get("folds")):
        fold_id = _int_or_zero(fold.get("fold_id"))
        candidate = best_by_fold.get(fold_id)
        validation_metrics = _mapping(candidate.get("validation_metrics")) if candidate else fold
        row = {
            "fold_id": fold_id,
            "passed": bool(fold.get("passed")),
            "expression_hash": candidate.get("expression_hash") if candidate else None,
            "candidate_id": candidate.get("candidate_id") if candidate else None,
            "validation_profit_factor": _float_value(validation_metrics.get("profit_factor")),
            "validation_total_return": _float_value(validation_metrics.get("total_return")),
            "validation_rank_ic": _float_value(validation_metrics.get("rank_ic")),
            "validation_max_drawdown": _float_value(validation_metrics.get("max_drawdown")),
            "validation_turnover": _float_value(validation_metrics.get("turnover")),
            "validation_exposure": _float_value(validation_metrics.get("exposure")),
            "cost_stress_surviving_scenarios": _candidate_surviving_cost_scenarios(candidate or {}),
            "failure_reasons": _candidate_failure_reasons(candidate) if candidate else _fold_failure_reasons(fold),
        }
        fold_rows.append(row)
    return {
        "fold_count": _int_or_zero(oos_stability.get("fold_count")) or len(fold_rows),
        "pass_rate": round(_float_value(oos_stability.get("pass_rate")), 6),
        "median_validation_profit_factor": round(_float_value(oos_stability.get("median_validation_pf")), 6),
        "failed_fold_ids": [row["fold_id"] for row in fold_rows if not row["passed"]],
        "folds": fold_rows,
    }


def _ga_candidate_diagnostics(candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [_ga_candidate_diagnostic_row(candidate) for candidate in candidates]
    train_positive = sum(
        1
        for candidate in candidates
        if _metric(candidate, "train_metrics", "profit_factor") >= 1.0
        and _metric(candidate, "train_metrics", "total_return") >= 0.0
    )
    validation_positive = sum(
        1
        for candidate in candidates
        if _metric(candidate, "validation_metrics", "profit_factor") >= 1.0
        and _metric(candidate, "validation_metrics", "total_return") >= 0.0
    )
    return {
        "selected_candidate_count": len(candidates),
        "train_positive_candidate_count": train_positive,
        "validation_positive_candidate_count": validation_positive,
        "candidates": rows,
    }


def _ga_candidate_diagnostic_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    train_pf = _metric(candidate, "train_metrics", "profit_factor")
    validation_pf = _metric(candidate, "validation_metrics", "profit_factor")
    pf_decay = None if train_pf <= 0.0 else round(1.0 - validation_pf / train_pf, 6)
    return {
        "candidate_id": candidate.get("candidate_id"),
        "expression_hash": candidate.get("expression_hash"),
        "fold_id": _int_or_zero(candidate.get("fold_id")),
        "complexity": _int_or_zero(candidate.get("complexity")),
        "depth": _int_or_zero(candidate.get("depth")),
        "train_profit_factor": train_pf,
        "validation_profit_factor": validation_pf,
        "train_total_return": _metric(candidate, "train_metrics", "total_return"),
        "validation_total_return": _metric(candidate, "validation_metrics", "total_return"),
        "train_rank_ic": _metric(candidate, "train_metrics", "rank_ic"),
        "validation_rank_ic": _metric(candidate, "validation_metrics", "rank_ic"),
        "validation_max_drawdown": _metric(candidate, "validation_metrics", "max_drawdown"),
        "validation_turnover": _metric(candidate, "validation_metrics", "turnover"),
        "validation_exposure": _metric(candidate, "validation_metrics", "exposure"),
        "train_to_validation_profit_factor_decay": pf_decay,
        "cost_stress_surviving_scenarios": _candidate_surviving_cost_scenarios(candidate),
        "failure_reasons": _candidate_failure_reasons(candidate),
        "expression": candidate.get("expression"),
    }


def _ga_cost_diagnostics(candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    scenario_names = sorted(
        {
            str(name)
            for candidate in candidates
            for name in _mapping(candidate.get("cost_stress")).keys()
        }
    )
    scenario_survival_counts = dict.fromkeys(scenario_names, 0)
    any_survive = 0
    all_survive = 0
    none_survive = 0
    for candidate in candidates:
        survived = set(_candidate_surviving_cost_scenarios(candidate))
        if survived:
            any_survive += 1
        else:
            none_survive += 1
        if scenario_names and len(survived) == len(scenario_names):
            all_survive += 1
        for scenario in survived:
            scenario_survival_counts[scenario] = scenario_survival_counts.get(scenario, 0) + 1
    return {
        "candidate_count": len(candidates),
        "scenario_count": len(scenario_names),
        "scenario_survival_counts": scenario_survival_counts,
        "candidate_any_scenario_survival_count": any_survive,
        "candidate_all_scenario_survival_count": all_survive,
        "candidate_no_scenario_survival_count": none_survive,
        "base_survival_count": scenario_survival_counts.get("base", 0),
    }


def _ga_primitive_usage(candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    primitive_counts: dict[str, int] = {}
    operator_counts: dict[str, int] = {}
    depths: list[int] = []
    complexities: list[int] = []
    for candidate in candidates:
        _collect_expression_usage(_mapping(candidate.get("expression")), primitive_counts, operator_counts)
        depths.append(_int_or_zero(candidate.get("depth")))
        complexities.append(_int_or_zero(candidate.get("complexity")))
    return {
        "primitive_counts": dict(sorted(primitive_counts.items())),
        "operator_counts": dict(sorted(operator_counts.items())),
        "max_depth": max(depths) if depths else 0,
        "max_complexity": max(complexities) if complexities else 0,
        "median_depth": round(float(np.median(depths)), 6) if depths else 0.0,
        "median_complexity": round(float(np.median(complexities)), 6) if complexities else 0.0,
    }


def _ga_recommended_next_actions(summary: Mapping[str, Any]) -> list[str]:
    reasons = set(str(item) for item in summary.get("failure_reasons", []) if item)
    actions = ["do_not_promote_current_ga_batch_to_paper_or_live"]
    if "derivatives_market_time_overlap_missing" in reasons:
        actions.append("refresh_or_backfill_btc_1h_ohlcv_to_overlap_sentiment_window_before_remining")
    if "derivatives_value_coverage_zero_after_merge" in reasons or "derivatives_value_coverage_partial_after_merge" in reasons:
        actions.append("repair_or_verify_derivatives_sentiment_field_mapping_before_remining")
    if "derivatives_value_coverage_zero_after_join" in reasons:
        actions.append("repair_derivatives_sentiment_timestamp_alignment_before_remining")
    if "oos_stability_pass_rate_zero" in reasons or "median_validation_profit_factor_below_1" in reasons:
        actions.append("expand_history_and_rerun_walk_forward_research_only_before_any_paper_review")
    if "validation_signal_inactive_or_threshold_mismatch" in reasons:
        actions.append("review_threshold_policy_with_research_only_quantile_diagnostics")
    if "cost_stress_no_candidate_survives_any_scenario" in reasons:
        actions.append("tighten_turnover_penalty_or_test_longer_horizon_labels_in_research_only")
    if "no_candidates_selected" in reasons:
        actions.append("inspect_ga_search_space_and_data_quality_before_rerun")
    return _dedupe_text(actions)


def _btc_ga_candidate_review_row(
    candidate: Mapping[str, Any],
    *,
    rank: int,
    scenario_names: list[str],
) -> dict[str, Any]:
    expression = _mapping(candidate.get("expression"))
    primitive_counts: dict[str, int] = {}
    operator_counts: dict[str, int] = {}
    _collect_expression_usage(expression, primitive_counts, operator_counts)
    primitives = sorted(primitive_counts)
    operators = sorted(operator_counts)
    flags = _btc_ga_candidate_review_flags(candidate, primitives, scenario_names)
    verdict = _btc_ga_candidate_review_verdict(candidate, flags, scenario_names)
    family = _btc_ga_logic_family(primitives)
    validation_metrics = _mapping(candidate.get("validation_metrics"))
    train_metrics = _mapping(candidate.get("train_metrics"))
    stress = _btc_ga_cost_stress_summary(candidate, scenario_names)
    return {
        "rank": rank,
        "candidate_id": candidate.get("candidate_id"),
        "expression_hash": candidate.get("expression_hash"),
        "fold_id": _int_or_zero(candidate.get("fold_id")),
        "logic_family": family,
        "logic_family_zh": _logic_family_label_zh(family),
        "expression_human": _expression_to_review_text(expression),
        "expression_human_zh": _expression_to_review_text_zh(expression),
        "expression": candidate.get("expression"),
        "primitives": primitives,
        "operators": operators,
        "complexity": _int_or_zero(candidate.get("complexity")),
        "depth": _int_or_zero(candidate.get("depth")),
        "train_fitness": round(_float_value(candidate.get("train_fitness")), 6),
        "validation_fitness": round(_float_value(candidate.get("validation_fitness")), 6),
        "train_metrics": _review_metric_subset(train_metrics),
        "validation_metrics": _review_metric_subset(validation_metrics),
        "cost_stress_summary": stress,
        "cost_stress": candidate.get("cost_stress"),
        "review_flags": flags,
        "review_flags_zh": [_flag_label_zh(flag) for flag in flags],
        "review_verdict": verdict,
        "review_verdict_zh": _verdict_label_zh(verdict),
        "paper_candidate_allowed": False,
        "paper_queue_write_allowed": False,
        "next_allowed_state": "extended_research_only" if verdict != "reject_from_current_review" else "drop_or_rework_in_research",
    }


def _review_metric_subset(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "profit_factor": round(_float_value(metrics.get("profit_factor")), 6),
        "total_return": round(_float_value(metrics.get("total_return")), 6),
        "rank_ic": round(_float_value(metrics.get("rank_ic")), 6),
        "max_drawdown": round(_float_value(metrics.get("max_drawdown")), 6),
        "turnover": round(_float_value(metrics.get("turnover")), 6),
        "exposure": round(_float_value(metrics.get("exposure")), 6),
        "hit_rate": round(_float_value(metrics.get("hit_rate")), 6),
        "observations": _int_or_zero(metrics.get("observations")),
        "threshold": round(_float_value(metrics.get("threshold")), 6),
        "direction": _int_or_zero(metrics.get("direction")),
    }


def _btc_ga_cost_stress_summary(candidate: Mapping[str, Any], scenario_names: list[str]) -> dict[str, Any]:
    survived = _candidate_surviving_cost_scenarios(candidate)
    return {
        "scenario_count": len(scenario_names),
        "survival_count": len(survived),
        "surviving_scenarios": survived,
        "base_survives": "base" in survived,
        "all_stress_survives": bool(scenario_names) and len(survived) == len(scenario_names),
    }


def _btc_ga_candidate_review_flags(
    candidate: Mapping[str, Any],
    primitives: list[str],
    scenario_names: list[str],
) -> list[str]:
    flags = ["fold_specific_candidate_not_global_approval", "sample_short_720h_research_only"]
    validation_pf = _metric(candidate, "validation_metrics", "profit_factor")
    validation_return = _metric(candidate, "validation_metrics", "total_return")
    validation_rank_ic = _metric(candidate, "validation_metrics", "rank_ic")
    validation_drawdown = _metric(candidate, "validation_metrics", "max_drawdown")
    validation_turnover = _metric(candidate, "validation_metrics", "turnover")
    validation_exposure = _metric(candidate, "validation_metrics", "exposure")
    survived = _candidate_surviving_cost_scenarios(candidate)
    train_pf = _metric(candidate, "train_metrics", "profit_factor")
    if validation_pf < 1.0:
        flags.append("validation_profit_factor_below_1")
    if validation_return <= 0.0:
        flags.append("validation_return_non_positive")
    if abs(validation_rank_ic) < 0.05:
        flags.append("validation_rank_ic_abs_below_0_05")
    if validation_drawdown <= -0.10:
        flags.append("validation_drawdown_worse_than_10pct")
    elif validation_drawdown <= -0.05:
        flags.append("validation_drawdown_worse_than_5pct")
    if validation_exposure <= 0.0:
        flags.append("validation_signal_inactive_or_threshold_mismatch")
    if validation_turnover >= 0.20:
        flags.append("validation_turnover_high_for_1h_candidate")
    if not survived:
        flags.append("cost_stress_no_scenario_survives")
    elif scenario_names and len(survived) < len(scenario_names):
        flags.append("cost_stress_not_full_survival")
    if train_pf > 0.0 and validation_pf / train_pf < 0.5:
        flags.append("train_validation_pf_decay_gt_50pct")
    if any(primitive.startswith("funding") for primitive in primitives):
        flags.append("funding_dominant_logic_needs_economic_review")
    if not any(_primitive_is_derivative_sentiment(primitive) for primitive in primitives):
        flags.append("price_only_candidate_missing_derivatives_edge")
    return _dedupe_text(flags)


def _btc_ga_candidate_review_verdict(
    candidate: Mapping[str, Any],
    flags: list[str],
    scenario_names: list[str],
) -> str:
    validation_pf = _metric(candidate, "validation_metrics", "profit_factor")
    validation_return = _metric(candidate, "validation_metrics", "total_return")
    survived = _candidate_surviving_cost_scenarios(candidate)
    if validation_pf < 1.0 or validation_return <= 0.0 or not survived:
        return "reject_from_current_review"
    if "validation_drawdown_worse_than_10pct" in flags:
        return "needs_manual_drawdown_review"
    if "cost_stress_not_full_survival" in flags:
        return "needs_cost_stress_review"
    if "validation_rank_ic_abs_below_0_05" in flags:
        return "needs_manual_ic_review"
    if scenario_names and len(survived) == len(scenario_names):
        return "promising_for_extended_research"
    return "needs_manual_review"


def _btc_ga_review_summary(candidate_reviews: list[Mapping[str, Any]]) -> dict[str, Any]:
    verdict_counts: dict[str, int] = {}
    for row in candidate_reviews:
        verdict = str(row.get("review_verdict") or "unknown")
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    promising = sum(
        1
        for row in candidate_reviews
        if str(row.get("review_verdict")) == "promising_for_extended_research"
    )
    rejected = sum(
        1
        for row in candidate_reviews
        if str(row.get("review_verdict")) == "reject_from_current_review"
    )
    return {
        "candidate_count": len(candidate_reviews),
        "extended_research_shortlist_count": promising,
        "manual_review_count": len(candidate_reviews) - promising - rejected,
        "reject_count": rejected,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "paper_candidate_generated": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _btc_ga_logic_family_summary(candidate_reviews: list[Mapping[str, Any]]) -> dict[str, Any]:
    family_counts: dict[str, int] = {}
    for row in candidate_reviews:
        family = str(row.get("logic_family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1
    return {
        "family_counts": dict(sorted(family_counts.items())),
        "dominant_family": max(family_counts, key=family_counts.get) if family_counts else None,
    }


def _btc_ga_review_holdout_summary(holdout: Mapping[str, Any]) -> dict[str, Any]:
    if not holdout or holdout.get("enabled") is not True:
        return {
            "enabled": False,
            "status": "not_requested",
            "status_zh": "未启用",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    status = str(holdout.get("status") or "")
    status_zh = {
        "complete": "已完成，GA 选择阶段未使用 holdout",
        "blocked": "阻塞，holdout 数据不足或评估失败",
    }.get(status, status)
    return {
        "enabled": True,
        "status": status,
        "status_zh": status_zh,
        "requested_hours": _int_or_zero(holdout.get("requested_hours")),
        "selection_rows": _int_or_zero(holdout.get("selection_rows")),
        "holdout_rows": _int_or_zero(holdout.get("holdout_rows")),
        "ga_selection_used_holdout": bool(holdout.get("ga_selection_used_holdout")),
        "surviving_candidate_count": _int_or_zero(holdout.get("surviving_candidate_count")),
        "shortlist_for_extended_research_only": [
            str(item) for item in holdout.get("shortlist_for_extended_research_only", []) if item
        ],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _btc_ga_manual_review_questions(candidate_reviews: list[Mapping[str, Any]]) -> list[str]:
    questions = [
        "Does the expression have a plausible economic rationale beyond curve fitting?",
        "Does the factor still work after extending BTC 1H history to at least 90 to 180 days?",
        "Does performance survive a confirmatory holdout that GA never used for selection?",
        "Are turnover, exposure, and drawdown acceptable after realistic exchange costs?",
    ]
    if any("funding_dominant_logic_needs_economic_review" in row.get("review_flags", []) for row in candidate_reviews):
        questions.append("Is the funding signal robust to funding timestamp conventions and hourly approximation error?")
    if any("price_only_candidate_missing_derivatives_edge" in row.get("review_flags", []) for row in candidate_reviews):
        questions.append("Does the price-only candidate add anything beyond the existing BTC trend research line?")
    return _dedupe_text(questions)


def _btc_ga_review_recommended_actions(
    candidate_reviews: list[Mapping[str, Any]],
    blockers: list[str],
) -> list[str]:
    actions = ["do_not_write_paper_queue_or_live_unlock_from_this_packet"]
    if blockers:
        actions.append("fix_review_packet_blockers_before_manual_review")
        return _dedupe_text(actions)
    actions.extend(
        [
            "extend_btc_1h_history_to_90_180_days_before_paper_review",
            "rerun_ga_with_confirmatory_holdout_and_regime_splits",
            "compare_shortlisted_expressions_against_existing_btc_trend_baselines",
        ]
    )
    if any(row.get("review_verdict") == "promising_for_extended_research" for row in candidate_reviews):
        actions.append("carry_promising_expressions_to_extended_research_only_shortlist")
    if any(row.get("review_verdict") == "reject_from_current_review" for row in candidate_reviews):
        actions.append("drop_rejected_current_candidates_from_shortlist_unless_reworked")
    if any("funding_dominant_logic_needs_economic_review" in row.get("review_flags", []) for row in candidate_reviews):
        actions.append("manually_review_funding_dominant_candidates_for_timestamp_and_cost_assumptions")
    if any("validation_drawdown_worse_than_10pct" in row.get("review_flags", []) for row in candidate_reviews):
        actions.append("run_drawdown_and_regime_attribution_before_any_candidate_gate")
    return _dedupe_text(actions)


def _review_cost_scenario_names(candidates: list[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(name)
            for candidate in candidates
            for name in _mapping(candidate.get("cost_stress")).keys()
        }
    )


def _btc_ga_logic_family(primitives: list[str]) -> str:
    primitive_set = set(primitives)
    has_funding = any(primitive.startswith("funding") for primitive in primitive_set)
    has_liquidation = any("liquidation" in primitive for primitive in primitive_set)
    has_long_short = any("long_short" in primitive for primitive in primitive_set)
    has_oi = any("open_interest" in primitive for primitive in primitive_set)
    has_momentum = bool({"momentum_24h", "return_1h", "return_4h"} & primitive_set)
    has_vol = "realized_vol_24h" in primitive_set or "range_pct" in primitive_set
    if has_funding and has_vol:
        return "funding_volatility_interaction"
    if has_funding:
        return "funding_pressure"
    if has_liquidation:
        return "liquidation_pressure"
    if has_long_short:
        return "long_short_sentiment"
    if has_oi:
        return "open_interest_positioning"
    if has_momentum:
        return "price_momentum_trend"
    if has_vol:
        return "price_volatility"
    return "mixed_or_other"


def _primitive_is_derivative_sentiment(primitive: str) -> bool:
    return (
        primitive.startswith("funding")
        or primitive.startswith("open_interest")
        or "liquidation" in primitive
        or primitive.startswith("long_short")
    )


def _expression_to_review_text(expression: Mapping[str, Any]) -> str:
    if not expression:
        return "empty expression"
    op = str(expression.get("op") or "")
    if op == "primitive":
        return _primitive_review_label(str(expression.get("primitive") or "unknown"))
    if op == "const":
        return _format_float(expression.get("value"))
    args = [_expression_to_review_text(child) for child in _mapping_rows(expression.get("args"))]
    if op == "rolling_z":
        window = _int_or_zero(expression.get("window")) or 24
        inner = args[0] if args else "signal"
        return f"{window}h rolling z-score of ({inner})"
    if op == "gate":
        signal = args[0] if args else "signal"
        condition = args[1] if len(args) > 1 else "condition"
        return f"({signal}) active only when ({condition}) is positive"
    if op == "safe_ratio":
        left = args[0] if args else "left"
        right = args[1] if len(args) > 1 else "right"
        return f"safe ratio of ({left}) to ({right})"
    if op in {"add", "sub", "mul"}:
        symbol = {"add": "+", "sub": "-", "mul": "*"}[op]
        joiner = f" {symbol} "
        return f"({joiner.join(args)})" if args else op
    if op in {"clip", "tanh", "sign"}:
        inner = args[0] if args else "signal"
        return f"{op}({inner})"
    return f"{op}({', '.join(args)})" if args else op


def _primitive_review_label(primitive: str) -> str:
    labels = {
        "return_1h": "1h return",
        "return_4h": "4h return",
        "momentum_24h": "24h momentum",
        "realized_vol_24h": "24h realized volatility",
        "range_pct": "hourly range percentage",
        "volume_z_24": "24h volume z-score",
        "open_interest_z_24": "24h open interest z-score",
        "open_interest_delta_1h": "1h open interest change",
        "funding_rate": "funding rate",
        "funding_z_24": "24h funding z-score",
        "funding_delta_1h": "1h funding change",
        "liquidation_z_24": "24h liquidation z-score",
        "liquidation_imbalance": "long-short liquidation imbalance",
        "long_short_ratio": "long-short ratio",
        "long_short_z_24": "24h long-short ratio z-score",
        "long_short_delta_1h": "1h long-short ratio change",
    }
    return labels.get(primitive, primitive)


def _expression_to_review_text_zh(expression: Mapping[str, Any]) -> str:
    if not expression:
        return "空表达式"
    op = str(expression.get("op") or "")
    if op == "primitive":
        return _primitive_review_label_zh(str(expression.get("primitive") or "unknown"))
    if op == "const":
        return _format_float(expression.get("value"))
    args = [_expression_to_review_text_zh(child) for child in _mapping_rows(expression.get("args"))]
    if op == "rolling_z":
        window = _int_or_zero(expression.get("window")) or 24
        inner = args[0] if args else "信号"
        return f"对（{inner}）做 {window} 小时滚动 z-score 标准化"
    if op == "gate":
        signal = args[0] if args else "信号"
        condition = args[1] if len(args) > 1 else "条件"
        return f"只有当（{condition}）为正时，启用（{signal}）"
    if op == "safe_ratio":
        left = args[0] if args else "分子"
        right = args[1] if len(args) > 1 else "分母"
        return f"安全相除：（{left}）除以（{right}）"
    if op in {"add", "sub", "mul"}:
        symbol = {"add": "+", "sub": "-", "mul": "*"}[op]
        joiner = f" {symbol} "
        return f"（{joiner.join(args)}）" if args else op
    if op == "clip":
        inner = args[0] if args else "信号"
        return f"截断极端值后的（{inner}）"
    if op == "tanh":
        inner = args[0] if args else "信号"
        return f"tanh 压缩后的（{inner}）"
    if op == "sign":
        inner = args[0] if args else "信号"
        return f"只保留方向符号的（{inner}）"
    return f"{op}（{', '.join(args)}）" if args else op


def _primitive_review_label_zh(primitive: str) -> str:
    labels = {
        "return_1h": "1 小时收益率",
        "return_4h": "4 小时收益率",
        "momentum_24h": "24 小时动量",
        "realized_vol_24h": "24 小时已实现波动率",
        "range_pct": "小时振幅比例",
        "volume_z_24": "24 小时成交量 z-score",
        "open_interest_z_24": "24 小时 OI z-score",
        "open_interest_delta_1h": "1 小时 OI 变化",
        "funding_rate": "资金费率",
        "funding_z_24": "24 小时资金费率 z-score",
        "funding_delta_1h": "1 小时资金费率变化",
        "liquidation_z_24": "24 小时爆仓额 z-score",
        "liquidation_imbalance": "多空爆仓不平衡",
        "long_short_ratio": "多空比",
        "long_short_z_24": "24 小时多空比 z-score",
        "long_short_delta_1h": "1 小时多空比变化",
    }
    return labels.get(primitive, primitive)


def _status_label_zh(status: Any) -> str:
    labels = {
        "complete": "完成",
        "blocked": "阻塞",
    }
    value = str(status or "")
    return f"{labels.get(value, value)} ({value})" if value else ""


def _decision_label_zh(decision: Any) -> str:
    labels = {
        "research_only_candidate_review_packet": "仅研究复核包，不允许进入 paper/live",
        "research_only_expression_review": "仅研究表达式复核",
        "research_only_ga_factor_failure_diagnostics": "仅研究诊断",
    }
    value = str(decision or "")
    return f"{labels.get(value, value)} ({value})" if value else ""


def _logic_family_label_zh(family: Any) -> str:
    labels = {
        "funding_pressure": "资金费率压力",
        "funding_volatility_interaction": "资金费率与波动率交互",
        "liquidation_pressure": "爆仓压力",
        "long_short_sentiment": "多空比情绪",
        "open_interest_positioning": "OI 持仓定位",
        "price_momentum_trend": "价格动量趋势",
        "price_volatility": "价格波动率",
        "mixed_or_other": "混合或其他",
    }
    return labels.get(str(family or ""), str(family or ""))


def _verdict_label_zh(verdict: Any) -> str:
    labels = {
        "promising_for_extended_research": "可进入扩展研究短名单",
        "needs_manual_drawdown_review": "需要人工复核回撤风险",
        "needs_cost_stress_review": "需要人工复核成本压力",
        "needs_manual_ic_review": "需要人工复核 IC 稳定性",
        "needs_manual_review": "需要人工复核",
        "reject_from_current_review": "当前批次剔除",
    }
    return labels.get(str(verdict or ""), str(verdict or ""))


def _flag_label_zh(flag: Any) -> str:
    labels = {
        "fold_specific_candidate_not_global_approval": "只是在某个 walk-forward 折上胜出，不代表全局批准",
        "sample_short_720h_research_only": "样本只有约 720 小时，只能做研究初筛",
        "validation_profit_factor_below_1": "验证集 PF 小于 1",
        "validation_return_non_positive": "验证集收益不为正",
        "validation_rank_ic_abs_below_0_05": "验证集 IC 绝对值低于 0.05",
        "validation_drawdown_worse_than_10pct": "验证集最大回撤超过 10%",
        "validation_drawdown_worse_than_5pct": "验证集最大回撤超过 5%",
        "validation_signal_inactive_or_threshold_mismatch": "验证集信号不活跃或阈值不匹配",
        "validation_turnover_high_for_1h_candidate": "1 小时因子换手偏高",
        "cost_stress_no_scenario_survives": "没有通过任何成本压力场景",
        "cost_stress_not_full_survival": "没有通过全部成本压力场景",
        "train_validation_pf_decay_gt_50pct": "训练到验证 PF 衰减超过 50%",
        "funding_dominant_logic_needs_economic_review": "资金费率主导，需要复核经济含义和时间戳假设",
        "price_only_candidate_missing_derivatives_edge": "价格类候选，没有体现衍生品情绪增量",
    }
    return labels.get(str(flag or ""), str(flag or ""))


def _action_label_zh(action: Any) -> str:
    labels = {
        "do_not_write_paper_queue_or_live_unlock_from_this_packet": "不要根据这个复核包写入 paper 队列，也不要解锁 live",
        "fix_review_packet_blockers_before_manual_review": "先修复复核包阻塞项，再做人工复核",
        "extend_btc_1h_history_to_90_180_days_before_paper_review": "把 BTC 1H 历史扩展到至少 90 到 180 天，再讨论 paper 复核",
        "rerun_ga_with_confirmatory_holdout_and_regime_splits": "用确认性 holdout 和行情分段重新跑 GA",
        "compare_shortlisted_expressions_against_existing_btc_trend_baselines": "把短名单表达式与现有 BTC 趋势基线比较",
        "carry_promising_expressions_to_extended_research_only_shortlist": "把较好的表达式只放入扩展研究短名单",
        "drop_rejected_current_candidates_from_shortlist_unless_reworked": "当前批次剔除的候选不进短名单，除非重新设计",
        "manually_review_funding_dominant_candidates_for_timestamp_and_cost_assumptions": "人工复核资金费率类候选的时间戳和成本近似假设",
        "run_drawdown_and_regime_attribution_before_any_candidate_gate": "任何候选进入门禁前，先做回撤和行情分段归因",
    }
    return labels.get(str(action or ""), str(action or ""))


def _question_label_zh(question: Any) -> str:
    labels = {
        "Does the expression have a plausible economic rationale beyond curve fitting?": "这个表达式是否有可解释的经济逻辑，而不只是拟合出来的形状？",
        "Does the factor still work after extending BTC 1H history to at least 90 to 180 days?": "把 BTC 1H 历史扩展到至少 90 到 180 天后，它是否仍然有效？",
        "Does performance survive a confirmatory holdout that GA never used for selection?": "在 GA 完全没见过的确认性 holdout 上，表现是否还能保住？",
        "Are turnover, exposure, and drawdown acceptable after realistic exchange costs?": "加入更真实的交易所费用后，换手、暴露和回撤是否还能接受？",
        "Is the funding signal robust to funding timestamp conventions and hourly approximation error?": "资金费率信号是否对时间戳口径和小时摊销误差足够稳健？",
        "Does the price-only candidate add anything beyond the existing BTC trend research line?": "价格类候选是否比现有 BTC 趋势研究线提供了新增信息？",
    }
    return labels.get(str(question or ""), str(question or ""))


def _next_state_label_zh(state: Any) -> str:
    labels = {
        "extended_research_only": "仅允许进入扩展研究",
        "drop_or_rework_in_research": "在研究层剔除或重新设计",
    }
    value = str(state or "")
    return f"{labels.get(value, value)} ({value})" if value else ""


def _candidate_failure_reasons(candidate: Mapping[str, Any] | None) -> list[str]:
    if not candidate:
        return ["candidate_missing_for_fold"]
    reasons: list[str] = []
    train_pf = _metric(candidate, "train_metrics", "profit_factor")
    validation_pf = _metric(candidate, "validation_metrics", "profit_factor")
    validation_return = _metric(candidate, "validation_metrics", "total_return")
    validation_rank_ic = _metric(candidate, "validation_metrics", "rank_ic")
    train_rank_ic = _metric(candidate, "train_metrics", "rank_ic")
    validation_drawdown = _metric(candidate, "validation_metrics", "max_drawdown")
    validation_exposure = _metric(candidate, "validation_metrics", "exposure")
    if validation_pf < 1.0:
        reasons.append("validation_profit_factor_below_1")
    if validation_return < 0.0:
        reasons.append("validation_total_return_negative")
    if validation_exposure <= 0.0:
        reasons.append("validation_signal_inactive_or_threshold_mismatch")
    if abs(validation_rank_ic) < 0.05:
        reasons.append("validation_rank_ic_abs_below_0_05")
    if validation_drawdown <= -0.05:
        reasons.append("validation_drawdown_worse_than_5pct")
    if not _candidate_surviving_cost_scenarios(candidate):
        reasons.append("cost_stress_no_scenario_survives")
    if train_pf > 0.0 and validation_pf / train_pf < 0.5:
        reasons.append("train_validation_pf_decay_gt_50pct")
    if train_rank_ic * validation_rank_ic < 0.0:
        reasons.append("train_validation_rank_ic_sign_flip")
    return _dedupe_text(reasons)


def _fold_failure_reasons(fold: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _float_value(fold.get("profit_factor")) < 1.0:
        reasons.append("validation_profit_factor_below_1")
    if _float_value(fold.get("max_drawdown")) <= -0.05:
        reasons.append("validation_drawdown_worse_than_5pct")
    if abs(_float_value(fold.get("rank_ic"))) < 0.05:
        reasons.append("validation_rank_ic_abs_below_0_05")
    return _dedupe_text(reasons)


def _candidate_surviving_cost_scenarios(candidate: Mapping[str, Any]) -> list[str]:
    survived: list[str] = []
    for name, scenario in _mapping(candidate.get("cost_stress")).items():
        if _mapping(scenario).get("survives") is True:
            survived.append(str(name))
    return sorted(survived)


def _metric(candidate: Mapping[str, Any], section: str, name: str) -> float:
    return _float_value(_mapping(candidate.get(section)).get(name))


def _derivative_value_coverage_status(coverage: Mapping[str, Any]) -> str:
    visible_rows = _int_or_zero(coverage.get("derivatives_visible_rows"))
    raw_counts = _mapping(coverage.get("field_non_null_counts_raw_visible"))
    field_counts = _mapping(
        coverage.get("field_non_null_counts_after_lookback")
        or coverage.get("field_non_null_counts_after_join")
        or coverage.get("field_non_null_counts")
    )
    raw_values = [_int_or_zero(raw_counts.get(field)) for field in _derivative_value_fields()]
    values = [_int_or_zero(field_counts.get(field)) for field in _derivative_value_fields()]
    if visible_rows <= 0:
        return "no_visible_derivatives_rows"
    if raw_counts and sum(raw_values) <= 0:
        return "visible_rows_but_value_fields_zero"
    if raw_counts and sum(raw_values) > 0 and "derivatives_market_overlap_rows" in coverage:
        if _int_or_zero(coverage.get("derivatives_market_overlap_rows")) <= 0:
            return "no_market_derivatives_time_overlap"
    if sum(values) <= 0:
        return "joined_value_fields_zero" if raw_counts else "visible_rows_but_value_fields_zero"
    if any(value <= 0 for value in values):
        return "partial_value_field_coverage"
    return "value_fields_present"


def _normalize_derivative_counts(counts: Mapping[str, Any]) -> dict[str, int]:
    return {field: _int_or_zero(counts.get(field)) for field in _derivative_value_fields()}


def _collect_expression_usage(
    expression: Mapping[str, Any],
    primitive_counts: dict[str, int],
    operator_counts: dict[str, int],
) -> None:
    if not expression:
        return
    op = str(expression.get("op") or "")
    if op:
        operator_counts[op] = operator_counts.get(op, 0) + 1
    primitive_name = str(expression.get("primitive") or "")
    if primitive_name:
        primitive_counts[primitive_name] = primitive_counts.get(primitive_name, 0) + 1
    children = expression.get("args", [])
    if not isinstance(children, list):
        return
    for child in children:
        if isinstance(child, Mapping):
            _collect_expression_usage(child, primitive_counts, operator_counts)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _read_json_mapping(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    number = _float_or_none(value)
    return float(number) if number is not None else 0.0


def _report_datetime(value: Any, *, default: datetime) -> datetime:
    try:
        return _parse_utc(value)
    except (TypeError, ValueError):
        return _ensure_utc(default)


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _frame_hash_payload(frame: pd.DataFrame, columns: Sequence[str]) -> dict[str, Any]:
    selected = frame[[column for column in columns if column in frame]].tail(2000).copy()
    return {
        "row_count": len(frame),
        "start": frame.index[0].isoformat() if len(frame) else None,
        "end": frame.index[-1].isoformat() if len(frame) else None,
        "tail_rows": selected.reset_index().to_dict(orient="records"),
    }


def _profit_factor(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    gains = float(values[values > 0.0].sum())
    losses = abs(float(values[values < 0.0].sum()))
    if losses <= 1e-12:
        return 999.0 if gains > 0.0 else 0.0
    return round(gains / losses, 6)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).cumprod()
    if equity.empty:
        return 0.0
    drawdown = equity / equity.cummax().replace(0, np.nan) - 1.0
    return float(drawdown.min() or 0.0)


def _rank_ic(factor: pd.Series, label: pd.Series) -> float:
    pair = pd.DataFrame({"factor": factor, "label": label}).dropna()
    if len(pair) < 3:
        return 0.0
    if pair["factor"].nunique(dropna=True) < 2 or pair["label"].nunique(dropna=True) < 2:
        return 0.0
    value = pair["factor"].rank().corr(pair["label"].rank())
    if value is None or value != value:
        return 0.0
    return float(value)


def _default_decision_time(rows: Sequence[Mapping[str, Any]]) -> datetime:
    times: list[datetime] = []
    for row in rows:
        try:
            times.append(_parse_utc(row.get("available_time")))
        except (TypeError, ValueError):
            continue
    return max(times) if times else datetime.now(timezone.utc)


def _parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return _ensure_utc(datetime.fromisoformat(text))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(_ensure_utc(value).timestamp() * 1000)


def _float_or_none(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _git_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _format_float(value: Any) -> str:
    return f"{_float_value(value):.6g}"


def _format_pct(value: Any) -> str:
    return f"{_float_value(value) * 100:.2f}%"
