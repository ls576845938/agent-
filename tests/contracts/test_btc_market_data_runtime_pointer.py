from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
POINTER_PATH = ".agent/runtime_manifests/btc-market-data-v1.json"


def _git_blob(path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
    )


def test_runtime_pointer_manifest_sha_binds_committed_git_blob() -> None:
    pointer = json.loads(_git_blob(POINTER_PATH))
    publication = pointer["immutable_publication"]
    manifest_path = publication["manifest_path"]
    declared_sha = publication["manifest_sha256"]

    assert isinstance(manifest_path, str) and manifest_path.startswith(
        ".agent/data_manifests/"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", declared_sha)
    manifest_blob = _git_blob(manifest_path)
    assert hashlib.sha256(manifest_blob).hexdigest() == declared_sha
