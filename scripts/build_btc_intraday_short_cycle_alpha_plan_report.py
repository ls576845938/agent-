#!/usr/bin/env python3
"""Build the BTC intraday short-cycle alpha research plan report.

This is an early research-governance artifact. It can authorize a distribution
probe on existing public 5m/15m history, but it never creates a strategy
candidate, paper review, live unlock, or broker/order path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
BTC_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
BTC_CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
BTC_RESEARCH_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
BTC_DATA_SOURCE_DECISION = Path("artifacts/btc_data_status/latest/btc_perpetual_data_source_decision_report.json")

MIN_SAMPLE_DAYS = 365.0
MIN_5M_BARS = 100_000
MIN_15M_BARS = 30_000
MIN_COMPLETENESS_RATIO = 0.995
REQUIRED_INTERVALS = ("5m", "15m")


def build_btc_intraday_short_cycle_alpha_plan_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    data_status = _read_json(root / BTC_DATA_STATUS)
    cost_model = _read_json(root / BTC_COST_MODEL)
    candidate_gate = _read_json(root / BTC_CANDIDATE_GATE)
    registry = _read_json(root / BTC_RESEARCH_REGISTRY)
    data_source_decision = _read_json(root / BTC_DATA_SOURCE_DECISION)

    coverage = _data_prerequisites(data_status)
    data_ready = _intraday_data_ready(coverage)
    status = "research_distribution_ready_candidate_blocked" if data_ready else "intraday_data_blocked"
    blockers = _blockers(
        data_ready=data_ready,
        coverage=coverage,
        data_status=data_status,
        cost_model=cost_model,
        candidate_gate=candidate_gate,
        data_source_decision=data_source_decision,
    )
    selected_style = _selected_research_style(data_ready=data_ready)
    return {
        "schema_version": "btc_intraday_short_cycle_alpha_plan_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_intraday_short_cycle_no_scalping_no_candidate_no_paper_no_live",
        "status": status,
        "decision": (
            "start_intraday_short_cycle_alpha_distribution"
            if data_ready
            else "extend_intraday_public_history_before_distribution"
        ),
        "next_required_action": (
            "run_research_only_intraday_short_cycle_distribution_probe"
            if data_ready
            else "repair_5m_15m_public_history_before_intraday_distribution_probe"
        ),
        "intraday_research_distribution_allowed": data_ready,
        "short_cycle_probe_allowed": data_ready,
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "source_data_status": _maybe_path(root, BTC_DATA_STATUS),
        "source_cost_model": _maybe_path(root, BTC_COST_MODEL),
        "source_candidate_gate": _maybe_path(root, BTC_CANDIDATE_GATE),
        "source_research_registry": _maybe_path(root, BTC_RESEARCH_REGISTRY),
        "source_data_source_decision": _maybe_path(root, BTC_DATA_SOURCE_DECISION),
        "data_status": str(data_status.get("status", "missing") or "missing"),
        "cost_model_status": str(cost_model.get("status", "missing") or "missing"),
        "candidate_gate_status": str(candidate_gate.get("status", "missing") or "missing"),
        "data_source_decision_status": str(data_source_decision.get("status", "missing") or "missing"),
        "current_candidate_count": len(_list_of_strings(_mapping(registry.get("btc")).get("current_candidates"))),
        "selected_research_style": selected_style,
        "candidate_families": _candidate_families(),
        "data_prerequisites": coverage,
        "cost_context": _cost_context(cost_model),
        "acceptance_gates": {
            "event_profit_factor_min": 1.15,
            "walk_forward_pass_rate_min": 0.80,
            "regime_pass_rate_min": 0.75,
            "cost_stress_required": True,
            "ledger_fill_pnl_required": True,
            "manifest_required": True,
            "no_lookahead": True,
            "candidate_generation_after_distribution_probe_only": True,
        },
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "intraday_research_distribution_allowed": data_ready,
            "short_cycle_probe_allowed": data_ready,
            "true_scalping_allowed": False,
            "sub_minute_or_tick_scalping_allowed": False,
            "maker_queue_assumption_without_orderbook_allowed": False,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "pnl_from_fill_ledger_required": True,
            "event_profit_factor_gate_required": True,
            "cost_stress_required": True,
            "walk_forward_required": True,
        },
        "interpretation": _interpretation(data_ready=data_ready, coverage=coverage, selected_style=selected_style),
        "blockers": blockers,
    }


def write_btc_intraday_short_cycle_alpha_plan_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_intraday_short_cycle_alpha_plan_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_alpha_plan_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_alpha_plan_report(payload, Path(args.output_root)))


def _data_prerequisites(data_status: Mapping[str, Any]) -> dict[str, Any]:
    coverage = _mapping(data_status.get("coverage"))
    bar_counts = _mapping(coverage.get("bar_count_by_interval"))
    completeness = _mapping(coverage.get("completeness_ratio_by_interval"))
    duplicate_counts = _mapping(coverage.get("duplicate_bar_count_by_interval"))
    missing_counts = _mapping(coverage.get("missing_bar_count_by_interval"))
    available = _list_of_strings(coverage.get("intervals_available"))
    sample_start = str(coverage.get("sample_start", ""))
    sample_end = str(coverage.get("sample_end", ""))
    interval_rows = {
        interval: {
            "bar_count": int(bar_counts.get(interval, 0) or 0),
            "min_required_bars": MIN_5M_BARS if interval == "5m" else MIN_15M_BARS,
            "completeness_ratio": _float_or_zero(completeness.get(interval)),
            "min_completeness_ratio": MIN_COMPLETENESS_RATIO,
            "missing_bar_count": int(missing_counts.get(interval, 0) or 0),
            "duplicate_bar_count": int(duplicate_counts.get(interval, 0) or 0),
        }
        for interval in REQUIRED_INTERVALS
    }
    return {
        "required_intervals": list(REQUIRED_INTERVALS),
        "present_intervals": available,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "sample_days": round(_sample_days(sample_start, sample_end), 6),
        "min_sample_days": MIN_SAMPLE_DAYS,
        "intervals": interval_rows,
        "data_status": str(data_status.get("status", "missing") or "missing"),
        "data_status_blockers": _list_of_strings(data_status.get("blockers")),
    }


def _intraday_data_ready(coverage: Mapping[str, Any]) -> bool:
    intervals = _mapping(coverage.get("intervals"))
    if coverage.get("sample_days", 0.0) < MIN_SAMPLE_DAYS:
        return False
    for interval in REQUIRED_INTERVALS:
        row = _mapping(intervals.get(interval))
        if int(row.get("bar_count", 0) or 0) < int(row.get("min_required_bars", 0) or 0):
            return False
        if _float_or_zero(row.get("completeness_ratio")) < MIN_COMPLETENESS_RATIO:
            return False
        if int(row.get("missing_bar_count", 0) or 0) != 0:
            return False
        if int(row.get("duplicate_bar_count", 0) or 0) != 0:
            return False
    return True


def _selected_research_style(*, data_ready: bool) -> dict[str, Any]:
    return {
        "style_id": "intraday_short_cycle_alpha_v0",
        "status": "ready_for_distribution_probe" if data_ready else "data_blocked",
        "primary_timeframes": list(REQUIRED_INTERVALS),
        "holding_period_intent": "minutes_to_hours_not_sub_minute_scalping",
        "core_hypothesis": (
            "BTC perpetual intraday edges should first be tested as event-ledger short-cycle alpha "
            "using 5m triggers, 15m confirmation, explicit costs, and walk-forward gates"
        ),
        "not_scalping_because": [
            "does not require sub-minute bars, tick data, order book queue position, or latency model",
            "does not assume maker fill priority or spread capture",
            "does not connect to any broker, private endpoint, paper runtime, or live runtime",
        ],
    }


def _candidate_families() -> list[dict[str, Any]]:
    return [
        {
            "family_id": "volatility_compression_reclaim_intraday_v0",
            "priority": 1,
            "selection_status": "distribution_probe_backlog",
            "primary_edge_inputs": ["5m_ohlcv", "15m_context", "range_reclaim", "realized_volatility"],
        },
        {
            "family_id": "liquidation_exhaustion_reclaim_intraday_v0",
            "priority": 2,
            "selection_status": "distribution_probe_backlog",
            "primary_edge_inputs": ["5m_ohlcv", "shock_recovery", "event_lifecycle", "tail_dependency_check"],
        },
        {
            "family_id": "funding_premium_reversion_intraday_v0",
            "priority": 3,
            "selection_status": "context_overlay_not_primary_alpha",
            "primary_edge_inputs": ["funding_rate", "premium_index", "mark_price", "15m_context"],
        },
        {
            "family_id": "orderflow_confirmed_momentum_intraday_v0",
            "priority": 4,
            "selection_status": "confirmation_only_until_orderbook_data_exists",
            "primary_edge_inputs": ["5m_ohlcv", "15m_momentum", "volume_expansion"],
        },
    ]


def _cost_context(cost_model: Mapping[str, Any]) -> dict[str, Any]:
    fee_model = _mapping(cost_model.get("fee_model"))
    fee_tier = _mapping(cost_model.get("fee_tier"))
    fee_tier_verified = cost_model.get(
        "fee_tier_verified",
        fee_tier.get("fee_tier_verified", fee_model.get("fee_tier_verified", False)),
    )
    maker_fee_bps = cost_model.get("maker_fee_bps", fee_tier.get("maker_fee_bps", fee_model.get("maker_fee_bps")))
    taker_fee_bps = cost_model.get("taker_fee_bps", fee_tier.get("taker_fee_bps", fee_model.get("taker_fee_bps")))
    return {
        "status": str(cost_model.get("status", "missing") or "missing"),
        "fee_tier_verified": bool(fee_tier_verified),
        "maker_fee_bps": _float_or_none(maker_fee_bps),
        "taker_fee_bps": _float_or_none(taker_fee_bps),
        "blockers": _list_of_strings(cost_model.get("blockers")),
    }


def _blockers(
    *,
    data_ready: bool,
    coverage: Mapping[str, Any],
    data_status: Mapping[str, Any],
    cost_model: Mapping[str, Any],
    candidate_gate: Mapping[str, Any],
    data_source_decision: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not data_status:
        blockers.append("btc_intraday_data_status_report_missing")
    if not data_ready:
        blockers.extend(_intraday_data_blockers(coverage))
    if str(cost_model.get("status", "missing") or "missing") != "pass":
        blockers.append("btc_intraday_cost_model_not_pass")
    if str(candidate_gate.get("status", "missing") or "missing") != "pass":
        blockers.append("btc_intraday_existing_candidate_gate_not_pass")
    blockers.extend(_list_of_strings(data_source_decision.get("blockers")))
    blockers.append("btc_intraday_candidate_generation_blocked_until_distribution_probe_passes")
    blockers.append("btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model")
    blockers.append("btc_intraday_paper_live_locked")
    return _dedupe(blockers)


def _intraday_data_blockers(coverage: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    intervals = _mapping(coverage.get("intervals"))
    if coverage.get("sample_days", 0.0) < MIN_SAMPLE_DAYS:
        blockers.append("btc_intraday_5m_15m_history_too_short")
    for interval in REQUIRED_INTERVALS:
        row = _mapping(intervals.get(interval))
        if int(row.get("bar_count", 0) or 0) < int(row.get("min_required_bars", 0) or 0):
            blockers.append(f"btc_intraday_{interval}_bars_too_short")
        if _float_or_zero(row.get("completeness_ratio")) < MIN_COMPLETENESS_RATIO:
            blockers.append(f"btc_intraday_{interval}_completeness_too_low")
        if int(row.get("missing_bar_count", 0) or 0) != 0:
            blockers.append(f"btc_intraday_{interval}_missing_bars_present")
        if int(row.get("duplicate_bar_count", 0) or 0) != 0:
            blockers.append(f"btc_intraday_{interval}_duplicate_bars_present")
    return blockers


def _interpretation(
    *,
    data_ready: bool,
    coverage: Mapping[str, Any],
    selected_style: Mapping[str, Any],
) -> list[str]:
    if data_ready:
        return [
            f"{selected_style['style_id']} can start research-only distribution probing on 5m/15m history",
            "this unlocks short-cycle alpha research only; it does not unlock candidate generation, paper, live, or scalping",
            "true scalping remains blocked until 1m/tick/orderbook/spread/latency/queue evidence exists",
        ]
    return [
        f"{selected_style['style_id']} remains blocked by insufficient 5m/15m evidence",
        (
            "repair intraday public history before any short-cycle distribution probe; "
            f"current sample_days={coverage.get('sample_days', 0.0)}"
        ),
        "candidate generation, paper review, live trading, and true scalping remain locked",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _sample_days(start: str, end: str) -> float:
    parsed_start = _parse_utc(start)
    parsed_end = _parse_utc(end)
    if not parsed_start or not parsed_end or parsed_end < parsed_start:
        return 0.0
    return (parsed_end - parsed_start).total_seconds() / 86_400.0


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: object) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


def _maybe_path(root: Path, path: Path) -> str | None:
    full = root / path
    return _relpath(full, root) if full.exists() else None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
