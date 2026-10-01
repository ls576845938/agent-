#!/usr/bin/env python3
"""Build the US equity factor momentum-quality v0 design specification.

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


SCHEMA_VERSION = "us_equity_factor_momentum_quality_design_spec_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_factor_momentum_quality_design_spec_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Factor Momentum Quality 研究设计规格.md")


def build_us_equity_factor_momentum_quality_design_spec_report(
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
        "strategy_id": "us_equity_factor_momentum_quality_v0_design",
        "registry_strategy_id": "us_equity_factor_momentum_quality_research_placeholder",
        "family": "equity_factor",
        "immutable_strategy_id_required_before_backtest": True,
        "hypothesis": {
            "alpha_sources": ["cross_sectional_momentum", "quality_factor"],
            "economic_rationale": (
                "Stocks with persistent relative strength and durable quality characteristics may earn compensation "
                "for bearing style risk and exploiting slow information diffusion. The v0 design tests whether a "
                "simple momentum-quality blend survives PIT fundamentals, delisting returns, costs, and capacity."
            ),
            "counterparty_or_risk_premia": [
                "benchmark-constrained investors slow to rotate across styles",
                "behavioral underreaction to improving fundamentals and price trends",
                "compensation for bearing momentum crash and quality crowding risk",
            ],
            "known_risks": [
                "survivorship bias from missing delisted securities",
                "fundamental data restatement and report-date leakage",
                "sector concentration and unintended beta exposure",
                "microcap liquidity and borrow constraints if extended beyond long-only",
            ],
        },
        "signal_design": {
            "momentum_factor": {
                "rule": "rank PIT-eligible equities by total return over trailing window, skipping the most recent month in classic variant",
                "lookbacks_trading_days": [126, 189, 252],
                "skip_recent_trading_days": [0, 21],
                "signal_timestamp": "rebalance_day_close",
                "effective_timestamp": "next_session_open_or_next_available_close_simulation",
            },
            "quality_factor": {
                "candidate_metrics": ["gross_profitability", "return_on_equity", "accruals", "debt_to_assets"],
                "rule": "use only fundamentals whose filing or vendor-asof timestamp is available before signal timestamp",
                "pit_fundamentals_availability": "required before formal backtest; stale fundamentals must use last-known-as-of with maximum age rule",
            },
            "composite_score": {
                "rule": "z-score factors within eligible universe, optionally sector-neutralize, then combine by fixed weights",
                "factor_weights": [{"momentum": 0.5, "quality": 0.5}, {"momentum": 0.7, "quality": 0.3}],
                "winsorization": ["1pct_99pct", "2pct_98pct"],
            },
        },
        "portfolio_design": {
            "gross_exposure_cap_research": 1.0,
            "initial_live_leverage_default": 1.0,
            "position_sizing": "long-only top quantile equal weight for v0 design; long-short variants explicitly excluded until borrow and short-cost model exists",
            "portfolio_constraints": {
                "top_quantiles": [0.1, 0.2],
                "max_single_name_weight": [0.02, 0.05],
                "sector_neutralization": [False, True],
                "min_adv_usd": [5000000, 10000000],
            },
            "small_account_constraints": {
                "account_equity_usd": 10000.0,
                "whole_share_and_fractional_share_models_required": True,
                "minimum_trade_amount_usd": 25.0,
                "maximum_name_count_for_10000_usd": [10, 20],
            },
        },
        "data_contract": {
            "prices": "point-in-time adjusted equity OHLCV with split/dividend adjustment replay",
            "universe": "point-in-time equity universe membership and exchange/listing eligibility",
            "fundamentals": "point-in-time fundamentals with filing date, accepted date, vendor as-of timestamp, and restatement policy",
            "corporate_actions": "split/dividend/symbol-change/merger adjustment replay required before promotion",
            "delistings": "delisting return policy required; missing delisted names block formal research",
            "industry_classification": "PIT sector/industry labels required for neutralization tests",
        },
        "parameter_space_before_backtest": {
            "momentum_lookbacks_trading_days": [126, 189, 252],
            "skip_recent_trading_days": [0, 21],
            "quality_metrics": ["gross_profitability", "return_on_equity", "accruals", "debt_to_assets"],
            "factor_weight_sets": [{"momentum": 0.5, "quality": 0.5}, {"momentum": 0.7, "quality": 0.3}],
            "top_quantiles": [0.1, 0.2],
            "rebalance_frequency": ["monthly"],
            "sector_neutralization": [False, True],
            "min_adv_usd": [5000000, 10000000],
        },
        "validation_plan": {
            "benchmarks": ["SPY", "IWM", "MTUM", "QUAL", "SHV"],
            "cost_stress_bps": [0, 10, 25, 50],
            "walk_forward_required": True,
            "parameter_stability_required": True,
            "year_regime_breakdown_required": True,
            "attribution_required": [
                "momentum_factor",
                "quality_factor",
                "sector_neutralization",
                "liquidity_filter",
                "delisting_returns",
                "turnover_and_cost",
            ],
        },
        "failure_conditions": [
            "PIT fundamentals availability is missing or ambiguous",
            "delisting return policy is absent or cannot be reproduced",
            "performance is dominated by microcaps or illiquid names",
            "factor works only without sector or beta exposure controls",
            "quality data uses restated values before their actual availability date",
        ],
        "required_design_outputs": [
            "immutable_strategy_id",
            "explicit_alpha_hypothesis",
            "parameter_space_before_backtest",
            "data_dependencies_and_pit_requirements",
            "cost_liquidity_capacity_model",
            "failure_conditions_and_stop_rules",
            "pit_fundamentals_availability",
            "delisting_return_policy",
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
        "# US Equity Factor Momentum Quality 研究设计规格",
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
    parser = argparse.ArgumentParser(description="Build US equity factor momentum-quality design spec.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_factor_momentum_quality_design_spec_report(
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
