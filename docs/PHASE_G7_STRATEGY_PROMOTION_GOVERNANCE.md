# Phase G7: Strategy Promotion Governance

## Overview

G7 defines the governance process for promoting a strategy from G6 (Micro Live Pilot) to G8 (Supervised Micro Live Session). Promotion is NEVER automatic -- it requires a scored evaluation, a human board review, and a signed manifest.

## What G7 Adds on Top of G6

| Capability | G6 | G7 |
|------------|----|----|
| Episode evaluation | Episode complete | Scored and graded |
| Promotion decision | Controller recommendation | Scorecard + Board + Manifest |
| Human governance | Implicit | Explicit (PromotionBoard) |
| Evidence collection | Ephemeral | Versioned manifest |
| G8 readiness | Controller says "ready" | Manifest says "approved" |

## PilotScorecard Rules and Decisions

The `PilotScorecard` evaluates a completed G6 micro pilot episode against hard and soft criteria:

### BLOCKED (Fatal)

Any of these conditions produces `BLOCKED`:

| Condition | Threshold |
|-----------|-----------|
| Duplicate orders | duplicate_order_count > 0 |
| Unresolved positions | unresolved_position_count > 0 |
| Reconciliation failures | recon_fail_count > 0 |
| Unresolved incidents | incident_count > 0 |

### PAUSE (Warning)

These conditions produce `PAUSE`:

| Condition | Threshold |
|-----------|-----------|
| Emergency stop triggered | emergency_stop_count > 0 |
| Risk limit breaches | risk_limit_breach_count > 0 |
| Cumulative loss exceeded | cumulative_pnl < -10.0 |

### PROMOTE_TO_SUPERVISED_SESSION_REVIEW (Pass)

All conditions must be clean: clean_order_count == order_count, zero incidents, zero breaches, zero emergency stops.

## StrategyPromotionManifest Requirements

The `StrategyPromotionManifest` collects all evidence required for promotion:

1. **PilotScorecard ID** -- scorecard from episode evaluation
2. **Dossier ID** -- G6 final dossier from episode review
3. **BoardReview ID** -- PromotionBoard approval record

### Validity

- Manifest expires after 7 days (configurable via `MANIFEST_VALIDITY_DAYS`)
- `is_valid_for_g8()` checks all evidence exists, status is APPROVED, and not expired
- Expired manifests must be re-created and re-approved

### States

```
DRAFT -> PENDING_EVIDENCE -> APPROVED (human) -> (7 days) -> EXPIRED
```

## PromotionBoard Governance Process

The `PromotionBoard` is a human-governed review body:

1. **Submit**: Scorecard is submitted for board review with board member list
2. **Review**: Board members evaluate the scorecard
3. **Approve**: Explicit human action marks as APPROVED_FOR_G8_REVIEW
4. **Reject**: Explicit human action with rejection reason

### Rules

- At least one board member is required for submission
- NO auto-approval path exists
- All decisions are audited to `board_audit.jsonl`
- Approved reviews cannot be re-approved
- Rejected reviews include a mandatory rejection reason

## How G7 Feeds Into G8

```
G6 Episode Complete
       |
       v
PilotScorecardBuilder.build(episode_id)
       |
       v
Scorecard decision (BLOCKED | PAUSE | PROMOTE...)
       |
       v
PromotionBoard.submit_for_review(scorecard_id, board_members)
       |
       v
PromotionBoard.approve(review_id, board_member)  -- HUMAN ONLY
       |
       v
StrategyPromotionManifestManager.create(strategy_id, scorecard_id, dossier_id, board_review_id)
       |
       v
Manifest approved + valid
       |
       v
G8 SessionGate checks promotion manifest as part of gate chain
```

## CLI Reference

```bash
# Build scorecard from episode data
quant-us scorecard build --episode-id <episode_id>

# Load and display a scorecard
quant-us scorecard show --scorecard-id <scorecard_id>

# List all scorecards
quant-us scorecard list

# Submit for board review
quant-us board submit --scorecard-id <scorecard_id> --members alice,bob

# Approve a review
quant-us board approve --review-id <review_id> --member alice

# Reject a review
quant-us board reject --review-id <review_id> --member bob --reason "insufficient_evidence"

# List pending reviews
quant-us board list-pending

# Create promotion manifest
quant-us manifest create --strategy-id <strategy_id> --scorecard-id <sc_id> --dossier-id <dos_id> --board-review-id <br_id>

# Approve manifest
quant-us manifest approve --manifest-id <manifest_id> --by alice

# Check manifest validity for G8
quant-us manifest check --manifest-id <manifest_id>
```
