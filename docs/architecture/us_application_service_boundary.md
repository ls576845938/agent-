# US application-service boundary

G05 introduces a transaction seam without rewriting the legacy US builders.
`USApplicationService` owns use-case orchestration and receives repositories,
a unit of work, the US calendar factory, and a clock. It contains no filesystem
root, environment lookup, HTTP dependency, broker SDK, or shared entrypoint.

The first extracted paths are:

- trading-calendar row construction and transactional upsert;
- minute-quality request normalization and injected-clock orchestration;
- promotion-gate invocation through a repository port.

`USQuantService` and `quant_us.cli` remain compatibility facades. Their calendar
return value, minute-quality dictionary, promotion result, CLI text, and exit
behavior remain unchanged. The internal promotion, minute-quality, evidence
registry, and production-line builders retain their US-domain rules.

## Integrator wiring contract

The independent facade is
`backend.app.services.us_application_facade.USApplicationFacade`. A later
US-only router ticket may inject it into the API composition root. This goal
does not modify `app_factory.py`, backend shared schemas, frontend types, or the
global Workbench.

## Deferred work

- Evidence-registry storage requires its own immutable repository/UoW ticket.
- Promotion-gate rule clusters may be moved behind pure evaluators only with
  decision-schema characterization.
- Production-line report repositories require a separately authorized,
  current-HEAD artifact rebuild.
- Paper-runtime depth changes remain reserved for G08.

No operation in this boundary enables promotion, paper, live, private, order,
or real-order behavior.
