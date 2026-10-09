# BTC Unified Entry Coordination Stage 1 Acceptance

This receipt is software acceptance only.  It is not a real candidate,
promotion, paper, Demo, or live readiness artifact.

## Required evidence

- [x] Exact source commit and validated append-only handoff are recorded after
  all checks finish.
- [x] Both adapters enter through `CandidateOfflineService`; the existing six
  Qlib lifecycle cases remain compatibility tests.
- [x] Donchian input is bound to exact Git HistorySpec/blob/spec digest plus the
  immutable four-table manifest; HTTP accepts no filesystem path or code.
- [x] A bounded explicit synthetic fixture enters the real service and runs the
  original Donchian replay, risk, OMS, historical venue, fill, and account
  ledger implementations.  Runtime economics are not faked.
- [x] The authoritative first event can commit before an injected coordinator
  UOW interruption; the same job and run resume without duplicating its order,
  fill, fee, or ledger entry.
- [x] Completion is projected only after final venue/marked-state/original-ledger
  agreement; terminal has no forced close and no synthetic next-bar fill.
- [x] A live writer conflicts, a confirmed dead legacy owner can recover under
  the OS lease, and live/unknown legacy owners remain blocked without unlinking.
- [x] Blocked jobs cannot resume.  GET/result does not initialize or recover a
  runtime.
- [x] UI filters inputs by adapter and describes sampled-mark versus historical
  OHLC ambiguity accurately; legacy blocked evidence remains authoritative.
- [x] Forecast/IC rules are scoped to the predictive route; the rule route still
  crosses portfolio/risk, costs, OMS, fills, ledger, and audit.

## Failure-first matrix

| Case | Expected result |
|---|---|
| wrong adapter/input kind | reject before runtime/economic state |
| wrong spec, input HEAD, blob, digest, or manifest identity | reject before runtime/economic state |
| wrong account adapter/equity/currency/root/run identity | reject before runtime/economic state |
| missing state after a prior construction attempt | block; never reset 5000 USDT |
| revoked/expired registration at event boundary | no new event; safety reconciliation/block |
| stop/generation fence at event boundary | no new event; same job may explicitly resume |
| authoritative event persisted, job projection interrupted | resume from sealed cursor; no duplicate economics |
| historical double-touch/timing ambiguity | terminal blocked; no guessed protection fill |
| terminal bar without next open | observe/reconcile only; no order and no force close |
| active writer or live/unknown legacy PID file | fail closed; no concurrent writer |

## Research and release gates

Real portfolio-value research is not started because there is no second
qualified comparable package.  Donchian 2960-phase ledger evidence does not
repair the rejected R2/R3 final-model/calibration/v3-package terminal evidence,
and conditioned-1956 remains protection-ambiguity blocked.  Tests with two
software adapters or fixture members must not be described as real portfolio
gain.

No new training/search, annual rerun, fit, research dataset, cost policy, or
default/admission configuration is authorized.  The proposed 25/5 budget and
2960 window remain drafts.  Source is not merged, pushed, published, deployed,
or served by this ticket.  All promotion, paper, live, private, order,
real-order, transfer, and withdrawal permissions remain false.

## Stage 2 software acceptance

- [x] Explicit contracts/BTC units and frozen `ctVal`/lot evidence are
  required; equivalent fixture quantities normalize without scaling.
- [x] The v1 flat-account contract supports a common long cohort only. It
  reaches original production
  composition, Risk/Portfolio, SharedPlatform OMS, dispatcher, in-process
  venue, and account ledger UOW as one FOK `0.02 contract` order and one raw
  fill. A common short cohort rejects before planner/OMS and leaves zero
  order/fill/UOW; arbitrary same-direction support is not claimed.
- [x] One member's actual `0.01 contract` IOC exit leaves the other member's
  `0.01 contract` allocation unchanged and replaces shared protection with an
  exact `0.01 contract` residual revision proof.
- [x] Fill quantity, fee, and funding conserve exactly. Fill timestamps freeze
  the ownership timeline; a pre-exit bill first observed after exit is shared
  by the ownership proven at its settlement time, while a later bill belongs
  to the residual member. Missing or transition-equal timestamps block, and an
  exact recorded bill retry remains idempotent. The integration fixture sends
  both cases through simulated venue facts, original account-ledger
  reconciliation, and funding-only UOWs carrying identical allocation
  payload/state.
- [x] Optional allocation payload and recovered state are exact in both
  directions in the same UOW; legacy calls omit both and keep old semantics.
  Empty offline residual-revision fields are absent from ordinary order and
  hosted-protection JSON rather than changing the legacy object/hash input.
- [x] Target quantity, hash-bound Target `metadata.quantity_unit`, and Signal
  direction must exactly match each `MemberDecision`; consumption revalidates
  the issued member objects/seal. Post-issue mutation, opposite directions,
  unbound member objects, incompatible protection,
  non-flat increase/new member/reversal, wrong conversion, and insufficient
  explicit budget reject without new risk or target scaling.
- [x] Public registered Donchian construction binds the actual normalized
  output root and run id to both registered digests before economic creation.
- [x] Registered replay retains its sealed coordination projection; ordinary
  historical replay cannot attach a coordination callback without opt-in.
- [x] A new controller for the same run/account recovers the original journal,
  residual `0.01` allocation and OCO revision proof. The same venue bill passes
  through the original funding-only UOW without a new UOW/hash. A newly issued
  exact old-member context with the same terminal client order id enters the
  original execution seam and is safely rejected; order, fill, fee, bill,
  equity, UOW count and last event hash remain unchanged. No hold intent or OMS
  retry semantic was added.

The integration member called `qlib-learning` is a fixture identity. The test
does not run a real fitted/calibrated Qlib model and is not evidence of a
qualified second candidate or portfolio value. Tested responsibility begins
after member proposal verification and object sealing; real admission still
requires each route's existing registration, frozen inputs/parameters,
Forecast calibration where applicable, and original exit policy.

Stage 2 remains source-only in this producer worktree. It is not merged,
pushed, deployed, published, served, or authorized for external Demo/private/
order/live access. `demo_environment_only` is a true safety attestation; all
paper/live/real-money/transfer/withdraw/permission-upgrade flags remain false.
