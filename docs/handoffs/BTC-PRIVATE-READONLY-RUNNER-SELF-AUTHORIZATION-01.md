# BTC-PRIVATE-READONLY-RUNNER-SELF-AUTHORIZATION-01

## Delivery boundary

- Role: `btc_developer`
- Base: `ba5195df38782f0e13a1ca6b360917d4a5c92f35`
- Change risk: `demo_execution_semantics`
- Producer branch: `agent/btc_developer/btc-private-readonly-runner-self-authorization-01`
- Integration: an independent integrator is required; fast-forward main is not allowed.
- Runtime: backend restart is required after integration. This producer did not
  start the runner, backend, keyring, network, or any private/account/order/live
  endpoint.

The change is confined to the private-readonly permission boundary, its exact
runner entry point, Hook guard/context, contracts, and operator documentation.
It does not change strategy, Forecast/TargetPosition/OrderIntent, Risk, OMS,
Private WS business reconciliation, ledger, Gate, artifact, backend, or
credential adapters.

## Failure-first evidence

The focused regression was added and run before implementation:

```text
py -3 -m pytest \
  tests/agent_governance/test_private_readonly_permission.py::test_runner_process_self_authorization_closes_unhooked_command_channel \
  tests/contracts/test_btc_demo_private_readonly_observation.py::test_dedicated_entrypoint_accepts_zero_security_arguments -q
```

It failed `2 failed` on the base implementation because
`authorize_runner_process` did not exist and `_parse_args` could not accept a
zero-argument argv list. This reproduces both the hosted/unhooked authorization
gap and the old five-required-argument entry point without reading a real
receipt, keyring, credential, or network surface.

## Implemented authorization flow

The sole invocation is now:

```text
py -3 scripts/run_btc_demo_private_readonly_observation.py
```

Before keyring or network access, the actual runner process:

1. requires a valid `CODEX_SESSION_ID` and matches it to the signed receipt's
   `target_session_id`; `CODEX_THREAD_ID` is never treated as a turn or an
   authorization identity;
2. requires the registered `main` checkout, current main HEAD, clean exact
   runner path, signed receipt, issued-at/TTL/revocation validity, and exact
   runner Git blob plus SHA256;
3. consumes only the unique receipt already armed by `UserPromptSubmit`;
4. validates a digest-bound `pretool_hook` launch reservation when Hook covered
   the command, or atomically creates a `runner_self`/no-turn reservation when
   the hosted command channel omitted `PreToolUse`;
5. creates `runner_starts/<receipt>.json` with O_EXCL. Replay and concurrent
   processes fail before credential loading;
6. deterministically derives runtime root, run ID, source HEAD, confirmation,
   and an internal claim digest. Receipt ID and security parameters are not
   accepted from command argv.

Both launch reservation variants bind the same session hash, receipt, source
HEAD, runner Git blob, runner SHA256, canonical invocation digest, permanent
permission map, and claim digest. A real Hook `turn_id` is preserved only on the
Hook reservation; runner self-authorization never invents one.

## Safety and lifecycle

- `allow_demo_orders=false`
- `allow_demo_cancels=false`
- `promotion=false`
- `paper=false`
- `live=false`
- `order=false`
- `real_order=false`
- `transfer=false`
- `withdraw=false`

`private=true` can apply only inside the exact committed read-only runner after
both receipt validation and the one-time process start claim. Tests and this
handoff are `quality_checked` only and do not unlock private access, paper,
promotion, or live readiness.

The old R8 receipt is consumed and was not read or reused. Existing tasks do not
hot-update. After independent integration and backend restart, the operator
must create a new task and externally install a new short-lived signed receipt
bound to the new session, integrated main HEAD, runner blob, and runner SHA256.

## Evidence and remaining gates

All tests use temporary capability roots, a fake signature verifier, monkeypatch
or fake adapters, and no real receipt/private key/keyring/network endpoint.

- `tests/agent_governance/test_private_readonly_permission.py`: `40 passed in
  39.48s`.
- `tests/agent_governance/test_hooks.py`: `8 passed in 65.27s`.
- `tests/contracts/test_btc_demo_private_readonly_observation.py`: `27 passed in
  5.30s`.
- Focused Windows process race: `1 passed in 9.37s` with 16 spawned claims and
  exactly one start winner.
- `py_compile` for all seven touched Python files: passed.
- `git diff --check` for the declared source/doc touch set: passed; only the
  repository's existing Windows LF-to-CRLF advisory was printed.

The complete `tests/agent_governance` run finished `122 passed, 10 failed in
258.98s`. One ticket-owned stale Hook-string assertion was then corrected and
is covered by the final `40 passed` permission run. The remaining nine failures
are outside this ticket and were not modified: seven temporary Git handoff
fixtures reported `handoff_deliverable_missing_at_commit`, one nested Windows
fixture exceeded the sparse-checkout lock path length, and the planner-created
sparse fixture did not materialize `.githooks/post-checkout`. These are explicit
unresolved governance-test blockers, not hidden as a passing full suite.

The deliverable commit and file SHA256 values are recorded in the separately
validated append-only published handoff event.

No runtime artifact, manifest, observation ledger, Gate artifact, or backend
read model was created. Current runtime and promotion evidence therefore remain
unchanged and fail-closed. Independent integration and post-integration backend
restart remain blockers owned by the integrator/operator workflow.
