"""Lazy candidate composition. Read-side catalogue resolution never creates files."""
from dataclasses import dataclass
import json
from pathlib import Path

from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
from backend.app.services.candidate_delivery_store import DeliveryStore
from quant_shared.strategy_delivery.models import DeliveryError, digest
from quant_shared.strategy_delivery.service import DeliveryService


def _read_candidate_catalog_roots(inputs) -> tuple[Path, Path]:
    """Normalize expected configuration I/O/shape failures without hiding code defects."""
    try:
        catalog = inputs.catalog()
        return (
            inputs.path_for(catalog["factory_root"]),
            inputs.path_for(catalog["qlib_root"]),
        )
    except DeliveryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise DeliveryError("offline_catalog_unreadable") from exc


@dataclass(frozen=True)
class CandidateResearchRoots:
    """Server-owned research roots, optionally bound to an immutable catalogue."""

    factory_root: Path
    qlib_root: Path
    inputs: object | None = None

    @property
    def configured(self) -> bool:
        return self.inputs is not None

    def revalidate(self) -> "CandidateResearchRoots":
        """Recheck the catalogue checksum and both paths on every public read."""
        if self.inputs is None:
            return self
        factory_root, qlib_root = _read_candidate_catalog_roots(self.inputs)
        if factory_root != self.factory_root or qlib_root != self.qlib_root:
            raise DeliveryError("offline_catalog_root_changed")
        return self


def resolve_candidate_research_roots(settings, *, qlib_root) -> CandidateResearchRoots:
    """Resolve one authoritative pair of roots; only absence permits legacy roots."""
    repo = settings.repo_root.resolve()
    if not getattr(settings, "candidate_offline_catalog", ""):
        return CandidateResearchRoots(
            factory_root=repo / "artifacts/alpha_factory_runs",
            qlib_root=Path(qlib_root),
        )
    from .candidate_offline_inputs import OfflineInputs

    inputs = OfflineInputs(
        settings.candidate_offline_catalog,
        settings.candidate_offline_catalog_sha256,
        settings.candidate_offline_catalog_revision,
        repo=repo,
    )
    factory_root, resolved_qlib_root = _read_candidate_catalog_roots(inputs)
    return CandidateResearchRoots(
        factory_root=factory_root,
        qlib_root=resolved_qlib_root,
        inputs=inputs,
    )


class CandidateResearchArchiveGuard:
    """Revalidate the external catalogue before delegating read-only discovery."""

    def __init__(self, roots: CandidateResearchRoots, archive):
        self.roots, self.archive = roots, archive

    def _validated(self):
        try:
            self.roots.revalidate()
        except DeliveryError as exc:
            from backend.app.services.research_archive_discovery import ResearchArchiveUnavailable

            raise ResearchArchiveUnavailable(f"candidate_offline_catalog_invalid:{exc.code}") from exc

    def _externalize(self, location):
        if location is None or location.archived:
            return location
        from backend.app.services.research_archive_discovery import ReadonlyRunLocation

        return ReadonlyRunLocation(
            run_id=location.run_id,
            run_root=location.run_root,
            qlib_root=location.qlib_root,
            logical_root=location.logical_root,
            provenance={
                "storage": "external_candidate_catalog",
                "catalog_revision": self.roots.inputs.revision,
                "catalog_sha256": self.roots.inputs.checksum,
                "logical_run": location.logical_root,
                "consumer_read_only": True,
                "integrity_validation": "catalog_and_run_seal_current_request",
            },
            verified_files=location.verified_files,
        )

    def list_qlib_runs(self, local_root):
        self._validated()
        return tuple(self._externalize(item) for item in self.archive.list_qlib_runs(local_root))

    def resolve_qlib_run(self, local_root, run_id):
        self._validated()
        return self._externalize(self.archive.resolve_qlib_run(local_root, run_id))

    def list_factory_runs(self, local_root, qlib_root):
        self._validated()
        return tuple(self._externalize(item) for item in self.archive.list_factory_runs(local_root, qlib_root))

    def resolve_factory_run(self, local_root, qlib_root, run_id):
        self._validated()
        return self._externalize(self.archive.resolve_factory_run(local_root, qlib_root, run_id))


class UnavailableCandidateResearchArchive:
    """Keep the app up while every affected GET fails closed with a stable 503."""

    def __init__(self, reason: str):
        self.reason = reason

    def _raise(self):
        from backend.app.services.research_archive_discovery import ResearchArchiveUnavailable

        raise ResearchArchiveUnavailable(self.reason)

    def list_qlib_runs(self, *_args):
        self._raise()

    def resolve_qlib_run(self, *_args):
        self._raise()

    def list_factory_runs(self, *_args):
        self._raise()

    def resolve_factory_run(self, *_args):
        self._raise()


def build_delivery_service(settings, *, archive, qlib_root, head, research_roots=None):
    if not settings.candidate_delivery_root: return None
    root = Path(settings.candidate_delivery_root)
    if not root.is_absolute(): raise DeliveryError("delivery_root_must_be_external_absolute")
    root = root.resolve()
    repo = settings.repo_root.resolve()
    from quant_crypto.adapters.btc_runtime_artifact_store import git_worktree_roots
    if (root == Path(root.anchor) or any(root.is_relative_to(checkout)
        or checkout.is_relative_to(root) for checkout in git_worktree_roots(repo))):
        raise DeliveryError("delivery_root_must_be_external_absolute")
    from backend.app.services.alpha_factory import AlphaFactoryService
    roots = research_roots or resolve_candidate_research_roots(settings, qlib_root=qlib_root)
    roots.revalidate()
    index = None
    if roots.configured:
        from .candidate_offline_store import OfflineStore
        from .candidate_delivery_index import DeliveryIndex

        index = DeliveryIndex(roots.inputs, OfflineStore(root, digest({"repository": str(repo)})))
    factory = AlphaFactoryService(root=roots.factory_root, qlib_root=roots.qlib_root,
                                   queue=None, readonly_archive=archive)
    sources = ResearchDeliverySources(repo, archive=archive, qlib_root=roots.qlib_root, factory_reader=factory,
                                     delivery_artifacts=index if index is not None else ())
    accounts = DeliveryAccounts(root / "accounts.json", repo_root=repo,
                               approval_registry=settings.btc_demo_account_facts_approval_registry)
    from tools.agent_governance.git_metadata import current_branch_head
    service = DeliveryService(DeliveryStore(root, digest({"repository": str(repo)})), sources, accounts,
                              head=head, head_provider=lambda: current_branch_head(repo)[1])
    service.offline_index = index
    return service


def build_offline_service(settings, delivery):
    if delivery is None or delivery.offline_index is None: return None
    from .candidate_offline_service import CandidateOfflineService
    index = delivery.offline_index
    return CandidateOfflineService(delivery, index.inputs, index, index.store,
        profile=settings.backend_evidence_profile, enabled=settings.candidate_offline_enabled,
        operator=settings.candidate_delivery_operator, management_key=settings.web_api_key,
        auth_mode=getattr(settings, "candidate_auth_mode", "key"))
