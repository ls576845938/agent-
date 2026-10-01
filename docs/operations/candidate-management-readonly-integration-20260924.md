# Candidate management readonly integration review

Date: 2026-09-25  
Role: independent integrator  
Ticket: `candidate-management-readonly-integration-20260924`  
Base: `1cd4ca2f70a547a21ce60a98acff992510286332`  
Frozen source: `1fc70fec77a6bac7b5699e99b503a10b92af659c`

## Decision

Approved as a source-review candidate for the ticket-specific `research_readonly` publication path. This approval does not enable candidate management, account access, Demo, paper, live, private endpoints, orders, runtime workers, promotion, or execution permission.

The frozen source was merged without business edits and remains an ancestor of the integration branch. The only derived source change is `frontend/public/frontend-identity.json`, refreshed through the existing `identity:refresh` command after the merge.

## Verified inputs

- The governance source and integrated handoffs validated successfully.
- All four business handoffs under `candidate-delivery-backend-20260924` validated successfully, including the superseded/rejected history and the final currency-fixed plus independently reviewed events.
- `candidate_management_readonly_delivery.frozen_source()` verified the exact 30-file inventory and SHA-256 values.
- Baseline, reviewed business, frozen source, governance producer, and governance review ancestry checks passed.
- Initial scoped status was clean for every source, identity, report, and handoff path in the approved touch set; no overlapping dirty source was found or altered.

The independent business review records one failed cleanup-only probe (`WinError32` while deleting a temporary SQLite fixture). It explicitly excludes that probe from pass counts; the business rejection under test was observed. This integration did not repeat or conceal that historical cleanup result.

## Validation

- Backend bounded suite: 71 passed and one expected protection failure caused by an integration-local pytest base directory being placed inside the repository. The single failed test was rerun with a system-external absolute base directory and passed. No business code was changed.
- Frontend candidate delivery and handoff tests: 20 passed.
- TypeScript: `tsc --noEmit` passed.
- Production frontend build: Vite completed successfully (chunk-size advisory only).
- Frontend identity refresh produced baseline `a6a867dc6b1f32fc45790b351edca03daca39098` and fingerprint `0441344dd7eccee6e426741e18e5a0b4da1dc4a94791ae149b909df43e6d3744`.

## Scope and remaining boundaries

The integrated source adds package validation, review records, exact settlement-currency matching, account binding contracts, candidate-management catalog registration/revocation, and truthful frontend handoff copy. Existing runtime entrypoints still do not consume the management catalog. The fixed Qlib candidate's original admission blockers remain.

No training, strategy, position, exit, risk, OMS, protection, ledger, launcher, Hook, runtime artifact, or trading permission semantics were changed. No private, broker, order, or live endpoint was accessed. No management database or account facts were created.

Required false states remain: `candidate_management_enabled`, management root/operator/auth configuration, Demo control, promotion, paper, live, private, order, real order, transfer, withdraw, execution permission, runtime worker, and runtime observed.

This report authorizes only the next governed step: merge the independently reviewed integration candidate into canonical main, restart through official launchers as `research_readonly`, and perform current-main identity, listener, blocked-management, no-storage, and browser acceptance checks. Deployment acceptance is a separate result.
