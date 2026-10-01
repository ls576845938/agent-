# BTC-V3-GATE-AGGREGATION-SPARSE-IMPORT-01

## Classification

- Category: `engineering`
- Owner: `btc_developer`
- Found by: `BTC-V3-FINAL-PAPER-READINESS-01`
- Gate impact: `blocks_gate`

## Reproduction

In an official BTC sparse worktree:

```text
py -3 scripts/build_btc_gate_aggregation_chain.py --help
```

The import fails with:

```text
ModuleNotFoundError: No module named 'quant_us'
```

Import chain:

```text
scripts/build_btc_gate_aggregation_chain.py
-> quant_crypto.research.btc_perpetual_paper_runtime_replay
-> quant_crypto.oms.paper_runtime_replay_session
-> quant_crypto.oms.execution_quality
-> quant_crypto.oms.lifecycle
-> quant_crypto.adapters.legacy_quant_us
-> quant_us.core.enums
```

The BTC worktree planner intentionally excludes `quant_us`, so a BTC final
gate builder cannot rely on that package being present.

## Required repair

Replace the inappropriate sparse-runtime dependency with the already
approved `quant_shared` contract or a BTC-owned adapter. Do not add
`quant_us` to the BTC sparse checkout and do not change shared enums from
this ticket.

## Acceptance

- Gate aggregation imports and collects in the official BTC sparse worktree.
- Direct BTC-to-US dependencies do not increase.
- Existing BTC lifecycle, replay, gate and safety contracts pass.
- No paper/private/order/live path is enabled.

## Resolution

- Status: `retired_engineering_blocker`
- Goal: `BTC-V3-ENGINEERING-BLOCKER-CLOSURE-01`
- The canonical records and enums now live in
  `quant_crypto/trading_contracts.py`; their wire values and fields remain
  compatible while their Python identities are BTC-owned in every checkout.
- `quant_crypto/adapters/legacy_quant_us.py` is a migration-only re-export
  shim and contains no `quant_us` import.
- All BTC runtime consumers and the two BTC producer scripts using these
  records were migrated atomically. The boundary allowlist permits zero
  direct `quant_crypto -> quant_us` imports.
- `py -3 scripts/build_btc_gate_aggregation_chain.py --help` and the related
  BTC producer `--help` checks succeed in the official sparse worktree.
- Contract, lifecycle, replay, gate and safety regressions passed; all
  paper/private/order/live permissions remain false.
