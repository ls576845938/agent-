#!/usr/bin/env python3
"""Build the US equity 151 Trading Strategies migration design specification.

This is a design artifact only. It defines the hypothesis, parameter space,
data contract, validation plan, and stop rules before any standardized
backtest is allowed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_151_trading_strategies_migration_design_spec_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_151_trading_strategies_migration_design_spec_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 151 Trading Strategies 迁移设计规格.md")


def build_us_equity_151_trading_strategies_migration_design_spec_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": "design_spec_ready",
        "decision": "wait_for_production_pit_data_and_research_start_gate_before_backtest",
        "strategy_id": "us_equity_151_trading_strategies_migration_v0_design",
        "registry_strategy_id": "us_equity_151_trading_strategies_candidate_research_placeholder",
        "family": "151_trading_strategies_migration",
        "immutable_strategy_id_required_before_backtest": True,
        "hypothesis": {
            "alpha_sources": ["strategy_library_migration", "hypothesis_screening"],
            "economic_rationale": (
                "The 151 Trading Strategies source is a hypothesis library, not a validated signal set. The migration "
                "process should map each usable idea into the local production-line contract, exclude ideas that require "
                "unavailable data or unsuitable execution, and only promote candidates after PIT and cost prerequisites pass."
            ),
            "counterparty_or_risk_premia": [
                "behavioral underreaction and overreaction ideas already represented in the source library",
                "structural premia such as trend, reversal, carry, seasonality, and liquidity compensation",
                "market microstructure premia only when execution assumptions are realistic",
            ],
            "known_risks": [
                "copying formulas without matching data definitions",
                "strategies requiring unavailable intraday, options, futures, shorting, or borrow data",
                "publication bias and multiple-testing across many ideas",
                "capacity, cost, and tax assumptions not transferable to a 10000 USD account",
            ],
        },
        "signal_design": {
            "source_strategy_mapping": {
                "source": "151 Trading Strategies by Zura Kakushadze and Juan Andres Serur",
                "mapping_fields": [
                    "source_strategy_number_or_name",
                    "asset_class",
                    "required_data",
                    "holding_period",
                    "execution_frequency",
                    "long_only_possible",
                    "local_strategy_family",
                    "reason_for_inclusion_or_exclusion",
                ],
                "local_families": [
                    "trend_or_time_series_momentum",
                    "cross_sectional_momentum_or_rotation",
                    "mean_reversion",
                    "seasonality_or_calendar",
                    "factor_or_fundamental",
                    "regime_or_macro_overlay",
                    "excluded_unavailable_or_unsuitable",
                ],
            },
            "implementation_exclusions": {
                "hard_exclusions": [
                    "requires real HFT latency or order-book queue position",
                    "requires options greeks or option chain history not yet in production data",
                    "requires futures continuous contracts not yet normalized",
                    "requires short borrow availability or borrow cost not modeled",
                    "requires data that cannot be made point-in-time",
                ],
                "soft_exclusions_for_later": [
                    "high-turnover intraday ideas",
                    "strategies with unclear capacity below 10000 USD",
                    "ideas duplicating already registered candidates",
                ],
            },
            "candidate_priority_rule": {
                "rule": "prefer daily or weekly long-only US equity or ETF ideas with low data burden and clear cost model",
                "priority_order": ["ETF trend/rotation", "daily equity factor", "calendar effect", "slow mean reversion", "intraday later"],
            },
        },
        "portfolio_design": {
            "gross_exposure_cap_research": 1.0,
            "initial_live_leverage_default": 1.0,
            "position_sizing": "migration stage does not define final weights; each promoted idea must create its own strategy design spec",
            "portfolio_constraints": {
                "must_define_before_backtest": [
                    "target_universe",
                    "target_weight_rule",
                    "rebalance_calendar",
                    "cash_or_defensive_handling",
                    "cost_liquidity_capacity_model",
                ]
            },
            "small_account_constraints": {
                "account_equity_usd": 10000.0,
                "whole_share_and_fractional_share_models_required": True,
                "minimum_trade_amount_usd": 25.0,
                "candidate_must_be_feasible_for_small_account": True,
            },
        },
        "data_contract": {
            "prices": "PIT adjusted OHLCV requirement must be mapped per candidate",
            "universe": "PIT universe membership requirement must be mapped per candidate",
            "fundamentals": "PIT fundamentals required only for factor candidates and must include as-of timestamps",
            "corporate_actions": "required for any equity or ETF candidate before standardized backtest",
            "delistings": "required for any equity universe candidate before standardized backtest",
            "intraday_or_microstructure": "blocked unless order-book/trade data and execution model exist",
        },
        "parameter_space_before_backtest": {
            "screening_buckets": [
                "daily_or_weekly_long_only_ready_for_design",
                "needs_pit_data_before_design",
                "needs_execution_model_before_design",
                "excluded_duplicate_or_unsuitable",
            ],
            "minimum_candidate_fields": [
                "hypothesis",
                "data_requirements",
                "rebalance_frequency",
                "cost_model",
                "capacity_model",
                "failure_conditions",
            ],
            "max_candidates_promoted_per_batch": [3, 5, 10],
        },
        "validation_plan": {
            "benchmarks": ["SPY", "QQQ", "IWM", "SHV"],
            "cost_stress_bps": [0, 10, 25, 50],
            "walk_forward_required": True,
            "parameter_stability_required": True,
            "year_regime_breakdown_required": True,
            "attribution_required": [
                "source_strategy_mapping",
                "implementation_exclusions",
                "duplicate_strategy_detection",
                "data_burden_score",
                "cost_and_capacity_screen",
            ],
        },
        "failure_conditions": [
            "source strategy cannot be mapped to local data and execution assumptions",
            "candidate requires unavailable PIT, intraday, options, futures, or borrow data",
            "candidate duplicates an existing registered strategy without new evidence",
            "candidate cannot define a cost and capacity model for a 10000 USD account",
            "migration output tries to start backtesting without a child strategy design spec",
        ],
        "required_design_outputs": [
            "immutable_strategy_id",
            "explicit_alpha_hypothesis",
            "parameter_space_before_backtest",
            "data_dependencies_and_pit_requirements",
            "cost_liquidity_capacity_model",
            "failure_conditions_and_stop_rules",
            "source_strategy_mapping",
            "implementation_exclusions",
        ],
        "guardrails": {
            "design_spec_only": True,
            "standardized_backtest_allowed_by_this_report": False,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 151 Trading Strategies 迁移设计规格",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- 策略 ID：`{payload.get('strategy_id', '')}`",
        "",
        "本规格只完成研究设计，不启动回测，不解锁 paper/live。",
        "",
        "## Hypothesis",
        "",
        str(_mapping(payload.get("hypothesis")).get("economic_rationale", "")),
        "",
        "## Parameter Space",
        "",
    ]
    for key, value in _mapping(payload.get("parameter_space_before_backtest")).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Validation Plan", ""])
    for key, value in _mapping(payload.get("validation_plan")).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Failure Conditions", ""])
    lines.extend(f"- {item}" for item in _list(payload.get("failure_conditions")))
    lines.extend(["", "## Guardrails", "", "- standardized_backtest_allowed_by_this_report=false", "- live_order_allowed=false"])
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity 151 Trading Strategies migration design spec.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_151_trading_strategies_migration_design_spec_report(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
