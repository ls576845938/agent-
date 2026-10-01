#!/usr/bin/env python3
"""Controlled, dependency-injected IBKR paper composition entrypoint."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.execution.ibkr_broker import (
    IBKRBroker,
    IBKRBrokerConfig,
    classify_ibkr_endpoint,
)
from quant_us.execution.ibkr_insync_facade import build_disconnected_ib_insync_facade
from quant_us.live.us_etf_26_ibkr_no_submit_shadow import (
    build_no_submit_shadow,
    committed_frozen_strategy_identity,
)
from quant_us.live.ibkr_runtime_market_data import (
    IBKRMarketDataTransportConfig,
    IBKRRuntimeMarketDataAdapter,
    IBKRRuntimeMarketDataConfig,
    IBKRSDKNeutralMarketDataTransport,
)
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig


@dataclass(frozen=True)
class ExactCandidateNoSubmitShadowComposition:
    broker_factory: Any
    repo_root: Path
    shared_data_root: Path
    expected_account_hash: str
    strategy_identity: dict[str, Any]

    def run(self, *, observed_at_utc: datetime | None = None) -> dict[str, Any]:
        return build_no_submit_shadow(
            broker_factory=self.broker_factory,
            repo_root=self.repo_root,
            shared_data_root=self.shared_data_root,
            expected_account_hash=self.expected_account_hash,
            observed_at_utc=observed_at_utc,
        )


def compose_ibkr_paper_runtime(
    *,
    paper_client_factory: Any,
    market_data_client_factory: Any,
    market_data_contract_factory: Any,
    account_hash_allowlist: tuple[str, ...],
    ledger_root: Path,
    data_root: Path,
    mode: str = "disabled",
    port: int = 4002,
    client_id: int = 1,
    connect_on_bootstrap: bool = False,
    start_market_data_on_bootstrap: bool = False,
    offline_replay: bool = False,
    corporate_action_entitlement_verified: bool = False,
    integration_receipt_path: Path | None = None,
    operator_paper_submit_authorized: bool = False,
    warmup_min_bars: int = 252,
) -> PaperRuntime:
    """Compose the canonical QQQ 1D IBKR runtime from injected factories.

    The function performs no connection.  It imports no IBKR SDK and accepts
    no Yahoo runtime or fallback factory.  A future operator must separately
    select connection, paper-submit mode, an integrated current-HEAD receipt
    and the runtime authorization gate.
    """

    endpoint_kind = classify_ibkr_endpoint(port)
    if endpoint_kind == "live":
        raise ValueError(f"ibkr_live_endpoint_forbidden:{port}")
    if endpoint_kind != "paper":
        raise ValueError(f"ibkr_paper_port_not_allowed:{port}")
    if (
        not callable(paper_client_factory)
        or not callable(market_data_client_factory)
        or not callable(market_data_contract_factory)
    ):
        raise TypeError("ibkr_injected_client_factories_required")
    normalized_mode = str(mode).lower().replace("_", "-")
    if normalized_mode not in {"disabled", "readonly", "paper-submit"}:
        raise ValueError(f"ibkr_paper_adapter_mode_not_supported:{mode}")
    submit_selected = normalized_mode == "paper-submit"
    config = PaperRuntimeConfig(
        symbols=["QQQ"],
        strategy_id="us-etf26-complete-return-qqq-1d-v1",
        data_vendor="ibkr",
        paper_broker="ibkr_paper",
        bar_size="1d",
        bar_sizes=["1d"],
        ledger_root=str(ledger_root),
        data_root=str(data_root),
        submit_orders=submit_selected,
        explicit_paper_submit=submit_selected,
        allow_live_orders=False,
        ibkr_port=port,
        ibkr_client_id=client_id,
        ibkr_adapter_mode=normalized_mode,
        ibkr_account_hash_allowlist=tuple(account_hash_allowlist),
        ibkr_connect_on_bootstrap=connect_on_bootstrap,
        ibkr_market_data_start_on_bootstrap=start_market_data_on_bootstrap,
        ibkr_require_adjusted_warmup=True,
        ibkr_offline_replay=offline_replay,
        ibkr_integration_receipt_path=str(integration_receipt_path or ""),
        ibkr_operator_paper_submit_authorized=operator_paper_submit_authorized,
    )

    def market_data_factory() -> IBKRRuntimeMarketDataAdapter:
        transport = IBKRSDKNeutralMarketDataTransport(
            IBKRMarketDataTransportConfig(
                symbols=("QQQ",),
                bar_size="1d",
                warmup_min_bars=warmup_min_bars,
            ),
            client=market_data_client_factory(),
            contract_factory=market_data_contract_factory,
        )
        return IBKRRuntimeMarketDataAdapter(
            IBKRRuntimeMarketDataConfig(
                symbols=("QQQ",),
                bar_size="1d",
                corporate_action_entitlement_verified=(
                    corporate_action_entitlement_verified
                ),
                require_warmup=True,
            ),
            client=transport,
        )

    return PaperRuntime(
        config,
        ibkr_paper_client_factory=paper_client_factory,
        ibkr_market_data_adapter_factory=market_data_factory,
    )


def compose_ibkr_paper_runtime_from_ib_insync(
    *,
    account_hash_allowlist: tuple[str, ...],
    ledger_root: Path,
    data_root: Path,
    mode: str = "disabled",
    port: int = 4002,
    client_id: int = 1,
    connect_on_bootstrap: bool = False,
    start_market_data_on_bootstrap: bool = False,
    integration_receipt_path: Path | None = None,
    operator_paper_submit_authorized: bool = False,
    warmup_min_bars: int = 252,
) -> PaperRuntime:
    """Build the real ib_insync composition without importing or connecting yet."""

    holder: dict[str, Any] = {}

    def shared_client() -> Any:
        if "client" not in holder:
            holder["client"] = build_disconnected_ib_insync_facade()
        return holder["client"]

    def contract_factory(symbol: str) -> Any:
        return shared_client().make_contract(symbol)

    return compose_ibkr_paper_runtime(
        paper_client_factory=shared_client,
        market_data_client_factory=shared_client,
        market_data_contract_factory=contract_factory,
        account_hash_allowlist=account_hash_allowlist,
        ledger_root=ledger_root,
        data_root=data_root,
        mode=mode,
        port=port,
        client_id=client_id,
        connect_on_bootstrap=connect_on_bootstrap,
        start_market_data_on_bootstrap=start_market_data_on_bootstrap,
        integration_receipt_path=integration_receipt_path,
        operator_paper_submit_authorized=operator_paper_submit_authorized,
        warmup_min_bars=warmup_min_bars,
    )


def compose_exact_candidate_no_submit_shadow(
    *,
    client: Any,
    expected_account_hash: str,
    repo_root: Path,
    shared_data_root: Path,
    strategy_identity: Mapping[str, Any],
    port: int = 4002,
    client_id: int = 1,
) -> ExactCandidateNoSubmitShadowComposition:
    """Compose an injected fake-client run without connecting or writing."""

    expected_identity = committed_frozen_strategy_identity(repo_root=repo_root.resolve())
    if dict(strategy_identity) != expected_identity:
        raise ValueError("exact_candidate_strategy_identity_mismatch")
    endpoint_kind = classify_ibkr_endpoint(port)
    if endpoint_kind == "live":
        raise ValueError(f"ibkr_live_endpoint_forbidden:{port}")
    if endpoint_kind != "paper":
        raise ValueError(f"ibkr_paper_port_not_allowed:{port}")
    config = IBKRBrokerConfig(port=port, client_id=client_id)

    def broker_factory() -> IBKRBroker:
        return IBKRBroker(config, client=client)

    return ExactCandidateNoSubmitShadowComposition(
        broker_factory=broker_factory,
        repo_root=repo_root.resolve(),
        shared_data_root=shared_data_root.resolve(),
        expected_account_hash=expected_account_hash,
        strategy_identity=expected_identity,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IBKR paper-only orchestration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    no_submit = subparsers.add_parser("no-submit")
    no_submit.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    no_submit.add_argument("--port", choices=[4002, 7497], type=int, default=4002)
    no_submit.add_argument("--expected-account-hash", required=True)
    no_submit.add_argument("--shared-data-root", type=Path, required=True)
    describe = subparsers.add_parser("describe-runtime")
    describe.add_argument("--port", choices=[4002, 7497], type=int, default=4002)
    describe.add_argument(
        "--mode",
        choices=["disabled", "readonly", "paper-submit"],
        default="disabled",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "no-submit":
        raise SystemExit(
            "injected_fake_client_required_no_gateway_factory_available: "
            "CLI construction/import never connects and exposes no submit, cancel, or globalCancel surface"
        )
    if args.command == "describe-runtime":
        print(
            json.dumps(
                {
                    "runtime": "PaperRuntime",
                    "market_data": "IBKRRuntimeMarketDataAdapter",
                    "symbol": "QQQ",
                    "bar_size": "1d",
                    "mode": args.mode,
                    "port": args.port,
                    "client_factory_injected": False,
                    "gateway_connected": False,
                    "paper_submit_allowed": False,
                    "paper_cancel_allowed": False,
                    "live_allowed": False,
                    "promotion_allowed": False,
                    "secrets_read": False,
                },
                sort_keys=True,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
