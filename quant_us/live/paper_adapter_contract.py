from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse


ALLOWED_ALPACA_PAPER_BASE_URLS: tuple[str, ...] = (
    "https://paper-api.alpaca.markets",
)
ALPACA_LIVE_BASE_URL = "https://api.alpaca.markets"
PAPER_ADAPTER_CONTRACT_VERSION = "paper_adapter_contract_v4"


REQUIRED_PAPER_ADAPTER_CAPABILITIES: tuple[str, ...] = (
    "submit_order",
    "cancel_order",
    "poll_orders",
    "sync_fills",
    "sync_account",
    "sync_positions",
    "readiness_report",
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


def normalize_alpaca_base_url(base_url: str) -> str:
    raw = base_url.strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/").lower()

    normalized_path = parsed.path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def classify_alpaca_endpoint(base_url: str) -> str:
    normalized_base_url = normalize_alpaca_base_url(base_url)
    if not normalized_base_url:
        return "unset"

    parsed = urlparse(normalized_base_url)
    host = parsed.netloc.lower()
    path = parsed.path
    if normalized_base_url in ALLOWED_ALPACA_PAPER_BASE_URLS:
        return "paper"
    if host == "api.alpaca.markets" and path in {"", "/"}:
        return "live"
    if host == "paper-api.alpaca.markets":
        return "paper_lookalike"
    if "paper-api.alpaca.markets" in host or "paper" in normalized_base_url.lower():
        return "paper_lookalike"
    if host.endswith("alpaca.markets") or "alpaca" in host:
        return "custom_alpaca"
    return "custom"


def audit_apca_paper_credentials(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    base_url = source.get("APCA_API_BASE_URL", "")
    normalized_base_url = normalize_alpaca_base_url(base_url)
    api_key_present = bool(source.get("APCA_API_KEY_ID"))
    api_secret_present = bool(source.get("APCA_API_SECRET_KEY"))
    return {
        "api_key_present": api_key_present,
        "api_secret_present": api_secret_present,
        "credentials_present": api_key_present and api_secret_present,
        "base_url": base_url,
        "normalized_base_url": normalized_base_url,
        "endpoint_kind": classify_alpaca_endpoint(base_url),
        "base_url_valid": normalized_base_url in ALLOWED_ALPACA_PAPER_BASE_URLS,
        "allowed_base_url": ALLOWED_ALPACA_PAPER_BASE_URLS[0],
        "allowed_base_urls": list(ALLOWED_ALPACA_PAPER_BASE_URLS),
        "live_base_url": ALPACA_LIVE_BASE_URL,
        "readonly": False,
    }


@dataclass(frozen=True)
class PaperAdapterContract:
    """Fail-closed contract for paper broker adapter activation."""

    requested_backend: str
    effective_backend: str
    adapter_enabled: bool
    adapter_code_enabled: bool
    adapter_factory_present: bool
    submit_capable: bool
    fail_closed: bool
    reason: str
    capabilities: dict[str, bool] = field(default_factory=paper_adapter_capability_defaults)
    env_requested: bool = False
    endpoint_kind: str = "unset"
    base_url_valid: bool = False
    credentials_present: bool = False
    approved_evidence: bool = False
    adapter_ready: bool = False
    readiness_reasons: list[str] = field(default_factory=list)
    allowed_base_urls: list[str] = field(
        default_factory=lambda: list(ALLOWED_ALPACA_PAPER_BASE_URLS)
    )
    contract_version: str = PAPER_ADAPTER_CONTRACT_VERSION

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
    credentials_present: bool = False,
    credential_reason: str = "apca_paper_credentials_missing",
    approved_evidence: bool = False,
    evidence_reason: str = "paper_review_or_promotion_evidence_missing",
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
            adapter_code_enabled=adapter_enabled,
            adapter_factory_present=False,
            submit_capable=False,
            fail_closed=False,
            reason="simulated_paper_backend",
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            credentials_present=credentials_present,
            approved_evidence=approved_evidence,
            adapter_ready=False,
            allowed_base_urls=list(allowed_base_urls),
        )

    if requested != "alpaca":
        return PaperAdapterContract(
            requested_backend=requested,
            effective_backend="simulated",
            adapter_enabled=False,
            adapter_code_enabled=adapter_enabled,
            adapter_factory_present=False,
            submit_capable=False,
            fail_closed=True,
            reason=f"unsupported_paper_broker: {requested_backend}",
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            credentials_present=credentials_present,
            approved_evidence=approved_evidence,
            adapter_ready=False,
            readiness_reasons=[f"unsupported_paper_broker: {requested_backend}"],
            allowed_base_urls=list(allowed_base_urls),
        )

    adapter_code_enabled = adapter_enabled
    explicitly_enabled = adapter_code_enabled and env_requested
    enabled = explicitly_enabled and adapter_factory_present
    missing_capabilities = [name for name, present in capabilities.items() if not present]
    readiness_reasons: list[str] = []
    if not adapter_code_enabled or not adapter_factory_present:
        readiness_reasons.append("alpaca_paper_broker_adapter_not_configured")
    elif not env_requested:
        readiness_reasons.append("alpaca_paper_adapter_not_explicitly_enabled")
    if missing_capabilities:
        readiness_reasons.append(
            "alpaca_paper_adapter_capabilities_incomplete: "
            + ",".join(sorted(missing_capabilities))
        )
    if not credentials_present:
        readiness_reasons.append(credential_reason)
    if not base_url_valid:
        readiness_reasons.append("apca_base_url_not_allowed")
    if not approved_evidence:
        readiness_reasons.append(evidence_reason)

    if enabled and not missing_capabilities and credentials_present and base_url_valid and approved_evidence:
        return PaperAdapterContract(
            requested_backend="alpaca",
            effective_backend="alpaca_paper",
            adapter_enabled=True,
            adapter_code_enabled=adapter_code_enabled,
            adapter_factory_present=True,
            submit_capable=True,
            fail_closed=False,
            reason="alpaca_paper_adapter_contract_ready",
            capabilities=capabilities,
            env_requested=env_requested,
            endpoint_kind=endpoint_kind,
            base_url_valid=base_url_valid,
            credentials_present=True,
            approved_evidence=True,
            adapter_ready=True,
            readiness_reasons=[],
            allowed_base_urls=list(allowed_base_urls),
        )

    if enabled and missing_capabilities:
        return PaperAdapterContract(
            requested_backend="alpaca",
            effective_backend="simulated",
            adapter_enabled=True,
            adapter_code_enabled=adapter_code_enabled,
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
            credentials_present=credentials_present,
            approved_evidence=approved_evidence,
            adapter_ready=False,
            readiness_reasons=readiness_reasons,
            allowed_base_urls=list(allowed_base_urls),
        )

    if enabled and not credentials_present:
        reason = credential_reason
    elif enabled and not base_url_valid:
        reason = "apca_base_url_not_allowed"
    elif enabled and not approved_evidence:
        reason = evidence_reason
    elif adapter_code_enabled and adapter_factory_present and not env_requested:
        reason = "alpaca_paper_adapter_not_explicitly_enabled"
    else:
        reason = "alpaca_paper_broker_adapter_not_configured"

    return PaperAdapterContract(
        requested_backend="alpaca",
        effective_backend="simulated",
        adapter_enabled=explicitly_enabled,
        adapter_code_enabled=adapter_code_enabled,
        adapter_factory_present=adapter_factory_present,
        submit_capable=False,
        fail_closed=True,
        reason=reason,
        capabilities=capabilities,
        env_requested=env_requested,
        endpoint_kind=endpoint_kind,
        base_url_valid=base_url_valid,
        credentials_present=credentials_present,
        approved_evidence=approved_evidence,
        adapter_ready=False,
        readiness_reasons=readiness_reasons,
        allowed_base_urls=list(allowed_base_urls),
    )
