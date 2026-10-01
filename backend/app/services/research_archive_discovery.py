"""Server-owned discovery for immutable, read-only research evidence archives."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from tools.agent_governance.shared_data import (
    SharedDataError,
    default_shared_data_root,
    load_manifest_from_git,
    resolve_manifest_payload,
)


M1_MANIFEST_COMMIT = "165a446729f8c114748e1b20bbfcf0c91e75066e"
M1_MANIFEST_PATH = (
    ".agent/data_manifests/m1-trend-environment-acceptance/"
    "m1-okx-59f5eb861-20260911.json"
)
M1_MANIFEST_GIT_SPEC = f"{M1_MANIFEST_COMMIT}:{M1_MANIFEST_PATH}"
M1_DATASET_ID = "m1-trend-environment-acceptance"
M1_DATASET_VERSION = "m1-okx-59f5eb861-20260911"
M1_AGGREGATE_SHA256 = "593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde"
M1_PRODUCER_COMMIT = "59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e"
M1_QLIB_RUN_IDS = (
    "m1-okx-qlib",
    "m1-okx-factory-input",
    "m1-okx-factory-t1-fold1",
    "m1-okx-factory-t1-fold2",
    "m1-okx-factory-t1-fold3",
    "m1-okx-factory-t1-fold4",
)
M1_FACTORY_RUN_IDS = ("m1-okx-factory",)


class ResearchArchiveError(RuntimeError):
    """Base class for fail-closed archive discovery errors."""


class ResearchArchiveUnavailable(ResearchArchiveError):
    """The fixed archive or one of its sealed files cannot be verified."""


class ResearchArchiveConflict(ResearchArchiveError):
    """A run id exists in both local mutable storage and the immutable archive."""


@dataclass(frozen=True)
class ReadonlyRunLocation:
    run_id: str
    run_root: Path
    qlib_root: Path
    logical_root: str
    provenance: Mapping[str, Any]
    verified_files: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def archived(self) -> bool:
        return self.provenance.get("storage") == "immutable_shared_data"


ManifestLoader = Callable[[Path, str], dict[str, Any]]
ManifestResolver = Callable[..., Path]


class ResearchArchiveCatalog:
    """Resolve a fixed catalog; callers cannot select a root, ref, path, or run set."""

    def __init__(
        self,
        *,
        repo_root: Path,
        shared_root: Path | None = None,
        manifest_loader: ManifestLoader = load_manifest_from_git,
        manifest_resolver: ManifestResolver = resolve_manifest_payload,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.shared_root = Path(shared_root or default_shared_data_root(self.repo_root)).resolve()
        self._manifest_loader = manifest_loader
        self._manifest_resolver = manifest_resolver

    def _verified_dataset(self) -> tuple[dict[str, Any], Path]:
        try:
            manifest = self._manifest_loader(self.repo_root, M1_MANIFEST_GIT_SPEC)
            self._validate_fixed_manifest(manifest)
            resolved = Path(
                self._manifest_resolver(
                    manifest,
                    shared_root=self.shared_root,
                    verify_files=True,
                )
            ).resolve()
        except (OSError, SharedDataError, ValueError) as exc:
            raise ResearchArchiveUnavailable("readonly_archive_unavailable") from exc

        expected = (
            self.shared_root
            / "datasets"
            / M1_DATASET_ID
            / M1_DATASET_VERSION
        ).resolve()
        if resolved != expected or not self._is_relative_to(resolved, self.shared_root):
            raise ResearchArchiveUnavailable("readonly_archive_resolved_path_mismatch")
        return manifest, resolved

    @staticmethod
    def _validate_fixed_manifest(manifest: Mapping[str, Any]) -> None:
        expected = {
            "dataset_id": M1_DATASET_ID,
            "dataset_version": M1_DATASET_VERSION,
            "producer_commit": M1_PRODUCER_COMMIT,
            "data_schema": "m1_research_observation_acceptance_v1",
            "readiness_class": "quality_checked",
            "quality_status": "pass_with_research_only_warnings",
            "aggregate_sha256": M1_AGGREGATE_SHA256,
            "file_count": 160,
            "total_bytes": 56_134_415,
        }
        mismatches = [key for key, value in expected.items() if manifest.get(key) != value]
        guardrails = manifest.get("guardrails")
        if not isinstance(guardrails, Mapping):
            mismatches.append("guardrails")
        else:
            if guardrails.get("consumer_read_only") is not True:
                mismatches.append("consumer_read_only")
            for key in (
                "promotion_unlock_allowed",
                "paper_or_live_unlock_allowed",
                "private_endpoint_used",
                "order_endpoint_used",
            ):
                if guardrails.get(key) is not False:
                    mismatches.append(key)

        qlib_ids: set[str] = set()
        factory_ids: set[str] = set()
        for item in manifest.get("files", []):
            if not isinstance(item, Mapping):
                continue
            parts = str(item.get("path", "")).split("/")
            if len(parts) >= 3 and parts[0] == "qlib_runs":
                qlib_ids.add(parts[1])
            elif len(parts) >= 3 and parts[0] == "alpha_factory":
                factory_ids.add(parts[1])
        if qlib_ids != set(M1_QLIB_RUN_IDS):
            mismatches.append("qlib_run_ids")
        if factory_ids != set(M1_FACTORY_RUN_IDS):
            mismatches.append("factory_run_ids")
        if mismatches:
            raise SharedDataError("readonly_archive_manifest_mismatch:" + ",".join(sorted(set(mismatches))))

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _archive_location(
        self,
        *,
        kind: str,
        run_id: str,
        dataset_root: Path,
        manifest: Mapping[str, Any],
    ) -> ReadonlyRunLocation:
        parent_name = "qlib_runs" if kind == "qlib" else "alpha_factory"
        parent = (dataset_root / parent_name).resolve()
        run_root = (parent / run_id).resolve()
        if (
            not self._is_relative_to(parent, dataset_root)
            or not self._is_relative_to(run_root, parent)
            or run_root.parent != parent
            or not run_root.is_dir()
        ):
            raise ResearchArchiveUnavailable(f"readonly_archive_run_missing_or_escaped:{kind}:{run_id}")
        logical_root = f"shared-data://{M1_DATASET_ID}/{M1_DATASET_VERSION}/{parent_name}/{run_id}"
        file_prefix = f"{parent_name}/{run_id}/"
        verified_files = {
            str(item["path"])[len(file_prefix):]: {
                "sha256": str(item["sha256"]),
                "bytes": int(item["bytes"]),
            }
            for item in manifest.get("files", [])
            if isinstance(item, Mapping)
            and str(item.get("path", "")).startswith(file_prefix)
        }
        return ReadonlyRunLocation(
            run_id=run_id,
            run_root=run_root,
            qlib_root=(dataset_root / "qlib_runs").resolve(),
            logical_root=logical_root,
            provenance={
                "storage": "immutable_shared_data",
                "dataset_id": M1_DATASET_ID,
                "dataset_version": M1_DATASET_VERSION,
                "manifest_git_spec": M1_MANIFEST_GIT_SPEC,
                "logical_run": f"{parent_name}/{run_id}",
                "consumer_read_only": True,
                "historical_reconstructed_availability": True,
                "integrity_validation": "shared_manifest_sha256_current_request",
            },
            verified_files=verified_files,
        )

    @staticmethod
    def _local_location(*, kind: str, run_id: str, local_root: Path) -> ReadonlyRunLocation:
        parent_name = "qlib_runs" if kind == "qlib" else "alpha_factory_runs"
        return ReadonlyRunLocation(
            run_id=run_id,
            run_root=local_root / run_id,
            qlib_root=local_root if kind == "qlib" else Path(),
            logical_root=f"artifacts/{parent_name}/{run_id}",
            provenance={
                "storage": "repo_local",
                "logical_run": f"artifacts/{parent_name}/{run_id}",
                "consumer_read_only": True,
            },
        )

    def _archive_locations(self, *, kind: str) -> tuple[ReadonlyRunLocation, ...]:
        manifest, dataset_root = self._verified_dataset()
        run_ids = M1_QLIB_RUN_IDS if kind == "qlib" else M1_FACTORY_RUN_IDS
        return tuple(
            self._archive_location(
                kind=kind,
                run_id=run_id,
                dataset_root=dataset_root,
                manifest=manifest,
            )
            for run_id in run_ids
        )

    def list_qlib_runs(self, local_root: Path) -> tuple[ReadonlyRunLocation, ...]:
        return self._combine(kind="qlib", local_root=Path(local_root), archive=self._archive_locations(kind="qlib"))

    def list_factory_runs(self, local_root: Path, qlib_root: Path) -> tuple[ReadonlyRunLocation, ...]:
        locations = self._combine(
            kind="factory",
            local_root=Path(local_root),
            archive=self._archive_locations(kind="factory"),
        )
        return tuple(
            location
            if location.archived
            else ReadonlyRunLocation(
                run_id=location.run_id,
                run_root=location.run_root,
                qlib_root=Path(qlib_root),
                logical_root=location.logical_root,
                provenance=location.provenance,
                verified_files=location.verified_files,
            )
            for location in locations
        )

    def resolve_qlib_run(self, local_root: Path, run_id: str) -> ReadonlyRunLocation | None:
        return self._resolve_one(kind="qlib", local_root=Path(local_root), run_id=run_id)

    def resolve_factory_run(self, local_root: Path, qlib_root: Path, run_id: str) -> ReadonlyRunLocation | None:
        location = self._resolve_one(kind="factory", local_root=Path(local_root), run_id=run_id)
        if location is None or location.archived:
            return location
        return ReadonlyRunLocation(
            run_id=location.run_id,
            run_root=location.run_root,
            qlib_root=Path(qlib_root),
            logical_root=location.logical_root,
            provenance=location.provenance,
            verified_files=location.verified_files,
        )

    def _combine(
        self,
        *,
        kind: str,
        local_root: Path,
        archive: tuple[ReadonlyRunLocation, ...],
    ) -> tuple[ReadonlyRunLocation, ...]:
        local: dict[str, ReadonlyRunLocation] = {}
        local_entry_names: set[str] = set()
        if local_root.exists():
            root_resolved = local_root.resolve()
            for path in local_root.iterdir():
                local_entry_names.add(path.name)
                if (
                    path.is_dir()
                    and path.resolve().parent == root_resolved
                    and (kind == "qlib" or (path / "state.json").is_file())
                ):
                    local[path.name] = self._local_location(kind=kind, run_id=path.name, local_root=local_root)
        duplicate_ids = sorted(local_entry_names & {item.run_id for item in archive})
        if duplicate_ids:
            raise ResearchArchiveConflict(
                f"readonly_archive_duplicate_run_id:{kind}:{','.join(duplicate_ids)}"
            )
        return (*local.values(), *archive)

    def _resolve_one(self, *, kind: str, local_root: Path, run_id: str) -> ReadonlyRunLocation | None:
        allowed = M1_QLIB_RUN_IDS if kind == "qlib" else M1_FACTORY_RUN_IDS
        local_candidate = local_root / run_id
        if run_id not in allowed:
            return self._local_location(kind=kind, run_id=run_id, local_root=local_root) if local_candidate.exists() else None
        archive = {item.run_id: item for item in self._archive_locations(kind=kind)}[run_id]
        if local_candidate.exists():
            raise ResearchArchiveConflict(f"readonly_archive_duplicate_run_id:{kind}:{run_id}")
        return archive


def build_m1_research_archive_catalog(*, repo_root: Path) -> ResearchArchiveCatalog:
    return ResearchArchiveCatalog(repo_root=repo_root)
