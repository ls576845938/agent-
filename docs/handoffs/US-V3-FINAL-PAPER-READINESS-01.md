# US-V3-FINAL-PAPER-READINESS-01 integration contract

## Delivery boundary

This delivery adds one US-only, offline final paper-readiness reviewer:

- application service:
  `quant_us/application/us_equity_final_paper_readiness.py`;
- thin CLI:
  `scripts/build_us_equity_final_paper_readiness.py`;
- configuration:
  `configs/governance/us_v3_final_paper_readiness_v1.json`;
- schema:
  `schemas/us_equity_final_paper_readiness.schema.json`;
- contract tests:
  `tests/contracts/test_us_equity_final_paper_readiness.py`.

It does not modify `quant_shared`, BTC, CN, `app_factory.py`, shared schemas,
frontend entrypoints, paper/live runtime, broker adapters, OMS semantics, or
order submission.

## Invocation

Run only after the serialized US current-HEAD gate builder:

```powershell
py -3 scripts/build_us_equity_current_head_gate_rebuild.py --repo-root .
py -3 scripts/build_us_equity_final_paper_readiness.py --repo-root .
```

The second command may exit successfully with a blocked decision. Consumers
must read the report `decision`, root blockers, source HEAD, hashes and safety
flags; wrapper success is never readiness.

## Durable outputs

The G12 writer exclusively owns:

- `artifacts/us_equity_final_paper_readiness/runs/<run-id>/report.json`;
- `artifacts/us_equity_final_paper_readiness/runs/<run-id>/manifest.json`;
- `artifacts/us_equity_final_paper_readiness/latest/latest_pointer.json`.

The latest pointer advances only after report schema/hash validation succeeds.
Repository-relative paths are POSIX. The artifact is intentionally not a
paper-run or paper-queue command.

## Current decision contract

Current missing external/manual/natural-time prerequisites and the two open
engineering tickets yield `blocked_fail_closed_no_paper_no_live`:

- production PIT seven-file evidence: owner `data_steward`;
- 30 natural days and 252 distinct XNYS sessions: owner `natural_time`;
- metadata-only broker review: owner `paper_operations`;
- manual decision record: owner `architect`;
- paper durable-path resolver defect: owner `paper_runtime`;
- live submission-gate audit-path injection defect: owner `live_runtime`.

No unknown/unclassified blocker is permitted. All promotion, paper, live,
private, order, broker, withdraw, queue-write, demo, network, secret and
real-order flags remain false.

## Integrator verification

1. Validate the append-only producer handoff with
   `tools/agent_governance/handoff.py validate`.
2. Integrate the committed source/schema/config/script/test/ticket/doc
   deliverables listed in that envelope.
3. Rebuild G10 then G12 from the integration commit, in that order.
4. Validate the resulting G12 report schema, source HEAD, report/config/schema
   hashes, zero unclassified blockers and all-false safety flags.
5. Do not interpret a valid blocked packet or valid handoff as authorization to
   start paper/live.
