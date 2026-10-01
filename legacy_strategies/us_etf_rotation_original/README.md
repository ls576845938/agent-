# US ETF Rotation Original Snapshot

This directory is a repository-local snapshot of the user's original ETF
rotation project copied from:

```text
D:/Trading/ETF轮动与数据引擎模块化代码
```

The external source was backed up first with:

```text
python scripts/backup_external_strategy_project.py --repo-root .
```

Latest backup manifest:

```text
artifacts/us_equity_data_status/latest/external_strategy_backup_manifest.json
```

Current role:

- Preserve the original strategy semantics as a legacy reference.
- Let the US equity system import the legacy strategy without depending on an
  external source-code directory.
- Provide a controlled migration path toward normal `quant_us` strategy modules.

Rules:

- Do not edit the external project directly unless a fresh backup manifest is
  generated first.
- If this snapshot is refactored, keep the old behavior covered by parity tests
  before changing strategy semantics.
- This legacy snapshot is not a live or paper trading entry point.
