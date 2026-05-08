# Phase G9: Production Ops Hardening

## What G9 Adds (Release Governance, Not Auto-Deploy)

G9 adds operational hardening around release management, configuration integrity, backup/restore, audit archiving, and deployment readiness checking.

G9 does NOT add:
- Auto-deployment
- Live trading capability
- Continuous operation

G9 adds:
- Release manifest governance (human-approved only)
- Configuration drift detection
- Backup and restore (dry-run default)
- Audit trail archiving with checksum verification
- Deployment readiness checklist

## ReleaseManifest Lifecycle

The `ReleaseManifest` captures a point-in-time snapshot of all operational configuration:

```
DRAFT -> CANDIDATE -> APPROVED (human) -> REJECTED -> ROLLED_BACK
```

### Manifest Contents

| Field | Description |
|-------|-------------|
| `release_id` | Unique release identifier |
| `git_commit` | Current git commit hash |
| `config_hash` | SHA-256 of all config files |
| `risk_envelope_hash` | SHA-256 of risk envelope files |
| `promotion_manifest_ids` | Associated G7 promotion manifests |
| `session_report_ids` | Associated G8 session reports |
| `strategy_versions` | Strategy version mapping |
| `status` | DRAFT -> APPROVED/REJECTED/ROLLED_BACK |

### Rules

- NEVER auto-approves (human `approved_by` required)
- Approve only valid from DRAFT or CANDIDATE status
- Rollback only changes status -- does NOT execute code
- Double rollback raises ValueError

## ConfigIntegrityChecker: What It Checks

The `ConfigIntegrityChecker` runs 8 checks:

| # | Check | What It Validates |
|---|-------|-------------------|
| 1 | Runtime config exists | `runtime_config.json` file exists and is valid JSON |
| 2 | Risk envelope valid | Envelope directory and files exist with valid IDs |
| 3 | Strategy versions | Strategy config is valid JSON if present |
| 4 | Broker endpoint | Endpoint matches expected (paper vs live). Live endpoint detected = drift |
| 5 | Env flags safe | `QUANT_LIVE_SUBMISSION_ENABLED` must be disabled |
| 6 | Approval manifests | Approval files exist, are APPROVED, and not expired |
| 7 | Promotion manifests | Promotion manifest files exist if directory present |
| 8 | Release consistency | Current config hash matches latest release hash |

### Secret Safety

- `_mask_secrets()` masks any secret-like values before returning
- `SECRET_VALUE_PATTERNS` regex identifies API keys, tokens, credentials
- NEVER outputs raw secret values in check results

## BackupRestoreController: What's Included/Excluded

### Included

- All files under `data/live_pilot/` except excluded patterns
- Collected into a versioned `tar.gz` archive
- SHA-256 checksum computed for archive verification

### Excluded

| Pattern | Examples |
|---------|----------|
| `.env` files | `.env`, `.env.production` |
| Key files | `*key*`, `*secret*`, `*credential*`, `*token*` |
| API credentials | `api_key*`, `api_secret*` |
| Password files | `*password*` |
| Cache/build | `__pycache__`, `*.pyc` |
| Git | `.git` |

### Restore Safety

- `restore()` defaults to `dry_run=True`
- Dry-run verifies archive integrity without extracting files
- Actual extraction requires explicit `dry_run=False`

## AuditArchive: Audit Chain of Custody

The `AuditArchiveBuilder` collects all audit trail files across G3-G9:

### Sources

- Board audit (`board_audit.jsonl`)
- Session audit (`session_audit.jsonl`)
- Session gate audit (`session_gate_audit.jsonl`)
- Manifest audit (`manifest_audit.jsonl`)
- Scorecard files
- Dossier files

### Chain of Custody

1. Archive is created with SHA-256 checksum
2. Original audit files are NEVER modified
3. `verify(archive_id)` checks checksum integrity
4. `detect_corruption(archive_id)` checks: file existence, size, tar integrity, member validity, checksum

## DeploymentReadinessCheck: Final Checklist

The `ReadinessChecker` runs 7 checks:

| # | Check | Description |
|---|-------|-------------|
| 1 | Release exists | At least one release manifest exists |
| 2 | Release approved | Latest release is APPROVED |
| 3 | Release consistent | Release has config_hash and approved_by |
| 4 | Config integrity | ConfigIntegrityChecker passes |
| 5 | No config drift | No drift detected in config |
| 6 | Backup available | Backup record exists |
| 7 | Audit archive exists | Audit archive record exists |

Decision: all pass -> READY, any fail -> BLOCKED with reasons.

## CLI Reference

```bash
# Create release manifest
quant-us release create

# Approve release
quant-us release approve --release-id <release_id> --by <name>

# Reject release
quant-us release reject --release-id <release_id> --reason "reason"

# Rollback release
quant-us release rollback --release-id <release_id> --reason "reason"

# List releases
quant-us release list

# Check config integrity
quant-us config check

# Create backup
quant-us backup create

# Restore from backup (dry-run)
quant-us backup restore --backup-id <backup_id>

# Verify backup checksum
quant-us backup verify --backup-id <backup_id>

# Build audit archive
quant-us audit-archive build

# Verify audit archive
quant-us audit-archive verify --archive-id <archive_id>

# Check deployment readiness
quant-us readiness check
```
