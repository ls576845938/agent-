from __future__ import annotations

import subprocess

from scripts.clone_us_equity_framework_references import REFERENCE_REPOS, clone_reference_repos


def test_reference_clone_script_defaults_to_external_dry_run(tmp_path) -> None:
    results = clone_reference_repos(root=tmp_path / "refs", dry_run=True)

    assert {row["name"] for row in results} == {repo.name for repo in REFERENCE_REPOS}
    assert all(row["status"] == "dry_run" for row in results)
    assert all("git clone --depth" in row["command"] for row in results)
    assert all("codeload.github.com" in row["zip_fallback_command"] for row in results)
    assert not (tmp_path / "refs").exists()


def test_reference_clone_script_covers_required_engine_repos() -> None:
    repo_names = {repo.name for repo in REFERENCE_REPOS}

    assert {"nautilus_trader", "Lean", "zipline-reloaded"} <= repo_names


def test_reference_clone_script_records_failed_clone_and_continues(tmp_path) -> None:
    calls = []

    def fake_runner(command, check):
        calls.append(command)
        if "nautilus_trader" in command[-1]:
            raise subprocess.CalledProcessError(128, command)

    results = clone_reference_repos(root=tmp_path / "refs", dry_run=False, runner=fake_runner)

    statuses = {row["name"]: row["status"] for row in results}
    assert statuses["nautilus_trader"] == "clone_failed"
    assert statuses["Lean"] == "cloned"
    assert statuses["zipline-reloaded"] == "cloned"
    assert len(calls) == len(REFERENCE_REPOS)


def test_reference_clone_script_can_download_zip_after_clone_failure(tmp_path) -> None:
    calls = []

    def fake_runner(command, check):
        calls.append(command)
        if command[0] == "git":
            raise subprocess.CalledProcessError(128, command)

    results = clone_reference_repos(
        root=tmp_path / "refs",
        dry_run=False,
        zip_fallback=True,
        runner=fake_runner,
    )

    assert all(row["status"] == "zip_downloaded_after_clone_failed" for row in results)
    assert all(row["archive"].endswith(".zip") for row in results)
    assert len(calls) == len(REFERENCE_REPOS) * 2
