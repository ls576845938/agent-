# Phase G6: Micro Live Pilot Expansion

## G5 Completion Status
- FirstLiveOrderTicket: check
- FinalHumanConfirmationGate: check
- OneShotLivePilotExecutor: check
- SubmitOnceLock: check
- PostTradeReconciler: check
- LivePilotFreezeState: check
- ExecutionQualityReport: check
- G5PostTradeDossier: check (always STOP_AND_REVIEW)

## G6 Objectives
1. Second One-Shot Review Gate: review G5 results before allowing second order
2. Micro Pilot Episode Manager: manage up to 3-5 orders under cumulative limits
3. Cumulative Risk Monitor: track aggregate risk across episode
4. Live Position Exit Plan: generate reduce-only exit strategies
5. Reduce-Only Exit Executor: safely execute position exits
6. Pilot Progression Controller: evaluate readiness for G7
7. Micro Pilot Final Dossier: complete episode review

## Allowed in G6
- Second one-shot order (after G5 dossier review)
- Up to 3-5 orders total in a micro episode
- Cumulative risk tracking
- Reduce-only position exits
- Episode management and progression evaluation
- Dry-run execution by default

## Prohibited in G6
- Automatic live trading of any kind
- Continuous/loop trading
- Removing one-shot constraint
- Removing freeze after orders
- Increasing capital beyond micro limits
- Auto-progression to G7
- New strategy development
- IBKR, Redis, WebSocket integration

## Completion Criteria
1. SecondOneShotReviewGate operational
2. MicroPilotEpisodeManager operational
3. CumulativeLiveRiskMonitor operational
4. LivePositionExitPlan operational
5. ReduceOnlyExitExecutor operational
6. PilotProgressionController operational
7. All tests pass: `pytest -q -m "not integration_live"`
8. Default system cannot submit real orders

## G7 Prerequisites
- Successful G6 micro pilot episode (3-5 orders)
- All post-trade reviews clean
- Cumulative risk within limits
- No unresolved incidents
- All positions exited or exit plans ready
- Manual review approved
- PilotProgressionController returns READY_FOR_G7_REVIEW
