from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.btc_demo_private_readonly_observation import (
    BTCPrivateReadonlyObservationConfig,
    BTCPrivateReadonlyObservationError,
    BTCPrivateReadonlyObservationRunner,
    OkxDemoPrivateReadObservationProvider,
    OkxDemoPrivateReadonlyWSAdapter,
)
from quant_crypto.oms.okx_demo import (
    OkxDemoClientConfig,
    OkxDemoReadOnlyClient,
    load_windows_keyring_credentials,
)
from quant_crypto.oms.okx_demo_private_ws import OkxDemoPrivateWS
from tools.agent_governance.private_readonly_permission import (
    CONFIRMATION,
    DEFAULT_CREDENTIAL_SERVICE,
    RunnerProcessAuthorization,
    authorize_runner_process,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated OKX Demo private-readonly observer. Security "
            "identity and runtime parameters are derived internally from the "
            "signed one-time receipt."
        )
    )
    return parser.parse_args(argv)


def _emit_authorization_failure(authorization: RunnerProcessAuthorization) -> int:
    print(
        json.dumps(
            {"error_code": authorization.reason},
            ensure_ascii=True,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def main(
    *,
    argv: Sequence[str] | None = None,
    capability_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    run_once: bool = False,
) -> int:
    _parse_args(argv)
    authorization = authorize_runner_process(
        root=capability_root,
        repo_root=REPO_ROOT,
        cwd=Path.cwd(),
        environ=os.environ if environ is None else environ,
    )
    if not authorization.allowed:
        return _emit_authorization_failure(authorization)
    if (
        authorization.runtime_root is None
        or authorization.confirmation != CONFIRMATION
        or not authorization.authorization_ticket_hash
    ):
        return _emit_authorization_failure(
            RunnerProcessAuthorization(
                False, "private_readonly_internal_authorization_invalid"
            )
        )
    poll_seconds = 30.0

    stopping = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    runner: BTCPrivateReadonlyObservationRunner | None = None
    failure: BTCPrivateReadonlyObservationError | None = None
    try:
        client_config = OkxDemoClientConfig(
            credential_service=DEFAULT_CREDENTIAL_SERVICE,
            allow_private_read=True,
            allow_demo_orders=False,
            allow_demo_cancels=False,
        )
        credentials = load_windows_keyring_credentials(DEFAULT_CREDENTIAL_SERVICE)
        client = OkxDemoReadOnlyClient(
            config=client_config,
            credentials=credentials,
        )
        provider = OkxDemoPrivateReadObservationProvider(client)

        def transport_factory(on_disconnect, on_reconciled):
            return OkxDemoPrivateWS(
                credentials=credentials,
                source_head=authorization.source_head,
                runtime_version=(
                    "btc_demo_private_readonly_observation_runner_v1"
                ),
                snapshot_loader=provider.read_snapshot,
                owned_client_order_ids=provider.observed_client_order_ids,
                on_disconnect=on_disconnect,
                on_reconciled=on_reconciled,
            )

        runner = BTCPrivateReadonlyObservationRunner(
            config=BTCPrivateReadonlyObservationConfig(
                runtime_root=authorization.runtime_root,
                source_head=authorization.source_head,
                run_id=authorization.run_id,
                private_read_authorized=True,
                private_authorization_ticket_hash=(
                    authorization.authorization_ticket_hash
                ),
            ),
            snapshot_provider=provider,
            private_ws=OkxDemoPrivateReadonlyWSAdapter(transport_factory),
        )
        status = runner.start()
        print(json.dumps(status, ensure_ascii=True, sort_keys=True))
        if run_once:
            runner.poll()
        while not run_once and not stopping:
            time.sleep(poll_seconds)
            status = runner.poll()
            print(json.dumps(status, ensure_ascii=True, sort_keys=True))
    except BTCPrivateReadonlyObservationError as exc:
        failure = exc
    except Exception:
        failure = BTCPrivateReadonlyObservationError(
            "private_readonly_runner_failed"
        )
    finally:
        if runner is not None:
            try:
                runner.stop()
            except Exception:
                if failure is None:
                    failure = BTCPrivateReadonlyObservationError(
                        "private_readonly_stop_failed"
                    )
    if failure is not None:
        payload: dict[str, object] = {"error_code": failure.error_code}
        if failure.safe_error is not None:
            payload["safe_error"] = failure.safe_error.to_dict()
        print(
            json.dumps(payload, ensure_ascii=True, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
