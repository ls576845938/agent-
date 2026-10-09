# Shared Dataset Manifests

Git stores only manifests and quality evidence here. Dataset payloads are published outside all worktrees under the shared data root.

Default local root:

`<quant-workspace>/shared-data/datasets/<dataset_id>/<dataset_version>/`

`QUANT_SHARED_DATA_ROOT` may override the root. Consumers must resolve the version through its manifest and must not hard-code another agent's worktree path.

Only `data_steward` may publish a dataset version. Versions are immutable; publishing different content under an existing version fails closed. Shared mutable SQLite files are not supported by this contract.

Consumers resolve a manifest committed on another branch without copying it into their worktree:

```powershell
py -3 tools/agent_governance/shared_data.py --repo-root . resolve --manifest-git-spec "agent/data_steward/<task>:.agent/data_manifests/<dataset>/<version>.json"
```
