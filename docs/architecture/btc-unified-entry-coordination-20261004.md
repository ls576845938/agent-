# BTC Unified Entry Coordination (Stage 1)

Ticket: `BTC-UNIFIED-ENTRY-COORDINATION-20261004`

Change risk: `demo_execution_semantics`

Base: `eaa88400f01e47e5c8da377606b6df52a9543382`

## Outcome and boundary

The existing candidate offline coordinator is the single HTTP/CLI lifecycle
entry for both the frozen Qlib forecast adapter and the registered Donchian
rule adapter.  This stage changes offline software coordination only.  It does
not merge to main, deploy, publish artifacts, train/search a model, collect new
data, start a portfolio-value study, or enable Demo, paper, private, order, or
live permissions.

The routes remain semantically distinct:

- Qlib: sealed model artifacts -> Forecast -> portfolio/risk -> OMS -> ledger.
- Donchian: immutable registered rule Signal -> TargetPosition -> risk -> OMS ->
  original historical venue/fills/ledger.  No Forecast or IC is fabricated.

Both use the same durable job identity, start/stop/resume fencing, idempotency,
read-only result API, and false trading permissions.  Their economic runtimes
and account contracts remain adapter-specific.

## Immutable authorities

Donchian start accepts only an input revision and digest.  The server-side
catalog binds that pair to an exact Git `HistorySpec`, blob SHA-256, canonical
spec digest, input HEAD, and the existing four-table manifest identity for
OHLCV, mark, premium/index, and funding.  Clients cannot supply paths or code.

Start or resume performs the expensive `HistorySpec` and four-table validation
and load once, before economic construction.  The registered driver constructs
one original `DonchianHistoricalReplay` for the session and reuses its immutable
in-memory input through all events.  Event boundaries perform only lightweight
registration/revocation/expiry, package, account, generation, and stop checks;
they do not reload tables, read `latest`, rebuild the runner, or rescan history.

The history account contract is explicit and exact:

- adapter `btc_donchian_history_offline_v1`;
- venue `donchian_historical_replay_v1`;
- initial equity `5000 USDT` and equity unit `USDT`;
- server-authored external absolute `output_root` and fixed `run_id`;
- digests of both output root and run state directory.

Adapter, spec, input, account, equity, or currency mismatch is rejected before
economic state construction.  A previously attempted run whose state is gone
is not reset from the initial balance.

## Commit ordering and recovery

For each historical event the original replay persists venue/OMS/ledger state
and its event (including both reversal phases when present) first.  It then
persists a coordination projection and only afterwards advances the job cursor.
If the authoritative event commits but the orchestration UOW is interrupted,
resume reads the sealed projection, advances the cursor without replaying the
event, and continues the same `output_root/run_id`.  Duplicate orders, fills,
fees, funding bills, and ledger entries are therefore not created.

Completion is written only after the original replay finalizes and its persisted
venue state, marked cash/position/equity/fees/funding, and original account
ledger all agree.  The final result is a sealed projection of those facts.
There is no terminal force-close and no invented next-bar fill.  A blocked
historical ambiguity is terminal and cannot be resumed or cleared.

GET/list/result never constructs a runner, loads the four tables, recovers a
lock, reconciles economics, or automatically resumes work.

## Writer exclusion

New writers use a reliable OS file lease held for the whole replay session.
The persistent `writer.lock` also preserves compatibility with the old
`pid=<n>` O_EXCL protocol:

- a live legacy PID or malformed/unknown legacy identity blocks takeover;
- a confirmed dead legacy PID may be replaced only while the new OS lease is
  already held; the file is never unlinked before acquisition;
- process exit releases the OS lease, permitting exactly one recovering writer;
- readers do not reclaim locks.

## Protection capability

The UI reports adapter facts instead of the former universal “not supported”
text.  Qlib reports explicit sampled-mark protection and its intrainterval
limitation.  Donchian reports original historical OHLC/mark protection and
fails closed on double-touch or timing ambiguity.  Existing sealed blocked
results retain their original marker.

## Research status and stage 2 seam

No complete comparable real candidate pair exists.  The Donchian 2960-phase
work has ledger evidence, while R2/R3 terminal evidence is rejected for missing
final model, valid calibration, and v3 package; the older conditioned-1956
result remains blocked by protection double-touch ambiguity.  Consequently the
real portfolio-value study has not started, no second qualified package exists,
and this software stage makes no claim of multi-member or portfolio gain.

No new fit, research run, dataset, or cost policy was produced.  Proposed
25/5 budgets and a new 2960 window remain unreviewed drafts and are neither
defaults nor admission rules.

## Stage 2: bounded two-member offline coordination

Stage 2 is implemented under the same producer ticket as a strictly offline,
exactly-two-member execution contract. It is not an arbitrary strategy list,
optimizer, ensemble model, or research result.

Each `MemberDecision` preserves its original strategy id/version, source
object hash, TargetPosition id, quantity unit, contract value, lot size, and
protection-policy digest. A contracts target and a BTC target are never added
as like units: `0.01 contracts` and `0.0001 BTC` each normalize to `0.01
contracts` in the bounded fixture only because the bound `ctVal` is exactly
`0.01 BTC/contract`. Opposite members are rejected instead of netted to a
fictional zero fill.

Budgets are mandatory inputs. There is no automatic 25/25 split or silent
target scaling. Member budgets may leave capacity unused, their sums must stay
within the explicit account policy, and account limits remain at or below
`50 USDT` notional and `10 USDT` loss. An insufficient member budget rejects
the whole cohort before order construction.

The account transition policy is narrow and v1 is long-only:

- a flat account may open only when both members request long and a compatible
  protection policy; a common short cohort is rejected before planner/OMS or
  any venue order because v1 residual-protection facts do not prove short
  replacement semantics;
- a non-flat account may hold or reduce each member's own actual-fill share;
- a new member, same-direction increase, reversal, cross-zero transition, or
  incompatible remaining protection policy is rejected;
- ordinary cohort entry remains FOK; the existing special 0.03 partial-fill
  drill is not selected.

The assembly layer issues an in-process versioned context bound to exact member
object hashes, the Target's original quantity and hash-bound
`metadata.quantity_unit`, the Signal direction, normalized plan, member-list
digest, explicit budget digest, allocation-plan digest, runtime run id, client
order id, and venue conversion facts. Consumption recomputes these member
bindings and checks the immutable issuance seal, so mutating a member object or
proposal after issue is rejected. The runtime accepts the context only for the
existing offline provider, offline credential namespace, and non-real client.
Legacy `None` Donchian and sealed Qlib Forecast branches retain their defaults.
No Forecast, probability, or IC is created for the rule member; learning-route
Forecast validation remains an upstream admission responsibility and was not
exercised by the fixture.

The coordinator Signal/Target names the execution scope only; it does not
rename or replace member decisions. The application entry calls the original
planner and production composition, then existing Portfolio/Risk, OMS,
dispatcher, deterministic offline venue, raw-fill, and ledger-UOW paths.

`strategy_allocations` is attribution, not a second economic book. Raw fills,
fees, bills, cash, and account-ledger rows are never rewritten. Each fill id
and bill id is bound to its immutable source digest; duplicates are idempotent
and conflicts block. Decimal residual is assigned deterministically to the
last sorted active member, so fill quantity, fee, and funding amount conserve
exactly. Allocation payload and recovered state have bidirectional exact parity
in the same ledger UOW. Calls without allocation retain the old payload and
semantic hash. Each actual fill also records the venue timestamp at which its
member ownership became effective. A newly observed funding bill is allocated
against the latest ownership fact strictly earlier than its venue settlement
timestamp; this correctly handles a pre-exit bill first observed after exit.
Missing timestamps, equality with an ownership transition, or absent history
cannot prove the owner and therefore block before allocation. An already-bound
identical bill id remains idempotent.

When one member exits, its actual reduce-only fill consumes only its attributed
lot. The deterministic offline venue replaces the shared OCO with a
residual-size OCO and records a v1 proof binding prior algo/parent, exact exit
order/fill ids, exited member, residual owner, and replacement algo identity
and quantity. This seam is unavailable to real clients and adds no economic
cash flow.

Member proposals are not admitted merely because a caller typed a strategy id
and hash. The issued context requires already-verified Signal/Target objects
whose exact hashes and ids match the member contract. Upstream remains
responsible for those proposals: the rule route retains frozen rule/parameter
and exit-policy evidence, while the learning route must retain its own sealed
calibrated Forecast evidence. The bounded tests supply fixture proposals; they
do not claim both real algorithms or a qualified Qlib package were invoked.

The historical coordination projection is now explicit opt-in on the
registered driver. Ordinary historical replays retain their original artifact
and economics without an extra full venue projection per event. A projection
write failure after authoritative artifact persistence remains a precise
fail-closed interruption; no economic event is replayed or invented to repair
it.

Offline residual-revision fields are omitted entirely when no non-empty
offline coordination revision exists. Ordinary order records and hosted
protection projections therefore retain their prior JSON shape and semantic
hash inputs instead of gaining an unconditional empty object.

Recovery coverage is exact but deliberately bounded. A newly constructed
controller restores the persisted allocation, residual protection, venue and
ledger journal; replaying the same venue funding bill through the original
funding-only reconciliation UOW reuses the prior event. Reissuing the old exit
members and same client order id creates a new sealed context, enters the
original execution seam, and is safely rejected by existing OMS/reconciliation
constraints with order, fill, UOW, event hash, and equity unchanged. No
no-action Target or new OMS retry behavior was introduced.
