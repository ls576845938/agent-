# BTC Promotion Gate Active Criteria Normalization 01

## Scope

This ticket changes BTC promotion evidence semantics only. It does not collect
data, publish runtime artifacts, restart services, access credentials, call
private/order/live endpoints, or authorize paper/live execution.

## Active information contract

The global 30-natural-day condition is retired. Admission is evaluated from
the frozen, Git-tracked preregistration:

`docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json`

The evaluator pins both exact prereg bytes and canonical JSON semantics. An
embedded preregistration that lowers a threshold and recomputes its own hash is
rejected. The loader reads only the requested repository and exact current-head
ref; a missing ref, missing object, or changed object fails closed without any
cross-checkout or `HEAD` fallback. Numeric thresholds are not defined by the
promotion evaluator.

The evidence must carry the preregistered eligible-window, autocorrelation-
adjusted ESS, UTC bucket, weekday, and volatility/liquidity regime metrics. It
is evaluated by `btc_10s_microstructure_data_contract.evaluate_readiness` for
one explicitly declared family and horizon.

## Family dependency scope

- `trade_imbalance_continuation`, `micro_breakout`, and
  `sweep_absorption_reversal` do not inherit an open-interest blocker.
- `liquidation_cascade_recovery` requires time-aligned open interest and
  liquidation-event capability.
- An absent or unregistered family/horizon fails closed with
  `active_strategy_family_dependency_scope_missing`.
- `maker_queue` remains out of scope for the taker-only preregistration.

## Immutable identity binding

Active-criteria evidence must match the authoritative OKX pointer on all of:

- current source HEAD;
- exact `run_id` and `data_version`;
- immutable manifest and evidence SHA256;
- a pointer/manifest/evidence lineage member carrying the exact artifact-root
  logical path, immutable URI, SHA256, and `producer_role=data_steward`;
- the resolved and hashed attestation JSON, whose run, data version, dataset,
  aggregate, and manifest identity match all three authoritative documents.

The gate returns only the verified logical identity and hashes, never the
physical artifact root. Missing, unreadable, forged, or mismatched identity
fails closed. Active-criteria evidence may bind only this verifier-produced
attestation identity; a manifest, handoff, self-reported lineage row, or schema
label by itself never unlocks promotion.

## Canonical blockers

Funding, private-WS reconciliation, natural non-flat fills, the authorized
25-hour Demo window, and manual approval remain hard gates. Legacy
`btc_next_stage` aliases are collapsed into the corresponding
`btc_okx_native` structured blocker so owner and next action are emitted once.

L2 timestamp alignment, sequence integrity, two-sided quality, latency/queue
evidence, funding, reconciliation, non-flat fills, 25-hour observation and
manual approval remain fail-closed. All promotion, paper, live, private,
order, transfer, and withdraw permissions remain false.
