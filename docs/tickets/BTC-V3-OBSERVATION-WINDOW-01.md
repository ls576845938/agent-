# BTC-V3-OBSERVATION-WINDOW-01

## Scope

This delivery reuses the historical
`btc_demo_observation_accumulator` and
`btc_demo_manual_approval_observer` module boundaries on current `main`.
It provides:

- hash-chained, append-only daily natural-observation receipts;
- explicit 30-day and 60-day window evaluation;
- gap records that never count as successful observation days;
- fail-closed rejection of historical backfill and conflicting daily receipts;
- explicit version segmentation across HEAD, strategy, data, or runtime changes;
- immutable per-run reports and manifests without a `latest` pointer;
- validation-only recording of independently approved manual facts.

## Operating boundary

This Goal does not start an OKX Demo runtime, access a private/order/live
endpoint, collect network data, read a secret, write a paper queue, submit an
order, or modify an operating-system scheduler.

Without separate runtime authorization, the accumulator emits
`awaiting_authorized_observation_runtime`. That receipt does not count toward
the 30/60-day window. Missing operating days are reported as
`gap_missing_receipt` and cannot be backfilled as success.

The manual observer cannot approve anything. It only validates a hash-bound
fact containing reviewer, approval ticket, UTC approval time, account hash,
and permission conclusions. It rejects secret/screenshot fields and any
withdraw-enabled conclusion. A valid fact remains review evidence only and
does not enable promotion, paper, live, private, order, broker, Demo runtime,
paper queue, network, or secret access.

## Readiness

- `quality_checked` describes structural and hash validation only.
- `research_ready` remains false.
- `backtest_ready` remains false.
- `promotion_evidence_ready` remains false.
- Natural-time 30/60-day evidence and manual approval remain independent,
  fail-closed prerequisites.
