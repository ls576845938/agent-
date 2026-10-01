from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "btc_strategy_governance_freeze_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_strategy_governance_freeze/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_governance_freeze_report.json"
DEFAULT_ROWS_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_governance_freeze_rows.csv"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_governance_freeze_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_STRATEGY_LEDGER_REPORT = Path("artifacts/btc_strategy_ledger/latest/btc_strategy_ledger_report.json")
DEFAULT_LEAKAGE_OVERFIT_AUDIT_REPORT = Path(
    "artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json"
)

DANGEROUS_TRUE_KEYS = {
    "broker_access_allowed",
    "broker_or_order_allowed",
    "live_allowed",
    "live_order_allowed",
    "live_unlock_allowed",
    "oms_access_allowed",
    "order_endpoint_allowed",
    "order_endpoint_used",
    "paper_allowed",
    "paper_candidate_created",
    "paper_queue_write_allowed",
    "private_endpoint_used",
    "real_order_submitted",
    "strategy_skeleton_generated",
}


def build_btc_strategy_governance_freeze(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    strategy_ledger_report_path: Path = DEFAULT_STRATEGY_LEDGER_REPORT,
    leakage_overfit_audit_report_path: Path = DEFAULT_LEAKAGE_OVERFIT_AUDIT_REPORT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir = _resolve(root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = _resolve(root, strategy_ledger_report_path)
    audit_path = _resolve(root, leakage_overfit_audit_report_path)
    ledger = _read_json(ledger_path)
    audit = _read_json(audit_path)

    artifact_blockers: list[str] = []
    if not ledger["exists"]:
        artifact_blockers.append("btc_strategy_governance_missing_strategy_ledger")
    if ledger["error"]:
        artifact_blockers.append("btc_strategy_governance_invalid_strategy_ledger_json")
    if not audit["exists"]:
        artifact_blockers.append("btc_strategy_governance_missing_leakage_overfit_audit")
    if audit["error"]:
        artifact_blockers.append("btc_strategy_governance_invalid_leakage_overfit_audit_json")

    ledger_payload = _mapping(ledger["payload"])
    audit_payload = _mapping(audit["payload"])
    source_safety_violations = sorted(
        set(_unsafe_true_paths(ledger_payload, prefix="strategy_ledger") + _unsafe_true_paths(audit_payload, prefix="leakage_overfit_audit"))
    )
    if source_safety_violations:
        artifact_blockers.append("btc_strategy_governance_upstream_safety_violation_fail_closed")

    strategy_rows = _strategy_freeze_rows(ledger_payload, audit_payload)
    high_octane_limits = _high_octane_post_selection_limits(audit_payload)
    holdout_lock = _holdout_lock_policy(audit_payload)
    champion_challenger = _champion_challenger_policy(strategy_rows, audit_payload)
    promotion_blockers = _promotion_blockers(audit_payload, holdout_lock, high_octane_limits)

    report_path = output_dir / DEFAULT_REPORT_PATH.name
    rows_path = output_dir / DEFAULT_ROWS_PATH.name
    summary_path = output_dir / DEFAULT_SUMMARY_CN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if artifact_blockers else "complete_research_only",
        "decision": (
            "btc_strategy_governance_freeze_incomplete_fail_closed_no_paper_no_live"
            if artifact_blockers
            else "btc_strategy_governance_freeze_active_no_new_mining_no_paper_no_live"
        ),
        "scope": "read_only_strategy_governance_freeze_no_strategy_mining_no_paper_no_live",
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "inputs": {
            "strategy_ledger_report": _portable_path(ledger_path, root),
            "strategy_ledger_sha256": _sha256(ledger_path) if ledger["exists"] else None,
            "leakage_overfit_audit_report": _portable_path(audit_path, root),
            "leakage_overfit_audit_sha256": _sha256(audit_path) if audit["exists"] else None,
        },
        "strategy_ledger_freeze": {
            "freeze_id": _freeze_id(ledger_path, audit_path),
            "freeze_active": True,
            "frozen_strategy_line_count": len(strategy_rows),
            "new_strategy_mining_allowed": False,
            "strategy_family_expansion_allowed": False,
            "parameter_mutation_allowed": False,
            "selection_after_observe_allowed": False,
            "frozen_rows": strategy_rows,
        },
        "holdout_lock": holdout_lock,
        "champion_challenger": champion_challenger,
        "parameter_freeze": {
            "all_current_parameters_frozen": True,
            "mutation_requires_new_pre_registered_research_ticket": True,
            "forward_observe_data_cannot_be_used_for_selection": True,
            "rows": [
                {
                    "strategy_id": row["strategy_id"],
                    "parameter_hash": row["parameter_hash"],
                    "parameter_mutation_allowed": row["parameter_mutation_allowed"],
                    "post_selection_usage": row["post_selection_usage"],
                }
                for row in strategy_rows
            ],
        },
        "post_selection_usage_limits": {
            "global_rule": "observe-only data after the freeze can confirm or reject a predeclared candidate, but cannot be used to tune parameters, add variants, or re-rank the mined set.",
            "new_strategy_mining_allowed": False,
            "high_octane": high_octane_limits,
            "timesfm_auxiliary": {
                "model_role": "auxiliary_risk_diagnostic_only",
                "can_generate_orders": False,
                "can_unlock_paper": False,
            },
        },
        "promotion_status": "blocked_by_governance_and_existing_paper_gate",
        "promotion_blockers": promotion_blockers,
        "source_safety_violations": source_safety_violations,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "artifact_blockers": sorted(set(artifact_blockers)),
        "blockers": sorted(set(artifact_blockers + promotion_blockers)),
        "outputs": {
            "json": _portable_path(report_path, root),
            "csv": _portable_path(rows_path, root),
            "summary_cn": _portable_path(summary_path, root),
            "paper_live_safety_status": _portable_path(safety_path, root),
        },
    }
    _write_json(report_path, report)
    _write_csv(rows_path, strategy_rows)
    _write_text(summary_path, render_btc_strategy_governance_freeze_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_strategy_governance_freeze_markdown(report: Mapping[str, Any]) -> str:
    freeze = _mapping(report.get("strategy_ledger_freeze"))
    champion = _mapping(_nested(report, "champion_challenger", "champion"))
    high_octane = _mapping(_nested(report, "post_selection_usage_limits", "high_octane"))
    holdout = _mapping(report.get("holdout_lock"))
    lines = [
        "# BTC 策略治理冻结包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        "- 边界：不扩大策略挖矿，不新增策略族，不写 paper 队列，不解锁 live。",
        f"- 冻结策略线数量：`{freeze.get('frozen_strategy_line_count')}`",
        f"- Champion：`{champion.get('strategy_id')}`",
        f"- Holdout 锁：selection_use_blocked_by_lock=`{holdout.get('selection_use_blocked_by_lock')}`，clean_confirmation_ready=`{holdout.get('clean_forward_confirmation_ready')}`",
        f"- High-Octane 结论：`{high_octane.get('verdict')}`",
        "",
        "| 策略线 | 角色 | 冻结状态 | 参数 hash | post-selection 使用限制 |",
        "|---|---|---|---|---|",
    ]
    for row in _list_of_mappings(freeze.get("frozen_rows")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("strategy_id")),
                    _md(row.get("champion_challenger_role")),
                    _md(row.get("freeze_status")),
                    _md(row.get("parameter_hash")),
                    _md(row.get("post_selection_usage")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Promotion Blockers", ""])
    for blocker in _list_of_strings(report.get("promotion_blockers")) or ["none"]:
        lines.append(f"- `{blocker}`")
    lines.extend(
        [
            "",
            "## 使用限制",
            "",
            "- 30/60 天 observe-only 只能用于确认或否决冻结候选，不能拿来继续筛参数。",
            "- High-Octane 因为 40% 生存线压线，只能作为高风险 challenger 观察，不能晋级 paper。",
            "- TimesFM 只能做风险诊断辅助，不能独立产生下单方向。",
            "- 新策略、新 primitive、新 GA/网格挖矿必须另开预注册研究票据，不能混入当前冻结批次。",
        ]
    )
    return "\n".join(lines) + "\n"


def _strategy_freeze_rows(ledger: Mapping[str, Any], audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _list_of_mappings(ledger.get("strategy_lines")):
        strategy_id = str(row.get("strategy_id") or "")
        parameter_payload = row.get("parameter_summary")
        freeze_status = "frozen_research_only"
        role = "challenger_observe_only"
        post_selection_usage = "observe_only_confirmation_or_rejection_only"
        if strategy_id == "stable_long_short":
            freeze_status = "frozen_champion_observe_only"
            role = "champion"
            post_selection_usage = "may_be_compared_in_forward_observe_but_not_retuned"
        elif strategy_id == "attack_sleeve":
            freeze_status = "frozen_high_risk_challenger_observe_only"
            role = "high_risk_challenger"
            post_selection_usage = "spike_survival_and_risk_observe_only_no_parameter_changes"
        elif strategy_id == "high_yield":
            freeze_status = "frozen_low_priority_challenger_observe_only"
            role = "challenger"
        elif strategy_id == "raw_trend_legacy":
            freeze_status = "frozen_legacy_baseline"
            role = "legacy_baseline"
            post_selection_usage = "comparison_only_consider_archive"
        elif strategy_id == "timesfm_auxiliary":
            freeze_status = "frozen_auxiliary_diagnostic"
            role = "auxiliary_model"
            post_selection_usage = "risk_diagnostic_only_no_order_direction"
        rows.append(
            {
                "strategy_id": strategy_id,
                "latest_report_path": row.get("latest_report_path"),
                "latest_report_status": row.get("latest_report_status") or row.get("status"),
                "freeze_status": freeze_status,
                "champion_challenger_role": role,
                "parameter_hash": _stable_hash(parameter_payload),
                "parameter_summary": parameter_payload,
                "parameter_mutation_allowed": False,
                "paper_allowed": False,
                "live_unlock_allowed": False,
                "post_selection_usage": post_selection_usage,
                "source_blockers": _list_of_strings(row.get("blockers")),
            }
        )
    high_octane = _mapping(audit.get("high_octane_v2_audit"))
    if high_octane:
        rows.append(
            {
                "strategy_id": "high_octane_attack_sleeve_v2_audit_subject",
                "latest_report_path": _nested(audit, "input", "high_octane_report_path"),
                "latest_report_status": high_octane.get("artifact_status"),
                "freeze_status": "frozen_boundary_mined_high_risk_challenger",
                "champion_challenger_role": "restricted_challenger",
                "parameter_hash": _stable_hash(
                    {
                        "best_scenario_id": high_octane.get("best_scenario_id"),
                        "best_watchlist_tier": high_octane.get("best_watchlist_tier"),
                        "parameter_mining_audit": high_octane.get("parameter_mining_audit"),
                    }
                ),
                "parameter_summary": {
                    "best_scenario_id": high_octane.get("best_scenario_id"),
                    "best_watchlist_tier": high_octane.get("best_watchlist_tier"),
                    "overfit_verdict": high_octane.get("overfit_verdict"),
                    "parameter_mining_verdict": high_octane.get("parameter_mining_verdict"),
                },
                "parameter_mutation_allowed": False,
                "paper_allowed": False,
                "live_unlock_allowed": False,
                "post_selection_usage": "observe_only_rejection_or_hazard_evidence_only_no_tuning_no_promotion",
                "source_blockers": ["high_octane_parameter_boundary_mined_research_only"],
            }
        )
    return rows


def _holdout_lock_policy(audit: Mapping[str, Any]) -> dict[str, Any]:
    holdout = _mapping(audit.get("holdout_and_forward_observe_audit"))
    window = _mapping(holdout.get("future_observe_window"))
    return {
        "holdout_lock_status": holdout.get("holdout_lock_status"),
        "holdout_lock_decision": holdout.get("holdout_lock_decision"),
        "latest_common_history_end": holdout.get("latest_common_history_end"),
        "future_observe_window": window,
        "minimum_30d_complete": bool(holdout.get("minimum_30d_complete")),
        "clean_forward_confirmation_ready": bool(holdout.get("clean_forward_confirmation_ready")),
        "selection_use_blocked_by_lock": bool(holdout.get("selection_use_blocked_by_lock", True)),
        "observe_only_violation_count": _int(holdout.get("observe_only_violation_count")),
        "post_selection_rule": "future observe rows after lock may not be used to re-rank, retune, or add strategy variants.",
    }


def _champion_challenger_policy(rows: Sequence[Mapping[str, Any]], audit: Mapping[str, Any]) -> dict[str, Any]:
    by_id = {str(row.get("strategy_id")): row for row in rows}
    challengers = []
    for strategy_id in ("high_yield", "attack_sleeve", "high_octane_attack_sleeve_v2_audit_subject"):
        if strategy_id in by_id:
            challengers.append(
                {
                    "strategy_id": strategy_id,
                    "role": by_id[strategy_id].get("champion_challenger_role"),
                    "freeze_status": by_id[strategy_id].get("freeze_status"),
                    "paper_allowed": False,
                }
            )
    return {
        "champion": {
            "strategy_id": "stable_long_short" if "stable_long_short" in by_id else None,
            "selection_reason": "lowest governance risk among current BTC trade strategy lines; still requires forward confirmation and execution gates.",
            "paper_allowed": False,
        },
        "challengers": challengers,
        "retired_or_auxiliary": [
            {"strategy_id": "raw_trend_legacy", "role": "legacy_baseline"},
            {"strategy_id": "timesfm_auxiliary", "role": "auxiliary_model_no_orders"},
        ],
        "champion_change_allowed": False,
        "challenger_promotion_allowed": False,
        "manual_review_required_for_any_change": True,
        "audit_decision": audit.get("decision"),
    }


def _high_octane_post_selection_limits(audit: Mapping[str, Any]) -> dict[str, Any]:
    high_octane = _mapping(audit.get("high_octane_v2_audit"))
    mining = _mapping(high_octane.get("parameter_mining_audit"))
    summary = _mapping(audit.get("summary"))
    return {
        "verdict": high_octane.get("overfit_verdict") or summary.get("high_octane_overfit_verdict"),
        "parameter_mining_verdict": high_octane.get("parameter_mining_verdict")
        or summary.get("high_octane_parameter_mining_verdict"),
        "likely_parameter_mined_boundary_candidate": bool(
            high_octane.get("likely_parameter_mined_boundary_candidate")
            or summary.get("high_octane_likely_parameter_mined_boundary_candidate")
        ),
        "best_scenario_id": high_octane.get("best_scenario_id"),
        "best_watchlist_tier": high_octane.get("best_watchlist_tier"),
        "best_margin_over_40pct_threshold": high_octane.get("best_margin_over_40pct_threshold")
        if high_octane.get("best_margin_over_40pct_threshold") is not None
        else summary.get("high_octane_best_margin_over_40pct_threshold"),
        "threshold_margin_by_tier_pct": high_octane.get("threshold_margin_by_tier_pct")
        or summary.get("high_octane_threshold_margin_by_tier_pct"),
        "scenario_grid_count": mining.get("scenario_grid_count"),
        "watchlist_count": mining.get("watchlist_count"),
        "post_selection_usage_allowed": False,
        "paper_candidate_allowed": False,
        "parameter_retest_allowed_without_new_ticket": False,
        "allowed_use": "frozen observe-only hazard/challenger evidence; cannot be used as promotion evidence until a new pre-registered design passes clean forward confirmation.",
    }


def _promotion_blockers(audit: Mapping[str, Any], holdout: Mapping[str, Any], high_octane: Mapping[str, Any]) -> list[str]:
    blockers = [
        "btc_strategy_governance_no_new_strategy_mining",
        "btc_strategy_governance_parameter_freeze_active",
        "btc_strategy_governance_paper_live_gate_remains_blocked",
    ]
    if high_octane.get("likely_parameter_mined_boundary_candidate"):
        blockers.append("btc_strategy_governance_high_octane_parameter_boundary_mined")
    if high_octane.get("post_selection_usage_allowed") is False:
        blockers.append("btc_strategy_governance_high_octane_post_selection_use_blocked")
    if holdout.get("selection_use_blocked_by_lock"):
        blockers.append("btc_strategy_governance_holdout_selection_use_blocked")
    if not holdout.get("clean_forward_confirmation_ready"):
        blockers.append("btc_strategy_governance_forward_confirmation_not_ready")
    if _nested(audit, "summary", "paper_queue_write_allowed") is False:
        blockers.append("btc_strategy_governance_audit_research_only_no_paper")
    return sorted(set(blockers))


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, Any]:
    return {
        "read_only_artifact_aggregation": True,
        "network_collection_used": False,
        "strategy_rerun_used": False,
        "new_strategy_mining_allowed": False,
        "strategy_family_expansion_allowed": False,
        "parameter_mutation_allowed": False,
        "post_selection_reuse_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_strategy_governance_freeze_safety_status_v1",
        "status": "research_only",
        "source_report": _nested(report, "outputs", "json"),
        "strategy_governance_freeze_active": True,
        "new_strategy_mining_allowed": False,
        "parameter_mutation_allowed": False,
        "post_selection_reuse_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "payload": {}, "error": "missing"}
    try:
        return {"exists": True, "payload": json.loads(path.read_text(encoding="utf-8")), "error": None}
    except json.JSONDecodeError as exc:
        return {"exists": True, "payload": {}, "error": str(exc)}


def _unsafe_true_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in DANGEROUS_TRUE_KEYS and item is True:
                paths.append(path)
            paths.extend(_unsafe_true_paths(item, prefix=path))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            paths.extend(_unsafe_true_paths(item, prefix=f"{prefix}[{idx}]"))
    return paths


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "strategy_id",
        "champion_challenger_role",
        "freeze_status",
        "parameter_hash",
        "parameter_mutation_allowed",
        "paper_allowed",
        "live_unlock_allowed",
        "post_selection_usage",
        "latest_report_path",
        "latest_report_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _freeze_id(*paths: Path) -> str:
    payload = {str(path): _sha256(path) if path.exists() else "missing" for path in paths}
    return f"btc_strategy_freeze_{_stable_hash(payload)}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path | None, root: Path | None = None) -> str | None:
    if path is None:
        return None
    try:
        if root is not None:
            return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        pass
    return path.as_posix()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _git(args: Sequence[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None
