# US shared-platform migration matrix

The machine-readable source of truth is
`configs/governance/us_shared_platform_adoption_v1.json`.

| Legacy symbol | Shared replacement | US compatibility facade | BTC dependent | Final deletion condition |
|---|---|---|---|---|
| `quant_us.core.clock.ensure_utc` / `utc_now` | `quant_shared.core` UTC functions | Same legacy imports | None on current main | All US callers migrate and an integrator ticket approves removal |
| `Signal` / `TargetPosition` / `OrderIntent` | None yet | `quant_us.core.types` | `quant_crypto.adapters.legacy_quant_us` | Shared domain-interface contract is integrated and both domains migrate atomically |
| `OrderSide` / `OrderType` / `TimeInForce` | None yet | `quant_us.core.enums` | `quant_crypto.adapters.legacy_quant_us` | Shared order-interface contract is integrated and both domains migrate atomically |

UTC, stable identity, canonical serialization, evidence, generic ledger,
injected-history replay, and read-model envelopes are adopted through
`quant_us.compat.shared_platform`. US trading calendars, PIT visibility,
corporate actions, and broker lifecycle remain US-domain semantics.

Breaking cleanup is deliberately deferred to an architect-approved integrator
ticket after a validated BTC handoff proves that exact-class imports are gone.
This adoption does not unlock promotion, paper, private, order, or live access.
