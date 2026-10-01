# BTC-PRIVATE-READONLY-TURN-ID-INJECTION-01

## Decision

`change_risk=governance_control`. The deterministic current-HEAD defect is that
Codex Desktop `UserPromptSubmit` can omit a usable `turn_id` even though later
`PreToolUse` events carry the real turn identity. The prior implementation
rejected the valid pending receipt before the exact runner could be evaluated.

No undocumented field alias is introduced. The correction uses a two-stage
protocol:

1. `UserPromptSubmit` validates and arms the signed session/HEAD/runner-bound
   receipt without granting `private` or creating a turn lease.
2. Only the first exact observer-runner `PreToolUse` with a valid `turn_id` can
   atomically bind the arm and claim its single launch.

## Security invariants

- `session_id` never substitutes for `turn_id`.
- The complete runner argv is validated before arm binding.
- While armed, every non-runner tool is denied and cannot bind.
- A later `UserPromptSubmit` interrupts the unbound arm; the immutable receipt
  claim prevents cross-prompt replay.
- Competing turns race on one complete, session-scoped O_EXCL winner-claim
  file, published only after full runner validation. One turn wins; all others
  read the same immutable claim and deterministically return
  `private_readonly_capability_bound_to_other_turn`.
- The winner claim contains turn, receipt, current HEAD, runner blob and runner
  SHA256 identities. Only the same turn may recover lease creation after a
  crash; no arm-to-binding directory observation window exists.
- Missing/invalid turn identity, receipt/session/HEAD/runner/hash/TTL mismatch,
  revocation, corruption, ambiguous receipt, and replay remain denied.
- Receipt prepare/install/sign stays restricted to the external human terminal.
- `promotion`, `paper`, `live`, `order`, `real_order`, `transfer`, and `withdraw`
  remain false. `private` remains false in prompt context until the exact runner
  `PreToolUse` atomically binds and claims the single launch.

## Scope and delivery

This ticket changes only repository governance hooks, the permission state
machine, focused contract tests, and documentation. It does not access operator
receipt storage, private keys, Windows keyring, OKX credentials, network, or any
private/account/order/live endpoint. It does not modify the observer runner,
business services, risk, OMS, ledger, data, strategy, artifact, or Gate.

Independent integration and hook re-trust on the resulting current main are
required. Existing tasks do not hot-load hook changes; after integration the
operator must create a new observation task and a new receipt bound to that
task session and the new main HEAD. No existing R1-R7 receipt is reusable.

## Append-only correction

Independent integration rejected the first deliverable after its twentieth
Windows concurrency repetition exposed a transient
`private_readonly_armed_attempt_state_race` loser result. The correction keeps
the original commits and handoff immutable, replaces the directory-observation
protocol with the session-scoped winner claim above, and adds a 100-trial
two-turn concurrency regression. The original handoff is superseded only by a
new append-only correction event.
