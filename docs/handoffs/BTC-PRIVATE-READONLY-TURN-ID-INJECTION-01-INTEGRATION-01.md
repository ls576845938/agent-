# BTC-PRIVATE-READONLY-TURN-ID-INJECTION-01-INTEGRATION-01

## Integration decision

`change_risk=governance_control`. Independent integration accepts the complete
append-only producer chain:

`fe3e906fca9ba925d7e05474b148d8fece825509`
→ `44919a4b46d594a5613264e675b701de37028034`
→ `532325ab0bc7f611465b0128efc78068d2721925`
→ `8e8c9b36e0113228b7bb1e1b81e86d1dd9b13bcc`
→ `c9c3ea954f17a763e33553d1e8f7b47232eb4bef`.

Both published handoff envelopes validate against Git. The original seven
deliverable hashes and the correction's four superseding hashes match their
committed bytes. The no-ff integration merge is
`75d48e6efe6d0a6a6f7e693bd1f83777b8695d6a`.

## Independent safety review

- `UserPromptSubmit` may arm a valid receipt without a turn identity, but it
  keeps `private=false` and does not create a lease or launch claim.
- `session_id` never substitutes for `turn_id`; missing or malformed real
  `PreToolUse` turn identity remains denied.
- The complete canonical runner argv is validated before publishing the
  session-scoped O_EXCL winner claim. A non-runner or invalid runner does not
  bind a turn or consume the one-time launch.
- Competing turns share one immutable winner claim. Every trial produced
  exactly one authorization; the loser deterministically returned
  `private_readonly_capability_bound_to_other_turn`.
- The winning turn can resume lease construction after a crash. A different
  turn, corrupt claim/arm/lease, receipt/session/HEAD/runner/hash/TTL mismatch,
  revocation and replay remain fail-closed.
- Receipt prepare/install/sign remains outside Codex. The observer runner,
  business services, keyring, credentials, network and exchange endpoints were
  not accessed or changed.
- `promotion`, `paper`, `live`, `order`, `real_order`, `transfer` and
  `withdraw` remain false. `private` remains false until the exact runner
  PreToolUse atomically wins and claims its single launch.

## Independent verification

- `handoff.py validate` original published event: `valid`.
- `handoff.py validate` correction published event: `valid`.
- Correction SHA256 verification: four of four committed paths matched.
- 100-trial two-thread concurrency regression: `1 passed in 32.94s`.
- Twenty independent pytest-process repetitions of the two-turn race:
  `PROCESS_RUNS=20 FAILURES=0`.
- Permission and hook contracts: `39 passed in 84.53s`.
- Complete governance suite: `123 passed in 276.83s`.
- Scoped `py_compile`: exit `0`.
- `git diff --check fe3e906f... HEAD`: exit `0`.
- All frozen touch paths were clean before integration; no overlapping dirty
  change was consumed or overwritten.

The planner-created worktree remained sparse. `.githooks` was added only to the
local sparse materialization so the repository disk-guard contract test could
read its committed fixture; this created no repository diff.

## Remaining fail-closed work

This source integration is only `quality_checked`; it is not promotion, paper,
live or observation evidence. The registered main owner must adopt the
integration commits, review and re-trust the resulting hook hash, then create a
new observation task. Existing tasks do not hot-load hooks, and every R1-R7
receipt is non-reusable. A fresh external receipt must bind the new task session
and the adopted current main HEAD before any exact readonly runner attempt.
