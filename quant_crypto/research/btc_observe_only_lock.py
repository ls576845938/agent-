from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.btc_confirmatory_holdout_lock import (
    DEFAULT_LOCK_CONFIG_PATH,
    selection_window_violations,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _portable_path


SCHEMA_VERSION = "btc_observe_only_holdout_lock_status_v1"
OBSERVE_ONLY_PURPOSE = "observe_only_signal_recording"
FORBIDDEN_SELECTION_PURPOSES = [
    "parameter_search",
    "candidate_ranking",
    "ga_fitness",
    "threshold_tuning",
    "watchlist_replacement",
    "paper_promotion_evidence_as_sole_basis",
    "paper_candidate_creation",
    "live_unlock",
]


def read_holdout_lock_config(path: Path = DEFAULT_LOCK_CONFIG_PATH) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if not path.exists():
        return {}, ["btc_observe_only_holdout_lock_config_missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["btc_observe_only_holdout_lock_config_unreadable"]
    if not isinstance(payload, dict):
        return {}, ["btc_observe_only_holdout_lock_config_not_object"]
    if payload.get("schema_version") != "btc_confirmatory_holdout_lock_config_v1":
        blockers.append("btc_observe_only_holdout_lock_schema_mismatch")
    policy = payload.get("global_policy", {})
    if policy.get("paper_queue_write_allowed") is not False:
        blockers.append("btc_observe_only_holdout_lock_policy_allows_paper")
    if policy.get("live_unlock_allowed") is not False:
        blockers.append("btc_observe_only_holdout_lock_policy_allows_live")
    if not payload.get("locked_windows"):
        blockers.append("btc_observe_only_holdout_lock_missing_windows")
    return payload, blockers


def observe_only_lock_status(
    *,
    lock_config: Mapping[str, Any],
    decision_times: Sequence[str | pd.Timestamp],
    observer_id: str,
    holdout_lock_path: Path = DEFAULT_LOCK_CONFIG_PATH,
) -> dict[str, Any]:
    unique_times = sorted({_ts(value) for value in decision_times if value})
    latest_common_end = lock_config.get("latest_common_history_end")
    latest_common_ts = _timestamp_or_none(latest_common_end)
    future_window = _future_observe_only_window(lock_config)
    planned_30d_end = _timestamp_or_none(future_window.get("planned_30d_end_inclusive"))
    planned_60d_end = _timestamp_or_none(future_window.get("planned_60d_end_inclusive") or future_window.get("end_inclusive"))

    row_checks: list[dict[str, Any]] = []
    observe_violations: list[dict[str, Any]] = []
    selection_violations: list[dict[str, Any]] = []
    for value in unique_times:
        ts = _timestamp(value)
        observe = selection_window_violations(
            lock_config,
            selection_start=ts,
            selection_end=ts,
            purpose=OBSERVE_ONLY_PURPOSE,
        )
        observe_violations.extend(observe)
        purpose_counts: dict[str, int] = {}
        for purpose in FORBIDDEN_SELECTION_PURPOSES:
            violations = selection_window_violations(
                lock_config,
                selection_start=ts,
                selection_end=ts,
                purpose=purpose,
            )
            purpose_counts[purpose] = len(violations)
            selection_violations.extend(violations)
        selection_count = sum(purpose_counts.values())
        row_checks.append(
            {
                "decision_time": _ts(ts),
                "relation_to_lock": _relation_to_lock(
                    ts,
                    latest_common_ts=latest_common_ts,
                    planned_30d_end=planned_30d_end,
                    planned_60d_end=planned_60d_end,
                ),
                "observe_only_purpose": OBSERVE_ONLY_PURPOSE,
                "observe_only_allowed": len(observe) == 0,
                "observe_only_violation_count": len(observe),
                "selection_use_forbidden": selection_count > 0,
                "selection_violation_count": selection_count,
                "selection_violation_counts_by_purpose": purpose_counts,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )

    blockers: list[str] = []
    if not lock_config:
        blockers.append("btc_observe_only_holdout_lock_config_missing")
    if not unique_times:
        blockers.append("btc_observe_only_holdout_lock_no_decision_times")
    if observe_violations:
        blockers.append("btc_observe_only_holdout_lock_observe_purpose_forbidden")
    policy = lock_config.get("global_policy", {})
    if policy.get("paper_queue_write_allowed") is not False:
        blockers.append("btc_observe_only_holdout_lock_policy_allows_paper")
    if policy.get("live_unlock_allowed") is not False:
        blockers.append("btc_observe_only_holdout_lock_policy_allows_live")

    relation_counts = Counter(str(row.get("relation_to_lock")) for row in row_checks)
    warnings: list[str] = []
    if any(row.get("relation_to_lock") in {"locked_history_or_anchor", "before_locked_history"} for row in row_checks):
        warnings.append("observe_only_row_is_not_new_forward_holdout_data")
    if any(row.get("relation_to_lock") == "beyond_planned_60d_observe_window" for row in row_checks):
        warnings.append("observe_only_row_beyond_planned_60d_window_requires_manual_lock_refresh")
    if not selection_violations:
        warnings.append("selection_use_not_blocked_for_current_decision_times_review_lock_scope")

    return {
        "schema_version": SCHEMA_VERSION,
        "observer_id": observer_id,
        "holdout_lock_path": _portable_path(holdout_lock_path),
        "lock_config_present": bool(lock_config),
        "lock_config_id": lock_config.get("lock_config_id"),
        "lock_config_hash": lock_config.get("lock_config_hash"),
        "latest_common_history_end": latest_common_end,
        "decision_time_count": len(unique_times),
        "latest_decision_time": unique_times[-1] if unique_times else None,
        "decision_time_relation_counts": dict(sorted(relation_counts.items())),
        "row_checks": row_checks,
        "observe_only_purpose": OBSERVE_ONLY_PURPOSE,
        "observe_only_violation_count": len(observe_violations),
        "selection_forbidden_purposes_checked": FORBIDDEN_SELECTION_PURPOSES,
        "selection_forbidden_violation_count": len(selection_violations),
        "selection_use_blocked_by_lock": bool(selection_violations),
        "selection_violation_examples": selection_violations[:10],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
    }


def observation_row_lock_stamp(status: Mapping[str, Any], decision_time: str | pd.Timestamp) -> dict[str, Any]:
    normalized = _ts(decision_time)
    row_check = next((row for row in status.get("row_checks", []) if row.get("decision_time") == normalized), {})
    return {
        "schema_version": "btc_observe_only_holdout_lock_row_stamp_v1",
        "holdout_lock_path": status.get("holdout_lock_path"),
        "lock_config_hash": status.get("lock_config_hash"),
        "decision_time_relation": row_check.get("relation_to_lock"),
        "observe_only_allowed": bool(row_check.get("observe_only_allowed")),
        "observe_only_violation_count": int(row_check.get("observe_only_violation_count", 0) or 0),
        "selection_use_forbidden": bool(row_check.get("selection_use_forbidden")),
        "selection_violation_count": int(row_check.get("selection_violation_count", 0) or 0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def holdout_lock_blockers(status: Mapping[str, Any]) -> list[str]:
    return list(status.get("blockers", []))


def _future_observe_only_window(lock_config: Mapping[str, Any]) -> Mapping[str, Any]:
    for lock in lock_config.get("locked_windows", []):
        if lock.get("lock_type") == "future_confirmatory_holdout_observe_only":
            return lock.get("window", {})
    return {}


def _relation_to_lock(
    ts: pd.Timestamp,
    *,
    latest_common_ts: pd.Timestamp | None,
    planned_30d_end: pd.Timestamp | None,
    planned_60d_end: pd.Timestamp | None,
) -> str:
    if latest_common_ts is None:
        return "lock_anchor_missing"
    if ts <= latest_common_ts:
        return "locked_history_or_anchor"
    if planned_30d_end is not None and ts <= planned_30d_end:
        return "future_observe_only_0_30d"
    if planned_60d_end is not None and ts <= planned_60d_end:
        return "future_observe_only_31_60d"
    return "beyond_planned_60d_observe_window"


def _timestamp_or_none(value: Any) -> pd.Timestamp | None:
    if value in {None, ""}:
        return None
    return _timestamp(value)


def _timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _ts(value: Any) -> str:
    return _timestamp(value).isoformat()
