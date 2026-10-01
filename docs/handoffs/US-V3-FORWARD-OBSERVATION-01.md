# US-V3-FORWARD-OBSERVATION-01 integrator contract

## Producer scope

The producer delivers a US-only application service, thin CLI, immutable
receipt schema/config, contract tests, and current-day fail-closed review.

It does not modify `quant_shared`, BTC/CN code, raw data, data manifests,
`app_factory.py`, shared API schemas, frontend workspaces, scheduler state,
broker adapters, paper queues, or live permissions.

## Integration

No shared entrypoint wiring is required for the current Goal. A later
integrator may invoke:

```powershell
py -3 scripts/run_us_equity_forward_observation.py --repo-root . --json
```

The command is safe only after `09:20 Asia/Shanghai`; before that time it writes
no receipt. The service enforces one append-only receipt per natural day and
uses only the committed immutable ETF26 manifest configured by the existing
US PIT/DataReady consumer.

## Gate semantics

- `in_progress_natural_time` is expected until real time has elapsed.
- `blocked_external_data` is expected when the immutable successor does not
  cover the expected finalized XNYS session.
- 30 natural days are only a paper-review prerequisite.
- 252 distinct trading sessions are a separate confirmation window.
- Wrapper success never changes the receipt decision.
- Promotion, paper, live, private, order, broker, demo, withdrawal and real
  order flags remain false.

The integrator must preserve the dedicated
`artifacts/us_equity_forward_observation/**` single-writer domain and must not
redirect it to the legacy ETF26 observation latest path.
