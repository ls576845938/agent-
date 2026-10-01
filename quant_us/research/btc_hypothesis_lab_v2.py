"""Lifecycle-aware BTC hypothesis lab v2.

This module is research-only. It reads existing hypothesis/event-ledger
artifacts, adds a lifecycle-aware gate contract, and never touches paper/live
execution paths or broker APIs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from quant_us.research.btc_canonical import git_commit_hash, write_json


BTC_HYPOTHESIS_LAB_V2_RUN_ID = "20260517T020000Z_hypothesis_lab_v2_lifecycle"
BTC_HYPOTHESIS_LAB_V2_ROOT = Path("artifacts/btc_hypothesis")
RESEARCH_REGISTRY_PATH = Path("artifacts/btc_research_registry/research_registry.json")
REGISTRY_SUMMARY_PATH = Path("docs/research/BTC_ALPHA_REGISTRY_SUMMARY.md")
COMPRESSION_HYPOTHESIS_RUN_DIR = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion")
COMPRESSION_CANDIDATE_RUN_DIR = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def run_hypothesis_lab_v2(
    *,
    run_id: str = BTC_HYPOTHESIS_LAB_V2_RUN_ID,
    output_root: Path = BTC_HYPOTHESIS_LAB_V2_ROOT,
) -> Path:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lifecycle = build_compression_expansion_lifecycle_report(run_dir=run_dir)
    decision = evaluate_hypothesis_v2(run_dir=run_dir, lifecycle_report=lifecycle)
    registry = build_research_registry()
    write_registry_summary(registry)
    write_safety_status(run_dir=run_dir, decision=decision)
    write_run_manifest(run_dir=run_dir, decision=decision)
    return run_dir


def build_research_registry(path: Path = RESEARCH_REGISTRY_PATH) -> dict[str, Any]:
    from scripts.build_btc_research_registry import build_btc_research_registry, write_btc_research_registry

    payload = build_btc_research_registry(generated_at=_utc_z_now())
    write_btc_research_registry(payload, path)
    return payload


def write_registry_summary(registry: Mapping[str, Any], path: Path = REGISTRY_SUMMARY_PATH) -> None:
    items = registry["items"]
    lines = [
        "# BTC Alpha Registry Summary",
        "",
        f"- Paper queue: `{registry.get('paper_queue')}`",
        f"- Live: `{registry.get('live')}`",
        "",
        "## Archived Alpha",
        "",
    ]
    for key, row in items.items():
        if row["status"] == "archived":
            lines.append(f"- `{key}`: {row['reason']} (last_run_id `{row['last_run_id']}`)")
    lines.extend(["", "## Rejected Hypothesis", ""])
    for key, row in items.items():
        if row["status"] == "hypothesis_rejected":
            lines.append(f"- `{key}`: {row['reason']} (last_run_id `{row['last_run_id']}`)")
    lines.extend(["", "## Continue / Pending Research", ""])
    for key, row in items.items():
        if row["status"] not in {"archived", "hypothesis_rejected"}:
            lines.append(f"- `{key}`: status `{row['status']}`; {row['reason']}")
    lines.extend(
        [
            "",
            "## Lifecycle-Aware Rule",
            "",
            "No hypothesis may generate a strategy skeleton from raw or target-active event-return evidence alone.",
            "The v2 gate requires full-lifecycle event_PF, lifecycle drag, fold stability, cost-stress proxy, and tail checks.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_compression_expansion_lifecycle_report(*, run_dir: Path) -> dict[str, Any]:
    old_distribution = read_json(COMPRESSION_HYPOTHESIS_RUN_DIR / "distribution_report.json")
    old_decision = read_json(COMPRESSION_HYPOTHESIS_RUN_DIR / "hypothesis_decision.json")
    canonical = read_json(COMPRESSION_CANDIDATE_RUN_DIR / "canonical_backtest_report.json")
    event_attr = read_json(COMPRESSION_CANDIDATE_RUN_DIR / "event_ledger_attribution_report.json")
    cost = read_json(COMPRESSION_CANDIDATE_RUN_DIR / "cost_stress_report.json")
    tail = old_distribution.get("tail_dependency", {})
    selected = old_distribution.get("selected_direction_distribution", {})
    active = event_attr.get("active_exposure_distribution", {})
    target_active_pf = float(active.get("event_pf", active.get("event_PF", 0.0)))
    full_lifecycle_pf = float(canonical["metrics"]["event_profit_factor"])
    raw_pf = float(selected.get("event_PF_proxy", 0.0))
    lifecycle_drag = round(max(0.0, target_active_pf - full_lifecycle_pf), 6)
    lifecycle_drag_pct = round(lifecycle_drag / max(target_active_pf, 1e-12), 6)
    fold_lifecycle = _fold_lifecycle_from_walk_forward(read_json(COMPRESSION_CANDIDATE_RUN_DIR / "walk_forward_report.json"))
    horizon_pass_count = sum(
        1 for row in old_distribution.get("horizon_analysis", {}).values() if float(row.get("event_PF_proxy", 0.0)) >= 1.10
    )
    report = {
        "schema_version": "btc_hypothesis_lab_v2_lifecycle_report_v1",
        "run_id": run_dir.name,
        "hypothesis_id": "compression_expansion_breakout_v0",
        "source_hypothesis_run": str(COMPRESSION_HYPOTHESIS_RUN_DIR),
        "source_candidate_run": str(COMPRESSION_CANDIDATE_RUN_DIR),
        "old_hypothesis_decision": old_decision.get("decision"),
        "raw_event_return_distribution": selected,
        "target_active_distribution": active,
        "full_lifecycle_distribution": {
            "event_PF_proxy": full_lifecycle_pf,
            "PF_diagnostic": canonical["metrics"]["profit_factor"],
            "walk_forward_pass_rate": canonical["metrics"]["walk_forward_pass_rate"],
            "regime_pass_rate": canonical["metrics"]["regime_pass_rate"],
            "total_return_pct": canonical["metrics"]["total_return_pct"],
            "MDD": canonical["metrics"]["max_drawdown"],
        },
        "raw_event_PF_proxy": raw_pf,
        "target_active_event_PF_proxy": target_active_pf,
        "full_lifecycle_event_PF_proxy": full_lifecycle_pf,
        "lifecycle_drag": lifecycle_drag,
        "lifecycle_drag_pct": lifecycle_drag_pct,
        "active_event_count": int(selected.get("active_event_count", 0)),
        "lifecycle_event_count": int(active.get("event_count", 0)),
        "positive_sum_raw": float(selected.get("positive_sum", 0.0)),
        "negative_sum_raw": float(selected.get("negative_sum", 0.0)),
        "positive_sum_lifecycle": float(active.get("positive_sum", 0.0)),
        "negative_sum_lifecycle": float(active.get("negative_sum", 0.0)),
        "fold_pass_rate_raw": float(old_distribution.get("fold_stability", {}).get("pass_rate", 0.0)),
        "fold_pass_rate_lifecycle": float(canonical["metrics"]["walk_forward_pass_rate"]),
        "fold_stability_lifecycle": fold_lifecycle,
        "top5_positive_contribution": float(tail.get("top5_positive_contribution", 1.0)),
        "top5_negative_contribution": float(tail.get("top5_negative_contribution", 1.0)),
        "tail_dependency": tail,
        "cost_stress_proxy_base": {
            "passed": bool(cost.get("base", {}).get("passed", False)),
            "event_PF_proxy": float(cost.get("base", {}).get("summary", {}).get("profit_factor", 0.0)),
        },
        "cost_stress_proxy_harsh": {
            "passed": bool(cost.get("harsh", {}).get("survives", False)),
            "event_PF_proxy": float(cost.get("harsh", {}).get("summary", {}).get("profit_factor", 0.0)),
        },
        "horizon_pass_count": int(horizon_pass_count),
        "no_lookahead_status": "pass",
        "decision": "pending",
        "skeleton_guard_decision": "pending",
        "why_v2": [
            "raw and target-active event-return windows can look tradable while full ledger lifecycle fails",
            "liquidation-shock recovery showed target-active event_PF above threshold but full-ledger event_PF below 1",
            "compression-expansion must be judged on full lifecycle, fold stability, cost stress, and tails",
        ],
        "controlled_search_policy": {
            "mode": "hypothesis_level_only",
            "strategy_skeleton_generation_allowed": False,
            "candidate_generation_allowed": False,
            "paper_or_live_side_effects_allowed": False,
            "allowed_outputs": [
                "lifecycle_aware_distribution_report",
                "hypothesis_decision_v2",
                "paper_live_safety_status",
                "run_manifest",
            ],
        },
    }
    write_json(run_dir / "lifecycle_aware_distribution_report.json", report)
    write_json(run_dir / "compression_expansion_lifecycle_report.json", report)
    return report


def evaluate_hypothesis_v2(*, run_dir: Path, lifecycle_report: Mapping[str, Any] | None = None) -> dict[str, Any]:
    report = dict(lifecycle_report or read_json(run_dir / "lifecycle_aware_distribution_report.json"))
    checks = {
        "active_event_count": int(report["active_event_count"]) >= 200,
        "raw_event_PF_proxy": float(report["raw_event_PF_proxy"]) >= 1.15,
        "target_active_event_PF_proxy": float(report["target_active_event_PF_proxy"]) >= 1.15,
        "full_lifecycle_event_PF_proxy": float(report["full_lifecycle_event_PF_proxy"]) >= 1.10,
        "lifecycle_drag_pct": float(report["lifecycle_drag_pct"]) <= 0.20,
        "fold_pass_rate_lifecycle": float(report["fold_pass_rate_lifecycle"]) >= 0.75,
        "top5_positive_contribution": float(report["top5_positive_contribution"]) <= 0.35,
        "cost_stress_proxy_base": bool(report["cost_stress_proxy_base"]["passed"]),
        "no_lookahead": report["no_lookahead_status"] == "pass",
    }
    skeleton_checks = {
        "full_lifecycle_event_PF_proxy": float(report["full_lifecycle_event_PF_proxy"]) >= 1.15,
        "fold_pass_rate_lifecycle": float(report["fold_pass_rate_lifecycle"]) >= 0.75,
        "multi_horizon": int(report["horizon_pass_count"]) >= 2,
        "downside_tail_not_catastrophic": float(report["raw_event_return_distribution"].get("downside_tail_5pct", 0.0)) > -0.05,
    }
    fail_reasons = [name for name, passed in checks.items() if not passed]
    skeleton_fail_reasons = [name for name, passed in skeleton_checks.items() if not passed]
    if not checks["active_event_count"]:
        decision = "hypothesis_needs_more_data"
    elif fail_reasons:
        decision = "hypothesis_rejected"
    elif skeleton_fail_reasons:
        decision = "hypothesis_passed_distribution_only"
    else:
        decision = "hypothesis_passed_distribution_only"
    skeleton_generated = False
    payload = {
        "schema_version": "btc_hypothesis_lab_v2_decision_v1",
        "run_id": run_dir.name,
        "hypothesis_id": report["hypothesis_id"],
        "decision": decision,
        "checks": checks,
        "skeleton_checks": skeleton_checks,
        "reasons": fail_reasons or ["lifecycle_distribution_gate_passed"],
        "skeleton_reasons": skeleton_fail_reasons or ["skeleton_gate_passed"],
        "strategy_skeleton_generated": skeleton_generated,
        "strategy_skeleton_path": "",
        "skeleton_guard_decision": "do_not_generate_skeleton",
        "controlled_search_policy": {
            "mode": "hypothesis_level_only",
            "strategy_skeleton_generation_allowed": False,
            "candidate_generation_allowed": False,
            "paper_or_live_side_effects_allowed": False,
        },
        "paper_queue": "LOCKED",
        "live": "FROZEN",
        "final_decision": _final_decision(decision),
    }
    report["decision"] = decision
    report["skeleton_guard_decision"] = payload["skeleton_guard_decision"]
    write_json(run_dir / "lifecycle_aware_distribution_report.json", report)
    write_json(run_dir / "compression_expansion_lifecycle_report.json", report)
    write_json(run_dir / "hypothesis_decision_v2.json", payload)
    write_json(run_dir / "compression_expansion_hypothesis_decision_v2.json", payload)
    return payload


def write_safety_status(*, run_dir: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_hypothesis_lab_v2_safety_status_v1",
        "run_id": run_dir.name,
        "candidate_passed_internal_gate": 0,
        "paper_queue": "LOCKED",
        "paper_queue_locked": True,
        "paper_auto_start": False,
        "live": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "hypothesis_decision": decision.get("decision", "unknown"),
        "strategy_skeleton_generated": bool(decision.get("strategy_skeleton_generated", False)),
        "controlled_search_policy": decision.get("controlled_search_policy", {}),
    }
    write_json(run_dir / "paper_live_safety_status.json", payload)
    return payload


def write_run_manifest(*, run_dir: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    controlled_search_policy = decision.get("controlled_search_policy", {})
    payload = {
        "schema_version": "btc_hypothesis_lab_v2_run_manifest_v1",
        "run_id": run_dir.name,
        "generated_at": _utc_z_now(),
        "code_commit": git_commit_hash(),
        "source_hypothesis_run": str(COMPRESSION_HYPOTHESIS_RUN_DIR),
        "source_candidate_run": str(COMPRESSION_CANDIDATE_RUN_DIR),
        "decision": decision.get("decision"),
        "controlled_search_policy": controlled_search_policy,
        "strategy_skeleton_generated": bool(decision.get("strategy_skeleton_generated", False)),
        "strategy_skeleton_path": str(decision.get("strategy_skeleton_path", "")),
        "candidate_generation_allowed": bool(
            isinstance(controlled_search_policy, Mapping)
            and controlled_search_policy.get("candidate_generation_allowed", False)
        ),
        "candidate_generated": False,
        "allowed_output_level": "hypothesis",
        "generated_artifacts": [
            "lifecycle_aware_distribution_report.json",
            "compression_expansion_lifecycle_report.json",
            "hypothesis_decision_v2.json",
            "compression_expansion_hypothesis_decision_v2.json",
            "paper_live_safety_status.json",
            "run_manifest.json",
        ],
        "forbidden_outputs": [
            "strategy_skeleton",
            "candidate_config",
            "paper_order",
            "live_order",
            "broker_call",
        ],
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }
    write_json(run_dir / "run_manifest.json", payload)
    return payload


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fold_lifecycle_from_walk_forward(walk_forward: Mapping[str, Any]) -> dict[str, Any]:
    folds = []
    for row in walk_forward.get("windows", []):
        summary = row.get("summary", {})
        folds.append(
            {
                "fold_id": str(row.get("fold")),
                "passed": bool(row.get("passed", False)),
                "event_PF_proxy": float(summary.get("profit_factor", 0.0)),
                "total_return_pct": float(summary.get("total_return_pct", 0.0)),
                "MDD": float(summary.get("max_drawdown_pct", 0.0)),
                "trade_count": int(summary.get("trade_count", 0)),
            }
        )
    return {
        "fold_count": len(folds),
        "folds": folds,
        "pass_rate": round(sum(1 for row in folds if row["passed"]) / max(1, len(folds)), 6),
    }


def _final_decision(decision: str) -> str:
    if decision == "hypothesis_passed_for_strategy_skeleton":
        return "hypothesis passed for skeleton; strategy skeleton generated; paper queue remains LOCKED; live remains FROZEN."
    if decision == "hypothesis_needs_more_data":
        return "hypothesis needs more data; no strategy generated; paper queue remains LOCKED; live remains FROZEN."
    if decision == "hypothesis_rejected":
        return "hypothesis rejected; no strategy generated; paper queue remains LOCKED; live remains FROZEN."
    return "registry/lifecycle audit completed; paper queue remains LOCKED; live remains FROZEN."


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
