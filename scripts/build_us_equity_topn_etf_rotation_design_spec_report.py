#!/usr/bin/env python3
"""Build the US equity Top-N ETF rotation v0 design specification.

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


SCHEMA_VERSION = "us_equity_topn_etf_rotation_design_spec_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_topn_etf_rotation_design_spec_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Top-N ETF Rotation 研究设计规格.md")


def build_us_equity_topn_etf_rotation_design_spec_report(
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
        "strategy_id": "us_equity_topn_etf_rotation_v0_design",
        "registry_strategy_id": "us_equity_etf_topn_rotation_research_placeholder",
        "family": "topn_etf_rotation",
        "immutable_strategy_id_required_before_backtest": True,
        "hypothesis": {
            "alpha_sources": ["cross_sectional_momentum", "diversified_trend_following"],
            "economic_rationale": (
                "A diversified ETF universe can rotate into the strongest recent return sleeves while capping "
                "single-theme concentration; this tests whether broad cross-sectional momentum survives costs, "
                "liquidity constraints, and realistic small-account execution."
            ),
            "counterparty_or_risk_premia": [
                "slow-moving asset allocation flows",
                "behavioral underreaction across sectors and styles",
                "risk premia compensation for holding recent winners",
            ],
            "known_risks": [
                "winner concentration in one sector or macro theme",
                "high turnover when ranks are unstable",
                "correlated ETF holdings create false diversification",
                "thin ETF capacity and wide spread drag",
            ],
        },
        "signal_design": {
            "relative_momentum": {
                "rule": "rank ETFs by trailing total return and select top N among PIT-eligible tradable assets",
                "lookbacks_trading_days": [63, 126, 189, 252],
                "rank_stabilizers": ["skip assets below min ADV", "tie break by lower realized volatility", "deterministic ticker sort"],
                "signal_timestamp": "rebalance_day_close",
                "effective_timestamp": "next_session_open_or_next_available_close_simulation",
            },
            "absolute_momentum_filter": {
                "rule": "optional risk filter excludes ETFs with non-positive own momentum before ranking",
                "enabled_variants": [False, True],
            },
            "universe_sleeves": {
                "broad_market": ["SPY", "VOO", "QQQ"],
                "sector": ["XLB", "XLI", "XLP", "XLU", "XLV", "XLY", "SOXX", "XBI"],
                "style_or_factor": ["MTUM", "QMOM"],
                "alternatives_or_defensive": ["GLD", "IEF", "SHV", "PDBC", "DBMF", "USO"],
            },
        },
        "portfolio_design": {
            "gross_exposure_cap_research": 1.0,
            "initial_live_leverage_default": 1.0,
            "position_sizing": "equal-weight top N for v0 design; capped-weight variant only after base test",
            "top_n_weighting_rule": {
                "top_n_values": [2, 3, 4, 5],
                "max_single_etf_weight": [0.25, 0.33, 0.5],
                "cash_or_shv_for_unfilled_slots": True,
            },
            "correlation_and_concentration_check": {
                "max_average_pairwise_correlation_warning": 0.85,
                "sector_or_theme_concentration_warning": 0.75,
                "overlapping_holdings_check_required": True,
            },
            "small_account_constraints": {
                "account_equity_usd": 10000.0,
                "whole_share_and_fractional_share_models_required": True,
                "minimum_trade_amount_usd": 25.0,
                "min_adv_usd": [5000000, 10000000],
            },
        },
        "data_contract": {
            "prices": "point-in-time adjusted ETF OHLCV with dividend and split adjustment replay",
            "universe": "point-in-time tradable ETF universe and start-date eligibility",
            "corporate_actions": "split/dividend/symbol-change adjustment replay required before promotion",
            "delistings": "delisted or unavailable ETF handling must be explicit",
            "macro": "not required for v0 Top-N rotation; macro overlay remains separate strategy family",
        },
        "parameter_space_before_backtest": {
            "relative_momentum_lookbacks_trading_days": [63, 126, 189, 252],
            "top_n_values": [2, 3, 4, 5],
            "max_single_etf_weight": [0.25, 0.33, 0.5],
            "min_adv_usd": [5000000, 10000000],
            "absolute_momentum_filter_enabled": [False, True],
            "rebalance_frequency": ["monthly", "weekly"],
            "universe_variants": [
                "broad_etf_core",
                "sector_etf_core",
                "style_etf_core",
                "broad_plus_alternative_etf_core",
            ],
            "defensive_cash_proxy": ["SHV"],
        },
        "validation_plan": {
            "benchmarks": ["SPY", "QQQ", "60_40_SPY_IEF", "SHV"],
            "cost_stress_bps": [0, 10, 25, 50],
            "walk_forward_required": True,
            "parameter_stability_required": True,
            "year_regime_breakdown_required": True,
            "attribution_required": [
                "relative_momentum_selection",
                "top_n_diversification",
                "concentration_penalty_or_cap",
                "liquidity_filter",
                "turnover_and_cost",
            ],
        },
        "failure_conditions": [
            "performance comes from a single ETF or single sector concentration",
            "works only for one Top-N value or one lookback",
            "turnover cost stress destroys most excess return",
            "PIT universe, delisting, or adjustment replay evidence is missing",
            "small-account trade sizing or ADV constraint materially changes results",
        ],
        "required_design_outputs": [
            "immutable_strategy_id",
            "explicit_alpha_hypothesis",
            "parameter_space_before_backtest",
            "data_dependencies_and_pit_requirements",
            "cost_liquidity_capacity_model",
            "failure_conditions_and_stop_rules",
            "top_n_weighting_rule",
            "correlation_and_concentration_check",
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
        "# US Equity Top-N ETF Rotation 研究设计规格",
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
    parser = argparse.ArgumentParser(description="Build US equity Top-N ETF rotation design spec.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_topn_etf_rotation_design_spec_report(
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
