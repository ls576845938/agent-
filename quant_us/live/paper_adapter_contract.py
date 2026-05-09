from __future__ import annotations

from dataclasses import asdict, dataclass, field


ALLOWED_ALPACA_PAPER_BASE_URLS: tuple[str, ...] = (
    "https://paper-api.alpaca.markets",
)


REQUIRED_PAPER_ADAPTER_CAPABILITIES: tuple[str, ...] = (
    "submit_order",
    "cancel_order",
    "poll_orders",
    "sync_fills",
    "sync_account",
    "sync_positions",
)


def paper_adapter_capability_defaults() -> dict[str, bool]:
    return {name: False for name in REQUIRED_PAPER_ADAPTER_CAPABILITIES}


def normalize_paper_adapter_capabilities(
    capabilities: dict[str, bool] | None = None,
) -> dict[str, bool]:
    normalized = paper_adapter_capability_defaults()
    if capabilities:
        for name, enabled in capabilities.items():
            if name in normalized:
                normalized[name] = bool(enabled)
    return normalized


@dataclass(frozen=True)
class PaperAdapterContract:
    """Fail-closed contract for paper broker adapter activation."""

    requested_backend: str
    effective_backend: str
    adapter_enabled: bool
    adapter_factory_present: bool
    submit_capable: bool
    fail_closed: bool
    reason: str
    capabilities: dict[str, bool] = field(default_factory=paper_adapter_capability_defaults)
    env_requested: bool = False
    endpoint_kind: str = "unset"
    base_url_valid: bool = False
    allowed_base_urls: list[str] = field(
        default_factory=lambda: list(ALLOWED_ALPACA_PAPER_BASE_URLS)
    )
    contract_version: str = "paper_adapter_contract_v3"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_paper_adapter_contract(
    requested_backend: str,
    *,
    adapter_enabled: bool = False,
    adapter_factory_present: bool = False,
    adapter_capabilities: dict[str, bool] | None = None,
    env_requested: bool = False,
    endpoint_kind: str = "unset",
    base_url_valid: bool = False,
    allowed_base_urls: tuple[str, ...] = ALLOWED_ALPACA_PAPER_BASE_URLS,
) -> PaperAdapterContract:
    """Return the effective paper broker contract without importing broker APIs."""
    requested = requested_backend.lower()
    capabilities = normalize_paper_adapter_capabilities(adapter_capabilities)
    if requested == "simulated":
        return PaperAdapterContract(
            requested_backend=requested,
            effective_backend="simulated",
            adapter_enabled=False,
            adapter_factory_present=False,
            submit_capable=False,
            fail_closed=False,
            reason="simulated_paper_backend",
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            allowed_base_urls=list(allowed_base_urls),
        )

    if requested != "alpaca":
        return PaperAdapterContract(
            requested_backend=requested,
            effective_backend="simulated",
            adapter_enabled=False,
            adapter_factory_present=False,
            submit_capable=False,
            fail_closed=True,
            reason=f"unsupported_paper_broker: {requested_backend}",
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            allowed_base_urls=list(allowed_base_urls),
        )

    enabled = adapter_enabled and adapter_factory_present
    missing_capabilities = [name for name, present in capabilities.items() if not present]
    if enabled and not missing_capabilities:
        return PaperAdapterContract(
            requested_backend="alpaca",
            effective_backend="alpaca_paper",
            adapter_enabled=True,
            adapter_factory_present=True,
            submit_capable=True,
            fail_closed=False,
            reason="alpaca_paper_adapter_contract_ready",
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            allowed_base_urls=list(allowed_base_urls),
        )

    if enabled and missing_capabilities:
        return PaperAdapterContract(
            requested_backend="alpaca",
            effective_backend="simulated",
            adapter_enabled=True,
            adapter_factory_present=True,
            submit_capable=False,
            fail_closed=True,
            reason=(
                "alpaca_paper_adapter_capabilities_incomplete: "
                + ",".join(sorted(missing_capabilities))
            ),
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            allowed_base_urls=list(allowed_base_urls),
        )

    return PaperAdapterContract(
        requested_backend="alpaca",
        effective_backend="simulated",
        adapter_enabled=False,
        adapter_factory_present=adapter_factory_present,
        submit_capable=False,
        fail_closed=True,
        reason="alpaca_paper_broker_adapter_not_configured",
        capabilities=capabilities,
        env_requested=env_requested,
        endpoint_kind=endpoint_kind,
        base_url_valid=base_url_valid,
        allowed_base_urls=list(allowed_base_urls),
    )
