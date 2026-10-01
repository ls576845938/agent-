#!/usr/bin/env python3
"""Build the US equity regime-overlay v0 design specification.

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


SCHEMA_VERSION = "us_equity_regime_overlay_design_spec_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_regime_overlay_design_spec_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Regime Overlay 研究设计规格.md")


def build_us_equity_regime_overlay_design_spec_report(
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
        "strategy_id": "us_equity_regime_overlay_v0_design",
        "registry_strategy_id": "us_equity_regime_overlay_research_placeholder",
        "family": "regime_overlay",
        "immutable_strategy_id_required_before_backtest": True,
        "hypothesis": {
            "alpha_sources": ["macro_regime_filter", "market_risk_state_filter"],
            "economic_rationale": (
                "A slow-moving macro and market-state overlay may reduce risk exposure when liquidity, inflation, "
                "growth, or credit conditions deteriorate, while leaving the underlying alpha model responsible for "
                "asset selection. The overlay is a risk throttle, not a standalone return engine."
            ),
            "counterparty_or_risk_premia": [
                "slow institutional de-risking after macro deterioration",
                "risk transfer from drawdown-averse investors",
                "lagged repricing of monetary and credit conditions",
            ],
            "known_risks": [
                "macro data publication lag and revisions",
                "false risk-off signals during recoveries",
                "overriding profitable alpha exposure too aggressively",
                "future-function leakage from revised macro histories",
            ],
        },
        "signal_design": {
            "macro_regime_inputs": {
                "candidate_series": [
                    "unemployment_rate",
                    "cpi_yoy_or_inflation_proxy",
                    "term_spread_10y_3m",
                    "credit_spread_proxy",
                    "fed_funds_or_policy_rate",
                ],
                "rule": "only use values available after their official release timestamp plus configured lag",
                "macro_release_lag_policy": "series value becomes eligible no earlier than first trading session after official release timestamp",
                "macro_revision_policy": "formal backtest must use vintage or as-of snapshots; revised final values are prohibited",
            },
            "market_state_inputs": {
                "candidate_series": ["SPY_trend", "VIX_proxy_if_available", "credit_or_bond_stress_proxy"],
                "rule": "market state may use only close data available at signal timestamp",
                "lookbacks_trading_days": [63, 126, 252],
            },
            "overlay_actions": {
                "risk_on": "leave base strategy target weights unchanged",
                "risk_neutral": "cap gross exposure or shift a partial sleeve to SHV",
                "risk_off": "reduce gross exposure and route unallocated capital to SHV",
                "effective_timestamp": "next_session_open_or_next_available_close_simulation",
            },
        },
        "portfolio_design": {
            "gross_exposure_cap_research": 1.0,
            "initial_live_leverage_default": 1.0,
            "position_sizing": "overlay multiplies base strategy weights by a regime exposure scalar",
            "overlay_exposure_scalars": {
                "risk_on": [1.0],
                "risk_neutral": [0.5, 0.75],
                "risk_off": [0.0, 0.25],
            },
            "small_account_constraints": {
                "account_equity_usd": 10000.0,
                "whole_share_and_fractional_share_models_required": True,
                "minimum_trade_amount_usd": 25.0,
                "overlay_trade_suppression_threshold_usd": 25.0,
            },
        },
        "data_contract": {
            "prices": "point-in-time adjusted ETF OHLCV with dividend and split adjustment replay",
            "universe": "point-in-time tradable ETF universe and start-date eligibility",
            "corporate_actions": "split/dividend/symbol-change adjustment replay required before promotion",
            "delistings": "delisted or unavailable ETF handling must be explicit",
            "macro": "FRED or vendor macro vintages with release calendar and as-of availability timestamps required",
        },
        "parameter_space_before_backtest": {
            "macro_release_lag_trading_days": [1, 3, 5],
            "macro_smoothing_months": [1, 3, 6],
            "market_state_lookbacks_trading_days": [63, 126, 252],
            "risk_neutral_exposure_scalar": [0.5, 0.75],
            "risk_off_exposure_scalar": [0.0, 0.25],
            "rebalance_frequency": ["monthly", "weekly"],
            "base_strategy_inputs": ["us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x", "future_candidate_strategy"],
            "defensive_cash_proxy": ["SHV"],
        },
        "validation_plan": {
            "benchmarks": ["SPY", "QQQ", "60_40_SPY_IEF", "SHV"],
            "cost_stress_bps": [0, 10, 25, 50],
            "walk_forward_required": True,
            "parameter_stability_required": True,
            "year_regime_breakdown_required": True,
            "attribution_required": [
                "base_strategy_without_overlay",
                "macro_regime_filter",
                "market_state_filter",
                "exposure_scalar",
                "turnover_and_cost",
            ],
        },
        "failure_conditions": [
            "uses revised macro data without vintage or as-of evidence",
            "overlay improves backtest only by avoiding known crises with parameters chosen after the fact",
            "risk-off scalar materially reduces long-run return without drawdown improvement",
            "macro release calendar or release lag evidence is missing",
            "base strategy attribution is not separated from overlay attribution",
        ],
        "required_design_outputs": [
            "immutable_strategy_id",
            "explicit_alpha_hypothesis",
            "parameter_space_before_backtest",
            "data_dependencies_and_pit_requirements",
            "cost_liquidity_capacity_model",
            "failure_conditions_and_stop_rules",
            "macro_release_lag_policy",
            "macro_revision_policy",
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
        "# US Equity Regime Overlay 研究设计规格",
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
    parser = argparse.ArgumentParser(description="Build US equity regime overlay design spec.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_regime_overlay_design_spec_report(
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
