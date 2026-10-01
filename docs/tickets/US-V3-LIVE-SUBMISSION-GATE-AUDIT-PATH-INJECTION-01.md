# US-V3-LIVE-SUBMISSION-GATE-AUDIT-PATH-INJECTION-01

## Status

`open`; owner: `live_runtime`; gate impact:
`blocks_final_paper_readiness`.

This independent follow-up was discovered during
`US-V3-FINAL-PAPER-READINESS-01`. The final review does not modify live or
submission business code.

## Current-main reproduction

- Base/current main reviewed:
  `78f3e07bfb5f13431d91ce2526aed00fad70f9e3`.
- Validator: `tests/live/test_safety_boundary_regressions.py`.
- Combined result: `103 passed, 4 failed`.
- The four failures are:
  - `test_paper_runtime_reconciliation_break_blocks_before_oms`
  - `test_paper_runtime_kill_switch_blocks_before_oms`
  - `test_live_runtime_paper_mode_requires_explicit_submit_orders_before_oms`
  - `test_runtime_restart_does_not_duplicate_previously_submitted_order`
- Exact construction boundary:
  `quant_us/live/live_order_submission_gate.py:109`.
- Exact operation:
  `self.audit_dir.mkdir(parents=True, exist_ok=True)`.
- Exact failure family:
  `FileNotFoundError` followed by
  `PermissionError: [WinError 5] Access is denied: 'data'`.

The tests inject an isolated ledger root, but `LiveOrderSubmissionGate`
constructs the fixed process-CWD-relative directory `data/live_pilot/audit`.
That implicit path is a side effect during runtime construction and is not
controlled by the injected repository/UoW boundary.

## Repair boundary

- Inject the audit root through the live runtime composition boundary.
- Do not create fixed process-CWD-relative paths during service construction.
- Preserve fail-closed submission, kill-switch, reconciliation, restart, and
  duplicate-order semantics.
- Do not enable broker, private, order, paper queue, live, or real-order access.
- Add a construction regression that uses a read-only process CWD and an
  explicit writable temporary audit root.

## Acceptance

1. All four exact safety-boundary regressions pass with a unique system
   temporary `basetemp`.
2. Runtime construction writes only below the explicitly injected audit root.
3. Reconciliation break and kill switch still block before OMS.
4. Paper mode still requires explicit submission authorization.
5. Restart still cannot duplicate a previously submitted order.
6. A separate deliverable and append-only handoff are integrated before a new
   final readiness review.
