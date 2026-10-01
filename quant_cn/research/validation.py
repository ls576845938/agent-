"""PIT, walk-forward, purge/embargo, holdout, and trial governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from typing import Any

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime
    purge: timedelta
    embargo: timedelta

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold_id", require_non_empty(self.fold_id, "fold_id"))
        for name in (
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "test_start",
            "test_end",
        ):
            object.__setattr__(
                self, name, ensure_aware_timestamp(getattr(self, name), name)
            )
        if not (
            self.train_start < self.train_end
            <= self.validation_start
            < self.validation_end
            <= self.test_start
            < self.test_end
        ):
            raise ValueError("walk_forward_window_order_invalid")
        if self.purge < timedelta(0) or self.embargo < timedelta(0):
            raise ValueError("purge_embargo_must_be_non_negative")

    def validate_separation(self, *, label_horizon: timedelta) -> tuple[str, ...]:
        blockers: list[str] = []
        if label_horizon <= timedelta(0):
            blockers.append("label_horizon_invalid")
        if self.validation_start - self.train_end < max(self.purge, label_horizon):
            blockers.append("train_validation_purge_insufficient")
        if self.test_start - self.validation_end < self.embargo:
            blockers.append("validation_test_embargo_insufficient")
        return tuple(blockers)


@dataclass(frozen=True)
class Trial:
    trial_id: str
    params_hash: str
    registered_at: datetime
    status: str
    selected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", require_non_empty(self.trial_id, "trial_id"))
        object.__setattr__(
            self, "params_hash", require_non_empty(self.params_hash, "params_hash")
        )
        object.__setattr__(
            self, "registered_at", ensure_aware_timestamp(self.registered_at, "registered_at")
        )
        if self.status not in {"accepted", "failed", "rejected"}:
            raise ValueError("trial_status_unknown")


class TrialRegistry:
    """Append-only in memory registry; freezes parameter search at holdout view."""

    def __init__(self, *, candidate_count: int) -> None:
        if not isinstance(candidate_count, int) or candidate_count <= 0:
            raise ValueError("candidate_count_must_be_positive")
        self.candidate_count = candidate_count
        self._trials: list[Trial] = []
        self._holdout_viewed_at: datetime | None = None

    def register(self, trial: Trial) -> None:
        if self._holdout_viewed_at is not None:
            raise ValueError("holdout_already_viewed_parameter_search_frozen")
        if any(item.trial_id == trial.trial_id for item in self._trials):
            raise ValueError("trial_id_duplicate")
        if len(self._trials) >= self.candidate_count:
            raise ValueError("trial_count_exceeds_candidate_count")
        self._trials.append(trial)

    def mark_holdout_viewed(self, viewed_at: datetime) -> None:
        viewed = ensure_aware_timestamp(viewed_at, "holdout_viewed_at")
        if not any(item.selected for item in self._trials):
            raise ValueError("selected_trial_required_before_holdout")
        if self._holdout_viewed_at is not None:
            raise ValueError("holdout_view_already_recorded")
        self._holdout_viewed_at = viewed

    @property
    def trials(self) -> tuple[Trial, ...]:
        return tuple(self._trials)

    @property
    def trial_count(self) -> int:
        return len(self._trials)

    @property
    def holdout_viewed_at(self) -> datetime | None:
        return self._holdout_viewed_at

    @property
    def selected_trial(self) -> Trial | None:
        selected = tuple(item for item in self._trials if item.selected)
        if len(selected) > 1:
            raise ValueError("multiple_selected_trials")
        return selected[0] if selected else None


@dataclass(frozen=True)
class FoldResult:
    fold_id: str
    params_hash: str
    total_return: float
    max_drawdown: float
    turnover: float
    exposure_ratio: float
    positive: bool
    acceptable: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold_id", require_non_empty(self.fold_id, "fold_id"))
        object.__setattr__(
            self, "params_hash", require_non_empty(self.params_hash, "params_hash")
        )
        for name in ("total_return", "max_drawdown", "turnover", "exposure_ratio"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"finite_number_required:{name}")
        if self.max_drawdown < 0 or self.turnover < 0:
            raise ValueError("fold_drawdown_turnover_must_be_non_negative")
        if self.exposure_ratio < 0 or self.exposure_ratio > 1:
            raise ValueError("fold_exposure_out_of_range")


@dataclass(frozen=True)
class ValidationPlan:
    folds: tuple[WalkForwardFold, ...]
    label_horizon: timedelta
    holdout_start: datetime
    holdout_end: datetime
    selected_before_holdout: bool
    parameter_stability_passed: bool

    def __post_init__(self) -> None:
        folds = tuple(self.folds)
        if not folds:
            raise ValueError("walk_forward_folds_required")
        if len({item.fold_id for item in folds}) != len(folds):
            raise ValueError("walk_forward_fold_id_duplicate")
        object.__setattr__(self, "folds", tuple(sorted(folds, key=lambda item: item.test_start)))
        object.__setattr__(
            self, "holdout_start", ensure_aware_timestamp(self.holdout_start, "holdout_start")
        )
        object.__setattr__(
            self, "holdout_end", ensure_aware_timestamp(self.holdout_end, "holdout_end")
        )
        if self.holdout_start >= self.holdout_end:
            raise ValueError("holdout_window_invalid")

    def blockers(self, registry: TrialRegistry) -> tuple[str, ...]:
        blockers: list[str] = []
        for fold in self.folds:
            blockers.extend(f"{fold.fold_id}:{item}" for item in fold.validate_separation(label_horizon=self.label_horizon))
        if not self.selected_before_holdout:
            blockers.append("parameters_not_frozen_before_holdout")
        if not self.parameter_stability_passed:
            blockers.append("parameter_stability_not_passed")
        if registry.selected_trial is None:
            blockers.append("selected_trial_missing")
        elif registry.selected_trial.registered_at >= self.holdout_start:
            blockers.append("selected_trial_not_frozen_before_holdout")
        if registry.trial_count == 0:
            blockers.append("trial_registry_empty")
        if any(item.test_end > self.holdout_start for item in self.folds):
            blockers.append("walk_forward_overlaps_holdout")
        if (
            registry.holdout_viewed_at is not None
            and registry.holdout_viewed_at < self.holdout_end
        ):
            blockers.append("holdout_viewed_before_window_end")
        return tuple(sorted(set(blockers)))

    def result_blockers(
        self,
        results: tuple[FoldResult, ...],
        registry: TrialRegistry,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        expected = {item.fold_id for item in self.folds}
        actual = {item.fold_id for item in results}
        if expected != actual or len(actual) != len(results):
            blockers.append("walk_forward_fold_results_incomplete")
        if not any(item.positive for item in results):
            blockers.append("walk_forward_no_positive_fold")
        if not any(item.acceptable for item in results):
            blockers.append("walk_forward_no_acceptable_fold")
        if any(not item.acceptable for item in results):
            blockers.append("walk_forward_fold_failed")
        selected = registry.selected_trial
        if selected is not None and any(
            item.params_hash != selected.params_hash for item in results
        ):
            blockers.append("walk_forward_params_not_selected_pre_holdout")
        return tuple(sorted(set(blockers)))

    @property
    def fingerprint(self) -> str:
        payload: dict[str, Any] = {
            "folds": [
                {
                    "embargo_seconds": item.embargo.total_seconds(),
                    "fold_id": item.fold_id,
                    "purge_seconds": item.purge.total_seconds(),
                    "test_end": item.test_end.isoformat(),
                    "test_start": item.test_start.isoformat(),
                    "train_end": item.train_end.isoformat(),
                    "train_start": item.train_start.isoformat(),
                    "validation_end": item.validation_end.isoformat(),
                    "validation_start": item.validation_start.isoformat(),
                }
                for item in self.folds
            ],
            "holdout_end": self.holdout_end.isoformat(),
            "holdout_start": self.holdout_start.isoformat(),
            "label_horizon_seconds": self.label_horizon.total_seconds(),
            "parameter_stability_passed": self.parameter_stability_passed,
            "selected_before_holdout": self.selected_before_holdout,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
