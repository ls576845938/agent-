# US v3 current-main successor

`US-V3-CURRENT-MAIN-SUCCESSOR-01` reconstructs the validated US v2 research chain on
integrated main `07e32a043a3fd48e5b50f67dd90ed59679bf6af7` by projecting selected committed
paths. It does not merge or cherry-pick the historical development branch.

## Delivered boundary

The successor restores the ETF26 immutable dataset consumer, frozen candidate,
complete-return multitimeframe research, canonical event backtest, production PIT
intake, candidate portfolio, and candidate execution envelope. The authoritative
per-file provenance, historical SHA-256, base comparison, and current test binding
are recorded in
`docs/handoffs/us-v3-current-main-successor-scope-manifest.json`.

The five historical branch-audit tooling paths are intentionally excluded because
their assumptions are tied to the old branch base and audit head. They are replaced
by the current-main successor manifest, schema, and contract test.

## Ownership and integration

This delivery is US-only. It does not modify `quant_shared`, `quant_crypto`,
`quant_cn`, backend or frontend entry points, shared schemas, or global workbench
wiring. Any shared consumer wiring remains an integrator-owned follow-up.

The data steward retains ownership of raw data, immutable dataset publication, and
data manifests. This code consumes only fixtures, fake adapters, local replay, or
validated immutable manifests.

## Gate impact

The delivery is `research_only`. It creates no current evidence artifact and does
not unlock promotion, paper, or live execution. Network collection, secret access,
broker/private/order endpoints, paper queue writes, paper orders, live orders, and
real orders remain disabled.
