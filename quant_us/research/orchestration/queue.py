"""Experiment queue for batch orchestration.

Manages batch plans: create, run, pause, resume, cancel, and status queries.
Each batch tracks individual experiment completion and integrates with the
resource budget guard.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class BatchPlan:
    """Plan for a batch of experiments."""

    batch_id: str
    experiment_ids: list[str]
    status: str = "CREATED"  # CREATED|RUNNING|PAUSED|COMPLETED|CANCELLED
    max_parallel: int = 1
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    created_at: str = ""


class ExperimentQueue:
    """Queue for managing and running experiment batches.

    Each batch has a plan that tracks which experiments completed, failed,
    or are pending. Failed experiments do not stop the batch.
    """

    def __init__(self, data_root: str = "data") -> None:
        self._data_root = Path(data_root)
        self._batches_dir = self._data_root / "research" / "batches"
        self._batches_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _batch_path(self, batch_id: str) -> Path:
        return self._batches_dir / f"{batch_id}.json"

    def _save(self, plan: BatchPlan) -> None:
        path = self._batch_path(plan.batch_id)
        path.write_text(
            json.dumps(
                {
                    "batch_id": plan.batch_id,
                    "experiment_ids": plan.experiment_ids,
                    "status": plan.status,
                    "max_parallel": plan.max_parallel,
                    "completed": plan.completed,
                    "failed": plan.failed,
                    "created_at": plan.created_at,
                },
                indent=2,
            )
        )

    def _load(self, batch_id: str) -> BatchPlan | None:
        path = self._batch_path(batch_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return BatchPlan(**data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_batch(
        self,
        experiment_ids: list[str],
        max_parallel: int = 1,
    ) -> BatchPlan:
        """Create a new batch plan.

        Args:
            experiment_ids: List of experiment IDs to run.
            max_parallel: Maximum parallel experiments (default 1).

        Returns:
            The created BatchPlan.
        """
        from quant_us.core.types import new_id

        batch_id = new_id("batch")
        plan = BatchPlan(
            batch_id=batch_id,
            experiment_ids=experiment_ids,
            status="CREATED",
            max_parallel=max_parallel,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save(plan)
        return plan

    def run_batch(
        self,
        batch_id: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run a batch of experiments.

        For each experiment, checks the resource guard before running.
        Failed experiments do not stop the batch. Skips already-completed
        or already-failed experiments.

        Args:
            batch_id: Batch plan ID.
            dry_run: If True, simulate running without executing experiments.

        Returns:
            Dict with batch_id, status, completed, failed counts.
        """
        plan = self._load(batch_id)
        if plan is None:
            return {"error": f"Batch not found: {batch_id}"}

        if plan.status == "CANCELLED":
            return {
                "batch_id": batch_id,
                "status": "CANCELLED",
                "message": "Batch was cancelled. Not running.",
            }

        plan.status = "RUNNING"
        self._save(plan)

        from quant_us.research.orchestration.resource_guard import (
            ResourceBudgetGuard,
        )

        guard = ResourceBudgetGuard()

        pending = [
            eid
            for eid in plan.experiment_ids
            if eid not in plan.completed and eid not in plan.failed
        ]

        if not pending:
            plan.status = "COMPLETED"
            self._save(plan)
            return {
                "batch_id": batch_id,
                "status": "COMPLETED",
                "completed": len(plan.completed),
                "failed": len(plan.failed),
                "message": "All experiments already processed.",
            }

        for exp_id in pending:
            # Check resource guard before each experiment
            if guard.should_pause():
                plan.status = "PAUSED"
                self._save(plan)
                return {
                    "batch_id": batch_id,
                    "status": "PAUSED",
                    "reason": "Resource budget exceeded",
                    "completed": len(plan.completed),
                    "failed": len(plan.failed),
                }

            # Reload plan each iteration to pick up external pause/cancel
            plan = self._load(batch_id)
            if plan is None or plan.status == "CANCELLED":
                return {
                    "batch_id": batch_id,
                    "status": "CANCELLED",
                    "completed": len(plan.completed) if plan else 0,
                    "failed": len(plan.failed) if plan else 0,
                }
            if plan.status == "PAUSED":
                return {
                    "batch_id": batch_id,
                    "status": "PAUSED",
                    "reason": "Externally paused",
                    "completed": len(plan.completed),
                    "failed": len(plan.failed),
                }

            if dry_run:
                print(f"  [DRY-RUN] Would run experiment {exp_id}")
                plan.completed.append(exp_id)
                self._save(plan)
                continue

            # Run experiment
            try:
                success = self._run_single_experiment(exp_id)
                if success:
                    plan.completed.append(exp_id)
                else:
                    plan.failed.append(exp_id)
            except Exception as exc:
                plan.failed.append(exp_id)
                print(f"  ERROR experiment {exp_id}: {exc}")

            self._save(plan)

        # Mark completed
        plan = self._load(batch_id)
        if plan and plan.status == "RUNNING":
            plan.status = "COMPLETED"
            self._save(plan)

        return {
            "batch_id": batch_id,
            "status": "COMPLETED",
            "completed": len(plan.completed) if plan else 0,
            "failed": len(plan.failed) if plan else 0,
        }

    def _run_single_experiment(self, experiment_id: str) -> bool:
        """Run a single experiment via the ExperimentManager.

        Args:
            experiment_id: Experiment ID to run.

        Returns:
            True if the experiment completed successfully.
        """
        from quant_us.research.lab.manifest import ExperimentManager

        mgr = ExperimentManager()
        manifest = mgr.inspect(experiment_id)
        if manifest is None:
            print(f"  Experiment {experiment_id} not found in manifest")
            return False

        # Run backtest for this experiment
        from quant_us.research.experiments import BatchBacktestRunner

        runner = BatchBacktestRunner()
        result = runner.run_experiment(manifest)
        return result is not None and getattr(result, "status", "") != "FAILED"

    def pause_batch(self, batch_id: str) -> None:
        """Pause a running batch.

        Args:
            batch_id: Batch plan ID.
        """
        plan = self._load(batch_id)
        if plan is None:
            return
        if plan.status == "RUNNING":
            plan.status = "PAUSED"
            self._save(plan)

    def resume_batch(self, batch_id: str) -> None:
        """Resume a paused batch.

        Args:
            batch_id: Batch plan ID.
        """
        plan = self._load(batch_id)
        if plan is None:
            return
        if plan.status == "PAUSED":
            plan.status = "RUNNING"
            self._save(plan)

    def cancel_batch(self, batch_id: str) -> None:
        """Cancel a batch (any status).

        Args:
            batch_id: Batch plan ID.
        """
        plan = self._load(batch_id)
        if plan is None:
            return
        plan.status = "CANCELLED"
        self._save(plan)

    def get_status(self, batch_id: str) -> dict[str, Any]:
        """Get the current status of a batch.

        Args:
            batch_id: Batch plan ID.

        Returns:
            Dict with batch details, or error if not found.
        """
        plan = self._load(batch_id)
        if plan is None:
            return {"error": f"Batch not found: {batch_id}"}
        return {
            "batch_id": plan.batch_id,
            "status": plan.status,
            "experiment_ids": plan.experiment_ids,
            "max_parallel": plan.max_parallel,
            "completed": plan.completed,
            "failed": plan.failed,
            "created_at": plan.created_at,
            "progress": f"{len(plan.completed) + len(plan.failed)}/{len(plan.experiment_ids)}",
        }

    def list_batches(self) -> list[dict[str, Any]]:
        """List all batch plans.

        Returns:
            List of batch status dicts.
        """
        batches: list[dict[str, Any]] = []
        for path in sorted(self._batches_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                batches.append(
                    {
                        "batch_id": data.get("batch_id", ""),
                        "status": data.get("status", ""),
                        "experiment_count": len(data.get("experiment_ids", [])),
                        "completed": len(data.get("completed", [])),
                        "failed": len(data.get("failed", [])),
                        "created_at": data.get("created_at", ""),
                    }
                )
            except Exception:
                continue
        return batches
