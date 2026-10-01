#!/usr/bin/env python3
"""Validate the US equity strategy registry."""

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

from scripts.build_us_equity_strategy_production_line_report import STAGE_ORDER


SCHEMA_VERSION = "us_equity_strategy_registry_report_v1"
DEFAULT_REGISTRY = Path("configs/strategies/us_equity_strategy_registry.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_registry/latest/us_equity_strategy_registry_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 策略池注册表审计.md")
REQUIRED_STRATEGY_KEYS = {
    "strategy_id",
    "family",
    "status",
    "current_stage",
    "hypothesis",
    "parameter_space",
    "data_dependencies",
    "cost_model",
    "failure_conditions",
    "source_reports",
    "guardrails",
}
REQUIRED_HYPOTHESIS_KEYS = {"alpha_sources", "risk_premia_explanation", "known_risks"}
REQUIRED_FAMILIES = {
    "us_etf_macro_momentum_rotation",
    "dual_momentum",
    "absolute_momentum",
    "topn_etf_rotation",
    "regime_overlay",
    "151_trading_strategies_migration",
}
REQUIRED_FORMAL_SOURCE_REPORT_KEYS = {
    "data_ingestion",
    "data_freshness",
    "etf_kline_quality_daily",
    "fred_macro_preflight",
    "data_source_reconciliation",
    "data_lineage_remediation",
    "production_data_acquisition_plan",
    "production_pit_intake_status",
    "pit_bundle_acceptance",
    "macro_release_lag_policy",
    "research_backtest",
    "standard_report_schema_audit",
    "top_candidate_validation",
    "walk_forward_parameter_stability_gate",
    "strategy_validation_gate",
    "forward_observation",
    "forward_observation_evaluation",
    "forward_observation_daily_health",
    "manual_review",
    "paper_simulation_readiness",
    "live_readiness",
    "monitoring_rules",
    "replay_readiness",
}


def build_us_equity_strategy_registry_report(
    *,
    repo_root: Path | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    registry_abs = _resolve(root, registry_path)
    registry = _read_json(registry_abs)
    blockers: list[str] = []
    warnings: list[str] = []

    if not registry:
        blockers.append("us_equity_strategy_registry_missing")
    policy = _mapping(registry.get("policy"))
    if policy.get("unregistered_strategy_promotion_allowed") is not False:
        blockers.append("us_equity_strategy_registry_unregistered_promotion_not_forbidden")
    if policy.get("paper_or_live_unlock_allowed_by_registry") is not False:
        blockers.append("us_equity_strategy_registry_can_unlock_paper_or_live")
    if policy.get("private_endpoint_allowed") is not False or policy.get("order_endpoint_allowed") is not False:
        blockers.append("us_equity_strategy_registry_endpoint_policy_unsafe")
    if _list_of_str(registry.get("production_line_order")) != STAGE_ORDER:
        blockers.append("us_equity_strategy_registry_stage_order_mismatch")

    strategies = _list(registry.get("strategies"))
    seen_ids: set[str] = set()
    family_set = {str(item.get("family", "")) for item in strategies if isinstance(item, Mapping)}
    missing_families = sorted(REQUIRED_FAMILIES - family_set)
    if missing_families:
        blockers.append("us_equity_strategy_registry_required_families_missing")

    strategy_rows = []
    for index, strategy in enumerate(strategies):
        row = _validate_strategy(root, strategy, index, seen_ids)
        strategy_rows.append(row)
        blockers.extend(row["blockers"])
        warnings.extend(row["warnings"])

    primary_count = sum(1 for row in strategy_rows if row["primary_candidate"])
    if primary_count != 1:
        blockers.append("us_equity_strategy_registry_primary_candidate_count_not_one")

    formal_candidates = [
        row
        for row in strategy_rows
        if row["status"] not in {"hypothesis_registered_only"} or row["current_stage"] != "strategy_hypothesis_registration"
    ]
    source_report_contract = _formal_source_report_contract(formal_candidates)
    for row in strategy_rows:
        if not row["strategy_card_exists"]:
            blockers.append(f"us_equity_strategy_registry_strategy_card_missing:{row['strategy_id']}")
    for row in formal_candidates:
        if not row["source_report_contract_passed"]:
            blockers.append(f"us_equity_strategy_registry_formal_source_report_contract_failed:{row['strategy_id']}")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "pass" if not blockers else "blocked",
        "asset": "us_equity",
        "registry_path": _relpath(registry_abs, root),
        "strategy_count": len(strategy_rows),
        "primary_candidate_count": primary_count,
        "required_families": sorted(REQUIRED_FAMILIES),
        "missing_required_families": missing_families,
        "formal_candidate_count": len(formal_candidates),
        "formal_candidate_source_report_contract": source_report_contract,
        "strategy_rows": strategy_rows,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "guardrails": {
            "unregistered_strategy_promotion_allowed": False,
            "paper_or_live_unlock_allowed_by_registry": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _validate_strategy(root: Path, strategy: Any, index: int, seen_ids: set[str]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if not isinstance(strategy, Mapping):
        return {
            "index": index,
            "strategy_id": "",
            "family": "",
            "status": "",
            "current_stage": "",
            "primary_candidate": False,
            "strategy_card_exists": False,
            "design_spec_report": "",
            "design_spec_exists": False,
            "design_spec_registry_id_matches": False,
            "blockers": [f"us_equity_strategy_registry_strategy_not_object:{index}"],
            "warnings": [],
        }
    strategy_id = str(strategy.get("strategy_id", ""))
    family = str(strategy.get("family", ""))
    status = str(strategy.get("status", ""))
    current_stage = str(strategy.get("current_stage", ""))
    primary = strategy.get("primary_candidate") is True
    missing_keys = sorted(key for key in REQUIRED_STRATEGY_KEYS if key not in strategy)
    blockers.extend([f"us_equity_strategy_registry_missing_{key}:{strategy_id or index}" for key in missing_keys])
    if not strategy_id:
        blockers.append(f"us_equity_strategy_registry_strategy_id_missing:{index}")
    elif strategy_id in seen_ids:
        blockers.append(f"us_equity_strategy_registry_duplicate_strategy_id:{strategy_id}")
    seen_ids.add(strategy_id)
    if current_stage and current_stage not in STAGE_ORDER:
        blockers.append(f"us_equity_strategy_registry_invalid_stage:{strategy_id}")

    hypothesis = _mapping(strategy.get("hypothesis"))
    missing_hypothesis = sorted(key for key in REQUIRED_HYPOTHESIS_KEYS if not hypothesis.get(key))
    blockers.extend([f"us_equity_strategy_registry_missing_hypothesis_{key}:{strategy_id}" for key in missing_hypothesis])
    for key in ("parameter_space", "data_dependencies", "cost_model"):
        if not _mapping(strategy.get(key)):
            blockers.append(f"us_equity_strategy_registry_empty_{key}:{strategy_id}")
    if not _list(strategy.get("failure_conditions")):
        blockers.append(f"us_equity_strategy_registry_empty_failure_conditions:{strategy_id}")

    guardrails = _mapping(strategy.get("guardrails"))
    for key in ("paper_ready", "live_ready", "real_order_allowed", "private_endpoint_allowed", "order_endpoint_allowed"):
        if guardrails.get(key) is True:
            blockers.append(f"us_equity_strategy_registry_forbidden_guardrail_true:{strategy_id}.{key}")
    if guardrails.get("backtest_allowed_without_registration") is not False:
        warnings.append(f"us_equity_strategy_registry_backtest_without_registration_not_explicitly_false:{strategy_id}")

    source_reports = _mapping(strategy.get("source_reports"))
    missing_required_source_keys = sorted(REQUIRED_FORMAL_SOURCE_REPORT_KEYS - set(source_reports))
    missing_source_paths = []
    for name, value in source_reports.items():
        path = _resolve(root, Path(str(value)))
        if not path.exists():
            missing_source_paths.append(str(name))
    if missing_source_paths and status != "hypothesis_registered_only":
        blockers.append(f"us_equity_strategy_registry_source_reports_missing:{strategy_id}")
    if not source_reports and status != "hypothesis_registered_only":
        blockers.append(f"us_equity_strategy_registry_formal_strategy_without_source_reports:{strategy_id}")

    design_spec_report = str(strategy.get("design_spec_report", "") or "")
    design_spec_exists = False
    design_spec_registry_id_matches = False
    if status == "hypothesis_registered_only" and current_stage == "strategy_hypothesis_registration":
        if not design_spec_report:
            blockers.append(f"us_equity_strategy_registry_design_spec_report_missing:{strategy_id}")
        else:
            design_spec_path = _resolve(root, Path(design_spec_report))
            design_spec_exists = design_spec_path.exists()
            if not design_spec_exists:
                blockers.append(f"us_equity_strategy_registry_design_spec_report_not_found:{strategy_id}")
            else:
                design_spec = _read_json(design_spec_path)
                registry_strategy_id = str(design_spec.get("registry_strategy_id", "") or "")
                design_status = str(design_spec.get("status", "") or "")
                design_spec_registry_id_matches = registry_strategy_id == strategy_id
                if not design_spec_registry_id_matches:
                    blockers.append(f"us_equity_strategy_registry_design_spec_id_mismatch:{strategy_id}")
                if design_status != "design_spec_ready":
                    blockers.append(f"us_equity_strategy_registry_design_spec_not_ready:{strategy_id}")

    card_path = str(strategy.get("strategy_card", ""))
    card_exists = bool(card_path) and _resolve(root, Path(card_path)).exists()
    return {
        "index": index,
        "strategy_id": strategy_id,
        "family": family,
        "status": status,
        "current_stage": current_stage,
        "primary_candidate": primary,
        "strategy_card": card_path,
        "strategy_card_exists": card_exists,
        "design_spec_report": design_spec_report,
        "design_spec_exists": design_spec_exists,
        "design_spec_registry_id_matches": design_spec_registry_id_matches,
        "source_report_count": len(source_reports),
        "missing_required_source_report_keys": missing_required_source_keys
        if status != "hypothesis_registered_only" or current_stage != "strategy_hypothesis_registration"
        else [],
        "source_report_contract_passed": (
            status == "hypothesis_registered_only"
            and current_stage == "strategy_hypothesis_registration"
        )
        or (not missing_required_source_keys and not missing_source_paths),
        "missing_source_report_keys": missing_source_paths,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
    }


def _formal_source_report_contract(formal_candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    missing_by_strategy = {
        str(row.get("strategy_id")): _list_of_str(row.get("missing_required_source_report_keys"))
        for row in formal_candidates
        if _list_of_str(row.get("missing_required_source_report_keys"))
    }
    path_missing_by_strategy = {
        str(row.get("strategy_id")): _list_of_str(row.get("missing_source_report_keys"))
        for row in formal_candidates
        if _list_of_str(row.get("missing_source_report_keys"))
    }
    passed_count = sum(1 for row in formal_candidates if row.get("source_report_contract_passed") is True)
    return {
        "required_keys": sorted(REQUIRED_FORMAL_SOURCE_REPORT_KEYS),
        "candidate_count": len(formal_candidates),
        "passed_count": passed_count,
        "missing_required_keys_by_strategy": missing_by_strategy,
        "missing_paths_by_strategy": path_missing_by_strategy,
        "passed": passed_count == len(formal_candidates),
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 策略池注册表审计",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 策略数：`{payload.get('strategy_count', 0)}`",
        f"- 主候选数：`{payload.get('primary_candidate_count', 0)}`",
        f"- 正式候选数：`{payload.get('formal_candidate_count', 0)}`",
        "",
        "## 策略池",
        "",
        "| strategy_id | family | status | stage | blockers |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in _list(payload.get("strategy_rows")):
        blockers = ", ".join(_list(row.get("blockers"))) or "-"
        lines.append(
            f"| `{row.get('strategy_id', '')}` | `{row.get('family', '')}` | `{row.get('status', '')}` | `{row.get('current_stage', '')}` | {blockers} |"
        )
    lines += ["", "## 全局 Blockers", ""]
    for blocker in _list(payload.get("blockers")):
        lines.append(f"- `{blocker}`")
    if not _list(payload.get("blockers")):
        lines.append("- 无")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity strategy registry report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_strategy_registry_report(
        repo_root=Path(args.repo_root),
        registry_path=Path(args.registry_path),
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
