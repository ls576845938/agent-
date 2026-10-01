from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pytest

from quant_us.core.artifact_paths import (
    artifact_path_identity_hash,
    durable_artifact_path_reference,
    external_artifact_path_reference,
    resolve_durable_artifact_path,
    serialize_durable_artifact_locator,
    serialize_durable_artifact_path,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/us_artifact_path_reference.schema.json"
CONFIG = ROOT / "configs/governance/us_windows_artifact_path_contract_v1.json"


def test_equivalent_windows_and_posix_paths_have_stable_identity_hash() -> None:
    windows = durable_artifact_path_reference(
        r"C:\repo\artifacts\paper\manifest.json",
        identity_root=r"C:\repo",
    )
    posix = durable_artifact_path_reference(
        "C:/repo/artifacts/paper/manifest.json",
        identity_root="C:/repo",
    )

    assert windows == posix
    assert windows["path"] == "artifacts/paper/manifest.json"
    assert artifact_path_identity_hash(windows) == artifact_path_identity_hash(posix)
    jsonschema.validate(windows, json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_durable_paths_are_relative_posix_and_resolve_under_identity_root(
    tmp_path: Path,
) -> None:
    target = tmp_path / "audit" / "paper_session_manifest.json"
    serialized = serialize_durable_artifact_path(target, identity_root=tmp_path)
    locator = serialize_durable_artifact_locator(
        f"{target}#section.review",
        identity_root=tmp_path,
    )

    assert serialized == "audit/paper_session_manifest.json"
    assert locator == "audit/paper_session_manifest.json#section.review"
    assert resolve_durable_artifact_path(serialized, identity_root=tmp_path) == target
    assert (
        serialize_durable_artifact_path("/repo/audit/report.json", identity_root="/")
        == "repo/audit/report.json"
    )


def test_external_absolute_path_has_explicit_non_identity_schema() -> None:
    reference = external_artifact_path_reference(r"C:\external\fixture.json")

    assert reference == {
        "schema_version": "us_artifact_path_reference_v1",
        "path_kind": "external_absolute",
        "path": "C:/external/fixture.json",
        "stable_identity": False,
    }
    jsonschema.validate(reference, json.loads(SCHEMA.read_text(encoding="utf-8")))
    with pytest.raises(ValueError, match="cannot be stable artifact identities"):
        artifact_path_identity_hash(reference)


def test_read_only_validator_accepts_durable_reference(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(
        json.dumps(
            durable_artifact_path_reference(
                tmp_path / "audit" / "manifest.json",
                identity_root=tmp_path,
            )
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/validate_us_windows_artifact_path_contract.py",
            "--reference",
            str(reference_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "valid"


def test_path_contract_config_keeps_all_execution_safety_flags_false() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert config["durable_relative"]["separator"] == "/"
    assert config["external_absolute"]["stable_identity"] is False
    assert all(value is False for value in config["safety"].values())


@pytest.mark.parametrize(
    ("path", "root"),
    [
        ("C:/other/artifact.json", "C:/repo"),
        ("../artifact.json", "C:/repo"),
        ("/tmp/artifact.json", "/repo"),
    ],
)
def test_durable_path_rejects_escape_or_external_location(path: str, root: str) -> None:
    with pytest.raises(ValueError):
        serialize_durable_artifact_path(path, identity_root=root)
