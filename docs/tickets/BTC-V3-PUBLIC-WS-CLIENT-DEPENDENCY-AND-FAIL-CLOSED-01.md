# BTC-V3-PUBLIC-WS-CLIENT-DEPENDENCY-AND-FAIL-CLOSED-01

## Scope and ceiling

This ticket fixes only the BTC-owned OKX public WebSocket L2 collector
dependency and its pre-network failure behavior. It does not collect market
data, consume another worktree, write `data/**`, `artifacts/**`, SQLite, or
data-steward manifests, change exporter/DataReady contracts, access
private/order/live endpoints, read secrets, submit or queue orders, or unlock
promotion. The maximum readiness is `quality_checked`.

Base commit:
`97d6448b89ce6029c69b20fbfe2427d99ae083e8`.

Dedicated branch:
`agent/btc_developer/btc-v3-public-ws-client-fail-closed-01`.

The planner-created worktree passed the first explicit Git gate with
`git config --bool core.sparseCheckout` returning `true`. Initial scoped
`safe_status.py` was clean for the complete touch set.

## Dependency decision

`websocket-client>=1.8,<2` is declared in the installable
`btc-public-ws` project extra. Install the runtime with:

```text
pip install .[btc-public-ws]
```

The dependency is not part of the core dependency list because the default
dry-run, offline research, exporter, DataReady consumer, and non-BTC domains
do not require a WebSocket client. The bounded major-version range preserves
the `WebSocket()`, `settimeout()`, and `connect()` API used by this collector
while avoiding an unreviewed future major upgrade.

## Fail-closed contract

The credential-environment guard remains before WebSocket module loading,
client construction, or connection. Client construction and timeout setup are
now separate from the actual `connect()` call.

Before any socket attempt:

- missing or broken `websocket-client` loading returns a deterministic
  `rejected` report with an explicit dependency blocker and error;
- WebSocket client construction or timeout initialization failure returns a
  deterministic `rejected` report with an explicit initialization blocker and
  error;
- both paths keep `network_called=false`,
  `websocket_client_initialized=false`, zero message/data rows, empty files,
  zero connections, and no raw-capture file or capture manifest;
- no dependency or initialization exception escapes the collector.

Dry-run still does not load the optional network dependency. Existing
public-channel allowlisting, private/login/VIP channel rejection, positive
finite duration/timeout validation, positive message limits, nonnegative
forced-reconnect validation, selected-bundle rejection, and public-only false
safety flags remain unchanged.

The successful test path now mirrors the runtime boundary: initialize a
client, configure its timeout, then mark `network_called=true` immediately
before `connect()`. No strategy, Signal, Forecast, TargetPosition,
OrderIntent, Portfolio/Risk, OMS, Fill/Ledger, or audit-DAG boundary is
changed.

## Verification

- Failure-first dependency and client-initialization subset: `2 failed`
  before implementation, then passed.
- Public WS collector and segment contracts, including dry-run, invalid
  channel/finite parameters, dependency rejection, initialization rejection,
  mocked public connect/receive, errors, and reconnect: `20 passed`.
- Complete public collector boundary file: `37 passed`.
- Related immutable L2 exporter and DataReady consumer contracts:
  `81 passed`.
- Python compile for the collector and contract test: pass.
- Collector CLI `--help`: pass without loading or connecting a WebSocket
  client.
- TOML parse resolves
  `project.optional-dependencies.btc-public-ws` to
  `websocket-client>=1.8,<2`.
- Scoped `git diff --check`: pass.

All tests used a unique system temporary directory and
`-p no:cacheprovider`. No real network or public collection was executed.

## Context and remaining blockers

Preflight used:

- `docs/knowledge/README.md`;
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`;
- `docs/agent_playbooks/shared_pitfalls.md`;
- `docs/agent_playbooks/btc_developer_pitfalls.md`;
- `docs/knowledge/08_live_trading_sre/exchange_api_runtime_contract.md`;
- `docs/knowledge/08_live_trading_sre/websocket_reconnect_gapfill.md`;
- `docs/knowledge/09_exchange_api_security/api_key_permission_policy.md`.

Context packet catalog hash:
`568cf9c4f4d96d1cff4d331f29b69ec40ad28b6c13156d542c586ef5d8314a11`.

Active pitfall IDs:
`GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-HANDOFF-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`,
`QSYS-GATE-001`, `QSYS-SECURITY-001`, `GOV-PROMPT-001`, and
`GOV-WINDOWS-001`.

Team Context reported zero ready upstream deliveries and
`invalid_handoffs=0`; no external handoff was consumed. The existing
current-HEAD promotion/data/observation blockers remain unaffected, including
missing immutable approved K-line publication, missing real timestamp-aligned
OKX L2 history, missing natural execution observations, incomplete
funding/private-WS reconciliation observations, incomplete observation
windows, and missing manual promotion approval.

`research_ready=false`, `backtest_ready=false`,
`promotion_evidence_ready=false`, `promotion=false`, `paper=false`,
`live=false`, `private=false`, `order=false`, `broker=false`,
`withdraw=false`, `secret=false`, `demo=false`, `paper_queue=false`, and
`real_order=false`.
