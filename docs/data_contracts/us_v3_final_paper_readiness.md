# US v3 final paper-readiness contract

`US-V3-FINAL-PAPER-READINESS-01` is an offline, read-only review of committed
US evidence. It may produce a valid blocked packet or, when every prerequisite
is complete, declare at most
`promotion_evidence_ready_for_architect_review_only`.

It never starts paper/live, reads secrets, writes a paper queue, or calls a
broker/private/order endpoint.

## Inputs

The review validates:

- every G01-G11 integrated handoff with `handoff.py` and current-HEAD ancestor
  checks;
- the immutable production PIT seven-file consumer report;
- canonical backtest/portfolio/fills-position-cash ledger and deterministic
  replay evidence;
- separate 30-natural-day and 252-distinct-XNYS-session observation windows;
- fake-adapter OMS lifecycle, recovery, reconciliation, rollback and failure
  drills;
- metadata-only broker credential review and the manual decision record;
- the serialized current-HEAD gate receipt, schemas, input/output hashes and
  all-false safety flags.

Historical blockers are never dropped. Each becomes an
`original_blocker_retirement` row with its source, evidence path, validator,
root classification and retirement decision. The packet rejects any blocker
that cannot be explicitly classified.

## Output

The writer owns only `artifacts/us_equity_final_paper_readiness/**` and
publishes:

- immutable `runs/<run-id>/report.json`;
- immutable `runs/<run-id>/manifest.json`;
- `latest/latest_pointer.json` after report/schema/hash validation succeeds.

A builder exception cannot advance the latest pointer. Durable repository
paths use POSIX separators. A wrapper exit of zero is not a readiness decision.

## Decisions and safety

- Missing, stale, wrong-HEAD, hash-drifted, unsafe or incomplete evidence:
  `blocked_fail_closed_no_paper_no_live`.
- Complete prerequisites:
  `promotion_evidence_ready_for_architect_review_only`.
- Even the latter leaves promotion authorization, paper, live, private,
  order, broker, withdrawal, queue writes and real orders false pending
  architecture approval and an independently authorized runtime.

The currently reproduced implementation defects are not repaired inside this
review. They are tracked independently by:

- `docs/tickets/US-V3-PAPER-DURABLE-PATH-ASSERTION-DRIFT-01.md`;
- `docs/tickets/US-V3-LIVE-SUBMISSION-GATE-AUDIT-PATH-INJECTION-01.md`.

Each remains a final-readiness root blocker until its exact current-main
regression passes and its repair handoff is integrated.
