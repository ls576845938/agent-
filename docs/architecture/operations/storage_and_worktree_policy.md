# Storage And Worktree Policy

## Scope

This policy covers local agent worktrees, Git LFS, runtime databases, generated artifacts, and the external shared-data store.

## Worktrees

- Writer agents use `tools/agent_governance/worktree_plan.py`; sparse checkout is the default.
- The repository `post-checkout` hook is a backstop for Codex-managed or manually created linked worktrees that bypass the planner. It applies the union of writer source paths and excludes runtime payloads.
- Default sparse paths include source, tests, governance, configuration, and documentation. They exclude `data/`, `artifacts/`, `mlruns/`, virtual environments, downloads, and generated run directories.
- Every worktree creation process sets `GIT_LFS_SKIP_SMUDGE=1`. LFS objects are fetched only for explicitly selected paths.
- A full checkout is exceptional and requires at least 50 GB free on the target volume.
- A governed full checkout sets `AGENT_ALLOW_FULL_CHECKOUT=1`; without that explicit override, a linked worktree is automatically converted to sparse checkout.
- A worktree can be removed only when it is clean, unlocked, unused by a process or active task, and its branch, HEAD, and committed handoff have been recorded. Removing a worktree never implies deleting its branch.
- Automatic context hooks read branch and HEAD only. They must not run repository-wide status or diff commands.
- Dirty checks use `tools/agent_governance/safe_status.py` with explicit source paths. Runtime payload roots are verified through manifests and hashes, not Git worktree scans.

## Runtime And Immutable Data

- Mutable single-writer databases live under `shared-data/.staging/runtime/`, outside every Git worktree.
- Compatibility links may preserve legacy repository-relative paths while consumers migrate to an explicit resolver.
- Immutable datasets live under `shared-data/datasets/<dataset_id>/<dataset_version>/` and are consumed through a Git-tracked manifest.
- A shared-data manifest records producer commit, schema, coverage, file hashes, size, quality status, gaps, blockers, and fail-closed safety flags.
- Mutable SQLite, WAL, SHM, raw market data, full ledgers, and large report payloads are not promotion evidence merely because they exist in shared storage.

## Git And LFS

- `data/market_data.sqlite`, its WAL, and its SHM files must never be staged again.
- Staged files under `data/` or `artifacts/` larger than 5 MB are rejected. Publish the payload to shared-data and commit only its manifest and a small summary report.
- Existing LFS history is retained until every required object is backed up or pushed. `git lfs prune` is forbidden while unpushed objects remain.
- Historical LFS cleanup requires a separate approved migration; this policy only stops new growth.

## Disk Watermarks

- `< 50 GB`: block full worktree creation; sparse worktrees remain available.
- `< 20 GB`: stop data collection and artifact rebuilds, emit a blocked receipt, and preserve trading safety flags as false.
- Disk probe failure is itself a blocker.

## Promotion Impact

Storage migration, a manifest, or a successful disk check cannot unlock paper or live trading. Current-HEAD evidence, reconciliation, risk, execution, and manual promotion gates remain independent and fail closed.
