from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pandas as pd

from .build_covariance import build_covariance
from .build_expected_returns import build_expected_returns
from .schemas import (
    AdapterError,
    PortfolioAdapterConfig,
    build_run_manifest,
    constraints_hash,
    expected_returns_path,
    load_current_weights,
    load_portfolio_config,
    missing_pypfopt_error,
    normalize_current_weights,
    now_iso,
    portfolio_run_dir,
    project_long_only_weights,
    read_covariance_frame,
    read_expected_returns_frame,
    resolve_portfolio_run_id,
    run_manifest_path,
    scale_weights_for_turnover,
    target_weights_path,
    write_frame,
    write_json,
)


def optimize_weights(
    *,
    score_run_id: str,
    config: PortfolioAdapterConfig,
    portfolio_run_id: str | None = None,
) -> tuple[pd.DataFrame, Path, bool]:
    resolved_run_id = resolve_portfolio_run_id(config, portfolio_run_id)
    portfolio_run_dir(config, resolved_run_id)

    if not expected_returns_path(config, resolved_run_id).exists():
        build_expected_returns(score_run_id=score_run_id, config=config, portfolio_run_id=resolved_run_id)
    if not (portfolio_run_dir(config, resolved_run_id) / "covariance.parquet").exists():
        build_covariance(score_run_id=score_run_id, config=config, portfolio_run_id=resolved_run_id)

    expected_frame = read_expected_returns_frame(config, resolved_run_id)
    covariance_frame = read_covariance_frame(config, resolved_run_id)
    created_at = now_iso()
    requested_optimizer = config.optimizer
    dependency_available = importlib.util.find_spec("pypfopt") is not None
    raw_current_weights = load_current_weights(config.current_weights_path)
    current_weights = normalize_current_weights(raw_current_weights, config)
    current_weight_projection_used = _weights_changed(raw_current_weights, current_weights)
    constraints_digest = constraints_hash(config)
    any_fallback = bool(current_weight_projection_used)

    rows: list[dict[str, object]] = []
    previous_target_weights = dict(current_weights)

    for timestamp, group in expected_frame.groupby("datetime", sort=True):
        selected = group.sort_values(["rank", "symbol"]).reset_index(drop=True)
        mu = pd.Series(selected["expected_return"].to_numpy(), index=selected["symbol"].tolist(), dtype=float)
        covariance_rows = covariance_frame[covariance_frame["datetime"] == timestamp]
        cov_matrix = covariance_rows.pivot(index="symbol", columns="peer_symbol", values="covariance").reindex(
            index=mu.index,
            columns=mu.index,
            fill_value=0.0,
        )
        for symbol in cov_matrix.index:
            cov_matrix.loc[symbol, symbol] = float(cov_matrix.loc[symbol, symbol]) + 1e-8

        raw_weights, fallback_used = _solve_weights(
            mu=mu,
            cov_matrix=cov_matrix,
            config=config,
            dependency_available=dependency_available,
        )
        fallback_label = fallback_used or ("current_weight_projection" if current_weight_projection_used else "")
        any_fallback = any_fallback or bool(fallback_label)
        clipped_weights = project_long_only_weights(raw_weights, gross_cap=config.gross_cap, max_weight=config.max_weight)
        final_weights, turnover_scale, realized_turnover = scale_weights_for_turnover(
            previous_target_weights,
            clipped_weights,
            config.max_turnover,
        )
        previous_target_weights = dict(final_weights)

        symbols = set(previous_target_weights) | set(raw_weights) | set(clipped_weights) | set(final_weights)
        for symbol in sorted(symbols):
            rows.append(
                {
                    "portfolio_run_id": resolved_run_id,
                    "source_score_run_id": score_run_id,
                    "datetime": timestamp,
                    "symbol": symbol,
                    "target_weight": float(final_weights.get(symbol, 0.0)),
                    "raw_weight": float(raw_weights.get(symbol, 0.0)),
                    "clipped_weight": float(clipped_weights.get(symbol, 0.0)),
                    "optimizer": requested_optimizer,
                    "constraints_hash": constraints_digest,
                    "fallback": fallback_label,
                    "current_weight": float(current_weights.get(symbol, 0.0) if timestamp == expected_frame["datetime"].min() else 0.0),
                    "turnover_from_previous": float(realized_turnover),
                    "turnover_scale": float(turnover_scale),
                    "created_at": created_at,
                }
            )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values(["datetime", "symbol"]).reset_index(drop=True)

    output_path = target_weights_path(config, resolved_run_id)
    write_frame(frame, output_path)
    manifest_payload = build_run_manifest(
        portfolio_run_id=resolved_run_id,
        score_run_id=score_run_id,
        config=config,
        output_files={
            "expected_returns": str(expected_returns_path(config, resolved_run_id)),
            "covariance": str(portfolio_run_dir(config, resolved_run_id) / "covariance.parquet"),
            "target_weights": str(output_path),
        },
        dependency_available=dependency_available,
        fallback_used=any_fallback,
        generated_at=created_at,
    )
    write_json(run_manifest_path(config, resolved_run_id), manifest_payload)
    return frame, output_path, any_fallback


def _weights_changed(raw_weights: dict[str, float], normalized_weights: dict[str, float]) -> bool:
    symbols = set(raw_weights) | set(normalized_weights)
    return any(
        abs(float(raw_weights.get(symbol, 0.0)) - float(normalized_weights.get(symbol, 0.0))) > 1e-9
        for symbol in symbols
    )


def _solve_weights(
    *,
    mu: pd.Series,
    cov_matrix: pd.DataFrame,
    config: PortfolioAdapterConfig,
    dependency_available: bool,
) -> tuple[dict[str, float], str]:
    if config.optimizer == "equal_weight_topk":
        return _equal_weight_topk(mu.index.tolist(), config.gross_cap), "equal_weight_topk"

    if (
        config.fallback_optimizer == "equal_weight_topk"
        and float(cov_matrix.abs().to_numpy().sum()) <= max(1e-10, len(cov_matrix.index) * 1e-7)
    ):
        return _equal_weight_topk(mu.index.tolist(), config.gross_cap), "equal_weight_topk:degenerate_covariance"

    if not dependency_available:
        if config.fallback_optimizer == "equal_weight_topk":
            return _equal_weight_topk(mu.index.tolist(), config.gross_cap), "equal_weight_topk"
        raise missing_pypfopt_error()

    try:
        return _solve_with_pypfopt(mu=mu, cov_matrix=cov_matrix, config=config), ""
    except Exception as exc:
        if config.fallback_optimizer == "equal_weight_topk":
            return _equal_weight_topk(mu.index.tolist(), config.gross_cap), f"equal_weight_topk:{type(exc).__name__}"
        raise AdapterError(f"PyPortfolioOpt optimization failed for {config.optimizer}: {exc}") from exc


def _solve_with_pypfopt(
    *,
    mu: pd.Series,
    cov_matrix: pd.DataFrame,
    config: PortfolioAdapterConfig,
) -> dict[str, float]:
    from pypfopt import EfficientFrontier, HRPOpt

    internal_cap = min(1.0, config.max_weight / config.gross_cap) if config.gross_cap > 0 else 0.0
    if config.optimizer == "max_sharpe":
        frontier = EfficientFrontier(mu, cov_matrix, weight_bounds=(0.0, internal_cap))
        frontier.max_sharpe(risk_free_rate=config.risk_free_rate)
        weights = frontier.clean_weights()
    elif config.optimizer == "min_volatility":
        frontier = EfficientFrontier(mu, cov_matrix, weight_bounds=(0.0, internal_cap))
        frontier.min_volatility()
        weights = frontier.clean_weights()
    elif config.optimizer == "hrp":
        optimizer = HRPOpt(cov_matrix=cov_matrix)
        weights = optimizer.optimize()
    else:
        raise AdapterError(f"Unsupported optimizer: {config.optimizer}")

    cleaned = {str(symbol).upper(): max(0.0, float(weight)) for symbol, weight in weights.items() if float(weight) > 0.0}
    return {symbol: weight * config.gross_cap for symbol, weight in cleaned.items()}


def _equal_weight_topk(symbols: list[str], gross_cap: float) -> dict[str, float]:
    if not symbols or gross_cap <= 0.0:
        return {}
    weight = gross_cap / len(symbols)
    return {symbol: weight for symbol in symbols}


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize long-only target weights from Qlib score artifacts.")
    parser.add_argument("--score-run-id", required=True, help="Qlib score run id under artifacts/qlib_runs/<run_id>/")
    parser.add_argument("--config", required=True, help="Portfolio config yaml path.")
    parser.add_argument("--portfolio-run-id", required=False, help="Optional explicit portfolio run id.")
    parser.add_argument(
        "--fallback-optimizer",
        required=False,
        choices=["equal_weight_topk"],
        help="Explicit fallback when PyPortfolioOpt is unavailable or optimization fails.",
    )
    args = parser.parse_args()

    config = load_portfolio_config(args.config)
    if args.fallback_optimizer:
        config = config.with_overrides(fallback_optimizer=args.fallback_optimizer)

    frame, output_path, fallback_used = optimize_weights(
        score_run_id=args.score_run_id,
        config=config,
        portfolio_run_id=args.portfolio_run_id,
    )
    print(f"wrote target weights: {output_path}")
    print(
        "rows="
        f"{len(frame)} dates={frame['datetime'].nunique() if not frame.empty else 0} "
        f"fallback_used={str(fallback_used).lower()}"
    )


if __name__ == "__main__":
    main()
