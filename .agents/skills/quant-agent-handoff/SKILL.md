---
name: quant-agent-handoff
description: Produce the required final handoff after a quant repository task. Use after architecture, data, research, implementation, testing, artifact, monitoring, or gate work to record ownership, evidence, conflicts, test results, and remaining fail-closed states.
---

# Quant Agent Handoff

Before finishing, report:

- role, base commit, final HEAD, and declared touch set;
- files changed and the responsibility boundary of each change;
- initial dirty paths, overlapping changes found, and how they were preserved;
- playbooks read, selected pitfall IDs, and catalog hash;
- exact tests or builders run, results, and material validation not run;
- artifact, manifest, ledger, replay, or report paths produced;
- schema or dependency-order effects;
- gate decision and every safety flag that remains false;
- unresolved blocker, owner, and next executable action.

For writer-to-writer delivery, a final chat response is not a durable handoff:

1. Commit the deliverable first.
2. Publish large data through `shared_data.py` and commit its manifest.
3. Create a separate append-only envelope under `.agent/handoffs/<ticket>/<event>.json` that references the deliverable commit and SHA-256 values.
4. Validate and commit the envelope. Consumers publish a separate acknowledgement or rejection event.

Use `quality_checked`, `research_ready`, `backtest_ready`, and `promotion_evidence_ready` precisely. Uncommitted files and worktree-private data paths are not deliverables.

Do not describe a partial, stale, fixture, research-only, or flat-sample result as promotion evidence. Do not hide failures behind a summary count.
