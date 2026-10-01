from __future__ import annotations

from dataclasses import dataclass
import re


PROMOTION_STRICT_PROFILE = "promotion_strict"
DEMO_QUASI_LIVE_PROFILE = "demo_quasi_live"
RESEARCH_READONLY_PROFILE = "research_readonly"
CANDIDATE_MANAGEMENT_PROFILE = "candidate_management"
BACKEND_EVIDENCE_PROFILES = frozenset(
    {
        PROMOTION_STRICT_PROFILE,
        DEMO_QUASI_LIVE_PROFILE,
        RESEARCH_READONLY_PROFILE,
        CANDIDATE_MANAGEMENT_PROFILE,
    }
)

_READONLY_EXACT_GET_PATHS = frozenset(
    {
        "/api/candidate-offline/capabilities",
        "/api/candidate-offline/catalog",
        "/api/candidate-offline/jobs",
        "/__backend_identity",
        "/api/health",
        "/api/strategies",
        "/api/tasks",
        "/api/integrations/qlib/runs",
        "/api/integrations/portfolio/runs",
        "/api/portfolio/status",
        "/api/research/alpha-factory",
        "/api/research/btc/strategy-registry",
        # Display-only public reads. No Demo/status/operator/private routes.
        "/api/research/btc/public-market/view",
        "/api/research/btc/public-market/ticker",
        "/api/research/btc/public-market/stream",
        "/api/research/candidates",
        "/api/research/evidence-registry",
        "/api/research/experiments",
        "/api/research/factors",
        "/api/research/features",
        "/api/research/global-registry",
        "/api/research/paper-review/entry-state",
        "/api/research/paper-review/pending",
        "/api/research/strategy-history/catalog",
        "/api/research/strategy-manifests",
        "/api/research/btc/domain-read-model",
        "/api/system/overview",
    }
)
_READONLY_PARAMETERIZED_GET_PATHS = (
    re.compile(r"^/api/candidate-offline/jobs/coff_[0-9a-f]{32}(?:/result)?$"),
    re.compile(r"^/api/tasks/[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    re.compile(r"^/api/integrations/qlib/runs/[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    re.compile(r"^/api/research/alpha-factory/runs/[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"),
    re.compile(r"^/api/integrations/portfolio/runs/[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
)


@dataclass(frozen=True)
class BackendAccessDecision:
    allowed: bool
    reason: str


def is_research_readonly(profile: str) -> bool:
    return profile.strip().lower() == RESEARCH_READONLY_PROFILE


def is_research_surface_profile(profile: str) -> bool:
    """Both modes exclude Demo/IBKR controller construction and private reads."""
    return profile.strip().lower() in {RESEARCH_READONLY_PROFILE, CANDIDATE_MANAGEMENT_PROFILE}


def evaluate_backend_access(
    *,
    profile: str,
    method: str,
    path: str,
) -> BackendAccessDecision:
    """Fail closed before a route can construct a writer or credential client."""
    if profile.strip().lower() == CANDIDATE_MANAGEMENT_PROFILE:
        base = evaluate_backend_access(profile=RESEARCH_READONLY_PROFILE, method=method, path=path)
        if base.allowed:
            return base
        normalized_method = method.upper()
        offline_command = path in {"/api/candidate-offline/jobs", "/api/candidate-offline/publish"} or re.fullmatch(
            r"/api/candidate-offline/jobs/coff_[0-9a-f]{32}/(?:stop|resume)", path) is not None
        if normalized_method == "POST" and offline_command:
            return BackendAccessDecision(True, "offline_route_requires_operator_and_capability")
        root = "/api/strategy-delivery"
        reads = path in {root + "/capabilities", root + "/accounts", root + "/packages", root + "/catalog"}
        detail = re.fullmatch(re.escape(root) + r"/packages/delivery_[0-9a-f]{32}", path) is not None
        detail = detail or re.fullmatch(re.escape(root) + r"/requests/[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", path) is not None
        command = path == root + "/packages" or re.fullmatch(
            re.escape(root) + r"/packages/delivery_[0-9a-f]{32}/(?:bind|review|register|revoke)", path) is not None
        if (normalized_method in {"GET", "HEAD"} and (reads or detail)) or (normalized_method == "POST" and command):
            return BackendAccessDecision(True, "candidate_management_route_requires_operator_auth")
        return BackendAccessDecision(False, "candidate_management_route_not_allowlisted")
    if not is_research_readonly(profile):
        return BackendAccessDecision(True, "profile_not_research_readonly")
    normalized_method = method.upper()
    if normalized_method == "OPTIONS":
        return BackendAccessDecision(True, "cors_preflight")
    if normalized_method not in {"GET", "HEAD"}:
        return BackendAccessDecision(False, "method_not_readonly")
    if path in _READONLY_EXACT_GET_PATHS:
        return BackendAccessDecision(True, "reviewed_read_surface")
    if any(pattern.fullmatch(path) for pattern in _READONLY_PARAMETERIZED_GET_PATHS):
        return BackendAccessDecision(True, "reviewed_parameterized_read_surface")
    return BackendAccessDecision(False, "route_not_reviewed_for_readonly")


def readonly_block_payload(*, reason: str) -> dict[str, object]:
    return {
        "status": "blocked",
        "error": "backend_research_readonly_route_blocked",
        "reason": reason,
        "evidence_profile": RESEARCH_READONLY_PROFILE,
        "read_only": True,
        "controls_disabled": True,
        "research_completion_grants_trading": False,
        "paper_allowed": False,
        "live_allowed": False,
        "broker_or_order_allowed": False,
    }

