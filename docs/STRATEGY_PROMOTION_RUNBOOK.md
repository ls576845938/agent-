# Strategy Promotion Runbook

Step-by-step process for promoting a strategy from G6 Micro Pilot to G8 Supervised Micro Live Session.

## Prerequisites

- G6 micro pilot episode completed (3-5 orders)
- All post-trade reviews clean
- Cumulative risk within limits
- No unresolved incidents
- Positions exited or exit plans ready
- PilotProgressionController returns READY_FOR_G7_REVIEW

## Step 1: G6 Final Dossier Review

1. Generate the G6 final dossier:
   ```
   quant-us dossier build --episode-id <episode_id>
   ```

2. Review the dossier output:
   - Order reviews: all orders traced, no duplicates
   - Risk review: cumulative limits respected
   - Exit review: all positions resolved or exit plans documented
   - Decision: should be READY_FOR_G7_REVIEW or CONTINUE_PAPER

3. If decision is not READY_FOR_G7_REVIEW:
   - Investigate blocked reasons
   - Fix issues in a new episode
   - Re-run dossier generation

## Step 2: Build PilotScorecard

1. Build the scorecard:
   ```
   quant-us scorecard build --episode-id <episode_id>
   ```

2. Verify the scorecard decision:
   - `PROMOTE_TO_SUPERVISED_SESSION_REVIEW`: Continue to Step 3
   - `BLOCKED`: Investigate hard blocks (duplicate orders, unresolved positions, recon failures, incidents)
   - `PAUSE`: Investigate warnings (emergency stops, risk breaches, cumulative loss)

3. Save the scorecard ID: `scorecard_id = <output_id>`

## Step 3: Promotion Board Review

1. Submit for board review:
   ```
   quant-us board submit --scorecard-id <scorecard_id> --members alice,bob
   ```
   This requires at least one named board member.

2. Board members review the scorecard:
   - Review episode metrics and scorecard details
   - Evaluate decision reasons
   - Discuss any concerns

3. Board approval:
   ```
   quant-us board approve --review-id <review_id> --member <member_name>
   ```

4. If board rejects:
   ```
   quant-us board reject --review-id <review_id> --member <member_name> --reason "reason"
   ```
   - Address rejection reasons
   - Return to Step 2 (rebuild scorecard)

## Step 4: Create Strategy Promotion Manifest

1. Create the manifest referencing all evidence:
   ```
   quant-us manifest create \
     --strategy-id <strategy_id> \
     --scorecard-id <scorecard_id> \
     --dossier-id <dossier_id> \
     --board-review-id <board_review_id>
   ```

2. Save the manifest ID: `manifest_id = <output_id>`

## Step 5: Approve Manifest

1. Human approval:
   ```
   quant-us manifest approve --manifest-id <manifest_id> --by <approver_name>
   ```

2. Verify manifest validity:
   ```
   quant-us manifest check --manifest-id <manifest_id>
   ```
   Expected: `is_valid_for_g8=True`

## Step 6: Ready for G8

The approved manifest is now ready for G8 session creation.

1. Record the manifest ID for G8 session creation
2. The SessionGate will verify the manifest as part of its gate chain

## Troubleshooting

| Issue | Likely Cause | Resolution |
|-------|-------------|------------|
| Scorecard BLOCKED | Hard block condition | Check duplicate orders, positions, recon |
| Scorecard PAUSE | Warning condition | Check emergency stops, risk, P&L |
| Board review cannot approve | Review already decided | Create new submission |
| Manifest invalid for G8 | Missing evidence or expired | Ensure all IDs present, re-approve if expired |
| Manifest expired | >7 days since creation | Create new manifest, re-run board review if needed |
