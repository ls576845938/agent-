#!/usr/bin/env python3
"""Build the independent US ETF strategy validation gate report.

This gate answers one narrow question: whether research evidence is sufficient
to allow or continue forward observation. It does not unlock paper simulation or
live trading.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_etf_strategy_validation_gate_report_v1"
STRATEGY_ID = "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"
ALLOWED_STATUSES = {
    "research_only",
    "validation_passed_for_forward_observation",
    "rejected",
    "blocked_data_quality",
}
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 策略验证门槛.md")
DEFAULT_RESEARCH_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json")
DEFAULT_TOP_VALIDATION_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json"
)
DEFAULT_COST_STRESS_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_stress_report.json")
DEFAULT_WALK_FORWARD_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json"
)
DEFAULT_YEAR_ATTRIBUTION_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_year_attribution_report.json"
)
DEFAULT_TIINGO_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_DATA_FRESHNESS_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_KLINE_QUALITY_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json")
DEFAULT_FRED_PREFLIGHT_REPORT = Path("artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json")
DEFAULT_PIT_INTAKE_STATUS_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json")
DEFAULT_PIT_BUNDLE_ACCEPTANCE_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json")
DEFAULT_STRATEGY_CARD = Path("docs/strategy_cards/us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x.md")
REQUIRED_METRIC_FIELDS = {"CAGR", "Vol", "Sharpe", "MDD", "Calmar", "Turnover", "CostStressedReturn", "LiquidityPass"}
REQUIRED_BENCHMARKS = {"SPY", "QQQ", "60_40_SPY_IEF"}
REQUIRED_CAPACITY_AUMS = {"10000", "50000", "100000", "500000", "1000000"}
REQUIRED_COST_LEVELS = {"0bps", "10bps", "25bps", "50bps"}
DATA_QUALITY_BLOCKERS = {
    "us_equity_data_not_promotion_clean",
    "point_in_time_universe_not_confirmed",
    "corporate_action_event_source_missing",
    "membership_events_missing",
    "delisting_coverage_missing",
    "survivorship_status_not_clean",
    "data_lineage_not_promotion_clean",
    "adjustment_reproducibility_missing",
    "price_adjustment_reproducibility_missing",
    "historical_membership_missing",
}


def build_us_etf_strategy_validation_gate_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    research_report: Path = DEFAULT_RESEARCH_REPORT,
    top_validation_report: Path = DEFAULT_TOP_VALIDATION_REPORT,
    cost_stress_report: Path = DEFAULT_COST_STRESS_REPORT,
    walk_forward_report: Path = DEFAULT_WALK_FORWARD_REPORT,
    year_attribution_report: Path = DEFAULT_YEAR_ATTRIBUTION_REPORT,
    tiingo_report: Path = DEFAULT_TIINGO_REPORT,
    data_freshness_report: Path = DEFAULT_DATA_FRESHNESS_REPORT,
    kline_quality_report: Path = DEFAULT_KLINE_QUALITY_REPORT,
    fred_preflight_report: Path = DEFAULT_FRED_PREFLIGHT_REPORT,
    pit_intake_status_report: Path = DEFAULT_PIT_INTAKE_STATUS_REPORT,
    pit_bundle_acceptance_report: Path = DEFAULT_PIT_BUNDLE_ACCEPTANCE_REPORT,
    strategy_card: Path = DEFAULT_STRATEGY_CARD,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {
        "research_report": _resolve(root, research_report),
        "top_validation_report": _resolve(root, top_validation_report),
        "cost_stress_report": _resolve(root, cost_stress_report),
        "walk_forward_report": _resolve(root, walk_forward_report),
        "year_attribution_report": _resolve(root, year_attribution_report),
        "tiingo_report": _resolve(root, tiingo_report),
        "data_freshness_report": _resolve(root, data_freshness_report),
        "kline_quality_report": _resolve(root, kline_quality_report),
        "fred_preflight_report": _resolve(root, fred_preflight_report),
        "pit_intake_status_report": _resolve(root, pit_intake_status_report),
        "pit_bundle_acceptance_report": _resolve(root, pit_bundle_acceptance_report),
        "strategy_card": _resolve(root, strategy_card),
    }
    reports = {
        "research_report": _read_json(paths["research_report"]),
        "top_validation_report": _read_json(paths["top_validation_report"]),
        "cost_stress_report": _read_json(paths["cost_stress_report"]),
        "walk_forward_report": _read_json(paths["walk_forward_report"]),
        "year_attribution_report": _read_json(paths["year_attribution_report"]),
        "tiingo_report": _read_json(paths["tiingo_report"]),
        "data_freshness_report": _read_json(paths["data_freshness_report"]),
        "kline_quality_report": _read_json(paths["kline_quality_report"]),
        "fred_preflight_report": _read_json(paths["fred_preflight_report"]),
        "pit_intake_status_report": _read_json(paths["pit_intake_status_report"]),
        "pit_bundle_acceptance_report": _read_json(paths["pit_bundle_acceptance_report"]),
    }
    card_text = paths["strategy_card"].read_text(encoding="utf-8") if paths["strategy_card"].exists() else ""
    checks = {
        "data_coverage_and_quality": _check_data_quality(
            reports["research_report"],
            reports["tiingo_report"],
            reports["data_freshness_report"],
            reports["kline_quality_report"],
            reports["fred_preflight_report"],
            reports["pit_intake_status_report"],
            reports["pit_bundle_acceptance_report"],
        ),
        "no_future_function": _check_no_future_function(reports["research_report"]),
        "original_strategy_semantics": _check_original_strategy_semantics(reports["top_validation_report"]),
        "benchmark_coverage": _check_benchmarks(reports["top_validation_report"]),
        "standard_metrics": _check_standard_metrics(reports["top_validation_report"]),
        "cost_stress": _check_cost_stress(reports["top_validation_report"], reports["cost_stress_report"]),
        "walk_forward": _check_walk_forward(reports["top_validation_report"]),
        "parameter_stability": _check_parameter_stability(reports["walk_forward_report"]),
        "capacity": _check_capacity(reports["top_validation_report"]),
        "return_attribution": _check_return_attribution(reports["top_validation_report"], reports["year_attribution_report"]),
        "strategy_card": _check_strategy_card(card_text),
        "guardrails": _check_guardrails(reports),
    }
    missing_inputs = [name for name, path in paths.items() if name != "strategy_card" and not path.exists()]
    if not paths["strategy_card"].exists():
        missing_inputs.append("strategy_card")
    blockers: list[str] = [f"us_etf_strategy_validation_missing_{name}" for name in missing_inputs]
    for check_name, check in checks.items():
        if not bool(check.get("passed", False)):
            blockers.append(f"us_etf_strategy_validation_{check_name}_failed")

    data_quality_failed = not bool(checks["data_coverage_and_quality"].get("passed", False))
    research_core_failed = any(
        not bool(checks[name].get("passed", False))
        for name in (
            "no_future_function",
            "standard_metrics",
            "cost_stress",
            "walk_forward",
            "parameter_stability",
            "capacity",
            "return_attribution",
            "strategy_card",
            "guardrails",
        )
    )
    if data_quality_failed:
        status = "blocked_data_quality"
        decision = "do_not_claim_strategy_validated_until_data_quality_gate_passes"
    elif research_core_failed or missing_inputs:
        status = "research_only"
        decision = "continue_research_do_not_promote"
    else:
        status = "validation_passed_for_forward_observation"
        decision = "allow_or_continue_forward_observation_only"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "strategy_id": STRATEGY_ID,
        "candidate_variant": "min_adv_10m_to_shv + vol_target_20pct_cap1.5x",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": decision,
        "allowed_next_action": "forward_observation_only" if status == "validation_passed_for_forward_observation" else "fix_blockers",
        "paper_ready": False,
        "live_ready": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "forward_observation_allowed": status in {"validation_passed_for_forward_observation", "blocked_data_quality"},
        "strategy_validation_gate_is_not_execution_permission": True,
        "checks": checks,
        "blockers": _dedupe(blockers),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "research_only_until_gate_passes": status != "validation_passed_for_forward_observation",
            "validation_gate_only_allows_forward_observation": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _check_data_quality(
    research: Mapping[str, Any],
    tiingo: Mapping[str, Any],
    data_freshness: Mapping[str, Any],
    kline_quality: Mapping[str, Any],
    fred_preflight: Mapping[str, Any],
    pit_intake_status: Mapping[str, Any],
    pit_bundle_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    research_blockers = set(_list_of_str(research.get("blockers")))
    matched = sorted(research_blockers & DATA_QUALITY_BLOCKERS)
    tiingo_ok = (
        str(tiingo.get("status", "")) == "pass"
        and int(tiingo.get("symbol_count", 0) or 0) >= 20
        and not _list(tiingo.get("missing_symbols"))
        and not _list(tiingo.get("blockers"))
    )
    freshness_ok = bool(data_freshness) and str(data_freshness.get("status", "")) == "pass" and not _list(data_freshness.get("blockers"))
    kline_status = str(kline_quality.get("status", ""))
    kline_ok = bool(kline_quality) and kline_status in {"pass", "warn"} and not _list(kline_quality.get("blockers"))
    fred_status = str(fred_preflight.get("status", ""))
    fred_ok = bool(fred_preflight) and fred_status in {"fred_macro_preflight_pass", "fred_macro_preflight_warn"} and not _list(
        fred_preflight.get("blockers")
    )
    pit_status = str(pit_intake_status.get("status", ""))
    pit_ok = bool(pit_intake_status) and pit_status == "production_pit_data_intake_ready" and not _list(pit_intake_status.get("blockers"))
    acceptance_status = str(pit_bundle_acceptance.get("status", ""))
    acceptance_ok = (
        bool(pit_bundle_acceptance)
        and acceptance_status == "acceptance_ready_for_manual_config_apply"
        and not _list(pit_bundle_acceptance.get("blockers"))
    )
    promotion_clean = bool(_nested(research, "data.promotion_clean", default=False))
    return {
        "passed": tiingo_ok and freshness_ok and kline_ok and fred_ok and pit_ok and acceptance_ok and promotion_clean and not matched,
        "tiingo_status": tiingo.get("status"),
        "tiingo_symbol_count": tiingo.get("symbol_count"),
        "latest_common_date": _nested(tiingo, "summary.latest_common_date"),
        "data_freshness_status": data_freshness.get("status"),
        "data_freshness_blockers": _list_of_str(data_freshness.get("blockers")),
        "kline_quality_status": kline_quality.get("status"),
        "kline_quality_latest_common_date": _nested(kline_quality, "summary.latest_common_date"),
        "kline_quality_blockers": _list_of_str(kline_quality.get("blockers")),
        "kline_quality_warnings": _list_of_str(kline_quality.get("warnings")),
        "fred_preflight_status": fred_preflight.get("status"),
        "fred_preflight_blockers": _list_of_str(fred_preflight.get("blockers")),
        "fred_preflight_warnings": _list_of_str(fred_preflight.get("warnings")),
        "pit_intake_status": pit_intake_status.get("status"),
        "pit_current_blocking_stage": pit_intake_status.get("current_blocking_stage"),
        "pit_intake_blockers": _list_of_str(pit_intake_status.get("blockers")),
        "pit_bundle_acceptance_status": pit_bundle_acceptance.get("status"),
        "pit_bundle_acceptance_current_blocking_step": pit_bundle_acceptance.get("current_blocking_step"),
        "pit_bundle_acceptance_blockers": _list_of_str(pit_bundle_acceptance.get("blockers")),
        "research_promotion_clean": promotion_clean,
        "matched_data_quality_blockers": matched,
    }


def _check_no_future_function(research: Mapping[str, Any]) -> dict[str, Any]:
    signal = _mapping(research.get("signal_integrity"))
    passed = (
        signal.get("t_plus_1_execution") is True
        and signal.get("no_private_endpoint") is True
        and signal.get("no_order_endpoint") is True
    )
    return {"passed": passed, "signal_integrity": signal}


def _check_original_strategy_semantics(validation: Mapping[str, Any]) -> dict[str, Any]:
    source_attr = _mapping(validation.get("source_attribution"))
    methodology = _mapping(validation.get("methodology"))
    return {
        "passed": bool(source_attr) and bool(methodology),
        "source_attribution_keys": sorted(source_attr.keys()),
        "methodology_keys": sorted(methodology.keys()),
    }


def _check_benchmarks(validation: Mapping[str, Any]) -> dict[str, Any]:
    rows = _list(_nested(validation, "standardized_report_schema.rows", default=[]))
    ids = {str(row.get("id", "")) for row in rows if isinstance(row, Mapping)}
    has_cash_proxy = bool({"SHV", "cash", "SHV_cash", "cash_SHV"} & ids)
    missing = sorted(REQUIRED_BENCHMARKS - ids)
    if not has_cash_proxy:
        missing.append("SHV_or_cash")
    return {"passed": not missing, "benchmark_ids": sorted(ids), "missing": missing}


def _check_standard_metrics(validation: Mapping[str, Any]) -> dict[str, Any]:
    rows = _list(_nested(validation, "standardized_report_schema.rows", default=[]))
    missing_by_row = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        missing = sorted(REQUIRED_METRIC_FIELDS - set(str(key) for key in row.keys()))
        if missing:
            missing_by_row[str(row.get("id", "unknown"))] = missing
    return {
        "passed": bool(rows) and not missing_by_row,
        "required_fields": sorted(REQUIRED_METRIC_FIELDS),
        "row_count": len(rows),
        "missing_by_row": missing_by_row,
    }


def _check_cost_stress(validation: Mapping[str, Any], cost_report: Mapping[str, Any]) -> dict[str, Any]:
    levels = set(_mapping(validation.get("cost_stress")).keys())
    missing = sorted(REQUIRED_COST_LEVELS - levels)
    decision = _mapping(validation.get("decision"))
    cost_report_levels = set(str(item) for item in _list(cost_report.get("stress_cost_bps")))
    return {
        "passed": not missing and decision.get("survives_25bps_slippage") is True and {"10", "25", "50"} <= cost_report_levels,
        "levels": sorted(levels),
        "external_cost_report_levels_bps": sorted(cost_report_levels),
        "missing": missing,
        "survives_25bps_slippage": decision.get("survives_25bps_slippage"),
    }


def _check_walk_forward(validation: Mapping[str, Any]) -> dict[str, Any]:
    walk = _mapping(validation.get("walk_forward"))
    decision = _mapping(validation.get("decision"))
    oos_cagr = _float_or(decision.get("walk_forward_oos_cagr"), None)
    return {
        "passed": int(walk.get("fold_count", 0) or 0) >= 5 and oos_cagr is not None and oos_cagr > 0,
        "fold_count": walk.get("fold_count"),
        "walk_forward_oos_cagr": oos_cagr,
    }


def _check_parameter_stability(walk_report: Mapping[str, Any]) -> dict[str, Any]:
    stability = _mapping(walk_report.get("stability"))
    grid = _mapping(walk_report.get("parameter_grid"))
    alive_rate = _float_or(stability.get("alive_rate"), 0.0)
    return {
        "passed": bool(stability.get("stable_enough_for_next_research_stage")) and alive_rate >= 0.7,
        "alive_rate": alive_rate,
        "candidate_count": stability.get("candidate_count"),
        "grid_dimensions": _mapping(grid.get("dimensions")),
    }


def _check_capacity(validation: Mapping[str, Any]) -> dict[str, Any]:
    capacity = _mapping(_nested(validation, "constrained_capacity_tests.aums", default={}))
    available = set(str(key) for key in capacity.keys())
    missing = sorted(REQUIRED_CAPACITY_AUMS - available)
    ten_k = _mapping(capacity.get("10000"))
    return {
        "passed": not missing and ten_k.get("passes_reference_aum_liquidity_check") is True,
        "required_aums": sorted(REQUIRED_CAPACITY_AUMS),
        "available_aums": sorted(available),
        "missing": missing,
        "ten_k_pass": ten_k.get("passes_reference_aum_liquidity_check"),
    }


def _check_return_attribution(validation: Mapping[str, Any], year_report: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(validation.get("source_attribution"))
    extreme = _mapping(validation.get("extreme_year_attribution"))
    years_raw = year_report.get("years")
    if isinstance(years_raw, Mapping):
        year_count = len(years_raw)
    else:
        year_count = len(_list(years_raw))
    required_source = {
        "asset_selection_and_parameter_effect_cagr",
        "gross_leverage_effect_cagr",
        "financing_effect_cagr",
        "slippage_25bps_effect_cagr",
    }
    return {
        "passed": required_source <= set(source.keys()) and bool(extreme) and year_count >= 4,
        "source_attribution_keys": sorted(source.keys()),
        "has_extreme_year_attribution": bool(extreme),
        "year_count": year_count,
    }


def _check_strategy_card(card_text: str) -> dict[str, Any]:
    required_terms = ["Expected Return Sources", "Main Risks", "Layer Boundaries", "Stop Or Disable Conditions"]
    missing = [term for term in required_terms if term not in card_text]
    return {"passed": bool(card_text) and not missing, "missing_sections": missing}


def _check_guardrails(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    unsafe = []
    for report_name, report in reports.items():
        for path, value in _walk(report):
            key = path.split(".")[-1]
            if key in {"live_ready", "paper_ready", "live_order_allowed", "private_endpoint_used", "order_endpoint_used", "real_order_submitted"} and value is True:
                unsafe.append(f"{report_name}.{path}=true")
    return {"passed": not unsafe, "unsafe_flags": unsafe}


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US ETF 轮动 策略验证门槛",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- strategy_id: `{payload.get('strategy_id')}`",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- live_order_allowed: `{payload.get('live_order_allowed')}`",
        f"- paper_simulation_allowed: `{payload.get('paper_simulation_allowed')}`",
        "",
        "## 结论边界",
        "",
        "- 本报告只判断是否允许进入或继续 forward observation。",
        "- 本报告不允许解锁 paper simulation 或 live trading。",
        "- 若数据质量未通过，状态必须是 `blocked_data_quality`。",
        "",
        "## Checks",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for name, check in _mapping(payload.get("checks")).items():
        lines.append(f"| `{name}` | `{bool(_mapping(check).get('passed', False))}` |")
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _float_or(value: Any, default: Any) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() or None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_etf_strategy_validation_gate_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
