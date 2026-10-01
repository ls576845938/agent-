# BTC-PRIVATE-READONLY-RUNNER-SELF-AUTHORIZATION-01-INTEGRATION-02

## Integration decision

- Role: `integrator`
- Change risk: `demo_execution_semantics`
- Approved main base: `ba5195df38782f0e13a1ca6b360917d4a5c92f35`
- Original producer deliverable: `176c64b07694404e9a7cf1054aedd7af3ecfae09`
- Correction 01: `8e9be10aad22e1a7081d22df9985e104203b2546`
- Correction 02: `bb8b67bf0b5ad85c49257a1261fbb65cb1a0c01f`
- Final producer handoff commit: `ba23ec69ce11d2c13b06790eea9a996701238775`
- Independent no-ff merge: `e3a3b6d7cac8ac791e559cd13f6498a10bb6f4c6`
- Decision: `integrated` in the dedicated integrator branch; registered main
  remains untouched pending root adoption.

All three producer events validated against committed Git objects. Correction
01 supersedes the original published event and correction 02 supersedes
correction 01. Commit ancestry, declared touch set and committed deliverable
SHA-256 values matched their envelopes.

## Independent security review

The rejection recorded by
`rejected-btc-private-readonly-runner-self-authorization-01-a2f1f0748` was
reproduced against correction 01 and then closed by correction 02's final
chain:

- `arm + binding_claim + no active lease` now returns
  `private_readonly_binding_claim_arm_unavailable` before launch/start claim;
- the pure-arm hosted path still creates one self reservation and one start
  winner;
- the active-lease Hook path still validates the Hook reservation and creates
  one distinct process-start winner;
- replay and Windows spawned multi-process contention produce exactly one
  `runner_starts` winner;
- `CODEX_SESSION_ID` is the only signed session authorization identity;
  `CODEX_THREAD_ID` and `THREAD_ID` do not substitute for session or turn;
- the security docstring now matches that signed-session contract.

The runner performs self-authorization before credential loading or network
client construction. Current main identity, clean runner path, signed receipt,
issued-at/TTL/revocation, exact runner Git blob/SHA, canonical invocation
digest, reservation and O_EXCL start claim remain fail-closed.

## Revocation v1 boundary

For this v1 integration, receipt revocation is an admission-time control. The
receipt is revalidated immediately before the launch/start claim path and a
receipt already revoked at admission is denied. The 25-hour runner does not
currently interpret a later revocation file as a runtime stop signal. Runtime
revocation and a revoke-versus-start linearization protocol are not claimed by
this ticket and require a separately approved contract if desired. This scope
statement does not weaken order/live prohibitions and does not authorize a new
engineering ticket.

## Verification

- Critical state/identity routes:
  `4 passed in 1.00s`.
- Full permission, Hook and runner contracts:
  `77 passed in 30.15s`.
- Explicit Windows spawned cross-process winner:
  `1 passed in 2.64s`.
- Python compilation of seven touched Python files: passed.
- `git diff --check` over the approved touch set: passed.
- Full `tests/agent_governance` in the clean planner sparse worktree:
  `132 passed, 2 failed in 86.69s`.

The two full-suite failures are environment/fixture-only and are not caused by
the runner correction:

1. `test_discovery_400_refs_uses_fixed_git_batches_and_one_blob_materialization`
   failed in its deeply nested Windows temporary repository with Git
   `Filename too long`.
2. `test_post_checkout_hook_runs_sparse_backstop_before_lfs` requires
   `.githooks/post-checkout`, which is intentionally absent from the planner
   sparse checkout.

The ticket-specific permission, Hook, runner, identity and cross-process
contracts all passed despite those two explicitly classified failures.

## Delivery boundary and safety

No real receipt store, keyring, credential, private key, network,
private/account/order/live endpoint, observer runner or backend was touched.
No runtime artifact, manifest, ledger, Gate artifact or read model was created
or rebuilt. The registered main worktree remained at the approved base.

After root adopts the integration commit, Hook trust must be reviewed, the
backend must be restarted as required by the change-risk policy, and a new task
plus a fresh externally signed receipt must bind the integrated main identity.
Those operational steps are not part of this integration.

`promotion=false`, `paper=false`, `live=false`, `private=false`, `order=false`,
`real_order=false`, `transfer=false`, and `withdraw=false` remain unchanged.
