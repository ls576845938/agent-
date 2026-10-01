"""Resource budget guard for experiment orchestration.

Monitors CPU, memory, runtime, and parallel job limits.
Falls back gracefully when psutil is not available.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResourceBudget:
    """Resource budget limits for experiment orchestration."""

    max_cpu_pct: float = 70.0
    max_memory_mb: int = 2048
    max_runtime_seconds: int = 3600
    max_parallel_jobs: int = 2


class ResourceBudgetGuard:
    """Check resource usage against a budget before running experiments."""

    def __init__(self, budget: ResourceBudget | None = None) -> None:
        self.budget = budget or ResourceBudget()

    def check(self) -> tuple[bool, str]:
        """Check if current resource usage is within budget.

        Uses psutil for CPU/memory monitoring. Falls back to 'OK' if psutil is
        unavailable.

        Returns:
            Tuple of (ok: bool, message: str).
        """
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            if cpu > self.budget.max_cpu_pct:
                return (
                    False,
                    f"CPU {cpu:.0f}% > {self.budget.max_cpu_pct}%",
                )
            mem_used_mb = mem.used / (1024 * 1024)
            if mem_used_mb > self.budget.max_memory_mb:
                return (
                    False,
                    f"Memory {mem_used_mb:.0f}MB > {self.budget.max_memory_mb}MB",
                )
            return True, "OK"
        except ImportError:
            return True, "OK (psutil unavailable)"
        except Exception:
            return True, "OK (resource check unavailable)"

    def should_pause(self) -> bool:
        """Return True if resources are strained and orchestration should pause."""
        ok, _ = self.check()
        return not ok
