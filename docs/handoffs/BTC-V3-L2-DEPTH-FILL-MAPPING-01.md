# BTC-V3-L2-DEPTH-FILL-MAPPING-01

## Boundary

- Role: `btc_developer`
- Base: `9629a075774255e48490574d4f24cbb6196b8ec5`
- Goal: close the engineering portion of
  `btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing`.
- Excluded: network collection, mutable SQLite, secret/private/order/live endpoints,
  Demo or real orders, paper queue writes, `quant_shared`, `quant_us` changes,
  frontend, shared schemas/enums, and historical `artifacts/**/latest`.
- The historical dirty
  `quant_crypto/application/btc_backtest_identity.py` was neither read nor
  consumed.

## Validated prerequisite

- `published-btc-v3-dataready-consumer-01-f6fe7cf9`: valid.
- `integrated-btc-v3-dataready-consumer-01-goal4-batch-01`: valid.
- Current upstream blockers remain owned by `data_steward`:
  `immutable_snapshot_not_published`,
  `data_steward_attestation_required`, and
  `okx_timestamp_aligned_l2_manifest_not_published`.

## Engineering deliverable

- Reuses `quant_crypto.research.btc_depth_slippage`; no second collector or
  replay stack was introduced.
- Depth decisions use only snapshots whose exchange/event timestamp and
  visibility timestamp are at or before modeled arrival time.
- The replay records spread, multi-level depth, queue-ahead assumption,
  latency/delay cost, partial fill, unfilled notional, impact, venue min
  notional/size/step/tick filters, and zero liquidity.
- Sequence gap, out-of-order events, one-sided books, stale snapshots and zero
  liquidity are explicit fail-closed diagnostics.
- `btc_okx_l2_depth_observation_batch_report.json` and
  `btc_depth_slippage_fill_mapping_report.json` now bind `data_version`,
  `run_id`, full `source_head`, parameters, parameter hash, input hashes and
  output hash.
- Fixture/diagnostic runs set `promotion_evidence_ready=false` and
  `evidence_class=fixture_or_diagnostic_only`.
- The new evidence-driven evaluator retires only the depth-fill blocker when
  both reports are current, fresh, complete, immutable/attested and mutually
  consistent. The other five OKX-native blockers are preserved unchanged.

## Tests

- Ticket-owned contracts: `21 passed`.
- Related BTC regression: `61 passed`.
- The first related run stopped at collection with
  `ModuleNotFoundError: No module named 'quant_us'` because the planner sparse
  set omitted a tracked, allowlisted legacy adapter dependency. `quant_us` was
  added read-only to this worktree's sparse set; no `quant_us` file was changed.
- Python compilation of all six changed/new Python files passed.
- No failure was skipped or filtered.

## Report and gate state

- No real report artifact was generated or committed because the immutable BTC
  snapshot, data-steward attestation and timestamp-aligned L2 manifest are not
  published.
- The output contracts are implemented and verified with temporary fixtures,
  but those fixture reports are not promotion evidence.
- `quality_checked=true` for the engineering deliverable.
- `research_ready=false`
- `backtest_ready=false`
- `promotion_evidence_ready=false`
- `promotion_allowed=false`
- `paper_allowed=false`
- `live_allowed=false`
- `private_endpoint_allowed=false`
- `order_endpoint_allowed=false`
- `withdraw_allowed=false`

## Next action

Owner `data_steward` must publish the immutable timestamp-aligned OKX L2 dataset,
manifest and attestation. After integration, rerun both report builders with the
same `data_version`, `run_id` and current full HEAD, then evaluate the depth-fill
blocker. Natural-time, funding, private reconciliation and manual approval
blockers remain separate follow-up gates.
