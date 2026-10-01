from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.monitoring.okx_demo_remote_supervisor import (
    OkxDemoRemoteSupervisor,
    OkxDemoRemoteSupervisorConfig,
)
from quant_crypto.oms.okx_demo import (
    OkxDemoClientConfig,
    OkxDemoReadOnlyClient,
    load_windows_keyring_credentials,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independent read-only BTC OKX Demo remote supervisor",
    )
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--expected-worker-id", required=True)
    parser.add_argument("--heartbeat-url", required=True)
    parser.add_argument("--heartbeat-allow-host", action="append", required=True)
    parser.add_argument("--receipt-external-root", type=Path, required=True)
    parser.add_argument("--supervisor-host-id", default=socket.gethostname())
    parser.add_argument("--credential-service", default="quant-system.okx-demo.readonly-supervisor")
    parser.add_argument("--worker-heartbeat-stale-seconds", type=float, default=90.0)
    parser.add_argument("--reconcile-stale-seconds", type=float, default=120.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = OkxDemoRemoteSupervisorConfig(
        deployment_id=args.deployment_id,
        expected_worker_id=args.expected_worker_id,
        heartbeat_url=args.heartbeat_url,
        heartbeat_allowlist=tuple(args.heartbeat_allow_host),
        receipt_external_root=args.receipt_external_root,
        supervisor_host_id=args.supervisor_host_id,
        worker_heartbeat_stale_seconds=args.worker_heartbeat_stale_seconds,
        reconcile_stale_seconds=args.reconcile_stale_seconds,
    )
    # Credentials are loaded only after all URL/deployment safety validation.
    credentials = load_windows_keyring_credentials(args.credential_service)
    reader = OkxDemoReadOnlyClient(
        config=OkxDemoClientConfig(
            credential_service=args.credential_service,
            allow_private_read=True,
            allow_demo_orders=False,
            allow_demo_cancels=False,
        ),
        credentials=credentials,
    )
    supervisor = OkxDemoRemoteSupervisor(config, exchange_reader=reader)
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    while True:
        receipt = supervisor.run_once()
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        if args.once:
            return 0 if receipt["status"] == "healthy" else 2
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
