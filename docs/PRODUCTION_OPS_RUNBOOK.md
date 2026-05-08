# Production Ops Runbook

Step-by-step process for G9 production ops hardening tasks.

## Step 1: Create Backup

Before any operational changes, create a backup:

1. Create backup archive:
   ```
   quant-us backup create
   ```

2. The backup automatically excludes:
   - `.env` files
   - API keys and secrets
   - Credential files
   - `__pycache__` and `.pyc` files

3. Save the backup ID: `backup_id = <output_id>`

4. Verify backup integrity:
   ```
   quant-us backup verify --backup-id <backup_id>
   ```

## Step 2: Check Config Integrity

1. Run config integrity check:
   ```
   quant-us config check
   ```

2. Verify all 8 checks pass:
   - runtime_config_exists: PASS
   - risk_envelope_valid: PASS
   - strategy_versions_consistent: PASS
   - broker_endpoint_correct: PASS
   - env_flags_safe: PASS
   - approval_manifests_valid: PASS
   - promotion_manifests_valid: PASS
   - release_manifest_consistent: PASS

3. If any check FAILS:
   - Review the drift_detected list
   - Fix the underlying issue
   - Re-run the check
   - Secret values will be masked in the output

## Step 3: Create Release Manifest

1. Create a release manifest:
   ```
   quant-us release create
   ```

2. This captures:
   - Current git commit hash
   - SHA-256 hash of all config files
   - SHA-256 hash of risk envelope files

3. Save the release ID: `release_id = <output_id>`

4. Release status: `DRAFT`

## Step 4: Approve Release

1. Human approval:
   ```
   quant-us release approve --release-id <release_id> --by <approver_name>
   ```

2. Release status: `APPROVED`

3. The release manifest is now a point-in-time record of the approved config.

## Step 5: Build Audit Archive

1. Build audit archive:
   ```
   quant-us audit-archive build
   ```

2. This collects all audit trails from:
   - Board audits (G7)
   - Session audits (G8)
   - Session gate audits (G8)
   - Manifest audits (G7)
   - Scorecard files
   - Dossier files

3. Save the archive ID: `archive_id = <output_id>`

4. Verify archive integrity:
   ```
   quant-us audit-archive verify --archive-id <archive_id>
   ```

## Step 6: Check Deployment Readiness

1. Run readiness check:
   ```
   quant-us readiness check
   ```

2. Verify all 7 checks pass:
   - Release exists
   - Release approved
   - Release consistent
   - Config integrity passed
   - No config drift
   - Backup available
   - Audit archive exists

3. Expected result: `status: READY`

## Rollback Procedure

If a release needs to be rolled back:

1. Mark release as rolled back:
   ```
   quant-us release rollback --release-id <release_id> --reason "reason"
   ```

2. This only changes the manifest status. It does NOT execute any code changes.

3. Restore from backup if needed (dry-run first):
   ```
   quant-us backup restore --backup-id <backup_id>          # dry run
   quant-us backup restore --backup-id <backup_id> --force  # actual restore
   ```

## Recovery After Config Drift

1. Detect drift:
   ```
   quant-us config check
   ```

2. Review what changed:
   - Check runtime_config.json
   - Check strategy_config.json
   - Check risk envelope files
   - Check approval expiry dates

3. Fix the drift:
   - Restore correct config files
   - Re-approve expired approvals if needed
   - Create a new release manifest

4. Re-run readiness check:
   ```
   quant-us readiness check
   ```

## Schedule

Recommended operational cadence:

| Task | Frequency | Owner |
|------|-----------|-------|
| Backup | Before any config change | Operator |
| Config integrity check | Weekly | Operator |
| Audit archive | After any session | Operator |
| Release manifest | Before deployment | Lead |
| Readiness check | Before deployment | Lead |
