# US v3 frozen-candidate forward observation contract

## Scope

This contract observes the already frozen ETF26 candidate. It does not select
an ETF, timeframe, parameter set, or execution venue. It consumes only a
committed and validated immutable `data_steward` successor through the existing
US PIT/DataReady consumer.

The service is local and offline. It does not collect data, read credentials,
modify the operating-system scheduler, call a broker/private/order endpoint, or
write a paper/live queue or ledger.

## Time contract

- Observation timezone: `Asia/Shanghai`.
- Recommended local time: `09:20`.
- Expected finalized session: the previous actual `XNYS` trading session.
- One immutable receipt is allowed per Shanghai natural day.
- An invocation before the recommended local time writes no receipt.
- Once a same-day receipt exists, later invocations only verify and reuse it.

## Independent windows

The two windows are independent and cannot substitute for each other:

1. `30` consecutive natural-day receipts are only a paper-review prerequisite.
2. `252` distinct finalized XNYS sessions form the independent confirmation
   window.

Weekends may advance the natural-day count only when an eligible receipt exists,
but a repeated Friday session is counted once in the 252-session window.
Neither window unlocks promotion, paper, live, private, order, or broker access.

## Receipt identity and continuity

Every receipt records:

- natural day and expected finalized session;
- source HEAD and committed code-tree hash;
- candidate, strategy, parameters, data version, manifest and hashes;
- signal, target, simulated fill and simulated ledger evidence state;
- natural-day streak and distinct-session count;
- blockers, gaps, owners, next actions, and all-false safety flags.

Missing finalized-session coverage, invalid immutable handoff, receipt/hash
tamper, dirty latest identity, wrong timezone, day gaps, cross-HEAD,
code-tree-hash drift, or cross-strategy drift interrupt continuity. No receipt
is backfilled, rewritten, or promoted from failure to success.

## Artifact layout

```text
artifacts/us_equity_forward_observation/
  runs/<YYYY-MM-DD>/<run-id>/report.json
  runs/<YYYY-MM-DD>/<run-id>/manifest.json
  latest/latest_pointer.json
```

The run directory is append-only. The latest pointer is updated atomically only
after the report and manifest hashes are materialized. The separate legacy
`artifacts/us_equity_etf_26_forward_observation/**` domain is not written.

## Current-main data boundary

At the G11 base, the validated immutable ETF26 successor is
`hf-data-library-etf26-clean-1min-6d6b07e77962`, with coverage ending
`2026-07-10T15:59:00`. A later natural-day review whose expected finalized
session is outside that coverage must be `blocked_external_data`; it must not
manufacture signal, target, fill, ledger, or observation credit.
