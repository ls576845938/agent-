# BTC-V3-CURRENT-MAIN-ENGINEERING-AND-DATA-EXPORT-FORWARDPORT-01

## Delivery classification

- Role: `btc_developer`
- Authoritative base: `8bc235e9f9c5a42bf852ef24a4f89b12b6a1a682`
- Branch: `agent/btc_developer/btc-v3-main-eng-data-export-forwardport-01`
- Readiness ceiling: `quality_checked`
- Gate decision: `blocked_external_evidence_fail_closed`
- No market-data collection, real SQLite write, shared-data publication,
  runtime artifact rebuild, private/order/live endpoint, broker call, secret
  access, paper queue, or real order is in scope.

## Verified upstream deliveries

The forward-port reviewed only committed Git objects and validated both
append-only envelopes:

- `published-btc-v3-engineering-blocker-closure-01-6216788f`
  - deliverable commit
    `6216788ff952466502bd041f079413a052f8f9e4`
- `published-btc-v3-dataready-export-tool-and-shared-contract-cleanup-01-6337ac300`
  - deliverable commit
    `6337ac3005fd863ab002da321aba0af691f631f0`

The envelope SHA-256 values match committed Git blob bytes. On Windows,
`git archive` can materialize CRLF under `core.autocrlf`; that checkout
representation is not a replacement for the handoff/git-blob hash contract.
Both deliveries require this successor because they are non-ancestors of the
authoritative current main, not because either envelope is invalid.

## Current-main engineering closure

The current-main successor preserves BTC-owned `Signal`/`Forecast`/
`TargetPosition`/`OrderIntent` identities and removes direct
`quant_crypto -> quant_us` imports without changing US shared enums or runtime
types. It forward-ports:

- official sparse import closure;
- canonical paper-readiness schema alignment;
- Windows pointer-specific locking and bounded atomic replace retry;
- BTC lifecycle, venue-rule, forecast/order-intent, evidence builder, replay,
  and observation consumers of the BTC-owned contracts.

## Governed K-line export

The exporter is offline, read-only, deterministic, and fail-closed:

- source SHA-256, SQLite integrity, source stability, schema, UTC, OHLCV,
  duplicates, continuity, common end, and freshness are checked;
- explicit PIT/finalized fields are preserved when present;
- the current-main legacy table uses the existing governed mapping
  `event_time=available_time=close_time` and
  `is_finalized=(close_time <= generated_at)`;
- future/unclosed rows are excluded and counted as in-progress;
- default partition mode is strict all-source validation;
- an explicit required partition set is repeatable on the CLI and the
  attestation lists required, included, and excluded partitions with reasons;
- the architect-approved current-main required set is exactly
  `binance_spot:BTCUSDT:{1m,5m,15m,1h}`; data-steward invocation must pass all
  four selectors explicitly;
- Binance 4h/1d and Coinbase 1m remain visible as
  `excluded_non_required`, with full-source partition counts, source and
  inventory hashes, freshness, common end, and the approved exclusion policy;
- the BTC DataReady consumer rejects a declared required set that does not
  exactly match the included interval attestations or full-source inventory.

The data-steward audit remains blocked evidence: source SHA prefix
`11278c46`, 575,434,752 bytes, integrity `ok`, 1,741,871 rows, stale global
common end, stale 4h/1d and Coinbase partitions, and no usable historical OKX
L2 sequence/reconnect stream. Default all-partition export therefore remains
fail-closed. The required-set decision does not make the audited source or any
output ready; data-steward hash verification, offline export, immutable
publication, and consumer validation are still required.

## Governed OKX L2 export

The successor also adds an offline exporter for the existing public OKX
`books` capture segments. It reuses the existing capture envelope and replay
semantics; it does not add a collector or make a network call.

- every segment is bound to caller-supplied raw and manifest SHA-256 values;
- every segment and reconnect starts in `waiting_for_snapshot`;
- a gap, duplicate, out-of-order sequence, invalid checksum, crossed/one-sided
  book, invalid clock ordering, or update before a new snapshot quarantines the
  state and blocks publication;
- valid output is deterministic, two-sided, timestamp-aligned partitioned
  JSONL plus a strict data-steward attestation;
- the existing DataReady consumer accepts the generated fixture attestation;
- a short fixture can be `quality_checked`, but cannot retire the 30-natural-
  day history, execution-latency, queue-model, or natural-observation blockers.

## Architect DENY successor closure

The successor after the `63d2bfed` denial removes span-based L2 coverage
claims and closes the remaining producer/consumer ambiguities:

- `history_window_days` is derived only from validated manifest capture
  durations minus measured reconnect gaps; `coverage_span_days` is separately
  attested and cannot substitute for observed history;
- capture manifest `capture_start`, `capture_end`, duration, `gap_count`,
  `connection_count`, channel counts, and raw-row facts must agree;
- adjacent segments must touch exactly; overlap, temporal gap, event/receipt
  rollback, or non-contiguous sequence IDs block the complete export;
- reconnect windows are measured and emitted, `unrecovered_gap_count` is
  computed, and temporal gaps reduce two-sided coverage rather than being
  written as 100%;
- two one-second segments separated by 31 days are rejected and cannot retire
  the 30-natural-day blocker;
- legacy K-line `close_time_ms` must equal the UTC epoch milliseconds of
  `close_time` and align to the declared interval boundary;
- the DataReady consumer infers the Binance current-main contract from the
  partition identities, so a generic `policy_id` cannot bypass the exact
  `binance_spot:BTCUSDT:{1m,5m,15m,1h}` set;
- shared capture filenames and identifiers live in the import-safe
  `quant_crypto.data.okx_l2_capture_contract` module; the exporter no longer
  imports a producer script.

## Architect second-DENY successor closure

The second DENY review identified two additional P0 data-contract defects.
This successor keeps the original base inventory and closes them fail-closed:

- legacy K-line `close_time_ms` is an inclusive interval end. The exporter now
  requires exact ISO/millisecond equality and
  `(close_time_ms + 1) % interval_ms == 0`; when `open_time_ms` exists it must
  be interval-aligned and `close_time_ms - open_time_ms == interval_ms - 1`;
- OKX L2 history is derived from contiguous message observations, not directly
  from manifest capture duration. Collector monotonic start/end fields are
  mandatory and duration-consistent; same-connection messages must have exact
  capture-sequence continuity and bounded event/receive/monotonic gaps.
  Oversized idle gaps are unrecovered gap windows and block export.

No public collection, shared-data publication, database payload, private or
order endpoint, broker call, paper/live unlock, or real order is performed by
this successor.

## Architect third-DENY successor closure

The third DENY review found that individually tolerated clock differences
could accumulate and that a caller-controlled idle-gap threshold could bypass
the 30-day blocker. This successor closes both paths:

- raw first/last receipt and monotonic endpoints are anchored to their
  manifest endpoints with a governed 0.1-second tolerance; larger unobserved
  heads or tails become unrecovered endpoint gaps and block the export;
- both per-message receipt/monotonic delta and cumulative last-minus-first
  spans are checked, so individually small drift cannot accumulate silently;
- observed history sums the more conservative receipt/monotonic contiguous
  delta and excludes reconnect, idle, and unobserved endpoint gaps;
- inter-message gap policy is fixed by
  `btc_okx_l2_inter_message_gap_v1` with a 5-second approved ceiling. A caller
  may select a stricter positive threshold, but cannot widen it; the exporter,
  schema, and consumer all reject oversized or unknown policies.

The architect-provided full legacy SQLite compatibility result reports
1,731,576 rows and zero violations in all four inclusive-close checks. This
writer independently reran the K-line SQLite fixture contracts; it did not
read or mutate the external real SQLite payload.

## Architect fourth-DENY successor closure

The fourth DENY review found that a forged, schema-shaped attestation could
claim 30 observed days while its per-segment raw receipt and monotonic spans
proved only 29 days. The consumer now independently:

- computes a conservative source cap as the sum of each segment's smaller raw
  receipt/monotonic span, less its validated reconnect gap durations;
- rejects `observed_history_seconds` above that cap with an explicit
  one-microsecond numeric tolerance;
- cross-checks capture wall duration, monotonic duration, raw endpoint spans,
  endpoint-gap status, segment blocker state, row/replay counts, reconnect
  windows, per-segment counts, top-level totals, and coverage endpoints;
- rejects missing, malformed, non-finite, unknown-segment, or internally
  contradictory cap inputs without trusting producer identity alone.

Exporter-produced no-gap, multi-segment, and recovered-reconnect attestations
remain accepted by the strengthened consumer.

## Successor-05 batch closure

The fifth review batch identified freshness, independent coverage, schema,
lineage, and duration-attestation gaps. This successor closes them as one
fail-closed contract:

- `common_start` and `common_end` are bound to coverage and raw first/last
  receive endpoints using the attested maximum clock offset plus the governed
  0.1-second anchor tolerance. Freshness uses the oldest of `common_end`,
  `coverage_end`, and the last raw receive endpoint;
- the consumer independently recomputes two-sided coverage as
  `min(output/books, observed_history/coverage_span, 1) * 100` and rejects
  row, temporal, zero-denominator, gap, and non-finite contradictions;
- the complete L2 JSON Schema is applied before cross-field checks, while
  explicit BTC swap/public-books, sequence, checksum, readiness, promotion
  blocker, and false safety-guardrail checks remain independently enforced;
- source aggregate and table inventory hashes are recomputed, table
  path/hash/byte triples are bound to the immutable shared-data manifest, and
  checksum, snapshot/resync, freshness-age, and producer-SLA totals are
  cross-checked;
- capture wall/monotonic/endpoint duration comparisons use one governed
  absolute 0.2-second envelope. Microsecond-scale capture overhead remains
  usable; values beyond the envelope block.

The generated fixture remains `quality_checked` only. It does not collect
market data, publish shared data, write a database, call private/order/live
surfaces, or change any promotion, paper, or live safety flag.

## Successor post-a261 full-audit closure

The committed `a2618740` object was held frozen for a complete read-only
review. The follow-up closes every item from that review without changing
promotion semantics:

- public consumer policy inputs reject booleans, unknown values, NaN,
  infinity, non-positive freshness, coverage below 99%, freshness above 48
  hours, coverage above 100%, or clock tolerance outside 0..1000 ms;
- K-line attestations now receive the same complete schema, non-finite,
  source-HEAD, lineage, inventory, readiness, promotion-blocker, and false
  guardrail checks as L2 attestations;
- K-line freshness uses the conservative coverage/common endpoint and each
  resolved partition is streamed to prove identity, row count, sorted fixed
  cadence, grid alignment, PIT ordering, finalized status, and declared
  partition windows;
- L2 snapshots cannot reset sequence state within the same connection.
  Additional snapshots require a reconnect or segment boundary already
  represented by the existing transition, gap, resync, and sequence checks;
- both exporters attest per-file row counts. Consumers require the immutable
  manifest payload inventory, after excluding control files, to equal the
  attested table inventory exactly and stream the resolved JSONL files to bind
  actual file/top/segment totals;
- manifest `data_schema`, attestation `source_head`, manifest producer commit,
  commit existence, and caller current-HEAD identity are checked together;
- public capture inputs are validated before a WebSocket module or connection
  can be reached, and any captured error is explicit. Immutable export accepts
  only raw manifests with `error_count=0`.

No collection was run while implementing or validating this closure. Network,
shared-data publication, SQLite mutation, private/order/live surfaces,
broker calls, paper queues, and real orders remain outside the ticket.

## Architect final physical-row and readiness closure

The final full audit held `5f6439dff` frozen and identified three remaining
P0 consumer gaps. This successor closes all three against the resolved
immutable JSONL bytes:

- every K-line row is strict JSON and must carry the complete identity,
  dataset version, UTC event/availability times, finalized flag, and finite
  numeric OHLCV payload. Prices must be positive, volume non-negative, high
  and low internally consistent, and
  `event <= available <= attestation.generated_at <= consumer.checked_at`;
- every L2 row is strict JSON and must carry the full public OKX books
  identity, UTC event/snapshot/availability times, connection/capture/
  monotonic/venue sequence fields, full two-sided sorted book, best prices,
  and checksum. The consumer performs a stateful replay across files,
  reconnects, and segments; initial/reconnect snapshots, updates, previous
  sequence IDs, connection transitions, monotonic ordering, non-crossed
  books, CRC32, clock offset, and global/per-segment counts must agree with
  the attestation;
- manifest readiness is only a ceiling. It must agree with the explicit
  attestation readiness chain, and the consumer requires both before setting
  `research_ready` or `backtest_ready`. Any higher or lower mismatch blocks
  consumption. The current schemas explicitly keep both false, so the
  highest possible result remains `quality_checked`.

Failure-first cases cover missing fields, non-finite JSON, invalid OHLC
relations, future PIT availability, crossed books, checksum mismatch,
sequence gaps, and readiness mismatch. Genuine K-line and OKX L2 exporter
outputs remain accepted.

## Final-review numeric, capture, and endpoint closure

The final review of committed object `6e7fa65d8` found three additional
physical-consumer bypasses. The next business object preserves all earlier
closures and adds:

- exception-safe Decimal parsing for every K-line OHLCV value. Booleans,
  non-finite or unconvertible values, values above governed magnitude
  `1e18`, non-zero values below `1e-18`, and values beyond 18 decimal places
  block with explicit invalid/range reasons. A legal JSON integer such as
  `10**400` can no longer raise `OverflowError` out of the consumer;
- exact per-segment, per-connection capture-sequence continuity. Within a
  connection each physical output row must be previous + 1. A reconnect may
  continue previous + 1 or explicitly reset to 1, and only an already
  validated reconnect/segment boundary permits that reset;
- streamed first/last event, snapshot, availability/receipt, and monotonic
  endpoints for every segment. They are bound to raw receipt and capture
  endpoints using physical/attested clock offset plus the governed
  0.1-second anchor tolerance. Per-segment clock maxima are bound, while
  global physical event endpoints bind `common_start/common_end` and physical
  availability endpoints bind `coverage_start/coverage_end`.

Failure-first evidence includes the original `OverflowError`, accepted
capture sequence `1 -> 99 -> 100`, and accepted whole/start/end 60-second
payload shifts. All now block without throwing. Whole and local 50ms shifts
remain accepted as within the governed endpoint tolerance.

## Decimal-lexeme and segment-origin closure

The review of committed object `1cd8ccc61` found two remaining physical-row
ambiguities. This successor closes both without changing the readiness
ceiling:

- every segment's first physical L2 output row now requires
  `capture_sequence == 1`. Rows within a connection remain exact previous + 1;
  an explicitly validated reconnect may continue previous + 1 or reset to 1,
  after which exact continuity resumes;
- immutable JSONL uses a strict streaming parser with `parse_float=Decimal`,
  exact integer parsing, and rejected non-standard constants. Original numeric
  lexemes therefore retain precision through validation;
- K-line OHLCV and L2 numeric best prices are checked as Decimal values before
  any lossy conversion. L2 book price and quantity strings use the same
  magnitude, minimum non-zero, and 18-decimal-place policy while their exact
  strings remain available for OKX CRC32;
- value-domain 19-decimal lexemes, book-price and quantity precision bypasses,
  huge exponents, and underflow block. Exact 18-place decimal and scientific
  notation boundaries remain accepted.

Failure-first evidence reproduced both bypasses: a segment beginning
`99 -> 100 -> 101` passed, and
`100.0000000000000000001` was rounded before validation. Both now block.
A reconnect reset to 1 followed by exact +1 remains a passing state-machine
control.

## Context-free Decimal range closure

The review of committed object `4796fcc9a` found that Decimal construction
alone was not sufficient: applying context-sensitive `abs()` to an extreme
finite exponent could still raise a trapped `decimal.Overflow`. This
successor removes that final exception path:

- after construction and `is_finite()`, range validation uses only
  `Decimal.as_tuple()` plus Python integer calculations for coefficient
  length, exponent, decimal places, adjusted magnitude, zero detection, and
  the exact `1e18` upper boundary;
- no `abs`, `quantize`, float conversion, or other Decimal-context operation
  occurs before an out-of-range value is rejected;
- the same helper covers K-line numeric lexemes and L2 best price, book price,
  and quantity values;
- the streaming file gate converts any residual `DecimalException`,
  `ArithmeticError` (including built-in overflow), or type error into an
  explicit `*_payload_validation_exception` blocker instead of terminating
  the consumer.

Failure-first cases reproduce trapped Overflow for the extreme positive and
negative exponent paths. Long K-line integer coefficients, long L2 price
strings, explicit context traps, and an injected residual Decimal validation
exception now all fail closed. The existing 18-place/scientific positive
controls and 19-place, huge, underflow, NaN, infinity, and boolean negative
controls remain covered.

## Verification

- Failure-first close-time/PIT regression: failed before implementation, then
  passed.
- Failure-first partition-selection/consumer consistency regressions: failed
  before implementation, then passed.
- Fourth-DENY K-line/L2/DataReady consumer contracts: `67 passed`.
- K-line SQLite inclusive-close fixture compatibility: `16 passed`.
- DENY-successor BTC data/lifecycle/risk/OMS/gate/collector boundary
  regression: `173 passed`.
- Existing L2 capture-quality, replay, and reconnect fixture builders:
  `7 passed`.
- Sparse import CLI checks: pass; direct BTC core-type imports from `quant_us`:
  `0`.
- Ticket-owned exporter plus DataReady consumer contracts: `20 passed`.
- BTC lifecycle/replay/gate/safety regression: `108 passed`.
- Migrated BTC producer contracts: `9 passed`.
- Expanded successor regression: `119 passed`; nine report-reader cases were
  not runnable because this sparse writer worktree intentionally has no
  `artifacts/btc_scalping_readiness/latest` payload. The seven corresponding
  fixture builder/replay/reconnect tests were run separately and passed.
- Python compile checks: pass.
- Ruff was not run because the active Python 3.14 environment does not install
  the `ruff` module.
- Windows concurrent publisher and pointer-failure stress: five repeated
  invocations, `2 passed` each.
- Successor-05 endpoint failure-first subset: four failures and one passing
  within-bound control before implementation; all pass after implementation.
- Successor-05 L2 consumer contracts: `31 passed`.
- Successor-05 L2 exporter contracts: `36 passed`.
- Successor-05 K-line/L2/DataReady contracts: `83 passed`.
- Successor-05 artifact-independent BTC/shared-data expanded regression:
  `162 passed`.
- Expanded artifact-reader attempt: `165 passed`; five reader cases were not
  runnable because this sparse writer worktree intentionally has no
  `artifacts/btc_research_registry`, `artifacts/global_research_registry`, or
  `artifacts/btc_scalping_readiness/latest` payload.
- Post-a261 consumer contracts: `39 passed`.
- Post-a261 L2 exporter contracts: `38 passed`.
- Post-a261 K-line exporter contracts: `16 passed`.
- Post-a261 public collector boundary contracts: `34 passed`.
- Post-a261 combined data/export/collector contracts: `127 passed`.
- Post-a261 artifact-independent expanded regression: `206 passed`.
- Final physical-row/readiness DataReady consumer contracts: `42 passed`.
- Final genuine K-line exporter contracts: `16 passed`.
- Final genuine OKX L2 exporter contracts: `38 passed`.
- Final public collector boundary contracts: `34 passed`.
- Final combined data/export/collector contracts: `130 passed`.
- Final artifact-independent expanded regression, using the same historical
  selection plus three new failure-first cases: `209 passed`.
- Existing L2 capture-quality, replay, and reconnect fixture builders:
  `7 passed` (`9 deselected` current-artifact readers).
- Python compile, both attestation JSON parses, three sparse CLI help imports,
  and scoped `git diff --check`: pass.
- Final-review failure-first subset: `3 failed` before implementation, then
  `3 passed`.
- Final-review DataReady consumer contracts: `43 passed`.
- Final-review K-line/L2/DataReady contracts: `97 passed`.
- Final-review combined data/export/collector contracts: `131 passed`.
- Final-review artifact-independent expanded regression: `210 passed`
  (the identical historical 209-test selection plus one endpoint contract).
- Final-review L2 capture-quality, replay, and reconnect fixture builders:
  `7 passed` (`9 deselected` current-artifact readers).
- Decimal/segment-origin failure-first subset: `2 failed` before
  implementation, then `2 passed`.
- Decimal/segment-origin K-line/L2/DataReady contracts: `97 passed`.
- Decimal/segment-origin combined data/export/collector contracts:
  `131 passed`.
- Decimal/segment-origin artifact-independent expanded regression:
  `210 passed`.
- Decimal/segment-origin L2 capture-quality, replay, and reconnect fixture
  builders: `7 passed` (`9 deselected` current-artifact readers).
- Context-free Decimal focused contracts: `2 failed` before implementation,
  then `2 passed`.
- Context-free Decimal combined data/export/collector contracts:
  `131 passed`.
- Context-free Decimal artifact-independent expanded regression:
  `210 passed`.
- Context-free Decimal L2 capture-quality, replay, and reconnect fixture
  builders: `7 passed` (`9 deselected` current-artifact readers).

All pytest commands use a unique system TEMP, explicit `--basetemp`, and
`-p no:cacheprovider`.

## Remaining blockers and safety

- `owner:data_steward` no immutable approved K-line publication exists.
- `owner:data_steward` real timestamp-aligned OKX L2 history with sequence,
  checksum, gap, reconnect, receipt clock, and two-sided coverage is missing.
- `owner:btc_observation` natural non-flat strategy/fill sample is missing.
- `owner:btc_operations` funding cashflow and private-WS reconciliation natural
  observations remain incomplete.
- `owner:btc_observation` 30/60-day observation window is incomplete.
- `owner:architect/manual_reviewer` promotion approval is missing.

`promotion=false`, `research_ready=false`, `backtest_ready=false`,
`promotion_evidence_ready=false`, `paper=false`, `live=false`,
`private=false`, `order=false`, `broker=false`, `withdraw=false`,
`network=false`, `secret=false`, `demo=false`, `paper_queue=false`, and
`real_order=false`.
