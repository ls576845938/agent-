from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.btc_strategy_bar_replay_visibility import DEFAULT_REPORT_PATH as DEFAULT_BAR_REPLAY_REPORT_PATH
from quant_crypto.research.high_octane_attack_sleeve_lab import DEFAULT_REPORT_PATH as DEFAULT_HIGH_OCTANE_REPORT_PATH
from quant_crypto.research.long_short_top5_review import DEFAULT_REPORT_PATH as DEFAULT_LONG_SHORT_TOP5_REPORT_PATH
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_confirmatory_holdout_lock_v1"
LOCK_CONFIG_SCHEMA_VERSION = "btc_confirmatory_holdout_lock_config_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_confirmatory_holdout_lock/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_confirmatory_holdout_lock_report.json"
DEFAULT_LOCKS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_confirmatory_holdout_lock_windows.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_confirmatory_holdout_lock_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_LOCK_CONFIG_PATH = Path("configs/btc/research_holdout/btc_confirmatory_holdout_locks.json")


def build_btc_confirmatory_holdout_lock(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    lock_config_path: Path = DEFAULT_LOCK_CONFIG_PATH,
    generated_at_utc: datetime | None = None,
    long_short_top5_report_path: Path = DEFAULT_LONG_SHORT_TOP5_REPORT_PATH,
    high_octane_report_path: Path = DEFAULT_HIGH_OCTANE_REPORT_PATH,
    bar_replay_report_path: Path = DEFAULT_BAR_REPLAY_REPORT_PATH,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    locks_csv_path = output_dir / DEFAULT_LOCKS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    long_short = _read_json(long_short_top5_report_path, blockers, "missing_long_short_top5_report")
    high_octane = _read_json(high_octane_report_path, blockers, "missing_high_octane_report")
    bar_replay = _read_json(bar_replay_report_path, blockers, "missing_bar_replay_visibility_report")

    lock_config = _lock_config(
        long_short=long_short,
        high_octane=high_octane,
        bar_replay=bar_replay,
        long_short_top5_report_path=long_short_top5_report_path,
        high_octane_report_path=high_octane_report_path,
        bar_replay_report_path=bar_replay_report_path,
    )
    blockers.extend(_config_blockers(lock_config, bar_replay=bar_replay))
    violations = _self_check_violations(lock_config)
    decision = "blocked_confirmatory_holdout_lock_no_paper_no_live" if blockers else "btc_confirmatory_holdout_locked_research_only_no_paper_no_live"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "lock_confirmatory_holdout_windows_before_next_btc_parameter_search",
        "code_commit": _git_commit(),
        "input": {
            "long_short_top5_report_path": _portable_path(long_short_top5_report_path),
            "high_octane_report_path": _portable_path(high_octane_report_path),
            "bar_replay_report_path": _portable_path(bar_replay_report_path),
            "lock_config_path": _portable_path(lock_config_path),
        },
        "summary": _summary(lock_config=lock_config, violations=violations, blockers=blockers, decision=decision),
        "lock_config": lock_config,
        "self_check_violations": violations,
        "checks": _checks(lock_config=lock_config, blockers=blockers, violations=violations),
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(lock_config=lock_config, blockers=blockers),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "lock_config": _portable_path(lock_config_path),
            "locks_csv": _portable_path(locks_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(lock_config_path, lock_config)
    _write_json(report_path, report)
    _write_csv(locks_csv_path, _lock_csv_rows(lock_config))
    _write_text(markdown_path, render_btc_confirmatory_holdout_lock_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def selection_window_violations(
    lock_config: Mapping[str, Any],
    *,
    selection_start: str | pd.Timestamp,
    selection_end: str | pd.Timestamp,
    purpose: str,
) -> list[dict[str, Any]]:
    start = _timestamp(selection_start)
    end = _timestamp(selection_end)
    if end < start:
        raise ValueError("selection_end must be >= selection_start")
    violations: list[dict[str, Any]] = []
    for lock in lock_config.get("locked_windows", []):
        if purpose not in set(lock.get("forbidden_uses", [])):
            continue
        window = lock.get("window", {})
        if _overlaps_locked_window(start, end, window):
            violations.append(
                {
                    "lock_id": lock.get("lock_id"),
                    "line": lock.get("line"),
                    "purpose": purpose,
                    "selection_start": _ts(start),
                    "selection_end": _ts(end),
                    "lock_window": window,
                    "severity": "fail",
                    "reason": "selection window overlaps a locked holdout or observe-only window",
                }
            )
    return violations


def render_btc_confirmatory_holdout_lock_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 确认性 holdout 锁定包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 锁定窗口数量：`{summary.get('lock_count')}`",
        f"- 历史已看过窗口：`{summary.get('historical_seen_lock_count')}`",
        f"- 未来 observe-only 窗口：`{summary.get('future_observe_only_lock_count')}`",
        f"- 最新共同历史截止：`{summary.get('latest_common_history_end')}`",
        f"- 自检违规数：`{summary.get('self_check_violation_count')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 规则",
        "",
        "- 已看过的历史确认窗口不能再用于参数搜索、候选排序、GA fitness、阈值微调或 watchlist 替换。",
        "- 2026-06-28 之后的新数据在 30/60 天观察完成前只允许 observe-only，不允许拿来继续调参。",
        "- High-Octane v2 截至当前的全历史窗口已经参与网格选择，所以不能把它伪装成干净 holdout。",
        "",
        "本锁定包只生成 research-only 约束和报告，不写 paper 队列，不生成策略骨架，不接 broker/OMS，不解锁 live。",
    ]
    return "\n".join(lines) + "\n"


def _lock_config(
    *,
    long_short: Mapping[str, Any],
    high_octane: Mapping[str, Any],
    bar_replay: Mapping[str, Any],
    long_short_top5_report_path: Path,
    high_octane_report_path: Path,
    bar_replay_report_path: Path,
) -> dict[str, Any]:
    ls_window = _long_short_holdout_window(long_short)
    high_window = _high_octane_history_window(high_octane, bar_replay)
    latest_common_end = _latest_common_history_end(ls_window, high_window, bar_replay)
    forward_30d_end = _add_days(latest_common_end, 30)
    forward_60d_end = _add_days(latest_common_end, 60)
    locks = [
        {
            "lock_id": "btc_ls_top5_historical_confirmation_holdout_v1",
            "line": "long_short_donchian_top5",
            "lock_type": "historical_confirmation_holdout_already_reviewed",
            "window": {
                "start_inclusive": ls_window.get("start"),
                "end_inclusive": ls_window.get("end"),
                "row_count": ls_window.get("row_count"),
            },
            "locked_before_next_search": True,
            "clean_pre_selection_holdout": bool(long_short.get("review_design", {}).get("clean_pre_selection_holdout", False)),
            "already_seen_by_human_or_report": True,
            "allowed_uses": ["audit_replay", "fixed_parameter_regression", "historical_context"],
            "forbidden_uses": _forbidden_selection_uses(),
            "source_artifact": _portable_path(long_short_top5_report_path),
            "source_note": long_short.get("review_design", {}).get("clean_pre_selection_holdout_note"),
        },
        {
            "lock_id": "btc_high_octane_v2_selection_consumed_history_v1",
            "line": "high_octane_attack_sleeve_v2",
            "lock_type": "selection_consumed_history_not_clean_holdout",
            "window": {
                "start_inclusive": high_window.get("start"),
                "end_inclusive": high_window.get("end"),
                "row_count": high_window.get("row_count"),
            },
            "locked_before_next_search": True,
            "clean_pre_selection_holdout": False,
            "already_seen_by_human_or_report": True,
            "allowed_uses": ["audit_replay", "fixed_parameter_regression", "historical_context"],
            "forbidden_uses": _forbidden_selection_uses(),
            "source_artifact": _portable_path(high_octane_report_path),
            "source_note": "High-Octane v2 was selected from this full historical grid window; future tuning must not reuse it as clean confirmation.",
        },
        {
            "lock_id": "btc_post_20260628_forward_observe_only_v1",
            "line": "btc_all_current_research_lines",
            "lock_type": "future_confirmatory_holdout_observe_only",
            "window": {
                "start_exclusive": latest_common_end,
                "planned_30d_end_inclusive": forward_30d_end,
                "planned_60d_end_inclusive": forward_60d_end,
                "end_inclusive": forward_60d_end,
                "open_until_observation_complete": True,
            },
            "locked_before_next_search": True,
            "clean_pre_selection_holdout": True,
            "already_seen_by_human_or_report": False,
            "allowed_uses": ["observe_only_signal_recording", "no_order_forward_monitoring"],
            "forbidden_uses": _forbidden_selection_uses() + ["paper_candidate_creation", "live_unlock"],
            "source_artifact": _portable_path(bar_replay_report_path),
            "source_note": "New data after the latest completed common history is reserved for 30/60 day observe-only confirmation.",
        },
    ]
    config = {
        "schema_version": LOCK_CONFIG_SCHEMA_VERSION,
        "lock_config_id": "btc_confirmatory_holdout_locks_current",
        "latest_common_history_end": latest_common_end,
        "source_reports": {
            "long_short_top5_report_path": _portable_path(long_short_top5_report_path),
            "high_octane_report_path": _portable_path(high_octane_report_path),
            "bar_replay_report_path": _portable_path(bar_replay_report_path),
            "long_short_report_commit": long_short.get("code_commit"),
            "high_octane_report_commit": high_octane.get("code_commit"),
            "bar_replay_report_commit": bar_replay.get("code_commit"),
        },
        "global_policy": {
            "default_for_new_btc_research": "check_selection_window_violations_before_parameter_search",
            "parameter_search_requires_no_overlap_with_forbidden_locked_windows": True,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "locked_windows": locks,
    }
    config["lock_config_hash"] = _hash_without_self(config)
    return config


def _long_short_holdout_window(report: Mapping[str, Any]) -> dict[str, Any]:
    for row in report.get("candidate_reviews", []):
        holdout = row.get("confirmation_holdout", {})
        if holdout.get("start") and holdout.get("end"):
            return {"start": holdout.get("start"), "end": holdout.get("end"), "row_count": holdout.get("row_count")}
    return {"start": None, "end": None, "row_count": 0}


def _high_octane_history_window(report: Mapping[str, Any], bar_replay: Mapping[str, Any]) -> dict[str, Any]:
    input_block = report.get("input", {})
    if input_block.get("market_4h_start") and input_block.get("market_4h_end"):
        return {
            "start": input_block.get("market_4h_start"),
            "end": input_block.get("market_4h_end"),
            "row_count": input_block.get("market_4h_rows"),
        }
    replay = bar_replay.get("long_short_top5_bar_replay", {})
    return {"start": replay.get("market_start"), "end": replay.get("market_end"), "row_count": replay.get("market_4h_row_count")}


def _latest_common_history_end(ls_window: Mapping[str, Any], high_window: Mapping[str, Any], bar_replay: Mapping[str, Any]) -> str | None:
    candidates = [ls_window.get("end"), high_window.get("end"), bar_replay.get("long_short_top5_bar_replay", {}).get("market_end")]
    timestamps = [_timestamp(value) for value in candidates if value]
    if not timestamps:
        return None
    return _ts(min(timestamps))


def _config_blockers(lock_config: Mapping[str, Any], *, bar_replay: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not lock_config.get("latest_common_history_end"):
        blockers.append("btc_holdout_lock_missing_latest_common_history_end")
    if not lock_config.get("locked_windows"):
        blockers.append("btc_holdout_lock_missing_locked_windows")
    if bar_replay:
        summary = bar_replay.get("summary", {})
        if int(summary.get("check_fail_count", 0) or 0) != 0:
            blockers.append("btc_holdout_lock_bar_replay_has_failed_checks")
        if bar_replay.get("gate", {}).get("paper_queue_write_allowed") or bar_replay.get("gate", {}).get("live_unlock_allowed"):
            blockers.append("btc_holdout_lock_source_gate_boundary_invalid")
    return blockers


def _self_check_violations(lock_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for lock in lock_config.get("locked_windows", []):
        window = lock.get("window", {})
        start = window.get("start_inclusive") or window.get("start_exclusive")
        end = window.get("end_inclusive")
        if not start or not end:
            violations.append({"lock_id": lock.get("lock_id"), "severity": "fail", "reason": "missing window boundary"})
            continue
        violations.extend(selection_window_violations(lock_config, selection_start=start, selection_end=end, purpose="parameter_search"))
    return violations


def _checks(*, lock_config: Mapping[str, Any], blockers: Sequence[str], violations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        _check("inputs", "required_reports_present", "pass" if not any(item.startswith("missing_") for item in blockers) else "fail", ",".join(blockers)),
        _check("bar_replay", "bar_replay_source_has_no_failed_checks", "pass" if "btc_holdout_lock_bar_replay_has_failed_checks" not in blockers else "fail", "bar replay must pass before holdout lock is trusted"),
        _check("lock_config", "locked_windows_declared", "pass" if len(lock_config.get("locked_windows", [])) >= 3 else "fail", f"lock_count={len(lock_config.get('locked_windows', []))}"),
        _check("lock_config", "selection_overlap_self_check_blocks_parameter_search", "pass" if len(violations) >= 3 else "fail", f"self_check_violation_count={len(violations)}"),
        _check("safety", "paper_live_locked", "pass", "paper_queue_write_allowed=false; live_unlock_allowed=false"),
    ]


def _summary(*, lock_config: Mapping[str, Any], violations: Sequence[Mapping[str, Any]], blockers: Sequence[str], decision: str) -> dict[str, Any]:
    locks = lock_config.get("locked_windows", [])
    return {
        "decision": decision,
        "lock_count": len(locks),
        "historical_seen_lock_count": sum(1 for row in locks if row.get("already_seen_by_human_or_report")),
        "future_observe_only_lock_count": sum(1 for row in locks if row.get("lock_type") == "future_confirmatory_holdout_observe_only"),
        "latest_common_history_end": lock_config.get("latest_common_history_end"),
        "self_check_violation_count": len(violations),
        "blocker_count": len(set(blockers)),
        "lock_config_hash": lock_config.get("lock_config_hash"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _lock_csv_rows(lock_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lock in lock_config.get("locked_windows", []):
        window = lock.get("window", {})
        rows.append(
            {
                "lock_id": lock.get("lock_id"),
                "line": lock.get("line"),
                "lock_type": lock.get("lock_type"),
                "start_inclusive": window.get("start_inclusive"),
                "start_exclusive": window.get("start_exclusive"),
                "end_inclusive": window.get("end_inclusive"),
                "planned_30d_end_inclusive": window.get("planned_30d_end_inclusive"),
                "planned_60d_end_inclusive": window.get("planned_60d_end_inclusive"),
                "clean_pre_selection_holdout": lock.get("clean_pre_selection_holdout"),
                "already_seen_by_human_or_report": lock.get("already_seen_by_human_or_report"),
                "forbidden_uses": lock.get("forbidden_uses"),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return rows


def _overlaps_locked_window(start: pd.Timestamp, end: pd.Timestamp, window: Mapping[str, Any]) -> bool:
    end_inclusive = window.get("end_inclusive")
    if not end_inclusive:
        return False
    lock_end = _timestamp(end_inclusive)
    if window.get("start_inclusive"):
        lock_start = _timestamp(window["start_inclusive"])
        return start <= lock_end and end >= lock_start
    if window.get("start_exclusive"):
        lock_start = _timestamp(window["start_exclusive"])
        return start <= lock_end and end > lock_start
    return False


def _forbidden_selection_uses() -> list[str]:
    return [
        "parameter_search",
        "candidate_ranking",
        "ga_fitness",
        "threshold_tuning",
        "watchlist_replacement",
        "paper_promotion_evidence_as_sole_basis",
    ]


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Holdout lock is a research constraint and cannot promote strategies.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(*, lock_config: Mapping[str, Any], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_confirmatory_holdout_lock_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_confirmatory_holdout_lock_blocked")
    if any(not lock.get("clean_pre_selection_holdout") for lock in lock_config.get("locked_windows", [])):
        warnings.append("some_locked_windows_are_already_seen_not_clean_holdout")
    warnings.append("future_observe_only_window_must_not_be_used_for_parameter_tuning")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_confirmatory_holdout_lock_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Holdout lock output is diagnostic and constraining only.",
    }


def _check(line: str, check_id: str, status: str, evidence: str) -> dict[str, Any]:
    return {
        "line": line,
        "check_id": check_id,
        "status": status,
        "evidence": evidence,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _read_json(path: Path, blockers: list[str], blocker_name: str) -> dict[str, Any]:
    if not path.exists():
        blockers.append(blocker_name)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return _timestamp(value).isoformat()


def _add_days(value: str | None, days: int) -> str | None:
    if value is None:
        return None
    return _ts(_timestamp(value).to_pydatetime() + timedelta(days=days))


def _hash_without_self(payload: Mapping[str, Any]) -> str:
    data = dict(payload)
    data.pop("lock_config_hash", None)
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
