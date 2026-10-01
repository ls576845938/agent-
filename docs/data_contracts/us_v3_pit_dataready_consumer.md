# US V3 PIT / DataReady Consumer Contract

Goal: `US-V3-PIT-DATAREADY-CONSUMER-01`

This US-only adapter consumes committed manifests and append-only handoffs. It
does not download, modify, publish, or synthesize production market data.

## Three distinct readiness classes

1. ETF26 minute data is `research_ready` and may only support frozen ETF26
   research observation. Its current manifest explicitly lacks adjustment
   available-time replay and proves no promotion readiness.
2. A PIT-lite zero-event proof may show that no membership or corporate-action
   event occurred in a bounded observation window. It cannot replace production
   PIT.
3. Production PIT acceptance requires one immutable data-steward manifest plus
   all six CSV tables: universe membership, delistings, corporate actions,
   symbol mapping, adjustment replay, and the macro release calendar.

## Production acceptance

The consumer checks:

- schema, producer role and committed producer commit;
- immutable bundle identity, file SHA-256 and record counts;
- coverage, XNYS calendar and declared source-splice identity;
- `event_time <= available_time <= ingested_at` for every record;
- bounded visibility lag and adjustment-specific available time;
- the exact seven-file contract.

Fixtures prove the adapter contract only. A missing, stale, partial, late,
uncommitted, or hash-mismatched bundle remains `blocked_external_data`.

## Ownership and safety

`data_steward` owns raw data, immutable publication and data manifests. The next
consumable handoff must be a committed append-only event that references the
immutable seven-file bundle and its hashes. This Goal never grants
`promotion_evidence_ready` and keeps promotion, paper, live, private, broker,
order, withdraw, demo, paper queue and real-order flags false.
