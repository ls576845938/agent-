from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agent_governance.safe_status import normalize_scopes, scoped_status, status_paths


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True)


@pytest.mark.parametrize(
    "scope",
    (".", "../outside", "D:/outside", "data", "artifacts/report.json", "mlruns/run"),
)
def test_status_scope_rejects_full_or_runtime_paths(scope: str) -> None:
    with pytest.raises(ValueError):
        normalize_scopes([scope])


def test_default_status_scope_excludes_runtime_payloads(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "agent@example.invalid")
    _git(repo, "config", "user.name", "Agent Test")
    (repo / "quant_us").mkdir()
    (repo / "data").mkdir()
    (repo / "quant_us" / "model.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "data" / "payload.txt").write_text("version 1\n", encoding="utf-8")
    _git(repo, "add", "quant_us/model.py", "data/payload.txt")
    _git(repo, "commit", "-m", "fixture")

    (repo / "quant_us" / "model.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "data" / "payload.txt").write_text("version 2\n", encoding="utf-8")

    paths = status_paths(scoped_status(repo))

    assert paths == ["quant_us/model.py"]


def test_explicit_status_scope_is_bounded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "agent@example.invalid")
    _git(repo, "config", "user.name", "Agent Test")
    (repo / "docs").mkdir()
    (repo / "tests").mkdir()
    (repo / "docs" / "rules.md").write_text("v1\n", encoding="utf-8")
    (repo / "tests" / "test_rule.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "docs/rules.md", "tests/test_rule.py")
    _git(repo, "commit", "-m", "fixture")
    (repo / "docs" / "rules.md").write_text("v2\n", encoding="utf-8")
    (repo / "tests" / "test_rule.py").write_text("VALUE = 2\n", encoding="utf-8")

    paths = status_paths(scoped_status(repo, ["docs"]))

    assert paths == ["docs/rules.md"]


def test_safe_status_cli_runs_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, "tools/agent_governance/safe_status.py", "--path", "AGENTS.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "safe_status_v1"
    assert payload["status"] in {"clean", "dirty"}
    assert payload["scopes"] == ["AGENTS.md"]
