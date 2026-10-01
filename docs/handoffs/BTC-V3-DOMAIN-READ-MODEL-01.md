# BTC-V3-DOMAIN-READ-MODEL-01

## Delivered boundary

- One BTC application read model aggregates data, strategy, risk, OMS, ledger,
  replay and gate evidence on the executing HEAD.
- The file adapter only reads explicitly configured artifacts and verifies
  existence, JSON shape, SHA-256, source HEAD and freshness.
- Missing, invalid, stale, wrong-HEAD or hash-mismatched evidence is blocked.
- Blockers are deduplicated, self-reference summaries are filtered, and each
  remaining blocker receives an engineering, data-steward, integrator,
  natural-time or manual-approval category, owner and next executable action.
- Flat heartbeat is displayed as `waiting_for_natural_non_flat_sample`, never
  as fill or promotion evidence.
- Research-only and blocked states can never be rendered as paper/live ready.
- The API contract is GET-only, authenticated, `Cache-Control: no-store`,
  read-only and cannot trigger builders, runtime or order paths.

## Integrator wiring contract

1. Include `build_btc_domain_read_model_router(...)` in the shared app factory.
2. Register
   `artifacts/btc_domain_read_model/latest/btc_domain_read_model.json` as the
   first BTC candidate in `tools/agent_governance/team_context.py`.
3. Materialize that path only through an approved read-model snapshot ticket;
   the GET endpoint itself must remain side-effect free.
4. Do not modify frontend semantics: consume the stable schema and preserve
   `research_only`, `blocked`, paper and live distinctions.

## Current gate

This Goal supplies code, schema and fixture/contract evidence only. Current
natural non-flat, private-WS, funding, immutable L2/data attestation and manual
approval blockers remain. `quality_checked=true`; `research_ready=false`;
`backtest_ready=false`; `promotion_evidence_ready=false`; all trading safety
flags remain false.
