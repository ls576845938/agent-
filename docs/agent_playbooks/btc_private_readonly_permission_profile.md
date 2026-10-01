# BTC Private Readonly Permission Profile V1

This profile is a repository trading-domain guardrail for one local observer
launch. It is not an operating-system sandbox, a Codex permission profile, or
evidence of least privilege. The repository currently uses
`sandbox_mode = danger-full-access`; hooks alone cannot change that fact.

## Fail-closed boundary

- Every permission is false by default.
- A signed receipt may expose `private=true` only to the exact committed
  `scripts/run_btc_demo_private_readonly_observation.py` entry point.
- `promotion`, `paper`, `live`, `order`, `real_order`, `transfer`, and
  `withdraw` remain false in the receipt, lease, launch claim, hook context,
  audit event, and CLI output.
- The receipt binds the target `session_id`, current `refs/heads/main`, runner
  Git blob, runner content SHA256, short TTL, and one prompt. Codex Desktop does
  not reliably expose a usable `turn_id` during `UserPromptSubmit`, so that
  event only creates an unbound arm and an immutable receipt-claim tombstone.
- The only invocation is the zero-security-argument command
  `py -3 scripts/run_btc_demo_private_readonly_observation.py`. Runtime root,
  run ID, source HEAD, confirmation, and the internal authorization-ticket hash
  are derived from the validated receipt and launch/start claims. Receipt IDs
  and five security parameters are never copied through chat or command argv.
- A canonical exact-runner `PreToolUse` with a valid real `turn_id` may publish
  the session-scoped binding and a `pretool_hook` launch reservation. The
  runner process still independently validates the signed receipt and creates
  `runner_starts/<receipt>.json` with O_EXCL before keyring or network access.
  No `session_id` fallback or guessed hook field is accepted as a turn identity.
- A hosted command channel that does not emit `PreToolUse` cannot bypass this
  boundary. After `UserPromptSubmit` has armed one unique receipt, the runner
  validates `CODEX_SESSION_ID` against `receipt.target_session_id`, the current
  registered-main checkout, TTL/issued-at/revocation, runner Git blob and file
  SHA256. It then publishes a `runner_self`/no-turn launch reservation and the
  same O_EXCL start claim. `CODEX_THREAD_ID`, when present, is not a turn and is
  not used as authorization identity.
- A second `UserPromptSubmit` atomically interrupts an unbound arm. Its receipt
  claim tombstone prevents the original pending source from being armed again,
  so authorization cannot cross prompts even if archival of the source file
  was interrupted.
- While the lease is active, `PreToolUse` defaults to deny. Only a canonical
  `Bash`/`exec_command` zero-argument runner invocation can reserve it.
  Reads, edits, arbitrary clients, other scripts, MCP/local tools, and any
  order/cancel/withdraw path are not released.

## Arm and claim concurrency

The Hook binding decision is one immutable file keyed only by the session hash. Its
entire payload (real `PreToolUse` turn, receipt, source HEAD, runner Git blob and
runner SHA256) is written to a temporary file and published with an O_EXCL
hard-link operation. There is no arm-to-binding directory observation window.
Competing turns read the same complete winner claim and deterministically fail
with `private_readonly_capability_bound_to_other_turn`; the winning turn may
resume lease creation after a crash. A malformed or missing `PreToolUse`
`turn_id`, wrong command shape, mismatched session/HEAD/runner/receipt, expired
TTL, revoked receipt, or corrupt arm/claim/lease remains fail-closed. Non-runner
tools are denied while an arm or winner claim exists and cannot cause binding.

## External operator signing

The repository contains no receipt signer and no private key. It verifies an
OpenSSH detached signature against the public-key-only allowed-signers file at
`.codex/hooks/private_readonly_operator_allowed_signers`, read from the exact
receipt `source_head`.

The committed file intentionally contains no enrolled key. Enrollment is a
separate reviewed governance change containing only the operator public key for
principal `btc-private-readonly-operator`. Until that change is integrated,
verification returns `private_readonly_operator_signer_not_enrolled` and
`private` remains false.

After enrollment, a human operator must perform receipt preparation, signing,
and installation in a terminal outside the Codex task. The external signer uses
namespace `quant-btc-private-readonly-v1`; the private key must never be placed
in the repository, exposed to Codex, printed, or read by these tools. The
observer task cannot prepare/install a receipt or invoke `ssh-keygen -Y sign`
through the repository hook.

## Runner self-authorization and platform boundary

`PreToolUse` matcher `.*` covers tools the local Codex hook platform actually
emits, but hosted/wrapped command channels may omit that event. The runner is
therefore the final mandatory authorization boundary for every command channel.
Non-runner hosted tools, an already-open `write_stdin` transport, computer-use,
private/account/order/live endpoints, and receipt/signing actions remain
blocked; the receipt releases only this exact committed runner process.

The trusted hook hash must be reviewed again after integration. Existing tasks
do not hot-update code or hook trust. The old R8 receipt is consumed and must
never be read or reused. After independent integration and backend restart, an
operator must create a new task and externally install a fresh receipt bound to
that task's session, the new main HEAD, and the integrated runner blob/SHA256.
A signed receipt by itself still does not authorize credentials, private
endpoints, or execution; only the exact observer runner can consume it once.
