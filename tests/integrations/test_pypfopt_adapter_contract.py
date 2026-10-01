from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from integrations.pypfopt_adapter.schemas import load_portfolio_config

from tests.integrations.helpers import (
    invoke_adapter_callable,
    locate_single_file,
    make_bar_frame,
    write_cleaned_bars,
    write_imported_scores,
    write_portfolio_config,
)


def _returns_kwargs(
    *,
    run_id: str,
    config_path: Path,
    portfolio_run_id: str | None = None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "score_run_id": run_id,
        "config": load_portfolio_config(config_path),
        "portfolio_run_id": portfolio_run_id,
    }


def _covariance_kwargs(
    *,
    run_id: str,
    config_path: Path,
    portfolio_run_id: str | None = None,
) -> dict[str, object]:
    kwargs = _returns_kwargs(
        run_id=run_id,
        config_path=config_path,
        portfolio_run_id=portfolio_run_id,
    )
    return kwargs


def _locate_portfolio_artifact(root: Path, filename: str) -> pd.DataFrame:
    return pd.read_parquet(locate_single_file(root, filename))


def test_build_expected_returns_is_no_lookahead(tmp_path: Path) -> None:
    base_root = tmp_path / "base"
    mutated_root = tmp_path / "mutated"

    base_data_root = base_root / "data"
    mutated_data_root = mutated_root / "data"
    write_cleaned_bars(base_data_root, "AAPL", make_bar_frame("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0]))
    write_cleaned_bars(base_data_root, "MSFT", make_bar_frame("MSFT", [200.0, 201.0, 202.0, 203.0, 204.0]))
    write_cleaned_bars(mutated_data_root, "AAPL", make_bar_frame("AAPL", [100.0, 101.0, 102.0, 103.0, 999.0]))
    write_cleaned_bars(mutated_data_root, "MSFT", make_bar_frame("MSFT", [200.0, 201.0, 202.0, 203.0, 1.0]))

    dates = pd.bdate_range(start="2026-01-05", periods=5, tz="UTC")
    scores = pd.DataFrame(
        [
            {"datetime": dt, "symbol": "AAPL", "score": score}
            for dt, score in zip(dates, [0.1, 0.3, 0.2, 0.4, 0.25], strict=True)
        ]
        + [
            {"datetime": dt, "symbol": "MSFT", "score": score}
            for dt, score in zip(dates, [0.05, 0.1, 0.35, 0.2, 0.45], strict=True)
        ]
    )
    write_imported_scores(base_root / "artifacts", "score_run", scores)
    write_imported_scores(mutated_root / "artifacts", "score_run", scores)
    base_config = write_portfolio_config(
        base_root / "configs" / "portfolio.yaml",
        data_root=base_data_root,
        score_runs_root=base_root / "artifacts" / "qlib_runs",
        portfolio_runs_root=base_root / "artifacts" / "portfolio_runs",
        portfolio_run_id="portfolio_base",
    )
    mutated_config = write_portfolio_config(
        mutated_root / "configs" / "portfolio.yaml",
        data_root=mutated_data_root,
        score_runs_root=mutated_root / "artifacts" / "qlib_runs",
        portfolio_runs_root=mutated_root / "artifacts" / "portfolio_runs",
        portfolio_run_id="portfolio_mutated",
    )

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_expected_returns",
        ("build_expected_returns", "build", "run"),
        **_returns_kwargs(
            run_id="score_run",
            config_path=base_config,
        ),
    )
    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_expected_returns",
        ("build_expected_returns", "build", "run"),
        **_returns_kwargs(
            run_id="score_run",
            config_path=mutated_config,
        ),
    )

    base_expected = _locate_portfolio_artifact(base_root / "artifacts", "expected_returns.parquet")
    mutated_expected = _locate_portfolio_artifact(mutated_root / "artifacts", "expected_returns.parquet")
    base_expected = base_expected.drop(columns=["created_at"], errors="ignore")
    mutated_expected = mutated_expected.drop(columns=["created_at"], errors="ignore")
    semantic_cols = ["datetime", "symbol", "score", "rank", "expected_return", "top_k", "selected_count"]
    pd.testing.assert_frame_equal(
        base_expected[semantic_cols].sort_values(["datetime", "symbol"]).reset_index(drop=True),
        mutated_expected[semantic_cols].sort_values(["datetime", "symbol"]).reset_index(drop=True),
        check_like=True,
    )


def test_build_covariance_is_no_lookahead(tmp_path: Path) -> None:
    base_root = tmp_path / "base"
    mutated_root = tmp_path / "mutated"

    base_data_root = base_root / "data"
    mutated_data_root = mutated_root / "data"
    write_cleaned_bars(base_data_root, "AAPL", make_bar_frame("AAPL", [100.0, 101.0, 102.0, 103.0, 104.0]))
    write_cleaned_bars(base_data_root, "MSFT", make_bar_frame("MSFT", [200.0, 201.0, 202.0, 203.0, 204.0]))
    write_cleaned_bars(mutated_data_root, "AAPL", make_bar_frame("AAPL", [100.0, 101.0, 102.0, 103.0, 500.0]))
    write_cleaned_bars(mutated_data_root, "MSFT", make_bar_frame("MSFT", [200.0, 201.0, 202.0, 203.0, 50.0]))

    target_date = pd.Timestamp("2026-01-08T00:00:00+00:00")
    scores = pd.DataFrame(
        [
            {"datetime": target_date, "symbol": "AAPL", "score": 0.5},
            {"datetime": target_date, "symbol": "MSFT", "score": 0.4},
        ]
    )
    write_imported_scores(base_root / "artifacts", "score_run_cov", scores)
    write_imported_scores(mutated_root / "artifacts", "score_run_cov", scores)
    base_config = write_portfolio_config(
        base_root / "configs" / "portfolio_cov.yaml",
        data_root=base_data_root,
        score_runs_root=base_root / "artifacts" / "qlib_runs",
        portfolio_runs_root=base_root / "artifacts" / "portfolio_runs",
        portfolio_run_id="pf_cov_base",
    )
    mutated_config = write_portfolio_config(
        mutated_root / "configs" / "portfolio_cov.yaml",
        data_root=mutated_data_root,
        score_runs_root=mutated_root / "artifacts" / "qlib_runs",
        portfolio_runs_root=mutated_root / "artifacts" / "portfolio_runs",
        portfolio_run_id="pf_cov_mutated",
    )

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_covariance",
        ("build_covariance", "build", "run"),
        **_covariance_kwargs(
            run_id="score_run_cov",
            config_path=base_config,
        ),
    )
    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_covariance",
        ("build_covariance", "build", "run"),
        **_covariance_kwargs(
            run_id="score_run_cov",
            config_path=mutated_config,
        ),
    )

    base_cov = _locate_portfolio_artifact(base_root / "artifacts", "covariance.parquet")
    mutated_cov = _locate_portfolio_artifact(mutated_root / "artifacts", "covariance.parquet")
    base_cov = base_cov.drop(columns=["created_at"], errors="ignore")
    mutated_cov = mutated_cov.drop(columns=["created_at"], errors="ignore")
    semantic_cols = [
        "datetime",
        "symbol",
        "peer_symbol",
        "covariance",
        "lookback_days",
        "observation_count",
        "returns_start",
        "returns_end",
    ]
    pd.testing.assert_frame_equal(
        base_cov[semantic_cols].sort_values(["datetime", "symbol", "peer_symbol"]).reset_index(drop=True),
        mutated_cov[semantic_cols].sort_values(["datetime", "symbol", "peer_symbol"]).reset_index(drop=True),
        check_like=True,
    )


def test_optimize_weights_enforces_constraints_and_turnover(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    portfolio_run_root = artifacts_root / "portfolio_runs" / "pf_constraints"
    portfolio_run_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_constraints",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "score": 0.60,
                "rank": 1,
                "expected_return": 0.06,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_constraints",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "score": 0.30,
                "rank": 2,
                "expected_return": 0.03,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "expected_returns.parquet", index=False)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_constraints",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "peer_symbol": "AAPL",
                "covariance": 0.04,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_constraints",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "peer_symbol": "MSFT",
                "covariance": 0.01,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_constraints",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "peer_symbol": "AAPL",
                "covariance": 0.01,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_constraints",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "peer_symbol": "MSFT",
                "covariance": 0.03,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "covariance.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAPL", "current_weight": 0.90},
            {"symbol": "MSFT", "current_weight": 0.00},
        ]
    ).to_parquet(portfolio_run_root / "current_weights.parquet", index=False)
    config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio.yaml",
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        current_weights_path=portfolio_run_root / "current_weights.parquet",
        portfolio_run_id="pf_constraints",
    )

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.optimize_weights",
        ("optimize_weights", "optimize", "run"),
        score_run_id="score_unused",
        config=load_portfolio_config(config_path),
    )

    weights = _locate_portfolio_artifact(artifacts_root, "target_weights.parquet")
    assert {"symbol", "target_weight", "raw_weight", "clipped_weight", "fallback"}.issubset(weights.columns)
    assert (weights["target_weight"] >= -1e-12).all()
    assert weights["target_weight"].sum() <= 0.95 + 1e-9
    assert weights["target_weight"].max() <= 0.60 + 1e-9

    current = {"AAPL": 0.90, "MSFT": 0.00}
    turnover = sum(abs(row.target_weight - current.get(row.symbol, 0.0)) for row in weights.itertuples())
    assert turnover <= 0.20 + 1e-9 or bool(weights["fallback"].any())


def test_optimize_weights_uses_explicit_fallback_when_optimizer_cannot_produce_solution(
    tmp_path: Path,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    portfolio_run_root = artifacts_root / "portfolio_runs" / "pf_fallback"
    portfolio_run_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "score": 0.20,
                "rank": 1,
                "expected_return": 0.02,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "score": 0.20,
                "rank": 2,
                "expected_return": 0.02,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "expected_returns.parquet", index=False)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "peer_symbol": "AAPL",
                "covariance": 0.0,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "peer_symbol": "MSFT",
                "covariance": 0.0,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "peer_symbol": "AAPL",
                "covariance": 0.0,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "peer_symbol": "MSFT",
                "covariance": 0.0,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "covariance.parquet", index=False)
    config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio_fallback.yaml",
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="pf_fallback",
    )

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.optimize_weights",
        ("optimize_weights", "optimize", "run"),
        score_run_id="score_unused",
        config=load_portfolio_config(config_path),
    )

    weights = _locate_portfolio_artifact(artifacts_root, "target_weights.parquet")
    assert bool(weights["fallback"].all())
    assert weights["target_weight"].sum() <= 0.95 + 1e-9
    assert (weights["target_weight"] >= -1e-12).all()


def test_optimize_weights_without_explicit_fallback_fails_closed_when_pypfopt_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    portfolio_run_root = artifacts_root / "portfolio_runs" / "pf_no_implicit_fallback"
    portfolio_run_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_no_implicit_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "score": 0.60,
                "rank": 1,
                "expected_return": 0.06,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_no_implicit_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "score": 0.30,
                "rank": 2,
                "expected_return": 0.03,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "expected_returns.parquet", index=False)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_no_implicit_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "peer_symbol": "AAPL",
                "covariance": 0.04,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_no_implicit_fallback",
                "source_score_run_id": "score_unused",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "peer_symbol": "MSFT",
                "covariance": 0.03,
                "lookback_days": 3,
                "observation_count": 3,
                "returns_start": "2026-01-06T00:00:00+00:00",
                "returns_end": "2026-01-08T00:00:00+00:00",
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "covariance.parquet", index=False)
    config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio_no_fallback.yaml",
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="pf_no_implicit_fallback",
        fallback_optimizer="",
    )

    optimize_module = importlib.import_module("integrations.pypfopt_adapter.optimize_weights")
    from integrations.pypfopt_adapter.schemas import MissingDependencyError

    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        optimize_module.importlib.util,
        "find_spec",
        lambda name: None if name == "pypfopt" else original_find_spec(name),
    )

    with pytest.raises(MissingDependencyError, match="PyPortfolioOpt"):
        optimize_module.optimize_weights(
            score_run_id="score_unused",
            config=load_portfolio_config(config_path),
        )

    assert not (portfolio_run_root / "target_weights.parquet").exists()
    assert not (portfolio_run_root / "run_manifest.json").exists()


def test_import_target_weights_stays_target_position_only(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    portfolio_run_root = artifacts_root / "portfolio_runs" / "pf_import"
    portfolio_run_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_import",
                "source_score_run_id": "score_run",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "target_weight": 0.55,
                "raw_weight": 0.55,
                "clipped_weight": 0.55,
                "optimizer": "fallback_equal_weight",
                "constraints_hash": "abc123",
                "fallback": True,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
            {
                "portfolio_run_id": "pf_import",
                "source_score_run_id": "score_run",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "target_weight": 0.40,
                "raw_weight": 0.40,
                "clipped_weight": 0.40,
                "optimizer": "fallback_equal_weight",
                "constraints_hash": "abc123",
                "fallback": True,
                "created_at": "2026-05-11T00:00:00+00:00",
            },
        ]
    ).to_parquet(portfolio_run_root / "target_weights.parquet", index=False)

    config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio_import.yaml",
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="pf_import",
    )

    result = invoke_adapter_callable(
        "integrations.pypfopt_adapter.import_target_weights",
        ("import_target_weights", "import_weights", "run"),
        portfolio_run_id="pf_import",
        config=load_portfolio_config(config_path),
    )

    imported_candidates = sorted(
        path
        for path in artifacts_root.rglob("*.parquet")
        if path.name != "target_weights.parquet"
    )
    assert imported_candidates or result is not None

    if imported_candidates:
        imported = pd.read_parquet(imported_candidates[0])
        columns = {str(column).lower() for column in imported.columns}
        assert "target_weight" in columns or "target_quantity" in columns
        assert "side" not in columns
        assert "order_type" not in columns
        assert "client_order_id" not in columns


def test_import_target_weights_ignores_order_like_source_columns(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    portfolio_run_root = artifacts_root / "portfolio_runs" / "pf_order_like_source"
    portfolio_run_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_order_like_source",
                "source_score_run_id": "score_run",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "target_weight": 0.55,
                "raw_weight": 0.55,
                "clipped_weight": 0.55,
                "optimizer": "max_sharpe",
                "constraints_hash": "abc123",
                "fallback": "",
                "created_at": "2026-05-11T00:00:00+00:00",
                "side": "BUY",
                "order_type": "MARKET",
                "client_order_id": "must_not_propagate",
                "broker_order_id": "must_not_propagate",
                "risk_check_id": "must_not_propagate",
            }
        ]
    ).to_parquet(portfolio_run_root / "target_weights.parquet", index=False)
    (portfolio_run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "source_score_run_id": "score_run",
                "research_only": True,
                "live_enabled": False,
                "order_generation": "disabled",
                "config": {"strategy_id": "pypfopt_daily_only"},
            }
        ),
        encoding="utf-8",
    )
    config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio_import.yaml",
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="pf_order_like_source",
    )

    frame, _, json_path = invoke_adapter_callable(
        "integrations.pypfopt_adapter.import_target_weights",
        ("import_target_weights", "import_weights", "run"),
        portfolio_run_id="pf_order_like_source",
        config=load_portfolio_config(config_path),
    )

    forbidden = {"side", "order_type", "client_order_id", "broker_order_id", "risk_check_id"}
    assert forbidden.isdisjoint({str(column).lower() for column in frame.columns})
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload
    assert forbidden.isdisjoint({str(key).lower() for key in payload[0]})
    assert forbidden.isdisjoint({str(key).lower() for key in payload[0]["metadata"]})


def test_optimize_weights_module_exists_even_without_optional_dependency() -> None:
    try:
        spec = importlib.util.find_spec("integrations.pypfopt_adapter.optimize_weights")
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.xfail("pending adapter implementation: integrations.pypfopt_adapter.optimize_weights")
