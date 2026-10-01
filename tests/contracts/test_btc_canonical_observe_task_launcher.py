from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import quant_crypto.application.btc_shared_observation_inputs as consumer
import scripts.run_btc_canonical_observe_task as launcher
from scripts.bootstrap_btc_runtime_artifact_root import (
    bootstrap_btc_runtime_artifact_root,
)
from scripts.run_btc_canonical_observe_task import (
    APPROVED_GIT_EXECUTABLE,
    APPROVED_GIT_EXECUTABLE_SHA256,
    BTCCanonicalObserveTaskError,
    LaunchRequest,
    PROTECTED_SOURCE_PATHS,
    run_btc_canonical_observe_task,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LauncherFixture:
    repo: Path
    head: str
    runtime_root: Path
    candidate_root: Path
    shared_root: Path
    retired_root: Path
    public_spec: str
    l2_spec: str
    request: LaunchRequest

    @property
    def receipt_path(self) -> Path:
        return (
            self.runtime_root
            / "btc_external_runtime_observe_job"
            / "btc_external_runtime_observe_receipt.json"
        )

    def run(
        self,
        *,
        request: LaunchRequest | None = None,
        environment: dict[str, str] | None = None,
        after_inner_hook=None,
    ) -> dict[str, object]:
        return run_btc_canonical_observe_task(
            request or self.request,
            canonical_main_root=self.repo,
            contract_path=(
                self.repo
                / "config/btc_canonical_observe_task_contract.json"
            ),
            environment={} if environment is None else environment,
            after_inner_hook=after_inner_hook,
        )


def test_canonical_success_fixture_publishes_only_valid_blocked_receipt(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.run()

    assert result["infrastructure_status"] == "success"
    assert result["gate_status"] == "blocked_fail_closed"
    assert result["task_registration_performed"] is False
    assert result["promotion_eligible"] is False
    assert result["paper_or_live_allowed"] is False
    assert all(value is False for value in result["safety"].values())
    receipt = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    assert receipt["source_head"] == fixture.head
    assert receipt["manifest_git_specs"] == {
        "public_swap": fixture.public_spec,
        "l2": fixture.l2_spec,
    }
    assert receipt["all_files_verified"] is True
    assert (
        receipt["inputs"]["public_swap"]["input_classification"]
        == "research_only_input"
    )
    assert (
        receipt["inputs"]["l2"]["input_classification"]
        == "blocked_evidence_only"
    )
    assert all(value is False for value in receipt["safety"].values())
    assert _git(fixture.repo, "status", "--porcelain") == ""


def test_wrong_registered_main_worktree_and_detached_main_fail_closed(
    tmp_path: Path,
) -> None:
    wrong_fixture = _fixture(tmp_path / "wrong")
    wrong_worktree = tmp_path / "wrong-worktree"
    _git(
        wrong_fixture.repo,
        "worktree",
        "add",
        "-b",
        "fixture/wrong",
        str(wrong_worktree),
    )
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_main_worktree_path_mismatch",
    ):
        run_btc_canonical_observe_task(
            wrong_fixture.request,
            canonical_main_root=wrong_worktree.resolve(),
            contract_path=(
                wrong_fixture.repo
                / "config/btc_canonical_observe_task_contract.json"
            ),
            environment={},
        )
    assert not wrong_fixture.receipt_path.exists()

    detached_fixture = _fixture(tmp_path / "detached")
    _git(detached_fixture.repo, "checkout", "--detach")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_main_worktree_not_unique",
    ):
        detached_fixture.run()
    assert not detached_fixture.receipt_path.exists()


def test_wrong_expected_head_dirty_source_and_main_drift_preserve_receipt(
    tmp_path: Path,
) -> None:
    wrong_head = _fixture(tmp_path / "wrong-head")
    _seed_final_receipt(wrong_head, b"existing-wrong-head\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_main_binding_mismatch",
    ):
        wrong_head.run(
            request=replace(
                wrong_head.request,
                expected_main_head="0" * 40,
            )
        )
    assert wrong_head.receipt_path.read_bytes() == b"existing-wrong-head\n"

    dirty = _fixture(tmp_path / "dirty")
    _seed_final_receipt(dirty, b"existing-dirty\n")
    (
        dirty.repo
        / "quant_crypto/application/btc_shared_observation_inputs.py"
    ).write_text("# dirty\n", encoding="utf-8")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_protected_source_dirty",
    ):
        dirty.run()
    assert dirty.receipt_path.read_bytes() == b"existing-dirty\n"

    drift = _fixture(tmp_path / "drift")
    _seed_final_receipt(drift, b"existing-drift\n")

    def move_main() -> None:
        _git(drift.repo, "commit", "--allow-empty", "-m", "main drift")

    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_main_binding_mismatch",
    ):
        drift.run(after_inner_hook=move_main)
    assert drift.receipt_path.read_bytes() == b"existing-drift\n"


@pytest.mark.parametrize(
    "bad_spec",
    [
        "HEAD:.agent/data_manifests/public.json",
        "main:.agent/data_manifests/public.json",
        "0" * 12 + ":.agent/data_manifests/public.json",
        "0" * 40 + ":.agent/data_manifests/public/latest.json",
        "0" * 40 + r":.agent\data_manifests\public.json",
    ],
)
def test_implicit_or_unpinned_manifest_specs_fail_closed(
    tmp_path: Path,
    bad_spec: str,
) -> None:
    fixture = _fixture(tmp_path)
    _seed_final_receipt(fixture, b"existing-pins\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_manifest_git_spec_invalid",
    ):
        fixture.run(
            request=replace(
                fixture.request,
                public_swap_manifest_git_spec=bad_spec,
            )
        )
    assert fixture.receipt_path.read_bytes() == b"existing-pins\n"


def test_receipt_pin_mismatch_fails_without_overwriting_final(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, inner_mode="wrong_pins")
    _seed_final_receipt(fixture, b"existing-pin-mismatch\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_receipt_pins_mismatch",
    ):
        fixture.run()
    assert (
        fixture.receipt_path.read_bytes()
        == b"existing-pin-mismatch\n"
    )


def test_owner_reparse_overlap_and_retired_root_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _fixture(tmp_path / "owner")
    _seed_final_receipt(owner, b"existing-owner\n")
    invalid_candidate = tmp_path / "owner" / "invalid-candidate"
    invalid_candidate.mkdir()
    (invalid_candidate / "btc_external_runtime_observe_job").mkdir()
    with pytest.raises(Exception, match="owner_marker_missing"):
        owner.run(
            request=replace(
                owner.request,
                candidate_runtime_root=invalid_candidate.resolve(),
            )
        )
    assert owner.receipt_path.read_bytes() == b"existing-owner\n"

    reparse = _fixture(tmp_path / "reparse")
    _seed_final_receipt(reparse, b"existing-reparse\n")
    original = launcher._is_reparse_point
    candidate = reparse.candidate_root
    monkeypatch.setattr(
        launcher,
        "_is_reparse_point",
        lambda path: (
            launcher._normalized(path) == launcher._normalized(candidate)
            or original(path)
        ),
    )
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_reparse_path_rejected",
    ):
        reparse.run()
    assert reparse.receipt_path.read_bytes() == b"existing-reparse\n"
    monkeypatch.setattr(launcher, "_is_reparse_point", original)

    overlap = _fixture(tmp_path / "overlap")
    _seed_final_receipt(overlap, b"existing-overlap\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_runtime_root_overlap",
    ):
        overlap.run(
            request=replace(
                overlap.request,
                runtime_root=overlap.shared_root,
            )
        )
    assert overlap.receipt_path.read_bytes() == b"existing-overlap\n"

    retired = _fixture(tmp_path / "retired")
    _seed_final_receipt(retired, b"existing-retired\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_runtime_root_overlap",
    ):
        retired.run(
            request=replace(
                retired.request,
                retired_runtime_root=retired.runtime_root,
            )
        )
    assert retired.receipt_path.read_bytes() == b"existing-retired\n"


@pytest.mark.parametrize(
    "inner_mode,expected_error",
    [
        ("exit_zero", "btc_canonical_observe_inner_exit_invalid"),
        ("invalid_receipt", "btc_canonical_observe_inner_receipt_invalid"),
        (
            "unverified_receipt",
            "btc_canonical_observe_receipt_files_not_verified",
        ),
    ],
)
def test_inner_failures_never_overwrite_existing_receipt(
    tmp_path: Path,
    inner_mode: str,
    expected_error: str,
) -> None:
    fixture = _fixture(tmp_path, inner_mode=inner_mode)
    original = f"existing-{inner_mode}\n".encode()
    _seed_final_receipt(fixture, original)
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match=expected_error,
    ):
        fixture.run()
    assert fixture.receipt_path.read_bytes() == original


@pytest.mark.parametrize(
    "environment",
    [
        {"OKX_API_KEY": "must-not-be-read"},
        {"HTTPS_PROXY": "http://proxy.invalid"},
        {"BROKER_TOKEN": "must-not-be-read"},
        {"PAPER_ORDER_MODE": "forbidden"},
    ],
)
def test_secret_proxy_broker_and_paper_order_environment_is_rejected(
    tmp_path: Path,
    environment: dict[str, str],
) -> None:
    fixture = _fixture(tmp_path)
    _seed_final_receipt(fixture, b"existing-env\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_canonical_observe_forbidden_environment_present",
    ):
        fixture.run(environment=environment)
    assert fixture.receipt_path.read_bytes() == b"existing-env\n"


def test_absolute_git_binding_ignores_absent_path_and_cwd_decoy(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    (fixture.repo / "git.exe").write_bytes(b"cwd-decoy-must-not-run")

    result = fixture.run(environment={"PATH": "Z:\\absent"})

    assert result["infrastructure_status"] == "success"
    assert result["gate_status"] == "blocked_fail_closed"


@pytest.mark.parametrize(
    ("git_path", "git_sha256", "expected_error"),
    [
        (
            Path("git.exe"),
            APPROVED_GIT_EXECUTABLE_SHA256,
            "btc_observe_git_executable_must_be_absolute",
        ),
        (
            Path(sys.executable).resolve(),
            APPROVED_GIT_EXECUTABLE_SHA256,
            "btc_observe_git_executable_invalid",
        ),
        (
            APPROVED_GIT_EXECUTABLE,
            "0" * 64,
            "btc_observe_git_executable_sha256_not_approved",
        ),
    ],
)
def test_git_path_and_hash_substitution_fail_closed(
    tmp_path: Path,
    git_path: Path,
    git_sha256: str,
    expected_error: str,
) -> None:
    fixture = _fixture(tmp_path)
    _seed_final_receipt(fixture, b"existing-git-binding\n")
    with pytest.raises(BTCCanonicalObserveTaskError, match=expected_error):
        fixture.run(
            request=replace(
                fixture.request,
                git_path=git_path,
                expected_git_sha256=git_sha256,
            )
        )
    assert fixture.receipt_path.read_bytes() == b"existing-git-binding\n"


def test_git_hash_drift_after_candidate_preserves_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    _seed_final_receipt(fixture, b"existing-git-drift\n")
    original = launcher._validate_git_path
    drifted = False

    def validate(path: Path, *, expected_sha256: str) -> Path:
        if drifted:
            raise BTCCanonicalObserveTaskError(
                "btc_observe_git_executable_sha256_mismatch"
            )
        return original(path, expected_sha256=expected_sha256)

    def drift() -> None:
        nonlocal drifted
        drifted = True

    monkeypatch.setattr(launcher, "_validate_git_path", validate)
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_observe_git_executable_sha256_mismatch",
    ):
        fixture.run(after_inner_hook=drift)
    assert fixture.receipt_path.read_bytes() == b"existing-git-drift\n"


def test_missing_and_reparse_git_paths_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = _fixture(tmp_path / "missing")
    _seed_final_receipt(missing, b"existing-missing-git\n")
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_observe_git_executable_invalid",
    ):
        missing.run(
            request=replace(
                missing.request,
                git_path=(tmp_path / "missing" / "git.exe").resolve(),
            )
        )
    assert missing.receipt_path.read_bytes() == b"existing-missing-git\n"

    reparse = _fixture(tmp_path / "reparse")
    _seed_final_receipt(reparse, b"existing-reparse-git\n")

    def reject(_path: Path) -> None:
        raise consumer.BTCSharedObservationInputsError(
            "btc_observe_git_executable_reparse_rejected"
        )

    monkeypatch.setattr(consumer, "_reject_reparse_chain", reject)
    with pytest.raises(
        BTCCanonicalObserveTaskError,
        match="btc_observe_git_executable_reparse_rejected",
    ):
        reparse.run()
    assert reparse.receipt_path.read_bytes() == b"existing-reparse-git\n"


def test_contract_is_disabled_single_action_design_and_no_registration(
    tmp_path: Path,
) -> None:
    contract = json.loads(
        (
            REPO_ROOT / "config/btc_canonical_observe_task_contract.json"
        ).read_text(encoding="utf-8")
    )
    schema = json.loads(
        (
            REPO_ROOT
            / "schemas/btc_canonical_observe_task_contract.schema.json"
        ).read_text(encoding="utf-8")
    )
    task = contract["task_design"]
    assert task == {
        "task_path": "\\QuantSystem\\BTC\\",
        "task_name": "Quant_BTC_Canonical_Observe_Only",
        "enabled": False,
        "registration_allowed": False,
        "action_count": 1,
        "trigger_count": 1,
        "execution_policy_bypass": False,
        "working_directory": (
            "D:\\vibe coding\\Obsidian\\量化系统\\agent-"
        ),
    }
    assert schema["properties"]["task_design"]["properties"][
        "enabled"
    ] == {"const": False}
    assert contract["git_contract"] == {
        "executable": str(APPROVED_GIT_EXECUTABLE),
        "sha256": APPROVED_GIT_EXECUTABLE_SHA256,
        "path_lookup_allowed": False,
    }
    ps1 = (
        REPO_ROOT / "scripts/run_btc_canonical_observe_task.ps1"
    ).read_text(encoding="utf-8")
    lowered = ps1.casefold()
    assert "register-scheduledtask" not in lowered
    assert "invoke-btcresearchjob.ps1".casefold() not in lowered
    assert "executionpolicy" not in lowered
    assert ps1.count("& $PythonPath $corePath") == 1

    powershell = shutil.which("powershell.exe")
    if powershell:
        escaped = str(
            REPO_ROOT / "scripts/run_btc_canonical_observe_task.ps1"
        ).replace("'", "''")
        parsed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                (
                    "$text=Get-Content -Raw -LiteralPath "
                    f"'{escaped}';"
                    "[void][ScriptBlock]::Create($text)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert parsed.returncode == 0, parsed.stderr


def test_core_help_has_only_explicit_machine_and_pinned_arguments() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_btc_canonical_observe_task.py",
            "--help",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    for option in (
        "--expected-main-head",
        "--python-path",
        "--git-path",
        "--expected-git-sha256",
        "--runtime-root",
        "--candidate-runtime-root",
        "--shared-root",
        "--retired-runtime-root",
        "--public-swap-manifest-git-spec",
        "--l2-manifest-git-spec",
        "--launcher-path",
        "--core-path",
    ):
        assert option in result.stdout
    assert "--bootstrap" not in result.stdout
    assert "--latest" not in result.stdout


def _fixture(
    tmp_path: Path,
    *,
    inner_mode: str = "valid",
) -> LauncherFixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")

    for relative in PROTECTED_SOURCE_PATHS:
        target = repo.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        source = REPO_ROOT.joinpath(*relative.split("/"))
        if relative == "scripts/run_btc_external_runtime_observe_job.py":
            target.write_text(
                _fake_inner_source(inner_mode),
                encoding="utf-8",
            )
        elif relative in {
            "quant_crypto/application/btc_shared_observation_inputs.py",
            "quant_crypto/adapters/btc_runtime_artifact_store.py",
        }:
            target.write_text(
                f'"""fixture committed source: {relative}."""\n',
                encoding="utf-8",
            )
        elif relative == (
            "config/btc_canonical_observe_task_contract.json"
        ):
            contract = json.loads(source.read_text(encoding="utf-8"))
            contract["canonical_main_root"] = str(repo.resolve())
            contract["task_design"]["working_directory"] = str(
                repo.resolve()
            )
            target.write_text(
                json.dumps(contract, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            target.write_bytes(source.read_bytes())

    public_path = ".agent/data_manifests/public/public.json"
    l2_path = ".agent/data_manifests/l2/l2.json"
    for relative in (public_path, l2_path):
        target = repo.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "canonical fixture")
    head = _git(repo, "rev-parse", "HEAD")

    runtime_root = tmp_path / "runtime"
    candidate_root = tmp_path / "candidate"
    for root in (runtime_root, candidate_root):
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=repo.resolve(),
            artifact_root=root.resolve(),
        )
        (root / "btc_external_runtime_observe_job").mkdir()
    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    retired_root = tmp_path / "retired"
    retired_root.mkdir()

    public_spec = f"{head}:{public_path}"
    l2_spec = f"{head}:{l2_path}"
    request = LaunchRequest(
        expected_main_head=head,
        python_path=Path(sys.executable).resolve(),
        git_path=APPROVED_GIT_EXECUTABLE,
        expected_git_sha256=APPROVED_GIT_EXECUTABLE_SHA256,
        runtime_root=runtime_root.resolve(),
        candidate_runtime_root=candidate_root.resolve(),
        shared_root=shared_root.resolve(),
        retired_runtime_root=retired_root.resolve(),
        public_swap_manifest_git_spec=public_spec,
        l2_manifest_git_spec=l2_spec,
        launcher_path=(
            repo / "scripts/run_btc_canonical_observe_task.ps1"
        ).resolve(),
        core_path=(
            repo / "scripts/run_btc_canonical_observe_task.py"
        ).resolve(),
    )
    return LauncherFixture(
        repo=repo.resolve(),
        head=head,
        runtime_root=runtime_root.resolve(),
        candidate_root=candidate_root.resolve(),
        shared_root=shared_root.resolve(),
        retired_root=retired_root.resolve(),
        public_spec=public_spec,
        l2_spec=l2_spec,
        request=request,
    )


def _fake_inner_source(mode: str) -> str:
    return f'''#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import subprocess

MODE = {mode!r}
parser = argparse.ArgumentParser()
parser.add_argument("--repo-root", required=True)
parser.add_argument("--shared-root", required=True)
parser.add_argument("--public-swap-manifest-git-spec", required=True)
parser.add_argument("--l2-manifest-git-spec", required=True)
parser.add_argument("--expected-source-head", required=True)
parser.add_argument("--repository-identity", required=True)
parser.add_argument("--worktree-root", action="append", required=True)
parser.add_argument("--git-executable", required=True)
parser.add_argument("--git-executable-sha256", required=True)
args = parser.parse_args()
if set(os.environ) != {{
    "QS_BTC_RUNTIME_ARTIFACT_ROOT",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONUTF8",
    "GIT_TERMINAL_PROMPT",
}}:
    raise SystemExit(91)
head = subprocess.run(
    [args.git_executable, "rev-parse", "HEAD"],
    cwd=args.repo_root,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
if head != args.expected_source_head:
    raise SystemExit(92)
safety = {{
    "network_accessed": False,
    "publish_attempted": False,
    "micro_live_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "private_endpoint_allowed": False,
    "order_endpoint_allowed": False,
    "broker_calls_allowed": False,
    "oms_calls_allowed": False,
    "real_order_submitted": False,
    "secret_accessed": False,
    "repo_write_allowed": False,
    "shared_data_write_allowed": False,
}}
pins = {{
    "public_swap": args.public_swap_manifest_git_spec,
    "l2": args.l2_manifest_git_spec,
}}
if MODE == "wrong_pins":
    pins["l2"] = "0" * 40 + ":.agent/data_manifests/l2/wrong.json"
receipt = {{
    "schema_version": "btc_external_runtime_observe_receipt_v1",
    "receipt_version": 1,
    "generated_at": "2026-07-27T00:00:00Z",
    "source_head": head,
    "commit": head[:12],
    "status": (
        "ready" if MODE == "invalid_receipt" else "blocked_fail_closed"
    ),
    "decision": "observe_only_blocked",
    "manifest_git_specs": pins,
    "inputs": {{
        "public_swap": {{
            "status": "resolved_research_only_input",
            "dataset_id": "btc-okx-public-swap-research-bundle",
            "input_classification": "research_only_input",
            "raw_committed_manifest_sha256": "a" * 64,
            "aggregate_sha256": "b" * 64,
            "files_verified": True,
        }},
        "l2": {{
            "status": "resolved_blocked_evidence_only",
            "dataset_id": "btc-okx-timestamp-aligned-public-l2-history",
            "input_classification": "blocked_evidence_only",
            "quality_status": "blocked",
            "raw_committed_manifest_sha256": "c" * 64,
            "aggregate_sha256": "d" * 64,
            "files_verified": True,
            "source_receipt": {{
                "blocked_evidence_only": True,
                "data_samples_accepted": False,
            }},
        }},
    }},
    "input_errors": [],
    "preserved_input_blockers": ["l2_missing"],
    "preserved_known_gaps": ["history_zero_days"],
    "all_files_verified": MODE != "unverified_receipt",
    "consumer_read_only": True,
    "blockers": ["observe_only_blocked"],
    "safety": safety,
}}
target = (
    Path(os.environ["QS_BTC_RUNTIME_ARTIFACT_ROOT"])
    / "btc_external_runtime_observe_job"
    / "btc_external_runtime_observe_receipt.json"
)
target.write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\\n",
    encoding="utf-8",
)
raise SystemExit(0 if MODE == "exit_zero" else 2)
'''


def _seed_final_receipt(
    fixture: LauncherFixture,
    content: bytes,
) -> None:
    fixture.receipt_path.write_bytes(content)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
