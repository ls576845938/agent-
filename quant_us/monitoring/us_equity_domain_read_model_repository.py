"""Committed-blob repository for the US equity domain read model."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


DEFAULT_SOURCE_CONTRACT = Path(
    "configs/governance/us_equity_domain_read_model_sources_v1.json"
)


class USCommittedEvidenceRepository:
    """Read immutable source bytes from Git, never from mutable working files."""

    def __init__(
        self,
        *,
        repo_root: Path,
        source_contract: Path = DEFAULT_SOURCE_CONTRACT,
        blob_reader: Callable[[str, str], bytes] | None = None,
        ancestor_checker: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.source_contract = source_contract
        self._blob_reader = blob_reader or self._git_blob
        self._ancestor_checker = ancestor_checker or self._git_is_ancestor

    def read_sources(
        self,
        *,
        source_head: str,
        generated_at_utc: datetime,
    ) -> Sequence[Mapping[str, Any]]:
        del generated_at_utc
        contract_path = _repo_path(self.source_contract)
        try:
            contract_raw = self._blob_reader(source_head, contract_path)
            contract = json.loads(contract_raw.decode("utf-8"))
        except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
            return [
                {
                    "id": "source_contract",
                    "integration_commit": source_head,
                    "freshness": "blocked",
                    "status": "blocked",
                    "decision": "fail_closed",
                    "readiness_class": "quality_checked",
                    "layers": [
                        {"id": layer, "readiness_class": "quality_checked"}
                        for layer in ("data", "backtest", "portfolio", "oms", "ledger", "replay")
                    ],
                    "artifact": {"path": contract_path, "sha256": "0" * 64},
                    "manifest": {"path": contract_path, "sha256": "0" * 64},
                    "validation_blockers": [
                        "domain_read_model_source_contract_missing_or_invalid"
                    ],
                    "payload": {},
                }
            ]
        if not isinstance(contract, dict) or contract.get("domain") != "us_equity":
            return [
                {
                    "id": "source_contract",
                    "integration_commit": source_head,
                    "freshness": "blocked",
                    "status": "blocked",
                    "decision": "fail_closed",
                    "readiness_class": "quality_checked",
                    "layers": [
                        {"id": layer, "readiness_class": "quality_checked"}
                        for layer in ("data", "backtest", "portfolio", "oms", "ledger", "replay")
                    ],
                    "artifact": {"path": contract_path, "sha256": hashlib.sha256(contract_raw).hexdigest()},
                    "manifest": {"path": contract_path, "sha256": hashlib.sha256(contract_raw).hexdigest()},
                    "validation_blockers": ["domain_read_model_source_contract_domain_invalid"],
                    "payload": {},
                }
            ]
        sources = contract.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        return [self._read_source(source_head, item) for item in sources]

    def _read_source(
        self,
        source_head: str,
        value: Any,
    ) -> dict[str, Any]:
        source = value if isinstance(value, Mapping) else {}
        source_id = str(source.get("id") or "unnamed_source")
        integration_commit = str(source.get("integration_commit") or "")
        artifact_contract = _mapping(source.get("artifact"))
        manifest_contract = _mapping(source.get("manifest"))
        layers = source.get("layers", [])
        validation_blockers: list[str] = []

        artifact, payload, artifact_errors = self._read_binding(
            source_head=source_head,
            source_id=source_id,
            kind="artifact",
            contract=artifact_contract,
            require_json=True,
        )
        validation_blockers.extend(artifact_errors)
        manifest, _, manifest_errors = self._read_binding(
            source_head=source_head,
            source_id=source_id,
            kind="manifest",
            contract=manifest_contract,
            require_json=False,
        )
        validation_blockers.extend(manifest_errors)

        if len(integration_commit) != 40:
            validation_blockers.append(
                f"source_integration_commit_invalid:{source_id}"
            )
        else:
            try:
                is_ancestor = self._ancestor_checker(integration_commit, source_head)
            except (OSError, subprocess.CalledProcessError):
                is_ancestor = False
            if not is_ancestor:
                validation_blockers.append(
                    f"source_integration_commit_wrong_head:{source_id}"
                )

        expected_schema = str(artifact_contract.get("schema_version") or "")
        if payload and expected_schema and payload.get("schema_version") != expected_schema:
            validation_blockers.append(f"source_schema_mismatch:{source_id}")

        freshness = "current_head" if not validation_blockers else "blocked"
        return {
            "id": source_id,
            "integration_commit": integration_commit,
            "freshness": freshness,
            "status": str(payload.get("status") or "blocked"),
            "decision": str(payload.get("decision") or "fail_closed"),
            "readiness_class": str(
                source.get("readiness_class") or "quality_checked"
            ),
            "layers": layers if isinstance(layers, list) else [],
            "artifact": artifact,
            "manifest": manifest,
            "validation_blockers": validation_blockers,
            "payload": payload,
        }

    def _read_binding(
        self,
        *,
        source_head: str,
        source_id: str,
        kind: str,
        contract: Mapping[str, Any],
        require_json: bool,
    ) -> tuple[dict[str, str], dict[str, Any], list[str]]:
        path_text = str(contract.get("path") or "")
        expected_sha = str(contract.get("sha256") or "")
        binding = {"path": path_text, "sha256": expected_sha}
        errors: list[str] = []
        if not _safe_repo_relative(path_text):
            errors.append(f"{kind}_path_invalid:{source_id}")
            return binding, {}, errors
        try:
            raw = self._blob_reader(source_head, path_text)
        except (OSError, subprocess.CalledProcessError):
            errors.append(f"{kind}_missing:{source_id}")
            return binding, {}, errors
        actual_sha = hashlib.sha256(raw).hexdigest()
        binding["sha256"] = actual_sha
        if len(expected_sha) != 64 or actual_sha != expected_sha:
            errors.append(f"{kind}_hash_mismatch:{source_id}")
        payload: dict[str, Any] = {}
        if require_json:
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                errors.append(f"{kind}_json_invalid:{source_id}")
            else:
                if isinstance(decoded, dict):
                    payload = decoded
                else:
                    errors.append(f"{kind}_not_object:{source_id}")
        return binding, payload, errors

    def _git_blob(self, revision: str, path: str) -> bytes:
        return subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
        ).stdout

    def _git_is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=self.repo_root,
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )


def _safe_repo_relative(value: str) -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _repo_path(path: Path) -> str:
    text = path.as_posix()
    if not _safe_repo_relative(text):
        raise ValueError("domain_read_model_contract_path_invalid")
    return text


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["DEFAULT_SOURCE_CONTRACT", "USCommittedEvidenceRepository"]
