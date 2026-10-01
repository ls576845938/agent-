from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


GIB = 1024**3
MIN_FREE_GB = {
    "full-worktree": 50.0,
    "sparse-worktree": 2.0,
    "data-collection": 20.0,
    "artifact-rebuild": 20.0,
}


class DiskGuardError(RuntimeError):
    pass


def evaluate_disk_guard(
    *,
    operation: str,
    path: Path,
    free_bytes: int | None = None,
) -> dict[str, Any]:
    if operation not in MIN_FREE_GB:
        raise DiskGuardError(f"disk_guard_operation_invalid:{operation}")

    probe = _existing_parent(path)
    observed_free = shutil.disk_usage(probe).free if free_bytes is None else free_bytes
    required_gb = MIN_FREE_GB[operation]
    free_gb = observed_free / GIB
    allowed = free_gb >= required_gb
    return {
        "schema_version": "agent_disk_guard_v1",
        "operation": operation,
        "probe_path": str(probe),
        "free_bytes": observed_free,
        "free_gb": round(free_gb, 2),
        "minimum_free_gb": required_gb,
        "status": "allowed" if allowed else "blocked_low_disk",
        "allowed": allowed,
        "blocker": None if allowed else f"disk_free_below_{required_gb:g}gb",
    }


def require_disk_capacity(*, operation: str, path: Path) -> dict[str, Any]:
    result = evaluate_disk_guard(operation=operation, path=path)
    if not result["allowed"]:
        raise DiskGuardError(
            f"{result['blocker']}:free_gb={result['free_gb']}:operation={operation}"
        )
    return result


def _existing_parent(path: Path) -> Path:
    probe = path.expanduser().resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists():
        raise DiskGuardError(f"disk_guard_probe_missing:{path}")
    return probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed disk watermark guard.")
    parser.add_argument("--operation", choices=sorted(MIN_FREE_GB), required=True)
    parser.add_argument("--path", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        result = evaluate_disk_guard(operation=args.operation, path=args.path)
    except (DiskGuardError, OSError) as exc:
        result = {
            "schema_version": "agent_disk_guard_v1",
            "operation": args.operation,
            "status": "blocked_disk_probe_failed",
            "allowed": False,
            "blocker": f"disk_probe_failed:{type(exc).__name__}:{exc}",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["allowed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
