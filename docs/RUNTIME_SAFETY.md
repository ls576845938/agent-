# Runtime Safety Architecture

## Mode Boundaries

| Mode | Real Orders | Live Endpoint | ReadOnlyBroker | Paper Orders |
|------|-------------|---------------|----------------|--------------|
| PAPER | Blocked | Blocked | N/A | Simulated only by default; explicit paper submit path required |
| SHADOW_LIVE | **Blocked** (hard) | Read-only only | Required | Optional simulated/audit evidence only |
| LIVE | **Blocked** in `LiveRuntime` safety shell | Review-only endpoint checks | N/A | N/A |

`LiveRuntime` is currently a safety shell. Live-mode readiness evidence can pass, but that evidence is
review material only and does not unlock order submission in this runtime boundary.
The `live start` operator path is review-only and fail-closed: it may render gate/evidence state, but it must not submit orders.
Any future executable live path must be introduced as a separate, explicit implementation with its own approved gate.
Readiness, report, and paper runtime gates in this baseline consume the saved Evidence Registry as source of truth. They do not implicitly rebuild it. Missing, `STALE`, or `CONFLICT` registry state must fail closed.
CLI reports may display subject index bucket counts, paper session manifests, startup sync artifacts, and ledger reconciliation artifacts.
Those files are persisted evidence and audit inputs only; displaying them does not grant execution authorization.

## Shadow Live vs Paper vs Live Boundaries

```
+--------------+    +------------------+    +--------------+
|    PAPER     |    |   SHADOW_LIVE    |    |     LIVE     |
|              |    |                  |    |              |
| o Paper API  |    | o Live API (RO)  |    | o Live API   |
| o Paper ord. |    | o Shadow orders  |    | o Review only|
| o Real ord.  |    | o Real orders    |    | o No submit  |
|   blocked    |    |   BLOCKED        |    |   BLOCKED    |
| o Simulated  |    | o Paper orders   |    | o No paper   |
|   broker ok  |    |   evidence only  |    |   broker     |
+--------------+    +------------------+    +--------------+
```

## Paper Submission Boundary

Paper order submission is off by default. Simulated paper artifacts and paper-review approvals are evidence for review;
they are not broker-write authorization. A real paper path must be selected explicitly and must remain separate from
research promotion, readiness, and report commands.

Current baseline expectations:

- `paper_broker=alpaca` remains fail-closed unless a separately approved adapter path is explicitly wired.
- Fake Alpaca adapters are contract-test tools only and are not production paper execution.
- Daily paper reports read persisted ledger evidence; they do not imply that paper orders were submitted.
- Startup sync artifacts are audit inputs only and do not enable paper or live writes.
- Paper session manifests record session intent, registry evidence, startup sync status, and no-submit proof; they are not an executable order path.
- Ledger reconciliation artifacts summarize fills, hashes, duplicate/conflict fill counts, and ledger PnL for review only.
- `paper_review_index` is a legacy view only; it is not the authority for runtime gating.
- `review.json` alone cannot start paper runtime. The registry must be rebuilt explicitly, then the saved registry is consumed by readiness/report/runtime gates.

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

Paper profile  -> MUST use paper endpoint when an actual, explicit paper submit adapter is wired
Shadow profile -> CAN use live endpoint (read-only only, via ReadOnlyLiveBrokerProxy)
Live profile   -> MAY inspect live endpoint state, but current LiveRuntime remains review-only and fail-closed
```

`AlpacaBrokerConfig.__post_init__` validates URL/paper alignment:
- `paper=True` -> URL must contain `paper-api.alpaca.markets`
- `paper=False` -> URL must contain `api.alpaca.markets`

## Ledger Idempotency Boundary

Ledger writes must be idempotent under repeated report/runtime invocations. If the runtime path writes ledger-derived
artifacts, it must either use a file lock around the write or document why the artifact is single-writer and safe to
rebuild. Reports that only read existing ledger files must preserve this distinction and should not claim locking for
paths that are not implemented yet.
This idempotency rule does not imply automatic registry rebuild. Registry rebuilds, when required, must be explicit.

## G3 Live Pilot Safety (Added Phase G3)

The live-pilot and micro-live sections below describe guard rails, not the baseline automation in this turn.
They remain manual-approval flows and are not part of the current automated closed loop.

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

6. **No PAPER_ELIGIBLE auto-promotion**: Automated research can only produce a `paper_review_ready` evidence result; `PAPER_ELIGIBLE` remains manual.
7. **Manual promotion required**: `ResearchAutomationPipeline.step_promote()` requires canonical gate approval plus approved paper review or explicit `manual_approval=True`. No auto-promote path exists.
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
3. Automated output stops at paper_review_ready evidence; PAPER_ELIGIBLE is manual
4. Manual action required for all promotions beyond RESEARCH_ONLY
5. Overfit candidates are automatically rejected
6. Lookahead bias is detected and prevented
7. Time-split is enforced in all dataset construction
8. Portfolio construction outputs allocation targets, not orders
9. No research module references QUANT_LIVE environment variable
10. All research tests use tmp_path and fake data -- no real API keys or network calls

## R2 Research Engine Hardening Safety (Added Phase R2)

### Manifest Reproducibility

Every experiment manifest contains full reproducibility metadata:
- Strategy version, data version, feature version
- Parameters and parameter grid
- Deterministic config hash for duplicate detection
- Archive support for experiment preservation

Manifests are validated for presence before any promotion gate check.

### Candidate Lineage Safety

Lineage tracking ensures:
- Each candidate records its parent candidates
- Chain traversal is bounded (no infinite loops)
- Circular references are detected and blocked
- Orphaned candidates (missing parent) are handled gracefully

### Deduplication Safety

Candidate deduplication is hash-based and non-destructive:
- Duplicates are marked (`is_duplicate = True`), never deleted
- Original candidate is preserved
- Same params_hash = same configuration = duplicate detection

### Promotion Gate Safety

The ResearchPromotionGate enforces 6 checks before any promotion:

1. **Manifest exists**: Experiment manifest must be present and complete
2. **Not overfit**: OverfitDetector must return False
3. **Sharpe above threshold**: Minimum Sharpe >= 0.5
4. **Trade count sufficient**: At least 10 trades
5. **Cost stress passes**: Must survive at 1x costs (minimum)
6. **Walk-forward passes**: Must survive 50%+ of walk-forward folds

Gate statuses:
- **BLOCKED**: Any check fails -- promotion is rejected with reason
- **PASS**: All checks pass -- ready for manual review

### Max Stage: PAPER_ELIGIBLE

The promotion gate can never promote beyond PAPER_ELIGIBLE:
- PAPER_ELIGIBLE is a status marker only, not an execution capability
- No method in the research engine calls `submit_order()`
- No research module imports from `quant_us.live` or `quant_us.execution`
- No research module references `AlpacaBroker` or any broker class

### R2 Safety Invariants

1. Research modules cannot submit real orders
2. Research modules cannot access live brokers
3. Automated output stops at paper_review_ready evidence; PAPER_ELIGIBLE is manual
4. Manual action required for all promotions beyond RESEARCH_ONLY
5. Overfit candidates are automatically rejected
6. Lookahead bias is detected and prevented
7. Time-split is enforced in all dataset construction
8. Portfolio construction outputs allocation targets, not orders
9. No research module references QUANT_LIVE environment variable
10. All research tests use tmp_path and fake data -- no real API keys or network calls

## R6 Alpha Robustness Safety (Added R-Series)

### No Live Interaction

R6 components work exclusively with pre-computed candidate data:

1. **Monte Carlo bootstrap**: Operates on cached trade lists from completed backtests. No live market data.
2. **Alpha decay estimation**: Computed from historical rolling alpha values. No real-time feeds.
3. **Parameter stability**: Tests perturbed parameter sets locally. No broker interaction.

### Metric-Based Checks

R6 promotion checks are metric-driven, not execution-driven:
- All R6 metrics are stored in candidate.json under `metrics`
- Missing metrics default to failure thresholds (conservative safety)
- Promotion gate reads metrics; it never computes them from live data

### R6 Safety Invariants

1. Monte Carlo survival check reads from candidate data only -- no simulation runs
2. Alpha decay check uses stored half-life values -- no live computation
3. Parameter stability check reads pre-computed scores -- no on-the-fly param sweeps
4. Missing metrics always result in BLOCKED or WATCHLIST (fail-safe)
5. No R6 module or check has broker or live API access
6. All R6 tests use seeded RNG for deterministic results

## R7 Multi-Strategy Portfolio Safety (Added R-Series)

### Correlation-Only Analysis

R7 features operate on computed metrics without portfolio execution:

1. **Correlation redundancy**: Computed from existing scorecard data. No live portfolio.
2. **Portfolio evidence review**: PaperReviewManager.create_from_portfolio_evidence() reads existing evidence packs. Never triggers trading.

### NEED_MORE_RESEARCH Safeguard

The `NEED_MORE_RESEARCH` decision is a hard gate between correlation checks and promotion:
- HIGH correlation redundancy triggers NEED_MORE_RESEARCH (not WATCHLIST or BLOCKED)
- NEED_MORE_RESEARCH blocks promotion just as BLOCKED does (it is checked before WATCHLIST)
- Human must explicitly re-submit after addressing the redundancy

### R7 Safety Invariants

1. Correlation redundancy check uses stored `correlation_redundancy` metric only
2. PaperReviewManager.create_from_portfolio_evidence() creates PENDING_HUMAN_REVIEW only -- no auto-promotion
3. Portfolio evidence validation requires non-BLOCKED gate decision
4. All R7 tests use tmp_path and synthetic data
5. No R7 module has broker or live API access

## R8 Research-to-Production Promotion Safety (Added R-Series)

### Stress Testing Isolation

R8 stress checks are simulated locally:
1. **Cost stress**: Simulates cost multiplier scenarios on pre-computed returns. No live execution.
2. **Crash window**: Tests against historical crash scenarios. No market impact.

### Gate Completeness

The ResearchPromotionGate is the single chokepoint for all research-to-production promotion:
- All 13 checks run in a single evaluate() call
- BLOCKED takes priority over all other outcomes
- READY_FOR_PAPER_REVIEW is the only pass-through state
- No bypass paths exist around the promotion gate

### R8 Safety Invariants

1. Stress survival check uses stored `stress_survival_rate` metric only
2. Promotion gate never promotes beyond PAPER_ELIGIBLE
3. Evidence packs are generated from existing data only -- no live queries
4. ResearchPromotionGate has no submit_order or broker access
5. All R8 tests use tmp_path and synthetic data
6. PaperReviewManager has no auto-approve path
7. PaperReviewManager.approve() requires a non-empty reviewer name
