# BTC registered candidate offline protection execution

Ticket: `BTC-REGISTERED-OFFLINE-PROTECTION-20260927`

This change closes one bounded gap in the registered-candidate offline path. It
does not change the candidate model, signal, target, position/exit policy,
Guardian, Risk, OMS, ledger algorithm, launcher, or any Demo/paper/live
permission.

## Accepted observation and price policy

- A protection trigger may execute only from an explicit, verified registered
  maintenance fact with UTC observation time, mark price, and index price.
- The attached OCO must be live, mark-triggered, bound to exactly one filled
  parent order/fill, match the current position direction and full size, and
  have become effective before the sampled observation.
- A sampled point is represented as mark open/high/low having the same value.
  The adapter does not infer the path between two samples and does not claim
  that an intrainterval high or low was observed.
- The protection fill uses the sampled mark with the candidate's frozen
  per-side non-fee costs (`spread + slippage + impact`) applied adversely. The
  existing 5 bps per-side fee continues to be recorded by the original venue
  economics and ledger path.
- Each protection fill stores the observation source, mark/index values,
  pricing-policy version/hash, cost, protection algo identity, and parent
  order/fill identities.

Missing identity, invalid ordering, unsupported trigger semantics, missing
facts, or ambiguous evidence remain fail-closed. The 90-second registered
maintenance coverage and 100-second runtime freshness contracts are unchanged.

## Authority and recovery

The venue persists one exchange-shaped protection order/fill and makes the OCO
effective. The existing controller then collects the account snapshot, commits
and verifies the authoritative ledger, and appends one idempotent
`registered_protection_executed` event.

The only newly handled crash window is:

1. the venue order/fill was atomically persisted;
2. the controller ledger/event tail was not yet committed.

On restart, exact persisted protection, order, fill, policy and parent
identities are checked before the existing ledger is reconciled. No order is
resubmitted and no second fill is created. Conflicting or incomplete recovery
evidence blocks instead of being guessed.

Old runs that already contain a durable `registered_protection_blocked` event
remain blocked. They are not migrated, resumed, or relabelled by this change.

## Read-model and integration note

The bounded read projection now reports `sampled_mark_protection_only` and
`intrainterval_mark_path_not_inferred`; the actual fill carries the policy and
receipt evidence. A subsequent integrator may change the management-service
capability from `protection_execution_supported=false` only for newly opened
current-code runs. A global capability flag must not upgrade the status of old
blocked results; each result remains authoritative by its own run identity,
policy version/hash, and protection receipt.

## Explicit exclusions

- no private, order, Demo, paper or live endpoint access;
- no continuous-path or OHLC trigger reconstruction;
- no migration of prior blocked runs;
- no model training, parameter search, or market-state policy;
- no change to default Donchian execution behavior;
- no permission or promotion-gate change.

