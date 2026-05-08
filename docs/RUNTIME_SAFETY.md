# Runtime Safety Architecture

## Mode Boundaries

| Mode | Real Orders | Live Endpoint | ReadOnlyBroker | Paper Orders |
|------|-------------|---------------|----------------|--------------|
| PAPER | Blocked | Blocked | N/A | Optional |
| SHADOW_LIVE | **Blocked** (hard) | Read-only only | Required | Optional |
| LIVE | Gated (default blocked) | Allowed | N/A | N/A |

## Shadow Live vs Paper vs Live Boundaries

```
+--------------+    +------------------+    +--------------+
|    PAPER     |    |   SHADOW_LIVE    |    |     LIVE     |
|              |    |                  |    |              |
| o Paper API  |    | o Live API (RO)  |    | o Live API   |
| o Paper ord. |    | o Shadow orders  |    | o Real orders|
| o Real ord.  |    | o Real orders    |    | o Full access|
|   blocked    |    |   BLOCKED        |    | o Gated      |
| o Simulated  |    | o Paper orders   |    | o No paper   |
|   broker ok  |    |   optional       |    |   broker     |
+--------------+    +------------------+    +--------------+
```

## QUANT_LIVE_SUBMISSION_ENABLED Safety

Even when `QUANT_LIVE_SUBMISSION_ENABLED=true`:

1. **RuntimeMode.SHADOW_LIVE.can_submit_real_orders -> False** (hardcoded)
2. **LiveRuntimeConfig.__post_init__** rejects `shadow_live + allow_live_orders`
3. **ReadOnlyLiveBrokerProxy.submit_order()** raises RuntimeError regardless
4. **ShadowOrchestratorConfig.readonly** must be True
5. **ShadowOrder.real_submit** is always False

### Safety Proof Chain
```
QUANT_LIVE_SUBMISSION_ENABLED=true
  -> LiveRuntimeConfig.real_order_submission_enabled checks mode=LIVE
    -> Shadow_live mode does NOT equal LIVE mode
      -> real_order_submission_enabled returns False
        -> No live order path reachable from shadow_live
```

## ReadOnlyBrokerProxy Forbidden Methods

All of these raise `RuntimeError` with audit log:

```python
proxy.submit_order(order)        # RuntimeError
proxy.cancel_order(order_id)     # RuntimeError
proxy.replace_order(id, order)   # RuntimeError
proxy.close_position(symbol)     # RuntimeError
proxy.close_all_positions()      # RuntimeError
```

The `forbidden_call_count` property tracks any attempt to call these methods.
Zero forbidden calls = proof no write was attempted.

## No Real Submit Proof Chain

The audit trail proves no real orders were submitted:

1. **Config level**: `ShadowOrchestratorConfig.readonly = True` (enforced in `__post_init__`)
2. **Runtime mode level**: `RuntimeMode.SHADOW_LIVE.can_submit_real_orders = False`
3. **Config validation**: `LiveRuntimeConfig` rejects `shadow_live + allow_live_orders`
4. **Broker proxy level**: `ReadOnlyLiveBrokerProxy` blocks all write operations
5. **Order model level**: `ShadowOrder.real_submit = False` (always)
6. **Journal level**: Every entry confirms `no_real_order_submitted`
7. **Audit level**: `audit_no_real_submit()` provides cryptographic proof

## Endpoint Guard

```
Paper endpoint:  https://paper-api.alpaca.markets
Live endpoint:   https://api.alpaca.markets

Paper profile  -> MUST use paper endpoint (validated in AlpacaBrokerConfig)
Shadow profile -> CAN use live endpoint (read-only only, via ReadOnlyLiveBrokerProxy)
Live profile   -> MUST use live endpoint (default blocked until gates pass)
```

`AlpacaBrokerConfig.__post_init__` validates URL/paper alignment:
- `paper=True` -> URL must contain `paper-api.alpaca.markets`
- `paper=False` -> URL must contain `api.alpaca.markets`

## G3 Live Pilot Safety (Added Phase G3)

### Approval Gate

Before any live pilot activity:
1. Human approval must exist (created via CLI)
2. Approval status must be APPROVED (explicit human action)
3. Approval must not be expired (7-day validity)
4. Strategy version must match approved version
5. Symbols must be subset of approved symbols

No live pilot activity is possible without a valid, approved, unexpired approval.

### Risk Envelope

Ultra-conservative default limits:
- Max total capital: $1,000
- Max order notional: $100
- Max daily notional: $300
- Max daily orders: 3
- Max gross exposure: 10%
- Market orders: BLOCKED
- Pre/post market: BLOCKED
- Short selling: BLOCKED

### Emergency Stop

States: ARMED -> TRIGGERED -> ACKNOWLEDGED -> RESOLVED

When TRIGGERED:
- New position openings: BLOCKED
- Reduce-only: ALLOWED
- Manual acknowledgement: REQUIRED before resolution

### Dry-Run Proof

LivePilotDryRunExecutor runs 14-step pipeline with ALL real_submit=False.
All LiveOrderDryRunRecords have real_submit=False.
No broker.submit_order() is ever called.

### G3 Safety Invariants

1. Approval gate cannot be bypassed
2. Risk envelope cannot be exceeded (validated at dry-run level)
3. Emergency stop always armed
4. Dry-run never submits real orders
5. Go/No-Go dossier does NOT enable live orders
6. Live profile remains NOT READY even after G3

## G6 Micro Live Pilot Safety (Added Phase G6)

### Second Order Prevention
- SubmitOnceLock prevents unauthorized second order
- Freeze applied after every order
- Second order requires: G5 dossier review + SecondOneShotReviewGate approval
- Episode manager enforces max order count

### Cumulative Risk Controls
- Max cumulative notional: $300 (default)
- Max cumulative loss: $10 (default)
- Max open positions: 1
- Max orders per day: 1
- Each limit violation -> BLOCK_NEW_ORDER or TERMINATE_EPISODE

### No Auto Progression
- All progression gates return recommendations only
- Human must explicitly approve each transition
- No cron job or timer auto-advances phases

### Reduce-Only Safety
- Exit plans always reduce-only
- Quantity never exceeds current position
- Side always opposite of current position
- Default dry-run for all exits

### Episode Termination
- Automatic on: max loss, max orders, emergency stop
- Manual via CLI
- Irreversible (cannot re-open terminated episode)

### Integration Test Safety
- All real-broker tests marked: @pytest.mark.integration_live
- Default pytest excludes integration_live
- Fake broker used for all standard tests

### G6 Safety Invariants

1. SecondOneShotReviewGate must pass before any second order is allowed
2. CumulativeLiveRiskMonitor must return PASS before each new order
3. Episode-level limits (notional, loss, count) are enforced independently of per-order limits
4. Exit plans are always reduce-only and can never increase position size
5. PilotProgressionController produces recommendations only, never auto-advances
6. All exits default to dry-run with no real submission
7. Terminated episodes cannot be re-opened

## G7 Promotion Governance Safety (Added Phase G7)

### No Auto-Promote

G7 promotion governance has no auto-promote path:

1. **PilotScorecardBuilder**: produces a recommendation only (PROMOTE_TO_SUPERVISED_SESSION_REVIEW, BLOCKED, PAUSE). NEVER auto-advances.
2. **PromotionBoard**: all decisions require explicit human action. NO auto-approve path exists.
3. **StrategyPromotionManifestManager**: approve() requires non-empty approved_by. NEVER auto-approves.

### Promotion Board Requirements

- At least one board member must be listed for submission
- Approval requires explicit board_member identification
- Rejection requires a mandatory reason
- Already-approved reviews cannot be re-approved
- All actions are audited to board_audit.jsonl

### Manifest Safety

- Manifests expire after 7 days (MANIFEST_VALIDITY_DAYS)
- is_valid_for_g8() requires all evidence references, APPROVED status, and non-expired
- Expired manifests cannot be approved -- must be re-created
- Manifest manager has no submit_order capability

### Scorecard Safety

- Scorecard builder evaluates episode data only -- no broker interaction
- No scorecard method calls submit_order
- BLOCKED is always returned for any hard condition (duplicate orders, unresolved positions, recon fails)
- PAUSE is always returned for any warning condition (emergency stops, risk breaches, cumulative loss)
- PROMOTE_TO_SUPERVISED_SESSION_REVIEW requires ALL conditions clean

### G7 Safety Invariants

1. PilotScorecardBuilder produces recommendations only, never auto-advances
2. PromotionBoard requires explicit human action for approve/reject
3. StrategyPromotionManifestManager.approve() requires non-empty approved_by
4. Manifests expire after 7 days -- expired manifests cannot be approved
5. No G7 component has submit_order or broker access
6. All board decisions are audited immutably
7. BLOCKED scorecards cannot proceed to board review

## G8 Session Gate Safety (Added Phase G8)

### No Loop Submit

G8 sessions CANNOT loop-submit orders:

1. **Session frozen after each order**: ACTIVE_MANUAL_SUPERVISION -> FROZEN. No submission possible while frozen.
2. **Manual resume required**: FROZEN -> ACTIVE_MANUAL_SUPERVISION requires explicit resume() action.
3. **Daily cap**: max_orders_per_day = 1 prevents second order same day.
4. **Session limits**: max_orders_per_session enforces hard lifetime cap.
5. **SessionGate defaults to BLOCKED**: every condition must explicitly pass.

### One-Shot Reuse

SessionExecutionBridge reuses the G5 OneShotLivePilotExecutor:

- Bridge NEVER creates new submit paths
- Bridge NEVER calls submit_order() or AlpacaBroker directly
- One call to execute_one_shot() = one attempt, then freeze
- No loop, no auto-continue, no retry

### Session Gate Checks (10 Conditions)

The SessionGate checks ALL conditions before allowing an order:

1. Dry run mode -> BLOCKED
2. Missing manual confirm -> BLOCKED
3. Missing promotion -> BLOCKED
4. Promotion not approved -> BLOCKED
5. Session not armed -> BLOCKED
6. Session frozen -> BLOCKED
7. Daily cap exceeded -> BLOCKED
8. Session limits exceeded -> BLOCKED
9. Emergency stop triggered -> BLOCKED
10. Reconciliation dirty -> BLOCKED

### Session Lifecycle Safety

- FROZEN/TERMINATED/COMPLETED sessions cannot submit orders
- TERMINATED is irreversible -- cannot re-open
- COMPLETED is terminal -- no resume possible
- PAUSED requires resume before any activity

### Integration Test Safety

- No real broker calls in G8 tests
- All tests use tmp_path for data isolation
- Fake broker used for any broker interaction
- bridge.can_submit() tested for all status states

### G8 Safety Invariants

1. Session is frozen after every order -- no continuous trading
2. SessionGate defaults to BLOCKED -- all conditions must pass
3. SessionExecutionBridge never calls submit_order directly
4. can_submit() returns False for FROZEN/TERMINATED/COMPLETED
5. Session requires manual resume after freeze
6. Daily caps prevent multiple orders per day
7. Session caps prevent exceeding lifetime limits
8. Each order requires manual_confirm=True

## G9 Ops Safety (Added Phase G9)

### No Auto-Deploy

G9 has no auto-deploy capability:

1. **ReleaseManifestManager.approve()**: requires human approved_by. NEVER triggers deployment.
2. **ReleaseManifestManager.rollback()**: only changes manifest status. Does NOT execute code.
3. **ReadinessChecker.check()**: returns a report only. NEVER triggers deployment.
4. **ConfigIntegrityChecker.check()**: detection only. NEVER auto-fixes drift.

### Backup No-Secrets

BackupRestoreController explicitly excludes:

- `.env` and `.env.*` files
- Files matching `*key*`, `*secret*`, `*credential*`, `*token*` patterns
- API credential files (`api_key*`, `api_secret*`)
- Password files (`*password*`)
- Cache/build artifacts (`__pycache__`, `*.pyc`)

Restore defaults to dry_run=True -- no files extracted without explicit override.

### Config Drift Detection

ConfigIntegrityChecker detects but NEVER fixes:

- Missing config files -> drift reported
- Endpoint mismatch (paper vs live) -> drift reported
- Version mismatch -> drift reported
- Env flag drift (QUANT_LIVE_SUBMISSION_ENABLED) -> drift reported
- Expired approvals -> drift reported
- Release config hash mismatch -> drift reported

Secret values are masked in all output using _mask_secrets().

### Audit Archive Safety

- AuditArchiveBuilder NEVER modifies original audit files
- Read-only collection into versioned archive
- SHA-256 checksum for tamper detection
- Excludes secret-bearing files
- detect_corruption() checks: file existence, size, tar integrity, member validity, checksum

### Deployment Readiness

ReadinessChecker is read-only:
- Checks 7 conditions before declaring READY
- Returns BLOCKED with reasons if any check fails
- NEVER triggers deployment or env changes
- NEVER calls submit_order

### G9 Safety Invariants

1. ReleaseManifestManager.approve() requires human approved_by -- no auto-approve
2. ReleaseManifestManager.rollback() changes status only -- no code execution
3. BackupRestoreController excludes secret files from archives
4. Restore defaults to dry_run=True -- no auto-restore
5. ConfigIntegrityChecker detects drift but never auto-fixes
6. AuditArchiveBuilder never modifies original audit files
7. ReadinessChecker returns report only -- never triggers deployment
8. No G9 component has submit_order or broker access
9. Secret values are masked in all config check output

## R5 Research Automation Safety (Added R-Series)

### Research-to-Live Isolation

Research automation modules are strictly isolated from live execution:

1. **No live imports**: Research modules (`quant_us.research.*`) never import from `quant_us.live` or `quant_us.execution`.
2. **No submit_order**: No research module contains a `submit_order()` method or calls it.
3. **No AlpacaBroker**: Research modules have no reference to `AlpacaBroker` or any broker class.
4. **No QUANT_LIVE**: Research modules do not reference the `QUANT_LIVE` environment variable.
5. **No broker config**: Research modules do not create or reference broker configuration objects.

### Promotion Safety

6. **Max auto-promotion**: The maximum automated promotion level is `PAPER_ELIGIBLE` (a status marker only).
7. **Manual promotion required**: `ResearchAutomationPipeline.step_promote()` requires explicit caller intent. No auto-promote path exists.
8. **Cannot promote past PAPER_ELIGIBLE**: Once a candidate reaches `PAPER_ELIGIBLE`, `step_promote()` raises `ValueError`.
9. **REJECTED is terminal**: Overfit or otherwise rejected candidates cannot be promoted.
10. **No live promotion method**: There is no `promote_to_live()` method anywhere in the research track.

### Overfit Guard

11. **OverfitDetector**: All candidates are checked for overfitting before promotion.
12. **Threshold enforcement**: OOS degradation > 40%, param sensitivity > 0.5, trade count < 10, single-year concentration > 50%, and single-symbol concentration > 60% all trigger rejection.
13. **Cost stress guard**: Sharpe < 0 after 5x costs triggers rejection.

### Lookahead Prevention

14. **No shift(-1)**: Factor computation modules never use `shift(-1)` which would peek into the future.
15. **No bfill in features**: Feature/factor computation modules do not use `bfill` for feature engineering (allowed only in regime detector's expanding percentile calculation, which is past-only).
16. **Time-split enforced**: ML dataset builder always enforces chronological train/validation/test splits.
17. **Rolling windows only**: Regime detection and factor computation use `rolling()` and `expanding()` windows that only access data available at time `t`.

### Portfolio Construction Safety

18. **No orders from portfolio**: Portfolio construction outputs `PortfolioTarget` (allocation weights only), never orders.
19. **No broker in portfolio**: Portfolio construction modules have no broker imports or references.
20. **Portfolio backtest is simulated**: `PortfolioBacktestRunner` combines return series -- it does not submit orders.

### R-Series Safety Invariants

1. Research modules cannot submit real orders
2. Research modules cannot access live brokers
3. Max auto-promotion is PAPER_ELIGIBLE (marker only)
4. Manual action required for all promotions beyond RESEARCH_ONLY
5. Overfit candidates are automatically rejected
6. Lookahead bias is detected and prevented
7. Time-split is enforced in all dataset construction
8. Portfolio construction outputs allocation targets, not orders
9. No research module references QUANT_LIVE environment variable
10. All research tests use tmp_path and fake data -- no real API keys or network calls
