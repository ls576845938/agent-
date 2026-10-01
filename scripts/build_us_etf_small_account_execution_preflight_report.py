#!/usr/bin/env python3
"""Build small-account execution preflight for US ETF rotation.

The report converts the latest target weights into account-size-aware target
orders. It is simulated-only and does not contact any broker.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_etf_small_account_execution_preflight_v1"
DEFAULT_LEDGER_ROOT = Path("data/forward_observation/us_etf_rotation_v1")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF 小账户执行约束审计.md")
DEFAULT_ACCOUNT_EQUITY = 10000.0
SCENARIOS = [
    {"scenario_id": "one_x_cash_only", "gross_cap": 1.0, "allow_margin": False, "description": "Initial live-review baseline; no margin."},
    {"scenario_id": "low_leverage_1_25x_research", "gross_cap": 1.25, "allow_margin": True, "description": "Research-only low leverage stress."},
    {"scenario_id": "research_cap_1_5x", "gross_cap": 1.5, "allow_margin": True, "description": "Research upper bound, not default live config."},
]


def build_us_etf_small_account_execution_preflight_report(
    *,
    repo_root: Path | None = None,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    account_equity: float = DEFAULT_ACCOUNT_EQUITY,
    min_trade_amount_usd: float = 25.0,
    slippage_bps: float = 10.0,
    annual_financing_rate: float = 0.055,
    initial_margin_requirement: float = 0.50,
    maintenance_margin_requirement: float = 0.25,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    targets = _read_jsonl(ledger / "target_positions.jsonl")
    latest = targets[-1] if targets else {}
    target = _mapping(latest.get("target_position"))
    weights = {str(k): _float_or(v, 0.0) for k, v in _mapping(target.get("weights")).items()}
    prices = {str(k): _float_or(v, 0.0) for k, v in _mapping(target.get("prices")).items()}
    blockers: list[str] = []
    if not targets:
        blockers.append("us_etf_small_account_preflight_no_target_positions")
    if account_equity <= 0.0:
        blockers.append("us_etf_small_account_preflight_account_equity_not_positive")
    if not weights:
        blockers.append("us_etf_small_account_preflight_no_target_weights")
    if any(price <= 0.0 for price in prices.values()):
        blockers.append("us_etf_small_account_preflight_non_positive_price")

    scenario_reports = [
        _scenario_report(
            scenario,
            weights=weights,
            prices=prices,
            account_equity=account_equity,
            min_trade_amount_usd=min_trade_amount_usd,
            slippage_bps=slippage_bps,
            annual_financing_rate=annual_financing_rate,
            initial_margin_requirement=initial_margin_requirement,
            maintenance_margin_requirement=maintenance_margin_requirement,
        )
        for scenario in SCENARIOS
    ]
    for scenario in scenario_reports:
        if not scenario["passes_preflight"]:
            blockers.append(f"us_etf_small_account_preflight_scenario_failed:{scenario['scenario_id']}")

    status = "pass_observation_only" if not blockers else "blocked"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "asset": "us_equity",
        "strategy_id": str(latest.get("strategy_id", "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x")),
        "candidate_variant": str(latest.get("candidate_variant", "")),
        "timestamp": str(latest.get("timestamp", "")),
        "account_equity": round(float(account_equity), 6),
        "min_trade_amount_usd": round(float(min_trade_amount_usd), 6),
        "slippage_bps": round(float(slippage_bps), 6),
        "annual_financing_rate": round(float(annual_financing_rate), 6),
        "initial_margin_requirement": round(float(initial_margin_requirement), 6),
        "maintenance_margin_requirement": round(float(maintenance_margin_requirement), 6),
        "source_files": {
            "ledger_root": _relpath(ledger, root),
            "target_positions": _relpath(ledger / "target_positions.jsonl", root),
        },
        "latest_target": {
            "gross_exposure": _float_or(target.get("gross_exposure"), sum(abs(v) for v in weights.values())),
            "net_exposure": _float_or(target.get("net_exposure"), sum(weights.values())),
            "symbols": sorted(weights),
        },
        "scenarios": scenario_reports,
        "blockers": _dedupe(blockers),
        "guardrails": {
            "simulated_only": True,
            "forward_or_paper_only": True,
            "not_a_broker_order": True,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "initial_live_leverage_default": 1.0,
            "research_cap_1_5x_not_live_default": True,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _scenario_report(
    scenario: Mapping[str, Any],
    *,
    weights: Mapping[str, float],
    prices: Mapping[str, float],
    account_equity: float,
    min_trade_amount_usd: float,
    slippage_bps: float,
    annual_financing_rate: float,
    initial_margin_requirement: float,
    maintenance_margin_requirement: float,
) -> dict[str, Any]:
    cap = _float_or(scenario.get("gross_cap"), 1.0)
    raw_gross = sum(abs(value) for value in weights.values())
    scale = min(1.0, cap / raw_gross) if raw_gross > 0 else 0.0
    scaled_weights = {symbol: value * scale for symbol, value in weights.items()}
    target_notional = {symbol: account_equity * weight for symbol, weight in scaled_weights.items()}
    fractional_orders = []
    whole_orders = []
    blockers = []
    for symbol in sorted(scaled_weights):
        price = _float_or(prices.get(symbol), 0.0)
        notional = target_notional[symbol]
        abs_notional = abs(notional)
        fractional_qty = notional / price if price > 0 else 0.0
        whole_qty = math.floor(abs(fractional_qty)) * (1 if fractional_qty >= 0 else -1)
        whole_notional = whole_qty * price
        if 0.0 < abs_notional < min_trade_amount_usd:
            blockers.append(f"below_min_trade_amount:{symbol}")
        fractional_orders.append(
            {
                "symbol": symbol,
                "side": "buy" if notional >= 0 else "sell",
                "price": round(price, 6),
                "target_weight": round(scaled_weights[symbol], 10),
                "target_notional": round(notional, 6),
                "quantity": round(fractional_qty, 10),
                "trade_amount_pass": abs_notional >= min_trade_amount_usd,
            }
        )
        whole_orders.append(
            {
                "symbol": symbol,
                "side": "buy" if whole_notional >= 0 else "sell",
                "price": round(price, 6),
                "target_weight": round(scaled_weights[symbol], 10),
                "target_notional": round(whole_notional, 6),
                "quantity": round(float(whole_qty), 10),
                "rounding_residual": round(notional - whole_notional, 6),
                "trade_amount_pass": abs(whole_notional) >= min_trade_amount_usd or abs(whole_notional) == 0.0,
            }
        )
    fractional_gross = sum(abs(row["target_notional"]) for row in fractional_orders)
    whole_gross = sum(abs(row["target_notional"]) for row in whole_orders)
    slippage = fractional_gross * slippage_bps / 10000.0
    borrow_notional = max(0.0, fractional_gross - account_equity)
    whole_borrow_notional = max(0.0, whole_gross - account_equity)
    financing_daily = borrow_notional * annual_financing_rate / 252.0
    whole_financing_daily = whole_borrow_notional * annual_financing_rate / 252.0
    cash_after_fractional = account_equity - sum(row["target_notional"] for row in fractional_orders) - slippage - financing_daily
    cash_after_whole = (
        account_equity
        - sum(row["target_notional"] for row in whole_orders)
        - whole_gross * slippage_bps / 10000.0
        - whole_financing_daily
    )
    fractional_initial_required = fractional_gross * initial_margin_requirement
    whole_initial_required = whole_gross * initial_margin_requirement
    fractional_maintenance_required = fractional_gross * maintenance_margin_requirement
    whole_maintenance_required = whole_gross * maintenance_margin_requirement
    if cash_after_fractional < -0.01 and not bool(scenario.get("allow_margin")):
        blockers.append("cash_negative_without_margin_fractional")
    if cash_after_whole < -0.01 and not bool(scenario.get("allow_margin")):
        blockers.append("cash_negative_without_margin_whole")
    if bool(scenario.get("allow_margin")) and account_equity + 0.01 < fractional_initial_required:
        blockers.append("initial_margin_requirement_failed_fractional")
    if bool(scenario.get("allow_margin")) and account_equity + 0.01 < whole_initial_required:
        blockers.append("initial_margin_requirement_failed_whole")
    if bool(scenario.get("allow_margin")) and account_equity + 0.01 < fractional_maintenance_required:
        blockers.append("maintenance_margin_requirement_failed_fractional")
    if bool(scenario.get("allow_margin")) and account_equity + 0.01 < whole_maintenance_required:
        blockers.append("maintenance_margin_requirement_failed_whole")
    return {
        "scenario_id": str(scenario.get("scenario_id", "")),
        "description": str(scenario.get("description", "")),
        "gross_cap": round(cap, 6),
        "allow_margin": bool(scenario.get("allow_margin")),
        "raw_target_gross": round(raw_gross, 10),
        "effective_gross": round(sum(abs(value) for value in scaled_weights.values()), 10),
        "scale_applied": round(scale, 10),
        "fractional_share_allowed_model": {
            "orders": fractional_orders,
            "gross_notional": round(fractional_gross, 6),
            "borrow_notional": round(borrow_notional, 6),
            "estimated_slippage": round(slippage, 6),
            "estimated_financing_daily": round(financing_daily, 6),
            "initial_margin_required": round(fractional_initial_required, 6),
            "initial_margin_surplus": round(account_equity - fractional_initial_required, 6),
            "maintenance_margin_required": round(fractional_maintenance_required, 6),
            "maintenance_margin_surplus": round(account_equity - fractional_maintenance_required, 6),
            "cash_after_orders": round(cash_after_fractional, 6),
        },
        "whole_share_model": {
            "orders": whole_orders,
            "gross_notional": round(whole_gross, 6),
            "borrow_notional": round(whole_borrow_notional, 6),
            "estimated_slippage": round(whole_gross * slippage_bps / 10000.0, 6),
            "estimated_financing_daily": round(whole_financing_daily, 6),
            "initial_margin_required": round(whole_initial_required, 6),
            "initial_margin_surplus": round(account_equity - whole_initial_required, 6),
            "maintenance_margin_required": round(whole_maintenance_required, 6),
            "maintenance_margin_surplus": round(account_equity - whole_maintenance_required, 6),
            "cash_after_orders": round(cash_after_whole, 6),
        },
        "blockers": _dedupe(blockers),
        "passes_preflight": not blockers,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _float_or(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US ETF 小账户执行约束审计",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 策略：`{payload.get('strategy_id', '')}`",
        f"- 日期：`{payload.get('timestamp', '')}`",
        f"- 账户权益：`${payload.get('account_equity', 0)}`",
        f"- 最小成交额：`${payload.get('min_trade_amount_usd', 0)}`",
        f"- 滑点假设：`{payload.get('slippage_bps', 0)} bps`",
        f"- 年化融资利率：`{payload.get('annual_financing_rate', 0)}`",
        f"- 初始保证金要求：`{payload.get('initial_margin_requirement', 0)}`",
        f"- 维持保证金要求：`{payload.get('maintenance_margin_requirement', 0)}`",
        "",
        "本报告只做目标订单和账户约束审计，不是 broker 指令，也不允许真实下单。",
        "",
        "| 场景 | gross cap | margin | fractional cash | whole cash | pass |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for scenario in _list(payload.get("scenarios")):
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |".format(
                scenario.get("scenario_id", ""),
                scenario.get("gross_cap", 0),
                scenario.get("allow_margin", False),
                _nested(scenario, "fractional_share_allowed_model.cash_after_orders", 0),
                _nested(scenario, "whole_share_model.cash_after_orders", 0),
                scenario.get("passes_preflight", False),
            )
        )
    lines += [
        "",
        "## Guardrails",
        "",
        "- simulated only",
        "- not a broker order",
        "- live_order_allowed=false",
        "- 1.5x is research cap, not default live configuration",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list(payload.get("blockers"))
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- 无")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US ETF small-account execution preflight.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--account-equity", type=float, default=DEFAULT_ACCOUNT_EQUITY)
    parser.add_argument("--min-trade-amount-usd", type=float, default=25.0)
    parser.add_argument("--slippage-bps", type=float, default=10.0)
    parser.add_argument("--annual-financing-rate", type=float, default=0.055)
    parser.add_argument("--initial-margin-requirement", type=float, default=0.50)
    parser.add_argument("--maintenance-margin-requirement", type=float, default=0.25)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_etf_small_account_execution_preflight_report(
        repo_root=Path(args.repo_root),
        ledger_root=Path(args.ledger_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        account_equity=args.account_equity,
        min_trade_amount_usd=args.min_trade_amount_usd,
        slippage_bps=args.slippage_bps,
        annual_financing_rate=args.annual_financing_rate,
        initial_margin_requirement=args.initial_margin_requirement,
        maintenance_margin_requirement=args.maintenance_margin_requirement,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
