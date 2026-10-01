# G6 Micro Pilot Risk Architecture

## Overview
G6 extends G5's single-order safety model with cumulative risk controls,
episode management, and explicit progression gating.

## Architecture Diagram (ASCII)

```
┌─────────────────────────────────────────────────┐
│               G5 Post-Trade Dossier              │
│         (STOP_AND_REVIEW after first order)      │
└────────────────────┬────────────────────────────┘
                     │ human reviews dossier
                     ▼
┌─────────────────────────────────────────────────┐
│         SecondOneShotReviewGate                  │
│  Checks: dossier, execution quality, recon,      │
│  freeze, lock, incidents, manual decision        │
│  Decision: APPROVED | BLOCKED | MORE_REVIEW       │
└────────────────────┬────────────────────────────┘
                     │ APPROVED_FOR_SECOND_ONE_SHOT_REVIEW
                     ▼
┌─────────────────────────────────────────────────┐
│         MicroPilotEpisodeManager                 │
│  Limits: max 3-5 orders, $300 notional, $10 loss │
│  Each order: separate ticket, approval, freeze   │
│  Status: DRAFT->ACTIVE->WAITING->FROZEN->TERMINATED │
└────────────────────┬────────────────────────────┘
                     │                    │
          ┌──────────┘                    └──────────┐
          ▼                                         ▼
┌──────────────────────┐              ┌──────────────────────────┐
│ CumulativeRiskMonitor│              │  LivePositionExitPlan     │
│ o Notional tracking  │              │  o Reduce-only always     │
│ o P&L tracking       │              │  o Never increase position│
│ o Position count     │              │  o Manual approval req'd  │
│ o Daily order limit  │              │  o Dry-run default        │
│ o Incident tracking  │              └──────────────────────────┘
│ Status: PASS|WARN|   │
│ BLOCK|TERMINATE|     │
│ REDUCE_ONLY          │
└──────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────┐
│         PilotProgressionController               │
│  Checks: all orders traceable, no duplicates,     │
│  no unresolved incidents, recon clean,           │
│  risk PASS, emergency stop tested                │
│  Result: READY_FOR_G7_REVIEW (recommendation)    │
│  NEVER auto-advances                             │
└─────────────────────────────────────────────────┘
```

## Component Details

### SecondOneShotReviewGate
- Purpose: Gate between G5 and G6
- Input: G5 dossier, execution quality, manual review decision
- Output: APPROVED_FOR_SECOND_ONE_SHOT_REVIEW | BLOCKED | REQUIRES_MORE_REVIEW
- Block reasons: 12 distinct reasons (missing_dossier, recon_not_clean, etc.)

### MicroPilotEpisodeManager
- Purpose: Manage multi-order episode state
- Episode limits: max_order_count=3, max_notional=$300, max_loss=$10
- Each order: separate one-shot with full gate chain
- Status machine: DRAFT -> ACTIVE_REVIEW_ONLY -> WAITING_NEXT_ONE_SHOT_REVIEW -> FROZEN_AFTER_ORDER -> TERMINATED/COMPLETED

### CumulativeLiveRiskMonitor
- Purpose: Track cumulative risk across episode
- Rule set: notional limit, loss limit, position count, daily count, incidents
- Decision: PASS | WARN | BLOCK_NEW_ORDER | TERMINATE_EPISODE | REDUCE_ONLY_REQUIRED

### LivePositionExitPlan
- Purpose: Generate exit strategy for open positions
- Core invariant: reduce_only=TRUE, never increase position
- Status: DRAFT -> READY_FOR_REVIEW -> APPROVED -> EXECUTED -> CANCELED

### ReduceOnlyExitExecutor
- Purpose: Execute position exit with safety checks
- Default: dry-run (no submission)
- Checks: reduce_only verified, position not increased, manual approval, env gate
- Only fake broker in tests can actually "submit"

### PilotProgressionController
- Purpose: Evaluate readiness for next phase
- Checks all criteria but NEVER auto-advances
- Output: recommendation only (READY_FOR_G7_REVIEW or BLOCKED)

## Safety Invariants
1. No automatic live orders - every order requires explicit human action
2. No continuous trading - each order is a one-shot with freeze
3. Reduce-only exits - can never increase position size
4. Cumulative limits - per-order safety + episode-level limits
5. Manual review at every step - no auto-progression
6. Default dry-run - all execution defaults to simulation
