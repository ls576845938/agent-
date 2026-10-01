from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_observe_only_health_report_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_observe_only_health/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_observe_only_health_report.json"
DEFAULT_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_observe_only_health_matrix.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_observe_only_health_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_LONG_SHORT_REPORT = Path("artifacts/btc_long_short_top5_forward_observer/latest/btc_long_short_top5_forward_observer_report.json")
DEFAULT_LONG_SHORT_ROWS = Path("artifacts/btc_long_short_top5_forward_observer/latest/btc_long_short_top5_forward_observations_latest.csv")
DEFAULT_ATTACK_REPORT = Path("artifacts/btc_bankroll_attack_forward_observer/latest/btc_bankroll_attack_forward_observer_report.json")
DEFAULT_ATTACK_ROWS = Path("artifacts/btc_bankroll_attack_forward_observer/latest/btc_bankroll_attack_forward_observations_latest.csv")
DEFAULT_HIGH_YIELD_REPORT = Path("artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_followup_report.json")
DEFAULT_HIGH_YIELD_ROWS = Path("artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_daily_observation_latest.csv")

MIN_30D_DAYS = 30
TARGET_60D_DAYS = 60
MAX_CALENDAR_GAP_DAYS = 1
MAX_LATEST_STALENESS_DAYS = 1

BAD_TRUE_FLAGS = {
    "paper_queue_write_allowed",
    "paper_candidate_created",
    "paper_order_intake_allowed",
    "position_increase_allowed",
    "strategy_skeleton_generated",
    "live_unlock_allowed",
    "live_order_allowed",
    "micro_live_allowed",
    "broker_access_allowed",
    "oms_access_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
}

LINE_SPECS = (
    {
        "line_id": "long_short_donchian_top5",
        "observer_id": "btc_long_short_donchian_top5_observe_only_v1",
        "report_path": DEFAULT_LONG_SHORT_REPORT,
        "rows_path": DEFAULT_LONG_SHORT_ROWS,
        "entity_field": "candidate_id",
        "report_progress_path": ("observation_progress",),
        "report_lock_path": ("holdout_lock",),
    },
    {
        "line_id": "high_octane_attack_sleeve_v2",
        "observer_id": "btc_bankroll_attack_top_10x_observe_only_v1",
        "report_path": DEFAULT_ATTACK_REPORT,
        "rows_path": DEFAULT_ATTACK_ROWS,
        "entity_field": "top_scenario_id",
        "report_progress_path": ("observation_progress",),
        "report_lock_path": ("holdout_lock",),
    },
    {
        "line_id": "high_yield_donchian_v2",
        "observer_id": "btc_high_yield_v2_frozen_observe_only_v1",
        "report_path": DEFAULT_HIGH_YIELD_REPORT,
        "rows_path": DEFAULT_HIGH_YIELD_ROWS,
        "entity_field": "variant_id",
        "report_progress_path": ("step_1_daily_observation_automation",),
        "report_lock_path": ("step_1_daily_observation_automation", "holdout_lock"),
    },
)


def build_btc_observe_only_health_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    long_short_report_path: Path = DEFAULT_LONG_SHORT_REPORT,
    long_short_rows_path: Path = DEFAULT_LONG_SHORT_ROWS,
    attack_report_path: Path = DEFAULT_ATTACK_REPORT,
    attack_rows_path: Path = DEFAULT_ATTACK_ROWS,
    high_yield_report_path: Path = DEFAULT_HIGH_YIELD_REPORT,
    high_yield_rows_path: Path = DEFAULT_HIGH_YIELD_ROWS,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    matrix_path = output_dir / DEFAULT_MATRIX_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    specs = _line_specs(
        long_short_report_path=long_short_report_path,
        long_short_rows_path=long_short_rows_path,
        attack_report_path=attack_report_path,
        attack_rows_path=attack_rows_path,
        high_yield_report_path=high_yield_report_path,
        high_yield_rows_path=high_yield_rows_path,
    )
    matrix = [_line_health(spec, generated=generated) for spec in specs]
    blockers = _blockers(matrix)
    status = "blocked_research_only" if blockers else "complete_research_only"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "decision": (
            "btc_observe_only_health_blocked_collect_more_days_no_paper_no_live"
            if blockers
            else "btc_observe_only_health_ready_for_manual_60d_review_no_auto_paper_no_live"
        ),
        "scope": "btc_30_60_day_observe_only_continuity_and_safety_health",
        "code_commit": _git_commit(),
        "input": {
            "long_short_report_path": _portable_path(long_short_report_path),
            "long_short_rows_path": _portable_path(long_short_rows_path),
            "attack_report_path": _portable_path(attack_report_path),
            "attack_rows_path": _portable_path(attack_rows_path),
            "high_yield_report_path": _portable_path(high_yield_report_path),
            "high_yield_rows_path": _portable_path(high_yield_rows_path),
        },
        "policy": {
            "minimum_30d_days": MIN_30D_DAYS,
            "target_60d_days": TARGET_60D_DAYS,
            "max_calendar_gap_days": MAX_CALENDAR_GAP_DAYS,
            "max_latest_staleness_days": MAX_LATEST_STALENESS_DAYS,
            "observe_only_may_record_theoretical_signal_only": True,
            "selection_or_parameter_use_forbidden_during_lock": True,
        },
        "summary": _summary(matrix=matrix, blockers=blockers),
        "matrix": matrix,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(matrix=matrix, blockers=blockers),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_rows_csv(matrix_path, matrix)
    _write_text(markdown_path, render_btc_observe_only_health_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_observe_only_health_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# BTC observe-only 30/60 天健康总表",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 观察线数量：`{summary.get('line_count')}`",
        f"- 满 30 天数量：`{summary.get('minimum_30d_complete_count')}`",
        f"- 满 60 天数量：`{summary.get('target_60d_complete_count')}`",
        f"- 连续性通过数量：`{summary.get('continuity_passed_count')}`",
        f"- 安全旗标违规数量：`{summary.get('safety_violation_count')}`",
        f"- paper/live 允许：`false`",
        "",
        "## 分线状态",
        "",
        "| 策略线 | 观察日 | 30天 | 60天 | 最大断档 | 最新日期 | 安全违规 | 结论 |",
        "|---|---:|---|---|---:|---|---:|---|",
    ]
    for row in report.get("matrix", []):
        lines.append(
            "| `{line}` | {days} | `{d30}` | `{d60}` | {gap} | {latest} | {violations} | `{decision}` |".format(
                line=row.get("line_id"),
                days=row.get("observation_days"),
                d30=row.get("minimum_30d_complete"),
                d60=row.get("target_60d_complete"),
                gap=row.get("max_calendar_gap_days"),
                latest=row.get("latest_observation_date"),
                violations=row.get("safety_violation_count"),
                decision=row.get("line_decision"),
            )
        )
    lines.extend(["", "## 阻断项", ""])
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers[:100])
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "说明：这份报告只检查 observe-only 观察连续性和安全边界，不写 paper 队列，不生成策略骨架，不连接 broker/OMS，不使用 private/order endpoint，不解锁 live。",
        ]
    )
    return "\n".join(lines) + "\n"


def _line_specs(
    *,
    long_short_report_path: Path,
    long_short_rows_path: Path,
    attack_report_path: Path,
    attack_rows_path: Path,
    high_yield_report_path: Path,
    high_yield_rows_path: Path,
) -> list[dict[str, Any]]:
    overrides = {
        "long_short_donchian_top5": (long_short_report_path, long_short_rows_path),
        "high_octane_attack_sleeve_v2": (attack_report_path, attack_rows_path),
        "high_yield_donchian_v2": (high_yield_report_path, high_yield_rows_path),
    }
    specs: list[dict[str, Any]] = []
    for spec in LINE_SPECS:
        report_path, rows_path = overrides[str(spec["line_id"])]
        item = dict(spec)
        item["report_path"] = report_path
        item["rows_path"] = rows_path
        specs.append(item)
    return specs


def _line_health(spec: Mapping[str, Any], *, generated: datetime) -> dict[str, Any]:
    report_path = Path(spec["report_path"])
    rows_path = Path(spec["rows_path"])
    report = _read_json(report_path)
    rows = _read_csv(rows_path)
    progress = _nested_mapping(report, *spec.get("report_progress_path", ()))
    lock = _nested_mapping(report, *spec.get("report_lock_path", ()))
    dates = _decision_dates(rows)
    duplicate_keys = _duplicate_keys(rows, entity_field=str(spec.get("entity_field")))
    safety_paths = _true_flag_paths(report)
    row_safety_paths = _row_safety_violations(rows)
    row_holdout_violations = _row_holdout_violations(rows)
    missing_required_row_flags = _missing_required_row_flags(rows)
    max_gap = _max_gap_days(dates)
    latest_date = dates[-1] if dates else None
    staleness = _staleness_days(latest_date, generated.date())
    observation_days = len(dates)
    report_observation_days = _int(progress.get("observation_days"))
    blockers: list[str] = []
    if not report:
        blockers.append("observer_report_missing")
    if not rows:
        blockers.append("observation_rows_missing")
    if observation_days < MIN_30D_DAYS:
        blockers.append("forward_observation_under_30d")
    if observation_days < TARGET_60D_DAYS:
        blockers.append("forward_observation_under_60d")
    if max_gap > MAX_CALENDAR_GAP_DAYS:
        blockers.append("observation_calendar_gap_gt_1d")
    if staleness > MAX_LATEST_STALENESS_DAYS:
        blockers.append("latest_observation_stale_gt_1d")
    if duplicate_keys:
        blockers.append("duplicate_observation_keys")
    if safety_paths or row_safety_paths:
        blockers.append("paper_live_or_order_safety_flag_true")
    if missing_required_row_flags:
        blockers.append("required_row_safety_flags_missing")
    if report_observation_days > 0 and report_observation_days != observation_days:
        blockers.append("report_progress_days_mismatch_csv_unique_days")
    if _int(lock.get("observe_only_violation_count")) or row_holdout_violations:
        blockers.append("observe_only_lock_violation")
    if lock and lock.get("selection_use_blocked_by_lock") is not True:
        blockers.append("selection_use_not_blocked_by_holdout_lock")
    return {
        "line_id": spec.get("line_id"),
        "observer_id": spec.get("observer_id"),
        "report_path": _portable_path(report_path),
        "rows_path": _portable_path(rows_path),
        "report_present": bool(report),
        "rows_present": bool(rows),
        "report_status": report.get("status") if report else None,
        "row_count": len(rows),
        "entity_count": len({str(row.get(spec.get("entity_field", ""), "")) for row in rows if row.get(spec.get("entity_field", ""))}),
        "observation_days": observation_days,
        "report_observation_days": report_observation_days,
        "report_observation_days_matches_rows": report_observation_days in {0, observation_days},
        "first_observation_date": dates[0].isoformat() if dates else None,
        "latest_observation_date": latest_date.isoformat() if latest_date else None,
        "latest_staleness_days": staleness,
        "max_calendar_gap_days": max_gap,
        "continuity_passed": bool(dates) and max_gap <= MAX_CALENDAR_GAP_DAYS,
        "minimum_30d_complete": observation_days >= MIN_30D_DAYS,
        "target_60d_complete": observation_days >= TARGET_60D_DAYS,
        "holdout_lock_present": bool(lock.get("lock_config_present")),
        "observe_only_violation_count": _int(lock.get("observe_only_violation_count")) + len(row_holdout_violations),
        "selection_use_blocked_by_lock": bool(lock.get("selection_use_blocked_by_lock")),
        "duplicate_key_count": len(duplicate_keys),
        "duplicate_keys": duplicate_keys[:20],
        "missing_required_row_flag_count": len(missing_required_row_flags),
        "missing_required_row_flags": missing_required_row_flags[:20],
        "safety_violation_count": len(safety_paths) + len(row_safety_paths),
        "report_safety_violations": safety_paths[:40],
        "row_safety_violations": row_safety_paths[:40],
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "line_decision": "observe_only_gate_blocked_collect_more_days_no_paper_no_live" if blockers else "observe_only_60d_complete_manual_review_only_no_auto_paper_no_live",
        "line_blockers": sorted(set(blockers)),
    }


def _summary(*, matrix: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> dict[str, Any]:
    return {
        "line_count": len(matrix),
        "minimum_30d_complete_count": sum(1 for row in matrix if row.get("minimum_30d_complete")),
        "target_60d_complete_count": sum(1 for row in matrix if row.get("target_60d_complete")),
        "continuity_passed_count": sum(1 for row in matrix if row.get("continuity_passed")),
        "safety_violation_count": sum(_int(row.get("safety_violation_count")) for row in matrix),
        "observe_only_violation_count": sum(_int(row.get("observe_only_violation_count")) for row in matrix),
        "blocker_count": len(blockers),
        "all_lines_minimum_30d_complete": all(row.get("minimum_30d_complete") for row in matrix),
        "all_lines_target_60d_complete": all(row.get("target_60d_complete") for row in matrix),
        "all_lines_continuity_passed": all(row.get("continuity_passed") for row in matrix),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _blockers(matrix: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for row in matrix:
        line = row.get("line_id")
        for blocker in row.get("line_blockers", []):
            blockers.append(f"{line}:{blocker}")
        for flag in BAD_TRUE_FLAGS:
            if row.get(flag) is True:
                blockers.append(f"{line}:unsafe_summary_flag_true:{flag}")
    return sorted(set(blockers))


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "forward_observation_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "reason": "Observe-only health can only prove observation discipline; it cannot promote paper/live by itself.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "forward_observation_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(*, matrix: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_observe_only_health_research_only_no_order_no_broker"]
    if blockers:
        warnings.append("observe_only_health_not_ready_for_paper_review")
    if any(_int(row.get("observation_days")) < MIN_30D_DAYS for row in matrix):
        warnings.append("30d_forward_observation_not_complete")
    if any(_int(row.get("max_calendar_gap_days")) > MAX_CALENDAR_GAP_DAYS for row in matrix):
        warnings.append("observe_only_calendar_gap_detected")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_observe_only_health_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "forward_observation_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _decision_dates(rows: Sequence[Mapping[str, str]]) -> list[date]:
    dates: set[date] = set()
    for row in rows:
        parsed = _parse_datetime(row.get("decision_time"))
        if parsed is not None:
            dates.add(parsed.date())
    return sorted(dates)


def _duplicate_keys(rows: Sequence[Mapping[str, str]], *, entity_field: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        key = f"{row.get('observer_id', '')}|{row.get(entity_field, '')}|{row.get('decision_time', '')}"
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return sorted(duplicates)


def _row_safety_violations(rows: Sequence[Mapping[str, str]]) -> list[str]:
    violations: list[str] = []
    for idx, row in enumerate(rows):
        for field in BAD_TRUE_FLAGS:
            if _bool(row.get(field)) is True:
                violations.append(f"row[{idx}].{field}=true")
    return violations


def _missing_required_row_flags(rows: Sequence[Mapping[str, str]]) -> list[str]:
    missing: list[str] = []
    for idx, row in enumerate(rows):
        for field in ("paper_queue_write_allowed", "live_unlock_allowed"):
            if field not in row or row.get(field) == "":
                missing.append(f"row[{idx}].{field}")
    return missing


def _row_holdout_violations(rows: Sequence[Mapping[str, str]]) -> list[str]:
    violations: list[str] = []
    for idx, row in enumerate(rows):
        nested = _row_holdout(row)
        if _int(nested.get("observe_only_violation_count")):
            violations.append(f"row[{idx}].holdout_lock.observe_only_violation_count")
        if nested and nested.get("paper_queue_write_allowed") is True:
            violations.append(f"row[{idx}].holdout_lock.paper_queue_write_allowed")
        if nested and nested.get("live_unlock_allowed") is True:
            violations.append(f"row[{idx}].holdout_lock.live_unlock_allowed")
    return violations


def _row_holdout(row: Mapping[str, str]) -> Mapping[str, Any]:
    if row.get("holdout_lock"):
        try:
            value = json.loads(str(row.get("holdout_lock")))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, Mapping) else {}
    prefix = "holdout_lock."
    nested = {key[len(prefix) :]: _coerce_scalar(value) for key, value in row.items() if key.startswith(prefix) and value != ""}
    return nested


def _true_flag_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_str = str(key)
            child_prefix = f"{prefix}.{key_str}" if prefix else key_str
            if key_str in BAD_TRUE_FLAGS and child is True:
                paths.append(child_prefix)
            paths.extend(_true_flag_paths(child, child_prefix))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            paths.extend(_true_flag_paths(child, f"{prefix}[{idx}]"))
    return paths


def _max_gap_days(dates: Sequence[date]) -> int:
    if len(dates) < 2:
        return 0
    return max((dates[idx] - dates[idx - 1]).days for idx in range(1, len(dates)))


def _staleness_days(latest: date | None, generated_date: date) -> int:
    if latest is None:
        return 9999
    return max(0, (generated_date - latest).days)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "line_id",
        "observer_id",
        "report_status",
        "row_count",
        "entity_count",
        "observation_days",
        "report_observation_days",
        "report_observation_days_matches_rows",
        "first_observation_date",
        "latest_observation_date",
        "latest_staleness_days",
        "max_calendar_gap_days",
        "continuity_passed",
        "minimum_30d_complete",
        "target_60d_complete",
        "holdout_lock_present",
        "observe_only_violation_count",
        "selection_use_blocked_by_lock",
        "duplicate_key_count",
        "missing_required_row_flag_count",
        "safety_violation_count",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
        "line_decision",
        "line_blockers",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _nested_mapping(value: Mapping[str, Any], *keys: Any) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _coerce_scalar(value: str) -> Any:
    text = str(value)
    lower = text.strip().lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        return int(text)
    except ValueError:
        return text


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
