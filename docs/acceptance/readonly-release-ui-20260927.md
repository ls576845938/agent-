# Research readonly release UI producer acceptance

- Ticket: `READONLY-RELEASE-UI-20260927`
- Role: `super_developer`
- Change risk: `research_readonly_release`
- Base commit: `8ea90775bc250ad4cfcab7592fbdc720b3df4edc`
- Canonical main observed before work: `770392bacab55596da3238b1815af4476866f0de`
- Readiness ceiling: `quality_checked`

## Boundary

This producer changes only frontend display and interaction gating. It does not
change backend access policy, candidate transport, strategy, risk, OMS, ledger,
runtime artifacts, governance, launchers, or trading permissions. No page,
backend, broker, private, order, paper, or live endpoint was started or invoked.

## Result

- `/api/health` is interpreted strictly. Missing or contradictory profile
  fields keep every side-effecting research action disabled.
- `research_readonly` keeps GET refresh and evidence navigation available while
  disabling Alpha Factory training/recovery, Qlib/factor/candidate writes,
  portfolio writes, and review writes with a short reason.
- `candidate_management` does not enable ordinary research writes. It preserves
  the existing candidate-management UI, which still requires its own
  capabilities and authentication response before commands can be used.
- `CandidateDelivery` begins fail-closed, reads only `/api/health`, and does not
  request `/api/strategy-delivery/*` unless the exact candidate-management
  profile is confirmed.
- The read-failure next action now opens and focuses the existing provenance
  details in place instead of navigating away and removing the failure detail.
- The permanently disabled local-draft publish control, portfolio rebalance
  placeholders, and unconnected account-risk placeholder were removed. Their
  explanatory safety text remains.
- Existing sealed A/B blocked evidence copy remains unchanged and fail-closed.

## Tests

Failure-first evidence:

- `node frontend/scripts/test-readonly-release-ui.mjs` initially failed `5/5`
  before implementation (missing profile helper and all four UI contracts).

Passing focused checks:

- `node frontend/scripts/test-readonly-release-ui.mjs` — `6/6` passed.
- `node frontend/scripts/test-candidate-delivery.mjs` — `6/6` passed.
- `node frontend/scripts/test-candidate-handoff.mjs` — `14/14` passed.
- `node frontend/scripts/test-candidate-local-auth.mjs` — `7/7` passed.
- `npm.cmd run lint` from `frontend/` — passed (`tsc --noEmit`).
- `npm.cmd run build` from `frontend/` — passed, `5275` modules transformed;
  only the existing large-chunk advisory was emitted.
- Scoped `git diff --check` — passed; only Git line-ending conversion warnings.

Not run:

- Playwright/browser checks were not run because worktree pages are forbidden.
  Canonical-main browser acceptance belongs to the independent integrator after
  integration and restart.
- `frontend/scripts/test-research-portfolio-contract.mjs` remains blocked before
  reaching this ticket's assertion by a pre-existing frozen-baseline mismatch:
  current candidate `research-api.ts` contains cancellable GET support while the
  script hard-codes baseline `13486a7802628e93dd624213ba6c317c5deb4ddf`.
  This ticket did not modify that API or weaken the frozen contract.

## Dependencies and remaining gates

The requested upstream event
`.agent/handoffs/INTEGRATE-CANDIDATE-OFFLINE-DIAGNOSTIC-ADMISSION-20260926/integrated-candidate-offline-diagnostic-market-policy-closeout-20260927-deace3f2b.json`
was not reachable from canonical main, the ticket base, any local Git ref, or the
current handoff file inventory, so this producer could not independently run
`handoff.py validate` on it. The UI work does not infer any readiness from that
missing event.

No artifact, manifest, ledger, replay, or promotion read model was rebuilt.
Current-main identity, restart, browser acceptance, rollback verification, and
independent integration remain pending. The following flags remain false:
`demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`,
`real_order`, `transfer`, `withdraw`, `execution_permission`, and
`runtime_observed`.
