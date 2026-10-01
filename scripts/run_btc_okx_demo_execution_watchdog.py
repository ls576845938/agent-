from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.okx_demo_execution_watchdog import (
    OkxDemoExecutionWatchdogConfig,
    inspect_okx_demo_execution_runtime,
)


DEFAULT_RUNTIME_ROOT = (
    Path(tempfile.gettempdir()) / "quant-system" / "btc_demo_paper_runtime"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the independent read-only OKX Demo execution watchdog."
    )
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--alert-path", type=Path)
    parser.add_argument("--heartbeat-stale-seconds", type=float, default=90.0)
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--no-write-alert", action="store_true")
    args = parser.parse_args()
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    alert_path = args.alert_path or args.runtime_root / "watchdog-alerts.jsonl"
    config = OkxDemoExecutionWatchdogConfig(
        runtime_root=args.runtime_root,
        alert_path=alert_path,
        worker_heartbeat_stale_seconds=args.heartbeat_stale_seconds,
    )
    exit_code = 0
    while True:
        report = inspect_okx_demo_execution_runtime(
            config,
            write_alert=not args.no_write_alert,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        exit_code = 2 if report["status"] == "critical" else 0
        if not args.continuous:
            return exit_code
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
