from __future__ import annotations

from typing import Any, Callable, Mapping

from quant_crypto.application.runtime_ports import (
    DemoRuntimeControllerPort,
    NativeDemoDataInspector,
    ReadonlyChartLoader,
)
from quant_crypto.application.btc_strategy_registry import (
    HIGH_OCTANE_STRATEGY_LINE,
    HIGH_YIELD_STRATEGY_LINE,
    OKX_NATIVE_STRATEGY_LINE,
    STABLE_STRATEGY_LINE,
    btc_strategy_registry,
)
from quant_crypto.application.btc_operator_contract_v2 import (
    OperatorAuthorizationRecord,
    authorize_operator_action,
    project_operator_contract_v2,
)


_OKX_NATIVE_STALE_SEED_BLOCKER = (
    "okx_demo_paper_okx_native_completed_1h_stale"
)


class BtcDemoRuntimeService:
    def __init__(
        self,
        *,
        controller: DemoRuntimeControllerPort,
        native_demo_data_inspector: NativeDemoDataInspector,
        readonly_chart_loader: ReadonlyChartLoader,
        readonly_market_view_loader: Callable[[str, int], dict[str, Any]] | None = None,
        instrument_id: str,
        authorization_ticket: str,
        confirmation_text: str,
    ) -> None:
        self.controller = controller
        self.native_demo_data_inspector = native_demo_data_inspector
        self.readonly_chart_loader = readonly_chart_loader
        self.readonly_market_view_loader = readonly_market_view_loader
        self.instrument_id = instrument_id
        self.authorization_ticket = authorization_ticket
        self.confirmation_text = confirmation_text

    def catalog(self) -> dict[str, Any]:
        native_demo_data = self.native_demo_data_inspector()
        native_admission = _native_demo_admission(native_demo_data)
        native_eligible = native_admission["demo_selectable"] is True
        rows: list[dict[str, Any]] = []
        for spec in btc_strategy_registry.list_specs():
            demo_selectable = spec.canonical_signal_available and (
                spec.strategy_id == STABLE_STRATEGY_LINE
                or (spec.strategy_id == OKX_NATIVE_STRATEGY_LINE and native_eligible)
            )
            if spec.strategy_id == OKX_NATIVE_STRATEGY_LINE and not native_eligible:
                demo_blocker = ";".join(str(item) for item in native_demo_data.get("blockers", []))
                demo_blocker = demo_blocker or "okx_native_demo_signal_data_not_eligible"
            elif demo_selectable:
                demo_blocker = ""
            else:
                demo_blocker = "identity_only_no_demo_execution_ledger"
            rows.append(
                {
                    **spec.identity(),
                    "display_name": _display_name(spec.strategy_id),
                    "demo_selectable": demo_selectable,
                    "demo_blocker": demo_blocker,
                    "historical_research_evidence": spec.strategy_id == STABLE_STRATEGY_LINE,
                    "native_evidence_freshness": (
                        {"status": "separate_promotion_gate", "blocks_demo_start": False}
                        if spec.strategy_id == OKX_NATIVE_STRATEGY_LINE
                        else {}
                    ),
                    "native_demo_data_readiness": native_demo_data if spec.strategy_id == OKX_NATIVE_STRATEGY_LINE else {},
                    "native_runtime_data_policy": (
                        native_admission["runtime_data_policy"]
                        if spec.strategy_id == OKX_NATIVE_STRATEGY_LINE
                        else {}
                    ),
                }
            )
        default_spec = next(
            (
                spec
                for spec in btc_strategy_registry.list_specs()
                if native_eligible and spec.strategy_id == OKX_NATIVE_STRATEGY_LINE
            ),
            btc_strategy_registry.get(STABLE_STRATEGY_LINE),
        )
        return {
            "schema_version": "btc_demo_strategy_catalog_v1",
            "environment": "OKX Demo",
            "instrument_id": self.instrument_id,
            "authorization_ticket": self.authorization_ticket,
            "confirmation_text": self.confirmation_text,
            "default_strategy_id": default_spec.strategy_id,
            "default_candidate_id": default_spec.candidate_id,
            "default_reason": (
                native_admission["default_reason"]
                if native_eligible
                else "binance_historical_fallback_fail_closed"
            ),
            "strategies": rows,
            "safety": {
                "live_order_allowed": False,
                "real_money_order_allowed": False,
                "transfer_allowed": False,
                "withdraw_allowed": False,
                "permission_upgrade_allowed": False,
                "auto_start_on_backend_launch": False,
            },
        }

    def status(self) -> dict[str, Any]:
        return self.controller.status()

    def operator_contract_v2(self) -> dict[str, Any]:
        """Expose the application-owned, read-only operator projection.

        This is deliberately the same projection consumed by the mutation
        adapter; the application layer never grants an exchange capability.
        """

        return project_operator_contract_v2(self.status())

    def authorize_operator_action(
        self,
        action: str,
        *,
        idempotency_key: str | None = None,
    ) -> OperatorAuthorizationRecord:
        return authorize_operator_action(
            self.status(),
            action,
            idempotency_key=idempotency_key,
        )

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.controller.start(payload)

    def start_operation(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        method = getattr(self.controller, "start_operation", None)
        if not callable(method):
            raise RuntimeError("btc_demo_start_operation_controller_capability_missing")
        return method(payload, idempotency_key=idempotency_key)

    def stop(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.controller.stop(payload)

    def reconcile(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.controller.reconcile(payload)

    def cancel_only(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.controller.enter_cancel_only(payload)

    def readonly_klines(self, *, limit: int = 1_000) -> dict[str, Any]:
        return self.readonly_chart_loader(limit)

    def readonly_market_view(self, *, timeframe: str, limit: int = 120) -> dict[str, Any]:
        """Public visual data only; never a strategy or execution input."""
        if self.readonly_market_view_loader is None:
            raise RuntimeError("btc_demo_readonly_market_view_loader_missing")
        return self.readonly_market_view_loader(timeframe, limit)


def _native_demo_admission(
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = tuple(
        str(item)
        for item in (readiness.get("blockers") or [])
        if str(item)
    )
    integrity_passed = readiness.get("integrity_passed") is True
    freshness_status = str(readiness.get("freshness_status") or "")
    fresh_admitted = (
        integrity_passed
        and readiness.get("eligible") is True
        and not blockers
        and freshness_status == "pass"
    )
    stale_seed_admitted = (
        integrity_passed
        and readiness.get("eligible") is False
        and blockers == (_OKX_NATIVE_STALE_SEED_BLOCKER,)
        and freshness_status == "stale"
    )

    if fresh_admitted:
        baseline_role = "fresh_signal_source"
        default_reason = "okx_native_demo_data_contract_passed"
    elif stale_seed_admitted:
        baseline_role = "immutable_integrity_verified_stale_seed_only"
        default_reason = "okx_native_stale_seed_public_tail_required"
    else:
        baseline_role = "not_admitted"
        default_reason = ""

    return {
        "demo_selectable": fresh_admitted or stale_seed_admitted,
        "default_reason": default_reason,
        "runtime_data_policy": {
            "baseline_role": baseline_role,
            "baseline_freshness_status": freshness_status,
            "runtime_public_tail_required": stale_seed_admitted,
            "runtime_public_tail_endpoint": (
                "/api/v5/market/candles" if stale_seed_admitted else ""
            ),
        },
    }


def _display_name(strategy_id: str) -> str:
    return {
        STABLE_STRATEGY_LINE: "Long/Short Donchian Top5",
        OKX_NATIVE_STRATEGY_LINE: "Long/Short Donchian Top5 · OKX Native",
        HIGH_YIELD_STRATEGY_LINE: "High-Yield Donchian v2",
        HIGH_OCTANE_STRATEGY_LINE: "High-Octane Attack Sleeve v2",
    }.get(strategy_id, strategy_id)
